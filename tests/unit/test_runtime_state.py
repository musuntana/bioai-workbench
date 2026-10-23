from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from runtime.state import RunStore


class RunStoreTests(unittest.TestCase):
    def test_run_state_is_persisted_and_updated(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = RunStore(Path(temp_dir))
            run_id = "c" * 32
            created = store.create(run_id, "deseq2-basic")
            self.assertEqual(created["status"], "queued")
            self.assertIsNone(created["started_at"])

            updated = store.update(
                run_id, status="running", started_at="2026-10-23T00:00:00+00:00"
            )
            self.assertEqual(updated["status"], "running")
            self.assertEqual(store.get(run_id)["status"], "running")
            self.assertTrue((Path(temp_dir) / run_id / "run.json").is_file())

    def test_invalid_run_id_and_unknown_state_fields_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = RunStore(Path(temp_dir))
            with self.assertRaises(ValueError):
                store.get("../outside")
            store.create("d" * 32, "deseq2-basic")
            with self.assertRaisesRegex(ValueError, "Unsupported run state field"):
                store.update("d" * 32, input_path="/private/input.csv")


if __name__ == "__main__":
    unittest.main()
