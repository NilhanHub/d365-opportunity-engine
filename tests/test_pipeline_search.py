from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from d365opps.blob_store import LocalBlobStore
from d365opps.classifier import OpportunityClassifier
from d365opps.db import Base
from d365opps.enrichment import OpportunityEnricher
from d365opps.models import (
    AcquisitionMethod,
    ExclusionAudit,
    Lane,
    OpportunityCandidate,
    ParsingMode,
    SourceRegistry,
)
from d365opps.pipeline import PipelineService
from d365opps.schemas import ExtractedEvidence, FetchBatch, FetchedDocument


class MixedAdapter:
    def fetch(self, source, since: datetime, cursor: str | None = None, query=None, budget=None) -> FetchBatch:
        del source, since, cursor, query, budget
        return FetchBatch(
            documents=[
                FetchedDocument(
                    external_id="mixed-doc",
                    canonical_url="https://example.com/mixed",
                    document_url="https://example.com/mixed",
                    content_type="application/json",
                    payload=b'{"status":"ok"}',
                )
            ]
        )

    def extract(self, source, raw_document, payload: bytes) -> list[ExtractedEvidence]:
        del source, raw_document, payload
        return [
            ExtractedEvidence(
                title="Dynamics 365 Field Service managed support tender",
                summary="Public procurement for Dynamics 365 Field Service support, upgrades, and integrations.",
                buyer_name="City Utilities",
                buyer_country="GB",
                procurement_type="Tender",
                publication_date=datetime.now(UTC),
                close_date=datetime.now(UTC) + timedelta(days=14),
                source_url="https://example.com/opportunity/1",
                response_url="https://example.com/opportunity/1/respond",
                raw_excerpt="Microsoft Dynamics 365 Field Service support services.",
                procurement_id="FS-001",
            ),
            ExtractedEvidence(
                title="Enterprise ERP replacement programme",
                summary="Generic ERP consultancy procurement.",
                buyer_name="City Utilities",
                buyer_country="GB",
                procurement_type="Tender",
                publication_date=datetime.now(UTC),
                close_date=datetime.now(UTC),
                source_url="https://example.com/opportunity/2",
                response_url="https://example.com/opportunity/2/respond",
                raw_excerpt="ERP implementation and maintenance.",
            ),
        ]


class MixedSourceFactory:
    def get(self, source_name: str):
        assert source_name == "mixed_source"
        return MixedAdapter()


class FalsePositiveAdapter:
    def fetch(self, source, since: datetime, cursor: str | None = None, query=None, budget=None) -> FetchBatch:
        del source, since, cursor, query, budget
        return FetchBatch(
            documents=[
                FetchedDocument(
                    external_id="fp-1",
                    canonical_url="https://example.com/boardwalk",
                    document_url="https://example.com/boardwalk",
                    content_type="application/json",
                    payload=b'{"status":"ok"}',
                ),
                FetchedDocument(
                    external_id="fp-2",
                    canonical_url="https://example.com/hr-upgrade",
                    document_url="https://example.com/hr-upgrade",
                    content_type="application/json",
                    payload=b'{"status":"ok"}',
                ),
            ]
        )

    def extract(self, source, raw_document, payload: bytes) -> list[ExtractedEvidence]:
        del source, payload
        if raw_document.external_id == "fp-1":
            return [
                ExtractedEvidence(
                    title="Abbey Park, Pershore - Boardwalk Replacement",
                    summary="Boardwalk replacement contract with site works and timber supply.",
                    buyer_name="Pershore Council",
                    buyer_country="GB",
                    procurement_type="Tender",
                    publication_date=datetime.now(UTC),
                    close_date=datetime.now(UTC),
                    source_url="https://example.com/boardwalk",
                    response_url="https://example.com/boardwalk/respond",
                    raw_excerpt="Boardwalk replacement works and construction services.",
                    procurement_id="FP-001",
                )
            ]
        return [
            ExtractedEvidence(
                title="Homes England - Upgrade to HR System",
                summary="Upgrade to the internal HR system and supporting implementation services.",
                buyer_name="Homes England",
                buyer_country="GB",
                procurement_type="Tender",
                publication_date=datetime.now(UTC),
                close_date=datetime.now(UTC),
                source_url="https://example.com/hr-upgrade",
                response_url="https://example.com/hr-upgrade/respond",
                raw_excerpt="HR system upgrade, implementation partner, testing, and support.",
                procurement_id="FP-002",
            )
        ]


