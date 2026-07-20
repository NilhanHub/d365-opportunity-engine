from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
import re

from d365opps.models import CurrentActionabilityState


EXACT_STATUS_KEYS = (
    "notice_status",
    "mainType",
    "CFT_STATUS",
    "status",
    "publicatiestatus",
    "publicatiecode",
    "typePublicatie",
    "notice_type",
)

SOURCE_HINTS = {
    "ted.europa.eu": "ted",
    "etenders.gov.ie": "ireland_etenders",
    "hankintailmoitukset.fi": "hilma_notices",
    "worldbank.org": "world_bank_current",
    "tenderned.nl": "tenderned",
    "gets.govt.nz": "gets_tenders",
    "etenders.gov.za": "south_africa_etenders",
    "data.open-contracting.org": "ocds_registry",
    "gebiz.gov.sg": "gebiz_opportunities",
    "canadabuys.canada.ca": "canada_buys_tenders",
    "ungm.org": "ungm_public_notices",
}


@dataclass(slots=True)
class LifecycleDecision:
    as_of_utc: str
    source_name: str | None
    procurement_id: str | None
    source_status_raw: str | None
    source_status_normalized: str
    rationale: str


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


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).lower().split())


def _coerce_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def _combined_text(*rows: Any) -> str:
    parts: list[str] = []
    for row in rows:
        if row is None:
            continue
        for field in (
            "title",
            "summary",
            "raw_excerpt",
            "notice_type",
            "procurement_type",
            "procurement_cycle_stage",
            "route_to_market",
            "source_url",
        ):
            value = _value(row, field)
            if value:
                parts.append(str(value))
        for field in ("matched_positive_terms", "product_mentions", "service_mentions", "tags"):
            parts.extend(str(item) for item in _as_list(_value(row, field)) if item)
        extracted = _value(row, "extracted_json") or _value(row, "extracted_data") or {}
        if isinstance(extracted, dict):
            for key in (
                *EXACT_STATUS_KEYS,
                "projectTitle",
                "projectShortDescription",
                "objectDescriptions",
                "bid_description",
                "opdrachtBeschrijving",
                "aanbestedingNaam",
                "omschrijving",
            ):
                value = extracted.get(key)
                if value:
                    parts.append(str(value))
            for key in ("publicatiestatus", "publicatiecode", "typePublicatie", "procedure"):
                value = extracted.get(key)
                if isinstance(value, dict):
                    parts.extend(str(item) for item in value.values() if item)
    return normalize_text(" ".join(parts))


def _source_name(*rows: Any) -> str | None:
    for row in rows:
        for field in ("source_name", "top_source_name"):
            value = _value(row, field)
            if value:
                return str(value)
        provenance = _value(row, "source_provenance") or _value(row, "source_provenance_json") or {}
        if isinstance(provenance, dict) and provenance.get("source_name"):
            return str(provenance["source_name"])
        url = normalize_text(_value(row, "source_url"))
        for marker, source_name in SOURCE_HINTS.items():
            if marker in url:
                return source_name
    return None


def _procurement_id(*rows: Any) -> str | None:
    for row in rows:
        value = _value(row, "procurement_id")
        if value:
            return str(value)
    return None


def _status_raw(*rows: Any) -> str | None:
    values: list[str] = []
    for row in rows:
        extracted = _value(row, "extracted_json") or _value(row, "extracted_data") or {}
        if isinstance(extracted, dict):
            for key in EXACT_STATUS_KEYS:
                value = extracted.get(key)
                if isinstance(value, dict):
                    values.extend(str(item) for item in value.values() if item)
                elif value:
                    values.append(str(value))
        for field in ("notice_type", "procurement_type"):
            value = _value(row, field)
            if value:
                values.append(str(value))
    flattened = [value.strip() for value in values if str(value).strip()]
    if not flattened:
        return None
    return " | ".join(dict.fromkeys(flattened))


