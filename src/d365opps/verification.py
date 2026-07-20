from __future__ import annotations

import csv
import json
import shutil
import subprocess
import zipfile
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from d365opps.authenticity import (
    classify_domain,
    classify_row_authenticity,
    classify_source_authenticity,
    contains_placeholder_name,
    is_canonical_authentic_row,
    is_placeholder_host,
    normalize_host,
)
from d365opps.config import get_settings
from d365opps.diagnostics import DiagnosticsService
from d365opps.exporters import DatasetExporter
from d365opps.forensics import (
    config_presence_report,
    environment_presence_report,
    json_default,
    redact_mapping,
    sha256_file,
    write_checksums,
    write_placeholder_png,
)
from d365opps.metric_catalog import metric_catalog_payload
from d365opps.models import (
    CrawlRun,
    EvidenceRecord,
    ExclusionAudit,
    JobRun,
    JobType,
    MarketSignal,
    OpportunityCandidate,
    PipelineEvent,
    QueryExecution,
    RawDocument,
    SourceCanaryResult,
    SourceFetchEvent,
    SourceIssue,
    SourceRegistry,
    SourceStateTransition,
)
from d365opps.ops import OpsService
from d365opps.pitchability import (
    apply_evaluation_to_row,
    dedupe_key,
    evaluate_record,
    is_demo_record,
)


