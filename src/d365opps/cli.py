from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer
from dateutil import parser as date_parser

from d365opps.db import init_db, session_scope
from d365opps.models import CandidateStatus
from d365opps.pipeline import PipelineService


app = typer.Typer(help="Public Dynamics 365 opportunity discovery engine.")


def _parse_since(value: str | None) -> datetime | None:
    return date_parser.parse(value) if value else None


@app.command("init-db")
def init_db_command() -> None:
    init_db()
    typer.echo("Database schema initialized.")


@app.command("seed-sources")
def seed_sources_command() -> None:
    with session_scope() as session:
        service = PipelineService(session)
        sources = service.init_sources()
        typer.echo(f"Seeded {len(sources)} sources.")


@app.command("list-sources")
def list_sources_command(enabled_only: bool = False) -> None:
    with session_scope() as session:
        service = PipelineService(session)
        for source in service.list_sources(enabled_only=enabled_only):
            typer.echo(
                f"{source.name}\tenabled={source.enabled}\ttier={source.tier}\tlane={source.lane.value}\tregion={source.region}"
            )


@app.command("discover-sources")
def discover_sources_command(
    source: Annotated[list[str] | None, typer.Option("--source")] = None,
    limit: Annotated[int | None, typer.Option("--limit")] = None,
    auto_enable_threshold: Annotated[float, typer.Option("--auto-enable-threshold")] = 0.95,
) -> None:
    with session_scope() as session:
        service = PipelineService(session)
        results = service.discover_sources(
            source_names=source,
            limit=limit,
            auto_enable_threshold=auto_enable_threshold,
        )
        for item in results:
            typer.echo(
                f"{item['candidate_name']}\tconfidence={item['confidence']}\tstatus={item['discovery_status']}\trobots={item['robots_status']}\t{item['endpoint']}"
            )


@app.command("query-preview")
def query_preview_command(source: Annotated[list[str] | None, typer.Option("--source")] = None) -> None:
    with session_scope() as session:
        service = PipelineService(session)
        previews = service.query_preview(source_names=source)
        for item in previews:
            negatives = ", ".join(item["negative_terms"][:6])
            typer.echo(
                f"{item['source_name']}\t{item['query_family']}\t{item['mode']}\t{item['phase']}\t{item['target_field']}\t{item['query_id']}\t{item['query_text']}\trenderer={item.get('renderer')}\tbrowse_only={item.get('browse_only')}\tnegatives={negatives}"
            )


@app.command("source-health")
def source_health_command(enabled_only: bool = False) -> None:
    with session_scope() as session:
        service = PipelineService(session)
        for item in service.source_health(enabled_only=enabled_only):
            typer.echo(
                f"{item['name']}\tenabled={item['enabled']}\thealth={item['health_status']}\tlast_ok={item['last_successful_fetch_at']}\tlast_attempt={item['last_attempted_fetch_at']}\trobots={item['robots_status']}"
            )


@app.command("recall-report")
def recall_report_command(
    fixtures: Annotated[Path, typer.Option("--fixtures")] = Path("tests/fixtures/retrieval_cases.json"),
) -> None:
    with session_scope() as session:
        service = PipelineService(session)
        report = service.recall_report(str(fixtures))
        typer.echo(
            f"precision={report['precision']}\trecall={report['recall']}\tfalse_positive_rate={report['false_positive_rate']}\tcases={report['totals']['cases']}"
        )
        for item in report["false_negative_examples"][:10]:
            typer.echo(
                f"false_negative\t{item['id']}\treason={item['reason']}\tscore={item['retrieval_score']}\t{item['title']}"
            )


@app.command("discover-accounts")
def discover_accounts_command() -> None:
    with session_scope() as session:
        service = PipelineService(session)
        for item in service.discover_accounts():
            typer.echo(
                f"{item['account_id']}\t{item['canonical_name']}\theat={item['heat_score']}\ttrigger={item['trigger_strength']}\tinstalled={item['installed_product_guess']}"
            )