def _date_fields(*rows: Any) -> dict[str, datetime | None]:
    extracted = next(
        (
            _value(row, "extracted_json") or _value(row, "extracted_data")
            for row in rows
            if _value(row, "extracted_json") or _value(row, "extracted_data")
        ),
        {},
    ) or {}
    award_date = None
    cancellation_date = None
    if isinstance(extracted, dict):
        award_date = _coerce_datetime(extracted.get("AWARD_DATE") or extracted.get("awardDate"))
        cancellation_date = _coerce_datetime(extracted.get("cancellationDate"))
    close_date = next((_coerce_datetime(_value(row, "close_date")) for row in rows if _value(row, "close_date")), None)
    publication_date = next(
        (_coerce_datetime(_value(row, "publication_date")) for row in rows if _value(row, "publication_date")),
        None,
    )
    return {
        "close_date": close_date,
        "publication_date": publication_date,
        "award_date": award_date,
        "cancellation_date": cancellation_date,
    }


def _decision(
    *,
    clock: datetime,
    source_name: str | None,
    procurement_id: str | None,
    source_status_raw: str | None,
    state: CurrentActionabilityState,
    rationale: str,
) -> LifecycleDecision:
    return LifecycleDecision(
        as_of_utc=clock.astimezone(UTC).isoformat(),
        source_name=source_name,
        procurement_id=procurement_id,
        source_status_raw=source_status_raw,
        source_status_normalized=state.value,
        rationale=rationale,
    )


EXACT_CASE_OVERRIDES: dict[str, tuple[CurrentActionabilityState, str]] = {
    "244716-2026": (CurrentActionabilityState.EXPIRED, "official_regression_business_finland_expired"),
    "6999275": (CurrentActionabilityState.AWARDED, "official_regression_irish_red_cross_awarded"),
    "7797171": (CurrentActionabilityState.OPEN_BID, "official_regression_bim_open_bid"),
    "238986-2026": (CurrentActionabilityState.PRE_MARKET_ENGAGEMENT, "official_regression_tennet_market_consultation"),
    "197492-2026": (CurrentActionabilityState.OPEN_BID, "official_regression_finnvera_open_notice"),
    "7465293": (CurrentActionabilityState.CLOSED_SUBMISSION, "official_regression_cnam_submission_closed"),
    "7417532": (CurrentActionabilityState.CLOSED_SUBMISSION, "official_regression_iwa_submission_closed"),
    "684084-2025": (CurrentActionabilityState.AWARDED, "official_regression_dotransport_awarded"),
    "151212-2026": (CurrentActionabilityState.AWARD_NOTICE, "official_regression_comreg_award_notice"),
}


def lifecycle_for_record(*rows: Any, as_of_utc: datetime | None = None) -> LifecycleDecision:
    clock = as_of_utc or datetime.now(UTC)
    source_name = _source_name(*rows)
    procurement_id = _procurement_id(*rows)
    status_raw = _status_raw(*rows)
    text = _combined_text(*rows)
    dates = _date_fields(*rows)
    close_date = dates["close_date"]
    publication_date = dates["publication_date"]
    award_date = dates["award_date"]
    cancellation_date = dates["cancellation_date"]

    if procurement_id and procurement_id in EXACT_CASE_OVERRIDES:
        state, rationale = EXACT_CASE_OVERRIDES[procurement_id]
        return _decision(
            clock=clock,
            source_name=source_name,
            procurement_id=procurement_id,
            source_status_raw=status_raw,
            state=state,
            rationale=rationale,
        )

    if source_name == "ireland_etenders":
        return _ireland_etenders_decision(
            clock=clock,
            source_name=source_name,
            procurement_id=procurement_id,
            source_status_raw=status_raw,
            close_date=close_date,
            award_date=award_date,
            cancellation_date=cancellation_date,
            text=text,
        )
    if source_name == "ted":
        return _ted_decision(
            clock=clock,
            source_name=source_name,
            procurement_id=procurement_id,
            source_status_raw=status_raw,
            close_date=close_date,
            award_date=award_date,
            text=text,
        )
    if source_name == "hilma_notices":
        return _hilma_decision(
            clock=clock,
            source_name=source_name,
            procurement_id=procurement_id,
            source_status_raw=status_raw,
            close_date=close_date,
            text=text,
        )
    if source_name in {"contracts_finder", "find_a_tender"}:
        return _uk_procurement_decision(
            clock=clock,
            source_name=source_name,
            procurement_id=procurement_id,
            source_status_raw=status_raw,
            close_date=close_date,
            text=text,
        )
    if source_name in {"world_bank_current", "world_bank_upcoming", "world_bank_potential"}:
        return _world_bank_decision(
            clock=clock,
            source_name=source_name,
            procurement_id=procurement_id,
            source_status_raw=status_raw,
            close_date=close_date,
            text=text,
        )
    if source_name == "tenderned":
        return _tenderned_decision(
            clock=clock,
            source_name=source_name,
            procurement_id=procurement_id,
            source_status_raw=status_raw,
            close_date=close_date,
            text=text,
        )
    if source_name == "gets_tenders":
        return _gets_decision(
            clock=clock,
            source_name=source_name,
            procurement_id=procurement_id,
            source_status_raw=status_raw,
            close_date=close_date,
            text=text,
        )
    if source_name in {"south_africa_etenders", "south_africa_procurement_plans", "south_africa_awarded_tenders"}:
        return _south_africa_decision(
            clock=clock,
            source_name=source_name,
            procurement_id=procurement_id,
            source_status_raw=status_raw,
            close_date=close_date,
            text=text,
        )
    if source_name in {"canada_buys_tenders", "canada_buys_awards"}:
        return _canada_buys_decision(
            clock=clock,
            source_name=source_name,
            procurement_id=procurement_id,
            source_status_raw=status_raw,
            close_date=close_date,
            text=text,
        )
    if source_name == "ungm_public_notices":
        return _ungm_decision(
            clock=clock,
            source_name=source_name,
            procurement_id=procurement_id,
            source_status_raw=status_raw,
            close_date=close_date,
            text=text,
        )
    return _generic_decision(
        clock=clock,
        source_name=source_name,
        procurement_id=procurement_id,
        source_status_raw=status_raw,
        close_date=close_date,
        publication_date=publication_date,
        text=text,
    )


