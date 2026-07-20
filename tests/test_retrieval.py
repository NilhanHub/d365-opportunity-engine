from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from d365opps.evaluation import RecallHarness
from d365opps.models import AcquisitionMethod, Lane, ParsingMode, SourceRegistry
from d365opps.retrieval import QueryCompiler, QueryExecutionPlanner, RetrievalScorer, load_retrieval_rules
from d365opps.schemas import ExtractedEvidence


def _source(name: str, *, config_json: dict[str, Any] | None = None) -> SourceRegistry:
    return SourceRegistry(
        name=name,
        description="fixture",
        lane=Lane.OPPORTUNITY,
        tier=1,
        region="Global",
        country="GB",
        enabled=True,
        is_seed=True,
        cadence="daily",
        acquisition_method=AcquisitionMethod.API,
        parsing_mode=ParsingMode.JSON,
        endpoint=f"https://{name}.example.test",
        config_json=config_json or {},
    )


def test_query_preview_excludes_standalone_generic_terms() -> None:
    compiler = QueryCompiler()
    previews = compiler.compile_for_source(_source("ted"))

    assert previews
    assert {item.query_family for item in previews} >= {
        "formal_procurement",
        "pre_positioning",
        "direct_outreach",
        "install_base_trigger",
    }
    assert all("ERP" not in item.required_anchors for item in previews)
    assert all("CRM" not in item.required_anchors for item in previews)
    assert all("Copilot" not in item.required_anchors for item in previews)
    assert all(item.mode in {"exact_phrase", "lane_specific", "field_constrained", "trigger_hunt"} for item in previews)
    assert all(
        "Dynamics 365" in item.query_text
        or "Business Central" in item.query_text
        or "Power Platform" in item.query_text
        or "Dynamics NAV" in item.query_text
        or "Dynamics AX" in item.query_text
        for item in previews
    )


def test_retrieval_rejects_hard_negatives_with_explicit_reason() -> None:
    scorer = RetrievalScorer()
    evidence = ExtractedEvidence(
        title="SAP S/4HANA implementation services",
        summary="Tender for SAP S/4HANA migration and support.",
        buyer_name="Transport Agency",
        buyer_country="GB",
        source_url="https://example.test/sap",
        response_url="https://example.test/sap/respond",
    )

    assessment = scorer.assess(evidence, _source("ted"))

    assert assessment.exclusion_reason == "competitor_tender"
    assert "sap" in assessment.matched_negative_terms
    assert not assessment.passes_signal_threshold


def test_retrieval_assigns_install_base_trigger_lane() -> None:
    scorer = RetrievalScorer()
    evidence = ExtractedEvidence(
        title="Dynamics NAV on-premises upgrade and managed support",
        summary="Public buyer needs Navision to Business Central migration assessment and AMS.",
        buyer_name="Water Utility",
        buyer_country="GB",
        source_url="https://example.test/nav",
        raw_excerpt="Legacy Dynamics NAV on-premises estate with migration roadmap and managed support requirement.",
    )

    assessment = scorer.assess(evidence, _source("generic_web"))

    assert assessment.signal_lane is not None
    assert assessment.signal_lane.value == "install_base_trigger"
    assert assessment.recommended_action.value == "outreach_now"
    assert assessment.installed_product_guess is not None


def test_recall_harness_reports_precision_and_recall() -> None:
    harness = RecallHarness()
    fixture_path = Path(__file__).parent / "fixtures" / "retrieval_cases.json"

    report = harness.run_fixture_file(fixture_path)

    assert report.precision >= 0.75
    assert report.recall >= 0.75
    assert report.false_positive_rate <= 0.25


def test_query_renderer_uses_plain_keywords_for_html_portals() -> None:
    compiler = QueryCompiler()
    rendered = compiler.render_for_source(_source("find_a_tender"), compiler.primary_query(_source("find_a_tender")))

    assert rendered.renderer == "plain_keywords_unquoted"
    assert "title:" not in rendered.rendered_query_text
    assert "summary:" not in rendered.rendered_query_text
    assert "Dynamics 365" in rendered.rendered_query_text or "Business Central" in rendered.rendered_query_text
    assert "Dataverse" not in rendered.rendered_query_text
    assert '"' not in rendered.rendered_query_text


def test_query_renderer_can_preserve_quotes_for_default_plain_keywords() -> None:
    compiler = QueryCompiler()
    source = _source("generic_html_portal", config_json={"query_renderer": "plain_keywords"})
    rendered = compiler.render_for_source(source, compiler.primary_query(source))

    assert rendered.renderer == "plain_keywords"
    assert '"' in rendered.rendered_query_text


def test_query_planner_collapses_query_agnostic_sources_to_single_fetch() -> None:
    planner = QueryExecutionPlanner()
    source = _source("ireland_etenders", config_json={"query_agnostic": True})

    plan = planner.plan(source, mode="bootstrap_backfill")

    assert len(plan.queries) == 1


def test_query_planner_dedupes_duplicate_plain_keyword_variants_within_family() -> None:
    planner = QueryExecutionPlanner()

    compiled = planner.query_compiler.compile_for_source(_source("find_a_tender"))
    plan = planner.plan(_source("find_a_tender"), mode="bootstrap_backfill")

    assert len(compiled) > len(plan.queries)
    assert len({(query.query_family, query.rendered_query_text) for query in plan.queries}) == len(plan.queries)
