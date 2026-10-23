from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from runtime.config import RuntimeConfig
from runtime.manager import RunManager


class RuntimeInputTests(unittest.TestCase):
    def test_input_resolver_accepts_files_inside_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_root = root / "inputs"
            input_root.mkdir()
            (input_root / "counts.csv").write_text("gene_id,s1,s2\ng1,1,2\n", encoding="utf-8")
            config = RuntimeConfig(
                project_root=root,
                input_root=input_root,
                runs_root=root / "runs",
            )
            manager = RunManager(config=config)
            self.assertEqual(manager._resolve_input("counts.csv"), (input_root / "counts.csv").resolve())

    def test_input_resolver_rejects_traversal_and_missing_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_root = root / "inputs"
            input_root.mkdir()
            config = RuntimeConfig(
                project_root=root,
                input_root=input_root,
                runs_root=root / "runs",
            )
            manager = RunManager(config=config)
            with self.assertRaisesRegex(ValueError, "not found"):
                manager._resolve_input("missing.csv")
            outside = root / "outside.csv"
            outside.write_text("synthetic", encoding="utf-8")
            (input_root / "escape.csv").symlink_to(outside)
            with self.assertRaisesRegex(ValueError, "remain under"):
                manager._resolve_input("escape.csv")


if __name__ == "__main__":
    unittest.main()
