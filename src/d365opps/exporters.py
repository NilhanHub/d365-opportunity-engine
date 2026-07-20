from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Select, desc, select
from sqlalchemy.orm import Session

from d365opps.authenticity import classify_row_authenticity
from d365opps.config import get_settings
from d365opps.models import (
    AccountCluster,
    Contact,
    CurrentActionabilityState,
    EvidenceRecord,
    ExclusionAudit,
    MarketSignal,
    OpportunityCandidate,
    Organization,
    RadarLane,
    SignalCluster,
    SourceRegistry,
)
from d365opps.pitchability import apply_evaluation_to_row, evaluate_record, is_demo_record


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


@dataclass(slots=True)
class ExportResult:
    directory: Path
    files: list[Path]


class DatasetExporter:
    def __init__(self, export_root: Path | None = None) -> None:
        self.export_root = export_root or get_settings().export_root

    def export_all(self, session: Session, *, fmt: str = "both", filters: dict[str, Any] | None = None) -> ExportResult:
        stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        directory = self.export_root / stamp
        directory.mkdir(parents=True, exist_ok=True)
        filters = filters or {}
        files: list[Path] = []
        files.extend(self._export_query(session, select(OpportunityCandidate), "opportunity_export", directory, fmt, filters))
        files.extend(
            self._export_query(
                session,
                select(OpportunityCandidate).where(OpportunityCandidate.signal_lane == RadarLane.FORMAL_PROCUREMENT),
                "formal_procurement_export",
                directory,
                fmt,
                filters,
            )
        )
        files.extend(
            self._export_query(
                session,
                select(OpportunityCandidate).where(OpportunityCandidate.signal_lane == RadarLane.PRE_POSITIONING),
                "pre_positioning_export",
                directory,
                fmt,
                filters,
            )
        )
        files.extend(
            self._export_query(
                session,
                select(OpportunityCandidate).where(OpportunityCandidate.signal_lane == RadarLane.DIRECT_OUTREACH),
                "direct_outreach_export",
                directory,
                fmt,
                filters,
            )
        )
        files.extend(
            self._export_query(
                session,
                select(OpportunityCandidate).where(OpportunityCandidate.signal_lane == RadarLane.INSTALL_BASE_TRIGGER),
                "install_base_trigger_export",
                directory,
                fmt,
                filters,
            )
        )
        files.extend(self._export_query(session, select(Organization), "organization_export", directory, fmt, {}))
        files.extend(self._export_query(session, select(AccountCluster), "account_cluster_export", directory, fmt, {}))
        files.extend(self._export_query(session, select(Contact), "contact_export", directory, fmt, {}))
        files.extend(self._export_query(session, select(MarketSignal), "market_signal_export", directory, fmt, filters))
        files.extend(self._export_query(session, select(SignalCluster), "signal_cluster_export", directory, fmt, {}))
        files.extend(self._export_pitchability_views(session, directory, fmt))
        dashboard = directory / "dashboard_snapshot.json"
        dashboard.write_text(json.dumps(self._dashboard_snapshot(session), default=_json_default, indent=2), encoding="utf-8")
        files.append(dashboard)
        return ExportResult(directory=directory, files=files)

    def _export_query(
        self,
        session: Session,
        statement: Select,
        base_name: str,
        directory: Path,
        fmt: str,
        filters: dict[str, Any],
    ) -> list[Path]:
        statement = self._apply_filters(statement, filters)
        rows = [row[0] for row in session.execute(statement).all()]
        if not rows:
            return []
        payload = [self._row_to_dict(row) for row in rows]
        files: list[Path] = []
        if fmt in {"csv", "both"}:
            target = directory / f"{base_name}.csv"
            with target.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=sorted(payload[0].keys()))
                writer.writeheader()
                writer.writerows(payload)
            files.append(target)
        if fmt in {"jsonl", "both"}:
            target = directory / f"{base_name}.jsonl"
            with target.open("w", encoding="utf-8") as handle:
                for row in payload:
                    handle.write(json.dumps(row, default=_json_default) + "\n")
            files.append(target)
        return files

    def _row_to_dict(self, row: Any) -> dict[str, Any]:
        data: dict[str, Any] = {}
        for key, value in vars(row).items():
            if key.startswith("_"):
                continue
            data[key] = value
        return data

    def _apply_filters(self, statement: Select, filters: dict[str, Any]) -> Select:
        if "country" in filters and hasattr(statement.column_descriptions[0]["entity"], "country"):
            entity = statement.column_descriptions[0]["entity"]
            statement = statement.where(entity.country == filters["country"])
        if "evidence_grade" in filters and hasattr(statement.column_descriptions[0]["entity"], "evidence_grade"):
            entity = statement.column_descriptions[0]["entity"]
            statement = statement.where(entity.evidence_grade == filters["evidence_grade"])
        if "app_family" in filters and hasattr(statement.column_descriptions[0]["entity"], "app_family"):
            entity = statement.column_descriptions[0]["entity"]
            statement = statement.where(entity.app_family == filters["app_family"])
        if "service_type" in filters and hasattr(statement.column_descriptions[0]["entity"], "service_type"):
            entity = statement.column_descriptions[0]["entity"]
            statement = statement.where(entity.service_type == filters["service_type"])
        if "signal_lane" in filters and hasattr(statement.column_descriptions[0]["entity"], "signal_lane"):
            entity = statement.column_descriptions[0]["entity"]
            statement = statement.where(entity.signal_lane == filters["signal_lane"])
        if "recommended_action" in filters and hasattr(statement.column_descriptions[0]["entity"], "recommended_action"):
            entity = statement.column_descriptions[0]["entity"]
            statement = statement.where(entity.recommended_action == filters["recommended_action"])
        if "route_to_market" in filters and hasattr(statement.column_descriptions[0]["entity"], "route_to_market"):
            entity = statement.column_descriptions[0]["entity"]
            statement = statement.where(entity.route_to_market == filters["route_to_market"])
        return statement

    def _export_pitchability_views(self, session: Session, directory: Path, fmt: str) -> list[Path]:
        as_of_utc = datetime.now(UTC)
        pitchable_rows: list[dict[str, Any]] = []
        seller_ready_rows: list[dict[str, Any]] = []
        seller_ready_bid_now_rows: list[dict[str, Any]] = []
        seller_ready_pre_position_rows: list[dict[str, Any]] = []
        research_ready_rows: list[dict[str, Any]] = []
        non_pitchable_rows: list[dict[str, Any]] = []
        current_bid_now_rows: list[dict[str, Any]] = []
        current_pre_position_rows: list[dict[str, Any]] = []
        award_watch_rows: list[dict[str, Any]] = []
        renewal_watch_rows: list[dict[str, Any]] = []
        monitor_only_rows: list[dict[str, Any]] = []
        stale_or_awarded_rows: list[dict[str, Any]] = []
        english_insufficient_rows: list[dict[str, Any]] = []
        exclusion_reason_rows: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        for candidate in session.execute(select(OpportunityCandidate).order_by(desc(OpportunityCandidate.updated_at))).scalars():
            evidence = session.get(EvidenceRecord, candidate.evidence_record_id)
            if is_demo_record(candidate) or is_demo_record(evidence):
                continue
            evaluation = evaluate_record(candidate, evidence=evidence, seen_keys=seen_keys, today=as_of_utc)
            source = session.get(SourceRegistry, evidence.source_id) if evidence and evidence.source_id else None
            row = self._row_to_dict(candidate)
            row["buyer_name"] = evidence.buyer_name if evidence else None
            row["source_url"] = evidence.source_url if evidence else row.get("source_url")
            row["source_name"] = source.name if source else row.get("source_name")
            row["source_family"] = source.source_family if source else row.get("source_family")
            row["public_access_mode"] = (
                source.public_access_mode.value
                if source and getattr(source.public_access_mode, "value", None)
                else row.get("public_access_mode")
            )
            apply_evaluation_to_row(row, evaluation)
            self._apply_authenticity_gate(row, source=source)
            row["as_of_utc"] = as_of_utc.isoformat()
            if evaluation.sales_handoff_state == "seller_ready":
                pass
            effective_handoff = row.get("sales_handoff_state")
            effective_action = row.get("recommended_action")
            if effective_handoff == "seller_ready":
                seller_ready_rows.append(row)
                pitchable_rows.append(row)
                if effective_action == "bid_now":
                    seller_ready_bid_now_rows.append(row)
                    current_bid_now_rows.append(row)
                elif effective_action == "pre_position":
                    seller_ready_pre_position_rows.append(row)
                    current_pre_position_rows.append(row)
            elif effective_handoff == "research_ready":
                research_ready_rows.append(row)
                non_pitchable_rows.append(row)
            else:
                non_pitchable_rows.append(row)
            if effective_handoff != "seller_ready":
                if effective_action == "award_watch":
                    award_watch_rows.append(row)
                elif effective_action == "renewal_watch":
                    renewal_watch_rows.append(row)
                elif effective_action == "monitor":
                    monitor_only_rows.append(row)
                if evaluation.current_actionability_state in {
                    CurrentActionabilityState.AWARD_NOTICE.value,
                    CurrentActionabilityState.AWARDED.value,
                    CurrentActionabilityState.CONTRACT_DETAILS_ONLY.value,
                    CurrentActionabilityState.CLOSED_SUBMISSION.value,
                    CurrentActionabilityState.EXPIRED.value,
                    CurrentActionabilityState.CANCELLED.value,
                }:
                    stale_or_awarded_rows.append(row)
                if "english_insufficient" in evaluation.reasons or "english_shell_only" in evaluation.reasons:
                    english_insufficient_rows.append(row)
                for reason in evaluation.reasons:
                    exclusion_reason_rows.append(
                        {
                            "candidate_id": candidate.id,
                            "title": candidate.title,
                            "buyer_name": evidence.buyer_name if evidence else None,
                            "source_url": evidence.source_url if evidence else candidate.source_url,
                            "reason": reason,
                            "current_actionability_state": evaluation.current_actionability_state,
                            "commercial_motion": evaluation.commercial_motion,
                        }
                    )
        near_miss_rows: list[dict[str, Any]] = []
        for exclusion in session.execute(select(ExclusionAudit).order_by(desc(ExclusionAudit.created_at))).scalars():
            if exclusion.reason not in {"no_d365_anchor", "missing_microsoft_anchor"}:
                continue
            evidence = session.get(EvidenceRecord, exclusion.evidence_record_id)
            source = session.get(SourceRegistry, evidence.source_id) if evidence else None
            details = exclusion.details_json or {}
            near_miss_rows.append(
                {
                    "title": evidence.title if evidence else None,
                    "source": source.name if source else None,
                    "buyer": evidence.buyer_name if evidence else None,
                    "reason_rejected": exclusion.reason,
                    "matched_service_terms": details.get("matched_service_terms", []),
                    "matched_procurement_terms": details.get("matched_procurement_terms", []),
                    "missing_microsoft_anchor_reason": exclusion.reason,
                    "query_family": evidence.query_family if evidence else None,
                    "source_url": evidence.source_url if evidence else None,
                }
            )
        files: list[Path] = []
        files.extend(self._write_payload(directory, "seller_ready_leads", seller_ready_rows, fmt))
        files.extend(self._write_payload(directory, "seller_ready_bid_now_leads", seller_ready_bid_now_rows, fmt))
        files.extend(self._write_payload(directory, "seller_ready_pre_position_leads", seller_ready_pre_position_rows, fmt))
        files.extend(self._write_payload(directory, "research_ready_leads", research_ready_rows, fmt))
        files.extend(self._write_payload(directory, "pitchable_leads", pitchable_rows, fmt))
        files.extend(self._write_payload(directory, "current_bid_now_leads", current_bid_now_rows, fmt))
        files.extend(self._write_payload(directory, "current_pre_position_leads", current_pre_position_rows, fmt))
        files.extend(self._write_payload(directory, "non_pitchable_live_records", non_pitchable_rows, fmt))
        files.extend(self._write_payload(directory, "award_watch", award_watch_rows, fmt))
        files.extend(self._write_payload(directory, "renewal_watch", renewal_watch_rows, fmt))
        files.extend(self._write_payload(directory, "monitor_only", monitor_only_rows, fmt))
        files.extend(self._write_payload(directory, "rejected_near_misses", near_miss_rows, fmt))
        files.extend(self._write_payload(directory, "stale_or_awarded_live_records", stale_or_awarded_rows, fmt))
        files.extend(self._write_payload(directory, "english_insufficient_live_records", english_insufficient_rows, fmt))
        files.extend(self._write_payload(directory, "pitchability_exclusion_reasons", exclusion_reason_rows, fmt))
        return files

    def _apply_authenticity_gate(self, row: dict[str, Any], *, source: SourceRegistry | None) -> dict[str, Any]:
        authenticity = classify_row_authenticity(
            source_name=(source.name if source else row.get("source_name")),
            source_url=row.get("source_url") or row.get("top_source"),
            endpoint=(source.endpoint if source else row.get("top_source")),
            source_family=(source.source_family if source else row.get("source_family")),
            public_access_mode=(
                source.public_access_mode.value
                if source and getattr(source.public_access_mode, "value", None)
                else row.get("public_access_mode")
            ),
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
            row["seller_handoff_rationale"] = "Source is not an official public procurement surface; retain for research or rejection only."
            if authenticity.authenticity_class in {"synthetic_fixture", "demo_seed"}:
                row["sales_handoff_state"] = "reject"
                row["recommended_action"] = "reject"
            else:
                row["sales_handoff_state"] = "research_ready"
            row["pursuit_recommendation"] = row["sales_handoff_state"]
        return row

    def _write_payload(self, directory: Path, base_name: str, payload: list[dict[str, Any]], fmt: str) -> list[Path]:
        files: list[Path] = []
        if fmt in {"csv", "both"}:
            target = directory / f"{base_name}.csv"
            with target.open("w", newline="", encoding="utf-8") as handle:
                fieldnames = sorted({key for row in payload for key in row.keys()}) if payload else ["empty"]
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                if payload:
                    writer.writerows(payload)
            files.append(target)
        if fmt in {"jsonl", "both"}:
            target = directory / f"{base_name}.jsonl"
            with target.open("w", encoding="utf-8") as handle:
                for row in payload:
                    handle.write(json.dumps(row, default=_json_default) + "\n")
            files.append(target)
        return files

    def _dashboard_snapshot(self, session: Session) -> dict[str, Any]:
        opportunities = session.execute(select(OpportunityCandidate)).scalars().all()
        closing_soon = sorted(
            [
                self._row_to_dict(opp)
                for opp in opportunities
                if opp.close_date
                and (
                    (
                        opp.close_date.replace(tzinfo=None)
                        if getattr(opp.close_date, "tzinfo", None)
                        else opp.close_date
                    )
                    - datetime.utcnow()
                ).days
                <= 14
            ],
            key=lambda row: row["close_date"],
        )[:25]
        by_region: dict[str, int] = {}
        by_app: dict[str, int] = {}
        by_grade: dict[str, int] = {}
        by_lane: dict[str, int] = {}
        for opp in opportunities:
            region = opp.country or "unknown"
            by_region[region] = by_region.get(region, 0) + 1
            by_app[opp.app_family] = by_app.get(opp.app_family, 0) + 1
            by_grade[opp.evidence_grade] = by_grade.get(opp.evidence_grade, 0) + 1
            lane = opp.signal_lane.value if hasattr(opp.signal_lane, "value") else str(opp.signal_lane)
            by_lane[lane] = by_lane.get(lane, 0) + 1
        return {
            "generated_at": datetime.utcnow(),
            "total_opportunities": len(opportunities),
            "closing_soon": closing_soon,
            "by_region": by_region,
            "by_app_family": by_app,
            "by_evidence_grade": by_grade,
            "by_signal_lane": by_lane,
        }
