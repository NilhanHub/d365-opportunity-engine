from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from d365opps.config import get_settings
from d365opps.models import JobRun


class OracleInstructionWriter:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.settings = get_settings()
        self.docs_root = Path("docs")
        self.docs_root.mkdir(parents=True, exist_ok=True)

    def refresh(self) -> dict[str, str]:
        latest_verification = Path("artifacts/verification/latest-live-public")
        latest_accountability = Path("artifacts/runs/latest-live-public")
        latest_source_campaign = Path("artifacts/source_campaign/latest")
        rejected_accountability = self._latest_rejected_candidate(self.settings.artifact_root / "runs" / "latest-candidate-rejected")
        latest_oracle_zip = Path("artifacts/oracle/d365-opps-oracle-latest.zip")
        latest_verification_text = latest_verification.as_posix()
        latest_accountability_text = latest_accountability.as_posix()
        latest_source_campaign_text = latest_source_campaign.as_posix()
        latest_oracle_zip_text = latest_oracle_zip.as_posix()
        latest_job = self.session.execute(select(JobRun).order_by(desc(JobRun.started_at)).limit(1)).scalar_one_or_none()
        latest_job_id = latest_job.id if latest_job else "none"
        accountability_snapshot = self._resolve_accountability_snapshot(latest_accountability)
        latest_run_id = accountability_snapshot.get("run_id") or latest_job_id
        latest_accountability_concrete = accountability_snapshot.get("snapshot_path") or latest_accountability_text
        latest_verification_concrete = self._resolve_verification_snapshot(latest_verification, latest_run_id)
        admissibility = self._load_json(latest_accountability / "canonical_bundle_admissibility_report.json")
        harness_validation = self._load_json(latest_accountability / "harness_schema_validation_report.json")
        current_truth = self._load_json(latest_accountability / "current_pipeline_truth_report.json")
        source_campaign_report = self._load_json(latest_source_campaign / "attempt_all_sources_report.json")
        source_campaign_verdict = self._load_json(latest_source_campaign / "global_source_campaign_verdict.json")
        rejected_admissibility = self._load_json(Path(rejected_accountability) / "canonical_bundle_admissibility_report.json") if rejected_accountability else {}
        previous_rejection_reason = ", ".join(rejected_admissibility.get("admissibility_fail_reasons") or []) if rejected_admissibility else "none"
        generated_at = datetime.now(UTC).isoformat()
        content = "\n".join(
            [
                "# For Oracle to Read",
                "",
                "## Current Objective",
                "Run the 3000+/1400-source global lawful public-source campaign from this repo, keep canonical truth and admissibility intact, and prove the actual breadth, attempt coverage, and blocker mix from artifacts alone.",
                "",
                "## Current Failure or Uncertainty",
                "- This pass is the 3000+/1400-source global attempt campaign, not another bounded baseline.",
                "- The main blocker is breadth and lawful attempt coverage, not missing accountability surfaces.",
                "- The repo must now prove exactly how many public source surfaces were built, attempted, blocked, and yielding in the latest global campaign.",
                "- Yield remains far below attempt breadth, so blocker proof by source family, country, and attempt outcome still matters.",
                "",
                "## Exact Reproduction",
                "1. Initialize the database with `d365-opps init-db`.",
                "2. Seed sources with `d365-opps seed-sources`.",
                "3. Run `d365-opps build-source-universe --target-size 3000`.",
                "4. Run `d365-opps attempt-source-universe --concurrency 120`.",
                "5. Run `d365-opps build-oracle-bundle`.",
                "6. Run `d365-opps refresh-oracle-instructions` so this file points at the latest source-campaign outputs.",
                "",
                "## Expected Behavior",
                "- Canonical latest pointers (`artifacts/runs/latest`, `artifacts/verification/latest`, and `artifacts/oracle/d365-opps-oracle-latest.zip`) only advance from an admissible official-public live run.",
                "- The latest source campaign builds and attempts a genuinely broad public source universe, not a narrow bounded subset.",
                "- Campaign artifacts must show exact family, country, and blocker distributions for every attempted surface.",
                "- Canonical Oracle packaging must include the latest source-campaign artifacts alongside the live/public admissibility surfaces.",
                "",
                "## Campaign Acceptance Thresholds",
                "- `source_universe_total >= 3000`.",
                "- `attempted_source_surfaces == source_universe_total`.",
                "- Every attempted surface must emit an explicit outcome and blocker proof when it does not yield.",
                "- Blocker categories must include at least CAPTCHA, robots, policy/terms, auth, network, rate-limit, parser failure, unsupported content, and invalid/removed source states when observed.",
                "",
                "## Actual Behavior",
                f"- Latest admissibility verdict: `{'admissible' if admissibility.get('oracle_admissible') else 'rejected'}`.",
                f"- Previous canonical/latest candidate rejection reasons: `{previous_rejection_reason}`.",
                f"- Harness schema status: `{harness_validation.get('status', 'unknown')}`.",
                f"- Current retained D365 count: `{current_truth.get('retained_d365_records', 'unknown')}`; seller-ready bid-now: `{current_truth.get('current_bid_now_leads', 'unknown')}`; seller-ready pre-position: `{current_truth.get('current_pre_position_leads', 'unknown')}`; production-ready public no-auth sources: `{current_truth.get('production_ready_public_no_auth_sources', 'unknown')}`.",
                f"- Latest source campaign universe: `{source_campaign_report.get('source_universe_total', 'unknown')}`; attempted: `{source_campaign_report.get('attempted_source_surfaces', 'unknown')}`; successful: `{source_campaign_report.get('successful_attempted_sources', 'unknown')}`; docs-returning: `{source_campaign_report.get('sources_returning_docs', 'unknown')}`; production-ready public no-auth campaign sources: `{source_campaign_verdict.get('production_ready_public_no_auth_sources', 'unknown')}`.",
                "",
                "## Relevant Paths",
                "- `src/d365opps/pipeline.py`",
                "- `src/d365opps/source_universe.py`",
                "- `src/d365opps/retrieval.py`",
                "- `src/d365opps/ops.py`",
                "- `src/d365opps/diagnostics.py`",
                "- `src/d365opps/verification.py`",
                "- `src/d365opps/oracle_bundle.py`",
                "- `src/d365opps/exporters.py`",
                "- `src/d365opps/oracle_instructions.py`",
                "- `src/d365opps/pitchability.py`",
                "- `src/d365opps/metric_catalog.py`",
                "- `src/d365opps/sources/public_portals.py`",
                "- `src/d365opps/sources/global_sources.py`",
                "- `src/d365opps/sources/find_a_tender.py`",
                "- `src/d365opps/sources/ted.py`",
                "- `src/d365opps/data/source_pack.json`",
                "- `src/d365opps/data/retrieval_rules.json`",
                "- `docs/metric-catalog.md`",
                "- `docs/architecture.md`",
                "- `docs/agent-handoff.md`",
                "- `docs/verification.md`",
                "- `docs/export-policy.md`",
                "- `harness/agent-native-repo-harness-map.json`",
                "- `docs/verification-operator-guide.md`",
                "- `artifacts/source_campaign/latest`",
                "",
                "## Required Artifacts",
                f"- Latest job run id: `{latest_run_id}`",
                f"- Latest live-public verification bundle: `{latest_verification_text}`",
                f"- Latest verification snapshot: `{latest_verification_concrete}`",
                f"- Latest live-public accountability bundle: `{latest_accountability_text}`",
                f"- Latest accountability snapshot: `{latest_accountability_concrete}`",
                f"- Latest source campaign snapshot: `{latest_source_campaign_text}`",
                f"- Latest rejected candidate path: `{rejected_accountability}`",
                f"- Latest Oracle zip: `{latest_oracle_zip_text}`",
                "- Fresh `run_verdict.md`, `realness_report.md`, `canonical_bundle_admissibility_report.md`, `official_regression_truth_report.md`, `known_current_examples_report.md`, `source_productionization_report.md`, `source_gap_report.md`, `source_yield_matrix.json`, `lead_funnel_report.md`, `ui_truth_audit.md`, `repo_harness_compliance_report.md`, `harness_schema_validation_report.json`, `dead_weight_audit.md`, and `truth_consistency_report.json` from the latest live-public accountability run.",
                "- Fresh source-campaign artifacts: `source_universe_full.json`, `attempt_all_sources_report.json`, `blocked_sources_report.json`, `free_source_onboarding_guide.md`, `source_productionization_report.json`, `source_yield_matrix.json`, `prime_hits_report.json`, `potential_hits_report.json`, `potential_hits_top12.json`, and `global_source_campaign_verdict.json`.",
                "- Real screenshots under the latest live-public verification/accountability bundle; placeholders are disallowed for canonical latest.",
                "",
                "## Exact Oracle Bundle Recipe",
                "- Include: `README.md`, `pyproject.toml`, `compose*.yaml`.",
                "- Include: `AGENTS.md`, `CODEOWNERS`, `.gitattributes`.",
                "- Include: `docs/for-oracle-to-read.md`, `docs/operator-guide.md`, `docs/verification-operator-guide.md`, `docs/metric-catalog.md`, `docs/architecture.md`, `docs/agent-handoff.md`, `docs/verification.md`, `docs/export-policy.md`.",
                "- Include: `harness/**`.",
                "- Include: `src/d365opps/**`.",
                "- Include: `tests/test_pitchability_truth.py`, `tests/test_verification.py`, and `tests/fixtures/**` when present.",
                f"- Include: `{latest_verification_text}`.",
                f"- Include: `{latest_accountability_text}`.",
                f"- Include: `{latest_source_campaign_text}`.",
                f"- Emit one canonical zip at `{latest_oracle_zip_text}` with the actual selected files inside it.",
                "",
                "## Admissibility Gates",
                "- `run_kind` must be `live_public_baseline` or `live_public_expanded`.",
                "- `evidence_class` must be `official_public`.",
                "- No placeholder source names, placeholder domains, or fixture/demo records may appear in seller-ready outputs.",
                "- Real screenshots are required; placeholder screenshots reject the candidate.",
                "- Harness schema validation must pass with zero errors and zero template markers.",
                "- Official regression truth must pass required positive and negative cases.",
                "- Minimum live-public admissibility thresholds must pass, and the source-expansion release thresholds must either pass or emit exact blocker proof by source, lane, query family, lifecycle class, English sufficiency, and extraction completeness.",
                "",
                "## Sanitization Rules",
                "- Exclude `node_modules`, `.next`, browser caches, temp DB sidecars, `.pytest_cache`, Playwright caches, and recursive artifact junk.",
                "- Exclude blobs and DB dumps unless explicitly requested.",
                "- Redact tokens, API keys, Authorization/Cookie headers, and sensitive query parameters.",
                "",
                "## Acceptance Evidence Required",
                "- A fresh admissible live-public accountability run under `artifacts/runs/<timestamp>-accountability-<run-id>/` and synced to `artifacts/runs/latest-live-public/`.",
                "- A fresh admissible live-public verification bundle under `artifacts/verification/<run-id-or-timestamp>/` and synced to `artifacts/verification/latest-live-public/`.",
                "- `current_pipeline_truth_report`, `run_verdict`, `realness_report`, `canonical_bundle_admissibility_report`, `official_regression_truth_report`, `source_productionization_report`, `source_gap_report`, `source_yield_matrix`, `lead_funnel_report`, `ui_truth_audit`, and `repo_harness_compliance_report` all agree.",
                "- `artifacts/oracle/d365-opps-oracle-latest.zip` is rebuilt only from the admissible live-public pointers.",
                "",
                "## Known Suspects / Hypotheses",
                "- The default `var/d365opps.db` can still hold synthetic or debug residue; canonical latest must never derive from it unless the run is classified/admitted correctly.",
                "- Some official sources will still pass canaries but fail commercial thresholds within a bounded window; that must reject the canonical candidate rather than pretend success.",
                "- Placeholder screenshots or non-schema-valid harness files must reject canonical latest even if the pipeline itself fetched real records.",
                "",
                "## Recent Instrumentation Changes",
                "- Added canonical run admissibility, source authenticity gating, official-domain inventory, realness reporting, and class-specific latest pointers.",
                "- Added schema-valid harness validation and canonical Oracle build refusal when latest live-public evidence is inadmissible.",
                "- Added UI truth audit and placeholder screenshot rejection for canonical bundles.",
                "",
                "## Evidence Delta vs Prior Canonical Bundle",
                "- This pass expands the source universe and attempt ledger materially beyond the earlier bounded campaign.",
                "- The latest source campaign should show higher family-C official portal coverage, higher family-D hosted instance coverage, and a complete attempt ledger for every discovered surface.",
                "- The evidence delta is now measured in source-universe breadth, attempted surfaces, successful probes, docs-returning sources, and blocker distribution, in addition to retained/seller-ready yield.",
                "",
                "## Dead-Weight Deletions",
                "- Remove stale wrapper zips, recursive artifact junk, placeholder screenshots in canonical paths, and dead fixture/debug debris from canonical surfaces.",
                "",
                "## Harness Compliance Delta",
                "- The harness map must validate against the supplied April 14, 2026 schema exactly; minimum-shape placeholder maps are no longer accepted.",
                "",
                f"_Generated: {generated_at}_",
            ]
        )
        target = self.docs_root / "for-oracle-to-read.md"
        target.write_text(content + "\n", encoding="utf-8")
        return {
            "path": str(target),
            "latest_run_id": latest_run_id,
            "latest_verification": latest_verification_text,
            "latest_accountability": latest_accountability_text,
        }

    def _load_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _latest_rejected_candidate(self, root: Path) -> str:
        if not root.exists():
            return ""
        candidates = sorted([path for path in root.iterdir() if path.is_dir()], key=lambda path: path.name, reverse=True)
        return candidates[0].as_posix() if candidates else ""

    def _resolve_accountability_snapshot(self, latest_accountability: Path) -> dict[str, str]:
        if not latest_accountability.exists():
            return {}
        bundle_manifest = latest_accountability / "bundle-manifest.json"
        run_scope = latest_accountability / "run_scope_report.json"
        snapshot: dict[str, Any] = {}
        for candidate in (run_scope, bundle_manifest):
            if not candidate.exists():
                continue
            try:
                snapshot = json.loads(candidate.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if snapshot:
                break
        run_id = (
            snapshot.get("anchor_run_id")
            or snapshot.get("run_id")
            or snapshot.get("latest_run_id")
        )
        concrete = ""
        if run_id:
            matches = sorted(
                [
                    path
                    for path in (self.settings.artifact_root / "runs").glob(f"*-accountability-{run_id}")
                    if path.is_dir()
                ],
                reverse=True,
            )
            if matches:
                concrete = matches[0].as_posix()
        return {"run_id": str(run_id or ""), "snapshot_path": concrete}

    def _resolve_verification_snapshot(self, latest_verification: Path, latest_run_id: str) -> str:
        if not latest_verification.exists() or not latest_run_id or latest_run_id == "none":
            return latest_verification.as_posix()
        candidate = self.settings.artifact_root / "verification" / latest_run_id
        return candidate.as_posix() if candidate.exists() else latest_verification.as_posix()
