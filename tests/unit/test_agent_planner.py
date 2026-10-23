from __future__ import annotations

import unittest

from pydantic import ValidationError

from agent.planner import plan_task


class AgentPlannerTests(unittest.TestCase):
    def test_known_task_returns_validated_plan_requiring_approval(self) -> None:
        plan = plan_task(
            "differential_expression",
            {"counts_file": "counts.csv", "metadata_file": "metadata.csv"},
        )
        self.assertEqual(plan.workflow_id, "deseq2-basic")
        self.assertEqual(plan.status, "proposed")
        self.assertTrue(plan.requires_approval)
        self.assertEqual(plan.parameters["alpha"], 0.05)

    def test_unknown_task_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported task"):
            plan_task("run arbitrary shell", {})

    def test_path_traversal_is_rejected_during_planning(self) -> None:
        with self.assertRaises(ValidationError):
            plan_task(
                "deseq2",
                {"counts_file": "../private.csv", "metadata_file": "metadata.csv"},
            )

    def test_extra_parameters_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            plan_task(
                "deseq2",
                {
                    "counts_file": "counts.csv",
                    "metadata_file": "metadata.csv",
                    "command": "echo unsafe",
                },
            )


if __name__ == "__main__":
    unittest.main()
