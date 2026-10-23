from __future__ import annotations

import unittest
from pathlib import Path

from app.registry import get_workflow


ROOT = Path(__file__).resolve().parents[2]


class Deseq2WorkflowContractTests(unittest.TestCase):
    def test_registered_entrypoint_and_contract_files_exist(self) -> None:
        workflow = get_workflow("deseq2-basic")
        self.assertIsNotNone(workflow)
        assert workflow is not None
        self.assertTrue(workflow.entrypoint.is_file())
        self.assertTrue((ROOT / "workflows/deseq2/workflow.yaml").is_file())
        self.assertTrue((ROOT / "workflows/deseq2/README.md").is_file())

    def test_legacy_cli_delegates_to_canonical_entrypoint(self) -> None:
        wrapper = (ROOT / "scripts/run_deseq2.R").read_text(encoding="utf-8")
        canonical = workflow_source = (ROOT / "workflows/deseq2/run.R").read_text(encoding="utf-8")
        self.assertIn("workflows", wrapper)
        self.assertIn("deseq2", wrapper)
        self.assertIn("DESeq2::DESeq", canonical)
        self.assertIn(".Machine$integer.max", workflow_source)


if __name__ == "__main__":
    unittest.main()