@app.command("coverage-report")
def coverage_report_command() -> None:
    with session_scope() as session:
        service = PipelineService(session)
        typer.echo(service.coverage_report())


@app.command("lane-report")
def lane_report_command() -> None:
    with session_scope() as session:
        service = PipelineService(session)
        for item in service.lane_report():
            typer.echo(
                f"{item['signal_lane']}\trecords={item['records']}\taccounts={item['unique_accounts']}\tavg_retrieval={item['avg_retrieval_score']}"
            )


@app.command("source-gap-report")
def source_gap_report_command() -> None:
    with session_scope() as session:
        service = PipelineService(session)
        for item in service.source_gap_report():
            typer.echo(
                f"{item['name']}\tenabled={item['enabled']}\taccess={item['public_access_mode']}\thealth={item['health_status']}\tblind_spot={item['known_blind_spot_reason']}"
            )


@app.command("build-source-universe")
def build_source_universe_command(
    target_size: Annotated[int, typer.Option("--target-size")] = 400,
    include_dynamic: Annotated[bool, typer.Option("--include-dynamic/--no-include-dynamic")] = True,
) -> None:
    with session_scope() as session:
        service = PipelineService(session)
        result = service.build_source_universe(target_size=target_size, include_dynamic=include_dynamic)
        typer.echo(f"Source universe path: {result['path']}")
        typer.echo(f"Latest pointer: {result['latest_path']}")
        typer.echo(f"Source universe total: {result['source_universe_total']}")


@app.command("attempt-source-universe")
def attempt_source_universe_command(
    concurrency: Annotated[int, typer.Option("--concurrency")] = 20,
    rebuild_if_missing: Annotated[bool, typer.Option("--rebuild-if-missing/--no-rebuild-if-missing")] = True,
) -> None:
    with session_scope() as session:
        service = PipelineService(session)
        result = service.attempt_source_universe(concurrency=concurrency, rebuild_if_missing=rebuild_if_missing)
        typer.echo(f"Attempt report path: {result['path']}")
        typer.echo(f"Latest pointer: {result['latest_path']}")
        typer.echo(f"Attempted source surfaces: {result['attempted_source_surfaces']}")
        typer.echo(f"Seller-ready total: {result['seller_ready_total']}")


@app.command("global-source-campaign")
def global_source_campaign_command(
    target_size: Annotated[int, typer.Option("--target-size")] = 400,
    concurrency: Annotated[int, typer.Option("--concurrency")] = 20,
    include_dynamic: Annotated[bool, typer.Option("--include-dynamic/--no-include-dynamic")] = True,
) -> None:
    with session_scope() as session:
        service = PipelineService(session)
        result = service.global_source_campaign(target_size=target_size, concurrency=concurrency, include_dynamic=include_dynamic)
        typer.echo(f"Universe path: {result['build']['path']}")
        typer.echo(f"Attempts path: {result['attempts']['path']}")
        typer.echo(f"Source universe total: {result['build']['source_universe_total']}")
        typer.echo(f"Attempted source surfaces: {result['attempts']['attempted_source_surfaces']}")


@app.command("review-potential-hits")
def review_potential_hits_command(
    limit: Annotated[int | None, typer.Option("--limit")] = None,
    ai_shortlist: Annotated[int | None, typer.Option("--ai-shortlist")] = None,
    use_ai: Annotated[bool | None, typer.Option("--use-ai/--no-use-ai")] = None,
    campaign_path: Annotated[str | None, typer.Option("--campaign-path")] = None,
) -> None:
    with session_scope() as session:
        service = PipelineService(session)
        result = service.review_potential_hits(
            limit=limit,
            ai_shortlist=ai_shortlist,
            use_ai=use_ai,
            campaign_path=campaign_path,
        )
        typer.echo(f"Potential-hit review path: {result['path']}")
        typer.echo(f"Prime hits total: {result['prime_hits_total']}")
        typer.echo(f"Potential hits total: {result['potential_hits_total']}")
        typer.echo(f"AI review status: {result['ai_review_status']}")