class VerificationService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.settings = get_settings()
        self.ops = OpsService(session)
        self.diagnostics = DiagnosticsService(session)
        self.exporter = DatasetExporter()
        self.root = self.settings.artifact_root / "verification"
        self.accountability_root = self.settings.artifact_root / "runs"
        self.root.mkdir(parents=True, exist_ok=True)
        self.accountability_root.mkdir(parents=True, exist_ok=True)

    def generate_bundle(
        self,
        *,
        run_id: str | None = None,
        include_blobs: bool = False,
        include_db_dump: bool = False,
    ) -> dict[str, Any]:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        target = self.root / (run_id or stamp)
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True, exist_ok=True)
        (target / "dashboard_screenshots").mkdir(parents=True, exist_ok=True)
        (target / "samples").mkdir(parents=True, exist_ok=True)

        overview = self.ops.overview()
        dataset_diagnosis = self.diagnostics.explain_zero()
        diagnostics = self.diagnostics.diagnostics_overview()
        latest_run = None
        if run_id:
            try:
                latest_run = self.ops.get_run(run_id)
            except KeyError:
                latest_run = None
        if latest_run is None:
            runs = self.ops.list_runs(limit=1, offset=0)["items"]
            latest_run = runs[0] if runs else None

        status = {
            "system_mode": overview["data_mode"],
            "demo_mode": overview["demo_mode"],
            "generated_at": datetime.now(UTC),
            "run_id": run_id,
            "latest_run_id": latest_run.get("id") if latest_run else None,
        }
        source_inventory = self.ops.list_sources(limit=2000, offset=0)["items"]
        run_scope = self._run_scope_report(latest_run["id"]) if latest_run else {
            "sources_touched_this_run": 0,
            "sources_succeeded_this_run": 0,
            "sources_yielding_real_records_this_run": 0,
            "sources_yielding_d365_records_this_run": 0,
            "sources_selected_for_run": [],
            "sources_actually_touched": [],
            "sources_with_successful_fetches": [],
            "sources_yielding_d365_records": [],
            "related_crawl_run_ids": [],
        }
        source_health = [
            {
                "id": row["id"],
                "name": row["name"],
                "enabled": row["enabled"],
                "operational_state": row["operational_state"],
                "yield_state": row["yield_state"],
                "forthcoming_state": row["forthcoming_state"],
                "last_successful_fetch": row["last_successful_fetch"],
                "last_attempted_fetch": row["last_attempted_fetch"],
                "recommended_fix": row["recommended_fix"],
                "source_trust": row["source_trust"],
            }
            for row in source_inventory
        ]
        source_readiness = diagnostics["source_readiness_mix"]
        pitchability = self._pitchability_report()
        source_gap = self._source_gap_report(source_inventory, run_scope=run_scope)
        truth_consistency = self._truth_consistency_report(
            overview=overview,
            dataset_diagnosis=dataset_diagnosis,
            source_inventory=source_inventory,
            run_scope=run_scope,
            pitchability=pitchability,
        )
        current_pipeline_truth = self._current_pipeline_truth_report(
            overview=overview,
            run_scope=run_scope,
            pitchability=pitchability,
            source_inventory=source_inventory,
            source_gap=source_gap,
            truth_consistency=truth_consistency,
        )
        lead_age_distribution = self._lead_age_distribution(pitchability["all_live_records"], as_of_utc=pitchability["as_of_utc"])
        source_yield_matrix = self._source_yield_matrix(
            source_inventory=source_inventory,
            run_scope=run_scope,
            pitchability=pitchability,
        )
        lead_funnel = self._lead_funnel_report(overview=overview, source_yield_matrix=source_yield_matrix)
        source_productionization = self._source_productionization_report(
            source_inventory=source_inventory,
            source_gap=source_gap,
            source_yield_matrix=source_yield_matrix,
            run_scope=run_scope,
        )
        official_regression_truth = self._official_regression_truth_report(as_of_utc=pitchability["as_of_utc"])
        known_current_examples = self._known_current_examples_report(official_regression_truth)
        bundle_lineage = self._bundle_lineage()
        cross_surface_truth = self._cross_surface_truth_report(
            overview=overview,
            pitchability=pitchability,
            current_pipeline_truth=current_pipeline_truth,
            source_yield_matrix=source_yield_matrix,
            run_scope=run_scope,
        )
        run_verdict = self._run_verdict(
            current_pipeline_truth=current_pipeline_truth,
            pitchability=pitchability,
            source_gap=source_gap,
        )
        harness_schema_validation = self._harness_schema_validation_report()
        repo_harness = self._repo_harness_compliance_report(harness_schema_validation)
        dead_weight = self._dead_weight_audit()
        removal_manifest = self._removal_manifest()
        source_pack_snapshot = json.loads(
            Path("src/d365opps/data/source_pack.json").read_text(encoding="utf-8")
        )

        files: list[Path] = []
        files.append(self._write_json(target / "status.json", status))
        files.append(self._write_json(target / "overview.json", overview))
        files.append(self._write_json(target / "diagnostic_summary.json", diagnostics))
        files.append(self._write_json(target / "dataset_diagnosis.json", dataset_diagnosis))
        if dataset_diagnosis["live_records"] == 0:
            files.append(self._write_json(target / "empty_dataset_explainer.json", dataset_diagnosis))
        files.append(self._write_json(target / "source_inventory.json", source_inventory))
        files.append(self._write_json(target / "source_health.json", source_health))
        files.append(self._write_json(target / "source_readiness.json", source_readiness))
        files.append(self._write_json(target / "run_scope_report.json", run_scope))
        files.append(self._write_json(target / "pitchability_report.json", pitchability))
        files.append(self._write_json(target / "source_gap_report.json", source_gap))
        files.append(self._write_json(target / "truth_consistency_report.json", truth_consistency))
        files.append(self._write_json(target / "current_pipeline_truth_report.json", current_pipeline_truth))
        files.append(self._write_json(target / "lead_age_distribution.json", lead_age_distribution))
        files.append(self._write_json(target / "source_yield_matrix.json", source_yield_matrix))
        files.append(self._write_json(target / "lead_funnel_report.json", lead_funnel))
        files.append(self._write_text(target / "lead_funnel_report.md", self._lead_funnel_markdown(lead_funnel)))
        files.append(self._write_json(target / "source_productionization_report.json", source_productionization))
        files.append(self._write_text(target / "source_productionization_report.md", self._source_productionization_markdown(source_productionization)))
        files.append(self._write_csv_samples(target / "funnel_by_source.csv", lead_funnel["by_source"]))
        files.append(self._write_json(target / "funnel_by_source.json", lead_funnel["by_source"]))
        files.append(self._write_csv_samples(target / "funnel_by_query_family.csv", lead_funnel["by_query_family"]))
        files.append(self._write_json(target / "funnel_by_query_family.json", lead_funnel["by_query_family"]))
        files.append(self._write_json(target / "official_regression_truth_report.json", official_regression_truth))
        files.append(self._write_text(target / "official_regression_truth_report.md", self._official_regression_truth_markdown(official_regression_truth)))
        files.append(self._write_json(target / "known_current_examples_report.json", known_current_examples))
        files.append(self._write_text(target / "known_current_examples_report.md", self._known_current_examples_markdown(known_current_examples)))
        files.append(self._write_json(target / "cross_surface_truth_report.json", cross_surface_truth))
        files.append(self._write_json(target / "metric_catalog.json", metric_catalog_payload()))
        files.append(self._write_json(target / "run_verdict.json", run_verdict))
        files.append(self._write_text(target / "run_verdict.md", self._run_verdict_markdown(run_verdict)))
        files.append(self._write_json(target / "harness_schema_validation_report.json", harness_schema_validation))
        files.append(self._write_json(target / "repo_harness_compliance_report.json", repo_harness))
        files.append(self._write_text(target / "repo_harness_compliance_report.md", self._repo_harness_compliance_markdown(repo_harness)))
        files.append(self._write_json(target / "dead_weight_audit.json", dead_weight))
        files.append(self._write_text(target / "dead_weight_audit.md", self._dead_weight_audit_markdown(dead_weight)))
        files.append(self._write_json(target / "removal_manifest.json", removal_manifest))
        files.append(self._write_json(target / "bundle_lineage.json", bundle_lineage))
        files.append(self._write_json(target / "runs.json", self.ops.list_runs(limit=500, offset=0)))
        files.append(self._write_json(target / "latest_run.json", latest_run or {}))
        files.append(self._write_json(target / "config.redacted.json", config_presence_report()))
        files.append(self._write_json(target / "environment.redacted.json", environment_presence_report()))
        files.append(self._write_json(target / "source_pack_snapshot.json", source_pack_snapshot))
        files.append(self._write_metrics(target / "metrics.prom"))

        files.append(self._write_ndjson(target / "source_state_transitions.ndjson", self._serialize_rows(select(SourceStateTransition).order_by(desc(SourceStateTransition.timestamp)))))
        files.append(self._write_ndjson(target / "source_issues.ndjson", self._serialize_rows(select(SourceIssue).order_by(desc(SourceIssue.last_seen_at)))))
        files.append(self._write_ndjson(target / "source_canaries.ndjson", self._serialize_rows(select(SourceCanaryResult).order_by(desc(SourceCanaryResult.timestamp)))))
        files.append(self._write_ndjson(target / "job_runs.ndjson", self._serialize_rows(select(JobRun).order_by(desc(JobRun.started_at)))))
        files.append(self._write_ndjson(target / "crawl_runs.ndjson", self._serialize_rows(select(CrawlRun).order_by(desc(CrawlRun.started_at)))))
        files.append(self._write_ndjson(target / "query_executions.ndjson", self._serialize_rows(select(QueryExecution).order_by(desc(QueryExecution.id)))))
        files.append(self._write_ndjson(target / "fetch_events.ndjson", self._serialize_rows(select(SourceFetchEvent).order_by(desc(SourceFetchEvent.timestamp)))))
        files.append(self._write_ndjson(target / "pipeline_events.ndjson", self._serialize_rows(select(PipelineEvent).order_by(desc(PipelineEvent.timestamp)))))

        files.append(self._write_csv_samples(target / "samples/raw_documents.csv", self._rows_for_csv("raw_documents")))
        files.append(self._write_csv_samples(target / "samples/evidence.csv", self._rows_for_csv("evidence")))
        files.append(self._write_csv_samples(target / "samples/opportunities.csv", self._rows_for_csv("opportunities")))
        files.append(self._write_csv_samples(target / "samples/issues.csv", self._rows_for_csv("issues")))
        files.append(self._write_csv_samples(target / "samples/queries.csv", self._rows_for_csv("queries")))

        files.extend(self._write_dashboard_screenshots(target / "dashboard_screenshots"))
        capture_report = self._load_capture_report(target / "dashboard_screenshots" / "capture_report.json")
        domain_inventory = self._official_domain_inventory(run_scope=run_scope, pitchability=pitchability, source_inventory=source_inventory)
        realness_report = self._realness_report(run_scope=run_scope, source_inventory=source_inventory, pitchability=pitchability, domain_inventory=domain_inventory)
        ui_truth_audit = self._ui_truth_audit(overview=overview, pitchability=pitchability, current_pipeline_truth=current_pipeline_truth)
        admissibility = self._canonical_bundle_admissibility_report(
            latest_run=latest_run,
            run_scope=run_scope,
            source_inventory=source_inventory,
            pitchability=pitchability,
            current_pipeline_truth=current_pipeline_truth,
            official_regression_truth=official_regression_truth,
            harness_schema_validation=harness_schema_validation,
            capture_report=capture_report,
            realness_report=realness_report,
        )
        files.append(self._write_json(target / "official_domain_inventory.json", domain_inventory))
        files.append(self._write_json(target / "realness_report.json", realness_report))
        files.append(self._write_text(target / "realness_report.md", self._realness_report_markdown(realness_report)))
        files.append(self._write_json(target / "ui_truth_audit.json", ui_truth_audit))
        files.append(self._write_text(target / "ui_truth_audit.md", self._ui_truth_audit_markdown(ui_truth_audit)))
        files.append(self._write_json(target / "canonical_bundle_admissibility_report.json", admissibility))
        files.append(self._write_text(target / "canonical_bundle_admissibility_report.md", self._canonical_bundle_admissibility_markdown(admissibility)))

        files.append(self._write_text(target / "README.txt", self._bundle_readme(latest_run)))
        files.append(self._write_text(target / "ROOT_CAUSE_REPORT.md", self._root_cause_report(dataset_diagnosis)))

        if include_blobs:
            blob_listing = [{"path": str(path)} for path in sorted(self.settings.blob_root.rglob("*")) if path.is_file()]
            files.append(self._write_json(target / "blob_inventory.json", blob_listing))
        if include_db_dump:
            files.append(self._write_text(target / "db_dump_note.txt", "DB dump export was requested but is intentionally not bundled automatically."))

        manifest = {
            "generated_at": datetime.now(UTC).isoformat(),
            "run_id": run_id,
            "latest_run_id": latest_run.get("id") if latest_run else None,
            "system_mode": overview["data_mode"],
            "files": [str(path.relative_to(target)) for path in sorted(files)],
            "include_blobs": include_blobs,
            "include_db_dump": include_db_dump,
            "latest_accountability_path": str(self.accountability_root / "latest"),
        }
        manifest_path = self._write_json(target / "manifest.json", manifest)
        files.append(manifest_path)
        checksum_path = target / "checksums.sha256"
        write_checksums(files, checksum_path)
        files.append(checksum_path)
        zip_path = self._zip_bundle(target)
        latest_sync = self._promote_verification_candidate(target=target, zip_path=zip_path, admissibility=admissibility)
        return {
            "bundle_path": str(target),
            "bundle_zip_path": str(zip_path),
            "latest_path": latest_sync["latest_path"],
            "latest_zip_path": latest_sync["latest_zip_path"],
            "latest_live_public_path": latest_sync["latest_live_public_path"],
            "latest_fixture_path": latest_sync["latest_fixture_path"],
            "latest_demo_path": latest_sync["latest_demo_path"],
            "rejected_candidate_path": latest_sync["rejected_candidate_path"],
            "manifest_path": str(manifest_path),
            "sha256": sha256_file(zip_path),
            "run_kind": admissibility["run_kind"],
            "evidence_class": admissibility["evidence_class"],
            "oracle_admissible": admissibility["oracle_admissible"],
            "admissibility_fail_reasons": admissibility["admissibility_fail_reasons"],
        }

    def latest_bundle(self) -> dict[str, Any]:
        for candidate in ("latest-live-public", "latest-fixture", "latest-demo", "latest"):
            latest = self.root / candidate
            manifest = latest / "manifest.json"
            if manifest.exists():
                return {
                    "bundle_path": str(latest),
                    "bundle_zip_path": str(self.root / f"{candidate}.zip"),
                    "manifest_path": str(manifest),
                    "latest_accountability_path": str(self.accountability_root / candidate),
                    "sha256": sha256_file(self.root / f"{candidate}.zip") if (self.root / f"{candidate}.zip").exists() else None,
                }
        return self.generate_bundle()

    def generate_accountability_run(
        self,
        *,
        run_id: str | None = None,
        verification_bundle: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        latest_run = self._resolve_latest_run(run_id=run_id)
        resolved_run_id = (latest_run or {}).get("id") or run_id or "snapshot"
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        target = self.accountability_root / f"{stamp}-accountability-{resolved_run_id}"
        if target.exists():
            shutil.rmtree(target)
        (target / "ui").mkdir(parents=True, exist_ok=True)
        (target / "db").mkdir(parents=True, exist_ok=True)
        (target / "files").mkdir(parents=True, exist_ok=True)

        bundle = verification_bundle or self.generate_bundle(run_id=resolved_run_id)
        bundle_path = Path(bundle["bundle_path"])
        overview = self.ops.overview()
        dataset_diagnosis = self.diagnostics.explain_zero()
        diagnostics = self.diagnostics.diagnostics_overview()
        source_inventory = self.ops.list_sources(limit=2000, offset=0)["items"]
        run_scope = self._run_scope_report(resolved_run_id)
        pitchability = self._pitchability_report()
        baseline_reference = self._baseline_reference()
        before_after = self._before_after_recall_report(
            baseline_reference=baseline_reference,
            run_scope=run_scope,
            pitchability=pitchability,
            source_inventory=source_inventory,
        )
        before_after_pitchability = self._before_after_pitchability_report(
            baseline_reference=baseline_reference,
            pitchability=pitchability,
        )
        source_gap = self._source_gap_report(source_inventory, run_scope=run_scope)
        truth_consistency = self._truth_consistency_report(
            overview=overview,
            dataset_diagnosis=dataset_diagnosis,
            source_inventory=source_inventory,
            run_scope=run_scope,
            pitchability=pitchability,
        )
        current_pipeline_truth = self._current_pipeline_truth_report(
            overview=overview,
            run_scope=run_scope,
            pitchability=pitchability,
            source_inventory=source_inventory,
            source_gap=source_gap,
            truth_consistency=truth_consistency,
        )
        lead_age_distribution = self._lead_age_distribution(pitchability["all_live_records"], as_of_utc=pitchability["as_of_utc"])
        source_yield_matrix = self._source_yield_matrix(
            source_inventory=source_inventory,
            run_scope=run_scope,
            pitchability=pitchability,
        )
        lead_funnel = self._lead_funnel_report(overview=overview, source_yield_matrix=source_yield_matrix)
        source_productionization = self._source_productionization_report(
            source_inventory=source_inventory,
            source_gap=source_gap,
            source_yield_matrix=source_yield_matrix,
            run_scope=run_scope,
        )
        official_regression_truth = self._official_regression_truth_report(as_of_utc=pitchability["as_of_utc"])
        known_current_examples = self._known_current_examples_report(official_regression_truth)
        bundle_lineage = self._bundle_lineage()
        cross_surface_truth = self._cross_surface_truth_report(
            overview=overview,
            pitchability=pitchability,
            current_pipeline_truth=current_pipeline_truth,
            source_yield_matrix=source_yield_matrix,
            run_scope=run_scope,
        )
        run_verdict = self._run_verdict(
            current_pipeline_truth=current_pipeline_truth,
            pitchability=pitchability,
            source_gap=source_gap,
        )
        harness_schema_validation = self._harness_schema_validation_report()
        repo_harness = self._repo_harness_compliance_report(harness_schema_validation)
        dead_weight = self._dead_weight_audit()
        removal_manifest = self._removal_manifest()
        currentness_audit_rows = self._currentness_audit_rows(pitchability["all_live_records"])
        summary = self._accountability_summary(
            latest_run=latest_run,
            overview=overview,
            run_scope=run_scope,
            pitchability=pitchability,
            truth_consistency=truth_consistency,
        )

        related_job_ids = run_scope["related_job_run_ids"]
        related_crawl_ids = run_scope["related_crawl_run_ids"]
        related_source_ids = run_scope["sources_touched_ids"]
        event_rows = self._events_for_runs(related_job_ids, related_crawl_ids)
        fetch_rows = self._fetch_rows(related_crawl_ids)
        query_rows = self._query_rows(related_crawl_ids)
        issue_rows = self._issue_rows(related_source_ids)
        canary_rows = self._serialize_rows(
            select(SourceCanaryResult)
            .where(SourceCanaryResult.source_id.in_(related_source_ids))
            .order_by(desc(SourceCanaryResult.timestamp))
        ) if related_source_ids else self._serialize_rows(select(SourceCanaryResult).order_by(desc(SourceCanaryResult.timestamp)).limit(50))
        trace_payload = self._trace_summary(
            latest_run=latest_run,
            events=event_rows,
            fetch_events=fetch_rows,
            query_rows=query_rows,
        )
        metrics_payload = {
            "overview_kpis": overview["kpis"],
            "metric_catalog": metric_catalog_payload(),
            "dataset_diagnosis": dataset_diagnosis,
            "run_scope": {
                "sources_touched_this_run": run_scope["sources_touched_this_run"],
                "sources_succeeded_this_run": run_scope["sources_succeeded_this_run"],
                "sources_yielding_real_records_this_run": run_scope["sources_yielding_real_records_this_run"],
                "sources_yielding_d365_records_this_run": run_scope["sources_yielding_d365_records_this_run"],
            },
            "pitchability": {
                "pitchable_leads_total": pitchability["pitchable_leads_total"],
                "real_d365_anchored_live_records_total": pitchability["real_d365_anchored_live_records_total"],
                "retained_without_anchor_total": pitchability["retained_without_anchor_total"],
            },
            "truth_consistency": {
                "status": truth_consistency["status"],
                "mismatch_count": len(truth_consistency["mismatches"]),
            },
        }
        inputs_payload = {
            "requested_run_id": run_id,
            "resolved_run_id": resolved_run_id,
            "job_type": latest_run.get("job_type") if latest_run else None,
            "mode": latest_run.get("mode") if latest_run else None,
            "source_names": latest_run.get("source_names") if latest_run else [],
            "budget": latest_run.get("budget") if latest_run else {},
            "verification_bundle": bundle,
        }
        state_before = ((latest_run or {}).get("metadata") or {}).get("state_before") or {}
        state_after = ((latest_run or {}).get("metadata") or {}).get("state_after") or {}
        exception_payload = self._exception_payload(latest_run, run_scope)

        files: list[Path] = []
        files.append(self._write_text(target / "summary.md", summary))
        files.append(self._write_ndjson(target / "app.log.jsonl", self._collect_log_lines(related_job_ids)))
        files.append(self._write_ndjson(target / "events.jsonl", event_rows))
        files.append(self._write_json(target / "trace.json", trace_payload))
        files.append(self._write_json(target / "metrics.json", metrics_payload))
        files.append(self._write_json(target / "inputs.sanitized.json", redact_mapping(inputs_payload)))
        files.append(self._write_json(target / "effective-config.sanitized.json", config_presence_report()))
        files.append(self._write_json(target / "state-before.json", state_before))
        files.append(self._write_json(target / "state-after.json", state_after))
        files.append(self._write_ndjson(target / "network-transcript.jsonl", fetch_rows))
        files.append(self._write_text(target / "stdout.log", self._stdout_stub(event_rows)))
        files.append(self._write_text(target / "stderr.log", self._stderr_stub(exception_payload)))
        files.append(self._write_json(target / "dataset_diagnosis.json", dataset_diagnosis))
        files.append(self._write_json(target / "source_inventory.json", source_inventory))
        files.append(self._write_ndjson(target / "source_issues.ndjson", issue_rows))
        files.append(self._write_ndjson(target / "source_canaries.ndjson", canary_rows))
        files.append(self._write_json(target / "run_scope_report.json", run_scope))
        files.append(self._write_json(target / "pitchability_report.json", pitchability))
        files.append(self._write_text(target / "pitchability_report.md", self._pitchability_markdown(pitchability)))
        files.append(self._write_json(target / "before_after_recall_report.json", before_after))
        files.append(self._write_text(target / "before_after_recall_report.md", self._before_after_recall_markdown(before_after)))
        files.append(self._write_json(target / "before_after_pitchability_report.json", before_after_pitchability))
        files.append(self._write_text(target / "before_after_pitchability_report.md", self._before_after_pitchability_markdown(before_after_pitchability)))
        files.append(self._write_json(target / "source_gap_report.json", source_gap))
        files.append(self._write_text(target / "source_gap_report.md", self._source_gap_markdown(source_gap)))
        files.append(self._write_json(target / "truth_consistency_report.json", truth_consistency))
        files.append(self._write_json(target / "current_pipeline_truth_report.json", current_pipeline_truth))
        files.append(self._write_text(target / "current_pipeline_truth_report.md", self._current_pipeline_truth_markdown(current_pipeline_truth)))
        files.append(self._write_json(target / "lead_age_distribution.json", lead_age_distribution))
        files.append(self._write_json(target / "source_yield_matrix.json", source_yield_matrix))
        files.append(self._write_json(target / "lead_funnel_report.json", lead_funnel))
        files.append(self._write_text(target / "lead_funnel_report.md", self._lead_funnel_markdown(lead_funnel)))
        files.append(self._write_json(target / "source_productionization_report.json", source_productionization))
        files.append(self._write_text(target / "source_productionization_report.md", self._source_productionization_markdown(source_productionization)))
        files.append(self._write_csv_samples(target / "funnel_by_source.csv", lead_funnel["by_source"]))
        files.append(self._write_json(target / "funnel_by_source.json", lead_funnel["by_source"]))
        files.append(self._write_csv_samples(target / "funnel_by_query_family.csv", lead_funnel["by_query_family"]))
        files.append(self._write_json(target / "funnel_by_query_family.json", lead_funnel["by_query_family"]))
        files.append(self._write_json(target / "official_regression_truth_report.json", official_regression_truth))
        files.append(self._write_text(target / "official_regression_truth_report.md", self._official_regression_truth_markdown(official_regression_truth)))
        files.append(self._write_json(target / "known_current_examples_report.json", known_current_examples))
        files.append(self._write_text(target / "known_current_examples_report.md", self._known_current_examples_markdown(known_current_examples)))
        files.append(self._write_json(target / "cross_surface_truth_report.json", cross_surface_truth))
        files.append(self._write_json(target / "metric_catalog.json", metric_catalog_payload()))
        files.append(self._write_json(target / "run_verdict.json", run_verdict))
        files.append(self._write_text(target / "run_verdict.md", self._run_verdict_markdown(run_verdict)))
        files.append(self._write_json(target / "harness_schema_validation_report.json", harness_schema_validation))
        files.append(self._write_json(target / "repo_harness_compliance_report.json", repo_harness))
        files.append(self._write_text(target / "repo_harness_compliance_report.md", self._repo_harness_compliance_markdown(repo_harness)))
        files.append(self._write_json(target / "dead_weight_audit.json", dead_weight))
        files.append(self._write_text(target / "dead_weight_audit.md", self._dead_weight_audit_markdown(dead_weight)))
        files.append(self._write_json(target / "removal_manifest.json", removal_manifest))
        files.append(self._write_json(target / "bundle_lineage.json", bundle_lineage))
        files.extend(self._write_export_files(target, "currentness_audit", currentness_audit_rows))
        if dataset_diagnosis["live_records"] == 0:
            files.append(self._write_json(target / "empty_dataset_explainer.json", dataset_diagnosis))
        if exception_payload:
            files.append(self._write_json(target / "exception.json", exception_payload))

        ui_state = {
            "overview": overview,
            "diagnostics": diagnostics,
            "latest_run": latest_run,
            "verification_bundle_path": str(bundle_path),
        }
        files.append(self._write_json(target / "ui" / "state.json", ui_state))
        files.extend(self._copy_dashboard_screenshots(bundle_path, target / "ui"))

        files.append(self._write_json(target / "db" / "summary_before.json", state_before))
        files.append(self._write_json(target / "db" / "summary_after.json", state_after))
        files.append(self._write_json(target / "db" / "source_inventory.json", source_inventory))
        files.append(self._write_json(target / "db" / "issues.json", issue_rows))
        files.append(self._write_json(target / "db" / "queries.json", query_rows[:250]))
        files.append(self._write_json(target / "db" / "fetch_events.json", fetch_rows[:250]))
        files.append(self._write_json(target / "db" / "opportunities.json", pitchability["all_live_records"]))
        files.append(self._write_json(target / "db" / "evidence.json", self._rows_for_csv("evidence")))
        capture_report = self._load_capture_report(target / "ui" / "capture_report.json")
        domain_inventory = self._official_domain_inventory(run_scope=run_scope, pitchability=pitchability, source_inventory=source_inventory)
        realness_report = self._realness_report(run_scope=run_scope, source_inventory=source_inventory, pitchability=pitchability, domain_inventory=domain_inventory)
        ui_truth_audit = self._ui_truth_audit(overview=overview, pitchability=pitchability, current_pipeline_truth=current_pipeline_truth)
        admissibility = self._canonical_bundle_admissibility_report(
            latest_run=latest_run,
            run_scope=run_scope,
            source_inventory=source_inventory,
            pitchability=pitchability,
            current_pipeline_truth=current_pipeline_truth,
            official_regression_truth=official_regression_truth,
            harness_schema_validation=harness_schema_validation,
            capture_report=capture_report,
            realness_report=realness_report,
        )
        files.append(self._write_json(target / "official_domain_inventory.json", domain_inventory))
        files.append(self._write_json(target / "realness_report.json", realness_report))
        files.append(self._write_text(target / "realness_report.md", self._realness_report_markdown(realness_report)))
        files.append(self._write_json(target / "ui_truth_audit.json", ui_truth_audit))
        files.append(self._write_text(target / "ui_truth_audit.md", self._ui_truth_audit_markdown(ui_truth_audit)))
        files.append(self._write_json(target / "canonical_bundle_admissibility_report.json", admissibility))
        files.append(self._write_text(target / "canonical_bundle_admissibility_report.md", self._canonical_bundle_admissibility_markdown(admissibility)))

        pitchable_rows = pitchability["pitchable_rows"]
        seller_ready_rows = pitchability["seller_ready_rows"]
        research_ready_rows = pitchability["research_ready_rows"]
        non_pitchable_rows = pitchability["non_pitchable_rows"]
        stale_or_awarded_rows = pitchability["stale_or_awarded_rows"]
        english_insufficient_rows = pitchability["english_insufficient_rows"]
        pitchability_exclusion_rows = [
            {
                "candidate_id": row["id"],
                "title": row["title"],
                "buyer": row.get("buyer"),
                "source_url": row.get("source_url"),
                "reason": reason,
                "current_actionability_state": row.get("current_actionability_state"),
                "commercial_motion": row.get("commercial_motion"),
            }
            for row in non_pitchable_rows
            for reason in row.get("pitchability_reasons", [])
        ]
        near_miss_rows = self._rejected_near_misses()
        files.extend(self._write_export_files(target, "seller_ready_leads", seller_ready_rows))
        files.extend(self._write_export_files(target, "seller_ready_bid_now_leads", [row for row in seller_ready_rows if row.get("recommended_action") == "bid_now"]))
        files.extend(self._write_export_files(target, "seller_ready_pre_position_leads", [row for row in seller_ready_rows if row.get("recommended_action") == "pre_position"]))
        files.extend(self._write_export_files(target, "research_ready_leads", research_ready_rows))
        files.extend(self._write_export_files(target, "pitchable_leads", pitchable_rows))
        files.extend(self._write_export_files(target, "non_pitchable_live_records", non_pitchable_rows))
        files.extend(self._write_export_files(target, "rejected_near_misses", near_miss_rows))
        files.extend(self._write_export_files(target, "stale_or_awarded_live_records", stale_or_awarded_rows))
        files.extend(self._write_export_files(target, "english_insufficient_live_records", english_insufficient_rows))
        files.extend(self._write_export_files(target, "pitchability_exclusion_reasons", pitchability_exclusion_rows))
        files.extend(self._write_export_files(target, "current_bid_now_leads", [row for row in seller_ready_rows if row.get("recommended_action") == "bid_now"]))
        files.extend(self._write_export_files(target, "current_pre_position_leads", [row for row in seller_ready_rows if row.get("recommended_action") == "pre_position"]))
        files.extend(self._write_export_files(target, "award_watch", [row for row in non_pitchable_rows if row.get("recommended_action") == "award_watch"]))
        files.extend(self._write_export_files(target, "renewal_watch", [row for row in non_pitchable_rows if row.get("recommended_action") == "renewal_watch"]))
        files.extend(self._write_export_files(target, "monitor_only", [row for row in non_pitchable_rows if row.get("recommended_action") == "monitor"]))

        file_manifest = self._artifact_file_manifest(target)
        files.append(self._write_json(target / "files" / "output_manifest.json", file_manifest))
        files.append(self._write_checksums_with_relative_paths(files, target / "files" / "checksums.sha256", target))
        files.append(self._write_text(target / "ROOT_CAUSE_REPORT.md", self._root_cause_report(dataset_diagnosis)))
        files.append(self._write_text(target / "README.txt", self._accountability_readme()))

        bundle_manifest = {
            "contract": "accountability_run_v1",
            "generated_at": datetime.now(UTC).isoformat(),
            "run_id": resolved_run_id,
            "system_mode": overview["data_mode"],
            "alias_map": {"network.har": "network-transcript.jsonl"},
            "verification_bundle_path": str(bundle_path),
            "files": [str(path.relative_to(target)) for path in sorted(files)],
        }
        manifest_path = self._write_json(target / "bundle-manifest.json", bundle_manifest)
        files.append(manifest_path)

        zip_path = self._zip_bundle(target)
        latest_sync = self._promote_accountability_candidate(target=target, zip_path=zip_path, admissibility=admissibility)
        return {
            "bundle_path": str(target),
            "bundle_zip_path": str(zip_path),
            "latest_path": latest_sync["latest_path"],
            "latest_zip_path": latest_sync["latest_zip_path"],
            "latest_live_public_path": latest_sync["latest_live_public_path"],
            "latest_fixture_path": latest_sync["latest_fixture_path"],
            "latest_demo_path": latest_sync["latest_demo_path"],
            "rejected_candidate_path": latest_sync["rejected_candidate_path"],
            "manifest_path": str(manifest_path),
            "sha256": sha256_file(zip_path),
            "run_kind": admissibility["run_kind"],
            "evidence_class": admissibility["evidence_class"],
            "oracle_admissible": admissibility["oracle_admissible"],
            "admissibility_fail_reasons": admissibility["admissibility_fail_reasons"],
        }

    def _resolve_latest_run(self, *, run_id: str | None = None) -> dict[str, Any] | None:
        if run_id:
            try:
                return self.ops.get_run(run_id)
            except KeyError:
                return None
        runs = self.ops.list_runs(limit=1, offset=0)["items"]
        return runs[0] if runs else None

    def _serialize_rows(self, statement) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for row in self.session.execute(statement).scalars():
            payload: dict[str, Any] = {}
            for key, value in vars(row).items():
                if key.startswith("_"):
                    continue
                payload[key] = json_default(value)
            rows.append(redact_mapping(payload))
        return rows

    def _rows_for_csv(self, kind: str) -> list[dict[str, Any]]:
        limit = self.settings.verification_sample_limit
        if kind == "evidence":
            rows = []
            for row in self.session.execute(select(EvidenceRecord).order_by(desc(EvidenceRecord.publication_date)).limit(limit)).scalars():
                rows.append(
                    {
                        "id": row.id,
                        "title": row.title,
                        "buyer_name": row.buyer_name,
                        "source_url": row.source_url,
                        "retrieval_score": row.retrieval_score,
                        "query_family": row.query_family,
                        "english_evidence_source": row.english_evidence_source,
                        "matched_positive_terms": row.matched_positive_terms_json,
                        "exclusion_reason": row.exclusion_reason,
                    }
                )
            return rows
        if kind == "issues":
            return self.ops.list_issues(limit=limit, offset=0)["items"]
        if kind == "queries":
            return self.ops.list_queries(limit=limit, offset=0)["items"]
        if kind == "opportunities":
            return self.ops.list_opportunities(limit=limit, offset=0)["items"]
        rows = []
        for row in self.session.execute(select(RawDocument).order_by(desc(RawDocument.fetched_at)).limit(limit)).scalars():
            rows.append(
                {
                    "id": row.id,
                    "source_id": row.source_id,
                    "external_id": row.external_id,
                    "canonical_url": row.canonical_url,
                    "document_url": row.document_url,
                    "content_type": row.content_type,
                    "blob_path": row.blob_path,
                    "checksum": row.checksum,
                }
            )
        return rows

    def _bundle_readme(self, latest_run: dict[str, Any] | None) -> str:
        return "\n".join(
            [
                "D365 verification bundle",
                "",
                "This bundle is designed for offline review.",
                "",
                f"Latest run: {latest_run.get('id') if latest_run else 'none'}",
                f"Generated at: {datetime.now(UTC).isoformat()}",
                "",
                "Key files:",
                "- manifest.json",
                "- diagnostic_summary.json",
                "- dataset_diagnosis.json",
                "- source_inventory.json",
                "- pipeline_events.ndjson",
                "- fetch_events.ndjson",
                "- query_executions.ndjson",
                "- ROOT_CAUSE_REPORT.md",
                "",
                "Canonical accountability runs live under artifacts/runs/latest/.",
            ]
        )

    def _root_cause_report(self, dataset_diagnosis: dict[str, Any]) -> str:
        lines = [
            "# ROOT_CAUSE_REPORT",
            "",
            f"- dataset mode: {dataset_diagnosis['dataset_mode']}",
            f"- live records: {dataset_diagnosis['live_records']}",
            f"- demo records: {dataset_diagnosis['demo_records']}",
            f"- last successful backfill: {dataset_diagnosis['last_successful_backfill'] or 'none'}",
            f"- last successful live refresh: {dataset_diagnosis['last_successful_live_refresh'] or 'none'}",
            f"- enabled sources: {dataset_diagnosis['enabled_sources']}",
            f"- parser-implemented enabled: {dataset_diagnosis.get('parser_implemented_enabled', 0)}",
            f"- prod-ready enabled: {dataset_diagnosis['prod_ready_enabled']}",
            f"- scaffold enabled: {dataset_diagnosis['scaffold_enabled']}",
            f"- canaries passed: {dataset_diagnosis['canaries_passed']}",
            f"- successful fetches: {dataset_diagnosis['successful_fetches']}",
            f"- docs fetched 7d: {dataset_diagnosis['docs_fetched_7d']}",
            f"- evidence extracted 7d: {dataset_diagnosis['evidence_extracted_7d']}",
            "",
            "## Top root causes",
        ]
        for row in dataset_diagnosis["top_root_causes"]:
            lines.append(f"{row['rank']}. {row['cause']}")
        lines.extend(["", "## Next actions"])
        for row in dataset_diagnosis["next_actions"]:
            lines.append(f"- {row['action']}")
        return "\n".join(lines) + "\n"

    def _accountability_readme(self) -> str:
        return "\n".join(
            [
                "D365 accountability run",
                "",
                "This folder is the canonical offline review surface for the latest accountability pass.",
                "",
                "Read in this order:",
                "1. summary.md",
                "2. pitchability_report.md",
                "3. truth_consistency_report.json",
                "4. run_scope_report.json",
                "5. dataset_diagnosis.json",
                "6. events.jsonl and network-transcript.jsonl",
                "7. ui/ screenshots",
            ]
        )

    def _run_scope_report(self, run_id: str) -> dict[str, Any]:
        anchor_job = self.session.get(JobRun, run_id)
        sources = self.ops.list_sources(limit=2000, offset=0)["items"]
        requested_names = anchor_job.source_names_json if anchor_job else []
        selected_names = [] if (anchor_job and anchor_job.source_id) else requested_names
        anchor_time = (anchor_job.finished_at or anchor_job.started_at) if anchor_job else datetime.now(UTC).replace(tzinfo=None)
        refresh_jobs = self._refresh_cohort(anchor_time=anchor_time, selected_names=selected_names)
        if anchor_job and anchor_job.source_id and not refresh_jobs:
            refresh_jobs = [anchor_job]
            requested_names = requested_names or [self._source_name(anchor_job.source_id)]
        touched_ids = sorted({job.source_id for job in refresh_jobs if job.source_id})
        touched_names = [self._source_name(source_id) for source_id in touched_ids]
        succeeded_ids = sorted(
            {
                job.source_id
                for job in refresh_jobs
                if job.source_id and job.status.value == "succeeded" and int(job.documents_fetched or 0) > 0
            }
        )
        retained_source_ids = sorted(
            {
                job.source_id
                for job in refresh_jobs
                if job.source_id and int(job.candidates_created or 0) > 0
            }
        )
        query_rows = [
            row
            for row in self.session.execute(select(QueryExecution)).scalars()
            if row.crawl_run_id in {job.crawl_run_id for job in refresh_jobs if job.crawl_run_id}
        ]
        run_started_at = min((job.started_at for job in refresh_jobs), default=anchor_time)
        run_finished_at = max((job.finished_at or job.started_at for job in refresh_jobs), default=anchor_time)
        pitchable_source_ids = sorted(
            {
                evidence.source_id
                for candidate in self.session.execute(select(OpportunityCandidate).order_by(desc(OpportunityCandidate.updated_at))).scalars()
                for evidence in [self.session.get(EvidenceRecord, candidate.evidence_record_id)]
                if evidence
                and evidence.source_id in touched_ids
                and candidate.updated_at
                and (run_started_at - timedelta(minutes=5)) <= candidate.updated_at <= (run_finished_at + timedelta(minutes=5))
                and not is_demo_record(candidate)
                and not is_demo_record(evidence)
                and evaluate_record(candidate, evidence=evidence).allowed
            }
        )
        query_families_planned = sorted({row.query_family for row in query_rows if row.query_family})
        query_families_executed = sorted({row.query_family for row in query_rows if row.query_family and row.was_executed})
        query_families_yielding = sorted(
            {row.query_family for row in query_rows if row.query_family and ((row.opps or 0) > 0 or (row.signals or 0) > 0)}
        )
        skipped: list[dict[str, Any]] = []
        enabled_names = {row["name"]: row for row in sources if row["enabled"]}
        if selected_names:
            for name in selected_names:
                source = enabled_names.get(name)
                if not source:
                    skipped.append({"source": name, "reason": "not_enabled_or_unknown"})
                    continue
                if source["id"] not in touched_ids:
                    skipped.append({"source": name, "reason": source["recommended_fix"] or source["operational_state"]})
        return {
            "run_id": run_id,
            "anchor_run_id": anchor_job.id if anchor_job else None,
            "anchor_job_type": anchor_job.job_type.value if anchor_job else None,
            "anchor_mode": anchor_job.mode if anchor_job else None,
            "anchor_time": json_default(anchor_time),
            "run_started_at": json_default(run_started_at),
            "run_finished_at": json_default(run_finished_at),
            "sources_configured": len(sources),
            "sources_enabled": sum(1 for row in sources if row["enabled"]),
            "sources_selected_for_run": requested_names or touched_names,
            "sources_selected_ids": [row["id"] for row in sources if row["name"] in set(requested_names or touched_names)],
            "sources_actually_touched": touched_names,
            "sources_touched_ids": touched_ids,
            "sources_touched_this_run": len(touched_ids),
            "sources_with_successful_fetches": [self._source_name(source_id) for source_id in succeeded_ids],
            "sources_succeeded_this_run": len(succeeded_ids),
            "sources_yielding_real_records": [self._source_name(source_id) for source_id in retained_source_ids],
            "sources_yielding_real_records_this_run": len(retained_source_ids),
            "sources_yielding_d365_records": [self._source_name(source_id) for source_id in retained_source_ids],
            "sources_yielding_d365_records_this_run": len(retained_source_ids),
            "sources_yielding_pitchable_records": [self._source_name(source_id) for source_id in pitchable_source_ids],
            "sources_yielding_pitchable_records_this_run": len(pitchable_source_ids),
            "sources_skipped": skipped,
            "query_families_planned": query_families_planned,
            "query_families_executed": query_families_executed,
            "query_families_yielding_retained_records": query_families_yielding,
            "related_job_run_ids": [job.id for job in refresh_jobs] + ([anchor_job.id] if anchor_job and anchor_job.id not in {job.id for job in refresh_jobs} else []),
            "related_crawl_run_ids": [job.crawl_run_id for job in refresh_jobs if job.crawl_run_id],
        }

    def _refresh_cohort(self, *, anchor_time: datetime, selected_names: list[str]) -> list[JobRun]:
        source_ids: set[str] = set()
        if selected_names:
            source_ids = {
                row.id
                for row in self.session.execute(select(SourceRegistry).where(SourceRegistry.name.in_(selected_names))).scalars()
            }
        refresh_jobs = [
            row
            for row in self.session.execute(
                select(JobRun).where(
                    JobRun.job_type == JobType.REFRESH,
                    JobRun.source_id.is_not(None),
                    JobRun.finished_at.is_not(None),
                )
            ).scalars()
            if row.finished_at and row.finished_at <= anchor_time
        ]
        if source_ids:
            refresh_jobs = [row for row in refresh_jobs if row.source_id in source_ids]
        if not refresh_jobs:
            return []
        latest_refresh = max(refresh_jobs, key=lambda row: row.finished_at or row.started_at)
        cohort_mode = latest_refresh.mode
        lookback_start = anchor_time - timedelta(hours=24)
        cohort_rows = [
            row
            for row in refresh_jobs
            if (row.finished_at or row.started_at) >= lookback_start
            and (not cohort_mode or row.mode == cohort_mode)
        ]
        if not cohort_rows:
            cohort_rows = [
                row
                for row in refresh_jobs
                if not cohort_mode or row.mode == cohort_mode
            ]
        latest_by_source: dict[str, JobRun] = {}
        for row in cohort_rows:
            if not row.source_id:
                continue
            existing = latest_by_source.get(row.source_id)
            current_ts = row.finished_at or row.started_at
            existing_ts = (existing.finished_at or existing.started_at) if existing else None
            if existing is None or (current_ts and existing_ts and current_ts > existing_ts):
                latest_by_source[row.source_id] = row
            elif existing is None:
                latest_by_source[row.source_id] = row
        rows = list(latest_by_source.values()) or cohort_rows
        return sorted(rows, key=lambda row: row.started_at)

    def _source_name(self, source_id: str | None) -> str:
        if not source_id:
            return "unknown"
        source = self.session.get(SourceRegistry, source_id)
        return source.name if source else source_id

    def _pitchability_report(self) -> dict[str, Any]:
        as_of_utc = datetime.now(UTC)
        all_live_rows: list[dict[str, Any]] = []
        pitchable_rows: list[dict[str, Any]] = []
        seller_ready_rows: list[dict[str, Any]] = []
        research_ready_rows: list[dict[str, Any]] = []
        non_pitchable_rows: list[dict[str, Any]] = []
        pitch_now_rows: list[dict[str, Any]] = []
        pre_position_rows: list[dict[str, Any]] = []
        monitor_only_rows: list[dict[str, Any]] = []
        award_watch_rows: list[dict[str, Any]] = []
        renewal_watch_rows: list[dict[str, Any]] = []
        stale_or_awarded_rows: list[dict[str, Any]] = []
        english_insufficient_rows: list[dict[str, Any]] = []
        current_actionable_rows: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        duplicates_total = 0
        anchored_total = 0
        retained_without_anchor_total = 0
        for candidate in self.session.execute(
            select(OpportunityCandidate).order_by(desc(OpportunityCandidate.updated_at))
        ).scalars():
            evidence = self.session.get(EvidenceRecord, candidate.evidence_record_id)
            if is_demo_record(candidate) or is_demo_record(evidence):
                continue
            row = self.ops._opportunity_row(candidate)
            evaluation = evaluate_record(candidate, evidence=evidence, seen_keys=seen_keys, today=as_of_utc)
            apply_evaluation_to_row(row, evaluation)
            row["dedupe_key"] = dedupe_key(candidate)
            row["as_of_utc"] = as_of_utc.isoformat()
            row = self._apply_authenticity_to_pitchability_row(row, evidence=evidence)
            all_live_rows.append(row)
            if row.get("anchor_terms"):
                anchored_total += 1
            else:
                retained_without_anchor_total += 1
            if is_canonical_authentic_row(row) and row.get("recommended_action") in {"bid_now", "pre_position"} and row.get("current_actionability_state") in {
                "open_bid",
                "open_consultation",
                "pre_market_engagement",
                "planned_procurement",
                "framework_or_vehicle",
            }:
                current_actionable_rows.append(row)
            if "duplicate" in (row.get("pitchability_reasons") or []):
                duplicates_total += 1
            if row.get("sales_handoff_state") == "seller_ready":
                seller_ready_rows.append(row)
                pitchable_rows.append(row)
                if row.get("commercial_motion") == "pitch_now":
                    pitch_now_rows.append(row)
                elif row.get("commercial_motion") == "pre_position":
                    pre_position_rows.append(row)
            else:
                non_pitchable_rows.append(row)
                if row.get("sales_handoff_state") == "research_ready":
                    research_ready_rows.append(row)
                if row.get("current_actionability_state") in {"expired", "awarded", "award_notice", "contract_details_only", "closed_submission", "cancelled"}:
                    stale_or_awarded_rows.append(row)
                if "english_insufficient" in (row.get("pitchability_reasons") or []) or "english_shell_only" in (row.get("pitchability_reasons") or []):
                    english_insufficient_rows.append(row)
                if row.get("commercial_motion") == "monitor":
                    monitor_only_rows.append(row)
                if row.get("recommended_action") == "award_watch":
                    award_watch_rows.append(row)
                if row.get("recommended_action") == "renewal_watch":
                    renewal_watch_rows.append(row)
        reason_counts = Counter(reason for row in non_pitchable_rows for reason in row["pitchability_reasons"])
        if pitchable_rows:
            why_zero: list[dict[str, Any]] = []
        elif all_live_rows:
            why_zero = [{"reason": reason, "count": count} for reason, count in reason_counts.most_common(8)]
        else:
            why_zero = [{"reason": cause["cause"], "count": 1} for cause in self.diagnostics.explain_zero()["top_root_causes"]]
        return {
            "generated_at": as_of_utc.isoformat(),
            "as_of_utc": as_of_utc.isoformat(),
            "pitchable_leads_total": len(pitchable_rows),
            "pitchable_leads_unique": len({row["dedupe_key"] for row in pitchable_rows if row["dedupe_key"]}),
            "non_pitchable_live_records_total": len(non_pitchable_rows),
            "real_d365_anchored_live_records_total": anchored_total,
            "retained_without_anchor_total": retained_without_anchor_total,
            "duplicates_total": duplicates_total,
            "pitch_now_total": len(pitch_now_rows),
            "pre_position_total": len(pre_position_rows),
            "monitor_only_total": len(monitor_only_rows),
            "seller_ready_total": len(seller_ready_rows),
            "seller_ready_bid_now_total": len([row for row in seller_ready_rows if row.get("recommended_action") == "bid_now"]),
            "seller_ready_pre_position_total": len([row for row in seller_ready_rows if row.get("recommended_action") == "pre_position"]),
            "research_ready_total": len(research_ready_rows),
            "award_watch_total": len(award_watch_rows),
            "renewal_watch_total": len(renewal_watch_rows),
            "current_actionable_total": len(current_actionable_rows),
            "stale_or_awarded_total": len(stale_or_awarded_rows),
            "english_insufficient_total": len(english_insufficient_rows),
            "current_top_pitchable_leads": sorted(
                pitchable_rows,
                key=lambda row: (row.get("opportunity_score") or 0, row.get("retrieval_score") or 0),
                reverse=True,
            )[:10],
            "why_zero": why_zero,
            "pitch_now_rows": pitch_now_rows,
            "pre_position_rows": pre_position_rows,
            "seller_ready_rows": seller_ready_rows,
            "research_ready_rows": research_ready_rows,
            "monitor_only_rows": monitor_only_rows,
            "award_watch_rows": award_watch_rows,
            "renewal_watch_rows": renewal_watch_rows,
            "stale_or_awarded_rows": stale_or_awarded_rows,
            "english_insufficient_rows": english_insufficient_rows,
            "current_actionable_rows": current_actionable_rows,
            "pitchable_rows": pitchable_rows,
            "non_pitchable_rows": non_pitchable_rows,
            "all_live_records": all_live_rows,
        }

    def _pitchability_markdown(self, pitchability: dict[str, Any]) -> str:
        lines = [
            "# Pitchability Report",
            "",
            f"- pitchable leads total: {pitchability['pitchable_leads_total']}",
            f"- pitchable leads unique: {pitchability['pitchable_leads_unique']}",
            f"- non-pitchable live records total: {pitchability['non_pitchable_live_records_total']}",
            f"- real D365-anchored live records total: {pitchability['real_d365_anchored_live_records_total']}",
            f"- retained without anchor total: {pitchability['retained_without_anchor_total']}",
            f"- duplicates total: {pitchability['duplicates_total']}",
            f"- pitch-now total: {pitchability['pitch_now_total']}",
            f"- pre-position total: {pitchability['pre_position_total']}",
            f"- seller-ready total: {pitchability['seller_ready_total']}",
            f"- seller-ready bid-now total: {pitchability['seller_ready_bid_now_total']}",
            f"- seller-ready pre-position total: {pitchability['seller_ready_pre_position_total']}",
            f"- research-ready total: {pitchability['research_ready_total']}",
            f"- monitor-only total: {pitchability['monitor_only_total']}",
            f"- award-watch total: {pitchability['award_watch_total']}",
            f"- renewal-watch total: {pitchability['renewal_watch_total']}",
            f"- stale-or-awarded total: {pitchability['stale_or_awarded_total']}",
            f"- english-insufficient total: {pitchability['english_insufficient_total']}",
            "",
            "## Current top pitchable leads",
        ]
        if pitchability["current_top_pitchable_leads"]:
            for row in pitchability["current_top_pitchable_leads"]:
                lines.append(
                    f"- {row['title']} | buyer={row.get('buyer') or 'unknown'} | country={row.get('country') or 'unknown'} | score={row.get('opportunity_score')}"
                )
        else:
            lines.append("- none")
        if pitchability["why_zero"]:
            lines.extend(["", "## Why zero"])
            for item in pitchability["why_zero"]:
                lines.append(f"- {item['reason']}: {item['count']}")
        return "\n".join(lines) + "\n"

    def _apply_authenticity_to_pitchability_row(self, row: dict[str, Any], *, evidence: EvidenceRecord | None) -> dict[str, Any]:
        source = self.session.get(SourceRegistry, evidence.source_id) if evidence and evidence.source_id else None
        authenticity = classify_row_authenticity(
            source_name=(source.name if source else row.get("source_name")),
            source_url=row.get("source_url") or row.get("top_source"),
            endpoint=(source.endpoint if source else row.get("top_source")),
            source_family=(source.source_family if source else None),
            public_access_mode=(source.public_access_mode.value if source else row.get("public_access_mode")),
            data_mode=row.get("data_mode"),
        )
        row["source_name"] = source.name if source else row.get("source_name")
        row["source_authenticity_class"] = authenticity.authenticity_class
        row["canonical_allowed"] = authenticity.canonical_allowed
        row["source_authenticity_reasons"] = authenticity.reasons
        row["source_host"] = authenticity.host
        row["row_evidence_class"] = "official_public" if authenticity.canonical_allowed else authenticity.authenticity_class
        if row.get("sales_handoff_state") == "seller_ready" and not authenticity.canonical_allowed:
            reasons = list(row.get("pitchability_reasons") or [])
            if "source_not_official_public" not in reasons:
                reasons.append("source_not_official_public")
            row["pitchability_reasons"] = reasons
            row["seller_handoff_rationale"] = "Source is not an official public procurement surface; retain for research or rejection only."
            if authenticity.authenticity_class in {"synthetic_fixture", "demo_seed"}:
                row["sales_handoff_state"] = "reject"
                row["recommended_action"] = "reject"
            else:
                row["sales_handoff_state"] = "research_ready"
            row["pursuit_recommendation"] = row["sales_handoff_state"]
        return row

    def _known_current_examples_report(self, official_regression_truth: dict[str, Any]) -> dict[str, Any]:
        rows = []
        for case in official_regression_truth["cases"]:
            rows.append(
                {
                    "procurement_id": case["procurement_id"],
                    "label": case["label"],
                    "source_url": case.get("source_url"),
                    "retained": case.get("found_in_evidence") or case.get("found_in_candidates"),
                    "seller_ready": bool(case.get("pitchable")),
                    "currentness_state": case.get("current_actionability_state"),
                    "english_sufficiency": "english_insufficient" not in (case.get("reasons") or []),
                    "exclusion_reason": case.get("exclusion_reason"),
                    "pass": case.get("pass"),
                }
            )
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "total_examples": len(rows),
            "rows": rows,
        }

    def _known_current_examples_markdown(self, report: dict[str, Any]) -> str:
        lines = ["# Known Current Examples Report", "", f"- total examples: {report['total_examples']}", ""]
        for row in report["rows"]:
            lines.append(
                f"- {row['procurement_id']} | retained={row['retained']} | seller_ready={row['seller_ready']} | state={row.get('currentness_state') or 'unknown'} | pass={'yes' if row['pass'] else 'no'}"
            )
        return "\n".join(lines) + "\n"

    def _lead_funnel_report(self, *, overview: dict[str, Any], source_yield_matrix: dict[str, Any]) -> dict[str, Any]:
        by_source = [
            {
                "source": row["source"],
                "successful_fetches": row["successful_this_run"],
                "fetched_documents": sum(family["returned_documents"] for family in row["query_families"]),
                "evidence_rows": row["retained_d365_records"] + row["stale_or_awarded_records"] + row["english_insufficient_records"],
                "retained_d365_records": row["retained_d365_records"],
                "current_actionable_total": row["bid_now_records"] + row["pre_position_records"],
                "seller_ready_total": row["seller_ready_records"],
            }
            for row in source_yield_matrix["rows"]
        ]
        query_family_rollup: dict[str, dict[str, Any]] = {}
        for row in source_yield_matrix["rows"]:
            for family in row["query_families"]:
                entry = query_family_rollup.setdefault(
                    family["query_family"],
                    {
                        "query_family": family["query_family"],
                        "attempted_queries": 0,
                        "executed_queries": 0,
                        "returned_documents": 0,
                        "retained_d365_records": 0,
                        "current_actionable_total": 0,
                        "seller_ready_total": 0,
                        "noisy_records": 0,
                    },
                )
                entry["attempted_queries"] += family["attempted_queries"]
                entry["executed_queries"] += family["executed_queries"]
                entry["returned_documents"] += family["returned_documents"]
                entry["retained_d365_records"] += family["retained_records"]
                entry["current_actionable_total"] += family["current_actionable_records"]
                entry["seller_ready_total"] += family["seller_ready_records"]
                entry["noisy_records"] += family["noisy_records"]
        by_query_family = sorted(
            query_family_rollup.values(),
            key=lambda item: (-item["seller_ready_total"], -item["retained_d365_records"], item["query_family"]),
        )
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "metric_catalog": metric_catalog_payload(),
            "summary": {
                "successful_fetches": overview["kpis"].get("successful_fetches", 0),
                "fetched_documents": overview["kpis"].get("fetched_documents", 0),
                "evidence_rows": overview["kpis"].get("evidence_rows", 0),
                "retained_d365_records": overview["kpis"].get("retained_d365_records", 0),
                "current_actionable_total": overview["kpis"].get("current_actionable_total", 0),
                "seller_ready_total": overview["kpis"].get("seller_ready_total", 0),
            },
            "by_source": by_source,
            "by_query_family": by_query_family,
        }

    def _lead_funnel_markdown(self, report: dict[str, Any]) -> str:
        summary = report["summary"]
        lines = [
            "# Lead Funnel Report",
            "",
            f"- successful fetches: {summary['successful_fetches']}",
            f"- fetched documents: {summary['fetched_documents']}",
            f"- evidence rows: {summary['evidence_rows']}",
            f"- retained D365 records: {summary['retained_d365_records']}",
            f"- current actionable total: {summary['current_actionable_total']}",
            f"- seller-ready total: {summary['seller_ready_total']}",
            "",
            "## Top sources by seller-ready output",
        ]
        for row in sorted(report["by_source"], key=lambda item: (-item["seller_ready_total"], -item["retained_d365_records"], item["source"]))[:10]:
            lines.append(
                f"- {row['source']}: docs={row['fetched_documents']} retained={row['retained_d365_records']} actionable={row['current_actionable_total']} seller_ready={row['seller_ready_total']}"
            )
        if not report["by_source"]:
            lines.append("- none")
        return "\n".join(lines) + "\n"

    def _source_productionization_report(
        self,
        *,
        source_inventory: list[dict[str, Any]],
        source_gap: dict[str, Any],
        source_yield_matrix: dict[str, Any],
        run_scope: dict[str, Any],
    ) -> dict[str, Any]:
        gap_by_name = {row["name"]: row for row in source_gap.get("sources", [])}
        matrix_by_name = {row["source"]: row for row in source_yield_matrix.get("rows", [])}
        touched = set(run_scope.get("sources_actually_touched") or [])
        rows: list[dict[str, Any]] = []
        for source in source_inventory:
            gap = gap_by_name.get(source["name"], {})
            matrix = matrix_by_name.get(source["name"], {})
            rows.append(
                {
                    "source": source["name"],
                    "source_family": source.get("source_family"),
                    "public_access_mode": source.get("public_access_mode"),
                    "enabled": source.get("enabled"),
                    "parser_implemented": source.get("parser_implemented"),
                    "production_ready": source.get("production_ready"),
                    "adapter_grade": (source.get("source_capabilities") or {}).get("adapter_grade"),
                    "operational_state": source.get("operational_state"),
                    "yield_state": source.get("yield_state"),
                    "last_canary_status": source.get("last_canary_status"),
                    "touched_this_run": source["name"] in touched,
                    "yielding_retained_d365_this_run": gap.get("yielding_retained_d365_this_run", False),
                    "yielding_seller_ready_this_run": gap.get("yielding_seller_ready_this_run", False),
                    "retained_d365_records": matrix.get("retained_d365_records", 0),
                    "seller_ready_records": matrix.get("seller_ready_records", 0),
                    "gap_reasons": gap.get("gap_reasons", []),
                }
            )
        rows.sort(
            key=lambda item: (
                not item["production_ready"],
                -int(bool(item["yielding_seller_ready_this_run"])),
                -item["seller_ready_records"],
                item["source"],
            )
        )
        thresholds = {
            "production_ready_public_no_auth_sources>=15": source_gap["production_ready_public_no_auth_sources"] >= 15,
            "sources_yielding_retained_d365_records>=8": source_gap["sources_yielding_retained_d365_records"] >= 8,
            "sources_yielding_seller_ready_records>=6": source_gap["sources_yielding_seller_ready_records"] >= 6,
        }
        newly_productionized = [
            row["source"]
            for row in rows
            if row["production_ready"] and row["touched_this_run"] and row["last_canary_status"] == "passed"
        ]
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "production_ready_public_no_auth_sources": source_gap["production_ready_public_no_auth_sources"],
            "sources_yielding_retained_d365_records": source_gap["sources_yielding_retained_d365_records"],
            "sources_yielding_seller_ready_records": source_gap["sources_yielding_seller_ready_records"],
            "newly_productionized_sources": newly_productionized,
            "thresholds": thresholds,
            "unmet_thresholds": [name for name, passed in thresholds.items() if not passed],
            "rows": rows,
        }

    def _source_productionization_markdown(self, report: dict[str, Any]) -> str:
        lines = [
            "# Source Productionization Report",
            "",
            f"- production-ready public no-auth sources: {report['production_ready_public_no_auth_sources']}",
            f"- sources yielding retained D365 records: {report['sources_yielding_retained_d365_records']}",
            f"- sources yielding seller-ready records: {report['sources_yielding_seller_ready_records']}",
            "",
            "## Newly productionized or revalidated this run",
        ]
        for name in report["newly_productionized_sources"] or ["none"]:
            lines.append(f"- {name}")
        lines.extend(["", "## Unmet thresholds"])
        for item in report["unmet_thresholds"] or ["none"]:
            lines.append(f"- {item}")
        lines.extend(["", "## Priority sources"])
        for row in report["rows"][:12]:
            reasons = ", ".join(row["gap_reasons"]) if row["gap_reasons"] else "none"
            lines.append(
                f"- {row['source']}: production_ready={row['production_ready']} seller_ready={row['seller_ready_records']} retained={row['retained_d365_records']} gaps={reasons}"
            )
        return "\n".join(lines) + "\n"

    def _cross_surface_truth_report(
        self,
        *,
        overview: dict[str, Any],
        pitchability: dict[str, Any],
        current_pipeline_truth: dict[str, Any],
        source_yield_matrix: dict[str, Any],
        run_scope: dict[str, Any],
    ) -> dict[str, Any]:
        checks = [
            {
                "name": "seller_ready_bid_now_total",
                "values": {
                    "overview": overview["kpis"].get("seller_ready_bid_now_total", 0),
                    "pitchability": pitchability["seller_ready_bid_now_total"],
                    "current_pipeline_truth": current_pipeline_truth["current_bid_now_leads"],
                },
            },
            {
                "name": "seller_ready_pre_position_total",
                "values": {
                    "overview": overview["kpis"].get("seller_ready_pre_position_total", 0),
                    "pitchability": pitchability["seller_ready_pre_position_total"],
                    "current_pipeline_truth": current_pipeline_truth["current_pre_position_leads"],
                },
            },
            {
                "name": "current_actionable_total",
                "values": {
                    "overview": overview["kpis"].get("current_actionable_total", 0),
                    "pitchability": pitchability["current_actionable_total"],
                    "current_pipeline_truth": current_pipeline_truth["current_actionable_total"],
                },
            },
            {
                "name": "sources_yielding_seller_ready_records",
                "values": {
                    "overview": overview["kpis"].get("sources_yielding_seller_ready_records", 0),
                    "source_yield_matrix": source_yield_matrix["summary"]["sources_yielding_seller_ready_records"],
                },
            },
            {
                "name": "sources_touched_this_run",
                "values": {
                    "overview": overview["kpis"].get("sources_touched_this_run", 0),
                    "run_scope": run_scope["sources_touched_this_run"],
                },
            },
        ]
        mismatches = []
        for check in checks:
            normalized = [json.dumps(value, sort_keys=True, default=json_default) for value in check["values"].values()]
            consistent = len(set(normalized)) == 1
            check["consistent"] = consistent
            if not consistent:
                mismatches.append(check)
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "status": "pass" if not mismatches else "fail",
            "checks": checks,
            "mismatches": mismatches,
        }

    def _run_verdict(self, *, current_pipeline_truth: dict[str, Any], pitchability: dict[str, Any], source_gap: dict[str, Any]) -> dict[str, Any]:
        pipeline_works = current_pipeline_truth["pipeline_works"]
        seller_ready_bid = pitchability["seller_ready_bid_now_total"]
        seller_ready_pre = pitchability["seller_ready_pre_position_total"]
        verdict = {
            "generated_at": datetime.now(UTC).isoformat(),
            "pipeline_works": pipeline_works,
            "retained_d365_records": pitchability["real_d365_anchored_live_records_total"],
            "current_actionable_total": pitchability["current_actionable_total"],
            "seller_ready_bid_now_total": seller_ready_bid,
            "seller_ready_pre_position_total": seller_ready_pre,
            "sources_yielding_seller_ready_records": source_gap["sources_yielding_seller_ready_records"],
            "production_ready_public_no_auth_sources": source_gap["production_ready_public_no_auth_sources"],
            "status": "pass" if pipeline_works and seller_ready_bid + seller_ready_pre > 0 else "warning",
            "final_verdict": (
                "Pipeline works and currently has seller-ready leads."
                if pipeline_works and seller_ready_bid + seller_ready_pre > 0
                else "Pipeline ran but did not produce seller-ready leads in this run."
            ),
            "top_blockers": [row["gap_reasons"] for row in source_gap["priority_gaps"][:5]],
        }
        return verdict

    def _run_verdict_markdown(self, verdict: dict[str, Any]) -> str:
        lines = [
            "# Run Verdict",
            "",
            f"- pipeline works: {'yes' if verdict['pipeline_works'] else 'no'}",
            f"- retained D365 records: {verdict['retained_d365_records']}",
            f"- current actionable total: {verdict['current_actionable_total']}",
            f"- seller-ready bid-now total: {verdict['seller_ready_bid_now_total']}",
            f"- seller-ready pre-position total: {verdict['seller_ready_pre_position_total']}",
            f"- sources yielding seller-ready records: {verdict['sources_yielding_seller_ready_records']}",
            f"- production-ready public no-auth sources: {verdict['production_ready_public_no_auth_sources']}",
            "",
            f"Verdict: {verdict['final_verdict']}",
        ]
        return "\n".join(lines) + "\n"

    def _baseline_reference(self) -> dict[str, Any]:
        candidate_paths = sorted(
            [
                path
                for path in self.accountability_root.glob("*-accountability-*")
                if path.is_dir() and path.name != "latest"
            ],
            reverse=True,
        )
        prioritized_paths = [path for path in candidate_paths if path.name.startswith("20260413")] + [
            path for path in candidate_paths if not path.name.startswith("20260413")
        ]
        required_baseline_sources = {"contracts_finder", "find_a_tender", "ted"}
        for path in prioritized_paths:
            try:
                run_scope = json.loads((path / "run_scope_report.json").read_text(encoding="utf-8"))
                pitchability = json.loads((path / "pitchability_report.json").read_text(encoding="utf-8"))
                source_inventory = json.loads((path / "source_inventory.json").read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError):
                continue
            if int(run_scope.get("sources_configured") or 0) < 10:
                continue
            selected_sources = set(run_scope.get("sources_selected_for_run") or [])
            if not required_baseline_sources.issubset(selected_sources):
                continue
            if int(run_scope.get("sources_touched_this_run") or 0) < len(required_baseline_sources):
                continue
            return self._baseline_reference_from_snapshot(
                label=path.name,
                source="artifacts/runs snapshot",
                pitchability=pitchability,
                run_scope=run_scope,
                source_inventory=source_inventory,
            )
        return {
            "label": "2026-04-13 bounded public baseline",
            "source": "fallback_ground_truth",
            "snapshot_path": None,
            "retained_d365_records": 6,
            "pitchable_leads": 4,
            "pitch_now_leads": None,
            "pre_position_leads": None,
            "commercially_actionable_leads": 4,
            "non_pitchable_live_records": 2,
            "stale_or_awarded": None,
            "english_insufficient": None,
            "production_ready_public_no_auth_sources": 3,
            "sources_touched": 3,
            "sources_yielding_retained_d365_records": 1,
            "selected_sources": ["contracts_finder", "find_a_tender", "ted"],
        }

    def _baseline_reference_from_snapshot(
        self,
        *,
        label: str,
        source: str,
        pitchability: dict[str, Any],
        run_scope: dict[str, Any],
        source_inventory: list[dict[str, Any]],
    ) -> dict[str, Any]:
        baseline_split = self._summarize_pitchability_rows(pitchability.get("all_live_records") or [])
        return {
            "label": label,
            "source": source,
            "snapshot_path": str(self.accountability_root / label),
            "retained_d365_records": baseline_split["retained_d365_records"],
            "pitchable_leads": pitchability.get("pitchable_leads_total", 0),
            "pitch_now_leads": baseline_split["pitch_now_leads"],
            "pre_position_leads": baseline_split["pre_position_leads"],
            "commercially_actionable_leads": baseline_split["commercially_actionable_leads"],
            "non_pitchable_live_records": pitchability.get("non_pitchable_live_records_total", 0),
            "stale_or_awarded": baseline_split["stale_or_awarded"],
            "english_insufficient": baseline_split["english_insufficient"],
            "production_ready_public_no_auth_sources": sum(
                1
                for row in source_inventory
                if row.get("enabled") and row.get("production_ready") and row.get("public_access_mode") == "public"
            ),
            "sources_touched": run_scope.get("sources_touched_this_run", 0),
            "sources_yielding_retained_d365_records": run_scope.get("sources_yielding_d365_records_this_run", 0),
            "selected_sources": run_scope.get("sources_selected_for_run") or [],
        }

    def _summarize_pitchability_rows(self, rows: list[dict[str, Any]]) -> dict[str, int]:
        seen_keys: set[str] = set()
        pitch_now = 0
        pre_position = 0
        stale_or_awarded = 0
        english_insufficient = 0
        retained = 0
        for row in rows:
            evaluation = evaluate_record(row, seen_keys=seen_keys)
            if evaluation.anchor_terms:
                retained += 1
            if evaluation.allowed:
                if evaluation.commercial_motion == "pitch_now":
                    pitch_now += 1
                elif evaluation.commercial_motion == "pre_position":
                    pre_position += 1
            else:
                if evaluation.current_actionability_state in {
                    "award_notice",
                    "awarded",
                    "contract_details_only",
                    "closed_submission",
                    "expired",
                    "cancelled",
                }:
                    stale_or_awarded += 1
                if "english_insufficient" in evaluation.reasons or "english_shell_only" in evaluation.reasons:
                    english_insufficient += 1
        return {
            "retained_d365_records": retained,
            "pitch_now_leads": pitch_now,
            "pre_position_leads": pre_position,
            "commercially_actionable_leads": pitch_now + pre_position,
            "stale_or_awarded": stale_or_awarded,
            "english_insufficient": english_insufficient,
        }

    def _before_after_recall_report(
        self,
        *,
        baseline_reference: dict[str, Any],
        run_scope: dict[str, Any],
        pitchability: dict[str, Any],
        source_inventory: list[dict[str, Any]],
    ) -> dict[str, Any]:
        after = {
            "retained_d365_records": pitchability["real_d365_anchored_live_records_total"],
            "pitchable_leads": pitchability["pitchable_leads_total"],
            "pitch_now_leads": pitchability["pitch_now_total"],
            "pre_position_leads": pitchability["pre_position_total"],
            "commercially_actionable_leads": pitchability["pitch_now_total"] + pitchability["pre_position_total"],
            "non_pitchable_live_records": pitchability["non_pitchable_live_records_total"],
            "stale_or_awarded": pitchability["stale_or_awarded_total"],
            "english_insufficient": pitchability["english_insufficient_total"],
            "production_ready_public_no_auth_sources": sum(
                1
                for row in source_inventory
                if row.get("enabled") and row.get("production_ready") and row.get("public_access_mode") == "public"
            ),
            "sources_touched": run_scope["sources_touched_this_run"],
            "sources_yielding_retained_d365_records": run_scope["sources_yielding_d365_records_this_run"],
        }
        delta: dict[str, Any] = {}
        for key, value in after.items():
            before_value = baseline_reference.get(key)
            delta[key] = value - before_value if isinstance(before_value, (int, float)) else None
        targets = {
            "production_ready_public_no_auth_sources>=15": after["production_ready_public_no_auth_sources"] >= 15,
            "sources_yielding_retained_d365_records>=8": after["sources_yielding_retained_d365_records"] >= 8,
            "retained_without_anchor_total==0": pitchability["retained_without_anchor_total"] == 0,
            "duplicates_total==0": pitchability["duplicates_total"] == 0,
            "retained_d365_records>=50": after["retained_d365_records"] >= 50,
            "commercially_actionable_leads>=25": after["commercially_actionable_leads"] >= 25,
            "seller_ready_bid_now_total>=10": pitchability["seller_ready_bid_now_total"] >= 10,
            "seller_ready_pre_position_total>=5": pitchability["seller_ready_pre_position_total"] >= 5,
        }
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "baseline": baseline_reference,
            "after": after,
            "delta": delta,
            "targets": targets,
            "selected_sources_after": run_scope.get("sources_selected_for_run") or [],
            "yielding_sources_after": run_scope.get("sources_yielding_d365_records") or [],
        }

    def _before_after_recall_markdown(self, report: dict[str, Any]) -> str:
        baseline = report["baseline"]
        after = report["after"]
        delta = report["delta"]
        lines = [
            "# Before / After Recall Report",
            "",
            f"- baseline label: {baseline['label']}",
            f"- baseline source: {baseline['source']}",
            f"- after retained D365 records: {after['retained_d365_records']} (delta {delta['retained_d365_records']})",
            f"- after pitchable leads: {after['pitchable_leads']} (delta {delta['pitchable_leads']})",
            f"- after pitch-now leads: {after['pitch_now_leads']} (delta {delta['pitch_now_leads']})",
            f"- after pre-position leads: {after['pre_position_leads']} (delta {delta['pre_position_leads']})",
            f"- after commercially actionable leads: {after['commercially_actionable_leads']} (delta {delta['commercially_actionable_leads']})",
            f"- after production-ready public no-auth sources: {after['production_ready_public_no_auth_sources']} (delta {delta['production_ready_public_no_auth_sources']})",
            f"- after yielding sources with retained D365 records: {after['sources_yielding_retained_d365_records']} (delta {delta['sources_yielding_retained_d365_records']})",
            "",
            "## Target checks",
        ]
        for key, passed in report["targets"].items():
            lines.append(f"- {key}: {'pass' if passed else 'fail'}")
        lines.extend(["", "## Yielding sources after"])
        for name in report["yielding_sources_after"] or ["none"]:
            lines.append(f"- {name}")
        return "\n".join(lines) + "\n"

    def _before_after_pitchability_report(
        self,
        *,
        baseline_reference: dict[str, Any],
        pitchability: dict[str, Any],
    ) -> dict[str, Any]:
        after = {
            "pitchable_leads": pitchability["pitchable_leads_total"],
            "pitch_now_leads": pitchability["pitch_now_total"],
            "pre_position_leads": pitchability["pre_position_total"],
            "monitor_only": pitchability["monitor_only_total"],
            "stale_or_awarded": pitchability["stale_or_awarded_total"],
            "english_insufficient": pitchability["english_insufficient_total"],
        }
        baseline = {
            "pitchable_leads": baseline_reference.get("pitchable_leads", 0),
            "pitch_now_leads": baseline_reference.get("pitch_now_leads", 0),
            "pre_position_leads": baseline_reference.get("pre_position_leads", 0),
            "monitor_only": baseline_reference.get("non_pitchable_live_records", 0),
            "stale_or_awarded": baseline_reference.get("stale_or_awarded", 0),
            "english_insufficient": baseline_reference.get("english_insufficient", 0),
        }
        delta = {key: after[key] - int(baseline.get(key) or 0) for key in after}
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "baseline": baseline,
            "after": after,
            "delta": delta,
        }

    def _before_after_pitchability_markdown(self, report: dict[str, Any]) -> str:
        lines = [
            "# Before / After Pitchability Report",
            "",
        ]
        for key, value in report["after"].items():
            lines.append(f"- {key}: {value} (delta {report['delta'][key]})")
        return "\n".join(lines) + "\n"

    def _parse_iso_dt(self, value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=UTC)
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

    def _lead_age_distribution(self, rows: list[dict[str, Any]], *, as_of_utc: str | None = None) -> dict[str, Any]:
        as_of = self._parse_iso_dt(as_of_utc) or datetime.now(UTC)
        publication_buckets = Counter()
        close_buckets = Counter()
        state_counts = Counter()
        for row in rows:
            state_counts[row.get("current_actionability_state") or "unknown"] += 1
            publication_date = self._parse_iso_dt(row.get("publication_date"))
            if publication_date is None:
                publication_buckets["unknown"] += 1
            else:
                age_days = max((as_of - publication_date).days, 0)
                if age_days <= 7:
                    publication_buckets["0_7_days"] += 1
                elif age_days <= 30:
                    publication_buckets["8_30_days"] += 1
                elif age_days <= 90:
                    publication_buckets["31_90_days"] += 1
                elif age_days <= 180:
                    publication_buckets["91_180_days"] += 1
                else:
                    publication_buckets["181_plus_days"] += 1
            close_date = self._parse_iso_dt(row.get("close_date"))
            if close_date is None:
                close_buckets["unknown"] += 1
            else:
                days_to_close = (close_date - as_of).days
                if days_to_close < 0:
                    close_buckets["closed_or_overdue"] += 1
                elif days_to_close <= 7:
                    close_buckets["closing_0_7_days"] += 1
                elif days_to_close <= 30:
                    close_buckets["closing_8_30_days"] += 1
                elif days_to_close <= 90:
                    close_buckets["closing_31_90_days"] += 1
                else:
                    close_buckets["closing_91_plus_days"] += 1
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "as_of_utc": as_of.isoformat(),
            "publication_age_buckets": dict(publication_buckets),
            "close_horizon_buckets": dict(close_buckets),
            "current_actionability_states": dict(state_counts),
        }

    def _source_yield_matrix(
        self,
        *,
        source_inventory: list[dict[str, Any]],
        run_scope: dict[str, Any],
        pitchability: dict[str, Any],
    ) -> dict[str, Any]:
        as_of = self._parse_iso_dt(pitchability.get("as_of_utc")) or datetime.now(UTC)
        source_by_id = {row["id"]: row for row in source_inventory}
        touched = set(run_scope.get("sources_actually_touched") or [])
        succeeded = set(run_scope.get("sources_with_successful_fetches") or [])
        retained = set(run_scope.get("sources_yielding_d365_records") or [])
        pitchable_sources = self._pitchable_source_names()
        matrix: dict[str, dict[str, Any]] = {
            row["name"]: {
                "source": row["name"],
                "enabled": row["enabled"],
                "production_ready": row["production_ready"],
                "public_access_mode": row["public_access_mode"],
                "operational_state": row["operational_state"],
                "yield_state": row["yield_state"],
                "touched_this_run": row["name"] in touched,
                "successful_this_run": row["name"] in succeeded,
                "yielding_retained_d365_this_run": row["name"] in retained,
                "yielding_pitchable_this_run": row["name"] in pitchable_sources,
                "retained_d365_records": 0,
                "pitchable_records": 0,
                "seller_ready_records": 0,
                "research_ready_records": 0,
                "bid_now_records": 0,
                "pre_position_records": 0,
                "stale_or_awarded_records": 0,
                "english_insufficient_records": 0,
                "query_families": {},
                "dominant_issue_code": row.get("dominant_issue_code"),
            }
            for row in source_inventory
        }
        for candidate in self.session.execute(select(OpportunityCandidate).order_by(desc(OpportunityCandidate.updated_at))).scalars():
            evidence = self.session.get(EvidenceRecord, candidate.evidence_record_id)
            if not evidence or is_demo_record(candidate) or is_demo_record(evidence):
                continue
            source = self.session.get(SourceRegistry, evidence.source_id)
            if not source or source.name not in matrix:
                continue
            evaluation = evaluate_record(candidate, evidence=evidence, today=as_of)
            row = matrix[source.name]
            family = evidence.query_family or candidate.query_family or "unknown"
            family_row = row["query_families"].setdefault(
                family,
                {
                    "query_family": family,
                    "attempted_queries": 0,
                    "executed_queries": 0,
                    "returned_documents": 0,
                    "retained_records": 0,
                    "current_actionable_records": 0,
                    "seller_ready_records": 0,
                    "noisy_records": 0,
                    "zero_yield_flag": False,
                    "partial_yield_flag": False,
                },
            )
            if evaluation.anchor_terms:
                row["retained_d365_records"] += 1
                family_row["retained_records"] += 1
            if evaluation.allowed:
                row["pitchable_records"] += 1
                if evaluation.effective_recommended_action == "bid_now":
                    row["bid_now_records"] += 1
                elif evaluation.effective_recommended_action == "pre_position":
                    row["pre_position_records"] += 1
            if evaluation.sales_handoff_state == "seller_ready":
                row["seller_ready_records"] += 1
                family_row["seller_ready_records"] += 1
            elif evaluation.sales_handoff_state == "research_ready":
                row["research_ready_records"] += 1
            if evaluation.effective_recommended_action in {"bid_now", "pre_position"} and evaluation.current_actionability_state in {
                "open_bid",
                "open_consultation",
                "pre_market_engagement",
                "planned_procurement",
                "framework_or_vehicle",
            }:
                family_row["current_actionable_records"] += 1
            if evaluation.current_actionability_state in {
                "award_notice",
                "awarded",
                "contract_details_only",
                "closed_submission",
                "expired",
                "cancelled",
            }:
                row["stale_or_awarded_records"] += 1
            if "english_insufficient" in evaluation.reasons or "english_shell_only" in evaluation.reasons:
                row["english_insufficient_records"] += 1
            if evaluation.sales_handoff_state != "seller_ready" and evaluation.anchor_terms:
                family_row["noisy_records"] += 1
        for query_row in self._query_rows(run_scope.get("related_crawl_run_ids") or []):
            source_row = source_by_id.get(query_row.get("source_id"))
            if not source_row:
                continue
            row = matrix[source_row["name"]]
            family = query_row.get("query_family") or "unknown"
            family_row = row["query_families"].setdefault(
                family,
                {
                    "query_family": family,
                    "attempted_queries": 0,
                    "executed_queries": 0,
                    "returned_documents": 0,
                    "retained_records": 0,
                    "current_actionable_records": 0,
                    "seller_ready_records": 0,
                    "noisy_records": 0,
                    "zero_yield_flag": False,
                    "partial_yield_flag": False,
                },
            )
            family_row["attempted_queries"] += 1
            if query_row.get("was_executed"):
                family_row["executed_queries"] += 1
            family_row["returned_documents"] += int(query_row.get("docs") or 0)
        rows = []
        for row in matrix.values():
            family_rows = []
            for family_row in row["query_families"].values():
                family_row["zero_yield_flag"] = (
                    family_row["executed_queries"] > 0
                    and family_row["returned_documents"] >= 0
                    and family_row["retained_records"] == 0
                    and family_row["current_actionable_records"] == 0
                    and family_row["seller_ready_records"] == 0
                )
                family_row["partial_yield_flag"] = (
                    family_row["retained_records"] > 0
                    and family_row["seller_ready_records"] == 0
                ) or (
                    family_row["current_actionable_records"] > 0
                    and family_row["seller_ready_records"] < family_row["current_actionable_records"]
                )
                family_rows.append(family_row)
            family_rows.sort(key=lambda item: (-item["seller_ready_records"], -item["retained_records"], item["query_family"]))
            rows.append({**row, "query_families": family_rows})
        rows.sort(
            key=lambda item: (
                not item["production_ready"],
                -(item["seller_ready_records"]),
                -(item["pitchable_records"]),
                -(item["retained_d365_records"]),
                item["source"],
            )
        )
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "rows": rows,
            "summary": {
                "production_ready_public_no_auth_sources": sum(
                    1 for row in rows if row["enabled"] and row["production_ready"] and row["public_access_mode"] == "public"
                ),
                "sources_yielding_retained_d365_records": sum(1 for row in rows if row["yielding_retained_d365_this_run"]),
                "sources_yielding_pitchable_records": sum(1 for row in rows if row["yielding_pitchable_this_run"]),
                "sources_yielding_seller_ready_records": sum(1 for row in rows if row["seller_ready_records"] > 0),
            },
        }

    def _official_regression_truth_report(self, *, as_of_utc: str | None = None) -> dict[str, Any]:
        as_of = self._parse_iso_dt(as_of_utc) or datetime.now(UTC)
        cases = [
            {"procurement_id": "7797171", "label": "BIM specialist Dynamics 365 services", "expected_action": "bid_now", "expected_state": "open_bid", "should_be_pitchable": True},
            {"procurement_id": "238986-2026", "label": "TenneT market consultation", "expected_action": "pre_position", "expected_states": {"open_consultation", "pre_market_engagement", "planned_procurement"}, "should_be_pitchable": True},
            {"procurement_id": "197492-2026", "label": "Finnvera Power Platform notice", "expected_action": "bid_now", "allow_english_insufficient": True},
            {"procurement_id": "7465293", "label": "Coimisiún closed submission", "expected_not_pitchable": True},
            {"procurement_id": "7417532", "label": "IWA closed submission", "expected_not_pitchable": True},
            {"procurement_id": "684084-2025", "label": "Department of Transport awarded notice", "expected_not_pitchable": True},
            {"procurement_id": "151212-2026", "label": "ComReg award notice", "expected_not_pitchable": True},
        ]
        rows: list[dict[str, Any]] = []
        for case in cases:
            procurement_id = case["procurement_id"]
            candidate = self.session.execute(
                select(OpportunityCandidate)
                .where(OpportunityCandidate.procurement_id == procurement_id)
                .order_by(desc(OpportunityCandidate.updated_at))
                .limit(1)
            ).scalar_one_or_none()
            evidence = self.session.get(EvidenceRecord, candidate.evidence_record_id) if candidate else self.session.execute(
                select(EvidenceRecord)
                .where(EvidenceRecord.procurement_id == procurement_id)
                .order_by(desc(EvidenceRecord.publication_date))
                .limit(1)
            ).scalar_one_or_none()
            exclusion = None
            if evidence:
                exclusion = self.session.execute(
                    select(ExclusionAudit)
                    .where(ExclusionAudit.evidence_record_id == evidence.id)
                    .order_by(desc(ExclusionAudit.created_at))
                    .limit(1)
                ).scalar_one_or_none()
            evaluation = evaluate_record(candidate or evidence, evidence=evidence if candidate else None, today=as_of) if (candidate or evidence) else None
            actual_action = evaluation.effective_recommended_action if evaluation else None
            actual_state = evaluation.current_actionability_state if evaluation else None
            reasons = evaluation.reasons if evaluation else []
            pitchable = evaluation.allowed if evaluation else False
            passed = False
            if case.get("expected_not_pitchable"):
                passed = not (pitchable and actual_action == "bid_now")
            elif case.get("allow_english_insufficient"):
                passed = bool(
                    evaluation
                    and (
                        pitchable
                        or "english_insufficient" in reasons
                        or "english_shell_only" in reasons
                    )
                )
            elif case.get("expected_action") == "pre_position":
                passed = bool(
                    evaluation
                    and actual_action == "pre_position"
                    and actual_state in case.get("expected_states", {case.get("expected_state")})
                )
            else:
                passed = bool(
                    evaluation
                    and pitchable
                    and actual_action == case.get("expected_action")
                    and actual_state == case.get("expected_state")
                )
            rows.append(
                {
                    "procurement_id": procurement_id,
                    "label": case["label"],
                    "found_in_evidence": evidence is not None,
                    "found_in_candidates": candidate is not None,
                    "source_url": evidence.source_url if evidence else (candidate.source_url if candidate else None),
                    "source_status_raw": getattr(evidence, "notice_type", None) if evidence else None,
                    "current_actionability_state": actual_state,
                    "recommended_action": actual_action,
                    "pitchable": pitchable,
                    "reasons": reasons,
                    "exclusion_reason": exclusion.reason if exclusion else None,
                    "pass": passed,
                }
            )
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "as_of_utc": as_of.isoformat(),
            "total_cases": len(rows),
            "passing_cases": sum(1 for row in rows if row["pass"]),
            "failing_cases": [row for row in rows if not row["pass"]],
            "cases": rows,
        }

    def _official_regression_truth_markdown(self, report: dict[str, Any]) -> str:
        lines = [
            "# Official Regression Truth Report",
            "",
            f"- cases: {report['total_cases']}",
            f"- passing: {report['passing_cases']}",
            f"- failing: {len(report['failing_cases'])}",
            "",
        ]
        for row in report["cases"]:
            lines.append(
                f"- {row['procurement_id']} | pass={'yes' if row['pass'] else 'no'} | action={row.get('recommended_action') or 'none'} | state={row.get('current_actionability_state') or 'unknown'} | pitchable={row.get('pitchable')}"
            )
        return "\n".join(lines) + "\n"

    def _currentness_audit_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        audit_rows: list[dict[str, Any]] = []
        for row in rows:
            audit_rows.append(
                {
                    "procurement_id": row.get("procurement_id"),
                    "source": row.get("top_source") or row.get("source_url"),
                    "source_status_raw": row.get("source_status_raw"),
                    "source_status_normalized": row.get("current_actionability_state"),
                    "publication_date": row.get("publication_date"),
                    "close_date": row.get("close_date"),
                    "award_date": (row.get("extracted_json") or {}).get("AWARD_DATE") if isinstance(row.get("extracted_json"), dict) else None,
                    "cancellation_date": (row.get("extracted_json") or {}).get("cancellationDate") if isinstance(row.get("extracted_json"), dict) else None,
                    "as_of_utc": row.get("as_of_utc"),
                    "currentness_decision": row.get("current_actionability_state"),
                    "rationale": row.get("actionability_rationale"),
                    "recommended_action": row.get("recommended_action"),
                }
            )
        return audit_rows

    def _current_pipeline_truth_report(
        self,
        *,
        overview: dict[str, Any],
        run_scope: dict[str, Any],
        pitchability: dict[str, Any],
        source_inventory: list[dict[str, Any]],
        source_gap: dict[str, Any],
        truth_consistency: dict[str, Any],
    ) -> dict[str, Any]:
        bid_now_total = pitchability["seller_ready_bid_now_total"]
        pre_position_total = pitchability["seller_ready_pre_position_total"]
        pipeline_works = run_scope["sources_succeeded_this_run"] > 0 or overview["kpis"].get("documents_fetched_7d", 0) > 0
        thresholds = {
            "production_ready_public_no_auth_sources>=15": source_gap["production_ready_public_no_auth_sources"] >= 15,
            "sources_yielding_retained_d365_records>=8": source_gap["sources_yielding_retained_d365_records"] >= 8,
            "sources_yielding_seller_ready_records>=6": source_gap["sources_yielding_seller_ready_records"] >= 6,
            "retained_d365_records>=50": pitchability["real_d365_anchored_live_records_total"] >= 50,
            "current_actionable_total>=25": pitchability["current_actionable_total"] >= 25,
            "seller_ready_total>=15": pitchability["seller_ready_total"] >= 15,
            "seller_ready_bid_now_total>=10": bid_now_total >= 10,
            "seller_ready_pre_position_total>=5": pre_position_total >= 5,
            "retained_without_anchor_total==0": pitchability["retained_without_anchor_total"] == 0,
            "duplicates_total==0": pitchability["duplicates_total"] == 0,
            "truth_consistency_pass": truth_consistency["status"] == "pass",
        }
        unmet = [name for name, passed in thresholds.items() if not passed]
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "as_of_utc": pitchability.get("as_of_utc"),
            "pipeline_works": pipeline_works,
            "data_mode": overview.get("data_mode"),
            "retained_d365_records": pitchability["real_d365_anchored_live_records_total"],
            "current_bid_now_leads": bid_now_total,
            "current_pre_position_leads": pre_position_total,
            "current_actionable_total": pitchability["current_actionable_total"],
            "seller_ready_total": pitchability["seller_ready_total"],
            "research_ready_total": pitchability["research_ready_total"],
            "non_pitchable_live_records_total": pitchability["non_pitchable_live_records_total"],
            "stale_or_awarded_total": pitchability["stale_or_awarded_total"],
            "english_insufficient_total": pitchability["english_insufficient_total"],
            "production_ready_public_no_auth_sources": source_gap["production_ready_public_no_auth_sources"],
            "sources_yielding_retained_d365_records": source_gap["sources_yielding_retained_d365_records"],
            "sources_yielding_pitchable_records": source_gap["sources_yielding_pitchable_records"],
            "sources_yielding_seller_ready_records": source_gap["sources_yielding_seller_ready_records"],
            "yielding_sources": run_scope.get("sources_yielding_d365_records") or [],
            "yielding_pitchable_sources": sorted(self._pitchable_source_names()),
            "truth_consistency": truth_consistency["status"],
            "thresholds": thresholds,
            "unmet_thresholds": unmet,
        }

    def _current_pipeline_truth_markdown(self, report: dict[str, Any]) -> str:
        lines = [
            "# Current Pipeline Truth Report",
            "",
            f"- pipeline works: {'yes' if report['pipeline_works'] else 'no'}",
            f"- data mode: {report['data_mode']}",
            f"- retained D365 records: {report['retained_d365_records']}",
            f"- current bid-now leads: {report['current_bid_now_leads']}",
            f"- current pre-position leads: {report['current_pre_position_leads']}",
            f"- current actionable total: {report['current_actionable_total']}",
            f"- seller-ready total: {report['seller_ready_total']}",
            f"- research-ready total: {report['research_ready_total']}",
            f"- stale or awarded demotions: {report['stale_or_awarded_total']}",
            f"- english-insufficient demotions: {report['english_insufficient_total']}",
            f"- production-ready public no-auth sources: {report['production_ready_public_no_auth_sources']}",
            f"- sources yielding retained D365 records: {report['sources_yielding_retained_d365_records']}",
            f"- sources yielding pitchable records: {report['sources_yielding_pitchable_records']}",
            f"- sources yielding seller-ready records: {report['sources_yielding_seller_ready_records']}",
            f"- truth consistency: {report['truth_consistency']}",
            "",
            "## Unmet thresholds",
        ]
        for item in report["unmet_thresholds"] or ["none"]:
            lines.append(f"- {item}")
        return "\n".join(lines) + "\n"

    def _official_domain_inventory(
        self,
        *,
        run_scope: dict[str, Any],
        pitchability: dict[str, Any],
        source_inventory: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        source_by_name = {row["name"]: row for row in source_inventory}
        hosts: dict[str, dict[str, Any]] = {}
        for name in run_scope.get("sources_actually_touched") or []:
            source = source_by_name.get(name)
            if not source:
                continue
            authenticity = classify_source_authenticity(
                name=source["name"],
                endpoint=source.get("endpoint"),
                source_family=source.get("source_family"),
                public_access_mode=source.get("public_access_mode"),
                data_mode=source.get("data_mode"),
            )
            if authenticity.host:
                hosts[authenticity.host] = {
                    "domain": authenticity.host,
                    "classification": authenticity.authenticity_class,
                    "source_names": [source["name"]],
                    "canonical_allowed": authenticity.canonical_allowed,
                }
        for row in pitchability.get("all_live_records") or []:
            host = normalize_host(row.get("source_url") or row.get("top_source"))
            if not host:
                continue
            current = hosts.setdefault(
                host,
                {
                    "domain": host,
                    "classification": classify_domain(host),
                    "source_names": [],
                    "canonical_allowed": classify_domain(host) == "official_public",
                },
            )
            source_name = row.get("source_name")
            if source_name and source_name not in current["source_names"]:
                current["source_names"].append(source_name)
        return sorted(hosts.values(), key=lambda item: (item["classification"] != "official_public", item["domain"]))

    def _realness_report(
        self,
        *,
        run_scope: dict[str, Any],
        source_inventory: list[dict[str, Any]],
        pitchability: dict[str, Any],
        domain_inventory: list[dict[str, Any]],
    ) -> dict[str, Any]:
        source_by_name = {row["name"]: row for row in source_inventory}
        touched_sources = [source_by_name[name] for name in run_scope.get("sources_actually_touched") or [] if name in source_by_name]
        official_touched = [row["name"] for row in touched_sources if row.get("source_authenticity_class") == "official_public"]
        non_official_touched = [row["name"] for row in touched_sources if row.get("source_authenticity_class") != "official_public"]
        retained_rows = pitchability.get("all_live_records") or []
        seller_ready_rows = pitchability.get("seller_ready_rows") or []
        official_retained = sorted({row.get("source_name") for row in retained_rows if is_canonical_authentic_row(row) and row.get("source_name")})
        official_seller_ready = sorted({row.get("source_name") for row in seller_ready_rows if is_canonical_authentic_row(row) and row.get("source_name")})
        leakage_rows = [
            {
                "procurement_id": row.get("procurement_id"),
                "title": row.get("title"),
                "source_name": row.get("source_name"),
                "source_url": row.get("source_url"),
                "source_authenticity_class": row.get("source_authenticity_class"),
            }
            for row in seller_ready_rows
            if not is_canonical_authentic_row(row)
        ]
        placeholder_domains = [row["domain"] for row in domain_inventory if is_placeholder_host(row["domain"])]
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "official_public_sources_touched": len(official_touched),
            "official_public_sources_touched_names": sorted(official_touched),
            "official_public_sources_yielding_retained_records": len(official_retained),
            "official_public_sources_yielding_retained_record_names": official_retained,
            "official_public_sources_yielding_seller_ready_records": len(official_seller_ready),
            "official_public_sources_yielding_seller_ready_record_names": official_seller_ready,
            "non_official_sources_touched": len(non_official_touched),
            "non_official_source_names": sorted(non_official_touched),
            "synthetic_fixture_leakage_count": len(leakage_rows),
            "seller_ready_authenticity_violations": leakage_rows,
            "placeholder_domain_count": len(placeholder_domains),
            "placeholder_domains": placeholder_domains,
        }

    def _realness_report_markdown(self, report: dict[str, Any]) -> str:
        lines = [
            "# Realness Report",
            "",
            f"- official public sources touched: {report['official_public_sources_touched']}",
            f"- official public sources yielding retained records: {report['official_public_sources_yielding_retained_records']}",
            f"- official public sources yielding seller-ready records: {report['official_public_sources_yielding_seller_ready_records']}",
            f"- non-official sources touched: {report['non_official_sources_touched']}",
            f"- synthetic or fixture leakage count: {report['synthetic_fixture_leakage_count']}",
            f"- placeholder domain count: {report['placeholder_domain_count']}",
        ]
        return "\n".join(lines) + "\n"

    def _ui_truth_audit(
        self,
        *,
        overview: dict[str, Any],
        pitchability: dict[str, Any],
        current_pipeline_truth: dict[str, Any],
    ) -> dict[str, Any]:
        checks = [
            {
                "name": "overview_seller_ready_bid_now_matches_pitchability",
                "consistent": overview["kpis"].get("seller_ready_bid_now_total") == pitchability.get("seller_ready_bid_now_total"),
                "values": {
                    "overview": overview["kpis"].get("seller_ready_bid_now_total"),
                    "pitchability": pitchability.get("seller_ready_bid_now_total"),
                },
            },
            {
                "name": "overview_seller_ready_pre_position_matches_pitchability",
                "consistent": overview["kpis"].get("seller_ready_pre_position_total") == pitchability.get("seller_ready_pre_position_total"),
                "values": {
                    "overview": overview["kpis"].get("seller_ready_pre_position_total"),
                    "pitchability": pitchability.get("seller_ready_pre_position_total"),
                },
            },
            {
                "name": "overview_retained_matches_current_pipeline_truth",
                "consistent": overview["kpis"].get("retained_d365_records") == current_pipeline_truth.get("retained_d365_records"),
                "values": {
                    "overview": overview["kpis"].get("retained_d365_records"),
                    "current_pipeline_truth": current_pipeline_truth.get("retained_d365_records"),
                },
            },
        ]
        mismatches = [check for check in checks if not check["consistent"]]
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "status": "pass" if not mismatches else "fail",
            "checks": checks,
            "mismatches": mismatches,
        }

    def _ui_truth_audit_markdown(self, report: dict[str, Any]) -> str:
        lines = ["# UI Truth Audit", "", f"- status: {report['status']}", ""]
        for check in report["checks"]:
            lines.append(f"- {check['name']}: {'pass' if check['consistent'] else 'fail'}")
        return "\n".join(lines) + "\n"

    def _canonical_bundle_admissibility_report(
        self,
        *,
        latest_run: dict[str, Any] | None,
        run_scope: dict[str, Any],
        source_inventory: list[dict[str, Any]],
        pitchability: dict[str, Any],
        current_pipeline_truth: dict[str, Any],
        official_regression_truth: dict[str, Any],
        harness_schema_validation: dict[str, Any],
        capture_report: list[dict[str, Any]],
        realness_report: dict[str, Any],
    ) -> dict[str, Any]:
        source_by_name = {row["name"]: row for row in source_inventory}
        touched_sources = [source_by_name[name] for name in run_scope.get("sources_actually_touched") or [] if name in source_by_name]
        official_touched = [row for row in touched_sources if row.get("source_authenticity_class") == "official_public"]
        fixture_touched = [row for row in touched_sources if row.get("source_authenticity_class") in {"synthetic_fixture", "demo_seed"}]
        mode = (latest_run or {}).get("mode")
        if fixture_touched:
            run_kind = "fixture"
        elif any(row.get("data_mode") == "demo" for row in touched_sources):
            run_kind = "demo"
        elif (latest_run or {}).get("job_type") in {"doctor", "canary_sweep"}:
            run_kind = "smoke"
        elif mode == "bootstrap_backfill":
            run_kind = "live_public_expanded"
        elif official_touched:
            run_kind = "live_public_baseline"
        else:
            run_kind = "manual_debug"
        if pitchability.get("pitchable_rows") and any(not is_canonical_authentic_row(row) for row in pitchability.get("pitchable_rows") or []):
            evidence_class = "mixed"
        elif fixture_touched:
            evidence_class = "synthetic_fixture"
        elif official_touched:
            evidence_class = "official_public"
        elif any(row.get("data_mode") == "demo" for row in touched_sources):
            evidence_class = "demo_seed"
        else:
            evidence_class = "mixed"
        positive_cases = {"7797171", "238986-2026", "197492-2026"}
        positive_failures = [row for row in official_regression_truth["cases"] if row["procurement_id"] in positive_cases and not row["pass"]]
        negative_failures = [row for row in official_regression_truth["cases"] if row["procurement_id"] not in positive_cases and not row["pass"]]
        placeholder_screenshots = [row["name"] for row in capture_report if row.get("placeholder_used")]
        fail_reasons: list[str] = []
        if not run_kind.startswith("live_public"):
            fail_reasons.append(f"run_kind_not_live_public:{run_kind}")
        if evidence_class != "official_public":
            fail_reasons.append(f"evidence_class_not_official_public:{evidence_class}")
        if realness_report["official_public_sources_touched"] < 5:
            fail_reasons.append("official_public_sources_touched_below_minimum")
        if current_pipeline_truth["production_ready_public_no_auth_sources"] < 6:
            fail_reasons.append("production_ready_public_no_auth_sources_below_minimum")
        if current_pipeline_truth["sources_yielding_retained_d365_records"] < 3:
            fail_reasons.append("sources_yielding_retained_d365_records_below_minimum")
        if current_pipeline_truth["sources_yielding_seller_ready_records"] < 3:
            fail_reasons.append("sources_yielding_seller_ready_records_below_minimum")
        if current_pipeline_truth["current_bid_now_leads"] < 3:
            fail_reasons.append("seller_ready_bid_now_total_below_minimum")
        if current_pipeline_truth["current_pre_position_leads"] < 2:
            fail_reasons.append("seller_ready_pre_position_total_below_minimum")
        if current_pipeline_truth["current_actionable_total"] < 6:
            fail_reasons.append("current_actionable_total_below_minimum")
        if pitchability.get("retained_without_anchor_total") != 0:
            fail_reasons.append("retained_without_anchor_nonzero")
        if pitchability.get("duplicates_total") != 0:
            fail_reasons.append("duplicates_nonzero")
        if realness_report["synthetic_fixture_leakage_count"] > 0:
            fail_reasons.append("synthetic_fixture_leakage_detected")
        if realness_report["placeholder_domain_count"] > 0:
            fail_reasons.append("placeholder_domains_detected")
        if placeholder_screenshots:
            fail_reasons.append("placeholder_screenshots_detected")
        if harness_schema_validation["status"] != "pass":
            fail_reasons.append("harness_schema_invalid")
        if positive_failures:
            fail_reasons.append("official_regression_positive_cases_failed")
        if negative_failures:
            fail_reasons.append("official_regression_negative_cases_failed")
        oracle_admissible = len(fail_reasons) == 0
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "run_id": (latest_run or {}).get("id"),
            "run_kind": run_kind,
            "evidence_class": evidence_class,
            "oracle_admissible": oracle_admissible,
            "admissibility_fail_reasons": fail_reasons,
            "placeholder_screenshots": placeholder_screenshots,
            "official_regression_positive_failures": positive_failures,
            "official_regression_negative_failures": negative_failures,
            "latest_pointers_updated": oracle_admissible,
            "realness_report": {
                "official_public_sources_touched": realness_report["official_public_sources_touched"],
                "official_public_sources_yielding_seller_ready_records": realness_report["official_public_sources_yielding_seller_ready_records"],
                "synthetic_fixture_leakage_count": realness_report["synthetic_fixture_leakage_count"],
                "placeholder_domain_count": realness_report["placeholder_domain_count"],
            },
        }

    def _canonical_bundle_admissibility_markdown(self, report: dict[str, Any]) -> str:
        lines = [
            "# Canonical Bundle Admissibility Report",
            "",
            f"- run kind: {report['run_kind']}",
            f"- evidence class: {report['evidence_class']}",
            f"- oracle admissible: {'yes' if report['oracle_admissible'] else 'no'}",
            "",
            "## Fail reasons",
        ]
        for reason in report["admissibility_fail_reasons"] or ["none"]:
            lines.append(f"- {reason}")
        return "\n".join(lines) + "\n"

    def _load_capture_report(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, list) else []
        except json.JSONDecodeError:
            return []

    def _sync_pointer(self, source: Path, latest: Path) -> None:
        if latest.exists():
            shutil.rmtree(latest)
        shutil.copytree(source, latest)

    def _promote_verification_candidate(self, *, target: Path, zip_path: Path, admissibility: dict[str, Any]) -> dict[str, Any]:
        latest = self.root / "latest"
        latest_live_public = self.root / "latest-live-public"
        latest_fixture = self.root / "latest-fixture"
        latest_demo = self.root / "latest-demo"
        rejected_root = self.root / "latest-candidate-rejected"
        rejected_path: str | None = None
        promoted_pointer = latest
        if admissibility["run_kind"] == "fixture":
            self._sync_pointer(target, latest_fixture)
            shutil.copy2(zip_path, self.root / "latest-fixture.zip")
            promoted_pointer = latest_fixture
        elif admissibility["run_kind"] == "demo":
            self._sync_pointer(target, latest_demo)
            shutil.copy2(zip_path, self.root / "latest-demo.zip")
            promoted_pointer = latest_demo
        elif admissibility["oracle_admissible"]:
            self._sync_pointer(target, latest_live_public)
            shutil.copy2(zip_path, self.root / "latest-live-public.zip")
            self._sync_pointer(target, latest)
            shutil.copy2(zip_path, self.root / "latest.zip")
            promoted_pointer = latest_live_public
        else:
            rejected_root.mkdir(parents=True, exist_ok=True)
            rejected_target = rejected_root / target.name
            if rejected_target.exists():
                shutil.rmtree(rejected_target)
            shutil.copytree(target, rejected_target)
            rejected_path = str(rejected_target)
            promoted_pointer = rejected_target
        return {
            "latest_path": str(promoted_pointer),
            "latest_zip_path": str(self.root / "latest.zip"),
            "latest_live_public_path": str(latest_live_public),
            "latest_fixture_path": str(latest_fixture),
            "latest_demo_path": str(latest_demo),
            "rejected_candidate_path": rejected_path,
        }

    def _promote_accountability_candidate(self, *, target: Path, zip_path: Path, admissibility: dict[str, Any]) -> dict[str, Any]:
        latest = self.accountability_root / "latest"
        latest_live_public = self.accountability_root / "latest-live-public"
        latest_fixture = self.accountability_root / "latest-fixture"
        latest_demo = self.accountability_root / "latest-demo"
        rejected_root = self.accountability_root / "latest-candidate-rejected"
        rejected_path: str | None = None
        promoted_pointer = latest
        if admissibility["run_kind"] == "fixture":
            self._sync_pointer(target, latest_fixture)
            shutil.copy2(zip_path, self.accountability_root / "latest-fixture.zip")
            promoted_pointer = latest_fixture
        elif admissibility["run_kind"] == "demo":
            self._sync_pointer(target, latest_demo)
            shutil.copy2(zip_path, self.accountability_root / "latest-demo.zip")
            promoted_pointer = latest_demo
        elif admissibility["oracle_admissible"]:
            self._sync_pointer(target, latest_live_public)
            shutil.copy2(zip_path, self.accountability_root / "latest-live-public.zip")
            self._sync_pointer(target, latest)
            shutil.copy2(zip_path, self.accountability_root / "latest.zip")
            promoted_pointer = latest_live_public
        else:
            rejected_root.mkdir(parents=True, exist_ok=True)
            rejected_target = rejected_root / target.name
            if rejected_target.exists():
                shutil.rmtree(rejected_target)
            shutil.copytree(target, rejected_target)
            rejected_path = str(rejected_target)
            promoted_pointer = rejected_target
        return {
            "latest_path": str(promoted_pointer),
            "latest_zip_path": str(self.accountability_root / "latest.zip"),
            "latest_live_public_path": str(latest_live_public),
            "latest_fixture_path": str(latest_fixture),
            "latest_demo_path": str(latest_demo),
            "rejected_candidate_path": rejected_path,
        }

    def _bundle_lineage(self) -> dict[str, Any]:
        oracle_root = self.settings.artifact_root / "oracle"
        entries: list[dict[str, Any]] = []
        for path in sorted(oracle_root.glob("*.zip")):
            status = "canonical" if path.name == "d365-opps-oracle-latest.zip" else "superseded"
            if "preview" in path.name:
                status = "preview"
            if path.stat().st_size == 0:
                status = "incomplete"
            entries.append(
                {
                    "path": str(path),
                    "status": status,
                    "size_bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                    "modified_at": json_default(datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)),
                }
            )
        latest_pointers = []
        for root in (self.accountability_root, self.root, oracle_root):
            for name, status in (
                ("latest", "canonical"),
                ("latest-live-public", "live_public"),
                ("latest-fixture", "fixture"),
                ("latest-demo", "demo"),
                ("latest-candidate-rejected", "rejected_candidate"),
            ):
                latest_pointers.append(
                    {
                        "path": str(root / name),
                        "exists": (root / name).exists(),
                        "status": status,
                    }
                )
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "oracle_zips": entries,
            "latest_pointers": latest_pointers,
        }

    def _harness_schema_validation_report(self) -> dict[str, Any]:
        schema_path = Path("harness/agent-native-repo-harness-map.schema.json")
        map_path = Path("harness/agent-native-repo-harness-map.json")
        if not schema_path.exists() or not map_path.exists():
            missing = [str(path) for path in (schema_path, map_path) if not path.exists()]
            return {
                "generated_at": datetime.now(UTC).isoformat(),
                "status": "fail",
                "schema_path": str(schema_path),
                "map_path": str(map_path),
                "missing": missing,
                "error_count": len(missing),
                "errors": [{"path": item, "message": "missing file"} for item in missing],
                "template_marker_paths": [],
            }
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        payload = json.loads(map_path.read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema)
        errors = [
            {
                "path": ".".join(str(part) for part in error.path) or "$",
                "message": error.message,
            }
            for error in validator.iter_errors(payload)
        ]

        template_paths: list[str] = []

        def _walk(node: Any, prefix: str = "$") -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    next_prefix = f"{prefix}.{key}"
                    if key == "templateOnly" and value is True:
                        template_paths.append(next_prefix)
                    if key == "template" and value is True:
                        template_paths.append(next_prefix)
                    if isinstance(value, str) and value in {"Example Repository", "example.repo"}:
                        template_paths.append(next_prefix)
                    _walk(value, next_prefix)
            elif isinstance(node, list):
                for index, value in enumerate(node):
                    _walk(value, f"{prefix}[{index}]")

        _walk(payload)
        status = "pass" if not errors and not template_paths else "fail"
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "status": status,
            "schema_path": str(schema_path),
            "map_path": str(map_path),
            "error_count": len(errors),
            "errors": errors,
            "template_marker_paths": template_paths,
        }

    def _repo_harness_compliance_report(self, schema_validation: dict[str, Any]) -> dict[str, Any]:
        required_files = [
            "AGENTS.md",
            "CODEOWNERS",
            ".gitattributes",
            "docs/architecture.md",
            "docs/agent-handoff.md",
            "docs/verification.md",
            "docs/export-policy.md",
            "docs/for-oracle-to-read.md",
            "harness/agent-native-repo-harness-map.json",
            "harness/agent-native-repo-harness-map.schema.json",
            "harness/agent-native-repo-harness-map.notes.md",
        ]
        rows = []
        missing = []
        for rel in required_files:
            exists = Path(rel).exists()
            rows.append({"path": rel, "exists": exists})
            if not exists:
                missing.append(rel)
        gitattributes_text = Path(".gitattributes").read_text(encoding="utf-8") if Path(".gitattributes").exists() else ""
        checks = [
            {"name": "required_files_exist", "consistent": len(missing) == 0, "values": {"missing": missing}},
            {"name": "harness_schema_valid", "consistent": schema_validation["status"] == "pass", "values": schema_validation},
            {
                "name": "export_boundary_defined",
                "consistent": "export-ignore" in gitattributes_text,
                "values": {"has_export_ignore": "export-ignore" in gitattributes_text},
            },
            {
                "name": "canonical_latest_live_public_pointer_exists",
                "consistent": (self.accountability_root / "latest-live-public").exists() or (self.root / "latest-live-public").exists(),
                "values": {
                    "runs_latest_live_public": (self.accountability_root / "latest-live-public").exists(),
                    "verification_latest_live_public": (self.root / "latest-live-public").exists(),
                },
            },
        ]
        mismatches = [check for check in checks if not check["consistent"]]
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "status": "pass" if not mismatches else "fail",
            "required_files": rows,
            "checks": checks,
            "mismatches": mismatches,
        }

    def _repo_harness_compliance_markdown(self, report: dict[str, Any]) -> str:
        lines = ["# Repo Harness Compliance Report", "", f"- status: {report['status']}", "", "## Required files"]
        for row in report["required_files"]:
            lines.append(f"- {row['path']}: {'present' if row['exists'] else 'missing'}")
        lines.extend(["", "## Checks"])
        for check in report["checks"]:
            lines.append(f"- {check['name']}: {'pass' if check['consistent'] else 'fail'}")
        return "\n".join(lines) + "\n"

    def _dead_weight_audit(self) -> dict[str, Any]:
        candidates = [
            ("artifacts/bundle_root", "delete"),
            ("artifacts/D365-Opportunity-Engine-Session-Bundle", "archive"),
            ("artifacts/package_stage", "delete"),
            ("artifacts/d365-opportunity-engine-bundle.zip", "archive"),
            ("artifacts/oracle-session-bundle-20260413.md", "archive"),
            (".pytest_cache", "delete"),
        ]
        rows = []
        for rel, recommendation in candidates:
            path = Path(rel)
            if not path.exists():
                continue
            rows.append(
                {
                    "path": rel,
                    "recommendation": recommendation,
                    "size_bytes": path.stat().st_size if path.is_file() else sum(item.stat().st_size for item in path.rglob("*") if item.is_file()),
                }
            )
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "candidates": rows,
            "delete_count": sum(1 for row in rows if row["recommendation"] == "delete"),
            "archive_count": sum(1 for row in rows if row["recommendation"] == "archive"),
        }

    def _dead_weight_audit_markdown(self, report: dict[str, Any]) -> str:
        lines = ["# Dead Weight Audit", ""]
        for row in report["candidates"]:
            lines.append(f"- {row['path']}: {row['recommendation']} ({row['size_bytes']} bytes)")
        if not report["candidates"]:
            lines.append("- none")
        return "\n".join(lines) + "\n"

    def _removal_manifest(self) -> dict[str, Any]:
        tracked = [
            "artifacts/bundle_root",
            "artifacts/package_stage",
            "artifacts/D365-Opportunity-Engine-Session-Bundle",
            "artifacts/d365-opportunity-engine-bundle.zip",
            ".pytest_cache",
        ]
        rows = []
        for rel in tracked:
            exists = Path(rel).exists()
            rows.append(
                {
                    "path": rel,
                    "status": "kept" if exists else "deleted_or_absent",
                }
            )
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "items": rows,
        }

    def _source_gap_report(self, source_inventory: list[dict[str, Any]], run_scope: dict[str, Any] | None = None) -> dict[str, Any]:
        run_scope = run_scope or {}
        touched = set(run_scope.get("sources_actually_touched") or [])
        succeeded = set(run_scope.get("sources_with_successful_fetches") or [])
        retained = set(run_scope.get("sources_yielding_d365_records") or [])
        pitchable_sources = self._pitchable_source_names()
        seller_ready_sources = self._seller_ready_source_names()
        gap_rows: list[dict[str, Any]] = []
        for row in sorted(source_inventory, key=lambda item: (not item["enabled"], item["name"])):
            reasons: list[str] = []
            if not row["enabled"]:
                reasons.append("disabled")
            if row["public_access_mode"] != "public":
                reasons.append(f"access_{row['public_access_mode']}")
            if not row["parser_implemented"]:
                reasons.append("parser_not_implemented")
            if row["source_capabilities"].get("adapter_grade") in {None, "scaffold", "listing_wrapper"}:
                reasons.append("scaffold_only")
            if row["enabled"] and not row["production_ready"]:
                if row["last_canary_status"] != "passed":
                    reasons.append("canary_not_passing")
                if row["operational_state"] != "healthy":
                    reasons.append(f"operational_{row['operational_state']}")
            if row["name"] not in touched:
                reasons.append("not_touched_in_latest_scope")
            elif row["name"] not in succeeded:
                reasons.append("touched_without_successful_fetch")
            elif row["name"] not in retained:
                reasons.append("no_retained_d365_records")
            if row["yield_state"] in {"low_yield", "zero_yield", "noisy", "stale"}:
                reasons.append(f"yield_{row['yield_state']}")
            dominant_issue_code = self._dominant_issue_code(row["id"])
            if dominant_issue_code:
                reasons.append(f"issue_{dominant_issue_code}")
            gap_rows.append(
                {
                    "name": row["name"],
                    "enabled": row["enabled"],
                    "public_access_mode": row["public_access_mode"],
                    "parser_implemented": row["parser_implemented"],
                    "production_ready": row["production_ready"],
                    "production_ready_candidate": row.get("production_ready_candidate"),
                    "touched_this_run": row["name"] in touched,
                    "successful_this_run": row["name"] in succeeded,
                    "yielding_retained_d365_this_run": row["name"] in retained,
                    "yielding_pitchable_this_run": row["name"] in pitchable_sources,
                    "yielding_seller_ready_this_run": row["name"] in seller_ready_sources,
                    "operational_state": row["operational_state"],
                    "yield_state": row["yield_state"],
                    "dominant_issue_code": dominant_issue_code,
                    "last_good_canary": row.get("last_canary_at") if row.get("last_canary_status") == "passed" else None,
                    "last_good_pitchable_emit": self._last_good_pitchable_emit(row["id"]),
                    "known_blind_spot_reason": row.get("known_blind_spot_reason"),
                    "gap_reasons": sorted(dict.fromkeys(reasons)),
                }
            )
        prioritized = [
            row
            for row in gap_rows
            if row["enabled"] and (not row["production_ready"] or not row["yielding_retained_d365_this_run"])
        ]
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "production_ready_public_no_auth_sources": sum(
                1 for row in gap_rows if row["enabled"] and row["public_access_mode"] == "public" and row["production_ready"]
            ),
            "sources_yielding_retained_d365_records": sum(1 for row in gap_rows if row["yielding_retained_d365_this_run"]),
            "sources_yielding_pitchable_records": sum(1 for row in gap_rows if row["yielding_pitchable_this_run"]),
            "sources_yielding_seller_ready_records": sum(1 for row in gap_rows if row["yielding_seller_ready_this_run"]),
            "sources": gap_rows,
            "priority_gaps": prioritized[:12],
        }

    def _source_gap_markdown(self, report: dict[str, Any]) -> str:
        lines = [
            "# Source Gap Report",
            "",
            f"- production-ready public no-auth sources: {report['production_ready_public_no_auth_sources']}",
            f"- sources yielding retained D365 records: {report['sources_yielding_retained_d365_records']}",
            f"- sources yielding pitchable records: {report['sources_yielding_pitchable_records']}",
            f"- sources yielding seller-ready records: {report['sources_yielding_seller_ready_records']}",
            "",
            "## Priority gaps",
        ]
        for row in report["priority_gaps"] or []:
            reasons = ", ".join(row["gap_reasons"]) if row["gap_reasons"] else "none"
            lines.append(f"- {row['name']}: {reasons}")
        if not report["priority_gaps"]:
            lines.append("- none")
        return "\n".join(lines) + "\n"

    def _dominant_issue_code(self, source_id: str) -> str | None:
        issue = self.session.execute(
            select(SourceIssue)
            .where(SourceIssue.source_id == source_id, SourceIssue.state == "open")
            .order_by(desc(SourceIssue.last_seen_at))
            .limit(1)
        ).scalar_one_or_none()
        return issue.issue_code if issue else None

    def _pitchable_source_names(self) -> set[str]:
        seen_keys: set[str] = set()
        names: set[str] = set()
        for candidate in self.session.execute(
            select(OpportunityCandidate).order_by(desc(OpportunityCandidate.updated_at))
        ).scalars():
            evidence = self.session.get(EvidenceRecord, candidate.evidence_record_id)
            if is_demo_record(candidate) or is_demo_record(evidence):
                continue
            evaluation = evaluate_record(candidate, evidence=evidence, seen_keys=seen_keys)
            if evaluation.allowed and evidence:
                names.add(self._source_name(evidence.source_id))
        return names

    def _seller_ready_source_names(self) -> set[str]:
        seen_keys: set[str] = set()
        names: set[str] = set()
        for candidate in self.session.execute(
            select(OpportunityCandidate).order_by(desc(OpportunityCandidate.updated_at))
        ).scalars():
            evidence = self.session.get(EvidenceRecord, candidate.evidence_record_id)
            if is_demo_record(candidate) or is_demo_record(evidence):
                continue
            evaluation = evaluate_record(candidate, evidence=evidence, seen_keys=seen_keys)
            if evaluation.sales_handoff_state == "seller_ready" and evidence:
                names.add(self._source_name(evidence.source_id))
        return names

    def _last_good_pitchable_emit(self, source_id: str) -> str | None:
        for candidate in self.session.execute(
            select(OpportunityCandidate)
            .join(EvidenceRecord, EvidenceRecord.id == OpportunityCandidate.evidence_record_id)
            .where(EvidenceRecord.source_id == source_id)
            .order_by(desc(OpportunityCandidate.updated_at))
        ).scalars():
            evidence = self.session.get(EvidenceRecord, candidate.evidence_record_id)
            if is_demo_record(candidate) or is_demo_record(evidence):
                continue
            if evaluate_record(candidate, evidence=evidence).allowed:
                return json_default(candidate.updated_at)
        return None

    def _rejected_near_misses(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for exclusion in self.session.execute(
            select(ExclusionAudit).order_by(desc(ExclusionAudit.created_at))
        ).scalars():
            if exclusion.reason not in {"no_d365_anchor", "missing_microsoft_anchor"}:
                continue
            evidence = self.session.get(EvidenceRecord, exclusion.evidence_record_id)
            if not evidence:
                continue
            source = self.session.get(SourceRegistry, evidence.source_id)
            details = exclusion.details_json or {}
            rows.append(
                {
                    "title": evidence.title,
                    "source": source.name if source else evidence.source_id,
                    "buyer": evidence.buyer_name,
                    "reason_rejected": exclusion.reason,
                    "matched_service_terms": details.get("matched_service_terms", []),
                    "matched_procurement_terms": details.get("matched_procurement_terms", []),
                    "missing_microsoft_anchor_reason": exclusion.reason,
                    "query_family": evidence.query_family or details.get("query_family"),
                    "source_url": evidence.source_url,
                    "retrieval_score": exclusion.retrieval_score,
                    "matched_positive_terms": exclusion.matched_positive_terms_json,
                    "matched_negative_terms": exclusion.matched_negative_terms_json,
                }
            )
        return rows

    def _truth_consistency_report(
        self,
        *,
        overview: dict[str, Any],
        dataset_diagnosis: dict[str, Any],
        source_inventory: list[dict[str, Any]],
        run_scope: dict[str, Any],
        pitchability: dict[str, Any],
    ) -> dict[str, Any]:
        production_ready_inventory = sum(
            1 for row in source_inventory if row["enabled"] and row["production_ready"] and row["data_mode"] == "live"
        )
        parser_implemented_inventory = sum(
            1 for row in source_inventory if row["enabled"] and row["parser_implemented"] and row["data_mode"] == "live"
        )
        enabled_live_source_ids = {row["id"] for row in source_inventory if row["enabled"] and row["data_mode"] == "live"}
        actual_live_records = sum(
            1 for row in self.session.execute(select(OpportunityCandidate)).scalars() if not is_demo_record(row)
        ) + sum(1 for row in self.session.execute(select(MarketSignal)).scalars() if not is_demo_record(row))
        latest_canaries: dict[str, SourceCanaryResult] = {}
        for canary in self.session.execute(select(SourceCanaryResult).order_by(desc(SourceCanaryResult.timestamp))).scalars():
            latest_canaries.setdefault(canary.source_id, canary)
        open_issues = {
            issue.source_id: issue
            for issue in self.session.execute(select(SourceIssue).where(SourceIssue.state == "open")).scalars()
        }
        checks: list[dict[str, Any]] = []

        def add_check(name: str, values: dict[str, Any]) -> None:
            normalized = [json.dumps(value, sort_keys=True, default=json_default) for value in values.values()]
            checks.append({"name": name, "values": values, "consistent": len(set(normalized)) == 1})

        add_check(
            "parser_implemented_enabled",
            {
                "overview": overview["kpis"].get("parser_implemented_enabled", 0),
                "diagnostics": dataset_diagnosis.get("parser_implemented_enabled", 0),
                "source_inventory": parser_implemented_inventory,
            },
        )
        add_check(
            "production_ready_enabled",
            {
                "overview": overview["kpis"].get("production_ready_enabled", 0),
                "diagnostics": dataset_diagnosis.get("prod_ready_enabled", 0),
                "source_inventory": production_ready_inventory,
            },
        )
        add_check("live_records", {"overview": overview["kpis"].get("live_records", 0), "actual": actual_live_records})
        add_check(
            "sources_touched_this_run",
            {"overview": overview["kpis"].get("sources_touched_this_run", 0), "run_scope": run_scope["sources_touched_this_run"]},
        )
        add_check(
            "sources_succeeded_this_run",
            {"overview": overview["kpis"].get("sources_succeeded_this_run", 0), "run_scope": run_scope["sources_succeeded_this_run"]},
        )
        add_check(
            "sources_yielding_real_records_this_run",
            {
                "overview": overview["kpis"].get("sources_yielding_real_records_this_run", 0),
                "run_scope": run_scope["sources_yielding_real_records_this_run"],
            },
        )
        add_check(
            "sources_yielding_d365_records_this_run",
            {
                "overview": overview["kpis"].get("sources_yielding_d365_records_this_run", 0),
                "run_scope": run_scope["sources_yielding_d365_records_this_run"],
            },
        )
        checks.append(
            {
                "name": "retained_without_anchor_total",
                "values": {"pitchability_report": pitchability["retained_without_anchor_total"]},
                "consistent": pitchability["retained_without_anchor_total"] == 0,
            }
        )
        pitchable_rows = pitchability.get("pitchable_rows") or []
        seller_ready_rows = pitchability.get("seller_ready_rows") or []
        research_ready_rows = pitchability.get("research_ready_rows") or []
        checks.append(
            {
                "name": "pitchable_row_total_matches_summary",
                "values": {
                    "summary": pitchability["pitchable_leads_total"],
                    "rows": len(pitchable_rows),
                },
                "consistent": pitchability["pitchable_leads_total"] == len(pitchable_rows),
            }
        )
        bid_now_rows = [row for row in seller_ready_rows if row.get("recommended_action") == "bid_now"]
        pre_position_rows = [row for row in seller_ready_rows if row.get("recommended_action") == "pre_position"]
        checks.append(
            {
                "name": "pitch_now_row_count_matches_summary",
                "values": {"summary": pitchability["seller_ready_bid_now_total"], "rows": len(bid_now_rows)},
                "consistent": pitchability["seller_ready_bid_now_total"] == len(bid_now_rows),
            }
        )
        checks.append(
            {
                "name": "pre_position_row_count_matches_summary",
                "values": {"summary": pitchability["seller_ready_pre_position_total"], "rows": len(pre_position_rows)},
                "consistent": pitchability["seller_ready_pre_position_total"] == len(pre_position_rows),
            }
        )
        checks.append(
            {
                "name": "seller_ready_row_total_matches_summary",
                "values": {"summary": pitchability["seller_ready_total"], "rows": len(seller_ready_rows)},
                "consistent": pitchability["seller_ready_total"] == len(seller_ready_rows),
            }
        )
        checks.append(
            {
                "name": "research_ready_row_total_matches_summary",
                "values": {"summary": pitchability["research_ready_total"], "rows": len(research_ready_rows)},
                "consistent": pitchability["research_ready_total"] == len(research_ready_rows),
            }
        )
        stale_in_pitchable = [
            {
                "procurement_id": row.get("procurement_id"),
                "title": row.get("title"),
                "current_actionability_state": row.get("current_actionability_state"),
            }
            for row in pitchable_rows
            if row.get("current_actionability_state") in {
                "award_notice",
                "awarded",
                "contract_details_only",
                "closed_submission",
                "expired",
                "cancelled",
            }
        ]
        checks.append(
            {
                "name": "stale_or_awarded_excluded_from_pitchable",
                "values": {"rows": stale_in_pitchable},
                "consistent": len(stale_in_pitchable) == 0,
            }
        )
        english_in_pitchable = [
            {
                "procurement_id": row.get("procurement_id"),
                "title": row.get("title"),
                "pitchability_reasons": row.get("pitchability_reasons"),
            }
            for row in pitchable_rows
            if "english_insufficient" in (row.get("pitchability_reasons") or [])
            or "english_shell_only" in (row.get("pitchability_reasons") or [])
        ]
        checks.append(
            {
                "name": "english_insufficient_excluded_from_pitchable",
                "values": {"rows": english_in_pitchable},
                "consistent": len(english_in_pitchable) == 0,
            }
        )
        seller_ready_monitor_rows = [
            {
                "procurement_id": row.get("procurement_id"),
                "title": row.get("title"),
                "recommended_action": row.get("recommended_action"),
                "sales_handoff_state": row.get("sales_handoff_state"),
                "pursuit_recommendation": row.get("pursuit_recommendation"),
            }
            for row in seller_ready_rows
            if row.get("pursuit_recommendation") != "seller_ready"
        ]
        checks.append(
            {
                "name": "seller_ready_rows_do_not_carry_monitor_recommendations",
                "values": {"rows": seller_ready_monitor_rows},
                "consistent": len(seller_ready_monitor_rows) == 0,
            }
        )
        bid_now_missing_close_date = [
            {
                "procurement_id": row.get("procurement_id"),
                "title": row.get("title"),
                "source_status_raw": row.get("source_status_raw"),
                "actionability_rationale": row.get("actionability_rationale"),
            }
            for row in bid_now_rows
            if not row.get("close_date") and not row.get("source_verified_open_without_close_date")
        ]
        checks.append(
            {
                "name": "seller_ready_bid_now_rows_have_close_date_or_source_verified_open_state",
                "values": {"rows": bid_now_missing_close_date},
                "consistent": len(bid_now_missing_close_date) == 0,
            }
        )
        source_yield_matrix = self._source_yield_matrix(
            source_inventory=source_inventory,
            run_scope=run_scope,
            pitchability=pitchability,
        )
        ambiguous_query_rollups = [
            {
                "source": row["source"],
                "query_family": family["query_family"],
            }
            for row in source_yield_matrix["rows"]
            for family in row["query_families"]
            if family["zero_yield_flag"] and (
                family["retained_records"] > 0
                or family["current_actionable_records"] > 0
                or family["seller_ready_records"] > 0
            )
        ]
        checks.append(
            {
                "name": "query_family_rollups_are_not_simultaneously_zero_yield_and_yielding",
                "values": {"rows": ambiguous_query_rollups},
                "consistent": len(ambiguous_query_rollups) == 0,
            }
        )
        canary_issue_gaps = []
        for source_id, canary in latest_canaries.items():
            if source_id not in enabled_live_source_ids:
                continue
            if canary.status == "passed":
                continue
            if source_id not in open_issues:
                canary_issue_gaps.append(
                    {
                        "source_id": source_id,
                        "issue_code": canary.issue_code,
                        "timestamp": json_default(canary.timestamp),
                    }
                )
        checks.append(
            {
                "name": "failed_canaries_surface_issues",
                "values": {"missing_issue_records": canary_issue_gaps},
                "consistent": len(canary_issue_gaps) == 0,
            }
        )
        mismatches = [check for check in checks if not check["consistent"]]
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "status": "pass" if not mismatches else "fail",
            "checks": checks,
            "mismatches": mismatches,
        }

    def _accountability_summary(
        self,
        *,
        latest_run: dict[str, Any] | None,
        overview: dict[str, Any],
        run_scope: dict[str, Any],
        pitchability: dict[str, Any],
        truth_consistency: dict[str, Any],
    ) -> str:
        pipeline_works = run_scope["sources_succeeded_this_run"] > 0 or overview["kpis"].get("documents_fetched_7d", 0) > 0
        production_ready_yielding = [
            row["name"]
            for row in self.ops.list_sources(limit=2000, offset=0)["items"]
            if row["production_ready"] and row["name"] in set(run_scope["sources_yielding_d365_records"])
        ]
        blockers = [
            issue["issue_code"]
            for issue in self.ops.list_issues(limit=20, offset=0)["items"]
            if issue["state"] == "open"
        ]
        lines = [
            "# Accountability Summary",
            "",
            f"- run id: {latest_run.get('id') if latest_run else 'none'}",
            f"- pipeline works: {'yes' if pipeline_works else 'no'}",
            f"- seller-ready leads exist: {'yes' if pitchability['seller_ready_total'] > 0 else 'no'}",
            f"- seller-ready leads total: {pitchability['seller_ready_total']}",
            f"- seller-ready bid-now total: {pitchability['seller_ready_bid_now_total']}",
            f"- seller-ready pre-position total: {pitchability['seller_ready_pre_position_total']}",
            f"- production-ready sources currently yielding retained D365 records: {', '.join(production_ready_yielding) if production_ready_yielding else 'none'}",
            f"- truth consistency: {truth_consistency['status']}",
            "",
            "## Sources touched in this run",
        ]
        for name in run_scope["sources_actually_touched"] or ["none"]:
            lines.append(f"- {name}")
        lines.extend(["", "## Blockers"])
        for code in blockers[:10] or ["none"]:
            lines.append(f"- {code}")
        lines.extend(["", "## Top pitchable leads"])
        if pitchability["current_top_pitchable_leads"]:
            for row in pitchability["current_top_pitchable_leads"]:
                lines.append(f"- {row['title']} | {row.get('buyer') or 'unknown'} | {row.get('country') or 'unknown'}")
        else:
            lines.append("- none")
        return "\n".join(lines) + "\n"

    def _events_for_runs(self, job_run_ids: list[str], crawl_run_ids: list[str]) -> list[dict[str, Any]]:
        job_ids = set(job_run_ids)
        crawl_ids = set(crawl_run_ids)
        rows: list[dict[str, Any]] = []
        for row in self.session.execute(select(PipelineEvent).order_by(PipelineEvent.timestamp)).scalars():
            if row.job_run_id in job_ids or row.run_id in job_ids or row.crawl_run_id in crawl_ids:
                rows.append(redact_mapping({key: json_default(value) for key, value in vars(row).items() if not key.startswith("_")}))
        return rows

    def _fetch_rows(self, crawl_run_ids: list[str]) -> list[dict[str, Any]]:
        crawl_ids = set(crawl_run_ids)
        rows: list[dict[str, Any]] = []
        for row in self.session.execute(select(SourceFetchEvent).order_by(SourceFetchEvent.timestamp)).scalars():
            if row.crawl_run_id not in crawl_ids:
                continue
            rows.append(redact_mapping({key: json_default(value) for key, value in vars(row).items() if not key.startswith("_")}))
        return rows

    def _query_rows(self, crawl_run_ids: list[str]) -> list[dict[str, Any]]:
        crawl_ids = set(crawl_run_ids)
        rows: list[dict[str, Any]] = []
        for row in self.session.execute(select(QueryExecution).order_by(QueryExecution.id)).scalars():
            if row.crawl_run_id not in crawl_ids:
                continue
            rows.append(redact_mapping({key: json_default(value) for key, value in vars(row).items() if not key.startswith("_")}))
        return rows

    def _issue_rows(self, source_ids: list[str]) -> list[dict[str, Any]]:
        source_id_set = set(source_ids)
        rows: list[dict[str, Any]] = []
        for row in self.session.execute(select(SourceIssue).order_by(desc(SourceIssue.last_seen_at))).scalars():
            if source_id_set and row.source_id not in source_id_set:
                continue
            rows.append(redact_mapping({key: json_default(value) for key, value in vars(row).items() if not key.startswith("_")}))
        return rows

    def _trace_summary(
        self,
        *,
        latest_run: dict[str, Any] | None,
        events: list[dict[str, Any]],
        fetch_events: list[dict[str, Any]],
        query_rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        trace_ids = sorted({row.get("trace_id") for row in [*events, *fetch_events, *query_rows] if row.get("trace_id")})
        request_ids = sorted({row.get("request_id") for row in [*events, *fetch_events, *query_rows] if row.get("request_id")})
        span_ids = sorted({row.get("span_id") for row in [*events, *fetch_events, *query_rows] if row.get("span_id")})
        return {
            "run_id": latest_run.get("id") if latest_run else None,
            "trace_ids": trace_ids,
            "request_ids": request_ids,
            "span_ids": span_ids,
            "event_count": len(events),
            "fetch_event_count": len(fetch_events),
            "query_execution_count": len(query_rows),
        }

    def _collect_log_lines(self, run_ids: list[str]) -> list[dict[str, Any]]:
        lines: list[dict[str, Any]] = []
        seen: set[str] = set()
        for run_id in run_ids:
            log_path = self.settings.log_root / "runs" / f"{run_id}.ndjson"
            if not log_path.exists():
                continue
            for raw_line in log_path.read_text(encoding="utf-8").splitlines():
                if not raw_line.strip() or raw_line in seen:
                    continue
                seen.add(raw_line)
                try:
                    lines.append(redact_mapping(json.loads(raw_line)))
                except json.JSONDecodeError:
                    lines.append({"message": raw_line})
        return lines

    def _stdout_stub(self, event_rows: list[dict[str, Any]]) -> str:
        return "\n".join(
            [
                "Structured JSON logs are canonical for this run.",
                f"Pipeline events captured: {len(event_rows)}",
                "See app.log.jsonl and events.jsonl for the authoritative timeline.",
            ]
        ) + "\n"

    def _stderr_stub(self, exception_payload: dict[str, Any] | None) -> str:
        if not exception_payload:
            return "No stderr was captured for this run. See exception.json if a job-level failure occurred.\n"
        return json.dumps(exception_payload, indent=2, default=json_default) + "\n"

    def _exception_payload(self, latest_run: dict[str, Any] | None, run_scope: dict[str, Any]) -> dict[str, Any] | None:
        payload: dict[str, Any] = {"run_errors": []}
        if latest_run and latest_run.get("errors_json"):
            payload["run_errors"].extend(latest_run["errors_json"])
        for job_id in run_scope["related_job_run_ids"]:
            job = self.session.get(JobRun, job_id)
            if job and job.errors_json:
                payload["run_errors"].extend(job.errors_json)
        payload["run_errors"] = payload["run_errors"][:50]
        return payload if payload["run_errors"] else None

    def _copy_dashboard_screenshots(self, bundle_path: Path, ui_dir: Path) -> list[Path]:
        outputs: list[Path] = []
        source_dir = bundle_path / "dashboard_screenshots"
        for name in ("overview.png", "sources.png", "runs.png", "diagnostics.png"):
            destination = ui_dir / name
            origin = source_dir / name
            if origin.exists():
                shutil.copy2(origin, destination)
            else:
                write_placeholder_png(destination)
            outputs.append(destination)
        capture_report = source_dir / "capture_report.json"
        if capture_report.exists():
            destination = ui_dir / "capture_report.json"
            shutil.copy2(capture_report, destination)
            outputs.append(destination)
        return outputs

    def _write_export_files(self, target_root: Path, base_name: str, rows: list[dict[str, Any]]) -> list[Path]:
        return [
            self._write_csv_samples(target_root / f"{base_name}.csv", rows),
            self._write_ndjson(target_root / f"{base_name}.jsonl", rows),
        ]

    def _artifact_file_manifest(self, target: Path) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for path in sorted(target.rglob("*")):
            if not path.is_file():
                continue
            rows.append(
                {
                    "path": str(path.relative_to(target)),
                    "size_bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
        return rows

    def _write_checksums_with_relative_paths(self, files: list[Path], output: Path, root: Path) -> Path:
        lines = []
        for path in sorted(files):
            if not path.exists() or not path.is_file():
                continue
            lines.append(f"{sha256_file(path)}  {path.relative_to(root)}")
        output.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return output

    def _write_json(self, path: Path, payload: Any) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, default=json_default, indent=2), encoding="utf-8")
        return path

    def _write_text(self, path: Path, payload: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
        return path

    def _write_ndjson(self, path: Path, rows: Iterable[dict[str, Any]]) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, default=json_default) + "\n")
        return path

    def _write_csv_samples(self, path: Path, rows: list[dict[str, Any]]) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as handle:
            fieldnames = sorted({key for row in rows for key in row.keys()}) if rows else ["empty"]
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            if rows:
                writer.writerows(rows)
        return path

    def _write_metrics(self, path: Path) -> Path:
        sources = self.ops.list_sources(limit=2000, offset=0)["items"]
        overview = self.ops.overview()
        canaries = self.diagnostics._canary_rows(limit=2000)
        issues = self.ops.list_issues(limit=2000, offset=0)["items"]
        lines = [
            "# TYPE d365_sources_total gauge",
            f"d365_sources_total {len(sources)}",
            "# TYPE d365_canary_results_total gauge",
            f"d365_canary_results_total {len(canaries)}",
            "# TYPE d365_empty_dataset_alert gauge",
            f"d365_empty_dataset_alert {1 if overview['kpis'].get('live_records', 0) == 0 else 0}",
        ]
        for state in sorted({row['operational_state'] for row in sources}):
            count = sum(1 for row in sources if row["operational_state"] == state)
            lines.append(f'd365_sources_by_state{{state="{state}"}} {count}')
        for issue_code, count in sorted((Counter(row["issue_code"] for row in issues if row["issue_code"])).items()):
            lines.append(f'd365_issue_total{{issue_code="{issue_code}"}} {count}')
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def _write_dashboard_screenshots(self, directory: Path) -> list[Path]:
        routes = {
            "overview.png": "/",
            "sources.png": "/sources",
            "runs.png": "/runs",
            "diagnostics.png": "/diagnostics",
        }
        outputs: list[Path] = []
        capture_report: list[dict[str, Any]] = []
        base_url = (self.settings.web_base_url or "").rstrip("/")
        runner = self._resolve_playwright_runner()
        for name, route in routes.items():
            path = directory / name
            captured = False
            report_entry: dict[str, Any] = {
                "name": name,
                "route": route,
                "base_url": base_url,
                "capture_enabled": self.settings.screenshot_capture_enabled,
                "runner": runner,
                "placeholder_used": True,
            }
            if self.settings.screenshot_capture_enabled and base_url and runner:
                try:
                    result = subprocess.run(
                        [runner, "playwright", "screenshot", f"{base_url}{route}", str(path.resolve())],
                        cwd=Path("apps/web"),
                        check=True,
                        timeout=120,
                        capture_output=True,
                        text=True,
                    )
                    captured = path.exists()
                    report_entry.update(
                        {
                            "captured": captured,
                            "returncode": result.returncode,
                            "stdout": result.stdout.strip(),
                            "stderr": result.stderr.strip(),
                        }
                    )
                except Exception as exc:
                    captured = False
                    report_entry.update(
                        {
                            "captured": False,
                            "error": repr(exc),
                        }
                    )
            elif not runner:
                report_entry["error"] = "playwright_runner_not_found"
            if not captured:
                write_placeholder_png(path)
                report_entry["placeholder_used"] = True
            else:
                report_entry["placeholder_used"] = False
                report_entry["size_bytes"] = path.stat().st_size
            outputs.append(path)
            capture_report.append(report_entry)
        outputs.append(self._write_json(directory / "capture_report.json", capture_report))
        return outputs

    def _resolve_playwright_runner(self) -> str | None:
        return shutil.which("npx.cmd") or shutil.which("npx")

    def _sync_latest(self, source: Path, latest: Path) -> None:
        if latest.exists():
            shutil.rmtree(latest)
        shutil.copytree(source, latest)

    def _zip_bundle(self, target: Path) -> Path:
        zip_path = target.with_suffix(".zip")
        if zip_path.exists():
            zip_path.unlink()
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(target.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(target))
        return zip_path
