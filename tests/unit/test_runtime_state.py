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
            created = store.create(
                run_id,
                "deseq2-basic",
                parameters={
                    "counts_file": "demo/counts.csv",
                    "metadata_file": "demo/metadata.csv",
                    "alpha": 0.05,
                },
            )
            self.assertEqual(created["status"], "queued")
            self.assertEqual(created["parameters"]["alpha"], 0.05)
            self.assertEqual(store.get(run_id)["parameters"]["counts_file"], "demo/counts.csv")
            self.assertIsNone(created["started_at"])

            updated = store.update(
                run_id, status="running", started_at="2026-10-23T00:00:00+00:00"
            )
            self.assertEqual(updated["status"], "running")
            self.assertEqual(store.get(run_id)["status"], "running")
            self.assertTrue((Path(temp_dir) / run_id / "run.json").is_file())

    def test_run_history_filters_sorts_and_paginates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = RunStore(root)
            created = [
                store.create("a" * 32, "deseq2-basic"),
                store.create("b" * 32, "deseq2-basic"),
                store.create("c" * 32, "deseq2-basic"),
            ]
            store.update("a" * 32, status="failed", finished_at="2026-10-23T00:00:00+00:00")
            store.update(
                "b" * 32, status="succeeded", finished_at="2026-10-23T00:01:00+00:00"
            )

            corrupt_dir = root / ("d" * 32)
            corrupt_dir.mkdir()
            (corrupt_dir / "run.json").write_text("{broken", encoding="utf-8")

            expected = sorted(
                [store.get(record["run_id"]) for record in created],
                key=lambda record: (record["created_at"], record["run_id"]),
                reverse=True,
            )
            first_page = store.list_runs(limit=2, offset=0)
            second_page = store.list_runs(limit=2, offset=2)
            succeeded = store.list_runs(status="succeeded")

            self.assertEqual(first_page["total"], 3)
            self.assertEqual(
                [record["run_id"] for record in first_page["runs"]],
                [record["run_id"] for record in expected[:2]],
            )
            self.assertEqual(
                [record["run_id"] for record in second_page["runs"]],
                [record["run_id"] for record in expected[2:]],
            )
            self.assertEqual(succeeded["total"], 1)
            self.assertEqual(succeeded["runs"][0]["run_id"], "b" * 32)

    def test_run_history_rejects_invalid_pagination_and_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = RunStore(Path(temp_dir))
            for kwargs in (
                {"limit": 0},
                {"limit": 101},
                {"offset": -1},
                {"status": "unknown"},
            ):
                with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                    store.list_runs(**kwargs)

    def test_run_lineage_counts_attempts_and_enforces_family_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = RunStore(Path(temp_dir))
            root_id = "a" * 32
            store.create(root_id, "deseq2-basic")
            second = store.create(
                "b" * 32,
                "deseq2-basic",
                parent_run_id=root_id,
                root_run_id=root_id,
                max_family_attempts=2,
            )
            self.assertEqual(second["attempt"], 2)
            self.assertEqual(store.count_runs_in_family(root_id), 2)
            with self.assertRaisesRegex(ValueError, "maximum number of attempts"):
                store.create(
                    "c" * 32,
                    "deseq2-basic",
                    parent_run_id=root_id,
                    root_run_id=root_id,
                    max_family_attempts=2,
                )

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