@app.command("detail-follow-bucket")
def detail_follow_bucket_command(
    bucket: Annotated[str, typer.Option("--bucket")] = "promising_surface_needs_detail_follow",
    limit: Annotated[int | None, typer.Option("--limit")] = None,
    campaign_path: Annotated[str | None, typer.Option("--campaign-path")] = None,
) -> None:
    with session_scope() as session:
        service = PipelineService(session)
        result = service.detail_follow_bucket(
            bucket=bucket,
            limit=limit,
            campaign_path=campaign_path,
        )
        typer.echo(f"Detail-follow path: {result['path']}")
        typer.echo(f"Bucket reviewed: {result['bucket']}")
        typer.echo(f"Candidates reviewed: {result['candidates_reviewed']}")
        typer.echo(f"Promoted seller-ready: {result['promoted_seller_ready_total']}")
        typer.echo(f"Promoted research: {result['promoted_research_total']}")


@app.command("verify-pack")
def verify_pack_command(
    run_id: Annotated[str | None, typer.Option("--run-id")] = None,
    include_blobs: Annotated[bool, typer.Option("--include-blobs")] = False,
    include_db_dump: Annotated[bool, typer.Option("--include-db-dump")] = False,
) -> None:
    with session_scope() as session:
        service = PipelineService(session)
        result = service.verify_pack(run_id=run_id, include_blobs=include_blobs, include_db_dump=include_db_dump)
        typer.echo(f"Bundle: {result['bundle_path']}")
        typer.echo(f"Zip: {result['bundle_zip_path']}")


@app.command("explain-zero")
def explain_zero_command() -> None:
    from d365opps.diagnostics import DiagnosticsService

    with session_scope() as session:
        report = DiagnosticsService(session).explain_zero()
        typer.echo(json.dumps(report, indent=2, default=str))


@app.command("doctor")
def doctor_command(source: Annotated[list[str] | None, typer.Option("--source")] = None) -> None:
    with session_scope() as session:
        service = PipelineService(session)
        typer.echo(service.doctor(source_names=source))


@app.command("refresh-oracle-instructions")
def refresh_oracle_instructions_command() -> None:
    with session_scope() as session:
        service = PipelineService(session)
        result = service.refresh_oracle_instructions()
        typer.echo(f"Oracle instructions: {result['path']}")
        typer.echo(f"Latest verification: {result['latest_verification']}")
        typer.echo(f"Latest accountability: {result['latest_accountability']}")


@app.command("build-oracle-bundle")
def build_oracle_bundle_command() -> None:
    with session_scope() as session:
        service = PipelineService(session)
        result = service.build_oracle_bundle()
        typer.echo(f"Oracle bundle directory: {result['bundle_path']}")
        typer.echo(f"Oracle bundle zip: {result['zip_path']}")
        typer.echo(f"Self-check: {result['bundle_self_check_path']}")


@app.command("verify-oracle-bundle")
def verify_oracle_bundle_command() -> None:
    with session_scope() as session:
        service = PipelineService(session)
        result = service.verify_oracle_bundle()
        typer.echo(json.dumps(result, indent=2, default=str))


@app.command("render-run-verdict")
def render_run_verdict_command(
    run_id: Annotated[str | None, typer.Option("--run-id")] = None,
) -> None:
    with session_scope() as session:
        service = PipelineService(session)
        result = service.render_run_verdict(run_id=run_id)
        typer.echo(f"Accountability: {result['accountability_path']}")
        typer.echo(f"Verdict: {result['run_verdict_path']}")


