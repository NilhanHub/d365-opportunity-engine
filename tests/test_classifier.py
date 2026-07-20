from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from d365opps.classifier import OpportunityClassifier
from d365opps.schemas import ExtractedEvidence


def test_classifier_promotes_actionable_opportunity() -> None:
    classifier = OpportunityClassifier()
    evidence = ExtractedEvidence(
        title="Dynamics 365 Customer Service implementation tender",
        summary="Public sector procurement for Dynamics 365 Customer Service and Power Platform support.",
        buyer_name="Example Borough Council",
        buyer_country="GB",
        procurement_type="Tender",
        publication_date=datetime.now(UTC),
        close_date=datetime.now(UTC) + timedelta(days=10),
        budget_value=Decimal("250000"),
        budget_currency="GBP",
        source_url="https://buyer.example/tender/1",
        response_url="https://buyer.example/tender/1/respond",
        raw_excerpt="Request for proposal for Dynamics 365 implementation partner.",
        tags=["rfp", "public_sector"],
        procurement_id="ABC-123",
    )

    result = classifier.classify(evidence, source_lane="opportunity", default_region="UK")

    assert result.opportunity is not None
    assert result.opportunity.evidence_grade == "A1"
    assert result.opportunity.app_family in {"Customer Service", "Dataverse / Power Platform"}
    assert result.opportunity.scorecard.recommendation in {"bid_now", "pre_position", "outreach_now"}
    assert result.signal is None


def test_classifier_routes_low_confidence_items_to_signal() -> None:
    classifier = OpportunityClassifier()
    evidence = ExtractedEvidence(
        title="General digital transformation article",
        summary="Commentary on cloud adoption without a buyer or response path.",
        source_url="https://example.com/article",
    )

    result = classifier.classify(evidence, source_lane="signal")

    assert result.signal is not None
    assert result.opportunity is None
    assert result.signal.confidence >= 0.1
