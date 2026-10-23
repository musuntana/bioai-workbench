"""Runtime environment provenance is allowlisted, bounded, and backward-compatible."""

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from app.run_compare import compare_runs
from runtime.environment import read_environment_versions
from runtime.state import RunStore


def test_manifest_versions_are_allowlisted_and_path_values_hidden():
    with TemporaryDirectory() as directory:
        manifest = Path(directory) / "run_manifest.tsv"
        manifest.write_text(
            "key\tvalue\n"
            "r_version\tR version 4.4.2 (2024-10-31)\n"
            "deseq2_version\t1.46.0\n"
            "workflow_version\t0.1.0\n"
            "bioconductor_version\t3.20\n"
            "counts_path\t/private/secret.csv\n"
            "r_version\t/home/secret\n",
            encoding="utf-8",
        )
        versions = read_environment_versions(manifest)
        assert versions["deseq2_version"] == "1.46.0"
        assert versions["r_version"].startswith("R version")
        assert versions["bioconductor_version"] == "3.20"
        assert "counts_path" not in versions
        assert "/" not in str(versions)
        assert len(versions) == 4


def test_unsafe_or_oversize_manifest_is_not_exposed():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        actual = root / "actual.tsv"
        actual.write_text("key\tvalue\nr_version\t4.4.2\n", encoding="utf-8")
        link = root / "link.tsv"
        link.symlink_to(actual)
        assert read_environment_versions(link) == {}
        actual.write_text("X" * 66000, encoding="utf-8")
        assert read_environment_versions(actual) == {}


def test_comparison_distinguishes_legacy_unknown_and_changed_workflows():
    with TemporaryDirectory() as directory:
        store = RunStore(Path(directory))
        a, b = "a" * 32, "b" * 32
        store.create(a, "deseq2-basic")
        store.create(b, "deseq2-basic")
        store.update(a, environment_provenance={
            "workflow_sha256": hashlib.sha256(b"first").hexdigest(),
            "deseq2_version": "1.44.0",
        })
        store.update(b, environment_provenance={
            "workflow_sha256": hashlib.sha256(b"second").hexdigest(),
        })
        manager = SimpleNamespace(store=store, get_artifacts=lambda _: [])
        env = {e["field"]: e for e in compare_runs(manager, a, b)["environment"]}
        assert env["workflow_sha256"]["same"] is False
        assert env["deseq2_version"]["same"] is None