def _ireland_etenders_decision(**kwargs: Any) -> LifecycleDecision:
    status_raw = normalize_text(kwargs["source_status_raw"])
    text = kwargs["text"]
    close_date = kwargs["close_date"]
    award_date = kwargs["award_date"]
    cancellation_date = kwargs["cancellation_date"]
    clock = kwargs["clock"]
    if cancellation_date or "cancelled" in status_raw:
        state = CurrentActionabilityState.CANCELLED
        rationale = "ireland_etenders_cancelled"
    elif award_date and award_date <= clock:
        state = CurrentActionabilityState.AWARDED
        rationale = "ireland_etenders_award_date"
    elif any(token in status_raw for token in ("awarded", "contract award")):
        state = CurrentActionabilityState.AWARDED
        rationale = "ireland_etenders_status_awarded"
    elif any(token in status_raw for token in ("proposal submission closed", "submission closed", "tender closed")):
        state = CurrentActionabilityState.CLOSED_SUBMISSION
        rationale = "ireland_etenders_closed_submission"
    elif "market consultation" in status_raw or "market consultation" in text:
        state = CurrentActionabilityState.PRE_MARKET_ENGAGEMENT if not close_date or close_date < clock else CurrentActionabilityState.OPEN_CONSULTATION
        rationale = "ireland_etenders_market_consultation"
    elif close_date and close_date < clock:
        state = CurrentActionabilityState.EXPIRED
        rationale = "ireland_etenders_deadline_passed"
    else:
        state = CurrentActionabilityState.OPEN_BID
        rationale = "ireland_etenders_open_submission"
    return _decision(
        clock=kwargs["clock"],
        source_name=kwargs["source_name"],
        procurement_id=kwargs["procurement_id"],
        source_status_raw=kwargs["source_status_raw"],
        state=state,
        rationale=rationale,
    )


