# b2-backup

Encrypted restic backups to Backblaze B2 (or any restic repository), run by
systemd user timers:

- `b2-backup backup`: hourly. Fixed secret excludes, cache and build excludes,
  `--one-file-system`, `--exclude-caches`, `--compression max`, a nonblocking lock
  (an overlapping run skips and exits 0), and a one-time restore check of `VERIFY_FILE`.
- `b2-backup prune`: weekly. `forget --prune` for this host and tag only, with
  `--max-unused unlimited --repack-cacheable-only`, so a prune downloads no pack data.
- `b2-backup check`: monthly `restic check --with-cache` (no `--read-data`).
- `b2-backup dbcopy`: daily consistent copies of live SQLite files listed in
  `SQLITE_COPIES`. Backups include the copies and exclude the live files.
- `b2-backup notify UNIT`: runs `NOTIFY_CMD` (default `notify-send`). Each unit's
  `OnFailure=` calls it through `b2-backup-notify@.service`.
- `--dry-run` (or `-n`, or `B2_BACKUP_DRY_RUN=1`) prints the commands without
  running them, in any position (`b2-backup prune --dry-run` is dry too). It takes
  no lock, reads no credentials and writes no state. Unknown options and extra
  arguments are refused before anything runs.
  `b2-backup show-config` prints the settings it has resolved.

All settings live in `~/.config/b2-backup/config.sh` (override the path with
`B2_BACKUP_CONFIG`). See `config.example.sh`.

## Status

**Working.** It is the generic form of a backup script that has saved hourly
snapshots to B2 on a daily-use laptop. This generic copy has not itself run
against B2. `python3 test_backup.py` runs 16 tests offline, with a stub restic
and a throwaway local restic repository. One of them backs up real fixture files
and checks that the secret and build files were left out (it is skipped when
restic is not installed).

## Dependencies

bash, `flock` (util-linux), restic ≥ 0.14 (for `--compression` and
`--repack-cacheable-only`), python3 (for `dbcopy` and the tests), systemd user
session, and `notify-send` unless you set `NOTIFY_CMD`.

## Install

```bash
mkdir -p ~/.local/bin ~/.config/systemd/user
install -m 700 b2-backup ~/.local/bin/b2-backup
mkdir -p ~/.config/b2-backup && chmod 700 ~/.config/b2-backup
cp -n config.example.sh ~/.config/b2-backup/config.sh     # then edit it
# Secrets, never in this repo (both files mode 600):
#   ~/.config/b2-backup/b2.env           B2_ACCOUNT_ID=...  B2_ACCOUNT_KEY=...
#   ~/.config/b2-backup/restic-password  one line
b2-backup --dry-run backup                      # check paths and excludes
# Create the repository once (same env the script uses):
( set -a; source ~/.config/b2-backup/b2.env; set +a
  export RESTIC_REPOSITORY=b2:YOUR-BUCKET:YOUR-HOST \
         RESTIC_PASSWORD_FILE=~/.config/b2-backup/restic-password
  restic init )
cp b2-backup*.service b2-backup*.timer ~/.config/systemd/user/
systemctl --user daemon-reload
b2-backup dbcopy                                # only if SQLITE_COPIES is set
b2-backup initial                               # first upload, no 20-minute timeout
systemctl --user enable --now b2-backup.timer b2-backup-prune.timer \
    b2-backup-check.timer b2-backup-dbcopy.timer
```

Until `dbcopy` has run once, a database in `SQLITE_COPIES` is in no snapshot:
the live file is always excluded and the copy does not exist yet.

**Moving from another backup script.** Disable the old timers before enabling
these. The two tools use different lock files, so nothing stops both from
uploading every hour, and both would run a prune. If you keep the same
repository, set `BACKUP_HOST` and `BACKUP_TAG` to the host and tag the old
script used, or the weekly prune will not apply retention to the older
snapshots. Put the old script's machine-specific paths and
excludes into `BACKUP_PATHS` / `EXTRA_EXCLUDES` and compare with
`b2-backup show-config` and `b2-backup --dry-run backup` first.

**Save the restic password somewhere off the machine.** Without it the backup
cannot be restored. B2 keys can be reissued, but the password cannot be
recovered from B2.

Restore to a separate directory, never over live files:

```bash
set -a; source ~/.config/b2-backup/b2.env; set +a
export RESTIC_REPOSITORY=b2:YOUR-BUCKET:YOUR-HOST RESTIC_PASSWORD_FILE=~/.config/b2-backup/restic-password
restic snapshots --host "$(hostname -s)" --tag auto
restic restore latest --host "$(hostname -s)" --tag auto --target ~/restic-restore
```

## Uninstall

```bash
systemctl --user disable --now b2-backup.timer b2-backup-prune.timer b2-backup-check.timer b2-backup-dbcopy.timer
rm ~/.config/systemd/user/b2-backup*.service ~/.config/systemd/user/b2-backup*.timer ~/.local/bin/b2-backup
systemctl --user daemon-reload
# Keep ~/.config/b2-backup until you no longer need to restore.
```

## Limits

- Excludes match by name. They are not a content scanner, so don't keep
  secrets in ordinary source files.
- `BULK_EXCLUDES` also drops any folder named `build`, `dist`, `target`, `cache`
  and so on, wherever it is, including hand-written source folders with those
  names. Override `BULK_EXCLUDES` in the config if that matters; the secret
  excludes cannot be overridden.
- B2 caps downloads and Class B calls. A daily prune once helped use up the
  cap, and backups failed with HTTP 403 `download_cap_exceeded` until the daily
  reset. That is why the prune now runs weekly and is cap-safe. Unused
  space is only freed when whole packs are unused, so the repository grows
  faster. If you need it smaller, run a full prune by hand when the cap allows.
- `check` does not read pack data, and the restore check covers one file, once.
- The notifier only reports. If `NOTIFY_CMD` fails, the failure is logged.
