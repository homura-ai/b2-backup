# b2-backup settings. Copy to ~/.config/b2-backup/config.sh and edit.
# This file is sourced by bash; arrays use bash syntax. No secrets here:
# B2 keys go in B2_ENV_FILE and the restic password in RESTIC_PASSWORD_FILE.

RESTIC_REPOSITORY=b2:YOUR-BUCKET:YOUR-HOST
# B2_ENV_FILE="$HOME/.config/b2-backup/b2.env"          # B2_ACCOUNT_ID=... B2_ACCOUNT_KEY=...
# RESTIC_PASSWORD_FILE="$HOME/.config/b2-backup/restic-password"
# BACKUP_HOST=laptop
# BACKUP_TAG=auto

BACKUP_PATHS=("$HOME/code" "$HOME/.config/systemd/user" "$HOME/.local/bin")
# Added only when they exist (for example git bundles of unpushed work).
BACKUP_OPTIONAL_PATHS=("$HOME/rescue")

# Machine-specific excludes: patterns or absolute paths. Examples:
EXTRA_EXCLUDES=(
    "$HOME/.snapshots"
    # "$HOME/code/some-repo/**/release"
)

# Databases that rewrite most pages often: back up a daily consistent copy
# (b2-backup dbcopy) instead of the live file. Example for T3 Code:
# SQLITE_COPIES=("$HOME/.t3/userdata/statev2.sqlite")

# Restored and compared once after the first successful backup.
# VERIFY_FILE="$HOME/code/README.md"

# Cache and build folders, matched by name anywhere (default list in b2-backup).
# Secret excludes are fixed and cannot be removed here.
# BULK_EXCLUDES=(node_modules .venv venv dist target .next .turbo build .cache __pycache__)

# Retention (restic keeps the union of these groups, not the sum).
# KEEP_ARGS=(--keep-last 36 --keep-hourly 48 --keep-daily 14 --keep-weekly 8)

# Any command that takes a title and a body. Default: notify-send.
# NOTIFY_CMD=(notify-send -a Backup -u critical)