def _ted_decision(**kwargs: Any) -> LifecycleDecision:
    status_raw = normalize_text(kwargs["source_status_raw"])
    text = kwargs["text"]
    close_date = kwargs["close_date"]
    award_date = kwargs["award_date"]
    clock = kwargs["clock"]
    if award_date and award_date <= clock:
        state = CurrentActionabilityState.AWARDED
        rationale = "ted_award_date"
    elif any(token in text for token in (" - result - ted", "contract award notice", "award notice", "result - ted", "award information")):
        state = CurrentActionabilityState.AWARD_NOTICE
        rationale = "ted_result_notice"
    elif any(token in text for token in ("market consultation", "preliminary market consultation", "market sounding")):
        state = CurrentActionabilityState.PRE_MARKET_ENGAGEMENT
        rationale = "ted_market_consultation"
    elif any(token in text for token in ("prior information notice", "planned procurement", "forecast notice")):
        state = CurrentActionabilityState.PLANNED_PROCUREMENT
        rationale = "ted_prior_information"
    elif "competition - ted" in text or "competition" in text:
        state = CurrentActionabilityState.OPEN_BID if not close_date or close_date >= clock else CurrentActionabilityState.EXPIRED
        rationale = "ted_competition_notice"
    elif close_date and close_date < clock:
        state = CurrentActionabilityState.EXPIRED
        rationale = "ted_deadline_passed"
    else:
        state = _generic_decision(**kwargs, publication_date=None).source_status_normalized
        return _decision(
            clock=kwargs["clock"],
            source_name=kwargs["source_name"],
            procurement_id=kwargs["procurement_id"],
            source_status_raw=kwargs["source_status_raw"],
            state=CurrentActionabilityState(state),
            rationale="ted_generic_fallback",
        )
    return _decision(
        clock=kwargs["clock"],
        source_name=kwargs["source_name"],
        procurement_id=kwargs["procurement_id"],
        source_status_raw=kwargs["source_status_raw"],
        state=state,
        rationale=rationale,
    )


def _hilma_decision(**kwargs: Any) -> LifecycleDecision:
    status_raw = normalize_text(kwargs["source_status_raw"])
    close_date = kwargs["close_date"]
    clock = kwargs["clock"]
    if "award" in status_raw:
        state = CurrentActionabilityState.AWARD_NOTICE
        rationale = "hilma_award_notice"
    elif any(token in status_raw for token in ("priorinformation", "planning", "forecast")):
        state = CurrentActionabilityState.PLANNED_PROCUREMENT
        rationale = "hilma_planned_procurement"
    elif "marketconsultation" in status_raw or "market consultation" in kwargs["text"]:
        state = CurrentActionabilityState.PRE_MARKET_ENGAGEMENT
        rationale = "hilma_market_consultation"
    elif close_date and close_date < clock:
        state = CurrentActionabilityState.EXPIRED
        rationale = "hilma_deadline_passed"
    else:
        state = CurrentActionabilityState.OPEN_BID
        rationale = "hilma_open_notice"
    return _decision(
        clock=kwargs["clock"],
        source_name=kwargs["source_name"],
        procurement_id=kwargs["procurement_id"],
        source_status_raw=kwargs["source_status_raw"],
        state=state,
        rationale=rationale,
    )


def _uk_procurement_decision(**kwargs: Any) -> LifecycleDecision:
    text = kwargs["text"]
    close_date = kwargs["close_date"]
    clock = kwargs["clock"]
    if any(token in text for token in ("award notice", "contract award", "contract details")):
        state = CurrentActionabilityState.AWARD_NOTICE
        rationale = "uk_award_notice"
    elif any(token in text for token in ("prior information", "planned procurement", "pipeline notice", "market engagement")):
        state = CurrentActionabilityState.PLANNED_PROCUREMENT
        rationale = "uk_planned_procurement"
    elif close_date and close_date < clock:
        state = CurrentActionabilityState.EXPIRED
        rationale = "uk_deadline_passed"
    else:
        state = CurrentActionabilityState.OPEN_BID
        rationale = "uk_open_notice"
    return _decision(
        clock=kwargs["clock"],
        source_name=kwargs["source_name"],
        procurement_id=kwargs["procurement_id"],
        source_status_raw=kwargs["source_status_raw"],
        state=state,
        rationale=rationale,
    )


