from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.schemas import RunRequest
from runtime.config import PROJECT_ROOT, RuntimeConfig
from runtime.manager import RunManager

OUTPUTS = (
    "differential_expression_all.csv",
    "differential_expression_significant.csv",
    "run_manifest.tsv",
    "session_info.txt",
)


def write_fake_rscript(bin_dir: Path, *, create_outputs: bool) -> None:
    """Create a deterministic stand-in for Rscript to exercise the Python runtime."""
    executable = bin_dir / "Rscript"
    lines = [
        "#!/usr/bin/env python3",
        "import pathlib",
        "import sys",
        "args = sys.argv[1:]",
        "outdir = pathlib.Path(args[args.index('--outdir') + 1])",
        f"create_outputs = {create_outputs!r}",
        "if create_outputs:",
        "    for name in " + repr(OUTPUTS) + ":",
        "        (outdir / name).write_text('synthetic artifact\\n', encoding='utf-8')",
        "print('synthetic fake Rscript completed')",
        "",
    ]
    executable.write_text("\n".join(lines), encoding="utf-8")
    executable.chmod(0o755)


class RuntimeLifecycleTests(unittest.TestCase):
    def _run_fake_workflow(
        self, root: Path, *, create_outputs: bool
    ) -> tuple[RunManager, str]:
        input_root = root / "inputs"
        input_root.mkdir()
        (input_root / "counts.csv").write_text(
            "gene_id,control_1,control_2,treatment_1,treatment_2\n"
            "gene_1,10,12,20,22\n",
            encoding="utf-8",
        )
        (input_root / "metadata.csv").write_text(
            "sample_id,condition\n"
            "control_1,control\n"
            "control_2,control\n"
            "treatment_1,treatment\n"
            "treatment_2,treatment\n",
            encoding="utf-8",
        )

        bin_dir = root / "bin"
        bin_dir.mkdir()
        write_fake_rscript(bin_dir, create_outputs=create_outputs)

        config = RuntimeConfig(
            project_root=PROJECT_ROOT,
            input_root=input_root,
            runs_root=root / "runs",
            max_run_seconds=5,
            max_log_bytes=4096,
            max_concurrent_runs=1,
        )
        manager = RunManager(config=config)
        request = RunRequest(counts_file="counts.csv", metadata_file="metadata.csv")
        path = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")

        with patch.dict(os.environ, {"PATH": path}):
            record = manager.create_run(request)
            manager.execute(record["run_id"], request.model_dump())

        return manager, record["run_id"]

    def test_successful_workflow_persists_state_and_artifact_checksums(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager, run_id = self._run_fake_workflow(
                Path(temp_dir), create_outputs=True
            )

            status = manager.store.get(run_id)
            self.assertEqual(status["status"], "succeeded")
            self.assertEqual(status["parameters"]["counts_file"], "counts.csv")
            self.assertEqual(status["parameters"]["metadata_file"], "metadata.csv")
            self.assertEqual(status["parameters"]["alpha"], 0.05)
            self.assertEqual(status["artifact_count"], len(OUTPUTS))
            artifacts = manager.get_artifacts(run_id)
            self.assertEqual({item["path"] for item in artifacts}, set(OUTPUTS))
            self.assertTrue(all(len(item["sha256"]) == 64 for item in artifacts))
            log, truncated = manager.get_log(run_id)
            self.assertIn("synthetic fake Rscript completed", log)
            self.assertFalse(truncated)


    def test_rerun_uses_original_verified_snapshots_after_inputs_change(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manager, source_run_id = self._run_fake_workflow(root, create_outputs=True)
            source_dir = manager.store.run_dir(source_run_id)
            source_counts = (source_dir / "tmp" / "counts.csv").read_bytes()
            source_metadata = (source_dir / "tmp" / "metadata.csv").read_bytes()
            source_workflow = (source_dir / "tmp" / "workflow.R").read_bytes()
            original_status = manager.store.get(source_run_id)

            (root / "inputs" / "counts.csv").write_text(
                "gene_id,control_1,control_2,treatment_1,treatment_2\ngene_1,999,999,999,999\n",
                encoding="utf-8",
            )
            rerun = manager.create_rerun(source_run_id)
            self.assertEqual(rerun["parent_run_id"], source_run_id)
            self.assertEqual(rerun["root_run_id"], source_run_id)
            self.assertEqual(rerun["attempt"], 2)

            bin_dir = root / "bin"
            path = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
            with patch.dict(os.environ, {"PATH": path}):
                manager.execute(
                    rerun["run_id"],
                    {"workflow_id": rerun["workflow_id"], **rerun["parameters"]},
                    source_run_id=source_run_id,
                )

            status = manager.store.get(rerun["run_id"])
            rerun_dir = manager.store.run_dir(rerun["run_id"])
            self.assertEqual(status["status"], "succeeded")
            self.assertEqual((rerun_dir / "tmp" / "counts.csv").read_bytes(), source_counts)
            self.assertEqual((rerun_dir / "tmp" / "metadata.csv").read_bytes(), source_metadata)
            self.assertEqual((rerun_dir / "tmp" / "workflow.R").read_bytes(), source_workflow)
            self.assertEqual(status["input_provenance"], original_status["input_provenance"])
            self.assertEqual(
                status["environment_provenance"]["workflow_sha256"],
                original_status["environment_provenance"]["workflow_sha256"],
            )

    def test_rerun_refuses_tampered_snapshots_and_active_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manager, source_run_id = self._run_fake_workflow(root, create_outputs=True)
            source_dir = manager.store.run_dir(source_run_id)
            (source_dir / "tmp" / "counts.csv").write_text("tampered\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "checksum"):
                manager.create_rerun(source_run_id)

            active_id = "b" * 32
            manager.store.create(active_id, "deseq2-basic")
            with self.assertRaisesRegex(ValueError, "completed"):
                manager.create_rerun(active_id)

    def test_zero_exit_without_required_outputs_is_a_failed_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager, run_id = self._run_fake_workflow(
                Path(temp_dir), create_outputs=False
            )

            status = manager.store.get(run_id)
            self.assertEqual(status["status"], "failed")
            self.assertEqual(status["exit_code"], 1)
            self.assertIn("required output artifacts are missing", status["error_message"])
            log, _ = manager.get_log(run_id)
            self.assertIn("Missing expected workflow outputs", log)


if __name__ == "__main__":
    unittest.main()
