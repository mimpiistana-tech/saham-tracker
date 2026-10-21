import os
import tempfile
import unittest
from unittest.mock import patch
from paper_storage import storage_health

class StorageGateTests(unittest.TestCase):
    def test_missing_configuration_is_closed(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(storage_health()["ready"])
    def test_regular_directory_is_not_a_mount(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {"AUTO_PAPER_DB_PATH": folder+"/paper.db",
                                         "AUTO_PAPER_DISK_MOUNT": folder}):
                self.assertFalse(storage_health()["ready"])
                self.assertEqual(storage_health()["reason"], "persistent_disk_not_mounted")
    def test_escape_mount_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {"AUTO_PAPER_DB_PATH": folder+"/../escape.db",
                                         "AUTO_PAPER_DISK_MOUNT": folder}):
                self.assertFalse(storage_health()["ready"])
                self.assertEqual(storage_health()["reason"], "journal_outside_durable_disk")

if __name__ == "__main__":
    unittest.main()
