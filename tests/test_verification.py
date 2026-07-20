from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from d365opps.blob_store import LocalBlobStore
from d365opps.classifier import OpportunityClassifier
from d365opps.config import get_settings
from d365opps.db import Base
from d365opps.diagnostics import DiagnosticsService
from d365opps.enrichment import OpportunityEnricher
from d365opps.models import (
    AcquisitionMethod,
    JobRun,
    Lane,
    ParsingMode,
    PipelineEvent,
    QueryExecution,
    SourceFetchEvent,
    SourceRegistry,
)
from d365opps.oracle_bundle import OracleBundleBuilder
from d365opps.pipeline import PipelineService
from d365opps.schemas import EnrichmentResult, ExtractedEvidence, FetchBatch, FetchedDocument
from d365opps.verification import VerificationService


class FakeAdapter:
    def fetch(self, source, since: datetime, cursor: str | None = None, query=None, budget=None) -> FetchBatch:
        del source, since, cursor, query, budget
        return FetchBatch(
            documents=[
                FetchedDocument(
                    external_id="verification-doc",
                    canonical_url="https://example.com/opportunity/verification",
                    document_url="https://example.com/opportunity/verification",
                    content_type="application/json",
                    payload=b'{"status":"ok"}',
                )
            ]
        )

    def extract(self, source, raw_document, payload: bytes) -> list[ExtractedEvidence]:
        del source, raw_document, payload
        return [
            ExtractedEvidence(
                title="Dynamics 365 Customer Service implementation support tender",
                summary="Buyer needs Microsoft Dynamics 365 Customer Service implementation and managed support.",
                buyer_name="Verification Authority",
                buyer_country="GB",
                procurement_type="Tender",
                publication_date=datetime.now(UTC),
                close_date=datetime.now(UTC) + timedelta(days=30),
                source_url="https://example.com/opportunity/verification",
                response_url="https://example.com/opportunity/verification/respond",
                raw_excerpt="Microsoft Dynamics 365 Customer Service implementation and support services.",
                procurement_id="VERIFY-001",
            )
        ]


class FakeSourceFactory:
    def get(self, source_name: str):
        assert source_name == "verification_source"
        return FakeAdapter()


class StubEnricher(OpportunityEnricher):
    def __init__(self) -> None:
        pass

    def enrich(self, *, buyer_name: str | None, source_url: str, contact_email: str | None, country: str | None):
        del contact_email
        return EnrichmentResult(
            organization_name=buyer_name or "Unknown",
            normalized_name=(buyer_name or "unknown").lower(),
            website_domain="example.com",
            country=country,
            region="UK",
            enrichment_confidence=0.5,
            provenance={"source_url": source_url},
        )


def make_session(tmp_path: Path) -> Session:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'verification.db'}", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return SessionLocal()


