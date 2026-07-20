from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from d365opps.blob_store import LocalBlobStore
from d365opps.classifier import OpportunityClassifier
from d365opps.db import Base
from d365opps.enrichment import OpportunityEnricher
from d365opps.models import AcquisitionMethod, Lane, ParsingMode, SourceRegistry
from d365opps.pipeline import PipelineService
from d365opps.schemas import EnrichmentResult, ExtractedEvidence, FetchBatch, FetchedDocument


class RadarAdapter:
    def fetch(self, source, since: datetime, cursor: str | None = None) -> FetchBatch:
        del source, since, cursor
        return FetchBatch(
            documents=[
                FetchedDocument(
                    external_id="radar-doc",
                    canonical_url="https://example.com/radar",
                    document_url="https://example.com/radar",
                    content_type="application/json",
                    payload=b'{"ok":true}',
                )
            ]
        )

    def extract(self, source, raw_document, payload: bytes) -> list[ExtractedEvidence]:
        del source, raw_document, payload
        return [
            ExtractedEvidence(
                title="Dynamics 365 Finance implementation tender",
                summary="Tender for Dynamics 365 Finance rollout and support.",
                buyer_name="City Council",
                buyer_country="GB",
                procurement_type="Tender",
                publication_date=datetime.now(UTC),
                close_date=datetime.now(UTC),
                source_url="https://example.com/formal",
                response_url="https://example.com/formal/respond",
                raw_excerpt="Dynamics 365 Finance implementation and integration.",
                procurement_id="FORM-1",
            ),
            ExtractedEvidence(
                title="Dynamics NAV modernization roadmap",
                summary="Board paper for Navision to Business Central migration.",
                buyer_name="City Council",
                buyer_country="GB",
                publication_date=datetime.now(UTC),
                source_url="https://example.com/trigger",
                raw_excerpt="Legacy Dynamics NAV on-premises estate needs migration and managed support.",
            ),
        ]


class RadarSourceFactory:
    def get(self, source_name: str):
        assert source_name == "radar_source"
        return RadarAdapter()


class StubEnricher(OpportunityEnricher):
    def __init__(self) -> None:
        pass

    def enrich(self, *, buyer_name: str | None, source_url: str, contact_email: str | None, country: str | None):
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


def test_coverage_and_lane_reports_include_new_lanes(tmp_path: Path) -> None:
    session = make_session()
    source = SourceRegistry(
        name="radar_source",
        description="Radar source",
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
        source_factory=RadarSourceFactory(),
    )
    service.refresh(source_names=["radar_source"], since=datetime.now(UTC))

    coverage = service.coverage_report()
    lanes = service.lane_report()

    assert coverage["records_by_lane"]["formal_procurement"] >= 1
    assert coverage["records_by_lane"]["install_base_trigger"] >= 1
    assert any(item["signal_lane"] == "formal_procurement" for item in lanes)
    assert any(item["signal_lane"] == "install_base_trigger" for item in lanes)