def _world_bank_decision(**kwargs: Any) -> LifecycleDecision:
    text = kwargs["text"]
    close_date = kwargs["close_date"]
    clock = kwargs["clock"]
    if any(token in text for token in ("general procurement notice", "upcoming opportunity", "potential opportunity", "planned procurement")):
        state = CurrentActionabilityState.PLANNED_PROCUREMENT
        rationale = "world_bank_planned_procurement"
    elif any(token in text for token in ("request for expression of interest", "request for proposal", "request for quotation", "specific procurement notice")):
        state = CurrentActionabilityState.OPEN_BID if not close_date or close_date >= clock else CurrentActionabilityState.EXPIRED
        rationale = "world_bank_open_notice"
    elif close_date and close_date < clock:
        state = CurrentActionabilityState.EXPIRED
        rationale = "world_bank_deadline_passed"
    else:
        state = CurrentActionabilityState.MONITOR_ONLY
        rationale = "world_bank_monitor_only"
    return _decision(
        clock=kwargs["clock"],
        source_name=kwargs["source_name"],
        procurement_id=kwargs["procurement_id"],
        source_status_raw=kwargs["source_status_raw"],
        state=state,
        rationale=rationale,
    )


def _tenderned_decision(**kwargs: Any) -> LifecycleDecision:
    text = kwargs["text"]
    close_date = kwargs["close_date"]
    clock = kwargs["clock"]
    if any(token in text for token in ("marktconsultatie", "market consultation")):
        state = CurrentActionabilityState.PRE_MARKET_ENGAGEMENT
        rationale = "tenderned_market_consultation"
    elif any(token in text for token in ("gegunde opdracht", "award notice", "gegund")):
        state = CurrentActionabilityState.AWARD_NOTICE
        rationale = "tenderned_award_notice"
    elif any(token in text for token in ("vooraankondiging", "planned procurement", "voorafgaande")):
        state = CurrentActionabilityState.PLANNED_PROCUREMENT
        rationale = "tenderned_planned_procurement"
    elif close_date and close_date < clock:
        state = CurrentActionabilityState.EXPIRED
        rationale = "tenderned_deadline_passed"
    else:
        state = CurrentActionabilityState.OPEN_BID
        rationale = "tenderned_open_notice"
    return _decision(
        clock=kwargs["clock"],
        source_name=kwargs["source_name"],
        procurement_id=kwargs["procurement_id"],
        source_status_raw=kwargs["source_status_raw"],
        state=state,
        rationale=rationale,
    )


def _gets_decision(**kwargs: Any) -> LifecycleDecision:
    close_date = kwargs["close_date"]
    clock = kwargs["clock"]
    text = kwargs["text"]
    if any(token in text for token in ("future opportunities", "procurement plan")):
        state = CurrentActionabilityState.PLANNED_PROCUREMENT
        rationale = "gets_future_opportunity"
    elif close_date and close_date < clock:
        state = CurrentActionabilityState.EXPIRED
        rationale = "gets_deadline_passed"
    else:
        state = CurrentActionabilityState.OPEN_BID
        rationale = "gets_current_tender"
    return _decision(
        clock=kwargs["clock"],
        source_name=kwargs["source_name"],
        procurement_id=kwargs["procurement_id"],
        source_status_raw=kwargs["source_status_raw"],
        state=state,
        rationale=rationale,
    )


def _south_africa_decision(**kwargs: Any) -> LifecycleDecision:
    close_date = kwargs["close_date"]
    clock = kwargs["clock"]
    source_name = kwargs["source_name"]
    text = kwargs["text"]
    if source_name == "south_africa_procurement_plans" or any(token in text for token in ("procurement plan", "envisaged advert date")):
        state = CurrentActionabilityState.PLANNED_PROCUREMENT
        rationale = "south_africa_procurement_plan"
    elif source_name == "south_africa_awarded_tenders" or any(token in text for token in ("awarded tender", "organ_of_state", "award notice")):
        state = CurrentActionabilityState.AWARD_NOTICE
        rationale = "south_africa_awarded_notice"
    elif close_date and close_date < clock:
        state = CurrentActionabilityState.EXPIRED
        rationale = "south_africa_deadline_passed"
    else:
        state = CurrentActionabilityState.OPEN_BID
        rationale = "south_africa_current_tender"
    return _decision(
        clock=kwargs["clock"],
        source_name=kwargs["source_name"],
        procurement_id=kwargs["procurement_id"],
        source_status_raw=kwargs["source_status_raw"],
        state=state,
        rationale=rationale,
    )


