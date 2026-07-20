from __future__ import annotations

import json
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from d365opps.config import get_settings
from d365opps.forensics import json_default, sha256_file


class OracleBundleBuilder:
    BANNED_SEGMENTS = {
        "node_modules",
        ".next",
        ".pytest_cache",
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        "bundle_root",
        ".turbo",
        ".git",
    }
    REQUIRED_FILES = [
        "README.md",
        "AGENTS.md",
        "CODEOWNERS",
        ".gitattributes",
        "docs/for-oracle-to-read.md",
        "docs/architecture.md",
        "docs/agent-handoff.md",
        "docs/verification.md",
        "docs/export-policy.md",
        "docs/metric-catalog.md",
        "docs/operator-guide.md",
        "docs/verification-operator-guide.md",
        "harness/agent-native-repo-harness-map.json",
        "harness/agent-native-repo-harness-map.schema.json",
        "harness/agent-native-repo-harness-map.notes.md",
        "src/d365opps/pitchability.py",
        "src/d365opps/pipeline.py",
        "src/d365opps/verification.py",
        "src/d365opps/metric_catalog.py",
        "src/d365opps/oracle_instructions.py",
        "src/d365opps/source_universe.py",
        "src/d365opps/data/source_pack.json",
        "src/d365opps/data/source_family_catalog.json",
        "src/d365opps/data/source_platform_fingerprints.json",
        "src/d365opps/data/source_attempt_policies.json",
        "src/d365opps/data/source_universe_registry.jsonl",
        "src/d365opps/data/retrieval_rules.json",
        "tests/test_pitchability_truth.py",
        "tests/test_verification.py",
        "artifacts/runs/latest-live-public/summary.md",
        "artifacts/runs/latest-live-public/run_verdict.md",
        "artifacts/runs/latest-live-public/realness_report.md",
        "artifacts/runs/latest-live-public/canonical_bundle_admissibility_report.md",
        "artifacts/runs/latest-live-public/cross_surface_truth_report.json",
        "artifacts/runs/latest-live-public/lead_funnel_report.md",
        "artifacts/runs/latest-live-public/metric_catalog.json",
        "artifacts/runs/latest-live-public/repo_harness_compliance_report.md",
        "artifacts/runs/latest-live-public/harness_schema_validation_report.json",
        "artifacts/runs/latest-live-public/dead_weight_audit.md",
        "artifacts/runs/latest-live-public/pitchability_report.md",
        "artifacts/runs/latest-live-public/before_after_recall_report.md",
        "artifacts/runs/latest-live-public/current_pipeline_truth_report.md",
        "artifacts/runs/latest-live-public/official_regression_truth_report.md",
        "artifacts/runs/latest-live-public/known_current_examples_report.md",
        "artifacts/runs/latest-live-public/source_gap_report.md",
        "artifacts/runs/latest-live-public/source_yield_matrix.json",
        "artifacts/runs/latest-live-public/lead_age_distribution.json",
        "artifacts/runs/latest-live-public/ui_truth_audit.md",
        "artifacts/runs/latest-live-public/bundle_lineage.json",
        "artifacts/runs/latest-live-public/truth_consistency_report.json",
        "artifacts/source_campaign/latest/source_universe_summary.md",
        "artifacts/source_campaign/latest/attempt_all_sources_report.md",
        "artifacts/source_campaign/latest/blocked_sources_report.md",
        "artifacts/source_campaign/latest/free_source_onboarding_guide.md",
        "artifacts/source_campaign/latest/source_productionization_report.md",
        "artifacts/source_campaign/latest/source_yield_matrix.json",
        "artifacts/source_campaign/latest/prime_hits_report.md",
        "artifacts/source_campaign/latest/potential_hits_report.md",
        "artifacts/source_campaign/latest/potential_hits_top12.json",
        "artifacts/source_campaign/latest/global_source_campaign_verdict.md",
        "artifacts/verification/latest-live-public/status.json",
        "artifacts/verification/latest-live-public/diagnostic_summary.json",
        "artifacts/verification/latest-live-public/dashboard_screenshots/capture_report.json",
    ]

    def __init__(self) -> None:
        self.settings = get_settings()
        self.repo_root = Path.cwd()
        self.oracle_root = self.settings.artifact_root / "oracle"
        self.latest_root = self.oracle_root / "latest"
        self.zip_path = self.oracle_root / "d365-opps-oracle-latest.zip"
        self.oracle_root.mkdir(parents=True, exist_ok=True)

    def build(self) -> dict[str, Any]:
        latest_verification = self.settings.artifact_root / "verification" / "latest-live-public"
        latest_accountability = self.settings.artifact_root / "runs" / "latest-live-public"
        latest_campaign = self.settings.artifact_root / "source_campaign" / "latest"
        admissibility_report = latest_accountability / "canonical_bundle_admissibility_report.json"
        if not latest_verification.exists() or not latest_accountability.exists():
            raise RuntimeError("No admissible live-public verification/accountability pointers exist for canonical Oracle packaging.")
        if not admissibility_report.exists():
            raise RuntimeError("Missing canonical bundle admissibility report for latest live-public run.")
        admissibility = json.loads(admissibility_report.read_text(encoding="utf-8"))
        if not admissibility.get("oracle_admissible"):
            raise RuntimeError("Latest live-public candidate is not Oracle-admissible; canonical bundle build refused.")
        if self.latest_root.exists():
            shutil.rmtree(self.latest_root)
        self.latest_root.mkdir(parents=True, exist_ok=True)

        copied = self._copy_selection(
            [
                (self.repo_root / "README.md", Path("README.md")),
                (self.repo_root / "AGENTS.md", Path("AGENTS.md")),
                (self.repo_root / "CODEOWNERS", Path("CODEOWNERS")),
                (self.repo_root / ".gitattributes", Path(".gitattributes")),
                (self.repo_root / "pyproject.toml", Path("pyproject.toml")),
                (self.repo_root / "compose.yaml", Path("compose.yaml")),
                (self.repo_root / "compose.live.yaml", Path("compose.live.yaml")),
                (self.repo_root / "compose.demo.yaml", Path("compose.demo.yaml")),
                (self.repo_root / "docs/architecture.md", Path("docs/architecture.md")),
                (self.repo_root / "docs/agent-handoff.md", Path("docs/agent-handoff.md")),
                (self.repo_root / "docs/verification.md", Path("docs/verification.md")),
                (self.repo_root / "docs/export-policy.md", Path("docs/export-policy.md")),
                (self.repo_root / "docs/metric-catalog.md", Path("docs/metric-catalog.md")),
                (self.repo_root / "docs/for-oracle-to-read.md", Path("docs/for-oracle-to-read.md")),
                (self.repo_root / "docs/operator-guide.md", Path("docs/operator-guide.md")),
                (self.repo_root / "docs/verification-operator-guide.md", Path("docs/verification-operator-guide.md")),
                (self.repo_root / "harness", Path("harness")),
                (self.repo_root / "src/d365opps", Path("src/d365opps")),
                (self.repo_root / "tests/test_pitchability_truth.py", Path("tests/test_pitchability_truth.py")),
                (self.repo_root / "tests/test_verification.py", Path("tests/test_verification.py")),
                (self.repo_root / "tests/fixtures", Path("tests/fixtures")),
                (latest_campaign, Path("artifacts/source_campaign/latest")),
                (latest_verification, Path("artifacts/verification/latest-live-public")),
                (latest_accountability, Path("artifacts/runs/latest-live-public")),
            ]
        )
        manifest = {
            "generated_at": datetime.now(UTC).isoformat(),
            "bundle_type": "oracle_debug_bundle_v1",
            "repo_root": str(self.repo_root),
            "artifact_root": str(self.settings.artifact_root),
            "oracle_zip_path": str(self.zip_path),
            "included_paths": [item["path"] for item in copied],
            "excluded_patterns": sorted(self.BANNED_SEGMENTS),
        }
        self._write_json(self.latest_root / "manifest.json", manifest)
        self._write_text(
            self.latest_root / "README.txt",
            "\n".join(
                [
                    "Canonical Oracle bundle for the D365 public-web opportunity engine.",
                    "",
                    "Contains the actual selected code, docs, tests, and latest accountability evidence.",
                    "Review docs/for-oracle-to-read.md first, then artifacts/runs/latest-live-public/summary.md.",
                ]
            )
            + "\n",
        )
        self._write_checksums(self.latest_root)
        if self.zip_path.exists():
            self.zip_path.unlink()
        self._zip_directory(self.latest_root, self.zip_path)
        self_check = self._verify_internal(self.latest_root, self.zip_path, include_zip_hash=False)
        self._write_json(self.latest_root / "bundle_self_check.json", self_check)
        self._write_checksums(self.latest_root)
        self._zip_directory(self.latest_root, self.zip_path)
        return {
            "bundle_path": str(self.latest_root),
            "zip_path": str(self.zip_path),
            "bundle_self_check_path": str(self.latest_root / "bundle_self_check.json"),
            "bundle_self_check": self._verify_internal(self.latest_root, self.zip_path),
        }

    def verify(self) -> dict[str, Any]:
        return self._verify_internal(self.latest_root, self.zip_path)

    def _copy_selection(self, mapping: list[tuple[Path, Path]]) -> list[dict[str, Any]]:
        copied: list[dict[str, Any]] = []
        for source, destination in mapping:
            if not source.exists():
                copied.append({"path": str(destination), "status": "missing_source"})
                continue
            target = self.latest_root / destination
            if source.is_dir():
                shutil.copytree(
                    source,
                    target,
                    dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns(*self.BANNED_SEGMENTS),
                )
                for path in sorted(target.rglob("*")):
                    if path.is_file():
                        copied.append({"path": str(path.relative_to(self.latest_root)), "status": "copied"})
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                copied.append({"path": str(destination), "status": "copied"})
        return copied

    def _verify_internal(self, bundle_root: Path, zip_path: Path, *, include_zip_hash: bool = True) -> dict[str, Any]:
        missing = [path for path in self.REQUIRED_FILES if not (bundle_root / path).exists()]
        banned_hits = sorted(
            {
                str(path.relative_to(bundle_root))
                for path in bundle_root.rglob("*")
                if any(segment in self.BANNED_SEGMENTS for segment in path.parts)
            }
        )
        capture_report_path = bundle_root / "artifacts/verification/latest-live-public/dashboard_screenshots/capture_report.json"
        screenshots_real = None
        if capture_report_path.exists():
            try:
                capture_report = json.loads(capture_report_path.read_text(encoding="utf-8"))
                screenshots_real = all(not row.get("placeholder_used", True) for row in capture_report)
            except json.JSONDecodeError:
                screenshots_real = False
        zip_entries: list[str] = []
        if zip_path.exists():
            with zipfile.ZipFile(zip_path, "r") as archive:
                zip_entries = sorted(archive.namelist())
        instructions_text = (bundle_root / "docs/for-oracle-to-read.md").read_text(encoding="utf-8") if (bundle_root / "docs/for-oracle-to-read.md").exists() else ""
        instructions_match = all(
            token in instructions_text
            for token in (
                "artifacts/runs/latest-live-public",
                "artifacts/verification/latest-live-public",
                "artifacts/oracle/d365-opps-oracle-latest.zip",
            )
        )
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "bundle_path": str(bundle_root),
            "zip_path": str(zip_path),
            "zip_sha256": sha256_file(zip_path) if include_zip_hash and zip_path.exists() else None,
            "required_files_present": len(missing) == 0,
            "missing_required_files": missing,
            "banned_junk_present": len(banned_hits) > 0,
            "banned_hits": banned_hits,
            "hashes_generated": (bundle_root / "checksums.sha256").exists(),
            "screenshots_real_if_capture_enabled": screenshots_real,
            "oracle_instructions_match_bundle": instructions_match,
            "zip_contains_actual_files": len(zip_entries) > 0 and "manifest.json" in zip_entries,
            "zip_entry_count": len(zip_entries),
            "status": "pass" if not missing and not banned_hits and instructions_match and zip_entries else "fail",
        }

    def _write_json(self, path: Path, payload: Any) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, default=json_default), encoding="utf-8")
        return path

    def _write_text(self, path: Path, payload: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
        return path

    def _write_checksums(self, root: Path) -> Path:
        target = root / "checksums.sha256"
        lines: list[str] = []
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path == target:
                continue
            lines.append(f"{sha256_file(path)}  {path.relative_to(root)}")
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return target

    def _zip_directory(self, source: Path, destination: Path) -> None:
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(source.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(source))
