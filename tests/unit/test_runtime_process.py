from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from runtime.manager import _run_bounded_process


class BoundedProcessTests(unittest.TestCase):
    def test_log_output_is_capped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "run.log"
            command = [
                sys.executable,
                "-c",
                "print('x' * 20000)",
            ]
            code, timed_out, truncated = _run_bounded_process(
                command=command,
                cwd=Path(temp_dir),
                environment={"PATH": ""},
                log_path=log_path,
                timeout_seconds=5,
                max_log_bytes=128,
            )
            self.assertEqual(code, 0)
            self.assertFalse(timed_out)
            self.assertTrue(truncated)
            self.assertLessEqual(log_path.stat().st_size, 128)

    def test_timeout_kills_child_that_keeps_stdout_open(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "run.log"
            child_code = "import time; time.sleep(10)"
            parent_code = (
                "import subprocess, sys; "
                "subprocess.Popen([sys.executable, '-c', " + repr(child_code) + "]); "
                "print('parent exited')"
            )
            command = [sys.executable, "-c", parent_code]
            code, timed_out, _ = _run_bounded_process(
                command=command,
                cwd=Path(temp_dir),
                environment={"PATH": ""},
                log_path=log_path,
                timeout_seconds=1,
                max_log_bytes=128,
            )
            self.assertTrue(timed_out)
            self.assertEqual(code, 0)

    def test_timeout_still_applies_after_process_closes_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "run.log"
            command = [
                sys.executable,
                "-c",
                "import os, time; os.close(1); os.close(2); time.sleep(10)",
            ]
            code, timed_out, _ = _run_bounded_process(
                command=command,
                cwd=Path(temp_dir),
                environment={"PATH": ""},
                log_path=log_path,
                timeout_seconds=1,
                max_log_bytes=128,
            )
            self.assertTrue(timed_out)
            self.assertNotEqual(code, 0)

    def test_long_running_process_is_terminated(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "run.log"
            command = [sys.executable, "-c", "import time; time.sleep(5)"]
            code, timed_out, _ = _run_bounded_process(
                command=command,
                cwd=Path(temp_dir),
                environment={"PATH": ""},
                log_path=log_path,
                timeout_seconds=1,
                max_log_bytes=128,
            )
            self.assertTrue(timed_out)
            self.assertNotEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
