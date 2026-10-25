"""Retention only runs after a successful dump and only affects automatic dump files."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.ops.db_backup import backup


class BackupRetentionTest(unittest.TestCase):
    def test_failure_preserves_backups_and_success_prunes_only_old_dumps(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            old = directory / "postgres_20000101T000000Z_old.dump"
            manual = directory / "manual.dump"
            for path in (old, manual):
                path.write_bytes(b"old archive")
                os.utime(path, (1, 1))
            with patch("scripts.ops.db_backup.container", side_effect=subprocess.CalledProcessError(1, "pg_dump")):
                with self.assertRaises(subprocess.CalledProcessError):
                    backup(directory / ".env", output_dir=directory, keep_days=14)
            self.assertTrue(old.exists())
            self.assertFalse(list(directory.glob("*.partial")))
            with patch("scripts.ops.db_backup.container", side_effect=lambda *args, **kwargs: kwargs["stdout"].write(b"new archive")):
                backup(directory / ".env", output_dir=directory, keep_days=14)
            self.assertFalse(old.exists())
            self.assertTrue(manual.exists())
            self.assertEqual(len(list(directory.glob("postgres_*.dump"))), 1)


if __name__ == "__main__":
    unittest.main()
