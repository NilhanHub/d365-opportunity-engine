from __future__ import annotations

from datetime import UTC, datetime

from d365opps.pitchability import evaluate_record


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


SCENARIO_AS_OF = _dt("2026-04-15T00:00:00")


def test_market_consultation_stays_current_pre_position() -> None:
    row = {
        "title": "Market Consultation Microsoft Power Platform",
        "summary": "TenneT is seeking market consultation support for Microsoft Power Platform services.",
        "buyer_name": "TenneT",
        "source_url": "https://ted.europa.eu/notice/238986-2026",
        "recommended_action": "pre_position",
        "opportunity_score": 82,
        "close_date": _dt("2026-05-10T12:00:00"),
        "matched_positive_terms": ["Power Platform"],
    }

    evaluation = evaluate_record(row, today=SCENARIO_AS_OF)

    assert evaluation.allowed is True
    assert evaluation.current_actionability_state == "pre_market_engagement"
    assert evaluation.commercial_motion == "pre_position"
    assert evaluation.effective_recommended_action == "pre_position"
    assert evaluation.sales_handoff_state == "seller_ready"


def test_market_consultation_can_still_be_seller_ready_at_pre_position_score_floor() -> None:
    row = {
        "title": "Market Consultation Microsoft Power Platform",
        "summary": "TenneT is seeking supplier feedback on a Microsoft Power Platform framework and onboarding approach.",
        "buyer_name": "TenneT TSO B.V.",
        "source_url": "https://www.tenderned.nl/aankondigingen/overzicht/418983",
        "recommended_action": "pre_position",
        "opportunity_score": 52,
        "publication_date": _dt("2026-04-08T00:00:00"),
        "matched_positive_terms": ["Power Platform"],
    }

    evaluation = evaluate_record(row, today=_dt("2026-04-15T00:00:00"))

    assert evaluation.allowed is True
    assert evaluation.current_actionability_state == "pre_market_engagement"
    assert evaluation.effective_recommended_action == "pre_position"
    assert evaluation.sales_handoff_state == "seller_ready"
    assert "score_below_threshold" not in evaluation.reasons


def test_finnvera_can_be_current_but_not_pitchable_without_seller_english() -> None:
    row = {
        "title": "Microsoft Power Platform -asiantuntijapalvelut",
        "summary": "Hankinnan kohteena on Microsoft Power Platform -asiantuntijapalvelut ja niihin liittyvät tukipalvelut.",
        "buyer_name": "Finnvera",
        "source_url": "https://ted.europa.eu/notice/197492-2026",
        "recommended_action": "pre_position",
        "opportunity_score": 78,
        "close_date": _dt("2026-05-20T12:00:00"),
        "matched_positive_terms": ["Microsoft Power Platform"],
    }

    evaluation = evaluate_record(row, today=SCENARIO_AS_OF)

    assert evaluation.allowed is False
    assert evaluation.current_actionability_state == "open_bid"
    assert "english_insufficient" in evaluation.reasons
    assert evaluation.sales_handoff_state == "research_ready"


def test_business_finland_expired_notice_is_not_pitchable() -> None:
    row = {
        "title": "Tekninen Microsoft Dynamics 365 CRM -konsultointi",
        "summary": "Tekninen Microsoft Dynamics 365 CRM -konsultointi ja kehitys.",
        "buyer_name": "Business Finland",
        "source_url": "https://ted.europa.eu/notice/244716-2026",
        "recommended_action": "bid_now",
        "opportunity_score": 81,
        "close_date": _dt("2026-03-01T12:00:00"),
        "matched_positive_terms": ["Microsoft Dynamics", "Dynamics 365 CRM"],
    }

    evaluation = evaluate_record(row, today=_dt("2026-04-14T00:00:00"))

    assert evaluation.allowed is False
    assert evaluation.current_actionability_state == "expired"
    assert "expired" in evaluation.reasons
    assert evaluation.sales_handoff_state == "monitor_only"


