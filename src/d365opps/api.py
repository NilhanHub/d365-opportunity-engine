from __future__ import annotations

import asyncio
import json
import re
import time
from collections import Counter, defaultdict
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from d365opps.config import get_settings
from d365opps.correlation import correlation_scope, ensure_correlation, traceparent
from d365opps.db import SessionLocal, init_db
from d365opps.demo import ensure_demo_data
from d365opps.diagnostics import DiagnosticsService
from d365opps.forensics import ForensicRecorder
from d365opps.models import (
    AcquisitionMethod,
    CandidateStatus,
    DiscoveryStatus,
    ExclusionAudit,
    JobRun,
    Lane,
    ParsingMode,
    PublicAccessMode,
    SourceCanaryResult,
    SourceDiscoveryCandidate,
    SourceFetchEvent,
    SourceRegistry,
)
from d365opps.ops import OpsService
from d365opps.pipeline import PipelineService
from d365opps.verification import VerificationService

try:
    from opentelemetry import trace
except Exception:  # pragma: no cover - optional dependency
    trace = None


def _tracer():
    if trace is None:
        return None
    return trace.get_tracer("d365opps.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    del app
    init_db()
    settings = get_settings()
    session = SessionLocal()
    try:
        recorder = ForensicRecorder(session, service="api")
        recorder.emit_event(
            "app.startup",
            component="lifespan",
            phase="startup",
            status="started",
            payload={"demo_mode": settings.demo_mode},
        )
        if settings.demo_mode:
            ensure_demo_data(session)
        session.commit()
    finally:
        session.close()
    try:
        yield
    finally:
        session = SessionLocal()
        try:
            recorder = ForensicRecorder(session, service="api")
            recorder.emit_event("app.shutdown", component="lifespan", phase="shutdown", status="completed")
            session.commit()
        finally:
            session.close()


app = FastAPI(
    title="D365 Opportunity Engine API",
    description="Operator API for source operations, discovery coverage, runs, evidence, and exports.",
    version="0.2.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_metrics(request, call_next):
    tracer = _tracer()
    started = time.perf_counter()
    incoming_traceparent = request.headers.get("traceparent")
    trace_id = None
    parent_span = None
    if incoming_traceparent:
        parts = incoming_traceparent.split("-")
        if len(parts) >= 4:
            trace_id = parts[1]
            parent_span = parts[2]
    request_id = request.headers.get("x-request-id")
    with correlation_scope(trace_id=trace_id, span_id=parent_span, request_id=request_id):
        ensure_correlation(request_id=request_id, trace_id=trace_id, span_id=parent_span)
        if tracer:
            with tracer.start_as_current_span(f"{request.method} {request.url.path}"):
                response = await call_next(request)
        else:
            response = await call_next(request)
        response.headers["X-Process-Time-Ms"] = str(int((time.perf_counter() - started) * 1000))
        response.headers["X-Request-Id"] = ensure_correlation().request_id or ""
        response.headers["X-Trace-Id"] = ensure_correlation().trace_id or ""
        response.headers["traceparent"] = traceparent()
        return response


def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


class RefreshRequest(BaseModel):
    source_names: list[str] | None = None
    region: str | None = None
    since: datetime | None = None
    include_disabled: bool = False
    mode: str = "incremental_sync"


class DiscoverRequest(BaseModel):
    source_names: list[str] | None = None
    limit: int | None = None
    auto_enable_threshold: float = 0.95


class CandidateDecisionRequest(BaseModel):
    candidate_id: str
    reason: str | None = None
    enable_source: bool = False


class ExportRequest(BaseModel):
    fmt: str = "both"
    filters: dict[str, Any] = Field(default_factory=dict)


class ReprocessRequest(BaseModel):
    document_id: str


class RescoreRequest(BaseModel):
    document_ids: list[str] | None = None
    purge_invalidated: bool = True


class SavedViewRequest(BaseModel):
    name: str
    route: str
    description: str | None = None
    filters_json: dict[str, Any] = Field(default_factory=dict)
    columns_json: list[str] = Field(default_factory=list)
    density: str | None = None


class VerifyPackRequest(BaseModel):
    run_id: str | None = None
    include_blobs: bool = False
    include_db_dump: bool = False


def _ops(session: Session) -> OpsService:
    return OpsService(session)


def _pipeline(session: Session) -> PipelineService:
    return PipelineService(session)


def _diagnostics(session: Session) -> DiagnosticsService:
    return DiagnosticsService(session)


def _verifier(session: Session) -> VerificationService:
    return VerificationService(session)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug[:80] or "discovered_source"


def _candidate_to_registry(candidate: SourceDiscoveryCandidate, *, enabled: bool) -> dict[str, Any]:
    return {
        "name": _slugify(candidate.candidate_name),
        "description": f"Discovered source: {candidate.candidate_name}",
        "lane": Lane.OPPORTUNITY if candidate.signal_lane in {None} or candidate.signal_lane.value in {"formal_procurement", "pre_positioning"} else Lane.SIGNAL,
        "tier": 3,
        "region": candidate.region,
        "country": candidate.country,
        "enabled": enabled,
        "is_seed": False,
        "cadence": "daily",
        "acquisition_method": candidate.acquisition_method,
        "parsing_mode": candidate.parsing_mode,
        "endpoint": candidate.endpoint,
        "legal_notes": "Discovered public source. Validate terms and robots before sustained collection.",
        "access_notes": candidate.access_notes,
        "source_family": candidate.source_family,
        "public_access_mode": candidate.public_access_mode,
        "language_support_json": candidate.language_support_json,
        "content_types_json": candidate.content_types_json,
        "supported_lanes_json": [candidate.signal_lane.value] if candidate.signal_lane else [],
        "discovery_provenance_json": candidate.provenance_json,
        "source_discovery_confidence": candidate.confidence,
        "search_capabilities_json": {"supports_query": False},
        "source_capability_json": {"portal_fingerprint": candidate.portal_fingerprint} if candidate.portal_fingerprint else {},
        "rate_limit_policy_json": {"per_minute": 2},
        "config_json": {"discovery_mode": candidate.discovery_mode},
        "known_blind_spot_reason": candidate.known_blind_spot_reason,
        "robots_status": candidate.robots_status,
    }


def _read_json_file(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _read_jsonl_file(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except Exception:
            continue
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def _triage_matrix(rows: list[dict[str, Any]], group_key: str, limit: int = 12) -> list[dict[str, Any]]:
    verdict_keys = [
        "promising_near_miss",
        "promising_surface_needs_detail_follow",
        "award_or_history_surface",
        "non_d365_or_too_generic",
        "false_friend_or_competitor_noise",
    ]
    grouped: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        group_value = str(row.get(group_key) or "unknown")
        verdict = str(row.get("review_verdict") or "unknown")
        grouped[group_value][verdict] += 1
    items: list[dict[str, Any]] = []
    for group_value, counts in grouped.items():
        item = {
            group_key: group_value,
            "total": sum(counts.values()),
        }
        for verdict in verdict_keys:
            item[verdict] = counts.get(verdict, 0)
        items.append(item)
    items.sort(key=lambda item: (_safe_int(item["total"]), _safe_int(item.get("promising_surface_needs_detail_follow"))), reverse=True)
    return items[:limit]


def _triage_queue_rows(bucket_report: dict[str, Any], bucket_name: str, limit: int = 12) -> list[dict[str, Any]]:
    bucket = ((bucket_report.get("buckets") or {}).get(bucket_name) or {})
    rows = bucket.get("top_rows") or []
    return [row for row in rows if isinstance(row, dict)][:limit]


def _detail_queue_rows(detail_report: dict[str, Any], key: str, limit: int = 12) -> list[dict[str, Any]]:
    rows = detail_report.get(key) or []
    return [row for row in rows if isinstance(row, dict)][:limit]


def _triage_blockers(bucket_report: dict[str, Any], detail_report: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    buckets = bucket_report.get("buckets") or {}
    for bucket_name, payload in buckets.items():
        for blocker in (payload.get("top_blockers") or [])[:4]:
            if isinstance(blocker, dict):
                reason = blocker.get("reason", "unknown")
                count = blocker.get("count")
            elif isinstance(blocker, (list, tuple)) and len(blocker) >= 2:
                reason = blocker[0]
                count = blocker[1]
            else:
                continue
            items.append({"bucket": bucket_name, "reason": str(reason), "count": _safe_int(count)})
    detail_reasons = detail_report.get("final_reason_counts") or {
        str(reason): _safe_int(count) for reason, count in (detail_report.get("top_final_reasons") or []) if isinstance(reason, str)
    }
    for reason, count in detail_reasons.items():
        items.append(
            {
                "bucket": "detail_follow",
                "reason": reason,
                "count": _safe_int(count),
            }
        )
    items.sort(key=lambda item: item["count"], reverse=True)
    return items[:16]


def _triage_funnel(summary: dict[str, Any], detail_report: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    verdict_counts = summary.get("verdict_counts") or {}
    reviewed = _safe_int(summary.get("records_reviewed")) or len(rows)
    detail_counts = detail_report.get("final_state_counts") or {}
    return [
        {"key": "docs_returning_non_prime", "label": "Docs-returning non-prime", "count": reviewed, "tone": "input"},
        {
            "key": "promising_near_miss",
            "label": "Near misses",
            "count": _safe_int(verdict_counts.get("promising_near_miss")),
            "tone": "review",
        },
        {
            "key": "promising_surface_needs_detail_follow",
            "label": "Needs detail follow",
            "count": _safe_int(verdict_counts.get("promising_surface_needs_detail_follow")),
            "tone": "review",
        },
        {
            "key": "award_or_history_surface",
            "label": "Award or history",
            "count": _safe_int(verdict_counts.get("award_or_history_surface")),
            "tone": "watch",
        },
        {
            "key": "non_d365_or_too_generic",
            "label": "Too generic",
            "count": _safe_int(verdict_counts.get("non_d365_or_too_generic")),
            "tone": "reject",
        },
        {
            "key": "false_friend_or_competitor_noise",
            "label": "False-friend noise",
            "count": _safe_int(verdict_counts.get("false_friend_or_competitor_noise")),
            "tone": "reject",
        },
        {
            "key": "detail_no_upgrade",
            "label": "No upgrade after follow",
            "count": _safe_int(detail_counts.get("no_upgrade")),
            "tone": "detail",
        },
        {
            "key": "detail_watch_only",
            "label": "Watch-only after follow",
            "count": _safe_int(detail_counts.get("watch_only")),
            "tone": "watch",
        },
        {
            "key": "detail_manual_review",
            "label": "Manual review after follow",
            "count": _safe_int(detail_counts.get("still_needs_manual_review")),
            "tone": "detail",
        },
        {
            "key": "detail_promoted",
            "label": "Promoted after follow",
            "count": _safe_int(detail_counts.get("promoted_seller_ready")) + _safe_int(detail_counts.get("promoted_research_ready")),
            "tone": "promote",
        },
    ]


@app.get("/api/overview")
def overview(session: Session = Depends(get_session)) -> dict[str, Any]:
    return _ops(session).overview()


@app.get("/api/status")
def status(session: Session = Depends(get_session)) -> dict[str, Any]:
    overview_payload = _ops(session).overview()
    return {
        "demo_mode": overview_payload.get("demo_mode", False),
        "data_mode": overview_payload.get("data_mode", "LIVE"),
        "live_records": overview_payload.get("kpis", {}).get("live_records", 0),
        "demo_records": overview_payload.get("kpis", {}).get("demo_records", 0),
        "last_live_refresh": overview_payload.get("kpis", {}).get("last_live_refresh"),
        "last_successful_backfill": overview_payload.get("kpis", {}).get("last_successful_backfill"),
    }


@app.get("/api/sources")
def list_sources(
    offset: int = 0,
    limit: int = Query(50, le=500),
    state: str | None = None,
    region: str | None = None,
    country: str | None = None,
    lane: str | None = None,
    enabled: bool | None = None,
    source_family: str | None = None,
    sort_by: str = "name",
    sort_dir: str = "asc",
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return _ops(session).list_sources(
        offset=offset,
        limit=limit,
        state=state,
        region=region,
        country=country,
        lane=lane,
        enabled=enabled,
        source_family=source_family,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )


@app.get("/api/sources/{source_id}")
def get_source(source_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    try:
        return _ops(session).get_source(source_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Source not found") from exc


@app.get("/api/sources/{source_id}/runs")
def source_runs(source_id: str, offset: int = 0, limit: int = Query(50, le=200), session: Session = Depends(get_session)) -> dict[str, Any]:
    return _ops(session).source_runs(source_id, offset=offset, limit=limit)


@app.get("/api/sources/{source_id}/issues")
def source_issues(source_id: str, offset: int = 0, limit: int = Query(50, le=200), session: Session = Depends(get_session)) -> dict[str, Any]:
    return _ops(session).source_issues(source_id, offset=offset, limit=limit)


@app.get("/api/sources/{source_id}/documents")
def source_documents(source_id: str, offset: int = 0, limit: int = Query(50, le=200), session: Session = Depends(get_session)) -> dict[str, Any]:
    return _ops(session).source_documents(source_id, offset=offset, limit=limit)


@app.get("/api/discovery/candidates")
def discovery_candidates(
    offset: int = 0,
    limit: int = Query(50, le=200),
    review_status: str | None = None,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return _ops(session).list_discovery_candidates(offset=offset, limit=limit, review_status=review_status)


@app.get("/api/issues")
def list_issues(
    offset: int = 0,
    limit: int = Query(50, le=200),
    source_id: str | None = None,
    sort_by: str = "last_seen_at",
    sort_dir: str = "desc",
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return _ops(session).list_issues(offset=offset, limit=limit, source_id=source_id, sort_by=sort_by, sort_dir=sort_dir)


@app.get("/api/runs")
def list_runs(offset: int = 0, limit: int = Query(50, le=200), session: Session = Depends(get_session)) -> dict[str, Any]:
    return _ops(session).list_runs(offset=offset, limit=limit)


@app.get("/api/runs/stream")
async def stream_runs(
    request: Request,
    limit: int = Query(50, le=200),
    interval: float = Query(2.0, ge=1.0, le=30.0),
) -> StreamingResponse:
    async def event_stream():
        while True:
            if await request.is_disconnected():
                break
            with SessionLocal() as session:
                payload = _ops(session).list_runs(offset=0, limit=limit)
            yield f"data: {json.dumps(payload, default=str)}\n\n"
            await asyncio.sleep(interval)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/runs/{run_id}")
def get_run(run_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    try:
        return _ops(session).get_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc


@app.get("/api/queries")
def list_queries(
    offset: int = 0,
    limit: int = Query(50, le=200),
    source_id: str | None = None,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return _ops(session).list_queries(offset=offset, limit=limit, source_id=source_id)


@app.get("/api/opportunities")
def list_opportunities(
    offset: int = 0,
    limit: int = Query(50, le=200),
    keyword: str | None = None,
    country: str | None = None,
    signal_lane: str | None = None,
    recommended_action: str | None = None,
    sort_by: str = "updated_at",
    sort_dir: str = "desc",
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return _ops(session).list_opportunities(
        offset=offset,
        limit=limit,
        keyword=keyword,
        country=country,
        signal_lane=signal_lane,
        recommended_action=recommended_action,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )


@app.get("/api/opportunities/{opportunity_id}")
def get_opportunity(opportunity_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    try:
        return _ops(session).get_opportunity(opportunity_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Opportunity not found") from exc


@app.get("/api/signals")
def list_signals(
    offset: int = 0,
    limit: int = Query(50, le=200),
    signal_lane: str | None = None,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return _ops(session).list_signals(offset=offset, limit=limit, signal_lane=signal_lane)


@app.get("/api/accounts")
def list_accounts(offset: int = 0, limit: int = Query(50, le=200), session: Session = Depends(get_session)) -> dict[str, Any]:
    return _ops(session).list_accounts(offset=offset, limit=limit)


@app.get("/api/coverage")
def coverage(session: Session = Depends(get_session)) -> dict[str, Any]:
    return _ops(session).coverage()


@app.get("/api/exports")
def exports(session: Session = Depends(get_session)) -> dict[str, Any]:
    return _ops(session).exports()


@app.get("/api/diagnostics")
def diagnostics(session: Session = Depends(get_session)) -> dict[str, Any]:
    return _diagnostics(session).diagnostics_overview()


@app.get("/api/diagnostics/empty")
def diagnostics_empty(session: Session = Depends(get_session)) -> dict[str, Any]:
    return _diagnostics(session).explain_zero()


@app.get("/api/diagnostics/source/{source_id}")
def diagnostics_source(source_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    try:
        return _diagnostics(session).source_diagnostics(source_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Source not found") from exc


@app.get("/api/diagnostics/run/{run_id}")
def diagnostics_run(run_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    try:
        return _diagnostics(session).run_diagnostics(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc


@app.get("/api/triage")
def triage() -> dict[str, Any]:
    root = get_settings().artifact_root / "source_campaign" / "latest"
    summary = _read_json_file(root / "full_document_intelligent_review_summary.json", {})
    bucket_report = _read_json_file(root / "bucket_drilldown_report.json", {})
    detail_report = _read_json_file(root / "detail_follow_promising_surface_needs_detail_follow_report.json", {})
    rows = _read_jsonl_file(root / "full_document_intelligent_review.jsonl")
    reviewed = _safe_int(summary.get("records_reviewed")) or len(rows)
    verdict_counts = summary.get("verdict_counts") or {}
    interesting_total = (
        _safe_int(verdict_counts.get("promising_near_miss"))
        + _safe_int(verdict_counts.get("promising_surface_needs_detail_follow"))
        + _safe_int(verdict_counts.get("award_or_history_surface"))
    )
    detail_counts = detail_report.get("final_state_counts") or {}
    detail_reason_counts = detail_report.get("final_reason_counts") or {
        str(reason): _safe_int(count) for reason, count in (detail_report.get("top_final_reasons") or []) if isinstance(reason, str)
    }
    family_heatmap = _triage_matrix(rows, "family")
    country_heatmap = _triage_matrix(rows, "country")
    return {
        "artifact_path": str(root),
        "generated_at": summary.get("generated_at") or detail_report.get("generated_at"),
        "headline": {
            "reviewed": reviewed,
            "interesting_total": interesting_total,
            "near_miss_total": _safe_int(verdict_counts.get("promising_near_miss")),
            "detail_follow_total": _safe_int(verdict_counts.get("promising_surface_needs_detail_follow")),
            "award_history_total": _safe_int(verdict_counts.get("award_or_history_surface")),
            "detail_follow_reviewed": _safe_int(detail_report.get("candidates_reviewed")),
            "detail_manual_review": _safe_int(detail_counts.get("still_needs_manual_review")),
            "detail_watch_only": _safe_int(detail_counts.get("watch_only")),
            "detail_promoted": _safe_int(detail_counts.get("promoted_seller_ready")) + _safe_int(detail_counts.get("promoted_research_ready")),
        },
        "funnel": _triage_funnel(summary, detail_report, rows),
        "family_heatmap": family_heatmap,
        "country_heatmap": country_heatmap,
        "blockers": _triage_blockers(bucket_report, detail_report),
        "detail_follow_summary": {
            "final_state_counts": detail_counts,
            "final_reason_counts": detail_reason_counts,
            "manual_review_rows": _detail_queue_rows(detail_report, "top_manual_review"),
            "watch_only_rows": _detail_queue_rows(detail_report, "top_watch_only"),
        },
        "queues": {
            "near_miss": _triage_queue_rows(bucket_report, "promising_near_miss"),
            "detail_follow": _triage_queue_rows(bucket_report, "promising_surface_needs_detail_follow"),
            "award_history": _triage_queue_rows(bucket_report, "award_or_history_surface"),
        },
        "artifact_files": {
            "summary": str(root / "full_document_intelligent_review_summary.md"),
            "bucket_drilldown": str(root / "bucket_drilldown_report.md"),
            "detail_follow": str(root / "detail_follow_promising_surface_needs_detail_follow_report.md"),
        },
    }


@app.get("/api/verification/latest")
def verification_latest(session: Session = Depends(get_session)) -> dict[str, Any]:
    return _verifier(session).latest_bundle()


@app.get("/api/verification/latest/download")
def verification_latest_download(session: Session = Depends(get_session)) -> FileResponse:
    bundle = _verifier(session).latest_bundle()
    zip_path = bundle["bundle_zip_path"]
    if not Path(zip_path).exists():
        bundle = _verifier(session).generate_bundle()
        zip_path = bundle["bundle_zip_path"]
    return FileResponse(zip_path, filename=Path(zip_path).name)


@app.get("/api/verification/{run_id}")
def verification_for_run(run_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    return _verifier(session).generate_bundle(run_id=run_id)


@app.get("/api/verification/{run_id}/download")
def verification_download(run_id: str, session: Session = Depends(get_session)) -> FileResponse:
    bundle = _verifier(session).generate_bundle(run_id=run_id)
    return FileResponse(bundle["bundle_zip_path"], filename=Path(bundle["bundle_zip_path"]).name)


@app.get("/api/saved-views")
def saved_views(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return _ops(session).list_saved_views()


@app.post("/api/saved-views")
def create_saved_view(payload: SavedViewRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    return _ops(session).create_saved_view(payload.model_dump())


@app.post("/api/actions/refresh")
def refresh(payload: RefreshRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    pipeline = _pipeline(session)
    if payload.mode == "bootstrap_backfill":
        results = pipeline.bootstrap_backfill(
            source_names=payload.source_names,
            region=payload.region,
            since=payload.since,
            include_disabled=payload.include_disabled,
        )
    else:
        results = pipeline.incremental_sync(
            source_names=payload.source_names,
            region=payload.region,
            since=payload.since,
            include_disabled=payload.include_disabled,
        )
    return {"items": results}


@app.post("/api/actions/bootstrap-backfill")
def bootstrap_backfill(payload: RefreshRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    results = _pipeline(session).bootstrap_backfill(
        source_names=payload.source_names,
        region=payload.region,
        since=payload.since,
        include_disabled=payload.include_disabled,
    )
    return {"items": results}


@app.post("/api/actions/discover-sources")
def discover_sources(payload: DiscoverRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    results = _pipeline(session).discover_sources(
        source_names=payload.source_names,
        limit=payload.limit,
        auto_enable_threshold=payload.auto_enable_threshold,
    )
    return {"items": results}


@app.post("/api/actions/approve-source")
def approve_source(payload: CandidateDecisionRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    candidate = session.get(SourceDiscoveryCandidate, payload.candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate source not found")
    candidate.discovery_status = DiscoveryStatus.ENABLED
    if payload.reason:
        candidate.access_notes = payload.reason
    existing = session.execute(select(SourceRegistry).where(SourceRegistry.endpoint == candidate.endpoint)).scalar_one_or_none()
    if not existing:
        registry = SourceRegistry(**_candidate_to_registry(candidate, enabled=payload.enable_source))
        session.add(registry)
        session.flush()
    return {"id": candidate.id, "status": candidate.discovery_status.value, "enabled_source": payload.enable_source}


@app.post("/api/actions/reject-source")
def reject_source(payload: CandidateDecisionRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    candidate = session.get(SourceDiscoveryCandidate, payload.candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate source not found")
    candidate.discovery_status = DiscoveryStatus.REJECTED
    if payload.reason:
        candidate.access_notes = payload.reason
    return {"id": candidate.id, "status": candidate.discovery_status.value}


@app.post("/api/actions/reprocess")
def reprocess(payload: ReprocessRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    return _pipeline(session).reprocess(payload.document_id)


@app.post("/api/actions/rescore")
def rescore(payload: RescoreRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    return _pipeline(session).rescore_historical(
        document_ids=payload.document_ids,
        purge_invalidated=payload.purge_invalidated,
    )


@app.post("/api/actions/purge-demo")
def purge_demo(session: Session = Depends(get_session)) -> dict[str, Any]:
    return _pipeline(session).purge_demo_records()


@app.post("/api/actions/export")
def export(payload: ExportRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    result = _pipeline(session).export(fmt=payload.fmt, filters=payload.filters)
    return {"directory": str(result.directory), "files": [str(path) for path in result.files]}


@app.post("/api/actions/canary-sweep")
def canary_sweep(payload: DiscoverRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    return {"items": _pipeline(session).canary_sweep(source_names=payload.source_names)}


@app.post("/api/actions/verify-pack")
def verify_pack(payload: VerifyPackRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    return _pipeline(session).verify_pack(
        run_id=payload.run_id,
        include_blobs=payload.include_blobs,
        include_db_dump=payload.include_db_dump,
    )


@app.post("/api/actions/doctor")
def doctor(payload: DiscoverRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    return _pipeline(session).doctor(source_names=payload.source_names)


@app.get("/metrics", response_class=PlainTextResponse)
def metrics(session: Session = Depends(get_session)) -> str:
    ops = _ops(session)
    diagnostics_service = _diagnostics(session)
    overview = ops.overview()
    sources = ops.list_sources(limit=500, offset=0)["items"]
    issues = ops.list_issues(limit=500, offset=0)["items"]
    canaries = diagnostics_service.diagnostics_overview()["canary_board"]
    runs = [row for row in session.execute(select(JobRun)).scalars()]
    exclusions = [row.reason for row in session.execute(select(ExclusionAudit)).scalars()]
    lines = [
        "# HELP d365_sources_total Total sources known to the engine.",
        "# TYPE d365_sources_total gauge",
        f"d365_sources_total {len(sources)}",
        "# HELP d365_opportunities_total Total opportunity candidates.",
        "# TYPE d365_opportunities_total gauge",
        f"d365_opportunities_total {overview['kpis']['opportunity_candidates_created']}",
        "# HELP d365_signals_total Total market signals.",
        "# TYPE d365_signals_total gauge",
        f"d365_signals_total {overview['kpis']['market_signals_created']}",
        "# HELP d365_documents_fetched_24h Acquisition documents fetched in the last 24 hours. Not a lead count.",
        "# TYPE d365_documents_fetched_24h gauge",
        f"d365_documents_fetched_24h {overview['kpis']['documents_fetched_24h']}",
        "# HELP d365_seller_ready_bid_now_total Seller-ready current open-bid leads.",
        "# TYPE d365_seller_ready_bid_now_total gauge",
        f"d365_seller_ready_bid_now_total {overview['kpis'].get('seller_ready_bid_now_total', 0)}",
        "# HELP d365_seller_ready_pre_position_total Seller-ready current pre-position leads.",
        "# TYPE d365_seller_ready_pre_position_total gauge",
        f"d365_seller_ready_pre_position_total {overview['kpis'].get('seller_ready_pre_position_total', 0)}",
        "# HELP d365_current_actionable_total Current commercially actionable D365 records.",
        "# TYPE d365_current_actionable_total gauge",
        f"d365_current_actionable_total {overview['kpis'].get('current_actionable_total', 0)}",
        "# HELP d365_retained_d365_records_total Retained live D365-anchored records.",
        "# TYPE d365_retained_d365_records_total gauge",
        f"d365_retained_d365_records_total {overview['kpis'].get('retained_d365_records', 0)}",
        "# HELP d365_live_records Total live records in the current dataset.",
        "# TYPE d365_live_records gauge",
        f"d365_live_records {overview['kpis'].get('live_records', 0)}",
        "# HELP d365_demo_records Total demo records in the current dataset.",
        "# TYPE d365_demo_records gauge",
        f"d365_demo_records {overview['kpis'].get('demo_records', 0)}",
        "# HELP d365_empty_dataset_alert Whether the live dataset is empty.",
        "# TYPE d365_empty_dataset_alert gauge",
        f"d365_empty_dataset_alert {1 if overview['kpis'].get('live_records', 0) == 0 else 0}",
        "# HELP d365_starter_backfill_needed Whether no successful bootstrap backfill has completed.",
        "# TYPE d365_starter_backfill_needed gauge",
        f"d365_starter_backfill_needed {1 if not overview['kpis'].get('last_successful_backfill') else 0}",
    ]
    for state in sorted({source["operational_state"] for source in sources}):
        count = sum(1 for source in sources if source["operational_state"] == state)
        lines.append(f'd365_sources_by_state{{state="{state}"}} {count}')
    for state in sorted({source["forthcoming_state"] for source in sources}):
        count = sum(1 for source in sources if source["forthcoming_state"] == state)
        lines.append(f'd365_sources_by_forthcoming_state{{state="{state}"}} {count}')
    for issue_code in sorted({issue["issue_code"] for issue in issues if issue.get("issue_code")}):
        count = sum(1 for issue in issues if issue["issue_code"] == issue_code)
        lines.append(f'd365_source_issue_total{{issue_code="{issue_code}"}} {count}')
    canary_passed = sum(1 for row in canaries if row["status"] == "passed")
    canary_failed = sum(1 for row in canaries if row["status"] != "passed")
    lines.append(f"d365_canary_results_total {len(canaries)}")
    lines.append(f'd365_canary_status_total{{status="passed"}} {canary_passed}')
    lines.append(f'd365_canary_status_total{{status="failed"}} {canary_failed}')
    fetch_total = int(session.execute(select(func.count(SourceFetchEvent.id))).scalar_one() or 0)
    fetch_success = int(session.execute(select(func.count(SourceFetchEvent.id)).where(SourceFetchEvent.success_flag.is_(True))).scalar_one() or 0)
    lines.append("# HELP d365_fetch_attempts_total Acquisition fetch attempts. Not a lead count.")
    lines.append(f"d365_fetch_attempts_total {fetch_total}")
    lines.append("# HELP d365_fetch_success_total Successful acquisition fetch attempts. Not a lead count.")
    lines.append(f"d365_fetch_success_total {fetch_success}")
    for reason in sorted(set(exclusions)):
        count = exclusions.count(reason)
        lines.append(f'd365_classifier_exclusions_total{{reason="{reason}"}} {count}')
    for job_type in sorted({run.job_type.value for run in runs}):
        count = sum(1 for run in runs if run.job_type.value == job_type)
        lines.append(f'd365_runs_total{{job_type="{job_type}"}} {count}')
    for status in sorted({run.status.value for run in runs}):
        count = sum(1 for run in runs if run.status.value == status)
        lines.append(f'd365_runs_by_status{{status="{status}"}} {count}')
    last_success = [
        source["last_successful_fetch"]
        for source in sources
        if source.get("last_successful_fetch")
    ]
    if last_success:
        latest = max(datetime.fromisoformat(value) for value in last_success)
        age_seconds = int((datetime.now() - latest).total_seconds())
        lines.append(f"d365_last_success_age_seconds {age_seconds}")
    return "\n".join(lines) + "\n"


def main() -> None:
    import uvicorn

    uvicorn.run("d365opps.api:app", host="0.0.0.0", port=8000, reload=False)
