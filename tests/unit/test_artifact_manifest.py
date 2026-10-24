from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from artifacts.manifest import (
    MANIFEST_NAME,
    ArtifactManifestError,
    build_artifact_manifest,
    load_artifact_manifest,
    write_artifact_manifest,
)


class ArtifactManifestTests(unittest.TestCase):
    def test_manifest_records_relative_paths_sizes_and_sha256(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "outputs"
            output_dir.mkdir()
            artifact = output_dir / "nested" / "result.csv"
            artifact.parent.mkdir()
            artifact.write_text("gene_id,log2FoldChange\ngene_1,1.2\n", encoding="utf-8")

            manifest = write_artifact_manifest(
                output_dir, run_id="a" * 32, workflow_id="deseq2-basic"
            )
            self.assertEqual(manifest["artifacts"][0]["path"], "nested/result.csv")
            self.assertEqual(manifest["artifacts"][0]["size_bytes"], artifact.stat().st_size)
            self.assertEqual(len(manifest["artifacts"][0]["sha256"]), 64)
            self.assertTrue((output_dir / MANIFEST_NAME).is_file())

            serialized = json.dumps(manifest)
            self.assertNotIn(str(output_dir.resolve()), serialized)
            self.assertNotIn(MANIFEST_NAME, [item["path"] for item in manifest["artifacts"]])

    def test_load_manifest_checks_identity_and_on_disk_artifact_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "outputs"
            output_dir.mkdir()
            artifact = output_dir / "result.csv"
            artifact.write_text("synthetic result\\n", encoding="utf-8")
            manifest = write_artifact_manifest(
                output_dir, run_id="a" * 32, workflow_id="deseq2-basic"
            )

            loaded = load_artifact_manifest(
                output_dir, run_id="a" * 32, workflow_id="deseq2-basic"
            )

            self.assertEqual(loaded["artifacts"], manifest["artifacts"])
            self.assertEqual(loaded["run_id"], "a" * 32)

    def test_load_manifest_rejects_wrong_identity_unsafe_paths_and_bad_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "outputs"
            output_dir.mkdir()
            artifact = output_dir / "result.csv"
            artifact.write_text("synthetic result\\n", encoding="utf-8")
            write_artifact_manifest(
                output_dir, run_id="b" * 32, workflow_id="deseq2-basic"
            )
            manifest_path = output_dir / MANIFEST_NAME
            original = json.loads(manifest_path.read_text(encoding="utf-8"))

            invalid_manifests = []
            wrong_run = json.loads(json.dumps(original))
            wrong_run["run_id"] = "c" * 32
            invalid_manifests.append(wrong_run)
            unsafe_path = json.loads(json.dumps(original))
            unsafe_path["artifacts"][0]["path"] = "../outside.csv"
            invalid_manifests.append(unsafe_path)
            bad_hash = json.loads(json.dumps(original))
            bad_hash["artifacts"][0]["sha256"] = "not-a-sha256"
            invalid_manifests.append(bad_hash)
            duplicate = json.loads(json.dumps(original))
            duplicate["artifacts"].append(dict(duplicate["artifacts"][0]))
            invalid_manifests.append(duplicate)
            wrong_size = json.loads(json.dumps(original))
            wrong_size["artifacts"][0]["size_bytes"] += 1
            invalid_manifests.append(wrong_size)

            for invalid in invalid_manifests:
                with self.subTest(invalid=invalid):
                    manifest_path.write_text(json.dumps(invalid), encoding="utf-8")
                    with self.assertRaises(ArtifactManifestError):
                        load_artifact_manifest(
                            output_dir, run_id="b" * 32, workflow_id="deseq2-basic"
                        )

            manifest_path.write_text("{broken", encoding="utf-8")
            with self.assertRaises(ArtifactManifestError):
                load_artifact_manifest(
                    output_dir, run_id="b" * 32, workflow_id="deseq2-basic"
                )

    def test_load_manifest_rejects_same_size_content_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "outputs"
            output_dir.mkdir()
            artifact = output_dir / "result.csv"
            artifact.write_text("synthetic result\\n", encoding="utf-8")
            write_artifact_manifest(
                output_dir, run_id="e" * 32, workflow_id="deseq2-basic"
            )
            artifact.write_bytes(b"x" * artifact.stat().st_size)

            with self.assertRaises(ArtifactManifestError):
                load_artifact_manifest(
                    output_dir, run_id="e" * 32, workflow_id="deseq2-basic"
                )

    def test_load_manifest_rejects_missing_artifact_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "outputs"
            output_dir.mkdir()
            artifact = output_dir / "result.csv"
            artifact.write_text("synthetic result\\n", encoding="utf-8")
            write_artifact_manifest(
                output_dir, run_id="d" * 32, workflow_id="deseq2-basic"
            )
            artifact.unlink()

            with self.assertRaises(ArtifactManifestError):
                load_artifact_manifest(
                    output_dir, run_id="d" * 32, workflow_id="deseq2-basic"
                )

    def test_build_manifest_is_stable_for_same_artifact_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            (output_dir / "result.txt").write_text("synthetic", encoding="utf-8")
            first = build_artifact_manifest(
                output_dir, run_id="b" * 32, workflow_id="deseq2-basic"
            )
            second = build_artifact_manifest(
                output_dir, run_id="b" * 32, workflow_id="deseq2-basic"
            )
            self.assertEqual(first["artifacts"], second["artifacts"])


if __name__ == "__main__":
    unittest.main()
