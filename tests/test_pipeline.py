from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from d365opps.blob_store import LocalBlobStore
from d365opps.classifier import OpportunityClassifier
from d365opps.db import Base
from d365opps.enrichment import OpportunityEnricher
from d365opps.models import (
    AcquisitionMethod,
    CurrentActionabilityState,
    EvidenceRecord,
    IssueSeverity,
    Lane,
    OpportunityCandidate,
    ParsingMode,
    PublicAccessMode,
    RawDocument,
    RecommendedAction,
    RouteToMarket,
    SourceIssue,
    SourceRegistry,
)
from d365opps.pipeline import PipelineService
from d365opps.schemas import ExtractedEvidence, FetchBatch, FetchedDocument


class FakeAdapter:
    def fetch(self, source, since: datetime, cursor: str | None = None) -> FetchBatch:
        del source, since, cursor
        return FetchBatch(
            documents=[
                FetchedDocument(
                    external_id="doc-1",
                    canonical_url="https://example.com/rfp/1",
                    document_url="https://example.com/rfp/1",
                    content_type="application/json",
                    payload=b'{"status":"ok"}',
                )
            ]
        )

    def extract(self, source, raw_document, payload: bytes) -> list[ExtractedEvidence]:
        del source, raw_document, payload
        return [
            ExtractedEvidence(
                title="Dynamics 365 Business Central managed services RFP",
                summary="Buyer needs Business Central support and integration partner.",
                buyer_name="Example Health Trust",
                buyer_country="GB",
                procurement_type="Tender",
                publication_date=datetime.now(UTC),
                close_date=datetime.now(UTC),
                source_url="https://example.com/rfp/1",
                response_url="https://example.com/rfp/1/respond",
                contact_name="Jordan Smith",
                contact_email="jordan.smith@example.com",
                raw_excerpt="Business Central managed support, upgrades, and integration work.",
                procurement_id="BC-001",
            )
        ]


class FakeSourceFactory:
    def get(self, source_name: str):
        assert source_name == "fake_source"
        return FakeAdapter()


class MixedSourceFactory:
    def get(self, source_name: str):
        if source_name == "fake_source":
            return FakeAdapter()
        if source_name == "failing_source":
            return FailingAdapter()
        raise AssertionError(source_name)


class FailingAdapter:
    def fetch(self, source, since: datetime, cursor: str | None = None, query=None, budget=None) -> FetchBatch:
        del source, since, cursor, query, budget
        request = httpx.Request("GET", "https://example.com/throttled")
        response = httpx.Response(status_code=429, request=request)
        raise httpx.HTTPStatusError("429 Too Many Requests", request=request, response=response)

    def extract(self, source, raw_document, payload: bytes) -> list[ExtractedEvidence]:
        del source, raw_document, payload
        return []


class StubEnricher(OpportunityEnricher):
    def __init__(self) -> None:
        pass

    def enrich(self, *, buyer_name: str | None, source_url: str, contact_email: str | None, country: str | None):
        from d365opps.schemas import EnrichmentResult

        return EnrichmentResult(
            organization_name=buyer_name or "Unknown",
            normalized_name=(buyer_name or "unknown").lower(),
            website_domain="example.com",
            country=country,
            region="UK",
            enrichment_confidence=0.5,
            provenance={"source_url": source_url, "contact_email": contact_email},
        )


def make_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return SessionLocal()


