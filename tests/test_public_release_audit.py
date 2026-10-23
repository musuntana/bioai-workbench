from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_public_release.py"
SPEC = importlib.util.spec_from_file_location("audit_public_release", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


class PublicReleaseAuditTests(unittest.TestCase):
    def test_synthetic_source_has_no_configured_findings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "analysis.R").write_text(
                'metadata$sample_id <- c("control_1", "control_2")\n'
                'outdir <- "/tmp/synthetic-results"\n',
                encoding="utf-8",
            )
            self.assertEqual(AUDIT.scan_root(root), [])

    def test_reports_categories_without_echoing_sensitive_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            private_ip = ".".join(("10", "23", "4", "5"))
            credential_line = "api_" + 'key = "secret-value-not-for-output"'
            personal_path = "/" + "Users/alice/private-data"
            (root / "config.py").write_text(
                f'endpoint = "{private_ip}"\n'
                + credential_line + "\n"
                + f'cache = "{personal_path}"\n',
                encoding="utf-8",
            )
            findings = AUDIT.scan_root(root)
            categories = {category for _, _, category in findings}
            self.assertIn("private_ipv4", categories)
            self.assertIn("credential_assignment", categories)
            self.assertIn("personal_or_data_absolute_path", categories)
            self.assertNotIn("secret-value-not-for-output", repr(findings))
            self.assertNotIn("/" + "Users/alice/private-data", repr(findings))

    def test_scans_markdown_and_text_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            personal_path = "/" + "Users/alice/private-notes"
            (root / "README.md").write_text(
                f"Example configuration path: {personal_path}\\n",
                encoding="utf-8",
            )
            findings = AUDIT.scan_root(root)
            self.assertIn(
                ("README.md", 1, "personal_or_data_absolute_path"),
                findings,
            )

    def test_scans_html_and_javascript_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            private_path = "/" + "Users/alice/private-config"
            (root / "index.html").write_text(
                f'<script>const config = "{private_path}";</script>\n',
                encoding="utf-8",
            )
            findings = AUDIT.scan_root(root)
            self.assertIn(
                ("index.html", 1, "personal_or_data_absolute_path"),
                findings,
            )

    def test_flags_prohibited_data_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            private_dir = root / "data" / "private"
            private_dir.mkdir(parents=True)
            (private_dir / "notes.txt").write_text("synthetic placeholder", encoding="utf-8")
            findings = AUDIT.scan_root(root)
            self.assertIn(
                ("data/private/notes.txt", 0, "prohibited_data_directory"),
                findings,
            )


    def test_scans_source_code_under_artifacts_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "artifacts"
            source_dir.mkdir()
            private_path = "/" + "Users/alice/private-config"
            (source_dir / "manifest.py").write_text(
                f'cache_path = "{private_path}"\\n',
                encoding="utf-8",
            )
            findings = AUDIT.scan_root(root)
            self.assertIn(
                ("artifacts/manifest.py", 1, "personal_or_data_absolute_path"),
                findings,
            )


if __name__ == "__main__":
    unittest.main()
