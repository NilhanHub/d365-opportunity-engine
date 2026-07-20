from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
import re

import httpx
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from d365opps.authenticity import classify_source_authenticity
from d365opps.attachments import AttachmentHarvester
from d365opps.blob_store import LocalBlobStore
from d365opps.bootstrap import seed_sources
from d365opps.classifier import OpportunityClassifier
from d365opps.config import get_settings
from d365opps.correlation import correlation_scope, current_correlation, ensure_correlation, new_child_span, set_correlation
from d365opps.dedupe import OpportunityClusterer
from d365opps.demo import purge_demo_data
from d365opps.discovery import SourceDiscoveryService
from d365opps.enrichment import OpportunityEnricher
from d365opps.evaluation import RecallHarness
from d365opps.exporters import DatasetExporter, ExportResult
from d365opps.forensics import ForensicRecorder, low_cardinality_error, redact_mapping, sha256_bytes
from d365opps.models import (
    AccountCluster,
    CandidateStatus,
    ClusterStatus,
    CurrentActionabilityState,
    Contact,
    CrawlRun,
    CrawlStatus,
    EvidenceRecord,
    ExclusionAudit,
    IssueSeverity,
    JobRun,
    JobType,
    MarketSignal,
    OperationalState,
    PipelineEvent,
    OpportunityCandidate,
    OpportunityCluster,
    Organization,
    PublicAccessMode,
    QueryExecution,
    RawDocument,
    RadarLane,
    RecommendedAction,
    RouteToMarket,
    SourceCanaryResult,
    SignalCluster,
    SourceDailyMetric,
    SourceFetchEvent,
    SourceHealthStatus,
    SourceIssue,
    SourceRegistry,
    SourceStateTransition,
    YieldState,
)
from d365opps.oracle_instructions import OracleInstructionWriter
from d365opps.oracle_bundle import OracleBundleBuilder
from d365opps.pitchability import (
    current_actionability_state_for_record,
    effective_recommended_action_for_record,
    english_readiness_for_record,
    retention_gate,
)
from d365opps.retrieval import QueryCompiler, QueryExecutionPlanner, RetrievalAssessment, RetrievalScorer
from d365opps.source_universe import SourceUniverseService
from d365opps.sources import SourceAdapterFactory
from d365opps.verification import VerificationService


@dataclass(slots=True)
class CrawlBudget:
    mode: str
    max_pages: int
    max_notices: int
    max_detail_pages: int
    max_attachments: int
    max_runtime_seconds: int