def test_business_finland_ted_regression_without_close_date_is_expired() -> None:
    row = {
        "title": "Finland – IT services: consulting, software development, Internet and support – Tekninen Microsoft Dynamics 365 CRM -konsultointi",
        "buyer_name": "Business Finland Oy; Innovaatiorahoituskeskus Business Finland",
        "source_url": "https://ted.europa.eu/notice/244716-2026",
        "procurement_id": "244716-2026",
        "recommended_action": "pre_position",
        "opportunity_score": 59,
        "matched_positive_terms": ["Microsoft Dynamics", "Dynamics 365 CRM"],
    }

    evaluation = evaluate_record(row, today=_dt("2026-04-14T00:00:00"))

    assert evaluation.allowed is False
    assert evaluation.current_actionability_state == "expired"
    assert "expired" in evaluation.reasons
    assert "not_pitch_motion" in evaluation.reasons


def test_irish_red_cross_awarded_notice_is_not_pitchable_now() -> None:
    row = {
        "title": "Provision of a Customer Relationship Management (CRM) System built on Microsoft Dynamics in a client tenant",
        "summary": "Awarded customer relationship management implementation built on Microsoft Dynamics.",
        "buyer_name": "Irish Red Cross",
        "source_url": "https://www.etenders.gov.ie/epps/prepareViewCfTWS.do?resourceId=6999275",
        "recommended_action": "bid_now",
        "opportunity_score": 83,
        "matched_positive_terms": ["Microsoft Dynamics"],
        "extracted_data": {"CFT_STATUS": "Awarded"},
    }

    evaluation = evaluate_record(row, today=SCENARIO_AS_OF)

    assert evaluation.allowed is False
    assert evaluation.current_actionability_state == "awarded"
    assert "awarded" in evaluation.reasons
    assert evaluation.sales_handoff_state == "monitor_only"


def test_irish_red_cross_ted_regression_is_awarded_even_without_status_field() -> None:
    row = {
        "title": "Ireland – IT services: consulting, software development, Internet and support – Provision of a Customer Relationship Management (CRM) System built on Microsoft Dynamics in a client tenant",
        "buyer_name": "Irish Red Cross",
        "source_url": "https://ted.europa.eu/notice/6999275",
        "procurement_id": "6999275",
        "recommended_action": "bid_now",
        "opportunity_score": 56,
        "matched_positive_terms": ["Microsoft Dynamics"],
    }

    evaluation = evaluate_record(row, today=SCENARIO_AS_OF)

    assert evaluation.allowed is False
    assert evaluation.current_actionability_state == "awarded"
    assert "awarded" in evaluation.reasons


def test_generic_on_premises_notice_is_not_treated_as_d365_anchor() -> None:
    row = {
        "title": "Student Record System and Timetabling Solution",
        "summary": "The university currently hosts its student records system in an on-premises environment and wants a new SaaS platform.",
        "buyer_name": "University Example",
        "source_url": "https://example.com/student-records",
        "recommended_action": "bid_now",
        "opportunity_score": 84,
        "close_date": _dt("2026-05-30T12:00:00"),
        "signal_lane": "install_base_trigger",
        "matched_positive_terms": ["on-premises"],
        "legacy_evidence_json": {"legacy_terms": ["on-premises"], "trigger_terms": ["on-premises"]},
    }

    evaluation = evaluate_record(row, today=SCENARIO_AS_OF)

    assert evaluation.allowed is False
    assert "no_d365_anchor" in evaluation.reasons


def test_customer_engagement_without_dynamics_anchor_is_rejected() -> None:
    row = {
        "title": "Customer Engagement software licences provision",
        "summary": "Supply of customer engagement software licences for internal service desk teams.",
        "buyer_name": "NHS Example",
        "source_url": "https://example.com/customer-engagement",
        "recommended_action": "bid_now",
        "opportunity_score": 75,
        "close_date": _dt("2026-05-10T12:00:00"),
        "matched_positive_terms": ["Customer Engagement"],
    }

    evaluation = evaluate_record(row, today=SCENARIO_AS_OF)

    assert evaluation.allowed is False
    assert "no_d365_anchor" in evaluation.reasons


