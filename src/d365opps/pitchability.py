from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from typing import Any
import re

from d365opps.lifecycle import lifecycle_for_record
from d365opps.models import CurrentActionabilityState, RadarLane


ANCHOR_TERMS: tuple[str, ...] = (
    "dynamics 365",
    "microsoft dynamics",
    "dynamics crm",
    "customer engagement",
    "business central",
    "dataverse",
    "power platform",
    "power apps",
    "power automate",
    "power pages",
    "copilot studio",
    "dynamics nav",
    "navision",
    "dynamics ax",
    "finance and operations",
    "dynamics gp",
    "great plains",
    "dynamics sl",
)
AMBIGUOUS_ANCHOR_TERMS: tuple[str, ...] = (
    "customer engagement",
    "ce",
)
EXPLICIT_ANCHOR_TOKENS: tuple[str, ...] = (
    "dynamics",
    "microsoft",
    "business central",
    "dataverse",
    "power platform",
    "power apps",
    "power automate",
    "power pages",
    "copilot studio",
    "navision",
    "finance and operations",
    "d365",
)
LEGACY_TRIGGER_TERMS: tuple[str, ...] = (
    "dynamics ax",
    "dynamics nav",
    "navision",
    "dynamics crm",
    "dynamics gp",
    "great plains",
    "dynamics sl",
    "finance and operations",
    "f&o",
    "microsoft dynamics",
    "business central",
)
SELLER_ENGLISH_MARKERS: tuple[str, ...] = (
    "the",
    "and",
    "for",
    "with",
    "services",
    "service",
    "support",
    "implementation",
    "migration",
    "upgrade",
    "maintenance",
    "consulting",
    "consultancy",
    "tender",
    "framework",
    "market",
    "consultation",
    "submission",
    "deadline",
)
PITCHABLE_ACTIONS = {"bid_now", "pre_position"}
PITCHABLE_STATES = {
    CurrentActionabilityState.OPEN_BID.value,
    CurrentActionabilityState.OPEN_CONSULTATION.value,
    CurrentActionabilityState.PRE_MARKET_ENGAGEMENT.value,
    CurrentActionabilityState.PLANNED_PROCUREMENT.value,
    CurrentActionabilityState.FRAMEWORK_OR_VEHICLE.value,
}
AWARD_OR_STALE_STATES = {
    CurrentActionabilityState.AWARD_NOTICE.value,
    CurrentActionabilityState.AWARDED.value,
    CurrentActionabilityState.CONTRACT_DETAILS_ONLY.value,
    CurrentActionabilityState.CLOSED_SUBMISSION.value,
    CurrentActionabilityState.EXPIRED.value,
    CurrentActionabilityState.CANCELLED.value,
}
STATE_REASON_MAP = {
    CurrentActionabilityState.CLOSED_SUBMISSION.value: "closed_submission",
    CurrentActionabilityState.AWARD_NOTICE.value: "award_notice",
    CurrentActionabilityState.AWARDED.value: "awarded",
    CurrentActionabilityState.CONTRACT_DETAILS_ONLY.value: "contract_details_only",
    CurrentActionabilityState.EXPIRED.value: "expired",
    CurrentActionabilityState.CANCELLED.value: "cancelled",
    CurrentActionabilityState.MONITOR_ONLY.value: "monitor_only",
    CurrentActionabilityState.UNKNOWN.value: "unknown_actionability",
}
SELLER_HANDOFF_STATES = {"seller_ready", "research_ready", "monitor_only", "reject"}


