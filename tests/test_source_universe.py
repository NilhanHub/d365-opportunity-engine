from __future__ import annotations

import json
from pathlib import Path

from d365opps.source_universe import AttemptResult, SourceUniverseService


def test_static_source_universe_exceeds_300(tmp_path: Path) -> None:
    service = SourceUniverseService()
    service.artifact_root = tmp_path / "artifacts"
    service.artifact_root.mkdir(parents=True, exist_ok=True)
    service.registry_path = tmp_path / "source_universe_registry.jsonl"

    result = service.build_universe(target_size=300, include_dynamic=False)

    assert result["source_universe_total"] >= 1500
    assert result["family_breakdown"]["official_national_portal"] >= 80
    assert result["family_breakdown"]["hosted_procurement_instance"] >= 50
    keys = [item.source_key for item in service._read_registry()]
    assert len(keys) == len(set(keys))


def test_analyze_payload_promotes_d365_procurement_signal(tmp_path: Path) -> None:
    service = SourceUniverseService()
    surface = service._read_registry()[0] if service.registry_path.exists() else service._load_supranational_surfaces()[0]
    payload = """
    <html><head><title>Microsoft Dynamics 365 implementation tender</title></head>
    <body>
    Open tender for implementation, migration, support and rollout of Microsoft Dynamics 365 and Power Platform.
    Contract notice with supplier response path.
    </body></html>
    """

    analysis = service._analyze_payload(payload, "Microsoft Dynamics 365 implementation tender", surface)

    assert analysis["retained_records"] == 1
    assert analysis["seller_ready_records"] == 1
    assert "bid_now" in analysis["lanes"]


def test_potential_hit_candidates_surface_strong_near_miss(tmp_path: Path) -> None:
    service = SourceUniverseService()
    sample = tmp_path / "near-miss.sample"
    sample.write_text(
        """
        <html><head><title>Enterprise CRM and workflow automation tender</title></head>
        <body>
        Procurement notice for CRM implementation, workflow automation, data platform integration,
        support services, training, and migration for a customer service platform.
        </body></html>
        """,
        encoding="utf-8",
    )
    result = AttemptResult(
        source_key="candidate",
        source_name="near_miss_source",
        family="official_national_portal",
        family_group="C",
        country="GB",
        canonical_url="https://buyer.example.gov/opportunity",
        authenticity_class="official_public",
        canonical_allowed=True,
        attempt_strategy="html_search",
        request_method="GET",
        attempt_status="success_with_docs",
        http_status=200,
        error_class=None,
        issue_code=None,
        content_type="text/html",
        english_sufficiency_score=0.16,
        extracted_docs_count=4,
        retained_records_count=0,
        seller_ready_records_count=0,
        lanes_detected=["bid_now"],
        matched_positive_terms=[],
        matched_negative_terms=[],
        blocker_reason=None,
        next_action="keep_as_near_miss",
        response_sha256="abc",
        response_sample_path=str(sample),
        robots_status="allowed",
        platform_fingerprint=None,
        latency_ms=12,
        as_of_utc="2026-04-18T00:00:00+00:00",
    )

    candidates = service._potential_hit_candidates([result])

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["heuristic_score"] > 0
    assert "crm" in candidate["soft_anchor_terms"]
    assert "strict D365 anchor did not fire" in candidate["seller_ready_blockers"]
    assert "English is below seller-ready threshold" in candidate["seller_ready_blockers"]


def test_potential_hits_review_keeps_prime_hits_separate(tmp_path: Path) -> None:
    service = SourceUniverseService()
    prime_sample = tmp_path / "prime.sample"
    prime_sample.write_text(
        """
        <html><head><title>Microsoft Dynamics 365 implementation tender</title></head>
        <body>Open tender for Microsoft Dynamics 365 migration, implementation and support services.</body></html>
        """,
        encoding="utf-8",
    )
    potential_sample = tmp_path / "potential.sample"
    potential_sample.write_text(
        """
        <html><head><title>ERP and CRM transformation procurement</title></head>
        <body>Open procurement for CRM modernisation, workflow automation, integration and support services.</body></html>
        """,
        encoding="utf-8",
    )

    prime = AttemptResult(
        source_key="prime",
        source_name="ted",
        family="official_national_portal",
        family_group="C",
        country=None,
        canonical_url="https://api.ted.europa.eu/v3/notices/search",
        authenticity_class="official_public",
        canonical_allowed=True,
        attempt_strategy="api",
        request_method="POST",
        attempt_status="success_with_docs",
        http_status=200,
        error_class=None,
        issue_code=None,
        content_type="application/json",
        english_sufficiency_score=1.0,
        extracted_docs_count=1,
        retained_records_count=1,
        seller_ready_records_count=1,
        lanes_detected=["bid_now"],
        matched_positive_terms=["dynamics 365"],
        matched_negative_terms=[],
        blocker_reason=None,
        next_action="promote_bid_now",
        response_sha256="prime",
        response_sample_path=str(prime_sample),
        robots_status="unknown",
        platform_fingerprint=None,
        latency_ms=10,
        as_of_utc="2026-04-18T00:00:00+00:00",
    )
    potential = AttemptResult(
        source_key="potential",
        source_name="portal_x",
        family="official_national_portal",
        family_group="C",
        country="IE",
        canonical_url="https://portal.example.ie/tenders",
        authenticity_class="official_public",
        canonical_allowed=True,
        attempt_strategy="html_search",
        request_method="GET",
        attempt_status="success_with_docs",
        http_status=200,
        error_class=None,
        issue_code=None,
        content_type="text/html",
        english_sufficiency_score=0.14,
        extracted_docs_count=3,
        retained_records_count=0,
        seller_ready_records_count=0,
        lanes_detected=["bid_now"],
        matched_positive_terms=[],
        matched_negative_terms=[],
        blocker_reason=None,
        next_action="keep_as_near_miss",
        response_sha256="potential",
        response_sample_path=str(potential_sample),
        robots_status="allowed",
        platform_fingerprint=None,
        latency_ms=10,
        as_of_utc="2026-04-18T00:00:00+00:00",
    )

    review = service._potential_hits_review([prime, potential], tmp_path, limit=12, use_ai=False)

    assert review["prime_hits_report"]["prime_hits_total"] == 1
    assert review["prime_hits_report"]["prime_hits"][0]["source_name"] == "ted"
    assert review["potential_hits_report"]["potential_hits_total"] == 1
    assert review["potential_hits_top12"][0]["source_name"] == "portal_x"
    assert review["potential_hits_report"]["ai_review_status"] == "disabled"


