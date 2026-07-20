from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import Select, desc, func, select
from sqlalchemy.orm import Session

from d365opps.authenticity import classify_row_authenticity, classify_source_authenticity, is_canonical_authentic_row
from d365opps.config import get_settings
from d365opps.metric_catalog import metric_catalog_payload
from d365opps.models import (
    AccountCluster,
    CandidateStatus,
    Contact,
    CrawlRun,
    CrawlStatus,
    DiscoveryStatus,
    EvidenceRecord,
    ExclusionAudit,
    ForthcomingState,
    JobRun,
    MarketSignal,
    OperationalState,
    OpportunityCluster,
    OpportunityCandidate,
    Organization,
    PublicAccessMode,
    RadarLane,
    QueryExecution,
    RawDocument,
    RecommendedAction,
    SourceCanaryResult,
    SourceDailyMetric,
    SourceDiscoveryCandidate,
    SourceFetchEvent,
    SourceHealthStatus,
    SourceIssue,
    SourceRegistry,
    SourceStateTransition,
    UiSavedView,
    YieldState,
)
from d365opps.pitchability import apply_evaluation_to_row, evaluate_record, is_demo_record


def _iso(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _paginate(items: list[dict[str, Any]], *, offset: int, limit: int) -> dict[str, Any]:
    return {"items": items[offset : offset + limit], "total": len(items), "offset": offset, "limit": limit}


class OpsService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.settings = get_settings()

    def overview(self) -> dict[str, Any]:
        sources = self.list_sources(limit=500, offset=0)["items"]
        issues = self.list_issues(limit=10, offset=0, sort_by="severity", sort_dir="desc")["items"]
        candidates = self.list_discovery_candidates(limit=25, offset=0)["items"]
        now = datetime.now(UTC)
        opportunity_rows = list(self.session.execute(select(OpportunityCandidate)).scalars())
        signal_rows = list(self.session.execute(select(MarketSignal)).scalars())
        evidence_rows = list(self.session.execute(select(EvidenceRecord)).scalars())
        raw_documents = list(self.session.execute(select(RawDocument)).scalars())
        exclusions = list(self.session.execute(select(ExclusionAudit)).scalars())
        records_by_day = self._records_by_day()
        opportunity_by_country = defaultdict(int)
        opportunity_by_lane = defaultdict(int)
        app_family_counts = defaultdict(int)
        for opp in opportunity_rows:
            opportunity_by_country[opp.country or "unknown"] += 1
            opportunity_by_lane[opp.signal_lane.value] += 1
            app_family_counts[opp.app_family] += 1
        active_sources = [source for source in sources if source["enabled"]]
        live_sources = [source for source in sources if source["enabled"] and source["data_mode"] == "live"]
        healthy_live_sources = [source for source in live_sources if source["operational_state"] == "healthy"]
        problems = [issue for issue in issues if issue["state"] == "open"][:8]
        blocked = [source for source in sources if source["operational_state"] in {"blocked", "robots_disallowed", "auth_required", "unsupported"}]
        live_records = sum(1 for row in [*opportunity_rows, *signal_rows] if not self._is_demo_record(row))
        demo_records = sum(1 for row in [*opportunity_rows, *signal_rows] if self._is_demo_record(row))
        data_mode = "MIXED" if live_records and demo_records else "DEMO" if demo_records else "LIVE"
        last_live_refresh = self._last_job_finished(mode="incremental_sync")
        last_successful_backfill = self._last_job_finished(mode="bootstrap_backfill")
        latest_run_scope = self._latest_run_scope_kpis()
        canonical_metrics, evaluated_rows = self._canonical_metric_snapshot(opportunity_rows, as_of=now)
        opportunities = sorted(
            [row for row in evaluated_rows if row.get("sales_handoff_state") == "seller_ready"],
            key=lambda row: (row.get("opportunity_score") or 0, row.get("retrieval_score") or 0),
            reverse=True,
        )
        closing_soon = [
            opp for opp in opportunities if opp.get("close_date") and datetime.fromisoformat(opp["close_date"]).replace(tzinfo=UTC) <= now + timedelta(days=14)
        ]
        recall_alerts = self._recall_sanity_alerts(
            sources=sources,
            opportunities=opportunity_rows,
            signals=signal_rows,
            evidence=evidence_rows,
        )
        return {
            "data_mode": data_mode,
            "demo_mode": self.settings.demo_mode,
            "metric_catalog": metric_catalog_payload(),
            "canonical_metrics": canonical_metrics,
            "kpis": {
                "sources_configured": len(sources),
                "total_active_sources": len(active_sources),
                "live_enabled_sources": len(live_sources),
                "parser_implemented_enabled": sum(1 for source in live_sources if source["parser_implemented"]),
                "production_ready_enabled": sum(1 for source in live_sources if source["production_ready"]),
                "production_ready_public_no_auth_sources": sum(1 for source in live_sources if source["production_ready"] and source["public_access_mode"] == "public"),
                "healthy_sources": sum(1 for source in sources if source["operational_state"] == "healthy"),
                "healthy_live_sources": len(healthy_live_sources),
                "degraded_sources": sum(1 for source in sources if source["operational_state"] == "degraded"),
                "throttled_sources": sum(1 for source in sources if source["operational_state"] == "throttled"),
                "blocked_sources": len(blocked),
                "credential_blocked_sources": sum(1 for source in sources if source["operational_state"] == "auth_required"),
                "parser_broken_sources": sum(1 for source in sources if source["operational_state"] == "parser_broken"),
                "blocked_or_throttled_sources": sum(1 for source in sources if source["operational_state"] in {"blocked", "robots_disallowed", "auth_required", "throttled"}),
                "candidate_sources_pending_review": sum(1 for candidate in candidates if candidate["review_status"] == "pending_review"),
                "live_records": live_records,
                "demo_records": demo_records,
                "raw_records_ingested": len(raw_documents),
                "successful_fetches": canonical_metrics["successful_fetches"],
                "fetched_documents": canonical_metrics["fetched_documents"],
                "fetched_detail_pages": canonical_metrics["fetched_detail_pages"],
                "fetched_attachments": canonical_metrics["fetched_attachments"],
                "documents_fetched_24h": self._sum_metric("documents_fetched", days=1),
                "documents_fetched_7d": self._sum_metric("documents_fetched", days=7),
                "evidence_records_extracted": canonical_metrics["evidence_rows"],
                "evidence_rows": canonical_metrics["evidence_rows"],
                "parsed_documents": canonical_metrics["parsed_documents"],
                "classified_documents": canonical_metrics["classified_documents"],
                "market_signals_created": len(signal_rows),
                "opportunity_candidates_created": len(opportunity_rows),
                "approved_opportunities": self._count(OpportunityCandidate, OpportunityCandidate.status == CandidateStatus.APPROVED),
                "rejected_items": self._count(OpportunityCandidate, OpportunityCandidate.status == CandidateStatus.REJECTED),
                "excluded_items": len(exclusions),
                "unique_buyers_accounts": self._count(AccountCluster),
                "high_priority_closing_soon": len(closing_soon),
                "retained_d365_records": canonical_metrics["retained_d365_records"],
                "duplicates_removed": canonical_metrics["duplicates_removed"],
                "retained_without_anchor_total": canonical_metrics["retained_without_anchor_total"],
                "english_insufficient_total": canonical_metrics["english_insufficient_total"],
                "stale_or_awarded_total": canonical_metrics["stale_or_awarded_total"],
                "monitor_only_total": canonical_metrics["monitor_only_total"],
                "current_actionable_total": canonical_metrics["current_actionable_total"],
                "current_bid_now_total": canonical_metrics["current_bid_now_total"],
                "current_pre_position_total": canonical_metrics["current_pre_position_total"],
                "award_watch_total": canonical_metrics["award_watch_total"],
                "renewal_watch_total": canonical_metrics["renewal_watch_total"],
                "seller_ready_total": canonical_metrics["seller_ready_total"],
                "seller_ready_bid_now_total": canonical_metrics["seller_ready_bid_now_total"],
                "seller_ready_pre_position_total": canonical_metrics["seller_ready_pre_position_total"],
                "research_ready_total": canonical_metrics["research_ready_total"],
                "monitor_total": canonical_metrics["monitor_total"],
                "reject_total": canonical_metrics["reject_total"],
                "sources_yielding_seller_ready_records": canonical_metrics["sources_yielding_seller_ready_records"],
                "rolling_30d_opportunities": sum(1 for row in opportunity_rows if row.created_at and row.created_at >= (now - timedelta(days=30)).replace(tzinfo=None)),
                "rolling_90d_opportunities": sum(1 for row in opportunity_rows if row.created_at and row.created_at >= (now - timedelta(days=90)).replace(tzinfo=None)),
                "live_open_opportunities": sum(1 for row in opportunity_rows if not self._is_demo_record(row) and (row.close_date is None or row.close_date >= now.replace(tzinfo=None))),
                "live_pre_positioning_items": sum(1 for row in opportunity_rows if not self._is_demo_record(row) and row.signal_lane == RadarLane.PRE_POSITIONING),
                "direct_outreach_triggers": sum(1 for row in signal_rows if not self._is_demo_record(row) and row.signal_lane == RadarLane.DIRECT_OUTREACH),
                "install_base_triggers": sum(1 for row in signal_rows if not self._is_demo_record(row) and row.signal_lane == RadarLane.INSTALL_BASE_TRIGGER),
                "last_live_refresh": _iso(last_live_refresh),
                "last_successful_backfill": _iso(last_successful_backfill),
                "sources_touched_this_run": latest_run_scope["sources_touched_this_run"],
                "sources_succeeded_this_run": latest_run_scope["sources_succeeded_this_run"],
                "sources_yielding_real_records_this_run": latest_run_scope["sources_yielding_real_records_this_run"],
                "sources_yielding_d365_records_this_run": latest_run_scope["sources_yielding_d365_records_this_run"],
            },
            "trends": {
                "records_by_day": records_by_day,
                "source_health_over_time": self._source_health_trend(),
                "opportunities_by_country": [{"country": key, "count": value} for key, value in sorted(opportunity_by_country.items(), key=lambda item: item[1], reverse=True)],
                "opportunities_by_lane": [{"lane": key, "count": value} for key, value in sorted(opportunity_by_lane.items(), key=lambda item: item[1], reverse=True)],
                "opportunities_by_app_family": [{"app_family": key, "count": value} for key, value in sorted(app_family_counts.items(), key=lambda item: item[1], reverse=True)],
            },
            "top_problems_now": problems,
            "best_leads_right_now": opportunities[:10],
            "coverage_gaps": self._coverage_gaps(sources, candidates),
            "recall_sanity": recall_alerts,
        }

    def list_sources(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        state: str | None = None,
        region: str | None = None,
        country: str | None = None,
        lane: str | None = None,
        enabled: bool | None = None,
        source_family: str | None = None,
        sort_by: str = "name",
        sort_dir: str = "asc",
    ) -> dict[str, Any]:
        rows = list(self.session.execute(select(SourceRegistry)).scalars())
        items = [self._source_summary(row) for row in rows]
        if state:
            items = [row for row in items if row["operational_state"] == state or row["yield_state"] == state or row["forthcoming_state"] == state]
        if region:
            items = [row for row in items if row["region"] == region]
        if country:
            items = [row for row in items if row["country"] == country]
        if lane:
            items = [row for row in items if lane in row["supported_lanes"]]
        if enabled is not None:
            items = [row for row in items if row["enabled"] is enabled]
        if source_family:
            items = [row for row in items if row["source_family"] == source_family]
        items.sort(key=lambda row: row.get(sort_by) or 0, reverse=sort_dir == "desc")
        return _paginate(items, offset=offset, limit=limit)

    def get_source(self, source_id: str) -> dict[str, Any]:
        source = self.session.get(SourceRegistry, source_id)
        if not source:
            raise KeyError(source_id)
        summary = self._source_summary(source)
        summary["runs"] = self.source_runs(source_id, limit=20, offset=0)["items"]
        summary["issues"] = self.source_issues(source_id, limit=20, offset=0)["items"]
        summary["documents"] = self.source_documents(source_id, limit=20, offset=0)["items"]
        summary["recent_evidence"] = [
            self._evidence_row(row)
            for row in self.session.execute(
                select(EvidenceRecord).where(EvidenceRecord.source_id == source_id).order_by(desc(EvidenceRecord.publication_date)).limit(20)
            ).scalars()
        ]
        summary["recent_opportunities"] = [
            self._opportunity_row(row)
            for row in self.session.execute(
                select(OpportunityCandidate)
                .join(EvidenceRecord, EvidenceRecord.id == OpportunityCandidate.evidence_record_id)
                .where(EvidenceRecord.source_id == source_id)
                .order_by(desc(OpportunityCandidate.updated_at))
                .limit(20)
            ).scalars()
        ]
        summary["query_executions"] = self.list_queries(limit=20, offset=0, source_id=source_id)["items"]
        fetch_events = list(
            self.session.execute(select(SourceFetchEvent).where(SourceFetchEvent.source_id == source_id)).scalars()
        )
        evidence_rows = list(
            self.session.execute(select(EvidenceRecord).where(EvidenceRecord.source_id == source_id)).scalars()
        )
        opportunity_rows = list(
            self.session.execute(
                select(OpportunityCandidate)
                .join(EvidenceRecord, EvidenceRecord.id == OpportunityCandidate.evidence_record_id)
                .where(EvidenceRecord.source_id == source_id)
            ).scalars()
        )
        signal_rows = list(
            self.session.execute(
                select(MarketSignal)
                .join(EvidenceRecord, EvidenceRecord.id == MarketSignal.evidence_record_id)
                .where(EvidenceRecord.source_id == source_id)
            ).scalars()
        )
        summary["health_timeline"] = [
            {
                "date": metric.metric_date.date().isoformat(),
                "operational_state": metric.operational_state.value,
                "yield_state": metric.yield_state.value,
                "documents_fetched": metric.documents_fetched,
                "evidence_extracted": metric.evidence_extracted,
                "opportunities_created": metric.opportunities_created,
            }
            for metric in self.session.execute(
                select(SourceDailyMetric).where(SourceDailyMetric.source_id == source_id).order_by(SourceDailyMetric.metric_date.desc()).limit(30)
            ).scalars()
        ]
        summary["yield_funnel"] = {
            "requests": len(fetch_events),
            "documents": sum(event.documents_emitted for event in fetch_events),
            "evidence": len(evidence_rows),
            "signals": len(signal_rows),
            "opportunities": len(opportunity_rows),
            "approved": sum(1 for item in opportunity_rows if item.status == CandidateStatus.APPROVED),
        }
        summary["field_completeness"] = {
            "title": self._ratio(sum(1 for row in evidence_rows if row.title), len(evidence_rows)),
            "buyer": self._ratio(sum(1 for row in evidence_rows if row.buyer_name), len(evidence_rows)),
            "close_date": self._ratio(sum(1 for row in evidence_rows if row.close_date), len(evidence_rows)),
            "budget": self._ratio(sum(1 for row in evidence_rows if row.budget_value is not None), len(evidence_rows)),
            "contacts": self._ratio(sum(1 for row in evidence_rows if row.contact_email or row.contact_name), len(evidence_rows)),
            "attachments": self._ratio(sum(1 for row in evidence_rows if row.attachment_urls_json), len(evidence_rows)),
            "english": self._ratio(sum(1 for row in evidence_rows if row.english_evidence_source), len(evidence_rows)),
            "classification": self._ratio(sum(1 for row in evidence_rows if row.classification_codes_json), len(evidence_rows)),
            "workload_mapping": self._ratio(sum(1 for row in opportunity_rows if row.app_family and row.business_process), len(opportunity_rows)),
        }
        return summary

    def source_runs(self, source_id: str, *, offset: int = 0, limit: int = 50) -> dict[str, Any]:
        crawl_runs = list(
            self.session.execute(select(CrawlRun).where(CrawlRun.source_id == source_id).order_by(desc(CrawlRun.started_at))).scalars()
        )
        items = [self._run_row(run) for run in crawl_runs]
        return _paginate(items, offset=offset, limit=limit)

    def source_issues(self, source_id: str, *, offset: int = 0, limit: int = 50) -> dict[str, Any]:
        rows = list(
            self.session.execute(select(SourceIssue).where(SourceIssue.source_id == source_id).order_by(desc(SourceIssue.last_seen_at))).scalars()
        )
        items = [self._issue_row(row) for row in rows]
        return _paginate(items, offset=offset, limit=limit)

    def source_documents(self, source_id: str, *, offset: int = 0, limit: int = 50) -> dict[str, Any]:
        rows = list(
            self.session.execute(select(EvidenceRecord).where(EvidenceRecord.source_id == source_id).order_by(desc(EvidenceRecord.publication_date))).scalars()
        )
        return _paginate([self._evidence_row(row) for row in rows], offset=offset, limit=limit)

    def list_discovery_candidates(self, *, offset: int = 0, limit: int = 50, review_status: str | None = None) -> dict[str, Any]:
        rows = list(self.session.execute(select(SourceDiscoveryCandidate).order_by(desc(SourceDiscoveryCandidate.last_seen_at))).scalars())
        items = [self._candidate_source_row(row) for row in rows]
        if review_status:
            items = [row for row in items if row["review_status"] == review_status]
        return _paginate(items, offset=offset, limit=limit)

    def list_issues(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        source_id: str | None = None,
        sort_by: str = "last_seen_at",
        sort_dir: str = "desc",
    ) -> dict[str, Any]:
        statement = select(SourceIssue)
        if source_id:
            statement = statement.where(SourceIssue.source_id == source_id)
        rows = [self._issue_row(row) for row in self.session.execute(statement).scalars()]
        rows.sort(key=lambda row: row.get(sort_by) or 0, reverse=sort_dir == "desc")
        return _paginate(rows, offset=offset, limit=limit)

    def list_runs(self, *, offset: int = 0, limit: int = 50) -> dict[str, Any]:
        job_runs = [self._job_run_row(run) for run in self.session.execute(select(JobRun).order_by(desc(JobRun.started_at))).scalars()]
        crawl_runs = [self._run_row(run) for run in self.session.execute(select(CrawlRun).order_by(desc(CrawlRun.started_at))).scalars()]
        rows = sorted([*job_runs, *crawl_runs], key=lambda row: row["started_at"], reverse=True)
        return _paginate(rows, offset=offset, limit=limit)

    def get_run(self, run_id: str) -> dict[str, Any]:
        job = self.session.get(JobRun, run_id)
        if job:
            detail = self._job_run_row(job)
            if job.crawl_run_id:
                detail["fetch_events"] = self._fetch_events(job.crawl_run_id)
            return detail
        crawl = self.session.get(CrawlRun, run_id)
        if not crawl:
            raise KeyError(run_id)
        detail = self._run_row(crawl)
        detail["fetch_events"] = self._fetch_events(crawl.id)
        detail["query_executions"] = [
            self._query_row(row)
            for row in self.session.execute(select(QueryExecution).where(QueryExecution.crawl_run_id == crawl.id)).scalars()
        ]
        return detail

    def list_queries(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        source_id: str | None = None,
    ) -> dict[str, Any]:
        statement = select(QueryExecution).order_by(desc(QueryExecution.evidence), desc(QueryExecution.opps))
        if source_id:
            statement = statement.where(QueryExecution.source_id == source_id)
        rows = [self._query_row(row) for row in self.session.execute(statement).scalars()]
        return _paginate(rows, offset=offset, limit=limit)

    def list_opportunities(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        keyword: str | None = None,
        country: str | None = None,
        signal_lane: str | None = None,
        recommended_action: str | None = None,
        sort_by: str = "updated_at",
        sort_dir: str = "desc",
    ) -> dict[str, Any]:
        statement: Select[Any] = select(OpportunityCandidate)
        if country:
            statement = statement.where(OpportunityCandidate.country == country)
        if signal_lane:
            statement = statement.where(OpportunityCandidate.signal_lane == RadarLane(signal_lane))
        if recommended_action:
            statement = statement.where(OpportunityCandidate.recommended_action == RecommendedAction(recommended_action))
        rows = [self._opportunity_row(row) for row in self.session.execute(statement).scalars()]
        if keyword:
            lowered = keyword.lower()
            rows = [row for row in rows if lowered in row["title"].lower() or lowered in (row.get("buyer") or "").lower()]
        rows.sort(key=lambda row: row.get(sort_by) or 0, reverse=sort_dir == "desc")
        return _paginate(rows, offset=offset, limit=limit)

    def get_opportunity(self, opportunity_id: str) -> dict[str, Any]:
        row = self.session.get(OpportunityCandidate, opportunity_id)
        if not row:
            raise KeyError(opportunity_id)
        payload = self._opportunity_row(row)
        evidence = self.session.get(EvidenceRecord, row.evidence_record_id)
        payload["evidence"] = self._evidence_row(evidence) if evidence else None
        payload["contacts"] = [
            self._contact_row(contact)
            for contact in self.session.execute(select(Contact).where(Contact.organization_id == row.organization_id)).scalars()
        ]
        if row.cluster_id:
            payload["related_opportunities"] = [
                self._opportunity_row(item)
                for item in self.session.execute(select(OpportunityCandidate).where(OpportunityCandidate.cluster_id == row.cluster_id)).scalars()
            ]
        return payload

    def list_signals(self, *, offset: int = 0, limit: int = 50, signal_lane: str | None = None) -> dict[str, Any]:
        statement = select(MarketSignal).order_by(desc(MarketSignal.created_at))
        if signal_lane:
            statement = statement.where(MarketSignal.signal_lane == RadarLane(signal_lane))
        rows = [self._signal_row(row) for row in self.session.execute(statement).scalars()]
        return _paginate(rows, offset=offset, limit=limit)

    def list_accounts(self, *, offset: int = 0, limit: int = 50) -> dict[str, Any]:
        rows = [self._account_row(row) for row in self.session.execute(select(AccountCluster).order_by(desc(AccountCluster.heat_score))).scalars()]
        return _paginate(rows, offset=offset, limit=limit)

    def coverage(self) -> dict[str, Any]:
        sources = self.list_sources(limit=500, offset=0)["items"]
        opportunities = self.list_opportunities(limit=1000, offset=0)["items"]
        by_country_sources = defaultdict(int)
        by_country_opportunities = defaultdict(int)
        by_country_english = defaultdict(int)
        by_country_lane = defaultdict(lambda: defaultdict(int))
        by_family = defaultdict(lambda: defaultdict(int))
        for source in sources:
            by_country_sources[source["country"] or "unknown"] += 1
            by_family[source["source_family"] or "unknown"][source["country"] or "unknown"] += 1
        for opp in opportunities:
            country = opp["country"] or "unknown"
            by_country_opportunities[country] += 1
            by_country_lane[country][opp["signal_lane"]] += 1
            if opp.get("english_evidence_source"):
                by_country_english[country] += 1
        return {
            "countries_by_active_sources": [{"country": key, "count": value} for key, value in sorted(by_country_sources.items(), key=lambda item: item[1], reverse=True)],
            "countries_by_opportunities_found": [{"country": key, "count": value} for key, value in sorted(by_country_opportunities.items(), key=lambda item: item[1], reverse=True)],
            "countries_by_english_evidence_yield": [{"country": key, "count": value} for key, value in sorted(by_country_english.items(), key=lambda item: item[1], reverse=True)],
            "source_family_heatmap": [{"source_family": family, "countries": dict(countries)} for family, countries in by_family.items()],
            "lane_coverage_by_country": [{"country": country, "lanes": dict(lanes)} for country, lanes in by_country_lane.items()],
            "supported_candidate_blocked_counts": {
                "supported": sum(1 for source in sources if source["operational_state"] not in {"unsupported", "candidate"}),
                "candidate": sum(1 for source in sources if source["operational_state"] == "candidate"),
                "blocked": sum(1 for source in sources if source["operational_state"] in {"blocked", "robots_disallowed", "auth_required"}),
                "unsupported": sum(1 for source in sources if source["operational_state"] == "unsupported"),
            },
            "blind_spot_register": self._coverage_gaps(sources, self.list_discovery_candidates(limit=100, offset=0)["items"]),
        }

    def exports(self) -> dict[str, Any]:
        directories = sorted([path for path in self.settings.export_root.iterdir() if path.is_dir()], reverse=True)
        items: list[dict[str, Any]] = []
        for directory in directories[:25]:
            files = sorted(directory.iterdir())
            items.append(
                {
                    "directory": str(directory),
                    "generated_at": directory.name,
                    "files": [str(path) for path in files],
                    "row_counts": self._export_row_counts(directory),
                }
            )
        return {"items": items, "schema_fields": sorted(self._schema_fields())}

    def list_saved_views(self) -> list[dict[str, Any]]:
        return [self._saved_view_row(row) for row in self.session.execute(select(UiSavedView).order_by(UiSavedView.updated_at.desc())).scalars()]

    def create_saved_view(self, payload: dict[str, Any]) -> dict[str, Any]:
        view = UiSavedView(
            name=payload["name"],
            route=payload["route"],
            description=payload.get("description"),
            filters_json=payload.get("filters_json", {}),
            columns_json=payload.get("columns_json", []),
            density=payload.get("density"),
        )
        self.session.add(view)
        self.session.flush()
        return self._saved_view_row(view)

    def _is_demo_value(self, value: Any) -> bool:
        if value is None:
            return False
        text = str(value).lower()
        return ".example" in text or "northbridge health authority" in text or "harbour transit agency" in text or "lighthouse municipal services" in text

    def _is_demo_record(self, row: Any) -> bool:
        if row is None:
            return False
        fields = [
            getattr(row, "title", None),
            getattr(row, "summary", None),
            getattr(row, "source_url", None),
            getattr(row, "response_url", None),
            getattr(row, "raw_excerpt", None),
        ]
        if any(self._is_demo_value(value) for value in fields):
            return True
        tags = getattr(row, "tags_json", None) or []
        if any(self._is_demo_value(tag) for tag in tags):
            return True
        organization_id = getattr(row, "organization_id", None)
        if organization_id:
            organization = self.session.get(Organization, organization_id)
            if organization and any(self._is_demo_value(value) for value in (organization.website_domain, organization.source_name)):
                return True
        account_cluster_id = getattr(row, "account_cluster_id", None)
        if account_cluster_id:
            account = self.session.get(AccountCluster, account_cluster_id)
            if account and any(self._is_demo_value(value) for value in (account.website_domain, account.canonical_name)):
                return True
        evidence_id = getattr(row, "evidence_record_id", None)
        if evidence_id:
            evidence = self.session.get(EvidenceRecord, evidence_id)
            if evidence:
                return self._is_demo_record(evidence)
        raw_document_id = getattr(row, "raw_document_id", None)
        if raw_document_id:
            raw_document = self.session.get(RawDocument, raw_document_id)
            if raw_document and any(
                self._is_demo_value(value)
                for value in (raw_document.canonical_url, raw_document.document_url, (raw_document.metadata_json or {}).get("listing_url"))
            ):
                return True
        source_id = getattr(row, "source_id", None)
        if source_id:
            source = self.session.get(SourceRegistry, source_id)
            if source and source.name.startswith("demo_"):
                return True
        return False

    def _last_job_finished(self, *, mode: str) -> datetime | None:
        latest: datetime | None = None
        for job in self.session.execute(select(JobRun)).scalars():
            metadata = job.metadata_json or {}
            if metadata.get("mode") != mode:
                continue
            if str(job.status.value) != "succeeded":
                continue
            if latest is None or (job.finished_at and job.finished_at > latest):
                latest = job.finished_at
        return latest

    def _recall_sanity_alerts(
        self,
        *,
        sources: list[dict[str, Any]],
        opportunities: list[OpportunityCandidate],
        signals: list[MarketSignal],
        evidence: list[EvidenceRecord],
    ) -> list[dict[str, Any]]:
        alerts: list[dict[str, Any]] = []
        healthy_live_sources = [source for source in sources if source["data_mode"] == "live" and source["operational_state"] == "healthy"]
        live_opportunities = [row for row in opportunities if not self._is_demo_record(row)]
        live_signals = [row for row in signals if not self._is_demo_record(row)]
        if len(healthy_live_sources) >= 6 and len(live_opportunities) < 5:
            alerts.append(
                {
                    "type": "implausibly_low_global_yield",
                    "severity": "high",
                    "detail": "Healthy live source count is high relative to qualified live opportunities.",
                }
            )
        for source in healthy_live_sources:
            if source["docs_fetched_7d"] == 0:
                alerts.append(
                    {
                        "type": "healthy_source_zero_docs",
                        "severity": "medium",
                        "detail": f"{source['name']} is healthy but emitted zero documents in the last 7 days.",
                    }
                )
        if evidence and not live_opportunities and any(not self._is_demo_record(row) for row in evidence):
            alerts.append(
                {
                    "type": "evidence_without_opportunities",
                    "severity": "medium",
                    "detail": "Live evidence is being extracted, but little or none is reaching the qualified opportunity set.",
                }
            )
        query_families = defaultdict(lambda: {"requests": 0, "yield": 0})
        for row in self.session.execute(select(QueryExecution)).scalars():
            query_families[row.query_family or "unknown"]["requests"] += row.requests
            query_families[row.query_family or "unknown"]["yield"] += row.opps + row.signals
        for family, stats in query_families.items():
            if stats["requests"] >= 3 and stats["yield"] == 0:
                alerts.append(
                    {
                        "type": "query_family_zero_yield",
                        "severity": "medium",
                        "detail": f"{family} is executing but producing no retained signals or opportunities.",
                    }
                )
        if len(live_signals) == 0 and len(healthy_live_sources) >= 4:
            alerts.append(
                {
                    "type": "missing_upper_funnel",
                    "severity": "medium",
                    "detail": "Healthy live sources are running, but the broader lead lanes remain empty.",
                }
            )
        return alerts[:12]

    def _latest_run_scope_kpis(self) -> dict[str, int]:
        refresh_jobs = [
            row
            for row in self.session.execute(
                select(JobRun).where(JobRun.source_id.is_not(None), JobRun.finished_at.is_not(None)).order_by(desc(JobRun.finished_at))
            ).scalars()
            if row.job_type.value == "refresh"
        ]
        if not refresh_jobs:
            return {
                "sources_touched_this_run": 0,
                "sources_succeeded_this_run": 0,
                "sources_yielding_real_records_this_run": 0,
                "sources_yielding_d365_records_this_run": 0,
            }
        latest = refresh_jobs[0]
        mode = latest.mode
        window_start = (latest.finished_at or latest.started_at) - timedelta(hours=24)
        cohort_rows = [
            row
            for row in refresh_jobs
            if (row.finished_at or row.started_at) >= window_start and (not mode or row.mode == mode)
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
        cohort = list(latest_by_source.values()) or cohort_rows
        touched = {row.source_id for row in cohort if row.source_id}
        succeeded = {
            row.source_id
            for row in cohort
            if row.source_id and row.status == CrawlStatus.SUCCEEDED and int(row.documents_fetched or 0) > 0
        }
        retained = {row.source_id for row in cohort if row.source_id and int(row.candidates_created or 0) > 0}
        return {
            "sources_touched_this_run": len(touched),
            "sources_succeeded_this_run": len(succeeded),
            "sources_yielding_real_records_this_run": len(retained),
            "sources_yielding_d365_records_this_run": len(retained),
        }

    def _source_summary(self, source: SourceRegistry) -> dict[str, Any]:
        latest_metric = self.session.execute(
            select(SourceDailyMetric)
            .where(SourceDailyMetric.source_id == source.id)
            .order_by(desc(SourceDailyMetric.metric_date))
            .limit(1)
        ).scalar_one_or_none()
        latest_canary = self.session.execute(
            select(SourceCanaryResult)
            .where(SourceCanaryResult.source_id == source.id)
            .order_by(desc(SourceCanaryResult.timestamp))
            .limit(1)
        ).scalar_one_or_none()
        issues = list(
            self.session.execute(
                select(SourceIssue).where(SourceIssue.source_id == source.id).order_by(desc(SourceIssue.last_seen_at))
            ).scalars()
        )
        open_issues = [issue for issue in issues if issue.state == "open"]
        source_capabilities = source.source_capability_json or {}
        candidate_rows = list(
            self.session.execute(
                select(OpportunityCandidate)
                .join(EvidenceRecord, EvidenceRecord.id == OpportunityCandidate.evidence_record_id)
                .where(EvidenceRecord.source_id == source.id)
                .order_by(desc(OpportunityCandidate.updated_at))
            ).scalars()
        )
        last_good_pitchable_emit = None
        for candidate in candidate_rows:
            evidence = self.session.get(EvidenceRecord, candidate.evidence_record_id)
            if is_demo_record(candidate) or is_demo_record(evidence):
                continue
            if evaluate_record(candidate, evidence=evidence).allowed:
                last_good_pitchable_emit = _iso(candidate.updated_at)
                break
        parser_implemented = bool(
            source_capabilities.get("parser_implemented")
            if "parser_implemented" in source_capabilities
            else source.parsing_mode.value in {"json", "ocds", "rss"} or bool((source.config_json or {}).get("max_detail_pages"))
        )
        production_ready_candidate = bool(source_capabilities.get("production_ready"))
        authenticity = classify_source_authenticity(
            name=source.name,
            endpoint=source.endpoint,
            source_family=source.source_family,
            public_access_mode=source.public_access_mode.value,
            data_mode="demo" if source.name.startswith("demo_") else "live",
        )
        query_count = int(
            self.session.execute(select(func.count(QueryExecution.id)).where(QueryExecution.source_id == source.id)).scalar_one() or 0
        )
        backfilled = any(
            (row.metadata_json or {}).get("mode") == "bootstrap_backfill" and row.status.value == "succeeded"
            for row in self.session.execute(select(JobRun).where(JobRun.source_id == source.id)).scalars()
        )
        incrementally_syncing = any(
            (row.metadata_json or {}).get("mode") == "incremental_sync" and row.status.value == "succeeded"
            for row in self.session.execute(select(JobRun).where(JobRun.source_id == source.id)).scalars()
        )
        return {
            "id": source.id,
            "name": source.name,
            "description": source.description,
            "region": source.region,
            "country": source.country,
            "lane": source.lane.value,
            "supported_lanes": source.supported_lanes_json or [source.lane.value],
            "acquisition_method": source.acquisition_method.value,
            "parsing_mode": source.parsing_mode.value,
            "enabled": source.enabled,
            "is_seed": source.is_seed,
            "seed_state": "seed" if source.is_seed else "discovered",
            "endpoint": source.endpoint,
            "source_family": source.source_family,
            "data_mode": "demo" if source.name.startswith("demo_") else "live",
            "health_status": source.health_status.value,
            "operational_state": self._operational_state(source, latest_metric, open_issues, latest_canary).value,
            "yield_state": self._yield_state(source, latest_metric, open_issues).value,
            "forthcoming_state": self._forthcoming_state(source).value,
            "public_access_mode": source.public_access_mode.value,
            "last_successful_fetch": _iso(source.last_successful_fetch_at),
            "last_attempted_fetch": _iso(source.last_attempted_fetch_at),
            "last_canary_status": latest_canary.status if latest_canary else None,
            "last_canary_at": _iso(latest_canary.timestamp) if latest_canary else None,
            "last_canary_issue_code": latest_canary.issue_code if latest_canary else None,
            "last_good_canary": _iso(latest_canary.timestamp) if latest_canary and latest_canary.status == "passed" else None,
            "source_trust": self._source_trust(source),
            "source_authenticity_class": source.source_authenticity_class or authenticity.authenticity_class,
            "canonical_allowed": bool(source.canonical_allowed if source.source_authenticity_class else authenticity.canonical_allowed),
            "source_discovery_confidence": float(source.source_discovery_confidence or 0.0),
            "robots_status": source.robots_status or "unknown",
            "rate_limit_policy": source.rate_limit_policy_json,
            "rate_limit_per_minute": source.rate_limit_per_minute,
            "avg_latency_ms": round(float(latest_metric.avg_latency_ms or 0.0), 2) if latest_metric else 0.0,
            "success_rate": round(float(latest_metric.success_rate or 0.0), 4) if latest_metric else 0.0,
            "rate_429": round(float(latest_metric.rate_429 or 0.0), 4) if latest_metric else 0.0,
            "rate_403": round(float(latest_metric.rate_403 or 0.0), 4) if latest_metric else 0.0,
            "timeout_rate": round(float(latest_metric.timeout_rate or 0.0), 4) if latest_metric else 0.0,
            "parser_failure_rate": round(float(latest_metric.parser_failure_rate or 0.0), 4) if latest_metric else 0.0,
            "docs_fetched_7d": self._sum_daily(source.id, "documents_fetched", days=7),
            "evidence_extracted_7d": self._sum_daily(source.id, "evidence_extracted", days=7),
            "opportunities_created_7d": self._sum_daily(source.id, "opportunities_created", days=7),
            "market_signals_created_7d": self._sum_daily(source.id, "market_signals_created", days=7),
            "english_acceptance_rate": round(float(latest_metric.english_acceptance_rate or 0.0), 4) if latest_metric else 0.0,
            "field_completeness_score": round(float(latest_metric.field_completeness_score or 0.0), 4) if latest_metric else 0.0,
            "unique_buyers_found": int(latest_metric.unique_buyers_found or 0) if latest_metric else 0,
            "issue_severity": self._top_issue_severity(open_issues),
            "dominant_issue_code": open_issues[0].issue_code if open_issues else None,
            "recommended_fix": open_issues[0].recommended_remediation if open_issues else None,
            "open_issue_count": len(open_issues),
            "query_count": query_count,
            "parser_implemented": parser_implemented,
            "production_ready": bool(
                source.enabled
                and production_ready_candidate
                and latest_canary
                and latest_canary.status == "passed"
                and self._operational_state(source, latest_metric, open_issues, latest_canary) == OperationalState.HEALTHY
            ),
            "production_ready_candidate": production_ready_candidate,
            "backfilled": backfilled,
            "incrementally_syncing": incrementally_syncing,
            "yielding_real_records": self._sum_daily(source.id, "documents_fetched", days=30) > 0,
            "yielding_d365_records": self._sum_daily(source.id, "opportunities_created", days=30) > 0 or self._sum_daily(source.id, "market_signals_created", days=30) > 0,
            "yielding_pitchable_records": last_good_pitchable_emit is not None,
            "last_good_pitchable_emit": last_good_pitchable_emit,
            "known_blind_spot_reason": source.known_blind_spot_reason,
            "content_types": source.content_types_json,
            "language_support": source.language_support_json,
            "search_capabilities": source.search_capabilities_json,
            "source_capabilities": source.source_capability_json,
            "config": source.config_json,
            "discovery_provenance": source.discovery_provenance_json,
            "legal_notes": source.legal_notes,
            "access_notes": source.access_notes,
            "health_tiny_trend": [
                {
                    "date": metric.metric_date.date().isoformat(),
                    "documents_fetched": metric.documents_fetched,
                    "opportunities_created": metric.opportunities_created,
                }
                for metric in self.session.execute(
                    select(SourceDailyMetric)
                    .where(SourceDailyMetric.source_id == source.id)
                    .order_by(desc(SourceDailyMetric.metric_date))
                    .limit(7)
                ).scalars()
            ][::-1],
        }

    def _operational_state(
        self,
        source: SourceRegistry,
        latest_metric: SourceDailyMetric | None,
        issues: list[SourceIssue],
        latest_canary: SourceCanaryResult | None = None,
    ) -> OperationalState:
        if source.public_access_mode == PublicAccessMode.UNSUPPORTED:
            return OperationalState.UNSUPPORTED
        if not source.enabled:
            return OperationalState.DISABLED
        issue_codes = {issue.issue_code for issue in issues}
        if "robots_blocked" in issue_codes:
            return OperationalState.ROBOTS_DISALLOWED
        if "throttled_429" in issue_codes:
            return OperationalState.THROTTLED
        if "blocked_401" in issue_codes or source.public_access_mode == PublicAccessMode.ACCOUNT_REQUIRED:
            return OperationalState.AUTH_REQUIRED
        if "blocked_403" in issue_codes:
            return OperationalState.BLOCKED
        if issue_codes & {"parser_error", "parser_drift"}:
            return OperationalState.PARSER_BROKEN
        if any(code and code.startswith("http_") for code in issue_codes):
            return OperationalState.DEGRADED
        if latest_canary and latest_canary.status != "passed":
            if latest_canary.issue_code == "http_401":
                return OperationalState.AUTH_REQUIRED
            if latest_canary.issue_code == "http_403":
                return OperationalState.BLOCKED
            if latest_canary.issue_code == "http_429":
                return OperationalState.THROTTLED
            if latest_canary.issue_code in {"unsupported_content_type", "parser_error", "parser_drift"}:
                return OperationalState.PARSER_BROKEN
            return OperationalState.DEGRADED
        if source.health_status == SourceHealthStatus.FAILING:
            return OperationalState.DEGRADED
        if latest_metric and latest_metric.success_rate < 0.5:
            return OperationalState.UNSTABLE
        if latest_metric and (latest_metric.rate_429 > 0.2 or latest_metric.rate_403 > 0.2):
            return OperationalState.DEGRADED
        recent_success = source.last_successful_fetch_at and source.last_successful_fetch_at >= datetime.now(UTC).replace(tzinfo=None) - timedelta(days=7)
        recent_canary = latest_canary and latest_canary.timestamp >= datetime.now(UTC).replace(tzinfo=None) - timedelta(days=7) and latest_canary.status == "passed"
        if recent_success or recent_canary:
            return OperationalState.HEALTHY
        return OperationalState.UNKNOWN

    def _yield_state(
        self,
        source: SourceRegistry,
        latest_metric: SourceDailyMetric | None,
        issues: list[SourceIssue],
    ) -> YieldState:
        if not latest_metric:
            return YieldState.UNKNOWN
        if latest_metric.documents_fetched == 0 and latest_metric.evidence_extracted == 0:
            return YieldState.ZERO_YIELD
        if any(issue.issue_code == "empty_result" for issue in issues):
            return YieldState.STALE
        if latest_metric.opportunities_created >= 5 or latest_metric.market_signals_created >= 10:
            return YieldState.HIGH_YIELD
        if latest_metric.opportunities_created == 0 and latest_metric.documents_fetched > 0:
            if latest_metric.field_completeness_score < 0.35 or latest_metric.parser_failure_rate > 0.1:
                return YieldState.NOISY
            return YieldState.LOW_YIELD
        if latest_metric.documents_fetched > 0 and latest_metric.field_completeness_score < 0.35:
            return YieldState.NOISY
        if source.last_successful_fetch_at and source.last_successful_fetch_at < datetime.now(UTC).replace(tzinfo=None) - timedelta(days=14):
            return YieldState.STALE
        return YieldState.NORMAL_YIELD

    def _forthcoming_state(self, source: SourceRegistry) -> ForthcomingState:
        if source.public_access_mode == PublicAccessMode.UNSUPPORTED:
            return ForthcomingState.UNSUPPORTED
        if not source.enabled:
            return ForthcomingState.INTENTIONALLY_DISABLED
        if source.enabled and not source.last_successful_fetch_at:
            return ForthcomingState.ENABLED_NOT_YET_SUCCESSFUL
        return ForthcomingState.ACTIVE

    def _source_trust(self, source: SourceRegistry) -> float:
        score = 0.45
        if source.is_seed:
            score += 0.1
        if source.acquisition_method.value in {"api", "ocds", "dataset", "rss"}:
            score += 0.2
        elif source.acquisition_method.value == "html":
            score += 0.05
        if source.public_access_mode == PublicAccessMode.PUBLIC:
            score += 0.1
        if source.source_family and any(token in source.source_family.lower() for token in ("official", "government", "multilateral", "procurement")):
            score += 0.1
        if source.health_status == SourceHealthStatus.FAILING:
            score -= 0.15
        return round(max(0.0, min(score, 1.0)), 2)

    def _top_issue_severity(self, issues: list[SourceIssue]) -> str | None:
        order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
        top = sorted((issue.severity.value for issue in issues), key=lambda value: order.get(value, 0), reverse=True)
        return top[0] if top else None

    def _run_row(self, run: CrawlRun) -> dict[str, Any]:
        fetch_events = list(
            self.session.execute(select(SourceFetchEvent).where(SourceFetchEvent.crawl_run_id == run.id)).scalars()
        )
        return {
            "id": run.id,
            "run_type": "crawl",
            "source_id": run.source_id,
            "job_type": "refresh",
            "started_at": _iso(run.started_at),
            "finished_at": _iso(run.finished_at),
            "duration_ms": int((run.finished_at - run.started_at).total_seconds() * 1000) if run.finished_at else None,
            "status": run.status.value,
            "documents_fetched": run.documents_fetched,
            "evidence_extracted": run.evidence_extracted,
            "candidates_created": run.candidates_created,
            "opportunities_created": run.candidates_created,
            "errors": len(run.errors_json or []),
            "retries": sum(event.retry_count for event in fetch_events),
            "bytes_fetched": sum(event.bytes for event in fetch_events),
            "cursor": run.cursor,
            "errors_json": run.errors_json,
            "fetch_events": self._fetch_events(run.id),
        }

    def _job_run_row(self, run: JobRun) -> dict[str, Any]:
        return {
            "id": run.id,
            "run_type": "job",
            "source_id": run.source_id,
            "crawl_run_id": run.crawl_run_id,
            "job_type": run.job_type.value,
            "started_at": _iso(run.started_at),
            "finished_at": _iso(run.finished_at),
            "duration_ms": run.duration_ms,
            "status": run.status.value,
            "documents_fetched": run.documents_fetched,
            "evidence_extracted": run.evidence_extracted,
            "candidates_created": run.candidates_created,
            "opportunities_created": run.opportunities_created,
            "errors": len(run.errors_json or []),
            "retries": run.retries,
            "bytes_fetched": run.bytes_fetched,
            "errors_json": run.errors_json,
            "metadata": run.metadata_json,
            "trace_id": run.trace_id,
            "request_id": run.request_id,
            "mode": run.mode,
            "source_names": run.source_names_json,
            "budget": run.budget_json,
            "query_count": run.query_count,
            "sources_attempted": run.sources_attempted,
            "sources_succeeded": run.sources_succeeded,
            "sources_failed": run.sources_failed,
            "sources_zero_yield": run.sources_zero_yield,
            "sources_untested": run.sources_untested,
            "run_reason": run.run_reason,
            "initiated_by": run.initiated_by,
            "run_kind": run.run_kind,
            "evidence_class": run.evidence_class,
            "oracle_admissible": run.oracle_admissible,
            "admissibility_fail_reasons": run.admissibility_fail_reasons_json,
            "verification_bundle_path": run.verification_bundle_path,
            "verification_bundle_sha256": run.verification_bundle_sha256,
            "diagnostic_summary": run.diagnostic_summary_json,
        }

    def _issue_row(self, issue: SourceIssue) -> dict[str, Any]:
        source = self.session.get(SourceRegistry, issue.source_id) if issue.source_id else None
        return {
            "id": issue.id,
            "source_id": issue.source_id,
            "source_name": source.name if source else None,
            "crawl_run_id": issue.crawl_run_id,
            "issue_code": issue.issue_code,
            "severity": issue.severity.value,
            "state": issue.state,
            "first_seen_at": _iso(issue.first_seen_at),
            "last_seen_at": _iso(issue.last_seen_at),
            "frequency": issue.frequency,
            "example_url": issue.example_url,
            "example_status_code": issue.example_status_code,
            "error_class": issue.error_class,
            "error_message": issue.error_message,
            "impact_on_yield": issue.impact_on_yield,
            "recommended_remediation": issue.recommended_remediation,
            "owner": issue.owner,
            "note": issue.note,
            "metadata": issue.metadata_json,
        }

    def _evidence_row(self, row: EvidenceRecord) -> dict[str, Any]:
        raw_document = self.session.get(RawDocument, row.raw_document_id)
        return {
            "id": row.id,
            "data_mode": "demo" if self._is_demo_record(row) else "live",
            "raw_document_id": row.raw_document_id,
            "title": row.title,
            "summary": row.summary,
            "buyer": row.buyer_name,
            "buyer_country": row.buyer_country,
            "buyer_region": row.buyer_region,
            "notice_type": row.notice_type,
            "procurement_type": row.procurement_type,
            "publication_date": _iso(row.publication_date),
            "close_date": _iso(row.close_date),
            "budget_value": float(row.budget_value) if row.budget_value is not None else None,
            "budget_currency": row.budget_currency,
            "source_url": row.source_url,
            "response_url": row.response_url,
            "contact_name": row.contact_name,
            "contact_email": row.contact_email,
            "contact_phone": row.contact_phone,
            "cpv_codes": row.cpv_codes_json,
            "attachment_urls": row.attachment_urls_json,
            "attachment_metadata": row.attachment_metadata_json,
            "lot_titles": row.lot_titles_json,
            "product_mentions": row.product_mentions_json,
            "service_mentions": row.service_mentions_json,
            "classification_codes": row.classification_codes_json,
            "procurement_id": row.procurement_id,
            "raw_excerpt": row.raw_excerpt,
            "language_status": row.language_status,
            "english_evidence_source": row.english_evidence_source,
            "current_actionability_state": row.current_actionability_state.value if row.current_actionability_state else None,
            "english_sufficiency_score": row.english_sufficiency_score,
            "english_shell_only_flag": row.english_shell_only_flag,
            "seller_readable_summary_en": row.seller_readable_summary_en,
            "seller_readable_title_en_flag": row.seller_readable_title_en_flag,
            "retrieval_score": row.retrieval_score,
            "formal_opportunity_score": row.formal_opportunity_score,
            "pre_position_score": row.pre_position_score,
            "account_intent_score": row.account_intent_score,
            "install_base_trigger_score": row.install_base_trigger_score,
            "service_fit_score": row.service_fit_score,
            "buyer_quality_score": row.buyer_quality_score,
            "corroboration_score": row.corroboration_score,
            "source_trust": row.source_trust,
            "matched_positive_terms": row.matched_positive_terms_json,
            "matched_negative_terms": row.matched_negative_terms_json,
            "discovery_query_id": row.discovery_query_id,
            "discovery_query_text": row.discovery_query_text,
            "query_family": row.query_family,
            "source_discovery_confidence": row.source_discovery_confidence,
            "signal_lane": row.signal_lane.value if row.signal_lane else None,
            "recommended_action": row.recommended_action.value if row.recommended_action else None,
            "route_to_market": row.route_to_market.value if row.route_to_market else None,
            "account_heat_score": row.account_heat_score,
            "installed_product_guess": row.installed_product_guess,
            "installed_product_evidence": row.installed_product_evidence,
            "trigger_type": row.trigger_type,
            "trigger_strength": row.trigger_strength,
            "procurement_cycle_stage": row.procurement_cycle_stage,
            "vehicle_type": row.vehicle_type,
            "incumbent_vendor": row.incumbent_vendor,
            "incumbent_expiry_guess": row.incumbent_expiry_guess,
            "buyer_intent_evidence_json": row.buyer_intent_evidence_json,
            "legacy_evidence_json": row.legacy_evidence_json,
            "portal_fingerprint": row.portal_fingerprint,
            "public_access_mode": row.public_access_mode.value,
            "known_blind_spot_reason": row.known_blind_spot_reason,
            "exclusion_reason": row.exclusion_reason,
            "raw_document_url": raw_document.document_url if raw_document else None,
            "blob_path": raw_document.blob_path if raw_document else None,
            "raw_document_metadata": raw_document.metadata_json if raw_document else {},
        }

    def _opportunity_row(self, row: OpportunityCandidate) -> dict[str, Any]:
        evidence = self.session.get(EvidenceRecord, row.evidence_record_id)
        cluster = self.session.get(OpportunityCluster, row.cluster_id) if row.cluster_id else None
        organization = self.session.get(Organization, row.organization_id) if row.organization_id else None
        source = self.session.get(SourceRegistry, evidence.source_id) if evidence and evidence.source_id else None
        buyer = evidence.buyer_name if evidence else organization.source_name if organization else None
        payload = {
            "id": row.id,
            "data_mode": "demo" if self._is_demo_record(row) else "live",
            "title": row.title,
            "summary": row.summary,
            "buyer": buyer,
            "buyer_country": evidence.buyer_country if evidence else row.country,
            "country": row.country,
            "signal_lane": row.signal_lane.value,
            "recommended_action": row.recommended_action.value,
            "route_to_market": row.route_to_market.value,
            "app_family": row.app_family,
            "workload": row.business_process,
            "business_process": row.business_process,
            "service_line": row.service_type,
            "service_type": row.service_type,
            "source_cluster": cluster.canonical_title if cluster else None,
            "source_count": cluster.corroboration_count if cluster else row.corroboration_count,
            "top_source": evidence.source_url if evidence else row.source_url,
            "source_name": source.name if source else None,
            "discovery_method": evidence.acquisition_method if evidence else None,
            "query_family": row.query_family,
            "retrieval_score": row.retrieval_score,
            "opportunity_score": row.opportunity_score,
            "formal_opportunity_score": row.formal_opportunity_score,
            "pre_position_score": row.pre_position_score,
            "account_intent_score": row.account_intent_score,
            "install_base_trigger_score": row.install_base_trigger_score,
            "service_fit_score": row.service_fit_score,
            "buyer_quality_score": row.buyer_quality_score,
            "corroboration_count": row.corroboration_count,
            "evidence_grade": row.evidence_grade,
            "close_date": _iso(row.close_date),
            "publication_date": _iso(row.publication_date),
            "budget": float(row.budget_value) if row.budget_value is not None else None,
            "budget_currency": row.budget_currency,
            "created_at": _iso(row.created_at),
            "updated_at": _iso(row.updated_at),
            "status": row.status.value,
            "retrieval_explanation": {
                "matched_positive_terms": row.matched_positive_terms_json,
                "matched_negative_terms": row.matched_negative_terms_json,
                "source_trust": row.source_trust,
                "language_status": row.language_status,
                "english_evidence_source": row.english_evidence_source,
            },
            "scoring_explanation": row.score_breakdown_json,
            "source_url": row.source_url,
            "response_url": row.response_url,
            "procurement_id": row.procurement_id,
            "raw_excerpt": row.raw_excerpt,
            "source_trust": row.source_trust,
            "matched_positive_terms": row.matched_positive_terms_json,
            "matched_negative_terms": row.matched_negative_terms_json,
            "language_status": row.language_status,
            "english_evidence_source": row.english_evidence_source,
            "current_actionability_state": row.current_actionability_state.value if row.current_actionability_state else None,
            "english_sufficiency_score": row.english_sufficiency_score,
            "english_shell_only_flag": row.english_shell_only_flag,
            "seller_readable_summary_en": row.seller_readable_summary_en,
            "seller_readable_title_en_flag": row.seller_readable_title_en_flag,
            "sales_handoff_state": row.sales_handoff_state,
            "discovery_query_id": row.discovery_query_id,
            "discovery_query_text": row.discovery_query_text,
            "source_discovery_confidence": row.source_discovery_confidence,
            "public_access_mode": row.public_access_mode.value,
            "account_id": row.account_cluster_id,
            "account_heat_score": row.account_heat_score,
            "installed_product_guess": row.installed_product_guess,
            "installed_product_evidence": row.installed_product_evidence,
            "trigger_type": row.trigger_type,
            "trigger_strength": row.trigger_strength,
            "procurement_cycle_stage": row.procurement_cycle_stage,
            "vehicle_type": row.vehicle_type,
            "incumbent_vendor": row.incumbent_vendor,
            "incumbent_expiry_guess": row.incumbent_expiry_guess,
            "buyer_intent_evidence_json": row.buyer_intent_evidence_json,
            "legacy_evidence_json": row.legacy_evidence_json,
            "portal_fingerprint": row.portal_fingerprint,
            "known_blind_spot_reason": row.known_blind_spot_reason,
            "exclusion_reason": row.exclusion_reason,
            "next_action": row.next_action,
            "pursuit_recommendation": row.pursuit_recommendation,
            "tags": row.tags_json,
        }
        evaluation = evaluate_record(row, evidence=evidence)
        apply_evaluation_to_row(payload, evaluation)
        self._apply_authenticity_to_row(payload, source_id=evidence.source_id if evidence else None)
        return payload

    def _canonical_metric_snapshot(
        self,
        opportunity_rows: list[OpportunityCandidate],
        *,
        as_of: datetime,
    ) -> tuple[dict[str, int], list[dict[str, Any]]]:
        seen_keys: set[str] = set()
        evaluated_rows: list[dict[str, Any]] = []
        yielding_seller_ready_sources: set[str] = set()
        metrics = {
            "successful_fetches": int(self.session.execute(select(func.count(SourceFetchEvent.id)).where(SourceFetchEvent.success_flag.is_(True))).scalar_one() or 0),
            "fetched_documents": int(self.session.execute(select(func.count(RawDocument.id))).scalar_one() or 0),
            "fetched_detail_pages": int(self.session.execute(select(func.count(SourceFetchEvent.id)).where(SourceFetchEvent.list_or_detail == "detail", SourceFetchEvent.success_flag.is_(True))).scalar_one() or 0),
            "fetched_attachments": int(self.session.execute(select(func.count(SourceFetchEvent.id)).where(SourceFetchEvent.stage == "attachment", SourceFetchEvent.success_flag.is_(True))).scalar_one() or 0),
            "evidence_rows": int(self.session.execute(select(func.count(EvidenceRecord.id))).scalar_one() or 0),
            "parsed_documents": int(self.session.execute(select(func.count(EvidenceRecord.id))).scalar_one() or 0),
            "classified_documents": len(opportunity_rows),
            "retained_d365_records": 0,
            "duplicates_removed": 0,
            "retained_without_anchor_total": 0,
            "english_insufficient_total": 0,
            "stale_or_awarded_total": 0,
            "monitor_only_total": 0,
            "current_actionable_total": 0,
            "current_bid_now_total": 0,
            "current_pre_position_total": 0,
            "award_watch_total": 0,
            "renewal_watch_total": 0,
            "seller_ready_total": 0,
            "seller_ready_bid_now_total": 0,
            "seller_ready_pre_position_total": 0,
            "research_ready_total": 0,
            "monitor_total": 0,
            "reject_total": 0,
            "sources_yielding_seller_ready_records": 0,
        }
        for candidate in opportunity_rows:
            evidence = self.session.get(EvidenceRecord, candidate.evidence_record_id)
            if self._is_demo_record(candidate) or self._is_demo_record(evidence):
                continue
            row = self._opportunity_row(candidate)
            evaluation = evaluate_record(candidate, evidence=evidence, seen_keys=seen_keys, today=as_of)
            apply_evaluation_to_row(row, evaluation)
            self._apply_authenticity_to_row(row, source_id=evidence.source_id if evidence else None)
            evaluated_rows.append(row)
            if row.get("anchor_terms"):
                metrics["retained_d365_records"] += 1
            else:
                metrics["retained_without_anchor_total"] += 1
            if "duplicate" in (row.get("pitchability_reasons") or []):
                metrics["duplicates_removed"] += 1
            if "english_insufficient" in (row.get("pitchability_reasons") or []) or "english_shell_only" in (row.get("pitchability_reasons") or []):
                metrics["english_insufficient_total"] += 1
            if row.get("current_actionability_state") in {"award_notice", "awarded", "contract_details_only", "closed_submission", "expired", "cancelled"}:
                metrics["stale_or_awarded_total"] += 1
            if is_canonical_authentic_row(row) and row.get("recommended_action") in {"bid_now", "pre_position"} and row.get("current_actionability_state") in {"open_bid", "open_consultation", "pre_market_engagement", "planned_procurement", "framework_or_vehicle"}:
                metrics["current_actionable_total"] += 1
                if row.get("recommended_action") == "bid_now":
                    metrics["current_bid_now_total"] += 1
                elif row.get("recommended_action") == "pre_position":
                    metrics["current_pre_position_total"] += 1
            if row.get("recommended_action") == "award_watch":
                metrics["award_watch_total"] += 1
            if row.get("recommended_action") == "renewal_watch":
                metrics["renewal_watch_total"] += 1
            if row.get("sales_handoff_state") == "seller_ready":
                metrics["seller_ready_total"] += 1
                if evidence and evidence.source_id:
                    source = self.session.get(SourceRegistry, evidence.source_id)
                    if source:
                        yielding_seller_ready_sources.add(source.name)
                if row.get("recommended_action") == "bid_now":
                    metrics["seller_ready_bid_now_total"] += 1
                elif row.get("recommended_action") == "pre_position":
                    metrics["seller_ready_pre_position_total"] += 1
            elif row.get("sales_handoff_state") == "research_ready":
                metrics["research_ready_total"] += 1
            elif row.get("sales_handoff_state") == "monitor_only":
                metrics["monitor_total"] += 1
                metrics["monitor_only_total"] += 1
            else:
                metrics["reject_total"] += 1
        metrics["sources_yielding_seller_ready_records"] = len(yielding_seller_ready_sources)
        return metrics, evaluated_rows

    def _apply_authenticity_to_row(self, row: dict[str, Any], *, source_id: str | None = None) -> dict[str, Any]:
        source = self.session.get(SourceRegistry, source_id) if source_id else None
        authenticity = classify_row_authenticity(
            source_name=(source.name if source else None),
            source_url=row.get("source_url") or row.get("top_source"),
            endpoint=(source.endpoint if source else row.get("top_source")),
            source_family=(source.source_family if source else None),
            public_access_mode=(source.public_access_mode.value if source else row.get("public_access_mode")),
            data_mode=row.get("data_mode"),
        )
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
            row["seller_handoff_rationale"] = "Source is not an official public procurement surface; retain for research or monitoring only."
            if authenticity.authenticity_class in {"synthetic_fixture", "demo_seed"}:
                row["sales_handoff_state"] = "reject"
                row["recommended_action"] = "reject"
            else:
                row["sales_handoff_state"] = "research_ready"
            row["pursuit_recommendation"] = row["sales_handoff_state"]
        return row

    def _signal_row(self, row: MarketSignal) -> dict[str, Any]:
        evidence = self.session.get(EvidenceRecord, row.evidence_record_id)
        organization = self.session.get(Organization, row.organization_id) if row.organization_id else None
        return {
            "id": row.id,
            "data_mode": "demo" if self._is_demo_record(row) else "live",
            "title": row.title,
            "summary": row.summary,
            "buyer": evidence.buyer_name if evidence else organization.source_name if organization else None,
            "country": row.country,
            "region": row.region,
            "signal_lane": row.signal_lane.value,
            "recommended_action": row.recommended_action.value,
            "route_to_market": row.route_to_market.value,
            "signal_type": row.signal_type,
            "confidence": row.confidence,
            "retrieval_score": row.retrieval_score,
            "source_trust": row.source_trust,
            "account_heat_score": row.account_heat_score,
            "trigger_type": row.trigger_type,
            "trigger_strength": row.trigger_strength,
            "public_access_mode": row.public_access_mode.value,
            "english_evidence_source": row.english_evidence_source,
            "query_family": row.query_family,
            "discovery_query_id": row.discovery_query_id,
            "discovery_query_text": row.discovery_query_text,
            "portal_fingerprint": row.portal_fingerprint,
            "known_blind_spot_reason": row.known_blind_spot_reason,
            "corroboration_count": row.corroboration_count,
            "source_url": row.source_url,
            "raw_excerpt": row.raw_excerpt,
            "created_at": _iso(row.created_at),
            "buyer_intent_evidence_json": row.buyer_intent_evidence_json,
            "legacy_evidence_json": row.legacy_evidence_json,
            "tags": row.tags_json,
        }

    def _account_row(self, row: AccountCluster) -> dict[str, Any]:
        contacts = [
            self._contact_row(contact)
            for contact in self.session.execute(
                select(Contact)
                .join(Organization, Organization.id == Contact.organization_id)
                .where(
                    (Organization.website_domain == row.website_domain)
                    | (func.lower(Organization.normalized_name) == func.lower(row.canonical_name))
                )
            ).scalars()
        ]
        opportunity_count = int(
            self.session.execute(
                select(func.count(OpportunityCandidate.id)).where(OpportunityCandidate.account_cluster_id == row.id)
            ).scalar_one()
            or 0
        )
        signal_count = int(
            self.session.execute(select(func.count(MarketSignal.id)).where(MarketSignal.account_cluster_id == row.id)).scalar_one()
            or 0
        )
        return {
            "id": row.id,
            "canonical_name": row.canonical_name,
            "website_domain": row.website_domain,
            "country": row.country,
            "first_seen_at": _iso(row.first_seen_at),
            "latest_seen_at": _iso(row.latest_seen_at),
            "heat_score": row.heat_score,
            "buyer_quality_score": row.buyer_quality_score,
            "installed_product_guess": row.installed_product_guess,
            "installed_product_evidence": row.installed_product_evidence,
            "trigger_strength": row.trigger_strength,
            "corroboration_count": row.corroboration_count,
            "opportunity_count": opportunity_count,
            "signal_count": signal_count,
            "contacts": contacts,
        }

    def _contact_row(self, row: Contact) -> dict[str, Any]:
        return {
            "id": row.id,
            "organization_id": row.organization_id,
            "full_name": row.full_name,
            "email": row.email,
            "phone": row.phone,
            "role": row.role,
            "public_source_url": row.public_source_url,
            "enrichment_confidence": row.enrichment_confidence,
            "created_at": _iso(row.created_at),
        }

    def _candidate_source_row(self, row: SourceDiscoveryCandidate) -> dict[str, Any]:
        if row.discovery_status == DiscoveryStatus.PENDING_REVIEW:
            forthcoming = ForthcomingState.DISCOVERED_PENDING_REVIEW
        elif row.discovery_status == DiscoveryStatus.ENABLED:
            forthcoming = ForthcomingState.APPROVED_PENDING_ENABLE
        elif row.public_access_mode == PublicAccessMode.UNSUPPORTED:
            forthcoming = ForthcomingState.UNSUPPORTED
        else:
            forthcoming = ForthcomingState.ACTIVE
        return {
            "id": row.id,
            "candidate_name": row.candidate_name,
            "endpoint": row.endpoint,
            "region": row.region,
            "country": row.country,
            "acquisition_method": row.acquisition_method.value,
            "parsing_mode": row.parsing_mode.value,
            "confidence": row.confidence,
            "robots_status": row.robots_status or "unknown",
            "auto_enable_eligible": row.auto_enable_eligible,
            "upstream_source_id": row.upstream_source_id,
            "source_family": row.source_family,
            "discovery_mode": row.discovery_mode,
            "portal_fingerprint": row.portal_fingerprint,
            "public_access_mode": row.public_access_mode.value,
            "language_support": row.language_support_json,
            "content_types": row.content_types_json,
            "review_status": row.discovery_status.value,
            "recommendation": "enable" if row.auto_enable_eligible else "review",
            "notes": row.access_notes or row.known_blind_spot_reason,
            "discovery_provenance": row.provenance_json,
            "discovered_from": row.provenance_json.get("referrer") if row.provenance_json else None,
            "source_discovery_confidence": row.confidence,
            "forthcoming_state": forthcoming.value,
            "last_seen_at": _iso(row.last_seen_at),
            "created_at": _iso(row.created_at),
        }

    def _query_row(self, row: QueryExecution) -> dict[str, Any]:
        return {
            "id": row.id,
            "source_id": row.source_id,
            "crawl_run_id": row.crawl_run_id,
            "query_id": row.query_id,
            "query_text": row.query_text,
            "abstract_query_text": row.abstract_query_text,
            "rendered_query_text": row.rendered_query_text,
            "renderer": row.renderer,
            "query_family": row.query_family,
            "phase": row.phase,
            "target_field": row.target_field,
            "negatives_applied": row.negatives_applied_json,
            "was_executed": row.was_executed,
            "skip_reason": row.skip_reason,
            "watermark_in": row.watermark_in,
            "watermark_out": row.watermark_out,
            "cursor_count": row.cursor_count,
            "duplicate_fetches_avoided": row.duplicate_fetches_avoided,
            "browse_only_pass": row.browse_only_pass,
            "status": row.status,
            "trace_id": row.trace_id,
            "requests": row.requests,
            "hits": row.hits,
            "docs": row.docs,
            "evidence": row.evidence,
            "opps": row.opps,
            "signals": row.signals,
            "yield_ratio": round((row.opps + row.signals) / max(row.docs, 1), 4),
            "metadata": row.metadata_json,
        }

    def _saved_view_row(self, row: UiSavedView) -> dict[str, Any]:
        return {
            "id": row.id,
            "name": row.name,
            "route": row.route,
            "description": row.description,
            "filters_json": row.filters_json,
            "columns_json": row.columns_json,
            "density": row.density,
            "created_at": _iso(row.created_at),
            "updated_at": _iso(row.updated_at),
        }

    def _fetch_events(self, crawl_run_id: str) -> list[dict[str, Any]]:
        return [
            {
                "id": row.id,
                "timestamp": _iso(row.timestamp),
                "request_url": row.request_url,
                "request_method": row.request_method,
                "response_status_code": row.response_status_code,
                "latency_ms": row.latency_ms,
                "bytes": row.bytes,
                "bytes_received": row.bytes_received,
                "bytes_stored": row.bytes_stored,
                "content_type": row.content_type,
                "was_retry": row.was_retry,
                "retry_count": row.retry_count,
                "robots_status": row.robots_status,
                "parser_used": row.parser_used,
                "trace_id": row.trace_id,
                "span_id": row.span_id,
                "request_id": row.request_id,
                "query_id": row.query_id,
                "query_family": row.query_family,
                "page_index": row.page_index,
                "cursor_in": row.cursor_in,
                "cursor_out": row.cursor_out,
                "parent_url": row.parent_url,
                "detail_url": row.detail_url,
                "adapter_name": row.adapter_name,
                "adapter_version": row.adapter_version,
                "stage": row.stage,
                "list_or_detail": row.list_or_detail,
                "attempt_number": row.attempt_number,
                "backoff_ms": row.backoff_ms,
                "network_error_stage": row.network_error_stage,
                "http_protocol": row.http_protocol,
                "tls_error_flag": row.tls_error_flag,
                "dns_error_flag": row.dns_error_flag,
                "transport_error_flag": row.transport_error_flag,
                "success_flag": row.success_flag,
                "issue_code": row.issue_code,
                "error_class": row.error_class,
                "error_message": row.error_message,
                "english_detected": row.english_detected,
                "documents_emitted": row.documents_emitted,
                "evidence_emitted": row.evidence_emitted,
                "request_headers": row.request_headers_redacted_json,
                "response_headers": row.response_headers_redacted_json,
                "rate_limit_headers": row.rate_limit_headers_json,
                "response_body_sha256": row.response_body_sha256,
                "response_blob_path": row.response_blob_path,
                "metadata": row.metadata_json,
            }
            for row in self.session.execute(
                select(SourceFetchEvent).where(SourceFetchEvent.crawl_run_id == crawl_run_id).order_by(SourceFetchEvent.timestamp)
            ).scalars()
        ]

    def _sum_daily(self, source_id: str, field_name: str, *, days: int) -> int:
        cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)
        rows = self.session.execute(
            select(SourceDailyMetric).where(
                SourceDailyMetric.source_id == source_id,
                SourceDailyMetric.metric_date >= cutoff,
            )
        ).scalars()
        return int(sum(int(getattr(row, field_name) or 0) for row in rows))

    def _sum_metric(self, field_name: str, *, days: int) -> int:
        cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)
        rows = self.session.execute(select(SourceDailyMetric).where(SourceDailyMetric.metric_date >= cutoff)).scalars()
        return int(sum(int(getattr(row, field_name) or 0) for row in rows))

    def _records_by_day(self, *, days: int = 14) -> list[dict[str, Any]]:
        cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)
        rows = list(
            self.session.execute(select(SourceDailyMetric).where(SourceDailyMetric.metric_date >= cutoff)).scalars()
        )
        grouped: dict[str, dict[str, int]] = defaultdict(lambda: {"documents": 0, "evidence": 0, "signals": 0, "opportunities": 0})
        for row in rows:
            day = row.metric_date.date().isoformat()
            grouped[day]["documents"] += row.documents_fetched
            grouped[day]["evidence"] += row.evidence_extracted
            grouped[day]["signals"] += row.market_signals_created
            grouped[day]["opportunities"] += row.opportunities_created
        return [{"date": day, **values} for day, values in sorted(grouped.items())]

    def _source_health_trend(self, *, days: int = 14) -> list[dict[str, Any]]:
        cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)
        rows = list(
            self.session.execute(select(SourceDailyMetric).where(SourceDailyMetric.metric_date >= cutoff)).scalars()
        )
        grouped: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for row in rows:
            day = row.metric_date.date().isoformat()
            grouped[day][row.operational_state.value] += 1
        return [{"date": day, "states": dict(states)} for day, states in sorted(grouped.items())]

    def _coverage_gaps(self, sources: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        gaps: list[dict[str, Any]] = []
        covered_countries = {source["country"] for source in sources if source.get("country")}
        interesting_countries = {"US", "UK", "AU", "NZ", "CA", "IE", "SG", "ZA", "IN", "KE", "JM", "PH"}
        for country in sorted(interesting_countries - covered_countries):
            gaps.append({"type": "country_gap", "country": country, "detail": "No active source registered for this country."})
        for source in sources:
            if source["enabled"] and source["yield_state"] in {"zero_yield", "low_yield", "noisy"}:
                gaps.append(
                    {
                        "type": "source_yield_gap",
                        "source_id": source["id"],
                        "source_name": source["name"],
                        "detail": f"Enabled source is currently {source['yield_state']}.",
                    }
                )
        for candidate in candidates:
            if candidate["review_status"] == "pending_review":
                gaps.append(
                    {
                        "type": "candidate_review_gap",
                        "candidate_id": candidate["id"],
                        "source_name": candidate["candidate_name"],
                        "detail": "Discovered source is pending analyst review.",
                    }
                )
        return gaps[:20]

    def _export_row_counts(self, directory: Path) -> dict[str, int]:
        counts: dict[str, int] = {}
        for path in directory.iterdir():
            if path.suffix not in {".csv", ".jsonl"}:
                continue
            line_count = max(sum(1 for _ in path.open("r", encoding="utf-8")) - (1 if path.suffix == ".csv" else 0), 0)
            counts[path.name] = line_count
        return counts

    def _schema_fields(self) -> set[str]:
        return {
            *(column.name for column in OpportunityCandidate.__table__.columns),
            *(column.name for column in MarketSignal.__table__.columns),
            *(column.name for column in EvidenceRecord.__table__.columns),
        }

    def _count(self, model: type[Any], condition: Any | None = None) -> int:
        statement = select(func.count()).select_from(model)
        if condition is not None:
            statement = statement.where(condition)
        return int(self.session.execute(statement).scalar_one() or 0)

    def _ratio(self, numerator: int, denominator: int) -> float:
        return round(numerator / max(denominator, 1), 4)