@dataclass(slots=True)
class PitchabilityEvaluation:
    allowed: bool
    reasons: list[str]
    anchor_terms: list[str]
    current_actionability_state: str
    source_status_raw: str | None
    actionability_rationale: str
    effective_recommended_action: str
    english_sufficiency_score: float
    english_shell_only_flag: bool
    seller_readable_summary_en: str | None
    seller_readable_title_en_flag: bool
    commercial_motion: str
    sales_handoff_state: str
    seller_handoff_rationale: str
    source_verified_open_without_close_date: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def apply_evaluation_to_row(row: dict[str, Any], evaluation: PitchabilityEvaluation) -> dict[str, Any]:
    row["pitchability_reasons"] = evaluation.reasons
    row["anchor_terms"] = evaluation.anchor_terms
    row["current_actionability_state"] = evaluation.current_actionability_state
    row["source_status_raw"] = evaluation.source_status_raw
    row["actionability_rationale"] = evaluation.actionability_rationale
    row["recommended_action"] = evaluation.effective_recommended_action
    row["english_sufficiency_score"] = evaluation.english_sufficiency_score
    row["english_shell_only_flag"] = evaluation.english_shell_only_flag
    row["seller_readable_summary_en"] = evaluation.seller_readable_summary_en
    row["seller_readable_title_en_flag"] = evaluation.seller_readable_title_en_flag
    row["commercial_motion"] = evaluation.commercial_motion
    row["sales_handoff_state"] = evaluation.sales_handoff_state
    row["seller_handoff_rationale"] = evaluation.seller_handoff_rationale
    row["source_verified_open_without_close_date"] = evaluation.source_verified_open_without_close_date
    row["pursuit_recommendation"] = evaluation.sales_handoff_state
    return row


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(str(value).lower().split())


def _english_tokens(text: str) -> list[str]:
    return re.findall(r"[a-z]+", normalize_text(text))


def _value(row: Any, name: str, default: Any = None) -> Any:
    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(name, default)
    return getattr(row, name, default)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _coerce_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _combined_text(*rows: Any) -> str:
    parts: list[str] = []
    for row in rows:
        if row is None:
            continue
        parts.extend(
            str(item)
            for item in (
                _value(row, "title"),
                _value(row, "summary"),
                _value(row, "raw_excerpt"),
                _value(row, "source_url"),
                _value(row, "response_url"),
                _value(row, "installed_product_guess"),
                _value(row, "installed_product_evidence"),
                _value(row, "notice_type"),
                _value(row, "procurement_type"),
                _value(row, "procurement_cycle_stage"),
                _value(row, "vehicle_type"),
                _value(row, "route_to_market"),
            )
            if item
        )
        for field in (
            "product_mentions",
            "product_mentions_json",
            "service_mentions",
            "service_mentions_json",
            "matched_positive_terms",
            "matched_positive_terms_json",
        ):
            parts.extend(str(item) for item in _as_list(_value(row, field)) if item)
        legacy = _value(row, "legacy_evidence_json") or _value(row, "legacy_evidence") or {}
        if isinstance(legacy, dict):
            parts.extend(str(item) for item in _as_list(legacy.get("legacy_terms")) if item)
            parts.extend(str(item) for item in _as_list(legacy.get("trigger_terms")) if item)
        extracted = _value(row, "extracted_json") or _value(row, "extracted_data") or {}
        if isinstance(extracted, dict):
            for key in (
                "mainType",
                "notice_type",
                "notice_status",
                "CFT_STATUS",
                "projectTitle",
                "projectShortDescription",
                "objectDescriptions",
                "bid_description",
                "notice_text",
            ):
                if extracted.get(key):
                    parts.append(str(extracted[key]))
    return normalize_text(" ".join(parts))


def anchor_terms_for_record(*rows: Any) -> list[str]:
    text = _combined_text(*rows)
    matched = {
        term
        for term in ANCHOR_TERMS
        if term in text and (term not in AMBIGUOUS_ANCHOR_TERMS or "dynamics" in text or "microsoft" in text)
    }
    for row in rows:
        for term in _as_list(_value(row, "matched_positive_terms") or _value(row, "matched_positive_terms_json")):
            normalized = normalize_text(term)
            if not normalized:
                continue
            if normalized in AMBIGUOUS_ANCHOR_TERMS and "dynamics" not in text and "microsoft" not in text:
                continue
            if any(token in normalized for token in EXPLICIT_ANCHOR_TOKENS):
                matched.add(normalized)
    return sorted(term for term in matched if term)