def test_extract_detail_candidates_prefers_notice_links() -> None:
    service = SourceUniverseService()
    sample = """
    <html><body>
      <a href="/privacy">Privacy</a>
      <a href="/procurement/notices/12345">Open tender notice 12345</a>
      <a href="/login">Login</a>
      <a href="/help">Help</a>
    </body></html>
    """

    candidates = service._extract_detail_candidates(
        sample,
        base_url="https://buyer.gov.example/procurement",
        content_kind="html",
        limit=5,
    )

    assert candidates
    assert candidates[0]["url"] == "https://buyer.gov.example/procurement/notices/12345"


def test_detail_follow_bucket_promotes_after_detail_follow(tmp_path: Path, monkeypatch) -> None:
    service = SourceUniverseService()
    service.artifact_root = tmp_path / "artifacts"
    service.artifact_root.mkdir(parents=True, exist_ok=True)

    campaign_path = service.artifact_root / "latest"
    campaign_path.mkdir(parents=True, exist_ok=True)
    sample = tmp_path / "listing.sample"
    sample.write_text(
        """
        <html><body>
          <a href="https://buyer.gov.example/opportunity/123">Open opportunity 123</a>
        </body></html>
        """,
        encoding="utf-8",
    )
    review_row = {
        "source_name": "detail_follow_source",
        "country": "GB",
        "family": "official_national_portal",
        "canonical_url": "https://buyer.gov.example/opportunities",
        "attempt_status": "success_with_docs",
        "docs": 3,
        "english": 1.0,
        "lanes": ["bid_now"],
        "title": "Opportunities",
        "content_kind": "html",
        "content_length": 400,
        "strict_anchor_terms": [],
        "soft_anchor_terms": ["crm"],
        "it_service_terms": ["implementation"],
        "procurement_terms": ["tender"],
        "award_terms": [],
        "closed_terms": [],
        "negative_terms": [],
        "specificity_score": 2,
        "verdict": "promising_surface_needs_detail_follow",
        "promising_score": 75,
        "why_promising": ["procurement_context_present"],
        "why_not_promoted": ["shell_or_listing_page_captured", "strict_microsoft_d365_anchor_missing"],
        "response_sample_path": str(sample),
        "response_sha256": "abc",
        "excerpt": "Open opportunity 123",
    }
    (campaign_path / "full_document_intelligent_review.jsonl").write_text(json.dumps(review_row) + "\n", encoding="utf-8")

    def fake_fetch(candidate, *, row, samples_root, as_of_utc):
        del row, samples_root, as_of_utc
        return {
            "url": candidate["url"],
            "anchor_text": candidate.get("anchor_text"),
            "candidate_score": candidate.get("score"),
            "detail_score": 96,
            "http_status": 200,
            "content_type": "text/html",
            "title": "Microsoft Dynamics 365 implementation tender",
            "latency_ms": 10,
            "response_sample_path": str(tmp_path / "detail.sample"),
            "english_sufficiency_score": 1.0,
            "positive_terms": ["dynamics 365"],
            "negative_terms": [],
            "soft_anchor_terms": ["crm"],
            "service_terms": ["implementation", "support"],
            "procurement_terms": ["tender", "contract"],
            "preposition_terms": [],
            "award_terms": [],
            "closed_terms": [],
            "retained_records": 1,
            "seller_ready_records": 1,
            "lanes": ["bid_now"],
            "watch_only": False,
            "blocker_reason": None,
            "issue_code": None,
            "excerpt": "Open tender for Microsoft Dynamics 365 implementation and support.",
        }

    monkeypatch.setattr(service, "_fetch_detail_candidate", fake_fetch)

    result = service.detail_follow_bucket(campaign_path=str(campaign_path), limit=10)

    assert result["promoted_seller_ready_total"] == 1
    report = json.loads(
        (campaign_path / "detail_follow_promising_surface_needs_detail_follow_report.json").read_text(encoding="utf-8")
    )
    assert report["final_state_counts"]["promoted_seller_ready"] == 1