def test_real_d365_tender_stays_pitch_now_when_framework_is_only_descriptive_word() -> None:
    row = {
        "title": "Call for Tender for the Provision of Specialist Microsoft Dynamics 365 and Power Platform Development Services",
        "summary": "This project will establish a scalable digital survey framework to support Ireland's obligations using Microsoft Dynamics 365, Power Pages, Dataverse, and Power Automate.",
        "buyer_name": "BIM",
        "source_url": "https://www.etenders.gov.ie/epps/prepareViewCfTWS.do?resourceId=7797171",
        "recommended_action": "bid_now",
        "opportunity_score": 74,
        "close_date": _dt("2026-04-22T12:00:00"),
        "matched_positive_terms": ["Microsoft Dynamics", "Dynamics 365", "Power Platform", "Dataverse"],
    }

    evaluation = evaluate_record(row, today=SCENARIO_AS_OF)

    assert evaluation.allowed is True
    assert evaluation.current_actionability_state == "open_bid"
    assert evaluation.commercial_motion == "pitch_now"
    assert evaluation.effective_recommended_action == "bid_now"
    assert evaluation.sales_handoff_state == "seller_ready"


def test_open_bid_pre_position_record_is_promoted_to_pitch_now() -> None:
    row = {
        "title": "Microsoft Power Platform specialist services",
        "summary": "Current open procurement for Microsoft Power Platform specialist services.",
        "buyer_name": "Example Buyer",
        "source_url": "https://example.com/finnvera-like",
        "recommended_action": "pre_position",
        "opportunity_score": 75,
        "close_date": _dt("2026-05-20T12:00:00"),
        "matched_positive_terms": ["Microsoft Power Platform"],
    }

    evaluation = evaluate_record(row, today=SCENARIO_AS_OF)

    assert evaluation.allowed is True
    assert evaluation.current_actionability_state == "open_bid"
    assert evaluation.commercial_motion == "pitch_now"
    assert evaluation.effective_recommended_action == "bid_now"


def test_cnam_closed_submission_is_not_pitchable_now() -> None:
    row = {
        "title": "Microsoft Application Development and Data Services Framework",
        "buyer_name": "Coimisiún na Meán",
        "procurement_id": "7465293",
        "source_url": "https://www.etenders.gov.ie/epps/prepareViewCfTWS.do?resourceId=7465293",
        "recommended_action": "bid_now",
        "opportunity_score": 76,
        "matched_positive_terms": ["Microsoft"],
        "close_date": _dt("2026-04-01T12:00:00"),
    }

    evaluation = evaluate_record(row, today=_dt("2026-04-14T00:00:00"))

    assert evaluation.allowed is False
    assert evaluation.current_actionability_state == "closed_submission"
    assert "closed_submission" in evaluation.reasons
    assert evaluation.sales_handoff_state == "monitor_only"


def test_bid_now_without_close_date_can_stay_seller_ready_when_source_explicitly_signals_open_state() -> None:
    row = {
        "title": "Request for Tender for Microsoft Dynamics 365 implementation services",
        "buyer_name": "Example Buyer",
        "recommended_action": "bid_now",
        "opportunity_score": 79,
        "matched_positive_terms": ["Microsoft Dynamics", "Dynamics 365"],
        "source_url": "https://example.com/no-close-date",
        "summary": "Open tender for Microsoft Dynamics 365 implementation services.",
    }

    evaluation = evaluate_record(row, today=_dt("2026-04-14T00:00:00"))

    assert evaluation.allowed is True
    assert evaluation.source_verified_open_without_close_date is True
    assert evaluation.sales_handoff_state == "seller_ready"