def qualifies_legacy_trigger(*rows: Any) -> bool:
    lane_value = None
    for row in rows:
        lane = _value(row, "signal_lane")
        if isinstance(lane, RadarLane):
            lane_value = lane.value
        elif lane:
            lane_value = str(lane)
        if lane_value:
            break
    if lane_value != RadarLane.INSTALL_BASE_TRIGGER.value:
        return False
    text = _combined_text(*rows)
    if any(term in text for term in LEGACY_TRIGGER_TERMS):
        return True
    for row in rows:
        legacy = _value(row, "legacy_evidence_json") or _value(row, "legacy_evidence") or {}
        if not isinstance(legacy, dict):
            continue
        legacy_terms = [normalize_text(term) for term in _as_list(legacy.get("legacy_terms")) if term]
        trigger_terms = [normalize_text(term) for term in _as_list(legacy.get("trigger_terms")) if term]
        installed_guess = normalize_text(_value(row, "installed_product_guess"))
        if any(term in LEGACY_TRIGGER_TERMS for term in legacy_terms):
            return True
        if any(term in LEGACY_TRIGGER_TERMS for term in trigger_terms):
            return True
        if any(term in installed_guess for term in LEGACY_TRIGGER_TERMS):
            return True
    return False


def retention_gate(*rows: Any) -> tuple[bool, str | None, list[str]]:
    anchor_terms = anchor_terms_for_record(*rows)
    if anchor_terms:
        return True, None, anchor_terms
    if qualifies_legacy_trigger(*rows):
        return True, None, []
    return False, "no_d365_anchor", []


def dedupe_key(row: Any) -> str:
    fingerprint = _value(row, "dedupe_fingerprint")
    if fingerprint:
        return str(fingerprint)
    procurement_id = normalize_text(_value(row, "procurement_id"))
    title = normalize_text(_value(row, "title"))
    buyer = normalize_text(_value(row, "buyer_name") or _value(row, "canonical_buyer"))
    source_url = normalize_text(_value(row, "source_url"))
    return "|".join(part for part in (procurement_id, title, buyer, source_url) if part)


def is_demo_record(row: Any) -> bool:
    tags = {normalize_text(tag) for tag in _as_list(_value(row, "tags") or _value(row, "tags_json")) if tag}
    title = normalize_text(_value(row, "title"))
    source_url = normalize_text(_value(row, "source_url"))
    return "demo" in tags or title.startswith("demo ") or "example.test" in source_url


def _action_value(row: Any, *fallback_rows: Any) -> str:
    action = _value(row, "recommended_action")
    if action is None:
        for item in fallback_rows:
            action = _value(item, "recommended_action")
            if action is not None:
                break
    if hasattr(action, "value"):
        return normalize_text(action.value)
    return normalize_text(str(action or ""))


def _textual_state(*rows: Any) -> str:
    return _combined_text(*rows)


def current_actionability_state_for_record(*rows: Any, today: datetime | None = None) -> str:
    return lifecycle_for_record(*rows, as_of_utc=today).source_status_normalized


def _english_score(text: str, *, anchor_terms: list[str] | None = None) -> float:
    normalized = normalize_text(text)
    if not normalized:
        return 0.0
    tokens = _english_tokens(normalized)
    if not tokens:
        return 0.0
    ascii_letters = sum(1 for char in normalized if char.isascii() and (char.isalpha() or char.isspace()))
    ascii_ratio = ascii_letters / max(len(normalized), 1)
    marker_hits = sum(1 for marker in SELLER_ENGLISH_MARKERS if marker in tokens)
    anchor_hits = sum(1 for term in (anchor_terms or []) if normalize_text(term) in normalized)
    score = min(1.0, (ascii_ratio * 0.28) + min(0.42, marker_hits * 0.08) + min(0.16, anchor_hits * 0.08))
    if marker_hits == 0:
        score = min(score, 0.18 + min(0.08, anchor_hits * 0.04))
    return round(score, 3)


