from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class MetricDefinition:
    key: str
    stage: str
    label: str
    description: str
    final_lead_metric: bool


METRIC_DEFINITIONS: tuple[MetricDefinition, ...] = (
    MetricDefinition("successful_fetches", "acquisition", "Successful fetches", "Successful HTTP/API fetch attempts. Acquisition volume only, not final leads.", False),
    MetricDefinition("fetched_documents", "acquisition", "Fetched documents", "Raw listing/detail documents stored from sources. Acquisition volume only, not final leads.", False),
    MetricDefinition("fetched_detail_pages", "acquisition", "Fetched detail pages", "Follow-up detail pages fetched for structured extraction. Acquisition volume only, not final leads.", False),
    MetricDefinition("fetched_attachments", "acquisition", "Fetched attachments", "Public attachments fetched for enrichment and evidence extraction. Acquisition volume only, not final leads.", False),
    MetricDefinition("evidence_rows", "extraction", "Evidence rows", "Extracted evidence records emitted from fetched documents. Extraction volume only, not final leads.", False),
    MetricDefinition("parsed_documents", "extraction", "Parsed documents", "Documents successfully parsed into structured fields. Extraction volume only, not final leads.", False),
    MetricDefinition("classified_documents", "extraction", "Classified documents", "Documents that reached classification/scoring. Extraction volume only, not final leads.", False),
    MetricDefinition("retained_d365_records", "retained_intelligence", "Retained D365 records", "Live retained records with explicit Microsoft/D365/BC/Dataverse/Power Platform anchors.", True),
    MetricDefinition("duplicates_removed", "retained_intelligence", "Duplicates removed", "Records demoted as duplicates after clustering and dedupe.", False),
    MetricDefinition("retained_without_anchor_total", "retained_intelligence", "Retained without anchor", "Live retained records missing a D365 anchor. This should remain zero.", False),
    MetricDefinition("english_insufficient_total", "retained_intelligence", "English insufficient", "Live records demoted because seller-usable English evidence was insufficient.", False),
    MetricDefinition("stale_or_awarded_total", "retained_intelligence", "Stale or awarded", "Live records demoted because they are expired, closed, cancelled, or awarded.", False),
    MetricDefinition("monitor_only_total", "retained_intelligence", "Monitor only", "Retained intelligence still worth monitoring but not seller-ready now.", False),
    MetricDefinition("current_actionable_total", "commercial_actionability", "Current actionable", "Commercially actionable records as of the current as-of timestamp.", True),
    MetricDefinition("current_bid_now_total", "commercial_actionability", "Current bid now", "Current open-bid records that remain commercially live.", True),
    MetricDefinition("current_pre_position_total", "commercial_actionability", "Current pre-position", "Current consultations, market engagement, or early-positioning records.", True),
    MetricDefinition("award_watch_total", "commercial_actionability", "Award watch", "Retained award-watch records useful for future pursuit timing, not immediate bids.", False),
    MetricDefinition("renewal_watch_total", "commercial_actionability", "Renewal watch", "Retained renewal-watch records useful for forward positioning, not immediate bids.", False),
    MetricDefinition("seller_ready_total", "seller_readiness", "Seller-ready total", "Records that a human seller can act on now with sufficient evidence.", True),
    MetricDefinition("seller_ready_bid_now_total", "seller_readiness", "Seller-ready bid now", "Seller-ready open bids with enough evidence and currentness to act now.", True),
    MetricDefinition("seller_ready_pre_position_total", "seller_readiness", "Seller-ready pre-position", "Seller-ready current consultations or shaping exercises worth active positioning.", True),
    MetricDefinition("research_ready_total", "seller_readiness", "Research-ready total", "Records with D365 anchors that still need analyst review before seller handoff.", False),
    MetricDefinition("monitor_total", "seller_readiness", "Monitor total", "Records retained for monitoring rather than seller handoff.", False),
    MetricDefinition("reject_total", "seller_readiness", "Reject total", "Rows rejected from seller handoff and live actionability.", False),
)


METRICS_BY_KEY: dict[str, MetricDefinition] = {metric.key: metric for metric in METRIC_DEFINITIONS}


def metric_catalog_payload() -> dict[str, Any]:
    stages: dict[str, list[dict[str, Any]]] = {}
    for metric in METRIC_DEFINITIONS:
        stages.setdefault(metric.stage, []).append(asdict(metric))
    return {
        "metrics": [asdict(metric) for metric in METRIC_DEFINITIONS],
        "stages": stages,
    }


def metric_stage(key: str) -> str | None:
    metric = METRICS_BY_KEY.get(key)
    return metric.stage if metric else None
