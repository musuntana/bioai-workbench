from __future__ import annotations

import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
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


    def test_running_child_log_is_visible_before_process_exits(self) -> None:
        """Readers should see flushed output while analysis is still running."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            marker = root / "child-started.flag"
            log_path = root / "run.log"
            cancellation = threading.Event()
            child_code = (
                "import pathlib, time; "
                "print('live-output-visible', flush=True); "
                "pathlib.Path('child-started.flag').touch(); "
                "time.sleep(10)"
            )
            with ThreadPoolExecutor(max_workers=1) as workers:
                task = workers.submit(
                    _run_bounded_process,
                    command=[sys.executable, "-u", "-c", child_code],
                    cwd=root,
                    environment={"PATH": ""},
                    log_path=log_path,
                    timeout_seconds=15,
                    max_log_bytes=512,
                    cancel_event=cancellation,
                )
                try:
                    started_by = time.monotonic() + 3
                    while not marker.exists() and time.monotonic() < started_by:
                        self.assertFalse(task.done(), "Child exited unexpectedly")
                        time.sleep(0.02)
                    self.assertTrue(marker.exists(), "Child never started")

                    visible_by = time.monotonic() + 1
                    while time.monotonic() < visible_by:
                        if log_path.is_file() and b"live-output-visible" in log_path.read_bytes():
                            break
                        time.sleep(0.02)
                    self.assertTrue(log_path.is_file())
                    self.assertIn(b"live-output-visible", log_path.read_bytes())
                    self.assertFalse(task.done(), "Log check must precede process exit")
                finally:
                    cancellation.set()
                return_code, timed_out, truncated = task.result(timeout=5)
                self.assertNotEqual(return_code, 0)
                self.assertFalse(timed_out)
                self.assertFalse(truncated)


if __name__ == "__main__":
    unittest.main()