class FalsePositiveSourceFactory:
    def get(self, source_name: str):
        assert source_name == "false_positive_source"
        return FalsePositiveAdapter()


class DuplicateD365Adapter:
    def fetch(self, source, since: datetime, cursor: str | None = None, query=None, budget=None) -> FetchBatch:
        del source, since, cursor, query, budget
        return FetchBatch(
            documents=[
                FetchedDocument(
                    external_id="dup-1",
                    canonical_url="https://example.com/d365-1",
                    document_url="https://example.com/d365-1",
                    content_type="application/json",
                    payload=b'{"status":"ok"}',
                ),
                FetchedDocument(
                    external_id="dup-2",
                    canonical_url="https://example.com/d365-2",
                    document_url="https://example.com/d365-2",
                    content_type="application/json",
                    payload=b'{"status":"ok"}',
                ),
            ]
        )

    def extract(self, source, raw_document, payload: bytes) -> list[ExtractedEvidence]:
        del source, raw_document, payload
        return [
            ExtractedEvidence(
                title="Dynamics 365 Finance implementation and managed support",
                summary="Buyer requires Microsoft Dynamics 365 Finance implementation, migration, and AMS.",
                buyer_name="Regional Water Authority",
                buyer_country="GB",
                procurement_type="Tender",
                publication_date=datetime.now(UTC),
                close_date=datetime.now(UTC) + timedelta(days=14),
                source_url="https://example.com/d365",
                response_url="https://example.com/d365/respond",
                raw_excerpt="Microsoft Dynamics 365 Finance rollout, integration, and support services.",
                procurement_id="D365-001",
            )
        ]


class DuplicateD365SourceFactory:
    def get(self, source_name: str):
        assert source_name == "duplicate_source"
        return DuplicateD365Adapter()


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


def test_pipeline_records_retrieval_fields_and_exclusions(tmp_path: Path) -> None:
    session = make_session()
    source = SourceRegistry(
        name="mixed_source",
        description="Test source",
        lane=Lane.OPPORTUNITY,
        tier=1,
        region="UK",
        country="GB",
        enabled=True,
        is_seed=True,
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
        source_factory=MixedSourceFactory(),
    )

    service.refresh(source_names=["mixed_source"], since=datetime.now(UTC))

    candidates = session.query(OpportunityCandidate).all()
    exclusions = session.query(ExclusionAudit).all()

    assert len(candidates) == 1
    assert candidates[0].retrieval_score >= 40
    assert candidates[0].matched_positive_terms_json
    assert candidates[0].signal_lane.value == "formal_procurement"
    assert candidates[0].recommended_action.value == "bid_now"
    assert len(exclusions) == 1
    assert exclusions[0].reason in {"missing_microsoft_anchor", "no_d365_anchor"}


def test_pipeline_rejects_known_non_d365_false_positives(tmp_path: Path) -> None:
    session = make_session()
    source = SourceRegistry(
        name="false_positive_source",
        description="False positive source",
        lane=Lane.OPPORTUNITY,
        tier=1,
        region="UK",
        country="GB",
        enabled=True,
        is_seed=True,
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
        source_factory=FalsePositiveSourceFactory(),
    )

    service.refresh(source_names=["false_positive_source"], since=datetime.now(UTC))

    assert session.query(OpportunityCandidate).count() == 0
    reasons = {row.reason for row in session.query(ExclusionAudit).all()}
    assert reasons <= {"no_d365_anchor", "missing_microsoft_anchor"}
    assert reasons


def test_pipeline_collapses_duplicate_live_opportunities(tmp_path: Path) -> None:
    session = make_session()
    source = SourceRegistry(
        name="duplicate_source",
        description="Duplicate source",
        lane=Lane.OPPORTUNITY,
        tier=1,
        region="UK",
        country="GB",
        enabled=True,
        is_seed=True,
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
        source_factory=DuplicateD365SourceFactory(),
    )

    service.refresh(source_names=["duplicate_source"], since=datetime.now(UTC))

    candidates = session.query(OpportunityCandidate).all()
    assert len(candidates) == 1
    assert candidates[0].procurement_id == "D365-001"
