"""Offline tests: a temporary HOME, a stub restic and a local restic repository.

Never contacts B2, never reads real credentials and never sends a notification.
Run: python3 test_backup.py
"""
import fcntl
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).with_name('b2-backup')
RESTIC = shutil.which('restic')


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        cfg = self.home / '.config/b2-backup'
        cfg.mkdir(parents=True)
        (cfg / 'b2.env').write_text('B2_ACCOUNT_ID=fixture\nB2_ACCOUNT_KEY=fixture\n')
        self.db = self.home / 'app/state.sqlite'
        self.db.parent.mkdir()
        con = sqlite3.connect(self.db)
        con.execute('create table t (x)')
        con.execute("insert into t values ('fixture')")
        con.commit()
        con.close()
        self.config = cfg / 'config.sh'
        self.config.write_text(
            'RESTIC_REPOSITORY=b2:fixture-bucket:fixture\n'
            'BACKUP_HOST=testhost\n'
            'BACKUP_PATHS=("$HOME/code" "$HOME/.config/systemd/user")\n'
            'BACKUP_OPTIONAL_PATHS=("$HOME/git-bundles" "$HOME/missing")\n'
            'EXTRA_EXCLUDES=("$HOME/code/big")\n'
            f'SQLITE_COPIES=("{self.db}")\n'
            'NOTIFY_CMD=(notify-stub)\n')
        (self.home / 'git-bundles').mkdir()
        (self.home / 'bin').mkdir()
        for name in ('restic', 'notify-stub'):
            stub = self.home / 'bin' / name
            stub.write_text('#!/usr/bin/python3\nimport os,sys,json\n'
                            f'open(os.environ["CAPTURE"]+".{name}","w").write(json.dumps(sys.argv[1:]))\n'
                            'sys.exit(int(os.environ.get("FAKE_EXIT", "0")))\n')
            stub.chmod(0o700)
        self.env = {**os.environ, 'HOME': str(self.home),
                    'XDG_RUNTIME_DIR': str(self.home),
                    'CAPTURE': str(self.home / 'args'),
                    'PATH': str(self.home / 'bin') + ':' + os.environ['PATH']}
        for key in ('B2_BACKUP_CONFIG', 'B2_BACKUP_DRY_RUN', 'RESTIC_REPOSITORY'):
            self.env.pop(key, None)

    def run_script(self, *args):
        return subprocess.run(['bash', str(SCRIPT), *args], env=self.env,
                              capture_output=True, text=True)

    def captured(self, name='restic'):
        return json.loads((self.home / f'args.{name}').read_text())

    def test_backup_paths_and_excludes(self):
        (self.home / '.local/state/b2-backup/sqlite-copies').mkdir(parents=True)
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.captured()
        self.assertEqual(args[0], 'backup')
        for flag in ('--one-file-system', '--exclude-caches'):
            self.assertIn(flag, args)
        self.assertEqual(args[args.index('--tag') + 1], 'auto')
        self.assertEqual(args[args.index('--host') + 1], 'testhost')
        self.assertEqual(args[args.index('--compression') + 1], 'max')
        for item in ('*.env', '.env.*', '.ssh', '.credentials.json', 'auth.json',
                     '.npmrc', '.netrc', '.git-credentials', 'secrets', 'node_modules',
                     str(self.home / 'code/big'), str(self.db), f'{self.db}-*',
                     str(self.home / '.config/b2-backup/b2.env'),
                     str(self.home / '.local/state/b2-backup/sqlite-copies/*.tmp')):
            self.assertIn(item, args)
        self.assertEqual(args[-4:], [str(self.home / p) for p in
                         ('code', '.config/systemd/user', 'git-bundles',
                          '.local/state/b2-backup/sqlite-copies')])

    def test_dry_run_runs_nothing(self):
        result = self.run_script('--dry-run', 'backup')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('DRY-RUN: restic backup', result.stdout)
        self.assertFalse((self.home / 'args.restic').exists())
        self.assertFalse((self.home / '.local/state').exists())
        self.assertFalse((self.home / 'b2-backup.lock').exists())

    def test_dry_run_flag_after_the_mode_is_still_dry(self):
        for args in (('prune', '--dry-run'), ('check', '-n'), ('backup', '--dry-run')):
            result = self.run_script(*args)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('DRY-RUN: restic', result.stdout)
            self.assertFalse((self.home / 'args.restic').exists(), args)

    def test_unknown_option_and_extra_argument_refuse_before_restic(self):
        for args in (('prune', '--dryrun'), ('prune', 'now'), ('--force',)):
            result = self.run_script(*args)
            self.assertEqual(result.returncode, 2, args)
            self.assertFalse((self.home / 'args.restic').exists(), args)

    def test_bulk_excludes_can_be_overridden(self):
        with self.config.open('a') as f:
            f.write('BULK_EXCLUDES=(node_modules)\n')
        self.assertEqual(self.run_script().returncode, 0)
        args = self.captured()
        self.assertIn('node_modules', args)
        self.assertNotIn('build', args)
        self.assertIn('.ssh', args)   # secret excludes stay

    def test_dbcopy_refuses_two_databases_with_one_name(self):
        other = self.home / 'other/state.sqlite'
        other.parent.mkdir()
        shutil.copy(self.db, other)
        with self.config.open('a') as f:
            f.write(f'SQLITE_COPIES+=("{other}")\n')
        result = self.run_script('dbcopy')
        self.assertEqual(result.returncode, 2)
        self.assertIn('state.sqlite', result.stderr)

    def test_dry_run_without_config_uses_placeholder_repository(self):
        self.config.unlink()
        result = self.run_script('--dry-run', 'prune')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('forget --prune', result.stdout)

    def test_missing_repository_refuses(self):
        self.config.unlink()
        result = self.run_script('backup')
        self.assertEqual(result.returncode, 2)
        self.assertIn('set RESTIC_REPOSITORY', result.stderr)

    def test_concurrent_run_skips(self):
        with (self.home / 'b2-backup.lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.run_script()
        self.assertEqual(result.returncode, 0)
        self.assertIn('skipping', result.stdout)
        self.assertFalse((self.home / 'args.restic').exists())

    def test_failure_propagates_for_systemd_notification(self):
        self.env['FAKE_EXIT'] = '3'
        self.assertEqual(self.run_script().returncode, 3)

    def test_prune_is_cap_safe_and_scoped(self):
        self.assertEqual(self.run_script('prune').returncode, 0)
        self.assertEqual(self.captured(), [
            'forget', '--prune', '--host', 'testhost', '--tag', 'auto',
            '--keep-last', '36', '--keep-hourly', '48', '--keep-daily', '14',
            '--keep-weekly', '8', '--max-unused', 'unlimited', '--repack-cacheable-only'])

    def test_check_uses_cache_only(self):
        self.assertEqual(self.run_script('check').returncode, 0)
        self.assertEqual(self.captured(), ['check', '--with-cache'])

    def test_notify_uses_configured_command(self):
        self.assertEqual(self.run_script('notify', 'b2-backup.service').returncode, 0)
        title, body = self.captured('notify-stub')
        self.assertIn('testhost', title)
        self.assertIn('journalctl --user -u b2-backup.service', body)

    def test_dbcopy_makes_consistent_copy(self):
        self.assertEqual(self.run_script('dbcopy').returncode, 0)
        copy = self.home / '.local/state/b2-backup/sqlite-copies/state.sqlite'
        con = sqlite3.connect(copy)
        self.assertEqual(con.execute('select x from t').fetchall(), [('fixture',)])
        con.close()

    def test_verify_restores_once(self):
        target = self.home / 'code/keep.txt'
        target.parent.mkdir(parents=True)
        target.write_text('x\n')
        with self.config.open('a') as f:
            f.write(f'VERIFY_FILE="{target}"\n')
        # The stub restic restores nothing, so cmp must fail and no marker is written.
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.home / '.local/state/b2-backup/verified').exists())

    def test_real_restic_excludes_nested_secret_and_build_fixtures(self):
        if RESTIC is None:
            self.skipTest('restic not installed')
        (self.home / '.local/state/b2-backup/verified').parent.mkdir(parents=True)
        (self.home / '.local/state/b2-backup/verified').touch()
        self.assertEqual(self.run_script().returncode, 0)
        args = self.captured()
        excluded = ['code/project/.env', 'code/project/config.env',
                    'code/project/.env.local', 'code/project/.ssh/id_ed25519',
                    'code/project/credentials/password', 'code/big/blob',
                    'code/project/node_modules/pkg/index.js',
                    'code/project/.venv/bin/python', 'code/project/dist/out',
                    'code/old/.claude/settings.json', 'code/old/.cli-proxy-api/account.json']
        for name in excluded + ['code/project/keep.txt', '.config/systemd/user/x.timer']:
            p = self.home / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('fixture, no real credentials\n')
        env = {**os.environ, 'RESTIC_REPOSITORY': str(self.home / 'repo'),
               'RESTIC_PASSWORD': 'throwaway-local-test-password',
               'RESTIC_CACHE_DIR': str(self.home / 'restic-cache')}
        env.pop('RESTIC_PASSWORD_FILE', None)
        for command in (['init'], args):
            subprocess.run([RESTIC, *command], env=env, check=True,
                           capture_output=True, text=True)
        result = subprocess.run([RESTIC, 'ls', '--json', 'latest'], env=env,
                                check=True, capture_output=True, text=True)
        saved = {line.get('path') for line in map(json.loads, result.stdout.splitlines())}
        self.assertIn(str(self.home / 'code/project/keep.txt'), saved)
        for name in excluded:
            self.assertNotIn(str(self.home / name), saved)


if __name__ == '__main__':
    unittest.main()