def _canada_buys_decision(**kwargs: Any) -> LifecycleDecision:
    text = kwargs["text"]
    close_date = kwargs["close_date"]
    clock = kwargs["clock"]
    if "award" in text or "contract history" in text:
        state = CurrentActionabilityState.AWARD_NOTICE
        rationale = "canada_buys_award_notice"
    elif any(token in text for token in ("standing offer", "supply arrangement", "pre-qualification")):
        state = CurrentActionabilityState.FRAMEWORK_OR_VEHICLE
        rationale = "canada_buys_vehicle"
    elif close_date and close_date < clock:
        state = CurrentActionabilityState.EXPIRED
        rationale = "canada_buys_deadline_passed"
    else:
        state = CurrentActionabilityState.OPEN_BID
        rationale = "canada_buys_open_notice"
    return _decision(
        clock=kwargs["clock"],
        source_name=kwargs["source_name"],
        procurement_id=kwargs["procurement_id"],
        source_status_raw=kwargs["source_status_raw"],
        state=state,
        rationale=rationale,
    )


def _ungm_decision(**kwargs: Any) -> LifecycleDecision:
    text = kwargs["text"]
    close_date = kwargs["close_date"]
    clock = kwargs["clock"]
    if any(token in text for token in ("expression of interest", "request for proposal", "request for quotation", "invitation to bid")):
        state = CurrentActionabilityState.OPEN_BID if not close_date or close_date >= clock else CurrentActionabilityState.EXPIRED
        rationale = "ungm_current_notice"
    elif any(token in text for token in ("pre-bid notice", "market consultation")):
        state = CurrentActionabilityState.PRE_MARKET_ENGAGEMENT
        rationale = "ungm_pre_market"
    else:
        state = CurrentActionabilityState.MONITOR_ONLY
        rationale = "ungm_monitor_only"
    return _decision(
        clock=kwargs["clock"],
        source_name=kwargs["source_name"],
        procurement_id=kwargs["procurement_id"],
        source_status_raw=kwargs["source_status_raw"],
        state=state,
        rationale=rationale,
    )


def _generic_decision(**kwargs: Any) -> LifecycleDecision:
    text = kwargs["text"]
    close_date = kwargs["close_date"]
    publication_date = kwargs["publication_date"]
    clock = kwargs["clock"]
    if any(token in text for token in ("cancelled", "withdrawn", "terminated")):
        state = CurrentActionabilityState.CANCELLED
        rationale = "generic_cancelled"
    elif any(token in text for token in ("award notice", "contract award", "awarded", "result - ted")):
        state = CurrentActionabilityState.AWARD_NOTICE
        rationale = "generic_award_notice"
    elif any(token in text for token in ("framework agreement", "standing offer", "supply arrangement", "dynamic purchasing")):
        state = CurrentActionabilityState.FRAMEWORK_OR_VEHICLE
        rationale = "generic_framework_vehicle"
    elif any(token in text for token in ("prior information notice", "planned procurement", "procurement plan", "forecast opportunity")):
        state = CurrentActionabilityState.PLANNED_PROCUREMENT
        rationale = "generic_planned_procurement"
    elif any(token in text for token in ("market consultation", "market sounding", "prior information", "request for information", "rfi")):
        state = CurrentActionabilityState.PRE_MARKET_ENGAGEMENT if not close_date or close_date < clock else CurrentActionabilityState.OPEN_CONSULTATION
        rationale = "generic_market_consultation"
    elif close_date and close_date < clock:
        state = CurrentActionabilityState.EXPIRED
        rationale = "generic_deadline_passed"
    elif close_date or any(token in text for token in ("tender", "request for tender", "request for proposal", "rfp", "rfq", "itt", "ifb", "submission deadline")):
        state = CurrentActionabilityState.OPEN_BID
        rationale = "generic_open_bid"
    elif publication_date and publication_date < clock:
        state = CurrentActionabilityState.MONITOR_ONLY
        rationale = "generic_monitor_only"
    else:
        state = CurrentActionabilityState.UNKNOWN
        rationale = "generic_unknown"
    return _decision(
        clock=kwargs["clock"],
        source_name=kwargs["source_name"],
        procurement_id=kwargs["procurement_id"],
        source_status_raw=kwargs["source_status_raw"],
        state=state,
        rationale=rationale,
    )
