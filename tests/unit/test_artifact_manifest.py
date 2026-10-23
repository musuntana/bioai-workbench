from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from artifacts.manifest import MANIFEST_NAME, build_artifact_manifest, write_artifact_manifest


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
