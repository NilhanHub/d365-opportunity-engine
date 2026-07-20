from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from d365opps.config import get_settings
from d365opps.models import (
    CrawlRun,
    EvidenceRecord,
    JobRun,
    OperationalState,
    PipelineEvent,
    QueryExecution,
    SourceCanaryResult,
    SourceFetchEvent,
    SourceIssue,
    SourceRegistry,
    SourceStateTransition,
)
from d365opps.ops import OpsService


def _iso(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


class DiagnosticsService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.settings = get_settings()
        self.ops = OpsService(session)

    def diagnostics_overview(self) -> dict[str, Any]:
        overview = self.ops.overview()
        sources = self.ops.list_sources(limit=2000, offset=0)["items"]
        runs = self.ops.list_runs(limit=20, offset=0)["items"]
        canaries = self._canary_rows(limit=50)
        blockers = self.ops.list_issues(limit=20, offset=0)["items"]
        return {
            "system_mode": overview["data_mode"],
            "demo_mode": overview["demo_mode"],
            "dataset_diagnosis": self.explain_zero(),
            "empty_dataset_diagnosis": self.explain_zero() if overview["kpis"].get("live_records", 0) == 0 else None,
            "source_readiness_mix": self._source_readiness_mix(sources),
            "canary_board": canaries,
            "source_health_evidence": sources[:25],
            "latest_run_evidence": runs[:10],
            "top_blockers": blockers[:10],
            "root_cause_tree": self._root_cause_tree(overview, sources, blockers, canaries),
            "recommended_actions": self._recommended_actions(overview, sources, blockers, canaries),
            "latest_verification_bundle": self.latest_verification_bundle(),
        }

    def explain_zero(self) -> dict[str, Any]:
        overview = self.ops.overview()
        sources = self.ops.list_sources(limit=2000, offset=0)["items"]
        runs = self.ops.list_runs(limit=2000, offset=0)["items"]
        canaries = self._canary_rows(limit=2000)
        query_rows = self.ops.list_queries(limit=2000, offset=0)["items"]
        latest_backfill = overview["kpis"].get("last_successful_backfill")
        latest_refresh = overview["kpis"].get("last_live_refresh")
        enabled_sources = [source for source in sources if source["enabled"] and source["data_mode"] == "live"]
        parser_implemented = [source for source in enabled_sources if source["parser_implemented"]]
        prod_ready = [source for source in enabled_sources if source["production_ready"]]
        scaffold = [
            source
            for source in enabled_sources
            if not source["parser_implemented"] or source["source_family"] in {"registry", "generic_web"}
        ]
        passed_canaries = [row for row in canaries if row["status"] == "passed"]
        successful_fetches = int(
            self.session.execute(select(func.count(SourceFetchEvent.id)).where(SourceFetchEvent.success_flag.is_(True))).scalar_one()
            or 0
        )
        docs_7d = overview["kpis"].get("documents_fetched_7d", 0)
        evidence_7d = overview["kpis"].get("evidence_records_extracted", 0)
        live_records = overview["kpis"].get("live_records", 0)
        root_causes: list[str] = []
        if not latest_backfill:
            root_causes.append("no bootstrap backfill completed")
        if successful_fetches == 0:
            root_causes.append("no successful fetches recorded")
        if scaffold and len(scaffold) >= max(1, len(enabled_sources) // 2):
            root_causes.append("majority of enabled sources are scaffold-only or discovery-first")
        zero_yield_families = [
            row["query_family"]
            for row in query_rows
            if row["requests"] >= 1 and row["yield_ratio"] == 0 and row["query_family"]
        ]
        if zero_yield_families:
            root_causes.append("one or more query families executed with zero retained yield")
        if not passed_canaries and enabled_sources:
            root_causes.append("canaries have not passed on the live-enabled public baseline")
        if docs_7d > 0 and evidence_7d == 0:
            root_causes.append("documents were fetched but extraction retained no evidence")
        if evidence_7d > 0 and live_records == 0:
            root_causes.append("evidence was extracted but all records were excluded or never promoted")
        if not root_causes:
            root_causes.append("live dataset is non-empty or no primary failure condition is currently active")
        next_actions = self._recommended_actions(overview, sources, self.ops.list_issues(limit=50, offset=0)["items"], canaries)
        return {
            "dataset_mode": overview["data_mode"],
            "live_records": live_records,
            "demo_records": overview["kpis"].get("demo_records", 0),
            "last_successful_backfill": latest_backfill,
            "last_successful_live_refresh": latest_refresh,
            "enabled_sources": len(enabled_sources),
            "parser_implemented_enabled": len(parser_implemented),
            "prod_ready_enabled": len(prod_ready),
            "scaffold_enabled": len(scaffold),
            "canaries_passed": len(passed_canaries),
            "successful_fetches": successful_fetches,
            "docs_fetched_7d": docs_7d,
            "evidence_extracted_7d": evidence_7d,
            "top_root_causes": [{"rank": idx + 1, "cause": cause} for idx, cause in enumerate(root_causes[:5])],
            "next_actions": next_actions[:5],
            "recent_runs": runs[:5],
        }

    def source_diagnostics(self, source_id: str) -> dict[str, Any]:
        source = self.ops.get_source(source_id)
        canaries = [
            row
            for row in self._canary_rows(limit=100)
            if row["source_id"] == source_id
        ]
        transitions = [
            {
                "id": row.id,
                "timestamp": _iso(row.timestamp),
                "previous_operational_state": row.previous_operational_state.value if row.previous_operational_state else None,
                "new_operational_state": row.new_operational_state.value,
                "previous_yield_state": row.previous_yield_state.value if row.previous_yield_state else None,
                "new_yield_state": row.new_yield_state.value,
                "reason_code": row.reason_code,
                "evidence": row.evidence_json,
                "run_id": row.run_id,
                "trace_id": row.trace_id,
            }
            for row in self.session.execute(
                select(SourceStateTransition)
                .where(SourceStateTransition.source_id == source_id)
                .order_by(desc(SourceStateTransition.timestamp))
                .limit(50)
            ).scalars()
        ]
        reason = self._source_reason(source)
        return {
            "source": source,
            "health_reason": reason,
            "canaries": canaries,
            "state_transitions": transitions,
            "recent_fetch_events": source.get("runs", [{}])[0].get("fetch_events", []) if source.get("runs") else [],
            "next_actions": self._source_actions(source, canaries),
        }

    def run_diagnostics(self, run_id: str) -> dict[str, Any]:
        run = self.ops.get_run(run_id)
        events = [
            self._event_row(row)
            for row in self.session.execute(
                select(PipelineEvent)
                .where((PipelineEvent.run_id == run_id) | (PipelineEvent.job_run_id == run_id) | (PipelineEvent.crawl_run_id == run_id))
                .order_by(PipelineEvent.timestamp)
                .limit(400)
            ).scalars()
        ]
        return {
            "run": run,
            "events": events,
            "event_counts": dict(Counter(event["event_type"] for event in events)),
            "issues": [
                issue
                for issue in self.ops.list_issues(limit=100, offset=0)["items"]
                if issue.get("crawl_run_id") == run_id
            ],
        }

    def explain_metric(self, metric_name: str) -> dict[str, Any]:
        overview = self.ops.overview()
        value = overview["kpis"].get(metric_name)
        explanation = {
            "healthy_sources": "Sources with recent successful fetch or passing canary and no dominant open blocker state.",
            "approved_opportunities": "Opportunity candidates currently marked approved in the system of record.",
            "live_records": "Opportunities and signals not tagged as demo content.",
            "documents_fetched_24h": "Documents counted from source_daily_metric in the last 24 hours.",
            "opportunity_candidates_created": "Rows in the opportunity candidate table regardless of approval state.",
        }.get(metric_name, "Metric explanation not specialized; inspect overview and diagnostics drill-down.")
        return {"metric": metric_name, "value": value, "explanation": explanation}

    def latest_verification_bundle(self) -> dict[str, Any] | None:
        manifest = self.settings.artifact_root / "verification" / "latest" / "manifest.json"
        if not manifest.exists():
            return None
        accountability = self.settings.artifact_root / "runs" / "latest"
        return {
            "path": str(manifest.parent),
            "manifest": manifest.read_text(encoding="utf-8"),
            "latest_accountability_path": str(accountability),
        }

    def _canary_rows(self, *, limit: int) -> list[dict[str, Any]]:
        return [
            {
                "id": row.id,
                "source_id": row.source_id,
                "source_name": (self.session.get(SourceRegistry, row.source_id).name if row.source_id else None),
                "timestamp": _iso(row.timestamp),
                "canary_name": row.canary_name,
                "status": row.status,
                "docs_seen": row.docs_seen,
                "expected_marker_found": row.expected_marker_found,
                "parser_ok": row.parser_ok,
                "latency_ms": row.latency_ms,
                "issue_code": row.issue_code,
                "evidence": row.evidence_json,
                "trace_id": row.trace_id,
            }
            for row in self.session.execute(select(SourceCanaryResult).order_by(desc(SourceCanaryResult.timestamp)).limit(limit)).scalars()
        ]

    def _source_readiness_mix(self, sources: list[dict[str, Any]]) -> dict[str, int]:
        return {
            "configured": len(sources),
            "enabled": sum(1 for row in sources if row["enabled"]),
            "healthy": sum(1 for row in sources if row["operational_state"] == OperationalState.HEALTHY.value),
            "candidate": sum(1 for row in sources if row["forthcoming_state"] == "discovered_pending_review"),
            "unsupported": sum(1 for row in sources if row["operational_state"] == OperationalState.UNSUPPORTED.value),
            "blocked": sum(1 for row in sources if row["operational_state"] in {"blocked", "robots_disallowed", "auth_required"}),
            "throttled": sum(1 for row in sources if row["operational_state"] == "throttled"),
        }

    def _root_cause_tree(
        self,
        overview: dict[str, Any],
        sources: list[dict[str, Any]],
        blockers: list[dict[str, Any]],
        canaries: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        tree: list[dict[str, Any]] = []
        if overview["kpis"].get("live_records", 0) == 0:
            tree.append({"node": "live_dataset_empty", "children": self.explain_zero()["top_root_causes"]})
        if blockers:
            tree.append({"node": "blockers", "children": [{"cause": blocker["issue_code"]} for blocker in blockers[:5]]})
        if canaries:
            failures = [row for row in canaries if row["status"] != "passed"]
            tree.append({"node": "canaries", "children": [{"cause": row["issue_code"] or row["status"]} for row in failures[:5]]})
        if not tree:
            tree.append({"node": "healthy", "children": [{"cause": "No dominant causal blocker is currently active."}]})
        return tree

    def _recommended_actions(
        self,
        overview: dict[str, Any],
        sources: list[dict[str, Any]],
        blockers: list[dict[str, Any]],
        canaries: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        live_enabled_sources = [source for source in sources if source["enabled"] and source["data_mode"] == "live"]
        production_ready_sources = [source for source in live_enabled_sources if source["production_ready"]]
        non_yielding_prod_ready = [
            source
            for source in production_ready_sources
            if source["yield_state"] in {"low_yield", "noisy", "zero_yield", "stale"}
        ]
        scaffold_enabled = [
            source
            for source in live_enabled_sources
            if not source["parser_implemented"] or source["source_family"] in {"registry", "generic_web"}
        ]
        if not overview["kpis"].get("last_successful_backfill"):
            actions.append({"priority": 1, "action": "Run bootstrap_backfill on the public no-auth baseline."})
        if scaffold_enabled and len(scaffold_enabled) >= max(1, len(live_enabled_sources) // 2):
            actions.append(
                {
                    "priority": 2,
                    "action": "Convert additional enabled scaffold or discovery-first sources into production-ready adapters before treating coverage as real.",
                }
            )
        if any(source["operational_state"] == "parser_broken" for source in sources):
            actions.append({"priority": 3, "action": "Inspect parser-broken sources and update extraction contracts."})
        if any(blocker["issue_code"] == "throttled_429" for blocker in blockers):
            actions.append({"priority": 4, "action": "Reduce page rate or batch size for throttled sources and re-run canaries."})
        if canaries and not any(row["status"] == "passed" for row in canaries):
            actions.append({"priority": 5, "action": "Resolve canary failures before trusting healthy labels."})
        if non_yielding_prod_ready:
            names = ", ".join(sorted(source["name"] for source in non_yielding_prod_ready[:4]))
            actions.append(
                {
                    "priority": 6,
                    "action": f"Inspect healthy but weak-yield production-ready sources ({names}) for noisy query families and retention fallout.",
                }
            )
        if overview["kpis"].get("sources_yielding_d365_records_this_run", 0) <= 1 and production_ready_sources:
            actions.append(
                {
                    "priority": 7,
                    "action": "Expand the bounded live baseline beyond the single yielding source and compare retained D365 output by source family.",
                }
            )
        if overview["kpis"].get("live_records", 0) > 0:
            actions.append(
                {
                    "priority": 8,
                    "action": "Review `artifacts/runs/latest/pitchability_report.md` and triage retained live records into pursue, monitor, or reject.",
                }
            )
        if overview["kpis"].get("live_records", 0) == 0 and overview["kpis"].get("demo_records", 0) > 0:
            actions.append({"priority": 9, "action": "Filter out demo rows and focus on live bootstrap diagnostics."})
        return sorted(actions, key=lambda row: row["priority"])

    def _source_reason(self, source: dict[str, Any]) -> dict[str, Any]:
        return {
            "operational_state": source["operational_state"],
            "yield_state": source["yield_state"],
            "health_status": source["health_status"],
            "last_successful_fetch": source["last_successful_fetch"],
            "last_attempted_fetch": source["last_attempted_fetch"],
            "open_issue_count": source["open_issue_count"],
            "recommended_fix": source["recommended_fix"],
        }

    def _source_actions(self, source: dict[str, Any], canaries: list[dict[str, Any]]) -> list[str]:
        actions: list[str] = []
        if source["operational_state"] in {"blocked", "robots_disallowed"}:
            actions.append("Use alternative public surfaces or leave blocked; do not keep retrying blindly.")
        if source["operational_state"] == "auth_required":
            actions.append("Complete the documented onboarding path and rerun connectivity checks.")
        if source["yield_state"] in {"zero_yield", "stale"}:
            actions.append("Run canary + refresh and inspect query execution or browse-only filtering.")
        if source["operational_state"] == "parser_broken":
            actions.append("Inspect recent raw documents and update parser rules before relabeling healthy.")
        if not canaries:
            actions.append("Add or run canaries for this source so healthy labels are evidence-backed.")
        return actions or ["No immediate corrective action suggested."]

    def _event_row(self, row: PipelineEvent) -> dict[str, Any]:
        return {
            "id": row.id,
            "timestamp": _iso(row.timestamp),
            "level": row.level,
            "event_type": row.event_type,
            "service": row.service,
            "component": row.component,
            "phase": row.phase,
            "run_id": row.run_id,
            "job_run_id": row.job_run_id,
            "crawl_run_id": row.crawl_run_id,
            "source_id": row.source_id,
            "source_name": row.source_name,
            "query_id": row.query_id,
            "query_family": row.query_family,
            "document_id": row.document_id,
            "evidence_id": row.evidence_id,
            "opportunity_id": row.opportunity_id,
            "account_id": row.account_id,
            "trace_id": row.trace_id,
            "span_id": row.span_id,
            "request_id": row.request_id,
            "message": row.message,
            "issue_code": row.issue_code,
            "status": row.status,
            "payload": row.payload_json,
        }
