import os
import tempfile
import unittest
from unittest.mock import patch
import paper_disk_probe

class TestProbe(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=os.path.join(self.temp.name,"probe.sqlite3")
        self.env=patch.dict(os.environ,{"AUTO_PAPER_DB_PATH":self.path,"RENDER_GIT_COMMIT":"rev_a"})
        self.env.start()
        self.disk=patch("paper_disk_probe.storage_health",return_value={"ready":True,"reason":"mounted_disk_verified"})
        self.disk.start()
        paper_disk_probe._CHECKED=None
    def tearDown(self):
        paper_disk_probe._CHECKED=None
        self.disk.stop()
        self.env.stop()
        self.temp.cleanup()
    def test_write_reopen_and_revision_retention(self):
        a=paper_disk_probe.probe_database()
        self.assertTrue(a["write_verified"])
        self.assertFalse(a["retained_from_previous_process"])
        paper_disk_probe._CHECKED=None
        with patch.dict(os.environ,{"RENDER_GIT_COMMIT":"rev_b"}):
            b=paper_disk_probe.probe_database()
        self.assertTrue(b["write_verified"])
        self.assertTrue(b["retained_from_previous_process"])
        self.assertTrue(b["retained_across_code_deploy"])
    def test_fail_closed_without_mount(self):
        paper_disk_probe._CHECKED=None
        with patch("paper_disk_probe.storage_health",return_value={"ready":False,"reason":"not_mounted"}):
            result=paper_disk_probe.probe_database()
        self.assertFalse(result["write_verified"])

if __name__=="__main__":
    unittest.main()
