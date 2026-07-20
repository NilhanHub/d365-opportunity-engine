from __future__ import annotations

from datetime import UTC, datetime

from d365opps.classifier import OpportunityClassifier
from d365opps.dedupe import OpportunityClusterer
from d365opps.schemas import ExtractedEvidence


def _draft(procurement_id: str | None = None):
    classifier = OpportunityClassifier()
    evidence = ExtractedEvidence(
        title="Dynamics 365 Finance implementation",
        summary="Finance transformation program.",
        buyer_name="Example Ministry",
        buyer_country="GB",
        procurement_type="Tender",
        publication_date=datetime.now(UTC),
        close_date=datetime.now(UTC),
        source_url="https://example.com/notice",
        response_url="https://example.com/respond",
        procurement_id=procurement_id,
        raw_excerpt="Dynamics 365 Finance and Supply Chain Management rollout.",
    )
    return classifier.classify(evidence, source_lane="opportunity").opportunity


def test_cluster_key_prefers_procurement_id() -> None:
    clusterer = OpportunityClusterer()
    draft = _draft(procurement_id="PROC-1")

    assert draft is not None
    assert clusterer.cluster_key(draft) == "procurement:proc-1"


def test_cluster_similarity_uses_title_and_buyer() -> None:
    clusterer = OpportunityClusterer()
    draft = _draft()

    assert draft is not None
    assert clusterer.is_same_cluster(draft, "Dynamics 365 Finance implementation", "Example Ministry")
