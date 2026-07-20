from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Iterable

from d365opps.retrieval import load_retrieval_rules
from d365opps.schemas import MarketSignalDraft, OpportunityDraft, Scorecard
from d365opps.taxonomy import (
    APP_FAMILIES,
    BUSINESS_PROCESSES,
    COUNTRY_TO_REGION,
    PROCUREMENT_TERMS,
    SERVICE_TYPES,
)


def _normalize(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip().lower()


def _bucket_score(text: str, buckets: Iterable) -> tuple[str, float]:
    best_name = "General"
    best_score = 0.0
    for bucket in buckets:
        hits = sum(1 for keyword in bucket.keywords if keyword in text)
        if hits > best_score:
            best_name = bucket.name
            best_score = float(hits)
    return best_name, best_score


RULES = load_retrieval_rules()


def infer_d365_confidence(text: str, evidence=None) -> float:
    normalized = _normalize(text)
    positive_hits = len(getattr(evidence, "matched_positive_terms", None) or RULES.match_positive_terms(normalized))
    negative_hits = len(getattr(evidence, "matched_negative_terms", None) or RULES.match_negative_terms(normalized))
    service_hits = len(getattr(evidence, "service_mentions", None) or RULES.match_terms(normalized, RULES.service_verbs))
    procurement_hits = len(RULES.match_terms(normalized, RULES.procurement_verbs))
    retrieval_boost = min(0.55, (float(getattr(evidence, "retrieval_score", 0.0) or 0.0) / 100.0) * 0.55)
    confidence = min(1.0, (positive_hits * 0.22) + (service_hits * 0.06) + (procurement_hits * 0.04) + retrieval_boost)
    confidence = max(0.0, confidence - (negative_hits * 0.18))
    if getattr(evidence, "exclusion_reason", None):
        confidence = min(confidence, 0.12)
    return round(confidence, 3)


def infer_evidence_grade(text: str, has_buyer: bool, has_response_path: bool, has_deadline: bool) -> str:
    normalized = _normalize(text)
    procurement_hit = any(term in normalized for term in PROCUREMENT_TERMS)
    if procurement_hit and has_response_path and has_deadline:
        return "A1"
    if has_buyer and (has_response_path or procurement_hit):
        return "A2"
    if has_buyer or has_deadline:
        return "B1"
    return "C1"


@dataclass(slots=True)
class ClassificationResult:
    opportunity: OpportunityDraft | None = None
    signal: MarketSignalDraft | None = None


class OpportunityClassifier:
    def classify(self, evidence, source_lane: str, default_region: str | None = None) -> ClassificationResult:
        full_text = " ".join(
            filter(
                None,
                [
                    evidence.title,
                    evidence.summary,
                    evidence.raw_excerpt,
                    " ".join(getattr(evidence, "lot_titles", []) or []),
                    " ".join(getattr(evidence, "product_mentions", []) or []),
                    " ".join(getattr(evidence, "service_mentions", []) or []),
                ],
            )
        )
        normalized = _normalize(full_text)
        d365_confidence = infer_d365_confidence(normalized, evidence)
        app_family, _ = _bucket_score(normalized, APP_FAMILIES)
        business_process, _ = _bucket_score(normalized, BUSINESS_PROCESSES)
        service_type, _ = _bucket_score(normalized, SERVICE_TYPES)

        signal_lane = getattr(evidence, "signal_lane", None)
        recommended_action = getattr(evidence, "recommended_action", None)
        route_to_market = getattr(evidence, "route_to_market", None)
        if signal_lane is None and source_lane == "opportunity":
            if evidence.response_url and evidence.close_date:
                signal_lane = "formal_procurement"
                recommended_action = recommended_action or "bid_now"
                route_to_market = route_to_market or "formal_bid"
            elif evidence.buyer_name:
                signal_lane = "pre_positioning"
                recommended_action = recommended_action or "pre_position"
                route_to_market = route_to_market or "framework_vehicle"
        recommended_action = recommended_action or "monitor"
        route_to_market = route_to_market or "unknown"

        evidence_grade = infer_evidence_grade(
            full_text,
            has_buyer=bool(evidence.buyer_name),
            has_response_path=bool(evidence.response_url),
            has_deadline=bool(evidence.close_date),
        )
        region = default_region or COUNTRY_TO_REGION.get((evidence.buyer_country or "").upper())

        if (
            signal_lane is None
            or recommended_action == "reject"
            or d365_confidence < 0.15
            or (source_lane == "signal" and signal_lane == "direct_outreach" and float(getattr(evidence, "retrieval_score", 0.0) or 0.0) < 30)
        ):
            signal = MarketSignalDraft(
                title=evidence.title,
                summary=evidence.summary,
                signal_type=evidence.record_type,
                source_url=evidence.source_url,
                signal_lane=signal_lane or "direct_outreach",
                recommended_action=recommended_action,
                route_to_market=route_to_market,
                region=region,
                country=evidence.buyer_country,
                confidence=round(max(d365_confidence, float(getattr(evidence, "retrieval_score", 0.0) or 0.0) / 100.0, 0.1), 3),
                retrieval_score=float(getattr(evidence, "retrieval_score", 0.0) or 0.0),
                source_trust=float(getattr(evidence, "source_trust", 0.0) or 0.0),
                account_heat_score=float(getattr(evidence, "account_heat_score", 0.0) or 0.0),
                trigger_type=getattr(evidence, "trigger_type", None),
                trigger_strength=float(getattr(evidence, "trigger_strength", 0.0) or 0.0),
                public_access_mode=getattr(evidence, "public_access_mode", "public"),
                english_evidence_source=getattr(evidence, "english_evidence_source", None),
                buyer_intent_evidence=dict(getattr(evidence, "buyer_intent_evidence", {}) or {}),
                legacy_evidence=dict(getattr(evidence, "legacy_evidence", {}) or {}),
                query_family=getattr(evidence, "query_family", None),
                discovery_query_id=getattr(evidence, "discovery_query_id", None),
                discovery_query_text=getattr(evidence, "discovery_query_text", None),
                portal_fingerprint=getattr(evidence, "portal_fingerprint", None),
                known_blind_spot_reason=getattr(evidence, "known_blind_spot_reason", None),
                corroboration_count=int(getattr(evidence, "corroboration_count", 1) or 1),
                tags=sorted(set(evidence.tags)),
                raw_excerpt=evidence.raw_excerpt,
            )
            return ClassificationResult(signal=signal)

        scorecard = self.score(
            retrieval_score=float(getattr(evidence, "retrieval_score", 0.0) or 0.0),
            formal_opportunity_score=float(getattr(evidence, "formal_opportunity_score", 0.0) or 0.0),
            pre_position_score=float(getattr(evidence, "pre_position_score", 0.0) or 0.0),
            account_intent_score=float(getattr(evidence, "account_intent_score", 0.0) or 0.0),
            install_base_trigger_score=float(getattr(evidence, "install_base_trigger_score", 0.0) or 0.0),
            service_fit_score=float(getattr(evidence, "service_fit_score", 0.0) or 0.0),
            buyer_quality_score=float(getattr(evidence, "buyer_quality_score", 0.0) or 0.0),
            corroboration_score=float(getattr(evidence, "corroboration_score", 0.0) or 0.0),
            recommendation=recommended_action,
        )
        next_action = {
            "bid_now": "Open the live notice, confirm mandatory bid documents, and prepare the response.",
            "pre_position": "Map the vehicle, incumbent, and renewal path before outreach.",
            "renewal_watch": "Track incumbent timing, renewal windows, and the likely route back to market.",
            "award_watch": "Track the award and incumbent position for follow-on work or renewal risk.",
            "install_base_trigger": "Review the public product footprint and prepare a trigger-based outreach brief.",
            "outreach_now": "Prepare the account brief and reach out using the public evidence trail.",
            "monitor": "Track follow-on notices, awards, and buyer signals.",
            "reject": "Retain for audit only.",
        }[scorecard.recommendation]
        dedupe_fingerprint = self.build_fingerprint(
            buyer_name=evidence.buyer_name,
            title=evidence.title,
            country=evidence.buyer_country,
            procurement_id=evidence.procurement_id,
            close_date=evidence.close_date,
        )
        opportunity = OpportunityDraft(
            title=evidence.title,
            summary=evidence.summary,
            app_family=app_family,
            business_process=business_process,
            service_type=service_type,
            evidence_grade=evidence_grade,
            signal_lane=signal_lane,
            recommended_action=recommended_action,
            route_to_market=route_to_market,
            d365_confidence=d365_confidence,
            procurement_type=evidence.procurement_type,
            country=evidence.buyer_country,
            buyer_name=evidence.buyer_name,
            publication_date=evidence.publication_date,
            close_date=evidence.close_date,
            budget_value=evidence.budget_value,
            budget_currency=evidence.budget_currency,
            source_url=evidence.source_url,
            response_url=evidence.response_url,
            procurement_id=evidence.procurement_id,
            raw_excerpt=evidence.raw_excerpt,
            retrieval_score=float(getattr(evidence, "retrieval_score", 0.0) or 0.0),
            formal_opportunity_score=float(getattr(evidence, "formal_opportunity_score", 0.0) or 0.0),
            pre_position_score=float(getattr(evidence, "pre_position_score", 0.0) or 0.0),
            account_intent_score=float(getattr(evidence, "account_intent_score", 0.0) or 0.0),
            install_base_trigger_score=float(getattr(evidence, "install_base_trigger_score", 0.0) or 0.0),
            service_fit_score=float(getattr(evidence, "service_fit_score", 0.0) or 0.0),
            buyer_quality_score=float(getattr(evidence, "buyer_quality_score", 0.0) or 0.0),
            corroboration_score=float(getattr(evidence, "corroboration_score", 0.0) or 0.0),
            opportunity_score=scorecard.total_score,
            source_trust=float(getattr(evidence, "source_trust", 0.0) or 0.0),
            matched_positive_terms=list(getattr(evidence, "matched_positive_terms", []) or []),
            matched_negative_terms=list(getattr(evidence, "matched_negative_terms", []) or []),
            language_status=getattr(evidence, "language_status", None),
            english_evidence_source=getattr(evidence, "english_evidence_source", None),
            corroboration_count=int(getattr(evidence, "corroboration_count", 1) or 1),
            discovery_query_id=getattr(evidence, "discovery_query_id", None),
            discovery_query_text=getattr(evidence, "discovery_query_text", None),
            query_family=getattr(evidence, "query_family", None),
            source_discovery_confidence=float(getattr(evidence, "source_discovery_confidence", 0.0) or 0.0),
            public_access_mode=getattr(evidence, "public_access_mode", "public"),
            account_heat_score=float(getattr(evidence, "account_heat_score", 0.0) or 0.0),
            installed_product_guess=getattr(evidence, "installed_product_guess", None),
            installed_product_evidence=getattr(evidence, "installed_product_evidence", None),
            trigger_type=getattr(evidence, "trigger_type", None),
            trigger_strength=float(getattr(evidence, "trigger_strength", 0.0) or 0.0),
            procurement_cycle_stage=getattr(evidence, "procurement_cycle_stage", None),
            vehicle_type=getattr(evidence, "vehicle_type", None),
            incumbent_vendor=getattr(evidence, "incumbent_vendor", None),
            incumbent_expiry_guess=getattr(evidence, "incumbent_expiry_guess", None),
            buyer_intent_evidence=dict(getattr(evidence, "buyer_intent_evidence", {}) or {}),
            legacy_evidence=dict(getattr(evidence, "legacy_evidence", {}) or {}),
            portal_fingerprint=getattr(evidence, "portal_fingerprint", None),
            known_blind_spot_reason=getattr(evidence, "known_blind_spot_reason", None),
            exclusion_reason=getattr(evidence, "exclusion_reason", None),
            scorecard=scorecard,
            next_action=next_action,
            dedupe_fingerprint=dedupe_fingerprint,
            tags=sorted(set(evidence.tags)),
        )
        return ClassificationResult(opportunity=opportunity)

    def build_fingerprint(
        self,
        buyer_name: str | None,
        title: str,
        country: str | None,
        procurement_id: str | None,
        close_date: datetime | None,
    ) -> str:
        if procurement_id:
            return f"procurement:{_normalize(procurement_id)}"
        base = "|".join(
            [
                _normalize(buyer_name),
                _normalize(title),
                (country or "").upper(),
                close_date.date().isoformat() if close_date else "",
            ]
        )
        return hashlib.sha1(base.encode("utf-8")).hexdigest()

    def score(
        self,
        *,
        retrieval_score: float,
        formal_opportunity_score: float,
        pre_position_score: float,
        account_intent_score: float,
        install_base_trigger_score: float,
        service_fit_score: float,
        buyer_quality_score: float,
        corroboration_score: float,
        recommendation: str,
    ) -> Scorecard:
        total_score = int(
            (
                retrieval_score * 0.2
                + max(formal_opportunity_score, pre_position_score, account_intent_score, install_base_trigger_score) * 0.24
                + service_fit_score * 0.16
                + buyer_quality_score * 0.14
                + corroboration_score * 0.1
                + formal_opportunity_score * 0.08
                + pre_position_score * 0.04
                + account_intent_score * 0.02
                + install_base_trigger_score * 0.02
            )
        )
        return Scorecard(
            retrieval_score=int(retrieval_score),
            formal_opportunity_score=int(formal_opportunity_score),
            pre_position_score=int(pre_position_score),
            account_intent_score=int(account_intent_score),
            install_base_trigger_score=int(install_base_trigger_score),
            service_fit_score=int(service_fit_score),
            buyer_quality_score=int(buyer_quality_score),
            corroboration_score=int(corroboration_score),
            total_score=total_score,
            recommendation=recommendation,
        )