def english_readiness_for_record(*rows: Any) -> tuple[float, bool, bool, str | None]:
    for row in rows:
        existing_score = _value(row, "english_sufficiency_score")
        if existing_score:
            return (
                float(existing_score),
                bool(_value(row, "english_shell_only_flag")),
                bool(_value(row, "seller_readable_title_en_flag")),
                _value(row, "seller_readable_summary_en"),
            )
    anchor_terms = anchor_terms_for_record(*rows)
    title = next((str(_value(row, "title")) for row in rows if _value(row, "title")), "")
    summary = next((str(_value(row, "summary")) for row in rows if _value(row, "summary")), "")
    excerpt = next((str(_value(row, "raw_excerpt")) for row in rows if _value(row, "raw_excerpt")), "")
    language_status = normalize_text(next((str(_value(row, "language_status")) for row in rows if _value(row, "language_status")), ""))
    english_source = normalize_text(next((str(_value(row, "english_evidence_source")) for row in rows if _value(row, "english_evidence_source")), ""))
    title_score = _english_score(title, anchor_terms=anchor_terms)
    summary_score = _english_score(summary, anchor_terms=anchor_terms)
    excerpt_score = _english_score(excerpt[:800], anchor_terms=anchor_terms)
    title_tokens = _english_tokens(title)
    summary_tokens = _english_tokens(summary)
    excerpt_tokens = _english_tokens(excerpt[:800])
    title_marker_hits = sum(1 for marker in SELLER_ENGLISH_MARKERS if marker in title_tokens)
    summary_marker_hits = sum(1 for marker in SELLER_ENGLISH_MARKERS if marker in summary_tokens)
    excerpt_marker_hits = sum(1 for marker in SELLER_ENGLISH_MARKERS if marker in excerpt_tokens)
    score = round((title_score * 0.45) + (summary_score * 0.4) + (excerpt_score * 0.15), 3)
    seller_title_flag = title_score >= 0.34 and title_marker_hits >= 1
    seller_summary = None
    if summary_score >= 0.3 and summary_marker_hits >= 2:
        seller_summary = summary
    elif excerpt_score >= 0.38 and excerpt_marker_hits >= 2:
        seller_summary = excerpt[:1200]
    shell_only = english_source in {"alternate", "metadata"} and not seller_title_flag and seller_summary is None
    if language_status == "non_english_only":
        score = min(score, 0.18)
    if english_source == "alternate" and score < 0.28:
        shell_only = True
    return score, shell_only, seller_title_flag, seller_summary


def commercial_motion_for_record(row: Any, *fallback_rows: Any, today: datetime | None = None) -> str:
    state = current_actionability_state_for_record(row, *fallback_rows, today=today)
    lane = _value(row, "signal_lane") or next((_value(item, "signal_lane") for item in fallback_rows if _value(item, "signal_lane")), None)
    lane_value = lane.value if hasattr(lane, "value") else str(lane or "")
    route_to_market = normalize_text(
        str(
            (_value(row, "route_to_market").value if hasattr(_value(row, "route_to_market"), "value") else _value(row, "route_to_market"))
            or next(
                (
                    (_value(item, "route_to_market").value if hasattr(_value(item, "route_to_market"), "value") else _value(item, "route_to_market"))
                    for item in fallback_rows
                    if _value(item, "route_to_market")
                ),
                "",
            )
        )
    )
    action = _action_value(row, *fallback_rows)
    if lane_value == RadarLane.INSTALL_BASE_TRIGGER.value:
        return "install_base_trigger"
    if state == CurrentActionabilityState.OPEN_BID.value:
        if action == "reject":
            return "reject"
        return "pitch_now"
    if state in {
        CurrentActionabilityState.OPEN_CONSULTATION.value,
        CurrentActionabilityState.PRE_MARKET_ENGAGEMENT.value,
        CurrentActionabilityState.PLANNED_PROCUREMENT.value,
        CurrentActionabilityState.FRAMEWORK_OR_VEHICLE.value,
    }:
        return "pre_position"
    if route_to_market == "renewal_watch":
        return "renewal_watch"
    if state in {
        CurrentActionabilityState.AWARD_NOTICE.value,
        CurrentActionabilityState.AWARDED.value,
        CurrentActionabilityState.CONTRACT_DETAILS_ONLY.value,
    }:
        return "award_watch"
    if action == "reject":
        return "reject"
    return "monitor"