class PipelineService:
    def __init__(
        self,
        session: Session,
        *,
        blob_store: LocalBlobStore | None = None,
        classifier: OpportunityClassifier | None = None,
        enricher: OpportunityEnricher | None = None,
        clusterer: OpportunityClusterer | None = None,
        source_factory: SourceAdapterFactory | None = None,
        exporter: DatasetExporter | None = None,
        query_compiler: QueryCompiler | None = None,
        retrieval_scorer: RetrievalScorer | None = None,
        attachment_harvester: AttachmentHarvester | None = None,
        discovery_service: SourceDiscoveryService | None = None,
        recall_harness: RecallHarness | None = None,
    ) -> None:
        self.session = session
        self.settings = get_settings()
        self.blob_store = blob_store or LocalBlobStore()
        self.classifier = classifier or OpportunityClassifier()
        self.enricher = enricher or OpportunityEnricher()
        self.clusterer = clusterer or OpportunityClusterer()
        self.source_factory = source_factory or SourceAdapterFactory()
        self.exporter = exporter or DatasetExporter()
        self.query_compiler = query_compiler or QueryCompiler()
        self.query_planner = QueryExecutionPlanner(self.query_compiler)
        self.retrieval_scorer = retrieval_scorer or RetrievalScorer(query_compiler=self.query_compiler)
        self.attachment_harvester = attachment_harvester or AttachmentHarvester(self.blob_store)
        self.discovery_service = discovery_service or SourceDiscoveryService(session)
        self.recall_harness = recall_harness or RecallHarness(
            retrieval_scorer=self.retrieval_scorer,
            classifier=self.classifier,
        )
        self.source_universe = SourceUniverseService(session)
        self.recorder = ForensicRecorder(session)
        self.verifier = VerificationService(session)
        self.oracle_writer = OracleInstructionWriter(session)
        self.oracle_bundle_builder = OracleBundleBuilder()

    def init_sources(self) -> list[SourceRegistry]:
        return seed_sources(self.session)

    def list_sources(self, *, enabled_only: bool = False) -> list[SourceRegistry]:
        statement = select(SourceRegistry).order_by(SourceRegistry.tier, SourceRegistry.name)
        if enabled_only:
            statement = statement.where(SourceRegistry.enabled.is_(True))
        return list(self.session.execute(statement).scalars())

    def discover_sources(
        self,
        *,
        source_names: list[str] | None = None,
        limit: int | None = None,
        auto_enable_threshold: float = 0.95,
    ) -> list[dict[str, Any]]:
        job = self._start_job(JobType.DISCOVER_SOURCES, metadata={"source_names": source_names or [], "limit": limit})
        try:
            candidates = self.discovery_service.discover_sources(
                source_names=source_names,
                limit=limit,
                auto_enable_threshold=auto_enable_threshold,
            )
            job.candidates_created = len(candidates)
            self._finish_job(job, CrawlStatus.SUCCEEDED)
            return [
                {
                    "candidate_name": candidate.candidate_name,
                    "endpoint": candidate.endpoint,
                    "confidence": candidate.confidence,
                    "discovery_status": candidate.discovery_status.value,
                    "robots_status": candidate.robots_status,
                    "auto_enable_eligible": candidate.auto_enable_eligible,
                }
                for candidate in candidates
            ]
        except Exception as exc:
            self._finish_job(job, CrawlStatus.FAILED, errors=[{"message": str(exc), "type": type(exc).__name__}])
            raise

    def query_preview(self, *, source_names: list[str] | None = None) -> list[dict[str, Any]]:
        statement = select(SourceRegistry).order_by(SourceRegistry.tier, SourceRegistry.name)
        if source_names:
            statement = statement.where(SourceRegistry.name.in_(source_names))
        sources = list(self.session.execute(statement).scalars())
        previews: list[dict[str, Any]] = []
        for source in sources:
            plan = self.query_planner.plan(source, mode="incremental_sync")
            for rendered in plan.queries:
                previews.append(rendered.as_dict())
        return previews

    def source_health(self, *, enabled_only: bool = False) -> list[dict[str, Any]]:
        return self.discovery_service.source_health(enabled_only=enabled_only)

    def discover_accounts(self) -> list[dict[str, Any]]:
        self._refresh_account_clusters()
        clusters = list(self.session.execute(select(AccountCluster).order_by(AccountCluster.heat_score.desc())).scalars())
        return [
            {
                "account_id": cluster.id,
                "canonical_name": cluster.canonical_name,
                "country": cluster.country,
                "heat_score": cluster.heat_score,
                "installed_product_guess": cluster.installed_product_guess,
                "trigger_strength": cluster.trigger_strength,
                "corroboration_count": cluster.corroboration_count,
            }
            for cluster in clusters
        ]

    def coverage_report(self) -> dict[str, Any]:
        sources = self.list_sources(enabled_only=False)
        candidates = list(self.session.execute(select(OpportunityCandidate)).scalars())
        signals = list(self.session.execute(select(MarketSignal)).scalars())
        records = [*candidates, *signals]
        lane_counts: dict[str, int] = {}
        action_counts: dict[str, int] = {}
        country_lanes: dict[str, set[str]] = {}
        english_count = 0
        enriched_count = 0
        for record in records:
            lane = getattr(record, "signal_lane", None)
            lane_value = lane.value if hasattr(lane, "value") else str(lane or "unknown")
            lane_counts[lane_value] = lane_counts.get(lane_value, 0) + 1
            action = getattr(record, "recommended_action", None)
            action_value = action.value if hasattr(action, "value") else str(action or "unknown")
            action_counts[action_value] = action_counts.get(action_value, 0) + 1
            country = getattr(record, "country", None) or "unknown"
            country_lanes.setdefault(country, set()).add(lane_value)
            if getattr(record, "english_evidence_source", None):
                english_count += 1
            if getattr(record, "account_cluster_id", None) or getattr(record, "organization_id", None):
                enriched_count += 1
        blocked = [source.name for source in sources if source.public_access_mode.value in {"invitation_only", "unsupported"}]
        return {
            "sources_enabled": sum(1 for source in sources if source.enabled),
            "sources_active": sum(1 for source in sources if source.last_successful_fetch_at),
            "countries_covered": sorted({source.country for source in sources if source.country}),
            "lane_coverage_by_country": {country: sorted(lanes) for country, lanes in country_lanes.items()},
            "last_successful_fetch_per_source": {source.name: source.last_successful_fetch_at for source in sources},
            "records_by_lane": lane_counts,
            "english_evidence_ratio": round(english_count / max(len(records), 1), 4),
            "buyer_or_account_enrichment_ratio": round(enriched_count / max(len(records), 1), 4),
            "records_by_recommended_action": action_counts,
            "known_unsupported_or_blocked_portals": blocked,
        }

    def lane_report(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        candidates = list(self.session.execute(select(OpportunityCandidate)).scalars())
        signals = list(self.session.execute(select(MarketSignal)).scalars())
        grouped: dict[str, dict[str, Any]] = {}
        for record in [*candidates, *signals]:
            lane = getattr(record, "signal_lane", None)
            lane_value = lane.value if hasattr(lane, "value") else str(lane or "unknown")
            bucket = grouped.setdefault(
                lane_value,
                {"signal_lane": lane_value, "records": 0, "unique_accounts": set(), "avg_retrieval_score": 0.0, "retrieval_total": 0.0},
            )
            bucket["records"] += 1
            bucket["retrieval_total"] += float(getattr(record, "retrieval_score", 0.0) or 0.0)
            if getattr(record, "account_cluster_id", None):
                bucket["unique_accounts"].add(record.account_cluster_id)
        for lane_value, bucket in grouped.items():
            rows.append(
                {
                    "signal_lane": lane_value,
                    "records": bucket["records"],
                    "unique_accounts": len(bucket["unique_accounts"]),
                    "avg_retrieval_score": round(bucket["retrieval_total"] / max(bucket["records"], 1), 2),
                }
            )
        return sorted(rows, key=lambda row: row["records"], reverse=True)

    def source_gap_report(self) -> list[dict[str, Any]]:
        from d365opps.ops import OpsService

        rows = OpsService(self.session).list_sources(limit=5000, offset=0)["items"]
        gaps: list[dict[str, Any]] = []
        for row in rows:
            blockers: list[str] = []
            if not row["enabled"]:
                blockers.append("disabled")
            if not row.get("production_ready_candidate"):
                blockers.append("scaffold_or_not_promoted")
            if not row["parser_implemented"]:
                blockers.append("parser_not_implemented")
            if row["operational_state"] not in {"healthy", "degraded"}:
                blockers.append(row["operational_state"])
            if row["public_access_mode"] in {"account_required", "invitation_only", "unsupported"}:
                blockers.append(row["public_access_mode"])
            if row["yield_state"] in {"zero_yield", "low_yield", "noisy", "stale"}:
                blockers.append(row["yield_state"])
            if row["production_ready"] and row["yielding_d365_records"]:
                continue
            gaps.append(
                {
                    "name": row["name"],
                    "enabled": row["enabled"],
                    "production_ready": row["production_ready"],
                    "production_ready_candidate": row.get("production_ready_candidate"),
                    "parser_implemented": row["parser_implemented"],
                    "source_family": row["source_family"],
                    "public_access_mode": row["public_access_mode"],
                    "operational_state": row["operational_state"],
                    "yield_state": row["yield_state"],
                    "supported_lanes": row["supported_lanes"],
                    "health_status": row["health_status"],
                    "last_successful_fetch_at": row["last_successful_fetch"],
                    "yielding_d365_records": row["yielding_d365_records"],
                    "dominant_issue": row["recommended_fix"],
                    "known_blind_spot_reason": row["known_blind_spot_reason"],
                    "gap_reasons": blockers or ["no_recent_d365_yield"],
                }
            )
        return gaps

    def build_source_universe(self, *, target_size: int = 400, include_dynamic: bool = True) -> dict[str, Any]:
        return self.source_universe.build_universe(target_size=target_size, include_dynamic=include_dynamic)

    def attempt_source_universe(self, *, concurrency: int = 20, rebuild_if_missing: bool = True) -> dict[str, Any]:
        return self.source_universe.attempt_universe(concurrency=concurrency, rebuild_if_missing=rebuild_if_missing)

    def global_source_campaign(self, *, target_size: int = 400, concurrency: int = 20, include_dynamic: bool = True) -> dict[str, Any]:
        return self.source_universe.run_campaign(target_size=target_size, concurrency=concurrency, include_dynamic=include_dynamic)

    def review_potential_hits(
        self,
        *,
        limit: int | None = None,
        ai_shortlist: int | None = None,
        use_ai: bool | None = None,
        campaign_path: str | None = None,
    ) -> dict[str, Any]:
        return self.source_universe.review_latest_potential_hits(
            limit=limit,
            ai_shortlist=ai_shortlist,
            use_ai=use_ai,
            campaign_path=campaign_path,
        )

    def detail_follow_bucket(
        self,
        *,
        bucket: str = "promising_surface_needs_detail_follow",
        limit: int | None = None,
        campaign_path: str | None = None,
    ) -> dict[str, Any]:
        return self.source_universe.detail_follow_bucket(
            bucket=bucket,
            limit=limit,
            campaign_path=campaign_path,
        )

    def recall_report(self, fixtures_path: str) -> dict[str, Any]:
        return self.recall_harness.run_fixture_file(fixtures_path).as_dict()

    def refresh(
        self,
        *,
        source_names: list[str] | None = None,
        region: str | None = None,
        since: datetime | None = None,
        include_disabled: bool = False,
        mode: str = "incremental_sync",
    ) -> list[dict[str, Any]]:
        statement = select(SourceRegistry).order_by(SourceRegistry.tier, SourceRegistry.name)
        if not include_disabled:
            statement = statement.where(SourceRegistry.enabled.is_(True))
        if source_names:
            statement = statement.where(SourceRegistry.name.in_(source_names))
        if region:
            statement = statement.where(SourceRegistry.region == region)
        sources = list(self.session.execute(statement).scalars())
        since = since or self._default_since(mode)
        results: list[dict[str, Any]] = []
        for source in sources:
            try:
                results.append(self._refresh_source(source, since=since, mode=mode))
            except Exception as exc:
                results.append(
                    {
                        "source": source.name,
                        "mode": mode,
                        "status": CrawlStatus.FAILED.value,
                        "queries_executed": 0,
                        "documents_fetched": 0,
                        "evidence_extracted": 0,
                        "candidates_created": 0,
                        "error": str(exc),
                        "issue_code": self._classify_issue(exc)[0],
                    }
                )
        return results

    def incremental_sync(
        self,
        *,
        source_names: list[str] | None = None,
        region: str | None = None,
        since: datetime | None = None,
        include_disabled: bool = False,
    ) -> list[dict[str, Any]]:
        return self.refresh(
            source_names=source_names,
            region=region,
            since=since,
            include_disabled=include_disabled,
            mode="incremental_sync",
        )

    def bootstrap_backfill(
        self,
        *,
        source_names: list[str] | None = None,
        region: str | None = None,
        since: datetime | None = None,
        include_disabled: bool = False,
    ) -> list[dict[str, Any]]:
        return self.refresh(
            source_names=source_names,
            region=region,
            since=since,
            include_disabled=include_disabled,
            mode="bootstrap_backfill",
        )

    def rescore_historical(
        self,
        *,
        document_ids: list[str] | None = None,
        purge_invalidated: bool = True,
    ) -> dict[str, Any]:
        job = self._start_job(
            JobType.REPROCESS,
            metadata={
                "job_kind": "historical_rescore",
                "document_ids": document_ids or [],
                "purge_invalidated": purge_invalidated,
            },
        )
        statement = select(RawDocument).order_by(RawDocument.fetched_at.desc())
        if document_ids:
            statement = statement.where(RawDocument.id.in_(document_ids))
        documents = list(self.session.execute(statement).scalars())
        evidence_records = 0
        created_or_updated = 0
        purged = 0
        for raw_document in documents:
            source = self.session.get(SourceRegistry, raw_document.source_id)
            if not source:
                continue
            payload = self.blob_store.get_bytes(raw_document.blob_path)
            evidence_count, created_count = self._process_raw_document(source, raw_document, payload)
            evidence_records += evidence_count
            created_or_updated += created_count
        if purge_invalidated:
            purged = self._purge_invalidated_records()
        job.documents_fetched = len(documents)
        job.evidence_extracted = evidence_records
        job.candidates_created = created_or_updated
        job.opportunities_created = created_or_updated
        job.metadata_json = _merge_json(job.metadata_json, {"purged_invalidated": purged})
        self._finish_job(job, CrawlStatus.SUCCEEDED)
        return {
            "documents": len(documents),
            "evidence_records": evidence_records,
            "created_or_updated": created_or_updated,
            "purged_invalidated": purged,
        }

    def purge_demo_records(self) -> dict[str, int]:
        job = self._start_job(JobType.REPROCESS, metadata={"job_kind": "purge_demo"})
        counts = purge_demo_data(self.session)
        self._finish_job(job, CrawlStatus.SUCCEEDED)
        return counts

    def canary_sweep(self, *, source_names: list[str] | None = None) -> list[dict[str, Any]]:
        statement = select(SourceRegistry).order_by(SourceRegistry.tier, SourceRegistry.name)
        if source_names:
            statement = statement.where(SourceRegistry.name.in_(source_names))
        else:
            statement = statement.where(SourceRegistry.enabled.is_(True))
        sources = list(self.session.execute(statement).scalars())
        job = self._start_job(
            JobType.CANARY_SWEEP,
            metadata={"source_names": [source.name for source in sources], "run_reason": "manual_canary_sweep"},
        )
        results: list[dict[str, Any]] = []
        with correlation_scope(run_id=job.id, job_run_id=job.id):
            client = httpx.Client(timeout=min(self.settings.http_timeout_seconds, 15), follow_redirects=True, headers={"User-Agent": self.settings.user_agent})
            try:
                for source in sources:
                    with correlation_scope(source_id=source.id):
                        try:
                            canary = self._execute_canary_request(client, source)
                        except Exception as exc:
                            issue_code, _ = self._classify_issue(exc)
                            canary = {
                                "status": "failed",
                                "issue_code": issue_code,
                                "latency_ms": 0,
                                "docs_seen": 0,
                                "expected_marker_found": False,
                                "parser_ok": False,
                                "evidence": {
                                    "endpoint": source.endpoint,
                                    "error_class": type(exc).__name__,
                                    "error_message": str(exc),
                                },
                            }
                        status = canary["status"]
                        issue_code = canary["issue_code"]
                        latency_ms = canary["latency_ms"]
                        docs_seen = canary["docs_seen"]
                        expected_marker_found = canary["expected_marker_found"]
                        parser_ok = canary["parser_ok"]
                        evidence = canary["evidence"]
                        source.last_attempted_fetch_at = datetime.now(UTC).replace(tzinfo=None)
                        result = SourceCanaryResult(
                            source_id=source.id,
                            canary_name=f"{source.name}_reachability",
                            status=status,
                            docs_seen=docs_seen,
                            expected_marker_found=expected_marker_found,
                            parser_ok=parser_ok,
                            latency_ms=latency_ms,
                            issue_code=issue_code,
                            evidence_json=evidence,
                            trace_id=current_correlation().trace_id,
                        )
                        self.session.add(result)
                        self.session.flush()
                        if status != "passed":
                            source.health_status = SourceHealthStatus.FAILING
                            self._upsert_source_issue(
                                source_id=source.id,
                                crawl_run_id=None,
                                issue_code=issue_code or "canary_failed",
                                severity=IssueSeverity.HIGH if (issue_code or "").startswith("http_") else IssueSeverity.MEDIUM,
                                example_url=str(evidence.get("url") or source.endpoint),
                                example_status_code=evidence.get("status_code"),
                                error_class=evidence.get("error_class"),
                                error_message=evidence.get("error_message"),
                                impact_on_yield="Canary failure blocks healthy classification until the source responds correctly again.",
                                recommended_remediation=self._recommended_fix(issue_code or "canary_failed"),
                                metadata={"canary": True, "canary_id": result.id, "canary_name": result.canary_name},
                            )
                        else:
                            source.health_status = SourceHealthStatus.HEALTHY
                            self._close_source_issues(source.id)
                        self.recorder.emit_event(
                            "canary.result",
                            level="warning" if status != "passed" else "info",
                            component="canary",
                            phase="connectivity",
                            run_id=job.id,
                            source_id=source.id,
                            source_name=source.name,
                            status=status,
                            issue_code=issue_code,
                            payload=evidence,
                        )
                        results.append(
                            {
                                "source_id": source.id,
                                "source_name": source.name,
                                "status": status,
                                "issue_code": issue_code,
                                "latency_ms": latency_ms,
                            }
                        )
                job.sources_attempted = len(sources)
                job.sources_succeeded = sum(1 for row in results if row["status"] == "passed")
                job.sources_failed = sum(1 for row in results if row["status"] != "passed")
                self._finish_job(job, CrawlStatus.SUCCEEDED)
            finally:
                client.close()
        return results

    def _execute_canary_request(self, client: httpx.Client, source: SourceRegistry) -> dict[str, Any]:
        started = datetime.now(UTC).replace(tzinfo=None)
        evidence: dict[str, Any] = {"endpoint": source.endpoint}
        if source.name == "contracts_finder":
            params = {
                "publishedFrom": (datetime.now(UTC) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "publishedTo": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "limit": 1,
            }
            response = client.get(source.endpoint, params=params)
            latency_ms = int((datetime.now(UTC).replace(tzinfo=None) - started).total_seconds() * 1000)
            body_json: dict[str, Any] = {}
            try:
                body_json = response.json() if response.content else {}
            except ValueError:
                body_json = {}
            parser_ok = response.headers.get("content-type", "").startswith("application/json")
            releases = body_json.get("releases", []) if isinstance(body_json, dict) else []
            expected_marker_found = isinstance(releases, list)
            issue_code = None
            status = "passed"
            if response.status_code >= 400:
                status = "failed"
                issue_code = f"http_{response.status_code}"
            elif not parser_ok:
                status = "failed"
                issue_code = "unsupported_content_type"
            evidence.update(
                {
                    "method": "GET",
                    "url": str(response.url),
                    "status_code": response.status_code,
                    "content_type": response.headers.get("content-type"),
                    "releases_seen": len(releases),
                }
            )
            return {
                "status": status,
                "issue_code": issue_code,
                "latency_ms": latency_ms,
                "docs_seen": len(releases),
                "expected_marker_found": expected_marker_found,
                "parser_ok": parser_ok,
                "evidence": evidence,
            }
        if source.name == "find_a_tender":
            search_url = source.endpoint.replace("/Find/Notice/Results", "/Search")
            response = client.get(search_url, params={"keywords": "Dynamics 365"})
            latency_ms = int((datetime.now(UTC).replace(tzinfo=None) - started).total_seconds() * 1000)
            body = response.text[:4000]
            parser_ok = response.headers.get("content-type", "").startswith("text/html")
            expected_marker_found = "find a tender" in body.lower() or "notice results" in body.lower()
            issue_code = None
            status = "passed"
            if response.status_code >= 400:
                status = "failed"
                issue_code = f"http_{response.status_code}"
            elif not parser_ok:
                status = "failed"
                issue_code = "unsupported_content_type"
            evidence.update(
                {
                    "method": "GET",
                    "url": str(response.url),
                    "status_code": response.status_code,
                    "content_type": response.headers.get("content-type"),
                    "keyword": "Dynamics 365",
                }
            )
            return {
                "status": status,
                "issue_code": issue_code,
                "latency_ms": latency_ms,
                "docs_seen": 1 if response.status_code < 400 else 0,
                "expected_marker_found": expected_marker_found,
                "parser_ok": parser_ok,
                "evidence": evidence,
            }
        if source.name == "ted":
            payload = {
                "query": 'publication-date >= 20240101 AND (notice-title ~ "Dynamics 365" OR notice-title ~ "Microsoft Dynamics" OR notice-title ~ "Business Central")',
                "fields": ["publication-number", "notice-title", "publication-date"],
                "limit": 1,
                "scope": source.config_json.get("scope", self.settings.ted_scope),
                "paginationMode": "ITERATION",
            }
            response = client.post(source.endpoint, json=payload)
            latency_ms = int((datetime.now(UTC).replace(tzinfo=None) - started).total_seconds() * 1000)
            body_json: dict[str, Any] = {}
            try:
                body_json = response.json() if response.content else {}
            except ValueError:
                body_json = {}
            docs_seen = len(body_json.get("notices", [])) if response.status_code < 400 else 0
            parser_ok = response.headers.get("content-type", "").startswith("application/json")
            expected_marker_found = isinstance(body_json.get("notices"), list)
            issue_code = None
            status = "passed"
            if response.status_code >= 400:
                status = "failed"
                issue_code = f"http_{response.status_code}"
            elif not parser_ok:
                status = "failed"
                issue_code = "unsupported_content_type"
            evidence.update(
                {
                    "method": "POST",
                    "url": str(response.url),
                    "status_code": response.status_code,
                    "content_type": response.headers.get("content-type"),
                    "query": payload["query"],
                    "response_keys": sorted(body_json.keys())[:20],
                }
            )
            return {
                "status": status,
                "issue_code": issue_code,
                "latency_ms": latency_ms,
                "docs_seen": docs_seen,
                "expected_marker_found": expected_marker_found,
                "parser_ok": parser_ok,
                "evidence": evidence,
            }
        if source.name == "hilma_notices":
            endpoint = (source.config_json or {}).get("search_endpoint") or source.endpoint
            response = client.get(endpoint, params={"lang": "en", "search": "Microsoft Dynamics", "$top": 1})
            latency_ms = int((datetime.now(UTC).replace(tzinfo=None) - started).total_seconds() * 1000)
            body_json: dict[str, Any] = {}
            try:
                body_json = response.json() if response.content else {}
            except ValueError:
                body_json = {}
            items = body_json.get("value", []) if isinstance(body_json, dict) else []
            parser_ok = response.headers.get("content-type", "").startswith("application/json")
            expected_marker_found = isinstance(items, list)
            issue_code = None
            status = "passed"
            if response.status_code >= 400:
                status = "failed"
                issue_code = f"http_{response.status_code}"
            elif not parser_ok:
                status = "failed"
                issue_code = "unsupported_content_type"
            evidence.update(
                {
                    "method": "GET",
                    "url": str(response.url),
                    "status_code": response.status_code,
                    "content_type": response.headers.get("content-type"),
                    "items_seen": len(items),
                }
            )
            return {
                "status": status,
                "issue_code": issue_code,
                "latency_ms": latency_ms,
                "docs_seen": len(items),
                "expected_marker_found": expected_marker_found,
                "parser_ok": parser_ok,
                "evidence": evidence,
            }
        if source.name == "ireland_etenders":
            endpoint = (source.config_json or {}).get("search_endpoint") or "https://www.etenders.gov.ie/epps/viewCFTSAction.do"
            response = client.post(
                endpoint,
                data={
                    "isExport": "true",
                    "isFTS": "true",
                    "isQuickSearch": "true",
                    "freeText": "Microsoft Dynamics",
                    "type": "cftFTS",
                    "tableUid": "searchCft",
                },
            )
            latency_ms = int((datetime.now(UTC).replace(tzinfo=None) - started).total_seconds() * 1000)
            body = response.text
            parser_ok = response.headers.get("content-type", "").startswith("text/csv")
            expected_marker_found = '"ID","TITLE","AUTHORITY"' in body
            rows = max(body.count("\n") - 1, 0) if parser_ok else 0
            issue_code = None
            status = "passed"
            if response.status_code >= 400:
                status = "failed"
                issue_code = f"http_{response.status_code}"
            elif not parser_ok:
                status = "failed"
                issue_code = "unsupported_content_type"
            evidence.update(
                {
                    "method": "POST",
                    "url": str(response.url),
                    "status_code": response.status_code,
                    "content_type": response.headers.get("content-type"),
                    "rows_seen": rows,
                }
            )
            return {
                "status": status,
                "issue_code": issue_code,
                "latency_ms": latency_ms,
                "docs_seen": rows,
                "expected_marker_found": expected_marker_found,
                "parser_ok": parser_ok,
                "evidence": evidence,
            }
        if source.name == "ocds_registry":
            endpoint = (source.config_json or {}).get("search_endpoint") or "https://data.open-contracting.org/en/search/"
            response = client.get(endpoint)
            latency_ms = int((datetime.now(UTC).replace(tzinfo=None) - started).total_seconds() * 1000)
            body = response.text
            parser_ok = response.headers.get("content-type", "").startswith("text/html")
            expected_marker_found = "Search for and download OCDS data" in body and "<article" in body
            docs_seen = body.count("<article")
            issue_code = None
            status = "passed"
            if response.status_code >= 400:
                status = "failed"
                issue_code = f"http_{response.status_code}"
            elif not parser_ok:
                status = "failed"
                issue_code = "unsupported_content_type"
            evidence.update(
                {
                    "method": "GET",
                    "url": str(response.url),
                    "status_code": response.status_code,
                    "content_type": response.headers.get("content-type"),
                    "rows_seen": docs_seen,
                }
            )
            return {
                "status": status,
                "issue_code": issue_code,
                "latency_ms": latency_ms,
                "docs_seen": docs_seen,
                "expected_marker_found": expected_marker_found,
                "parser_ok": parser_ok,
                "evidence": evidence,
            }
        if source.name == "gebiz_opportunities":
            response = client.get(source.endpoint)
            latency_ms = int((datetime.now(UTC).replace(tzinfo=None) - started).total_seconds() * 1000)
            body = response.text
            parser_ok = response.headers.get("content-type", "").startswith("text/html")
            docs_seen = body.count("directlink.xhtml?docCode=")
            expected_marker_found = "GeBIZ | Opportunities" in body and docs_seen > 0
            issue_code = None
            status = "passed"
            if response.status_code >= 400:
                status = "failed"
                issue_code = f"http_{response.status_code}"
            elif not parser_ok:
                status = "failed"
                issue_code = "unsupported_content_type"
            evidence.update(
                {
                    "method": "GET",
                    "url": str(response.url),
                    "status_code": response.status_code,
                    "content_type": response.headers.get("content-type"),
                    "rows_seen": docs_seen,
                }
            )
            return {
                "status": status,
                "issue_code": issue_code,
                "latency_ms": latency_ms,
                "docs_seen": docs_seen,
                "expected_marker_found": expected_marker_found,
                "parser_ok": parser_ok,
                "evidence": evidence,
            }
        if source.name in {"world_bank_current", "world_bank_upcoming", "world_bank_potential"}:
            endpoint = (source.config_json or {}).get("api_endpoint") or source.endpoint
            response = client.get(endpoint, params={"format": "json", "apilang": "en", "rows": 1, "os": 0, "qterm": "microsoft"})
            latency_ms = int((datetime.now(UTC).replace(tzinfo=None) - started).total_seconds() * 1000)
            body_json: dict[str, Any] = {}
            try:
                body_json = response.json() if response.content else {}
            except ValueError:
                body_json = {}
            items = body_json.get("procnotices", []) if isinstance(body_json, dict) else []
            parser_ok = response.headers.get("content-type", "").startswith("application/json")
            expected_marker_found = isinstance(items, list) and "total" in body_json
            issue_code = None
            status = "passed"
            if response.status_code >= 400:
                status = "failed"
                issue_code = f"http_{response.status_code}"
            elif not parser_ok:
                status = "failed"
                issue_code = "unsupported_content_type"
            evidence.update(
                {
                    "method": "GET",
                    "url": str(response.url),
                    "status_code": response.status_code,
                    "content_type": response.headers.get("content-type"),
                    "rows_seen": len(items),
                    "total": body_json.get("total"),
                }
            )
            return {
                "status": status,
                "issue_code": issue_code,
                "latency_ms": latency_ms,
                "docs_seen": len(items),
                "expected_marker_found": expected_marker_found,
                "parser_ok": parser_ok,
                "evidence": evidence,
            }
        if source.name == "south_africa_etenders":
            config = source.config_json or {}
            endpoint = config.get("api_endpoint") or source.endpoint
            response = client.get(
                endpoint,
                params={
                    "draw": "1",
                    "columns[0][data]": "icon",
                    "columns[0][name]": "",
                    "columns[0][searchable]": "true",
                    "columns[0][orderable]": "false",
                    "columns[0][search][value]": "",
                    "columns[0][search][regex]": "false",
                    "columns[1][data]": "description",
                    "columns[1][name]": "",
                    "columns[1][searchable]": "true",
                    "columns[1][orderable]": "true",
                    "columns[1][search][value]": "",
                    "columns[1][search][regex]": "false",
                    "columns[2][data]": "advertisedDate",
                    "columns[2][name]": "",
                    "columns[2][searchable]": "true",
                    "columns[2][orderable]": "false",
                    "columns[2][search][value]": "",
                    "columns[2][search][regex]": "false",
                    "columns[3][data]": "closingDate",
                    "columns[3][name]": "",
                    "columns[3][searchable]": "true",
                    "columns[3][orderable]": "true",
                    "columns[3][search][value]": "",
                    "columns[3][search][regex]": "false",
                    "order[0][column]": "2",
                    "order[0][dir]": "desc",
                    "start": "0",
                    "length": "1",
                    "search[value]": "Dynamics 365",
                    "search[regex]": "false",
                    "status": str(config.get("status", 1)),
                },
                headers={"X-Requested-With": "XMLHttpRequest", "Referer": config.get("referer") or "https://www.etenders.gov.za/Home/opportunities?id=1"},
            )
            latency_ms = int((datetime.now(UTC).replace(tzinfo=None) - started).total_seconds() * 1000)
            body_json: dict[str, Any] = {}
            try:
                body_json = response.json() if response.content else {}
            except ValueError:
                body_json = {}
            items = body_json.get("data", []) if isinstance(body_json, dict) else []
            parser_ok = response.headers.get("content-type", "").startswith("application/json")
            expected_marker_found = isinstance(items, list) and "recordsTotal" in body_json
            issue_code = None
            status = "passed"
            if response.status_code >= 400:
                status = "failed"
                issue_code = f"http_{response.status_code}"
            elif not parser_ok:
                status = "failed"
                issue_code = "unsupported_content_type"
            evidence.update(
                {
                    "method": "GET",
                    "url": str(response.url),
                    "status_code": response.status_code,
                    "content_type": response.headers.get("content-type"),
                    "rows_seen": len(items),
                    "records_total": body_json.get("recordsTotal"),
                }
            )
            return {
                "status": status,
                "issue_code": issue_code,
                "latency_ms": latency_ms,
                "docs_seen": len(items),
                "expected_marker_found": expected_marker_found,
                "parser_ok": parser_ok,
                "evidence": evidence,
            }
        if source.name == "south_africa_procurement_plans":
            response = client.get(source.endpoint)
            latency_ms = int((datetime.now(UTC).replace(tzinfo=None) - started).total_seconds() * 1000)
            body = response.text
            parser_ok = response.headers.get("content-type", "").startswith("text/html")
            expected_marker_found = "Procurement plans - eTenders Portal" in body and "Envisaged advert date" in body
            docs_seen = body.count("<tr") - 1
            issue_code = None
            status = "passed"
            if response.status_code >= 400:
                status = "failed"
                issue_code = f"http_{response.status_code}"
            elif not parser_ok:
                status = "failed"
                issue_code = "unsupported_content_type"
            evidence.update(
                {
                    "method": "GET",
                    "url": str(response.url),
                    "status_code": response.status_code,
                    "content_type": response.headers.get("content-type"),
                    "rows_seen": max(docs_seen, 0),
                }
            )
            return {
                "status": status,
                "issue_code": issue_code,
                "latency_ms": latency_ms,
                "docs_seen": max(docs_seen, 0),
                "expected_marker_found": expected_marker_found,
                "parser_ok": parser_ok,
                "evidence": evidence,
            }
        if source.name == "south_africa_awarded_tenders":
            response = client.get(source.endpoint)
            latency_ms = int((datetime.now(UTC).replace(tzinfo=None) - started).total_seconds() * 1000)
            body = response.text
            parser_ok = response.headers.get("content-type", "").startswith("text/html")
            expected_marker_found = "AwardedTenders" in body or "Tender No" in body
            docs_seen = body.count("<tr") - 1
            issue_code = None
            status = "passed"
            if response.status_code >= 400:
                status = "failed"
                issue_code = f"http_{response.status_code}"
            elif not parser_ok:
                status = "failed"
                issue_code = "unsupported_content_type"
            evidence.update(
                {
                    "method": "GET",
                    "url": str(response.url),
                    "status_code": response.status_code,
                    "content_type": response.headers.get("content-type"),
                    "rows_seen": max(docs_seen, 0),
                }
            )
            return {
                "status": status,
                "issue_code": issue_code,
                "latency_ms": latency_ms,
                "docs_seen": max(docs_seen, 0),
                "expected_marker_found": expected_marker_found,
                "parser_ok": parser_ok,
                "evidence": evidence,
            }
        if source.name == "tenderned":
            endpoint = (source.config_json or {}).get("api_endpoint") or source.endpoint
            response = client.get(endpoint, params={"page": 0, "size": 1, "search": "Microsoft"})
            latency_ms = int((datetime.now(UTC).replace(tzinfo=None) - started).total_seconds() * 1000)
            body_json: dict[str, Any] = {}
            try:
                body_json = response.json() if response.content else {}
            except ValueError:
                body_json = {}
            items = body_json.get("content", []) if isinstance(body_json, dict) else []
            parser_ok = response.headers.get("content-type", "").startswith("application/json")
            expected_marker_found = isinstance(items, list) and "totalElements" in body_json
            issue_code = None
            status = "passed"
            if response.status_code >= 400:
                status = "failed"
                issue_code = f"http_{response.status_code}"
            elif not parser_ok:
                status = "failed"
                issue_code = "unsupported_content_type"
            evidence.update(
                {
                    "method": "GET",
                    "url": str(response.url),
                    "status_code": response.status_code,
                    "content_type": response.headers.get("content-type"),
                    "rows_seen": len(items),
                    "total_elements": body_json.get("totalElements"),
                }
            )
            return {
                "status": status,
                "issue_code": issue_code,
                "latency_ms": latency_ms,
                "docs_seen": len(items),
                "expected_marker_found": expected_marker_found,
                "parser_ok": parser_ok,
                "evidence": evidence,
            }
        if source.name == "gets_tenders":
            endpoint = (source.config_json or {}).get("search_endpoint") or "https://www.gets.govt.nz/ExternalTenderSearching.htm"
            response = client.get(endpoint, params={"SearchingText": "Microsoft Dynamics", "submit": "Search"})
            latency_ms = int((datetime.now(UTC).replace(tzinfo=None) - started).total_seconds() * 1000)
            body = response.text[:8000]
            parser_ok = response.headers.get("content-type", "").startswith("text/html")
            detail_matches = re.findall(r"ExternalTenderDetails\.htm\?id=\d+", body)
            expected_marker_found = "gets - government electronic tender service" in body.lower() and bool(detail_matches)
            issue_code = None
            status = "passed"
            if response.status_code >= 400:
                status = "failed"
                issue_code = f"http_{response.status_code}"
            elif not parser_ok:
                status = "failed"
                issue_code = "unsupported_content_type"
            evidence.update(
                {
                    "method": "GET",
                    "url": str(response.url),
                    "status_code": response.status_code,
                    "content_type": response.headers.get("content-type"),
                    "detail_matches": len(detail_matches),
                }
            )
            return {
                "status": status,
                "issue_code": issue_code,
                "latency_ms": latency_ms,
                "docs_seen": len(detail_matches),
                "expected_marker_found": expected_marker_found,
                "parser_ok": parser_ok,
                "evidence": evidence,
            }
        response = client.get(source.endpoint)
        latency_ms = int((datetime.now(UTC).replace(tzinfo=None) - started).total_seconds() * 1000)
        body = response.text[:2000]
        docs_seen = 1 if response.status_code < 400 else 0
        expected_marker_found = source.name.split("_")[0].lower() in body.lower() or bool(source.country and source.country.lower() in body.lower())
        parser_ok = response.headers.get("content-type", "").startswith(("application/json", "text/html", "application/xml", "text/xml"))
        issue_code = None
        status = "passed"
        if response.status_code >= 400:
            status = "failed"
            issue_code = f"http_{response.status_code}"
        elif not parser_ok:
            status = "failed"
            issue_code = "unsupported_content_type"
        evidence.update(
            {
                "method": "GET",
                "url": str(response.url),
                "status_code": response.status_code,
                "content_type": response.headers.get("content-type"),
            }
        )
        return {
            "status": status,
            "issue_code": issue_code,
            "latency_ms": latency_ms,
            "docs_seen": docs_seen,
            "expected_marker_found": expected_marker_found,
            "parser_ok": parser_ok,
            "evidence": evidence,
        }

    def verify_pack(self, *, run_id: str | None = None, include_blobs: bool = False, include_db_dump: bool = False) -> dict[str, Any]:
        job = self._start_job(
            JobType.VERIFY_PACK,
            metadata={"run_reason": "verification_bundle", "target_run_id": run_id, "include_blobs": include_blobs, "include_db_dump": include_db_dump},
        )
        try:
            bundle = self.verifier.generate_bundle(run_id=run_id or job.id, include_blobs=include_blobs, include_db_dump=include_db_dump)
            job.metadata_json = _merge_json(job.metadata_json, bundle)
            self._finish_job(job, CrawlStatus.SUCCEEDED)
            return bundle
        except Exception as exc:
            self._finish_job(job, CrawlStatus.FAILED, errors=[{"message": str(exc), "type": type(exc).__name__}])
            raise

    def doctor(self, *, source_names: list[str] | None = None) -> dict[str, Any]:
        job = self._start_job(JobType.DOCTOR, metadata={"source_names": source_names or [], "run_reason": "doctor"})
        try:
            canaries = self.canary_sweep(source_names=source_names)
            bundle = self.verifier.generate_bundle(run_id=job.id)
            summary = self.verifier.diagnostics.explain_zero()
            job.metadata_json = _merge_json(job.metadata_json, {"canaries": canaries, "bundle": bundle})
            job.diagnostic_summary_json = summary
            self._finish_job(job, CrawlStatus.SUCCEEDED)
            return {"canaries": canaries, "bundle": bundle, "summary": summary}
        except Exception as exc:
            self._finish_job(job, CrawlStatus.FAILED, errors=[{"message": str(exc), "type": type(exc).__name__}])
            raise

    def _default_since(self, mode: str) -> datetime:
        days = self.settings.backfill_window_days if mode == "bootstrap_backfill" else self.settings.incremental_window_days
        return datetime.now(UTC) - timedelta(days=days)

    def _budget_for_source(self, source: SourceRegistry, mode: str) -> CrawlBudget:
        config = source.config_json or {}
        if mode == "bootstrap_backfill":
            max_pages = int(config.get("backfill_max_pages", self.settings.backfill_max_pages_per_source))
            max_notices = int(config.get("backfill_max_notices", self.settings.backfill_max_notices_per_source))
        else:
            max_pages = int(config.get("incremental_max_pages", self.settings.incremental_max_pages_per_source))
            max_notices = int(config.get("incremental_max_notices", self.settings.incremental_max_notices_per_source))
        return CrawlBudget(
            mode=mode,
            max_pages=max_pages,
            max_notices=max_notices,
            max_detail_pages=int(config.get("max_detail_pages", self.settings.max_detail_pages_per_source)),
            max_attachments=int(config.get("max_attachments", self.settings.max_attachments_per_source)),
            max_runtime_seconds=int(config.get("max_runtime_seconds", self.settings.max_runtime_seconds_per_source)),
        )

    def _load_watermark(self, source: SourceRegistry, query_id: str, mode: str) -> str | None:
        if mode == "bootstrap_backfill":
            return None
        watermarks = ((source.config_json or {}).get("watermarks") or {}).get(mode) or {}
        return watermarks.get(query_id)

    def _save_watermark(self, source: SourceRegistry, query_id: str, mode: str, value: str | None) -> None:
        config = dict(source.config_json or {})
        watermarks = dict(config.get("watermarks") or {})
        mode_watermarks = dict(watermarks.get(mode) or {})
        mode_watermarks[query_id] = value
        watermarks[mode] = mode_watermarks
        config["watermarks"] = watermarks
        source.config_json = config

    def _refresh_source(self, source: SourceRegistry, *, since: datetime, mode: str = "incremental_sync") -> dict[str, Any]:
        adapter = self.source_factory.get(source.name)
        started_at = datetime.now(UTC).replace(tzinfo=None)
        source.last_attempted_fetch_at = started_at
        run = CrawlRun(source_id=source.id, cursor=None)
        budget = self._budget_for_source(source, mode)
        job = self._start_job(
            JobType.REFRESH,
            source_id=source.id,
            metadata={
                "source_name": source.name,
                "since": since.isoformat(),
                "mode": mode,
                "budget": {
                    "mode": budget.mode,
                    "max_pages": budget.max_pages,
                    "max_notices": budget.max_notices,
                    "max_detail_pages": budget.max_detail_pages,
                    "max_attachments": budget.max_attachments,
                    "max_runtime_seconds": budget.max_runtime_seconds,
                },
            },
        )
        self.session.add(run)
        self.session.flush()
        job.crawl_run_id = run.id
        job.sources_attempted = 1
        documents_fetched = 0
        evidence_extracted = 0
        candidates_created = 0
        bytes_fetched = 0
        query_count = 0
        cursor: str | None = None
        deadline = datetime.now(UTC).replace(tzinfo=None) + timedelta(seconds=budget.max_runtime_seconds)
        with correlation_scope(run_id=job.id, job_run_id=job.id, crawl_run_id=run.id, source_id=source.id):
            self.recorder.emit_event(
                "source.run.start",
                component="pipeline.refresh",
                phase=mode,
                run_id=job.id,
                job_run_id=job.id,
                crawl_run_id=run.id,
                source_id=source.id,
                source_name=source.name,
                status="started",
                payload={"since": since.isoformat(), "budget": job.budget_json, "endpoint": source.endpoint},
            )
            try:
                plan = self.query_planner.plan(source, mode=mode)
                self.recorder.emit_event(
                    "query.plan",
                    component="retrieval",
                    phase=mode,
                    run_id=job.id,
                    source_id=source.id,
                    source_name=source.name,
                    status="planned",
                    payload={"query_count": len(plan.queries)},
                )
                for rendered_query in plan.queries:
                    if documents_fetched >= budget.max_notices or datetime.now(UTC).replace(tzinfo=None) >= deadline:
                        break
                    query_count += 1
                    cursor = self._load_watermark(source, rendered_query.query_id, mode)
                    with correlation_scope(query_id=rendered_query.query_id):
                        self.recorder.emit_event(
                            "query.render",
                            component="retrieval",
                            phase=rendered_query.phase,
                            run_id=job.id,
                            source_id=source.id,
                            source_name=source.name,
                            query_id=rendered_query.query_id,
                            query_family=rendered_query.query_family,
                            status="rendered",
                            payload=rendered_query.as_dict(),
                        )
                        self._upsert_query_execution(
                            source_id=source.id,
                            crawl_run_id=run.id,
                            query_id=rendered_query.query_id,
                            query_text=rendered_query.rendered_query_text,
                            query_family=rendered_query.query_family,
                            phase=rendered_query.phase,
                            target_field=rendered_query.target_field,
                            negatives_applied=list(rendered_query.negative_terms),
                            metadata={"mode": mode, **(rendered_query.metadata or {})},
                            renderer=rendered_query.renderer,
                            abstract_query_text=rendered_query.abstract_query_text,
                            rendered_query_text=rendered_query.rendered_query_text,
                            was_executed=True,
                            skip_reason=None,
                            watermark_in=cursor,
                            browse_only_pass=rendered_query.browse_only,
                            status="planned",
                        )
                        page = 0
                        while page < budget.max_pages and documents_fetched < budget.max_notices:
                            if datetime.now(UTC).replace(tzinfo=None) >= deadline:
                                break
                            fetch_started = datetime.now(UTC).replace(tzinfo=None)
                            batch = self._fetch_batch(adapter, source=source, since=since, cursor=cursor, query=rendered_query, budget=budget)
                            fetch_finished = datetime.now(UTC).replace(tzinfo=None)
                            page += 1
                            run.cursor = batch.next_cursor
                            event = self._record_fetch_event(
                                source=source,
                                run=run,
                                request_url=cursor or source.endpoint,
                                latency_ms=int((fetch_finished - fetch_started).total_seconds() * 1000),
                                status_code=200,
                                content_type=batch.documents[0].content_type if batch.documents else None,
                                documents_emitted=len(batch.documents),
                                success_flag=True,
                                query_id=rendered_query.query_id,
                                query_family=rendered_query.query_family,
                                page_index=page,
                                cursor_in=cursor,
                                cursor_out=batch.next_cursor,
                                adapter_name=adapter.__class__.__name__,
                                stage="fetch",
                                list_or_detail="list",
                                bytes_received=sum(len(item.payload) for item in batch.documents),
                                bytes_stored=sum(len(item.payload) for item in batch.documents),
                                response_body_sha256=sha256_bytes(b"".join(item.payload for item in batch.documents)) if batch.documents else None,
                                metadata={"renderer": rendered_query.renderer, "browse_only": rendered_query.browse_only},
                            )
                            self.recorder.emit_event(
                                "fetch.attempt",
                                component="adapter",
                                phase=rendered_query.phase,
                                run_id=job.id,
                                crawl_run_id=run.id,
                                source_id=source.id,
                                source_name=source.name,
                                query_id=rendered_query.query_id,
                                query_family=rendered_query.query_family,
                                status="succeeded",
                                payload={
                                    "request_url": cursor or source.endpoint,
                                    "status_code": 200,
                                    "documents_emitted": len(batch.documents),
                                    "latency_ms": event.latency_ms,
                                    "page_index": page,
                                    "cursor_in": cursor,
                                    "cursor_out": batch.next_cursor,
                                },
                            )
                            self._upsert_query_execution(
                                source_id=source.id,
                                crawl_run_id=run.id,
                                query_id=rendered_query.query_id,
                                query_text=rendered_query.rendered_query_text,
                                query_family=rendered_query.query_family,
                                phase=rendered_query.phase,
                                target_field=rendered_query.target_field,
                                negatives_applied=list(rendered_query.negative_terms),
                                metadata={"renderer": rendered_query.renderer, "mode": mode, **(rendered_query.metadata or {})},
                                renderer=rendered_query.renderer,
                                abstract_query_text=rendered_query.abstract_query_text,
                                rendered_query_text=rendered_query.rendered_query_text,
                                was_executed=True,
                                skip_reason=None,
                                watermark_in=cursor,
                                watermark_out=batch.next_cursor,
                                cursor_count=1 if batch.next_cursor else 0,
                                browse_only_pass=rendered_query.browse_only,
                                status="executed",
                                requests=1,
                                docs=len(batch.documents),
                            )
                            for fetched in batch.documents[: max(budget.max_notices - documents_fetched, 0)]:
                                metadata = dict(fetched.metadata or {})
                                metadata.setdefault("query_id", rendered_query.query_id)
                                metadata.setdefault("query_text", rendered_query.rendered_query_text)
                                metadata.setdefault("abstract_query_text", rendered_query.abstract_query_text)
                                metadata.setdefault("query_family", rendered_query.query_family)
                                metadata.setdefault("phase", rendered_query.phase)
                                metadata.setdefault("target_field", rendered_query.target_field)
                                metadata.setdefault("renderer", rendered_query.renderer)
                                fetched = fetched.model_copy(update={"metadata": metadata})
                                documents_fetched += 1
                                bytes_fetched += len(fetched.payload)
                                raw_document, created = self._store_raw_document(source, run, fetched)
                                self.recorder.emit_event(
                                    "raw_document.stored",
                                    component="storage",
                                    phase="ingest",
                                    run_id=job.id,
                                    crawl_run_id=run.id,
                                    source_id=source.id,
                                    source_name=source.name,
                                    query_id=rendered_query.query_id,
                                    query_family=rendered_query.query_family,
                                    document_id=raw_document.id,
                                    status="created" if created else "duplicate",
                                    payload={
                                        "blob_path": raw_document.blob_path,
                                        "checksum": raw_document.checksum,
                                        "content_type": raw_document.content_type,
                                    },
                                )
                                if not created:
                                    self._upsert_query_execution(
                                        source_id=source.id,
                                        crawl_run_id=run.id,
                                        query_id=rendered_query.query_id,
                                        query_text=rendered_query.rendered_query_text,
                                        query_family=rendered_query.query_family,
                                        renderer=rendered_query.renderer,
                                        abstract_query_text=rendered_query.abstract_query_text,
                                        rendered_query_text=rendered_query.rendered_query_text,
                                        duplicate_fetches_avoided=1,
                                        requests=0,
                                    )
                                    continue
                                evidence_count, created_count = self._process_raw_document(source, raw_document, fetched.payload)
                                evidence_extracted += evidence_count
                                candidates_created += created_count
                                run.candidates_created = candidates_created
                                event.evidence_emitted += evidence_count
                            if not batch.next_cursor:
                                saved = datetime.now(UTC).replace(tzinfo=None).isoformat()
                                self._save_watermark(source, rendered_query.query_id, mode, saved)
                                self.recorder.emit_event(
                                    "cursor.update",
                                    component="retrieval",
                                    phase=mode,
                                    run_id=job.id,
                                    source_id=source.id,
                                    source_name=source.name,
                                    query_id=rendered_query.query_id,
                                    query_family=rendered_query.query_family,
                                    status="final",
                                    payload={"watermark": saved},
                                )
                                break
                            cursor = batch.next_cursor
                            self._save_watermark(source, rendered_query.query_id, mode, cursor)
                    self.recorder.emit_event(
                        "query.execute.end",
                        component="retrieval",
                        phase=rendered_query.phase,
                        run_id=job.id,
                        source_id=source.id,
                        source_name=source.name,
                        query_id=rendered_query.query_id,
                        query_family=rendered_query.query_family,
                        status="completed",
                        payload={"documents_fetched_so_far": documents_fetched, "evidence_extracted_so_far": evidence_extracted},
                    )
                finished_at = datetime.now(UTC).replace(tzinfo=None)
                run.status = CrawlStatus.SUCCEEDED
                run.finished_at = finished_at
                run.documents_fetched = documents_fetched
                run.evidence_extracted = evidence_extracted
                run.candidates_created = candidates_created
                source.last_successful_fetch_at = finished_at
                source.health_status = SourceHealthStatus.HEALTHY if documents_fetched else SourceHealthStatus.DEGRADED
                source.robots_status = source.robots_status or "unknown"
                job.documents_fetched = documents_fetched
                job.evidence_extracted = evidence_extracted
                job.candidates_created = candidates_created
                job.opportunities_created = candidates_created
                job.bytes_fetched = bytes_fetched
                job.query_count = query_count
                job.sources_succeeded = 1
                job.sources_zero_yield = 1 if documents_fetched == 0 else 0
                self._close_source_issues(source.id)
                self._update_source_daily_metric(source, run)
                self._finish_job(job, CrawlStatus.SUCCEEDED)
                if documents_fetched == 0:
                    self._upsert_source_issue(
                        source_id=source.id,
                        crawl_run_id=run.id,
                        issue_code="empty_result",
                        severity=IssueSeverity.MEDIUM,
                        example_url=source.endpoint,
                        impact_on_yield="No documents were emitted by the source during the latest run.",
                        recommended_remediation="Verify filters, pagination, and whether the source is stale or rate-limited.",
                    )
                self.recorder.emit_event(
                    "source.run.end",
                    component="pipeline.refresh",
                    phase=mode,
                    run_id=job.id,
                    job_run_id=job.id,
                    crawl_run_id=run.id,
                    source_id=source.id,
                    source_name=source.name,
                    status="succeeded",
                    payload={
                        "documents_fetched": documents_fetched,
                        "evidence_extracted": evidence_extracted,
                        "candidates_created": candidates_created,
                        "bytes_fetched": bytes_fetched,
                    },
                )
                return {
                    "source": source.name,
                    "mode": mode,
                    "status": run.status.value,
                    "queries_executed": query_count,
                    "documents_fetched": documents_fetched,
                    "evidence_extracted": evidence_extracted,
                    "candidates_created": candidates_created,
                }
            except Exception as exc:
                run.status = CrawlStatus.FAILED
                run.finished_at = datetime.now(UTC).replace(tzinfo=None)
                errors = list(run.errors_json or [])
                errors.append({"message": str(exc), "type": type(exc).__name__})
                run.errors_json = errors
                source.health_status = SourceHealthStatus.FAILING
                job.sources_failed = 1
                issue_code, severity = self._classify_issue(exc)
                self._record_fetch_event(
                    source=source,
                    run=run,
                    request_url=source.endpoint,
                    latency_ms=None,
                    status_code=_status_from_exception(exc),
                    content_type=None,
                    documents_emitted=0,
                    success_flag=False,
                    issue_code=issue_code,
                    error_class=type(exc).__name__,
                    error_message=str(exc),
                    adapter_name=adapter.__class__.__name__,
                    stage="fetch",
                    list_or_detail="list",
                    query_id=current_correlation().query_id,
                    query_family=None,
                    metadata={"exception": type(exc).__name__},
                )
                self._upsert_source_issue(
                    source_id=source.id,
                    crawl_run_id=run.id,
                    issue_code=issue_code,
                    severity=severity,
                    example_url=cursor or source.endpoint,
                    example_status_code=_status_from_exception(exc),
                    error_class=type(exc).__name__,
                    error_message=str(exc),
                    impact_on_yield="Latest refresh failed before results were processed.",
                    recommended_remediation=self._recommended_fix(issue_code),
                )
                self.recorder.emit_event(
                    "source.run.end",
                    level="error",
                    component="pipeline.refresh",
                    phase=mode,
                    run_id=job.id,
                    job_run_id=job.id,
                    crawl_run_id=run.id,
                    source_id=source.id,
                    source_name=source.name,
                    status="failed",
                    issue_code=issue_code,
                    message=str(exc),
                    payload={"error_class": type(exc).__name__},
                )
                self._finish_job(job, CrawlStatus.FAILED, errors=errors)
                raise

    def _fetch_batch(self, adapter, *, source: SourceRegistry, since: datetime, cursor: str | None, query, budget):
        try:
            return adapter.fetch(source, since=since, cursor=cursor, query=query, budget=budget)
        except TypeError as exc:
            if "unexpected keyword" not in str(exc) and "positional argument" not in str(exc):
                raise
            return adapter.fetch(source, since=since, cursor=cursor)

    def _store_raw_document(self, source: SourceRegistry, run: CrawlRun, fetched) -> tuple[RawDocument, bool]:
        suffix = ".json"
        if "html" in fetched.content_type:
            suffix = ".html"
        elif "pdf" in fetched.content_type:
            suffix = ".pdf"
        elif "xml" in fetched.content_type or "rss" in fetched.content_type:
            suffix = ".xml"
        blob = self.blob_store.put_bytes(source.name, fetched.external_id, fetched.payload, suffix)
        existing = self.session.execute(
            select(RawDocument).where(
                RawDocument.source_id == source.id,
                RawDocument.external_id == fetched.external_id,
                RawDocument.checksum == blob.checksum,
            )
        ).scalar_one_or_none()
        if existing:
            return existing, False
        raw_document = RawDocument(
            source_id=source.id,
            crawl_run_id=run.id,
            external_id=fetched.external_id,
            canonical_url=fetched.canonical_url,
            document_url=fetched.document_url,
            content_type=fetched.content_type,
            published_at=fetched.published_at,
            checksum=blob.checksum,
            blob_path=blob.path,
            metadata_json=fetched.metadata,
        )
        self.session.add(raw_document)
        self.session.flush()
        return raw_document, True

    def _process_raw_document(self, source: SourceRegistry, raw_document: RawDocument, payload: bytes) -> tuple[int, int]:
        adapter = self.source_factory.get(source.name)
        evidence_records = adapter.extract(source, raw_document, payload)
        evidence_count = len(evidence_records)
        created = 0
        self.recorder.emit_event(
            "extraction.success",
            component="extractor",
            phase="extract",
            run_id=current_correlation().run_id,
            crawl_run_id=raw_document.crawl_run_id,
            source_id=source.id,
            source_name=source.name,
            document_id=raw_document.id,
            status="succeeded",
            payload={"evidence_count": evidence_count, "adapter": adapter.__class__.__name__},
        )
        for extracted in evidence_records:
            attachment_metadata = extracted.attachment_metadata or []
            if not attachment_metadata and extracted.attachment_urls:
                attachment_metadata = self.attachment_harvester.harvest(source.name, extracted.attachment_urls)
            corroboration_count = self._estimate_corroboration(extracted)
            enriched_evidence = extracted.model_copy(
                update={
                    "attachment_metadata": attachment_metadata,
                    "classification_codes": sorted(set((extracted.classification_codes or []) + (extracted.cpv_codes or []))),
                }
            )
            assessment = self.retrieval_scorer.assess(enriched_evidence, source, corroboration_count=corroboration_count)
            enriched_evidence = enriched_evidence.model_copy(
                update={
                    "product_mentions": sorted(set((enriched_evidence.product_mentions or []) + list(assessment.matched_positive_terms))),
                    "service_mentions": sorted(set((enriched_evidence.service_mentions or []) + list(assessment.matched_service_terms))),
                    "language_status": assessment.language_status,
                    "language_details": assessment.language_details,
                    "english_evidence_source": assessment.english_evidence_source,
                    "retrieval_score": assessment.retrieval_score,
                    "formal_opportunity_score": assessment.formal_opportunity_score,
                    "pre_position_score": assessment.pre_position_score,
                    "account_intent_score": assessment.account_intent_score,
                    "install_base_trigger_score": assessment.install_base_trigger_score,
                    "service_fit_score": assessment.service_fit_score,
                    "buyer_quality_score": assessment.buyer_quality_score,
                    "corroboration_score": assessment.corroboration_score,
                    "source_trust": assessment.source_trust,
                    "matched_positive_terms": list(assessment.matched_positive_terms),
                    "matched_negative_terms": list(assessment.matched_negative_terms),
                    "corroboration_count": assessment.corroboration_count or 1,
                    "discovery_query_id": enriched_evidence.discovery_query_id or assessment.query_id,
                    "discovery_query_text": enriched_evidence.discovery_query_text or assessment.query_text,
                    "query_family": assessment.query_family,
                    "source_discovery_confidence": max(
                        enriched_evidence.source_discovery_confidence,
                        float(source.source_discovery_confidence or 0.0),
                        assessment.source_discovery_confidence,
                    ),
                    "signal_lane": assessment.signal_lane.value if assessment.signal_lane else None,
                    "recommended_action": assessment.recommended_action.value,
                    "route_to_market": assessment.route_to_market.value,
                    "account_heat_score": assessment.account_heat_score,
                    "installed_product_guess": assessment.installed_product_guess,
                    "installed_product_evidence": assessment.installed_product_evidence,
                    "trigger_type": assessment.trigger_type,
                    "trigger_strength": assessment.trigger_strength,
                    "procurement_cycle_stage": assessment.procurement_cycle_stage,
                    "vehicle_type": assessment.vehicle_type,
                    "incumbent_vendor": assessment.incumbent_vendor,
                    "incumbent_expiry_guess": assessment.incumbent_expiry_guess,
                    "buyer_intent_evidence": assessment.buyer_intent_evidence,
                    "legacy_evidence": assessment.legacy_evidence,
                    "portal_fingerprint": assessment.portal_fingerprint,
                    "public_access_mode": assessment.public_access_mode.value,
                    "known_blind_spot_reason": assessment.known_blind_spot_reason,
                    "acquisition_method": enriched_evidence.acquisition_method or source.acquisition_method.value,
                    "source_provenance": _merge_json(
                        enriched_evidence.source_provenance,
                        {
                            "source_name": source.name,
                            "endpoint": source.endpoint,
                            "raw_document": raw_document.canonical_url,
                        },
                    ),
                    "exclusion_reason": assessment.exclusion_reason,
                }
            )
            evidence = self._upsert_evidence(source, raw_document, enriched_evidence)
            self.recorder.emit_event(
                "language.gate",
                component="retrieval",
                phase="language",
                run_id=current_correlation().run_id,
                crawl_run_id=raw_document.crawl_run_id,
                source_id=source.id,
                source_name=source.name,
                document_id=raw_document.id,
                evidence_id=evidence.id,
                status=assessment.language_status,
                payload={
                    "english_evidence_source": assessment.english_evidence_source,
                    "matched_positive_terms": list(assessment.matched_positive_terms),
                    "matched_negative_terms": list(assessment.matched_negative_terms),
                },
            )
            if not assessment.passes_signal_threshold:
                self._upsert_exclusion(evidence, assessment, reason=assessment.exclusion_reason or "below_retrieval_threshold")
                self._purge_invalidated_records(evidence.id)
                self.recorder.emit_event(
                    "exclusion.decision",
                    component="classifier",
                    phase="exclude",
                    run_id=current_correlation().run_id,
                    crawl_run_id=raw_document.crawl_run_id,
                    source_id=source.id,
                    source_name=source.name,
                    document_id=raw_document.id,
                    evidence_id=evidence.id,
                    query_id=assessment.query_id,
                    query_family=assessment.query_family,
                    status="excluded",
                    issue_code=assessment.exclusion_reason,
                    payload=assessment.as_dict(),
                )
                continue
            retained, retention_reason, anchor_terms = retention_gate(enriched_evidence, assessment)
            if anchor_terms:
                enriched_evidence.matched_positive_terms = sorted(set(enriched_evidence.matched_positive_terms + anchor_terms))
                evidence.matched_positive_terms_json = sorted(set((evidence.matched_positive_terms_json or []) + anchor_terms))
                evidence.extracted_json = _merge_json(evidence.extracted_json or {}, {"retention_anchor_terms": anchor_terms})
            if not retained and retention_reason:
                evidence.exclusion_reason = retention_reason
                enriched_evidence.exclusion_reason = retention_reason
                self._upsert_exclusion(evidence, assessment, reason=retention_reason)
                self._purge_invalidated_records(evidence.id)
                self.recorder.emit_event(
                    "exclusion.decision",
                    component="classifier",
                    phase="retention_gate",
                    run_id=current_correlation().run_id,
                    crawl_run_id=raw_document.crawl_run_id,
                    source_id=source.id,
                    source_name=source.name,
                    document_id=raw_document.id,
                    evidence_id=evidence.id,
                    query_id=assessment.query_id,
                    query_family=assessment.query_family,
                    status="excluded",
                    issue_code=retention_reason,
                    payload={**assessment.as_dict(), "retention_anchor_terms": anchor_terms},
                )
                continue
            actionability_as_of_utc = datetime.now(UTC)
            current_actionability_state = current_actionability_state_for_record(enriched_evidence, assessment, today=actionability_as_of_utc)
            (
                english_sufficiency_score,
                english_shell_only_flag,
                seller_readable_title_en_flag,
                seller_readable_summary_en,
            ) = english_readiness_for_record(enriched_evidence, assessment)
            effective_recommended_action = effective_recommended_action_for_record(
                enriched_evidence,
                assessment,
                today=actionability_as_of_utc,
            )
            enriched_evidence.current_actionability_state = current_actionability_state
            enriched_evidence.recommended_action = effective_recommended_action
            enriched_evidence.english_sufficiency_score = english_sufficiency_score
            enriched_evidence.english_shell_only_flag = english_shell_only_flag
            enriched_evidence.seller_readable_title_en_flag = seller_readable_title_en_flag
            enriched_evidence.seller_readable_summary_en = seller_readable_summary_en
            evidence.current_actionability_state = CurrentActionabilityState(current_actionability_state)
            evidence.recommended_action = RecommendedAction(effective_recommended_action)
            evidence.english_sufficiency_score = english_sufficiency_score
            evidence.english_shell_only_flag = english_shell_only_flag
            evidence.seller_readable_title_en_flag = seller_readable_title_en_flag
            evidence.seller_readable_summary_en = seller_readable_summary_en
            evidence.extracted_json = _merge_json(
                evidence.extracted_json or {},
                {
                    "actionability_as_of_utc": actionability_as_of_utc.isoformat(),
                    "current_actionability_state": current_actionability_state,
                    "effective_recommended_action": effective_recommended_action,
                    "english_sufficiency_score": english_sufficiency_score,
                    "english_shell_only_flag": english_shell_only_flag,
                    "seller_readable_title_en_flag": seller_readable_title_en_flag,
                },
            )
            result = self.classifier.classify(enriched_evidence, source.lane.value, default_region=source.region)
            enrichment = self.enricher.enrich(
                buyer_name=enriched_evidence.buyer_name,
                source_url=enriched_evidence.source_url,
                contact_email=enriched_evidence.contact_email,
                country=enriched_evidence.buyer_country or source.country,
            )
            organization = self._upsert_organization(enrichment)
            self._upsert_contact(organization, enriched_evidence)
            if result.opportunity:
                result.opportunity.current_actionability_state = current_actionability_state
                result.opportunity.recommended_action = effective_recommended_action
                result.opportunity.english_sufficiency_score = english_sufficiency_score
                result.opportunity.english_shell_only_flag = english_shell_only_flag
                result.opportunity.seller_readable_title_en_flag = seller_readable_title_en_flag
                result.opportunity.seller_readable_summary_en = seller_readable_summary_en
                candidate = self._upsert_candidate(evidence, organization, result.opportunity, source=source)
                created += 1
                self.recorder.emit_event(
                    "classifier.decision",
                    component="classifier",
                    phase="promote",
                    run_id=current_correlation().run_id,
                    crawl_run_id=raw_document.crawl_run_id,
                    source_id=source.id,
                    source_name=source.name,
                    document_id=raw_document.id,
                    evidence_id=evidence.id,
                    opportunity_id=candidate.id,
                    account_id=candidate.account_cluster_id,
                    query_id=assessment.query_id,
                    query_family=assessment.query_family,
                    status="opportunity",
                    payload={
                        "signal_lane": candidate.signal_lane.value,
                        "recommended_action": candidate.recommended_action.value,
                        "opportunity_score": candidate.opportunity_score,
                    },
                )
                self._upsert_query_execution(
                    source_id=source.id,
                    crawl_run_id=raw_document.crawl_run_id or "",
                    query_id=assessment.query_id,
                    query_text=assessment.query_text,
                    query_family=assessment.query_family,
                    metadata={"source_url": enriched_evidence.source_url},
                    renderer=(raw_document.metadata_json or {}).get("renderer"),
                    abstract_query_text=(raw_document.metadata_json or {}).get("abstract_query_text"),
                    rendered_query_text=(raw_document.metadata_json or {}).get("query_text"),
                    status="retained",
                    docs=0,
                    evidence=1,
                    opps=1,
                )
            elif result.signal:
                signal = self._upsert_signal(evidence, organization, result.signal)
                self.recorder.emit_event(
                    "classifier.decision",
                    component="classifier",
                    phase="promote",
                    run_id=current_correlation().run_id,
                    crawl_run_id=raw_document.crawl_run_id,
                    source_id=source.id,
                    source_name=source.name,
                    document_id=raw_document.id,
                    evidence_id=evidence.id,
                    account_id=signal.account_cluster_id,
                    query_id=assessment.query_id,
                    query_family=assessment.query_family,
                    status="signal",
                    payload={
                        "signal_lane": signal.signal_lane.value,
                        "recommended_action": signal.recommended_action.value,
                        "confidence": signal.confidence,
                    },
                )
                self._upsert_query_execution(
                    source_id=source.id,
                    crawl_run_id=raw_document.crawl_run_id or "",
                    query_id=assessment.query_id,
                    query_text=assessment.query_text,
                    query_family=assessment.query_family,
                    metadata={"source_url": enriched_evidence.source_url},
                    renderer=(raw_document.metadata_json or {}).get("renderer"),
                    abstract_query_text=(raw_document.metadata_json or {}).get("abstract_query_text"),
                    rendered_query_text=(raw_document.metadata_json or {}).get("query_text"),
                    status="retained",
                    docs=0,
                    evidence=1,
                    signals=1,
                )
        return evidence_count, created

    def _upsert_evidence(self, source: SourceRegistry, raw_document: RawDocument, extracted) -> EvidenceRecord:
        if extracted.procurement_id:
            identity_filters = [
                EvidenceRecord.source_id == source.id,
                EvidenceRecord.procurement_id == extracted.procurement_id,
            ]
        else:
            identity_filters = [
                EvidenceRecord.raw_document_id == raw_document.id,
                EvidenceRecord.source_url == extracted.source_url,
            ]
        existing = (
            self.session.execute(
                select(EvidenceRecord)
                .where(*identity_filters)
                .order_by(desc(EvidenceRecord.id))
                .limit(1)
            )
            .scalars()
            .first()
        )
        if not existing and extracted.source_url and extracted.title:
            existing = (
                self.session.execute(
                    select(EvidenceRecord)
                    .where(
                        EvidenceRecord.raw_document_id == raw_document.id,
                        EvidenceRecord.source_url == extracted.source_url,
                        EvidenceRecord.title == extracted.title,
                    )
                    .order_by(desc(EvidenceRecord.id))
                    .limit(1)
                )
                .scalars()
                .first()
            )
        values = {
            "title": extracted.title,
            "summary": extracted.summary,
            "buyer_name": extracted.buyer_name,
            "buyer_country": extracted.buyer_country,
            "buyer_region": extracted.buyer_region,
            "notice_type": extracted.notice_type,
            "procurement_type": extracted.procurement_type,
            "publication_date": extracted.publication_date,
            "close_date": extracted.close_date,
            "budget_value": Decimal(extracted.budget_value) if extracted.budget_value is not None else None,
            "budget_currency": extracted.budget_currency,
            "response_url": extracted.response_url,
            "contact_name": extracted.contact_name,
            "contact_email": extracted.contact_email,
            "contact_phone": extracted.contact_phone,
            "cpv_codes_json": extracted.cpv_codes,
            "attachment_urls_json": extracted.attachment_urls,
            "attachment_metadata_json": extracted.attachment_metadata,
            "lot_titles_json": extracted.lot_titles,
            "product_mentions_json": extracted.product_mentions,
            "service_mentions_json": extracted.service_mentions,
            "classification_codes_json": extracted.classification_codes,
            "tags_json": extracted.tags,
            "procurement_id": extracted.procurement_id,
            "raw_excerpt": extracted.raw_excerpt,
            "acquisition_method": extracted.acquisition_method,
            "source_provenance_json": extracted.source_provenance,
            "language_status": extracted.language_status,
            "language_details_json": extracted.language_details,
            "english_evidence_source": extracted.english_evidence_source,
            "current_actionability_state": CurrentActionabilityState(extracted.current_actionability_state) if extracted.current_actionability_state else None,
            "english_sufficiency_score": extracted.english_sufficiency_score,
            "english_shell_only_flag": extracted.english_shell_only_flag,
            "seller_readable_summary_en": extracted.seller_readable_summary_en,
            "seller_readable_title_en_flag": extracted.seller_readable_title_en_flag,
            "retrieval_score": extracted.retrieval_score,
            "formal_opportunity_score": extracted.formal_opportunity_score,
            "pre_position_score": extracted.pre_position_score,
            "account_intent_score": extracted.account_intent_score,
            "install_base_trigger_score": extracted.install_base_trigger_score,
            "service_fit_score": extracted.service_fit_score,
            "buyer_quality_score": extracted.buyer_quality_score,
            "corroboration_score": extracted.corroboration_score,
            "source_trust": extracted.source_trust,
            "matched_positive_terms_json": extracted.matched_positive_terms,
            "matched_negative_terms_json": extracted.matched_negative_terms,
            "discovery_query_id": extracted.discovery_query_id,
            "discovery_query_text": extracted.discovery_query_text,
            "query_family": extracted.query_family,
            "source_discovery_confidence": extracted.source_discovery_confidence,
            "signal_lane": RadarLane(extracted.signal_lane) if extracted.signal_lane else None,
            "recommended_action": RecommendedAction(extracted.recommended_action) if extracted.recommended_action else None,
            "route_to_market": RouteToMarket(extracted.route_to_market) if extracted.route_to_market else None,
            "account_heat_score": extracted.account_heat_score,
            "installed_product_guess": extracted.installed_product_guess,
            "installed_product_evidence": extracted.installed_product_evidence,
            "trigger_type": extracted.trigger_type,
            "trigger_strength": extracted.trigger_strength,
            "procurement_cycle_stage": extracted.procurement_cycle_stage,
            "vehicle_type": extracted.vehicle_type,
            "incumbent_vendor": extracted.incumbent_vendor,
            "incumbent_expiry_guess": extracted.incumbent_expiry_guess,
            "buyer_intent_evidence_json": extracted.buyer_intent_evidence,
            "legacy_evidence_json": extracted.legacy_evidence,
            "portal_fingerprint": extracted.portal_fingerprint,
            "public_access_mode": PublicAccessMode(extracted.public_access_mode),
            "known_blind_spot_reason": extracted.known_blind_spot_reason,
            "exclusion_reason": extracted.exclusion_reason,
            "extracted_json": extracted.extracted_data,
        }
        if existing:
            for key, value in values.items():
                setattr(existing, key, value)
            return existing
        record = EvidenceRecord(
            raw_document_id=raw_document.id,
            source_id=source.id,
            record_type=extracted.record_type,
            source_url=extracted.source_url,
            **values,
        )
        self.session.add(record)
        self.session.flush()
        return record

    def _upsert_organization(self, enrichment) -> Organization:
        existing = self.session.execute(
            select(Organization).where(
                Organization.normalized_name == enrichment.normalized_name,
                Organization.website_domain == enrichment.website_domain,
            )
        ).scalar_one_or_none()
        if existing:
            existing.registry_payload_json = enrichment.provenance
            existing.country = enrichment.country or existing.country
            existing.region = enrichment.region or existing.region
            existing.enrichment_confidence = max(existing.enrichment_confidence, enrichment.enrichment_confidence)
            return existing
        organization = Organization(
            source_name=enrichment.organization_name,
            normalized_name=enrichment.normalized_name,
            website_domain=enrichment.website_domain,
            country=enrichment.country,
            region=enrichment.region,
            industry=enrichment.industry,
            size_band=enrichment.size_band,
            registry_payload_json=enrichment.provenance,
            enrichment_confidence=enrichment.enrichment_confidence,
            provenance_json=enrichment.provenance,
        )
        self.session.add(organization)
        self.session.flush()
        return organization

    def _upsert_contact(self, organization: Organization, extracted) -> Contact | None:
        if not extracted.contact_name and not extracted.contact_email:
            return None
        existing = self.session.execute(
            select(Contact).where(
                Contact.organization_id == organization.id,
                Contact.email == extracted.contact_email,
                Contact.full_name == extracted.contact_name,
            )
        ).scalar_one_or_none()
        if existing:
            existing.public_source_url = extracted.source_url
            existing.phone = extracted.contact_phone or existing.phone
            return existing
        contact = Contact(
            organization_id=organization.id,
            full_name=extracted.contact_name,
            email=extracted.contact_email,
            phone=extracted.contact_phone,
            public_source_url=extracted.source_url,
            enrichment_payload_json={"source": "evidence_record"},
            enrichment_confidence=0.35,
            provenance_json={"source_url": extracted.source_url},
        )
        self.session.add(contact)
        self.session.flush()
        return contact

    def _upsert_candidate(self, evidence: EvidenceRecord, organization: Organization, draft, *, source: SourceRegistry) -> OpportunityCandidate:
        existing = self.session.execute(
            select(OpportunityCandidate).where(OpportunityCandidate.evidence_record_id == evidence.id)
        ).scalar_one_or_none()
        if not existing and draft.dedupe_fingerprint:
            existing = self.session.execute(
                select(OpportunityCandidate)
                .where(OpportunityCandidate.dedupe_fingerprint == draft.dedupe_fingerprint)
                .order_by(OpportunityCandidate.updated_at.desc())
                .limit(1)
            ).scalar_one_or_none()
        if not existing and draft.procurement_id:
            existing = self.session.execute(
                select(OpportunityCandidate)
                .where(
                    OpportunityCandidate.procurement_id == draft.procurement_id,
                    func.lower(OpportunityCandidate.title) == draft.title.lower(),
                )
                .order_by(OpportunityCandidate.updated_at.desc())
                .limit(1)
            ).scalar_one_or_none()
        cluster = self._resolve_cluster(draft)
        account_cluster = self._resolve_account_cluster(organization, draft)
        score_breakdown = draft.scorecard.model_dump()
        common_values = {
            "organization_id": organization.id,
            "account_cluster_id": account_cluster.id,
            "cluster_id": cluster.id,
            "summary": draft.summary,
            "app_family": draft.app_family,
            "business_process": draft.business_process,
            "service_type": draft.service_type,
            "evidence_grade": draft.evidence_grade,
            "signal_lane": RadarLane(draft.signal_lane),
            "recommended_action": RecommendedAction(draft.recommended_action),
            "route_to_market": RouteToMarket(draft.route_to_market),
            "d365_confidence": draft.d365_confidence,
            "country": draft.country,
            "procurement_type": draft.procurement_type,
            "publication_date": draft.publication_date,
            "close_date": draft.close_date,
            "budget_value": Decimal(draft.budget_value) if draft.budget_value is not None else None,
            "budget_currency": draft.budget_currency,
            "source_url": draft.source_url,
            "response_url": draft.response_url,
            "procurement_id": draft.procurement_id,
            "raw_excerpt": draft.raw_excerpt,
            "retrieval_score": draft.retrieval_score,
            "formal_opportunity_score": draft.formal_opportunity_score,
            "pre_position_score": draft.pre_position_score,
            "account_intent_score": draft.account_intent_score,
            "install_base_trigger_score": draft.install_base_trigger_score,
            "service_fit_score": draft.service_fit_score,
            "buyer_quality_score": draft.buyer_quality_score,
            "corroboration_score": draft.corroboration_score,
            "opportunity_score": draft.opportunity_score or draft.scorecard.total_score,
            "source_trust": draft.source_trust,
            "matched_positive_terms_json": draft.matched_positive_terms,
            "matched_negative_terms_json": draft.matched_negative_terms,
            "language_status": draft.language_status,
            "english_evidence_source": draft.english_evidence_source,
            "current_actionability_state": CurrentActionabilityState(draft.current_actionability_state) if draft.current_actionability_state else None,
            "english_sufficiency_score": draft.english_sufficiency_score,
            "english_shell_only_flag": draft.english_shell_only_flag,
            "seller_readable_summary_en": draft.seller_readable_summary_en,
            "seller_readable_title_en_flag": draft.seller_readable_title_en_flag,
            "discovery_query_id": draft.discovery_query_id,
            "discovery_query_text": draft.discovery_query_text,
            "query_family": draft.query_family,
            "source_discovery_confidence": draft.source_discovery_confidence,
            "public_access_mode": PublicAccessMode(draft.public_access_mode),
            "account_heat_score": draft.account_heat_score,
            "installed_product_guess": draft.installed_product_guess,
            "installed_product_evidence": draft.installed_product_evidence,
            "trigger_type": draft.trigger_type,
            "trigger_strength": draft.trigger_strength,
            "procurement_cycle_stage": draft.procurement_cycle_stage,
            "vehicle_type": draft.vehicle_type,
            "incumbent_vendor": draft.incumbent_vendor,
            "incumbent_expiry_guess": draft.incumbent_expiry_guess,
            "buyer_intent_evidence_json": draft.buyer_intent_evidence,
            "legacy_evidence_json": draft.legacy_evidence,
            "portal_fingerprint": draft.portal_fingerprint,
            "known_blind_spot_reason": draft.known_blind_spot_reason,
            "exclusion_reason": draft.exclusion_reason,
            "score_breakdown_json": score_breakdown,
            "total_score": draft.scorecard.total_score,
            "pursuit_recommendation": draft.scorecard.recommendation,
            "next_action": draft.next_action,
            "dedupe_fingerprint": draft.dedupe_fingerprint,
            "tags_json": draft.tags,
        }
        if existing:
            existing.evidence_record_id = evidence.id
            existing.title = draft.title
            for key, value in common_values.items():
                setattr(existing, key, value)
            existing.updated_at = datetime.now(UTC).replace(tzinfo=None)
            self._update_cluster_corroboration(cluster, draft, source)
            existing.corroboration_count = cluster.corroboration_count
            self._update_account_cluster(account_cluster, draft)
            return existing
        candidate = OpportunityCandidate(
            evidence_record_id=evidence.id,
            title=draft.title,
            corroboration_count=max(1, int(draft.corroboration_count or 1)),
            **common_values,
        )
        self.session.add(candidate)
        self.session.flush()
        self._update_cluster_corroboration(cluster, draft, source)
        candidate.corroboration_count = cluster.corroboration_count
        self._update_account_cluster(account_cluster, draft)
        return candidate

    def _resolve_cluster(self, draft) -> OpportunityCluster:
        decision = self.clusterer.decide(draft)
        existing = self.session.execute(
            select(OpportunityCluster).where(OpportunityCluster.cluster_key == decision.cluster_key)
        ).scalar_one_or_none()
        if not existing:
            fuzzy_statement = select(OpportunityCluster)
            if draft.country:
                fuzzy_statement = fuzzy_statement.where(OpportunityCluster.country == draft.country)
            if draft.buyer_name:
                fuzzy_statement = fuzzy_statement.where(
                    func.lower(OpportunityCluster.canonical_buyer) == draft.buyer_name.lower()
                )
            for cluster in self.session.execute(fuzzy_statement.limit(50)).scalars():
                if self.clusterer.is_same_cluster(draft, cluster.canonical_title, cluster.canonical_buyer):
                    existing = cluster
                    break
        if existing:
            existing.aggregate_score = max(existing.aggregate_score, decision.score)
            existing.latest_seen_at = decision.latest_seen_at or datetime.now(UTC).replace(tzinfo=None)
            existing.evidence_grade = draft.evidence_grade
            return existing
        cluster = OpportunityCluster(
            cluster_key=decision.cluster_key,
            canonical_title=decision.canonical_title,
            canonical_buyer=decision.canonical_buyer,
            country=decision.country,
            latest_seen_at=decision.latest_seen_at or datetime.now(UTC).replace(tzinfo=None),
            aggregate_score=decision.score,
            evidence_grade=draft.evidence_grade,
            status=ClusterStatus.OPEN,
        )
        self.session.add(cluster)
        self.session.flush()
        return cluster

    def _update_cluster_corroboration(self, cluster: OpportunityCluster, draft, source: SourceRegistry) -> None:
        sources = set(cluster.corroborating_sources_json or [])
        sources.add(source.name)
        cluster.corroborating_sources_json = sorted(sources)
        cluster.corroboration_count = int(
            self.session.execute(
                select(func.count(OpportunityCandidate.id)).where(OpportunityCandidate.cluster_id == cluster.id)
            ).scalar_one()
            or 1
        )
        cluster.aggregate_score = max(cluster.aggregate_score, draft.scorecard.total_score)
        cluster.latest_seen_at = draft.publication_date or draft.close_date or datetime.now(UTC).replace(tzinfo=None)
        cluster.evidence_grade = draft.evidence_grade

    def _resolve_account_cluster(self, organization: Organization, draft) -> AccountCluster:
        cluster_key = organization.website_domain or organization.normalized_name
        existing = self.session.execute(
            select(AccountCluster).where(AccountCluster.cluster_key == cluster_key)
        ).scalar_one_or_none()
        if existing:
            return existing
        cluster = AccountCluster(
            cluster_key=cluster_key,
            canonical_name=organization.source_name,
            website_domain=organization.website_domain,
            country=draft.country or organization.country,
        )
        self.session.add(cluster)
        self.session.flush()
        return cluster

    def _update_account_cluster(self, cluster: AccountCluster, draft) -> None:
        cluster.latest_seen_at = datetime.now(UTC).replace(tzinfo=None)
        cluster.heat_score = max(cluster.heat_score, float(getattr(draft, "account_heat_score", 0.0) or 0.0))
        cluster.buyer_quality_score = max(
            cluster.buyer_quality_score,
            float(getattr(draft, "buyer_quality_score", 0.0) or 0.0),
        )
        cluster.installed_product_guess = getattr(draft, "installed_product_guess", None) or cluster.installed_product_guess
        cluster.installed_product_evidence = getattr(draft, "installed_product_evidence", None) or cluster.installed_product_evidence
        cluster.trigger_strength = max(cluster.trigger_strength, float(getattr(draft, "trigger_strength", 0.0) or 0.0))
        cluster.corroboration_count = max(cluster.corroboration_count, int(getattr(draft, "corroboration_count", 1) or 1))

    def _resolve_signal_cluster(self, draft) -> SignalCluster:
        cluster_key = f"{draft.signal_lane}:{(draft.country or 'XX')}:{(draft.title or '').lower()[:120]}"
        existing = self.session.execute(
            select(SignalCluster).where(SignalCluster.cluster_key == cluster_key)
        ).scalar_one_or_none()
        if existing:
            existing.latest_seen_at = datetime.now(UTC).replace(tzinfo=None)
            existing.corroboration_count = max(existing.corroboration_count, int(getattr(draft, "corroboration_count", 1) or 1))
            return existing
        cluster = SignalCluster(
            cluster_key=cluster_key,
            canonical_title=draft.title,
            canonical_buyer=None,
            signal_lane=RadarLane(draft.signal_lane),
            country=draft.country,
            recommended_action=RecommendedAction(draft.recommended_action),
            route_to_market=RouteToMarket(draft.route_to_market),
        )
        self.session.add(cluster)
        self.session.flush()
        return cluster

    def _refresh_account_clusters(self) -> None:
        for candidate in self.session.execute(select(OpportunityCandidate)).scalars():
            if candidate.account_cluster_id:
                continue
            organization = self.session.get(Organization, candidate.organization_id) if candidate.organization_id else None
            if not organization:
                continue
            cluster = self._resolve_account_cluster(organization, candidate)
            candidate.account_cluster_id = cluster.id
            self._update_account_cluster(cluster, candidate)
        for signal in self.session.execute(select(MarketSignal)).scalars():
            if signal.account_cluster_id:
                continue
            organization = self.session.get(Organization, signal.organization_id) if signal.organization_id else None
            if not organization:
                continue
            cluster = self._resolve_account_cluster(organization, signal)
            signal.account_cluster_id = cluster.id
            cluster.heat_score = max(cluster.heat_score, float(signal.account_heat_score or 0.0))
            cluster.trigger_strength = max(cluster.trigger_strength, float(signal.trigger_strength or 0.0))

    def _start_job(self, job_type: JobType, *, source_id: str | None = None, metadata: dict[str, Any] | None = None) -> JobRun:
        correlation = ensure_correlation()
        metadata = _merge_json(metadata or {}, {"state_before": self._state_snapshot()})
        source_names = metadata.get("source_names") or ([metadata["source_name"]] if metadata.get("source_name") else [])
        source_classes = []
        for name in source_names:
            source = self.session.execute(select(SourceRegistry).where(SourceRegistry.name == name)).scalar_one_or_none()
            if not source:
                continue
            source_classes.append(
                classify_source_authenticity(
                    name=source.name,
                    endpoint=source.endpoint,
                    source_family=source.source_family,
                    public_access_mode=source.public_access_mode.value,
                    data_mode="demo" if source.name.startswith("demo_") else "live",
                ).authenticity_class
            )
        if any(value == "demo_seed" for value in source_classes):
            run_kind = "demo"
            evidence_class = "demo_seed"
        elif any(value == "synthetic_fixture" for value in source_classes):
            run_kind = "fixture"
            evidence_class = "synthetic_fixture"
        elif metadata.get("mode") == "bootstrap_backfill":
            run_kind = "live_public_expanded"
            evidence_class = "official_public"
        elif source_classes:
            run_kind = "live_public_baseline"
            evidence_class = "official_public"
        else:
            run_kind = "manual_debug"
            evidence_class = "mixed"
        job = JobRun(
            source_id=source_id,
            job_type=job_type,
            metadata_json=metadata,
            trace_id=correlation.trace_id,
            request_id=correlation.request_id,
            mode=metadata.get("mode"),
            source_names_json=source_names,
            budget_json=metadata.get("budget") or {},
            run_reason=metadata.get("run_reason") or metadata.get("mode") or job_type.value,
            initiated_by=metadata.get("initiated_by") or "system",
            run_kind=run_kind,
            evidence_class=evidence_class,
            oracle_admissible=False,
            admissibility_fail_reasons_json=[],
        )
        self.session.add(job)
        self.session.flush()
        set_correlation(run_id=job.id, job_run_id=job.id, source_id=source_id)
        self.recorder.emit_event(
            "job.start",
            component="pipeline",
            phase=metadata.get("mode"),
            run_id=job.id,
            job_run_id=job.id,
            source_id=source_id,
            status="started",
            payload={"job_type": job_type.value, "metadata": metadata},
        )
        return job

    def _finish_job(self, job: JobRun, status: CrawlStatus, *, errors: list[dict[str, Any]] | None = None) -> None:
        finished_at = datetime.now(UTC).replace(tzinfo=None)
        job.status = status
        job.finished_at = finished_at
        job.duration_ms = int((finished_at - job.started_at).total_seconds() * 1000)
        if errors:
            job.errors_json = errors
        job.metadata_json = _merge_json(job.metadata_json, {"state_after": self._state_snapshot()})
        job.diagnostic_summary_json = {
            "status": status.value,
            "documents_fetched": job.documents_fetched,
            "evidence_extracted": job.evidence_extracted,
            "candidates_created": job.candidates_created,
            "opportunities_created": job.opportunities_created,
            "errors": errors or [],
        }
        self.recorder.emit_event(
            "job.end",
            level="error" if status == CrawlStatus.FAILED else "info",
            component="pipeline",
            phase=job.mode,
            run_id=job.id,
            job_run_id=job.id,
            source_id=job.source_id,
            status=status.value,
            payload=job.diagnostic_summary_json,
        )
        bundle_target_run_id = (job.metadata_json or {}).get("target_run_id") or job.id
        bundle = self.verifier.generate_bundle(run_id=bundle_target_run_id)
        accountability = self.verifier.generate_accountability_run(run_id=bundle_target_run_id, verification_bundle=bundle)
        job.verification_bundle_path = bundle["bundle_path"]
        job.verification_bundle_sha256 = bundle["sha256"]
        job.run_kind = accountability.get("run_kind") or bundle.get("run_kind") or job.run_kind
        job.evidence_class = accountability.get("evidence_class") or bundle.get("evidence_class") or job.evidence_class
        job.oracle_admissible = bool(accountability.get("oracle_admissible") if accountability.get("oracle_admissible") is not None else bundle.get("oracle_admissible"))
        job.admissibility_fail_reasons_json = accountability.get("admissibility_fail_reasons") or bundle.get("admissibility_fail_reasons") or []
        job.metadata_json = _merge_json(
            job.metadata_json,
            {
                "verification_bundle": bundle,
                "accountability_bundle": accountability,
            },
        )
        self.oracle_writer.refresh()

    def _state_snapshot(self) -> dict[str, Any]:
        return {
            "captured_at": datetime.now(UTC).isoformat(),
            "sources_total": int(self.session.execute(select(func.count(SourceRegistry.id))).scalar_one() or 0),
            "sources_enabled": int(
                self.session.execute(select(func.count(SourceRegistry.id)).where(SourceRegistry.enabled.is_(True))).scalar_one() or 0
            ),
            "raw_documents": int(self.session.execute(select(func.count(RawDocument.id))).scalar_one() or 0),
            "evidence_records": int(self.session.execute(select(func.count(EvidenceRecord.id))).scalar_one() or 0),
            "opportunity_candidates": int(self.session.execute(select(func.count(OpportunityCandidate.id))).scalar_one() or 0),
            "market_signals": int(self.session.execute(select(func.count(MarketSignal.id))).scalar_one() or 0),
            "exclusions": int(self.session.execute(select(func.count(ExclusionAudit.id))).scalar_one() or 0),
            "source_issues": int(self.session.execute(select(func.count(SourceIssue.id))).scalar_one() or 0),
        }

    def refresh_oracle_instructions(self) -> dict[str, str]:
        return self.oracle_writer.refresh()

    def build_oracle_bundle(self) -> dict[str, Any]:
        self.oracle_writer.refresh()
        return self.oracle_bundle_builder.build()

    def verify_oracle_bundle(self) -> dict[str, Any]:
        return self.oracle_bundle_builder.verify()

    def render_run_verdict(self, *, run_id: str | None = None) -> dict[str, Any]:
        bundle = self.verifier.generate_bundle(run_id=run_id)
        accountability = self.verifier.generate_accountability_run(run_id=run_id, verification_bundle=bundle)
        verdict_path = Path(accountability["latest_path"]) / "run_verdict.md"
        verdict_json_path = Path(accountability["latest_path"]) / "run_verdict.json"
        return {
            "accountability_path": accountability["latest_path"],
            "run_verdict_path": str(verdict_path),
            "run_verdict_json_path": str(verdict_json_path),
        }

    def _record_fetch_event(
        self,
        *,
        source: SourceRegistry,
        run: CrawlRun,
        request_url: str,
        latency_ms: int | None,
        status_code: int | None,
        content_type: str | None,
        documents_emitted: int,
        success_flag: bool,
        issue_code: str | None = None,
        error_class: str | None = None,
        error_message: str | None = None,
        query_id: str | None = None,
        query_family: str | None = None,
        page_index: int = 0,
        cursor_in: str | None = None,
        cursor_out: str | None = None,
        parent_url: str | None = None,
        detail_url: str | None = None,
        bytes_received: int = 0,
        bytes_stored: int = 0,
        request_headers: dict[str, Any] | None = None,
        response_headers: dict[str, Any] | None = None,
        rate_limit_headers: dict[str, Any] | None = None,
        response_body_sha256: str | None = None,
        response_blob_path: str | None = None,
        adapter_name: str | None = None,
        adapter_version: str | None = None,
        stage: str | None = None,
        list_or_detail: str | None = None,
        attempt_number: int = 1,
        backoff_ms: int | None = None,
        network_error_stage: str | None = None,
        http_protocol: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SourceFetchEvent:
        correlation = ensure_correlation()
        tls_error_flag, dns_error_flag, transport_error_flag = low_cardinality_error(
            Exception(error_message) if error_message else None
        )
        event = SourceFetchEvent(
            source_id=source.id,
            crawl_run_id=run.id,
            trace_id=correlation.trace_id,
            span_id=correlation.span_id,
            request_id=correlation.request_id,
            query_id=query_id or correlation.query_id,
            query_family=query_family,
            page_index=page_index,
            cursor_in=cursor_in,
            cursor_out=cursor_out,
            parent_url=parent_url,
            detail_url=detail_url,
            request_url=request_url,
            request_method="GET",
            response_status_code=status_code,
            latency_ms=latency_ms,
            bytes=bytes_received,
            bytes_received=bytes_received,
            bytes_stored=bytes_stored,
            content_type=content_type,
            robots_status=source.robots_status,
            parser_used=source.parsing_mode.value,
            adapter_name=adapter_name,
            adapter_version=adapter_version,
            stage=stage,
            list_or_detail=list_or_detail,
            attempt_number=attempt_number,
            backoff_ms=backoff_ms,
            network_error_stage=network_error_stage,
            http_protocol=http_protocol,
            tls_error_flag=tls_error_flag,
            dns_error_flag=dns_error_flag,
            transport_error_flag=transport_error_flag,
            success_flag=success_flag,
            issue_code=issue_code,
            error_class=error_class,
            error_message=error_message,
            documents_emitted=documents_emitted,
            request_headers_redacted_json=redact_mapping(request_headers),
            response_headers_redacted_json=redact_mapping(response_headers),
            rate_limit_headers_json=redact_mapping(rate_limit_headers),
            response_body_sha256=response_body_sha256,
            response_blob_path=response_blob_path,
            metadata_json=metadata or {},
        )
        self.session.add(event)
        self.session.flush()
        return event

    def _upsert_source_issue(
        self,
        *,
        source_id: str,
        crawl_run_id: str | None,
        issue_code: str,
        severity: IssueSeverity,
        example_url: str | None,
        example_status_code: int | None = None,
        error_class: str | None = None,
        error_message: str | None = None,
        impact_on_yield: str | None = None,
        recommended_remediation: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SourceIssue:
        correlation = ensure_correlation()
        existing = self.session.execute(
            select(SourceIssue).where(SourceIssue.source_id == source_id, SourceIssue.issue_code == issue_code)
        ).scalar_one_or_none()
        if existing:
            existing.last_seen_at = datetime.now(UTC).replace(tzinfo=None)
            existing.frequency += 1
            existing.severity = severity
            existing.example_url = example_url or existing.example_url
            existing.example_status_code = example_status_code or existing.example_status_code
            existing.error_class = error_class or existing.error_class
            existing.error_message = error_message or existing.error_message
            existing.impact_on_yield = impact_on_yield or existing.impact_on_yield
            existing.recommended_remediation = recommended_remediation or existing.recommended_remediation
            existing.crawl_run_id = crawl_run_id or existing.crawl_run_id
            existing.trace_id = correlation.trace_id
            existing.request_id = correlation.request_id
            existing.metadata_json = _merge_json(existing.metadata_json, metadata or {})
            return existing
        issue = SourceIssue(
            source_id=source_id,
            crawl_run_id=crawl_run_id,
            issue_code=issue_code,
            severity=severity,
            example_url=example_url,
            example_status_code=example_status_code,
            error_class=error_class,
            error_message=error_message,
            impact_on_yield=impact_on_yield,
            recommended_remediation=recommended_remediation,
            trace_id=correlation.trace_id,
            request_id=correlation.request_id,
            metadata_json=metadata or {},
        )
        self.session.add(issue)
        self.session.flush()
        self.recorder.emit_event(
            "issue.upsert",
            level="warning",
            component="pipeline",
            phase="health",
            run_id=current_correlation().run_id,
            crawl_run_id=crawl_run_id,
            source_id=source_id,
            issue_code=issue_code,
            status=issue.state,
            payload={
                "severity": severity.value,
                "example_url": example_url,
                "example_status_code": example_status_code,
                "recommended_remediation": recommended_remediation,
                "metadata": metadata or {},
            },
        )
        return issue

    def _close_source_issues(self, source_id: str, *, canary_only: bool = False) -> int:
        closed = 0
        for issue in self.session.execute(
            select(SourceIssue).where(SourceIssue.source_id == source_id, SourceIssue.state == "open")
        ).scalars():
            metadata = issue.metadata_json or {}
            if canary_only and not metadata.get("canary"):
                continue
            issue.state = "closed"
            issue.last_seen_at = datetime.now(UTC).replace(tzinfo=None)
            closed += 1
        return closed

    def _upsert_query_execution(
        self,
        *,
        source_id: str,
        crawl_run_id: str | None,
        query_id: str | None,
        query_text: str | None,
        query_family: str | None = None,
        phase: str = "runtime",
        target_field: str = "mixed",
        negatives_applied: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        renderer: str | None = None,
        abstract_query_text: str | None = None,
        rendered_query_text: str | None = None,
        was_executed: bool = True,
        skip_reason: str | None = None,
        watermark_in: str | None = None,
        watermark_out: str | None = None,
        cursor_count: int = 0,
        duplicate_fetches_avoided: int = 0,
        browse_only_pass: bool = False,
        status: str | None = None,
        docs: int = 0,
        evidence: int = 0,
        opps: int = 0,
        signals: int = 0,
        requests: int = 1,
    ) -> None:
        if not query_id or not query_text:
            return
        correlation = ensure_correlation()
        existing = self.session.execute(
            select(QueryExecution).where(
                QueryExecution.source_id == source_id,
                QueryExecution.crawl_run_id == crawl_run_id,
                QueryExecution.query_id == query_id,
            )
        ).scalar_one_or_none()
        if existing:
            existing.requests += requests
            existing.hits += docs
            existing.docs += docs
            existing.evidence += evidence
            existing.opps += opps
            existing.signals += signals
            existing.renderer = renderer or existing.renderer
            existing.abstract_query_text = abstract_query_text or existing.abstract_query_text
            existing.rendered_query_text = rendered_query_text or existing.rendered_query_text
            existing.was_executed = was_executed
            existing.skip_reason = skip_reason or existing.skip_reason
            existing.watermark_in = watermark_in or existing.watermark_in
            existing.watermark_out = watermark_out or existing.watermark_out
            existing.cursor_count += cursor_count
            existing.duplicate_fetches_avoided += duplicate_fetches_avoided
            existing.browse_only_pass = browse_only_pass
            existing.status = status or existing.status
            existing.trace_id = correlation.trace_id
            if metadata:
                existing.metadata_json = _merge_json(existing.metadata_json, metadata)
            return
        record = QueryExecution(
            source_id=source_id,
            crawl_run_id=crawl_run_id,
            query_id=query_id,
            query_text=query_text,
            renderer=renderer,
            abstract_query_text=abstract_query_text,
            rendered_query_text=rendered_query_text or query_text,
            query_family=query_family or (query_id.split(":")[0] if ":" in query_id else None),
            phase=phase,
            target_field=target_field,
            negatives_applied_json=negatives_applied or [],
            was_executed=was_executed,
            skip_reason=skip_reason,
            watermark_in=watermark_in,
            watermark_out=watermark_out,
            cursor_count=cursor_count,
            duplicate_fetches_avoided=duplicate_fetches_avoided,
            browse_only_pass=browse_only_pass,
            status=status,
            trace_id=correlation.trace_id,
            requests=requests,
            hits=docs,
            docs=docs,
            evidence=evidence,
            opps=opps,
            signals=signals,
            metadata_json=metadata or {},
        )
        self.session.add(record)
        self.session.flush()

    def _update_source_daily_metric(self, source: SourceRegistry, run: CrawlRun) -> None:
        metric_date = (run.finished_at or datetime.now(UTC).replace(tzinfo=None)).replace(hour=0, minute=0, second=0, microsecond=0)
        existing = self.session.execute(
            select(SourceDailyMetric).where(
                SourceDailyMetric.source_id == source.id,
                SourceDailyMetric.metric_date == metric_date,
            )
        ).scalar_one_or_none()
        previous_metric = self.session.execute(
            select(SourceDailyMetric)
            .where(SourceDailyMetric.source_id == source.id)
            .order_by(SourceDailyMetric.metric_date.desc())
            .limit(1)
        ).scalar_one_or_none()
        evidence_rows = list(
            self.session.execute(
                select(EvidenceRecord).where(EvidenceRecord.source_id == source.id)
            ).scalars()
        )
        completeness = 0.0
        if evidence_rows:
            completeness = round(
                sum(
                    1
                    for row in evidence_rows
                    if row.title and row.buyer_name and row.source_url and row.language_status
                )
                / max(len(evidence_rows), 1),
                4,
            )
        opportunities_created = int(
            self.session.execute(
                select(func.count(OpportunityCandidate.id))
                .join(EvidenceRecord, EvidenceRecord.id == OpportunityCandidate.evidence_record_id)
                .where(EvidenceRecord.source_id == source.id)
            ).scalar_one()
            or 0
        )
        market_signals_created = int(
            self.session.execute(
                select(func.count(MarketSignal.id))
                .join(EvidenceRecord, EvidenceRecord.id == MarketSignal.evidence_record_id)
                .where(EvidenceRecord.source_id == source.id)
            ).scalar_one()
            or 0
        )
        unique_buyers_found = int(
            self.session.execute(
                select(func.count(func.distinct(EvidenceRecord.buyer_name))).where(EvidenceRecord.source_id == source.id)
            ).scalar_one()
            or 0
        )
        english_acceptance = round(
            sum(1 for row in evidence_rows if row.english_evidence_source) / max(len(evidence_rows), 1),
            4,
        )
        fetch_events = list(
            self.session.execute(select(SourceFetchEvent).where(SourceFetchEvent.crawl_run_id == run.id)).scalars()
        )
        success_rate = round(sum(1 for event in fetch_events if event.success_flag) / max(len(fetch_events), 1), 4)
        avg_latency = round(sum((event.latency_ms or 0) for event in fetch_events) / max(len(fetch_events), 1), 2)
        rate_429 = round(sum(1 for event in fetch_events if event.response_status_code == 429) / max(len(fetch_events), 1), 4)
        rate_403 = round(sum(1 for event in fetch_events if event.response_status_code == 403) / max(len(fetch_events), 1), 4)
        timeout_rate = round(sum(1 for event in fetch_events if event.issue_code == "timeout") / max(len(fetch_events), 1), 4)
        parser_failure_rate = round(sum(1 for event in fetch_events if event.issue_code in {"parser_error", "parser_drift"}) / max(len(fetch_events), 1), 4)
        operational_state = OperationalState.HEALTHY if run.status == CrawlStatus.SUCCEEDED and run.documents_fetched else OperationalState.DEGRADED
        yield_state = YieldState.ZERO_YIELD if run.documents_fetched == 0 else YieldState.NORMAL_YIELD
        if run.candidates_created >= 5:
            yield_state = YieldState.HIGH_YIELD
        elif run.candidates_created == 0 and run.documents_fetched > 0:
            yield_state = YieldState.LOW_YIELD
        if existing:
            previous_operational_state = existing.operational_state
            previous_yield_state = existing.yield_state
            existing.documents_fetched += run.documents_fetched
            existing.evidence_extracted += run.evidence_extracted
            existing.market_signals_created = market_signals_created
            existing.opportunities_created = opportunities_created
            existing.success_rate = success_rate
            existing.avg_latency_ms = avg_latency
            existing.rate_429 = rate_429
            existing.rate_403 = rate_403
            existing.timeout_rate = timeout_rate
            existing.parser_failure_rate = parser_failure_rate
            existing.english_acceptance_rate = english_acceptance
            existing.field_completeness_score = completeness
            existing.unique_buyers_found = unique_buyers_found
            existing.operational_state = operational_state
            existing.yield_state = yield_state
            self._record_source_state_transition(
                source_id=source.id,
                previous_operational_state=previous_operational_state,
                new_operational_state=operational_state,
                previous_yield_state=previous_yield_state,
                new_yield_state=yield_state,
                reason_code="daily_metric_update",
                evidence={"documents_fetched": run.documents_fetched, "candidates_created": run.candidates_created},
                run_id=current_correlation().run_id,
            )
            return
        metric = SourceDailyMetric(
            source_id=source.id,
            metric_date=metric_date,
            documents_fetched=run.documents_fetched,
            evidence_extracted=run.evidence_extracted,
            market_signals_created=market_signals_created,
            opportunities_created=opportunities_created,
            approved_opportunities=0,
            success_rate=success_rate,
            avg_latency_ms=avg_latency,
            rate_429=rate_429,
            rate_403=rate_403,
            timeout_rate=timeout_rate,
            parser_failure_rate=parser_failure_rate,
            english_acceptance_rate=english_acceptance,
            field_completeness_score=completeness,
            unique_buyers_found=unique_buyers_found,
            operational_state=operational_state,
            yield_state=yield_state,
        )
        self.session.add(metric)
        self.session.flush()
        self._record_source_state_transition(
            source_id=source.id,
            previous_operational_state=previous_metric.operational_state if previous_metric else None,
            new_operational_state=operational_state,
            previous_yield_state=previous_metric.yield_state if previous_metric else None,
            new_yield_state=yield_state,
            reason_code="daily_metric_create",
            evidence={"documents_fetched": run.documents_fetched, "candidates_created": run.candidates_created},
            run_id=current_correlation().run_id,
        )

    def _record_source_state_transition(
        self,
        *,
        source_id: str,
        previous_operational_state: OperationalState | None,
        new_operational_state: OperationalState,
        previous_yield_state: YieldState | None,
        new_yield_state: YieldState,
        reason_code: str,
        evidence: dict[str, Any],
        run_id: str | None,
    ) -> None:
        if previous_operational_state == new_operational_state and previous_yield_state == new_yield_state:
            return
        transition = SourceStateTransition(
            source_id=source_id,
            previous_operational_state=previous_operational_state,
            new_operational_state=new_operational_state,
            previous_yield_state=previous_yield_state,
            new_yield_state=new_yield_state,
            reason_code=reason_code,
            evidence_json=evidence,
            run_id=run_id,
            trace_id=current_correlation().trace_id,
        )
        self.session.add(transition)
        self.session.flush()
        self.recorder.emit_event(
            "health.state_transition",
            component="health",
            phase="source_state",
            run_id=run_id,
            source_id=source_id,
            status=new_operational_state.value,
            payload={
                "previous_operational_state": previous_operational_state.value if previous_operational_state else None,
                "new_operational_state": new_operational_state.value,
                "previous_yield_state": previous_yield_state.value if previous_yield_state else None,
                "new_yield_state": new_yield_state.value,
                "reason_code": reason_code,
                "evidence": evidence,
            },
        )

    def _classify_issue(self, exc: Exception) -> tuple[str, IssueSeverity]:
        message = str(exc).lower()
        if "429" in message:
            return "throttled_429", IssueSeverity.HIGH
        if "403" in message:
            return "blocked_403", IssueSeverity.HIGH
        if "401" in message:
            return "blocked_401", IssueSeverity.HIGH
        if "timed out" in message or "timeout" in message:
            return "timeout", IssueSeverity.MEDIUM
        if "ssl" in message:
            return "ssl_error", IssueSeverity.MEDIUM
        if "name or service not known" in message or "dns" in message:
            return "dns_error", IssueSeverity.MEDIUM
        if "robot" in message:
            return "robots_blocked", IssueSeverity.MEDIUM
        return "parser_error", IssueSeverity.MEDIUM

    def _recommended_fix(self, issue_code: str) -> str:
        fixes = {
            "throttled_429": "Reduce cadence or page size and review source rate-limit policy.",
            "blocked_403": "Check whether the source has tightened public access or now needs a compliant credential path.",
            "blocked_401": "Add a documented credential or disable the source until access is lawful again.",
            "timeout": "Lower batch size, increase timeout cautiously, and inspect target responsiveness.",
            "ssl_error": "Verify TLS compatibility and certificate chain from the runtime environment.",
            "dns_error": "Check endpoint validity and network resolution.",
            "robots_blocked": "Do not crawl further; retain as blocked and look for alternative public surfaces.",
            "parser_error": "Inspect the latest raw document and update the adapter or fallback parser.",
        }
        return fixes.get(issue_code, "Inspect the latest fetch event and raw evidence to determine the next fix.")

    def _upsert_signal(self, evidence: EvidenceRecord, organization: Organization, draft) -> MarketSignal:
        existing = self.session.execute(
            select(MarketSignal).where(MarketSignal.evidence_record_id == evidence.id)
        ).scalar_one_or_none()
        account_cluster = self._resolve_account_cluster(organization, draft)
        signal_cluster = self._resolve_signal_cluster(draft)
        if existing:
            existing.summary = draft.summary
            existing.confidence = draft.confidence
            existing.account_cluster_id = account_cluster.id
            existing.signal_cluster_id = signal_cluster.id
            existing.signal_lane = RadarLane(draft.signal_lane)
            existing.recommended_action = RecommendedAction(draft.recommended_action)
            existing.route_to_market = RouteToMarket(draft.route_to_market)
            existing.retrieval_score = draft.retrieval_score
            existing.source_trust = draft.source_trust
            existing.account_heat_score = draft.account_heat_score
            existing.trigger_type = draft.trigger_type
            existing.trigger_strength = draft.trigger_strength
            return existing
        signal = MarketSignal(
            evidence_record_id=evidence.id,
            organization_id=organization.id,
            account_cluster_id=account_cluster.id,
            signal_cluster_id=signal_cluster.id,
            signal_type=draft.signal_type,
            signal_lane=RadarLane(draft.signal_lane),
            recommended_action=RecommendedAction(draft.recommended_action),
            route_to_market=RouteToMarket(draft.route_to_market),
            title=draft.title,
            summary=draft.summary,
            source_url=draft.source_url,
            region=draft.region,
            country=draft.country,
            confidence=draft.confidence,
            retrieval_score=draft.retrieval_score,
            source_trust=draft.source_trust,
            account_heat_score=draft.account_heat_score,
            trigger_type=draft.trigger_type,
            trigger_strength=draft.trigger_strength,
            public_access_mode=PublicAccessMode(draft.public_access_mode),
            english_evidence_source=draft.english_evidence_source,
            buyer_intent_evidence_json=draft.buyer_intent_evidence,
            legacy_evidence_json=draft.legacy_evidence,
            query_family=draft.query_family,
            discovery_query_id=draft.discovery_query_id,
            discovery_query_text=draft.discovery_query_text,
            portal_fingerprint=draft.portal_fingerprint,
            known_blind_spot_reason=draft.known_blind_spot_reason,
            corroboration_count=draft.corroboration_count,
            tags_json=draft.tags,
            raw_excerpt=draft.raw_excerpt,
        )
        self.session.add(signal)
        self.session.flush()
        return signal

    def _upsert_exclusion(self, evidence: EvidenceRecord, assessment: RetrievalAssessment, *, reason: str) -> ExclusionAudit:
        existing = self.session.execute(
            select(ExclusionAudit).where(
                ExclusionAudit.evidence_record_id == evidence.id,
                ExclusionAudit.reason == reason,
            )
        ).scalar_one_or_none()
        details = {
            "query_id": assessment.query_id,
            "query_text": assessment.query_text,
            "component_scores": assessment.component_scores,
            "language_details": assessment.language_details,
            "matched_service_terms": list(assessment.matched_service_terms),
            "matched_procurement_terms": list(assessment.matched_procurement_terms),
            "matched_route_terms": list(assessment.matched_route_terms),
            "matched_trigger_terms": list(assessment.matched_trigger_terms),
            "signal_lane": assessment.signal_lane.value if assessment.signal_lane else None,
            "recommended_action": assessment.recommended_action.value,
            "route_to_market": assessment.route_to_market.value,
        }
        if existing:
            existing.retrieval_score = assessment.retrieval_score
            existing.language_status = assessment.language_status
            existing.matched_positive_terms_json = list(assessment.matched_positive_terms)
            existing.matched_negative_terms_json = list(assessment.matched_negative_terms)
            existing.details_json = details
            return existing
        exclusion = ExclusionAudit(
            evidence_record_id=evidence.id,
            reason=reason,
            retrieval_score=assessment.retrieval_score,
            language_status=assessment.language_status,
            matched_positive_terms_json=list(assessment.matched_positive_terms),
            matched_negative_terms_json=list(assessment.matched_negative_terms),
            details_json=details,
        )
        self.session.add(exclusion)
        self.session.flush()
        return exclusion

    def _purge_invalidated_records(self, evidence_record_id: str | None = None) -> int:
        statement = select(EvidenceRecord).where(EvidenceRecord.exclusion_reason.is_not(None))
        if evidence_record_id:
            statement = statement.where(EvidenceRecord.id == evidence_record_id)
        purged = 0
        for evidence in self.session.execute(statement).scalars():
            for candidate in self.session.execute(
                select(OpportunityCandidate).where(OpportunityCandidate.evidence_record_id == evidence.id)
            ).scalars():
                self.session.delete(candidate)
                purged += 1
            for signal in self.session.execute(
                select(MarketSignal).where(MarketSignal.evidence_record_id == evidence.id)
            ).scalars():
                self.session.delete(signal)
                purged += 1
        if purged:
            self.session.flush()
        return purged

    def _estimate_corroboration(self, extracted) -> int:
        score = 0
        if extracted.procurement_id:
            score += self.session.execute(
                select(func.count(EvidenceRecord.id)).where(EvidenceRecord.procurement_id == extracted.procurement_id)
            ).scalar_one()
        if extracted.buyer_name and extracted.title:
            score += self.session.execute(
                select(func.count(EvidenceRecord.id)).where(
                    func.lower(EvidenceRecord.buyer_name) == extracted.buyer_name.lower(),
                    func.lower(EvidenceRecord.title) == extracted.title.lower(),
                )
            ).scalar_one()
        if extracted.source_url:
            score += self.session.execute(
                select(func.count(EvidenceRecord.id)).where(EvidenceRecord.source_url == extracted.source_url)
            ).scalar_one()
        return max(0, int(score))

    def reprocess(self, document_id: str) -> dict[str, Any]:
        job = self._start_job(JobType.REPROCESS, metadata={"document_id": document_id, "job_kind": "reprocess"})
        raw_document = self.session.get(RawDocument, document_id)
        if not raw_document:
            self._finish_job(job, CrawlStatus.FAILED, errors=[{"message": f"Raw document '{document_id}' was not found.", "type": "ValueError"}])
            raise ValueError(f"Raw document '{document_id}' was not found.")
        source = self.session.get(SourceRegistry, raw_document.source_id)
        if not source:
            self._finish_job(job, CrawlStatus.FAILED, errors=[{"message": f"Source '{raw_document.source_id}' was not found.", "type": "ValueError"}])
            raise ValueError(f"Source '{raw_document.source_id}' was not found.")
        payload = self.blob_store.get_bytes(raw_document.blob_path)
        evidence_count, created = self._process_raw_document(source, raw_document, payload)
        purged = self._purge_invalidated_records()
        job.source_id = source.id
        job.documents_fetched = 1
        job.evidence_extracted = evidence_count
        job.candidates_created = created
        job.opportunities_created = created
        job.metadata_json = _merge_json(job.metadata_json, {"purged_invalidated": purged})
        self._finish_job(job, CrawlStatus.SUCCEEDED)
        return {
            "document_id": document_id,
            "evidence_records": evidence_count,
            "created_or_updated": created,
            "purged_invalidated": purged,
        }

    def set_candidate_status(self, candidate_id: str, status: CandidateStatus, reason: str | None = None) -> OpportunityCandidate:
        candidate = self.session.get(OpportunityCandidate, candidate_id)
        if not candidate:
            raise ValueError(f"Candidate '{candidate_id}' was not found.")
        candidate.status = status
        candidate.review_reason = reason
        candidate.updated_at = datetime.now(UTC).replace(tzinfo=None)
        return candidate

    def export(self, *, fmt: str, filters: dict[str, Any]) -> ExportResult:
        job = self._start_job(JobType.EXPORT, metadata={"fmt": fmt, "filters": filters})
        try:
            result = self.exporter.export_all(self.session, fmt=fmt, filters=filters)
            job.candidates_created = len(result.files)
            job.metadata_json = _merge_json(job.metadata_json, {"directory": str(result.directory), "files": [str(item) for item in result.files]})
            self._finish_job(job, CrawlStatus.SUCCEEDED)
            return result
        except Exception as exc:
            self._finish_job(job, CrawlStatus.FAILED, errors=[{"message": str(exc), "type": type(exc).__name__}])
            raise


def _merge_json(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    merged = dict(left or {})
    for key, value in (right or {}).items():
        if key not in merged:
            merged[key] = value
            continue
        if merged[key] == value:
            continue
        if isinstance(merged[key], list):
            if value not in merged[key]:
                merged[key].append(value)
            continue
        merged[key] = [merged[key], value]
    return merged


def _status_from_exception(exc: Exception) -> int | None:
    message = str(exc)
    match = next((code for code in (429, 403, 401, 404, 500, 502, 503, 504) if str(code) in message), None)
    return match