def test_refresh_creates_candidate(tmp_path: Path) -> None:
    session = make_session()
    source = SourceRegistry(
        name="fake_source",
        description="Test source",
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

    results = service.refresh(source_names=["fake_source"], since=datetime.now(UTC))

    assert results[0]["status"] == "succeeded"
    candidates = session.query(OpportunityCandidate).all()
    assert len(candidates) == 1
    assert candidates[0].app_family in {"Business Central", "Dataverse / Power Platform"}


def test_failed_canary_creates_source_issue(tmp_path: Path, monkeypatch) -> None:
    session = make_session()
    source = SourceRegistry(
        name="ted",
        description="TED source",
        lane=Lane.OPPORTUNITY,
        tier=1,
        region="Europe",
        country="GB",
        enabled=True,
        cadence="daily",
        acquisition_method=AcquisitionMethod.API,
        parsing_mode=ParsingMode.JSON,
        endpoint="https://api.ted.europa.eu/v3/notices/search",
        config_json={},
    )
    session.add(source)
    session.commit()

    def fake_post(self, url, json=None):  # type: ignore[override]
        del self, json
        request = httpx.Request("POST", url)
        return httpx.Response(
            status_code=405,
            request=request,
            headers={"content-type": "application/json"},
            json={"error": "method not allowed"},
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    service = PipelineService(
        session,
        blob_store=LocalBlobStore(tmp_path / "blob"),
        classifier=OpportunityClassifier(),
        enricher=StubEnricher(),
        source_factory=FakeSourceFactory(),
    )
    service.canary_sweep(source_names=["ted"])

    issues = session.query(SourceIssue).all()
    assert len(issues) == 1
    assert issues[0].issue_code == "http_405"


def test_passing_canary_closes_stale_open_source_issues(tmp_path: Path, monkeypatch) -> None:
    session = make_session()
    source = SourceRegistry(
        name="ted",
        description="TED source",
        lane=Lane.OPPORTUNITY,
        tier=1,
        region="Europe",
        country="EU",
        enabled=True,
        cadence="daily",
        acquisition_method=AcquisitionMethod.API,
        parsing_mode=ParsingMode.JSON,
        endpoint="https://api.ted.europa.eu/v3/notices/search",
        config_json={},
    )
    session.add(source)
    session.flush()
    session.add(
        SourceIssue(
            source_id=source.id,
            crawl_run_id=None,
            issue_code="throttled_429",
            severity=IssueSeverity.HIGH,
            example_url=source.endpoint,
            impact_on_yield="Earlier run throttled.",
            recommended_remediation="Reduce page size.",
        )
    )
    session.commit()

    def fake_post(self, url, json=None):  # type: ignore[override]
        del self, json
        request = httpx.Request("POST", url)
        return httpx.Response(
            status_code=200,
            request=request,
            headers={"content-type": "application/json"},
            json={"notices": [{"publication-number": "123456-2026"}]},
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    service = PipelineService(
        session,
        blob_store=LocalBlobStore(tmp_path / "blob"),
        classifier=OpportunityClassifier(),
        enricher=StubEnricher(),
        source_factory=FakeSourceFactory(),
    )
    results = service.canary_sweep(source_names=["ted"])

    assert results[0]["status"] == "passed"
    issues = session.query(SourceIssue).all()
    assert len(issues) == 1
    assert issues[0].state == "closed"
    assert session.get(SourceRegistry, source.id).health_status.value == "healthy"


def test_refresh_continues_when_one_source_fails(tmp_path: Path) -> None:
    session = make_session()
    session.add_all(
        [
            SourceRegistry(
                name="fake_source",
                description="Working source",
                lane=Lane.OPPORTUNITY,
                tier=1,
                region="UK",
                country="GB",
                enabled=True,
                cadence="daily",
                acquisition_method=AcquisitionMethod.API,
                parsing_mode=ParsingMode.JSON,
                endpoint="https://example.com/ok",
                config_json={},
            ),
            SourceRegistry(
                name="failing_source",
                description="Failing source",
                lane=Lane.OPPORTUNITY,
                tier=1,
                region="UK",
                country="GB",
                enabled=True,
                cadence="daily",
                acquisition_method=AcquisitionMethod.API,
                parsing_mode=ParsingMode.JSON,
                endpoint="https://example.com/fail",
                config_json={},
            ),
        ]
    )
    session.commit()

    service = PipelineService(
        session,
        blob_store=LocalBlobStore(tmp_path / "blob"),
        classifier=OpportunityClassifier(),
        enricher=StubEnricher(),
        source_factory=MixedSourceFactory(),
    )

    results = service.refresh(source_names=["failing_source", "fake_source"], since=datetime.now(UTC))

    assert len(results) == 2
    statuses = {item["source"]: item["status"] for item in results}
    assert statuses["failing_source"] == "failed"
    assert statuses["fake_source"] == "succeeded"
    assert session.query(OpportunityCandidate).count() == 1
    issue = session.query(SourceIssue).filter(SourceIssue.source_id.is_not(None)).one()
    assert issue.issue_code == "throttled_429"


def test_upsert_evidence_updates_existing_row_when_title_changes(tmp_path: Path) -> None:
    session = make_session()
    source = SourceRegistry(
        name="fake_source",
        description="Test source",
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
    session.flush()
    raw_document = RawDocument(
        source_id=source.id,
        crawl_run_id=None,
        external_id="doc-1",
        canonical_url="https://example.com/notice/1",
        document_url="https://example.com/notice/1",
        content_type="application/json",
        checksum="abc",
        blob_path="blob/doc-1.json",
        metadata_json={},
    )
    session.add(raw_document)
    session.commit()

    service = PipelineService(
        session,
        blob_store=LocalBlobStore(tmp_path / "blob"),
        classifier=OpportunityClassifier(),
        enricher=StubEnricher(),
        source_factory=FakeSourceFactory(),
    )

    original = ExtractedEvidence(
        title="Hungarian only title",
        summary="summary",
        buyer_name="Buyer",
        buyer_country="GB",
        source_url="https://example.com/notice/1",
        response_url="https://example.com/notice/1",
        procurement_id="ABC-123",
    )
    updated = original.model_copy(update={"title": "English title"})

    first = service._upsert_evidence(source, raw_document, original)
    second = service._upsert_evidence(source, raw_document, updated)
    session.flush()

    assert first.id == second.id
    assert session.query(EvidenceRecord).count() == 1
    assert second.title == "English title"


def test_upsert_evidence_merges_same_procurement_across_raw_documents(tmp_path: Path) -> None:
    session = make_session()
    source = SourceRegistry(
        name="fake_source",
        description="Test source",
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
    session.flush()
    raw_document_a = RawDocument(
        source_id=source.id,
        crawl_run_id=None,
        external_id="doc-a",
        canonical_url="https://example.com/notice/1",
        document_url="https://example.com/notice/1",
        content_type="application/json",
        checksum="abc",
        blob_path="blob/doc-a.json",
        metadata_json={},
    )
    raw_document_b = RawDocument(
        source_id=source.id,
        crawl_run_id=None,
        external_id="doc-b",
        canonical_url="https://example.com/notice/1",
        document_url="https://example.com/notice/1",
        content_type="application/json",
        checksum="def",
        blob_path="blob/doc-b.json",
        metadata_json={},
    )
    session.add_all([raw_document_a, raw_document_b])
    session.commit()

    service = PipelineService(
        session,
        blob_store=LocalBlobStore(tmp_path / "blob"),
        classifier=OpportunityClassifier(),
        enricher=StubEnricher(),
        source_factory=FakeSourceFactory(),
    )

    original = ExtractedEvidence(
        title="Original title",
        summary="summary",
        buyer_name="Buyer",
        buyer_country="GB",
        source_url="https://example.com/notice/1",
        response_url="https://example.com/notice/1",
        procurement_id="ABC-123",
    )
    updated = original.model_copy(update={"title": "Updated title"})

    first = service._upsert_evidence(source, raw_document_a, original)
    second = service._upsert_evidence(source, raw_document_b, updated)
    session.flush()

    assert first.id == second.id
    assert session.query(EvidenceRecord).count() == 1
    assert second.raw_document_id == raw_document_a.id
    assert second.title == "Updated title"


def test_upsert_candidate_relinks_to_latest_evidence(tmp_path: Path) -> None:
    session = make_session()
    source = SourceRegistry(
        name="fake_source",
        description="Test source",
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
    session.flush()
    raw_document_a = RawDocument(
        source_id=source.id,
        crawl_run_id=None,
        external_id="doc-a",
        canonical_url="https://example.com/notice/1",
        document_url="https://example.com/notice/1",
        content_type="application/json",
        checksum="abc",
        blob_path="blob/doc-a.json",
        metadata_json={},
    )
    raw_document_b = RawDocument(
        source_id=source.id,
        crawl_run_id=None,
        external_id="doc-b",
        canonical_url="https://example.com/notice/1",
        document_url="https://example.com/notice/1",
        content_type="application/json",
        checksum="def",
        blob_path="blob/doc-b.json",
        metadata_json={},
    )
    session.add_all([raw_document_a, raw_document_b])
    session.flush()

    evidence_a = EvidenceRecord(
        source_id=source.id,
        raw_document_id=raw_document_a.id,
        record_type="notice",
        title="Dynamics 365 upgrade",
        buyer_name="Buyer",
        buyer_country="GB",
        source_url="https://example.com/notice/1",
        response_url="https://example.com/notice/1",
        procurement_id="ABC-123",
        publication_date=datetime.now(UTC).replace(tzinfo=None),
        close_date=None,
        public_access_mode=PublicAccessMode.PUBLIC,
        current_actionability_state=CurrentActionabilityState.OPEN_BID,
        recommended_action=RecommendedAction.BID_NOW,
        route_to_market=RouteToMarket.FORMAL_BID,
        matched_positive_terms_json=["dynamics 365"],
        language_status="english_ready",
        english_sufficiency_score=0.72,
        seller_readable_title_en_flag=True,
        summary="Need Dynamics 365 services",
        raw_excerpt="Need Dynamics 365 services",
        query_family="formal_procurement",
        source_trust=0.9,
    )
    evidence_b = EvidenceRecord(
        source_id=source.id,
        raw_document_id=raw_document_b.id,
        record_type="notice",
        title="Dynamics 365 upgrade",
        buyer_name="Buyer",
        buyer_country="GB",
        source_url="https://example.com/notice/1",
        response_url="https://example.com/notice/1",
        procurement_id="ABC-123",
        publication_date=datetime.now(UTC).replace(tzinfo=None),
        close_date=datetime.now(UTC).replace(tzinfo=None),
        public_access_mode=PublicAccessMode.PUBLIC,
        current_actionability_state=CurrentActionabilityState.OPEN_BID,
        recommended_action=RecommendedAction.BID_NOW,
        route_to_market=RouteToMarket.FORMAL_BID,
        matched_positive_terms_json=["dynamics 365"],
        language_status="english_ready",
        english_sufficiency_score=0.81,
        seller_readable_title_en_flag=True,
        summary="Need Dynamics 365 services",
        raw_excerpt="Need Dynamics 365 services",
        query_family="formal_procurement",
        source_trust=0.9,
    )
    session.add_all([evidence_a, evidence_b])
    session.flush()

    service = PipelineService(
        session,
        blob_store=LocalBlobStore(tmp_path / "blob"),
        classifier=OpportunityClassifier(),
        enricher=StubEnricher(),
        source_factory=FakeSourceFactory(),
    )
    organization = service._upsert_organization(
        StubEnricher().enrich(
            buyer_name="Buyer",
            source_url="https://example.com/notice/1",
            contact_email=None,
            country="GB",
        )
    )
    extracted = ExtractedEvidence(
        title="Dynamics 365 upgrade",
        summary="Need Dynamics 365 services",
        buyer_name="Buyer",
        buyer_country="GB",
        source_url="https://example.com/notice/1",
        response_url="https://example.com/notice/1",
        procurement_id="ABC-123",
        publication_date=datetime.now(UTC),
        close_date=datetime.now(UTC),
        matched_positive_terms=["dynamics 365"],
        language_status="english_ready",
        english_sufficiency_score=0.81,
        seller_readable_title_en_flag=True,
        source_trust=0.9,
        signal_lane="formal_procurement",
        recommended_action="bid_now",
        route_to_market="formal_bid",
        public_access_mode="public",
        query_family="formal_procurement",
        retrieval_score=82.0,
        formal_opportunity_score=80.0,
        pre_position_score=10.0,
        account_intent_score=5.0,
        install_base_trigger_score=0.0,
        service_fit_score=75.0,
        buyer_quality_score=70.0,
        corroboration_score=65.0,
    )
    draft = service.classifier.classify(extracted, source.lane.value, default_region=source.region).opportunity
    assert draft is not None

    candidate = service._upsert_candidate(evidence_a, organization, draft, source=source)
    updated = service._upsert_candidate(evidence_b, organization, draft, source=source)
    session.flush()

    assert candidate.id == updated.id
    assert updated.evidence_record_id == evidence_b.id
