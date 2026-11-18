import os
import sys
import time
import unittest
from pathlib import Path

from core_support import CoreCase
from factory.process import run_process


class ProcessTests(CoreCase):
    def test_timeout_kills_descendants(self):
        marker = self.tmp / "alive"
        code = ("import subprocess,sys,time;"
                f"subprocess.Popen([sys.executable,'-c',\"import time,pathlib\\nfor i in range(50):\\n time.sleep(.1)\\n pathlib.Path({str(marker)!r}).write_text(str(i))\"]);"
                "time.sleep(30)")
        r = run_process([sys.executable, "-c", code], self.tmp, 1, self.tmp / "log")
        self.assertTrue(r.timed_out)
        time.sleep(0.6)
        a = marker.read_text() if marker.exists() else ""
        time.sleep(0.4)
        self.assertEqual(a, marker.read_text() if marker.exists() else "")  # child no longer writing

    def test_stdin_from_file_and_no_shell(self):
        r = run_process([sys.executable, "-c", "import sys;print(sys.stdin.read().upper())"], self.tmp, 10,
                        self.tmp / "o.log", stdin_text="hi; echo $HOME")
        self.assertEqual(r.returncode, 0)
        self.assertEqual((self.tmp / "o.log").read_text().strip(), "HI; ECHO $HOME")

    def test_launch_error(self):
        r = run_process(["/nonexistent/bin"], self.tmp, 5, self.tmp / "l.log")
        self.assertEqual(r.returncode, 127)
        self.assertTrue(r.launch_error)


if __name__ == "__main__":
    unittest.main()