def effective_recommended_action_for_record(row: Any, *fallback_rows: Any, today: datetime | None = None) -> str:
    motion = commercial_motion_for_record(row, *fallback_rows, today=today)
    mapping = {
        "pitch_now": "bid_now",
        "pre_position": "pre_position",
        "renewal_watch": "renewal_watch",
        "award_watch": "award_watch",
        "install_base_trigger": "install_base_trigger",
        "reject": "reject",
        "monitor": "monitor",
    }
    return mapping.get(motion, "monitor")


def _source_trust_for_record(row: Any, *fallback_rows: Any) -> float:
    for item in (row, *fallback_rows):
        value = _value(item, "source_trust")
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0


def evaluate_record(
    row: Any,
    *,
    evidence: Any = None,
    seen_keys: set[str] | None = None,
    today: datetime | None = None,
) -> PitchabilityEvaluation:
    reasons: list[str] = []
    anchor_terms = anchor_terms_for_record(row, evidence)
    lifecycle = lifecycle_for_record(row, evidence, as_of_utc=today)
    close_date = _coerce_datetime(_value(row, "close_date") or _value(evidence, "close_date"))
    if is_demo_record(row):
        reasons.append("demo_record")
    if _value(row, "exclusion_reason"):
        reasons.append(str(_value(row, "exclusion_reason")))
    if _value(row, "status") and str(_value(row, "status")).lower().endswith("rejected"):
        reasons.append("rejected")
    key = dedupe_key(row)
    if seen_keys is not None and key:
        if key in seen_keys:
            reasons.append("duplicate")
        else:
            seen_keys.add(key)
    allowed, retention_reason, _ = retention_gate(row, evidence)
    if not allowed and retention_reason:
        reasons.append(retention_reason)
    score = float(_value(row, "opportunity_score", 0) or 0)
    motion = commercial_motion_for_record(row, evidence, today=today)
    minimum_score = 50 if motion == "pre_position" else 55
    if score < minimum_score:
        reasons.append("score_below_threshold")
    state = lifecycle.source_status_normalized
    if state not in PITCHABLE_STATES:
        reasons.append(STATE_REASON_MAP.get(state, "not_currently_actionable"))
    effective_action = effective_recommended_action_for_record(row, evidence, today=today)
    if effective_action not in PITCHABLE_ACTIONS or motion not in {"pitch_now", "pre_position"}:
        reasons.append("not_pitch_motion")
    english_score, english_shell_only, seller_title_flag, seller_summary = english_readiness_for_record(row, evidence)
    if english_score < 0.28 or (not seller_title_flag and not seller_summary):
        reasons.append("english_insufficient")
    if english_shell_only:
        reasons.append("english_shell_only")
    if not (_value(row, "buyer_name") or _value(row, "organization_id") or _value(evidence, "buyer_name")):
        reasons.append("missing_buyer")
    if not (
        (_value(row, "source_url") or _value(evidence, "source_url"))
        and (
            _value(row, "summary")
            or _value(row, "raw_excerpt")
            or _value(evidence, "summary")
            or _value(evidence, "raw_excerpt")
        )
    ):
        reasons.append("insufficient_evidence")
    source_verified_open_without_close_date = False
    if effective_action == "bid_now" and state == CurrentActionabilityState.OPEN_BID.value:
        if close_date is not None:
            if close_date.tzinfo is None:
                close_date = close_date.replace(tzinfo=UTC)
            if today is not None and close_date < today:
                reasons.append("expired")
        else:
            open_status_text = normalize_text(
                " ".join(filter(None, (lifecycle.source_status_raw, lifecycle.rationale)))
            )
            open_markers = (
                "open",
                "submission",
                "tender",
                "deadline",
                "closing",
                "competition_notice",
                "open_notice",
                "current_tender",
                "open_submission",
                "world_bank_open_notice",
                "hilma_open_notice",
                "uk_open_notice",
                "tenderned_open_notice",
                "gets_current_tender",
                "ted_competition_notice",
                "ted_generic_fallback",
            )
            if any(marker in open_status_text for marker in open_markers):
                source_verified_open_without_close_date = True
            else:
                reasons.append("missing_close_date")
    source_trust = _source_trust_for_record(row, evidence)
    if source_trust and source_trust < 0.55:
        reasons.append("source_trust_below_threshold")
    unique_reasons = sorted(set(reasons))
    if not anchor_terms and "no_d365_anchor" in unique_reasons:
        sales_handoff_state = "reject"
        seller_handoff_rationale = "Missing explicit Microsoft/D365/BC/Dataverse/Power Platform anchor."
    elif any(reason in unique_reasons for reason in ("demo_record", "rejected", "duplicate")):
        sales_handoff_state = "reject"
        seller_handoff_rationale = "Record is not eligible for seller handoff."
    elif any(reason in unique_reasons for reason in ("award_notice", "awarded", "contract_details_only", "closed_submission", "expired", "cancelled")):
        sales_handoff_state = "monitor_only"
        seller_handoff_rationale = "Commercially stale or closed. Keep for monitoring or award-watch only."
    elif any(reason in unique_reasons for reason in ("english_insufficient", "english_shell_only", "missing_close_date", "source_trust_below_threshold")):
        sales_handoff_state = "research_ready"
        seller_handoff_rationale = "Needs analyst validation before seller handoff."
    elif any(reason in unique_reasons for reason in ("missing_buyer", "insufficient_evidence", "score_below_threshold")):
        sales_handoff_state = "research_ready"
        seller_handoff_rationale = "D365-anchored but missing enough structured evidence for direct seller handoff."
    elif motion in {"award_watch", "renewal_watch", "install_base_trigger", "monitor"}:
        sales_handoff_state = "monitor_only"
        seller_handoff_rationale = "Retain for monitoring or proactive account strategy, not immediate handoff."
    elif effective_action in PITCHABLE_ACTIONS and state in PITCHABLE_STATES:
        sales_handoff_state = "seller_ready"
        seller_handoff_rationale = "Current commercially actionable D365 lead with seller-usable evidence."
    else:
        sales_handoff_state = "reject"
        seller_handoff_rationale = "Does not satisfy the canonical seller handoff contract."
    return PitchabilityEvaluation(
        allowed=sales_handoff_state == "seller_ready",
        reasons=unique_reasons,
        anchor_terms=anchor_terms,
        current_actionability_state=state,
        source_status_raw=lifecycle.source_status_raw,
        actionability_rationale=lifecycle.rationale,
        effective_recommended_action=effective_action,
        english_sufficiency_score=english_score,
        english_shell_only_flag=english_shell_only,
        seller_readable_summary_en=seller_summary,
        seller_readable_title_en_flag=seller_title_flag,
        commercial_motion=motion,
        sales_handoff_state=sales_handoff_state,
        seller_handoff_rationale=seller_handoff_rationale,
        source_verified_open_without_close_date=source_verified_open_without_close_date,
    )


def pitchability_for_record(
    row: Any,
    *,
    evidence: Any = None,
    seen_keys: set[str] | None = None,
    today: datetime | None = None,
) -> tuple[bool, list[str], list[str]]:
    evaluation = evaluate_record(row, evidence=evidence, seen_keys=seen_keys, today=today)
    return evaluation.allowed, evaluation.reasons, evaluation.anchor_terms