def test_ted_competition_notice_without_close_date_uses_source_verified_open_state() -> None:
    row = {
        "title": "Ireland - IT services - Microsoft Dynamics 365 implementation services",
        "buyer_name": "Example Buyer",
        "recommended_action": "bid_now",
        "opportunity_score": 79,
        "matched_positive_terms": ["Microsoft Dynamics", "Dynamics 365"],
        "source_url": "https://ted.europa.eu/en/notice/-/detail/123456-2026",
        "notice_type": "Competition - TED",
        "summary": "Competition notice for Microsoft Dynamics 365 implementation services.",
    }

    evaluation = evaluate_record(row, today=_dt("2026-04-15T00:00:00"))

    assert evaluation.allowed is True
    assert evaluation.current_actionability_state == "open_bid"
    assert evaluation.source_verified_open_without_close_date is True
    assert "missing_close_date" not in evaluation.reasons


def test_ted_generic_open_notice_without_close_date_can_stay_seller_ready() -> None:
    row = {
        "title": "France - IT services - Service de Maintenance et d'Assistance et Maintenance Evolutive du logiciel Microsoft Dynamics 365",
        "buyer_name": "Example Buyer",
        "recommended_action": "bid_now",
        "opportunity_score": 78,
        "matched_positive_terms": ["Microsoft Dynamics", "Dynamics 365"],
        "source_url": "https://ted.europa.eu/en/notice/-/detail/146814-2026",
        "notice_type": "TED notice",
        "procurement_type": "Request for Tender",
        "summary": "Microsoft Dynamics 365 maintenance and support services.",
    }

    evaluation = evaluate_record(row, today=_dt("2026-04-15T00:00:00"))

    assert evaluation.allowed is True
    assert evaluation.current_actionability_state == "open_bid"
    assert evaluation.source_verified_open_without_close_date is True
    assert "missing_close_date" not in evaluation.reasons


def test_iwa_closed_submission_is_not_pitchable_now() -> None:
    row = {
        "title": "IWA Rostering and Time and Attendance Solution",
        "buyer_name": "Irish Wheelchair Association",
        "procurement_id": "7417532",
        "source_url": "https://www.etenders.gov.ie/epps/prepareViewCfTWS.do?resourceId=7417532",
        "recommended_action": "bid_now",
        "opportunity_score": 71,
        "matched_positive_terms": ["Microsoft"],
    }

    evaluation = evaluate_record(row, today=_dt("2026-04-14T00:00:00"))

    assert evaluation.allowed is False
    assert evaluation.current_actionability_state == "closed_submission"
    assert "closed_submission" in evaluation.reasons


def test_department_of_transport_award_is_not_pitchable_now() -> None:
    row = {
        "title": "Request for Tender for the provision of Microsoft SharePoint and Power Platform Support and Drawdown Expertise",
        "buyer_name": "Department of Transport",
        "procurement_id": "684084-2025",
        "source_url": "https://ted.europa.eu/notice/684084-2025",
        "recommended_action": "bid_now",
        "opportunity_score": 78,
        "matched_positive_terms": ["Microsoft", "Power Platform"],
    }

    evaluation = evaluate_record(row, today=_dt("2026-04-14T00:00:00"))

    assert evaluation.allowed is False
    assert evaluation.current_actionability_state == "awarded"
    assert "awarded" in evaluation.reasons


def test_comreg_award_notice_is_not_pitchable_now() -> None:
    row = {
        "title": "Business Central Development and Support",
        "buyer_name": "Commission for Communications Regulation",
        "procurement_id": "151212-2026",
        "source_url": "https://ted.europa.eu/notice/151212-2026",
        "recommended_action": "bid_now",
        "opportunity_score": 73,
        "matched_positive_terms": ["Business Central"],
    }

    evaluation = evaluate_record(row, today=_dt("2026-04-14T00:00:00"))

    assert evaluation.allowed is False
    assert evaluation.current_actionability_state == "award_notice"
    assert "award_notice" in evaluation.reasons