@app.command("refresh")
def refresh_command(
    source: Annotated[list[str] | None, typer.Option("--source")] = None,
    region: Annotated[str | None, typer.Option("--region")] = None,
    since: Annotated[str | None, typer.Option("--since")] = None,
    include_disabled: Annotated[bool, typer.Option("--include-disabled")] = False,
    mode: Annotated[str, typer.Option("--mode")] = "incremental_sync",
) -> None:
    with session_scope() as session:
        service = PipelineService(session)
        results = service.refresh(
            source_names=source,
            region=region,
            since=_parse_since(since),
            include_disabled=include_disabled,
            mode=mode,
        )
        for item in results:
            typer.echo(item)


@app.command("bootstrap-backfill")
def bootstrap_backfill_command(
    source: Annotated[list[str] | None, typer.Option("--source")] = None,
    region: Annotated[str | None, typer.Option("--region")] = None,
    since: Annotated[str | None, typer.Option("--since")] = None,
    include_disabled: Annotated[bool, typer.Option("--include-disabled")] = False,
) -> None:
    with session_scope() as session:
        service = PipelineService(session)
        for item in service.bootstrap_backfill(
            source_names=source,
            region=region,
            since=_parse_since(since),
            include_disabled=include_disabled,
        ):
            typer.echo(item)


@app.command("reprocess")
def reprocess_command(document_id: str) -> None:
    with session_scope() as session:
        service = PipelineService(session)
        typer.echo(service.reprocess(document_id))


@app.command("rescore")
def rescore_command(
    document_id: Annotated[list[str] | None, typer.Option("--document-id")] = None,
    purge_invalidated: Annotated[bool, typer.Option("--purge-invalidated")] = True,
) -> None:
    with session_scope() as session:
        service = PipelineService(session)
        typer.echo(service.rescore_historical(document_ids=document_id, purge_invalidated=purge_invalidated))


@app.command("purge-demo")
def purge_demo_command() -> None:
    with session_scope() as session:
        service = PipelineService(session)
        typer.echo(service.purge_demo_records())


@app.command("approve")
def approve_command(candidate_id: str, reason: Annotated[str | None, typer.Option("--reason")] = None) -> None:
    with session_scope() as session:
        service = PipelineService(session)
        candidate = service.set_candidate_status(candidate_id, CandidateStatus.APPROVED, reason)
        typer.echo(f"Approved {candidate.id}")


@app.command("reject")
def reject_command(candidate_id: str, reason: Annotated[str | None, typer.Option("--reason")] = None) -> None:
    with session_scope() as session:
        service = PipelineService(session)
        candidate = service.set_candidate_status(candidate_id, CandidateStatus.REJECTED, reason)
        typer.echo(f"Rejected {candidate.id}")


@app.command("export")
def export_command(
    fmt: Annotated[str, typer.Option("--fmt")] = "both",
    country: Annotated[str | None, typer.Option("--country")] = None,
    evidence_grade: Annotated[str | None, typer.Option("--evidence-grade")] = None,
    app_family: Annotated[str | None, typer.Option("--app-family")] = None,
    service_type: Annotated[str | None, typer.Option("--service-type")] = None,
    signal_lane: Annotated[str | None, typer.Option("--signal-lane")] = None,
    recommended_action: Annotated[str | None, typer.Option("--recommended-action")] = None,
    route_to_market: Annotated[str | None, typer.Option("--route-to-market")] = None,
) -> None:
    with session_scope() as session:
        service = PipelineService(session)
        export_result = service.export(
            fmt=fmt,
            filters={
                key: value
                for key, value in {
                    "country": country,
                    "evidence_grade": evidence_grade,
                    "app_family": app_family,
                    "service_type": service_type,
                    "signal_lane": signal_lane,
                    "recommended_action": recommended_action,
                    "route_to_market": route_to_market,
                }.items()
                if value is not None
            },
        )
        typer.echo(f"Exported {len(export_result.files)} files to {export_result.directory}")


if __name__ == "__main__":
    app()