def test_verification_bundle_contains_forensic_artifacts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("D365_OPPS_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("D365_OPPS_LOG_ROOT", str(tmp_path / "logs"))
    monkeypatch.setenv("D365_OPPS_SAM_GOV_API_KEY", "super-secret-key")
    get_settings.cache_clear()

    session = make_session(tmp_path)
    source = SourceRegistry(
        name="verification_source",
        description="Verification source",
        lane=Lane.OPPORTUNITY,
        tier=1,
        region="UK",
        country="GB",
        enabled=True,
        cadence="daily",
        acquisition_method=AcquisitionMethod.API,
        parsing_mode=ParsingMode.JSON,
        endpoint="https://example.com",
        config_json={},
    )
    session.add(source)
    session.commit()

    service = PipelineService(
        session,
        blob_store=LocalBlobStore(tmp_path / "blob"),
        classifier=OpportunityClassifier(),
        enricher=StubEnricher(),
        source_factory=FakeSourceFactory(),
    )
    service.refresh(source_names=["verification_source"], since=datetime.now(UTC))
    session.commit()

    bundle = VerificationService(session).latest_bundle()
    bundle_path = Path(bundle["bundle_path"])
    assert bundle_path.name == "latest-fixture"
    assert (bundle_path / "manifest.json").exists()
    assert (bundle_path / "pipeline_events.ndjson").exists()
    assert (bundle_path / "fetch_events.ndjson").exists()
    assert (bundle_path / "dataset_diagnosis.json").exists()
    assert (bundle_path / "ROOT_CAUSE_REPORT.md").exists()
    accountability_path = Path(bundle["latest_accountability_path"])
    assert accountability_path.name == "latest-fixture"
    assert (accountability_path / "bundle-manifest.json").exists()
    assert (accountability_path / "pitchability_report.md").exists()
    assert (accountability_path / "run_verdict.md").exists()
    assert (accountability_path / "lead_funnel_report.md").exists()
    assert (accountability_path / "cross_surface_truth_report.json").exists()
    assert (accountability_path / "metric_catalog.json").exists()
    assert (accountability_path / "repo_harness_compliance_report.md").exists()
    assert (accountability_path / "dead_weight_audit.md").exists()
    assert (accountability_path / "before_after_recall_report.md").exists()
    assert (accountability_path / "current_pipeline_truth_report.md").exists()
    assert (accountability_path / "official_regression_truth_report.md").exists()
    assert (accountability_path / "source_gap_report.md").exists()
    assert (accountability_path / "source_productionization_report.md").exists()
    assert (accountability_path / "source_yield_matrix.json").exists()
    assert (accountability_path / "lead_age_distribution.json").exists()
    assert (accountability_path / "bundle_lineage.json").exists()
    assert (accountability_path / "truth_consistency_report.json").exists()

    manifest = json.loads((bundle_path / "manifest.json").read_text(encoding="utf-8"))
    assert "pipeline_events.ndjson" in manifest["files"]
    assert not (tmp_path / "artifacts" / "verification" / "latest-live-public").exists()
    admissibility = json.loads((accountability_path / "canonical_bundle_admissibility_report.json").read_text(encoding="utf-8"))
    assert admissibility["run_kind"] == "fixture"
    assert admissibility["oracle_admissible"] is False
    pipeline_events = (bundle_path / "pipeline_events.ndjson").read_text(encoding="utf-8")
    assert "job.start" in pipeline_events
    assert "source.run.start" in pipeline_events
    environment_report = (bundle_path / "environment.redacted.json").read_text(encoding="utf-8")
    assert "super-secret-key" not in environment_report
    assert "<redacted>" in environment_report

    job = session.execute(select(JobRun).order_by(JobRun.started_at.desc())).scalars().first()
    assert job is not None
    assert job.verification_bundle_path
    assert job.verification_bundle_sha256


def test_oracle_bundle_refuses_fixture_only_outputs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("D365_OPPS_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("D365_OPPS_LOG_ROOT", str(tmp_path / "logs"))
    get_settings.cache_clear()

    session = make_session(tmp_path)
    source = SourceRegistry(
        name="verification_source",
        description="Verification source",
        lane=Lane.OPPORTUNITY,
        tier=1,
        region="UK",
        country="GB",
        enabled=True,
        cadence="daily",
        acquisition_method=AcquisitionMethod.API,
        parsing_mode=ParsingMode.JSON,
        endpoint="https://example.com",
        config_json={},
    )
    session.add(source)
    session.commit()

    service = PipelineService(
        session,
        blob_store=LocalBlobStore(tmp_path / "blob"),
        classifier=OpportunityClassifier(),
        enricher=StubEnricher(),
        source_factory=FakeSourceFactory(),
    )
    service.refresh(source_names=["verification_source"], since=datetime.now(UTC))
    session.commit()
    service.refresh_oracle_instructions()

    builder = OracleBundleBuilder()
    with pytest.raises(RuntimeError, match="No admissible live-public"):
        builder.build()


def test_render_run_verdict_writes_latest_verdict_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("D365_OPPS_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("D365_OPPS_LOG_ROOT", str(tmp_path / "logs"))
    get_settings.cache_clear()

    session = make_session(tmp_path)
    source = SourceRegistry(
        name="verification_source",
        description="Verification source",
        lane=Lane.OPPORTUNITY,
        tier=1,
        region="UK",
        country="GB",
        enabled=True,
        cadence="daily",
        acquisition_method=AcquisitionMethod.API,
        parsing_mode=ParsingMode.JSON,
        endpoint="https://example.com",
        config_json={},
    )
    session.add(source)
    session.commit()

    service = PipelineService(
        session,
        blob_store=LocalBlobStore(tmp_path / "blob"),
        classifier=OpportunityClassifier(),
        enricher=StubEnricher(),
        source_factory=FakeSourceFactory(),
    )
    service.refresh(source_names=["verification_source"], since=datetime.now(UTC))
    session.commit()

    result = service.render_run_verdict()
    assert Path(result["run_verdict_path"]).exists()
    assert Path(result["run_verdict_json_path"]).exists()


def test_trace_ids_propagate_into_fetch_query_and_events(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("D365_OPPS_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("D365_OPPS_LOG_ROOT", str(tmp_path / "logs"))
    get_settings.cache_clear()

    session = make_session(tmp_path)
    source = SourceRegistry(
        name="verification_source",
        description="Verification source",
        lane=Lane.OPPORTUNITY,
        tier=1,
        region="UK",
        country="GB",
        enabled=True,
        cadence="daily",
        acquisition_method=AcquisitionMethod.API,
        parsing_mode=ParsingMode.JSON,
        endpoint="https://example.com",
        config_json={},
    )
    session.add(source)
    session.commit()

    service = PipelineService(
        session,
        blob_store=LocalBlobStore(tmp_path / "blob"),
        classifier=OpportunityClassifier(),
        enricher=StubEnricher(),
        source_factory=FakeSourceFactory(),
    )
    service.refresh(source_names=["verification_source"], since=datetime.now(UTC))
    session.commit()

    fetch_event = session.execute(select(SourceFetchEvent)).scalars().first()
    query_execution = session.execute(select(QueryExecution)).scalars().first()
    pipeline_event = session.execute(select(PipelineEvent)).scalars().first()

    assert fetch_event is not None and fetch_event.trace_id and fetch_event.request_id
    assert query_execution is not None and query_execution.trace_id == fetch_event.trace_id
    assert pipeline_event is not None and pipeline_event.trace_id == fetch_event.trace_id


def test_explain_zero_reports_root_cause_without_live_ui(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("D365_OPPS_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("D365_OPPS_LOG_ROOT", str(tmp_path / "logs"))
    get_settings.cache_clear()

    session = make_session(tmp_path)
    source = SourceRegistry(
        name="verification_source",
        description="Verification source",
        lane=Lane.OPPORTUNITY,
        tier=1,
        region="UK",
        country="GB",
        enabled=True,
        cadence="daily",
        acquisition_method=AcquisitionMethod.API,
        parsing_mode=ParsingMode.JSON,
        endpoint="https://example.com",
        config_json={},
    )
    session.add(source)
    session.commit()

    report = DiagnosticsService(session).explain_zero()
    causes = [row["cause"] for row in report["top_root_causes"]]
    assert report["live_records"] == 0
    assert "no bootstrap backfill completed" in causes
    assert "no successful fetches recorded" in causes

    bundle = VerificationService(session).generate_bundle()
    root_cause_report = Path(bundle["latest_path"]) / "ROOT_CAUSE_REPORT.md"
    assert root_cause_report.exists()
    content = root_cause_report.read_text(encoding="utf-8")
    assert "no bootstrap backfill completed" in content


def test_explain_zero_prod_ready_counts_only_production_ready_sources(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("D365_OPPS_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("D365_OPPS_LOG_ROOT", str(tmp_path / "logs"))
    get_settings.cache_clear()

    session = make_session(tmp_path)
    source = SourceRegistry(
        name="prod-ready-check",
        description="Verification source",
        lane=Lane.OPPORTUNITY,
        tier=1,
        region="UK",
        country="GB",
        enabled=True,
        cadence="daily",
        acquisition_method=AcquisitionMethod.API,
        parsing_mode=ParsingMode.JSON,
        endpoint="https://example.com",
        config_json={},
    )
    session.add(source)
    session.commit()

    report = DiagnosticsService(session).explain_zero()
    assert report["enabled_sources"] == 1
    assert report["parser_implemented_enabled"] == 1
    assert report["prod_ready_enabled"] == 0


def test_harness_map_schema_validation_report_passes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("D365_OPPS_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("D365_OPPS_LOG_ROOT", str(tmp_path / "logs"))
    get_settings.cache_clear()

    session = make_session(tmp_path)
    report = VerificationService(session)._harness_schema_validation_report()
    assert report["status"] == "pass"
    assert report["error_count"] == 0
