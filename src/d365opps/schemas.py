from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl


EvidenceGrade = Literal["A1", "A2", "B1", "C1"]
SignalLane = Literal["formal_procurement", "pre_positioning", "direct_outreach", "install_base_trigger"]
PursuitRecommendation = Literal[
    "bid_now",
    "pre_position",
    "renewal_watch",
    "award_watch",
    "install_base_trigger",
    "outreach_now",
    "monitor",
    "reject",
]
RouteToMarket = Literal[
    "formal_bid",
    "framework_vehicle",
    "vendor_registration",
    "renewal_watch",
    "direct_outreach",
    "partner_with_incumbent",
    "unknown",
]
PublicAccessMode = Literal["public", "account_optional", "account_required", "invitation_only", "unsupported"]
CurrentActionabilityState = Literal[
    "open_bid",
    "open_consultation",
    "pre_market_engagement",
    "planned_procurement",
    "framework_or_vehicle",
    "award_notice",
    "contract_details_only",
    "closed_submission",
    "expired",
    "cancelled",
    "awarded",
    "monitor_only",
    "unknown",
]


class FetchedDocument(BaseModel):
    external_id: str
    canonical_url: str
    document_url: str
    content_type: str
    payload: bytes
    published_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class FetchBatch(BaseModel):
    documents: list[FetchedDocument]
    next_cursor: str | None = None


class ExtractedEvidence(BaseModel):
    record_type: str = "notice"
    title: str
    summary: str | None = None
    buyer_name: str | None = None
    buyer_country: str | None = None
    buyer_region: str | None = None
    notice_type: str | None = None
    procurement_type: str | None = None
    publication_date: datetime | None = None
    close_date: datetime | None = None
    budget_value: Decimal | None = None
    budget_currency: str | None = None
    source_url: str
    response_url: str | None = None
    attachment_urls: list[str] = Field(default_factory=list)
    attachment_metadata: list[dict[str, Any]] = Field(default_factory=list)
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    cpv_codes: list[str] = Field(default_factory=list)
    lot_titles: list[str] = Field(default_factory=list)
    product_mentions: list[str] = Field(default_factory=list)
    service_mentions: list[str] = Field(default_factory=list)
    classification_codes: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    procurement_id: str | None = None
    raw_excerpt: str | None = None
    acquisition_method: str | None = None
    source_provenance: dict[str, Any] = Field(default_factory=dict)
    language_status: str | None = None
    language_details: dict[str, Any] = Field(default_factory=dict)
    english_evidence_source: str | None = None
    current_actionability_state: CurrentActionabilityState | None = None
    english_sufficiency_score: float = 0.0
    english_shell_only_flag: bool = False
    seller_readable_summary_en: str | None = None
    seller_readable_title_en_flag: bool = False
    retrieval_score: float = 0.0
    formal_opportunity_score: float = 0.0
    pre_position_score: float = 0.0
    account_intent_score: float = 0.0
    install_base_trigger_score: float = 0.0
    service_fit_score: float = 0.0
    buyer_quality_score: float = 0.0
    corroboration_score: float = 0.0
    source_trust: float = 0.0
    matched_positive_terms: list[str] = Field(default_factory=list)
    matched_negative_terms: list[str] = Field(default_factory=list)
    corroboration_count: int = 0
    discovery_query_id: str | None = None
    discovery_query_text: str | None = None
    query_family: str | None = None
    source_discovery_confidence: float = 0.0
    signal_lane: SignalLane | None = None
    recommended_action: PursuitRecommendation | None = None
    route_to_market: RouteToMarket | None = None
    account_heat_score: float = 0.0
    installed_product_guess: str | None = None
    installed_product_evidence: str | None = None
    trigger_type: str | None = None
    trigger_strength: float = 0.0
    procurement_cycle_stage: str | None = None
    vehicle_type: str | None = None
    incumbent_vendor: str | None = None
    incumbent_expiry_guess: str | None = None
    buyer_intent_evidence: dict[str, Any] = Field(default_factory=dict)
    legacy_evidence: dict[str, Any] = Field(default_factory=dict)
    portal_fingerprint: str | None = None
    public_access_mode: PublicAccessMode = "public"
    known_blind_spot_reason: str | None = None
    exclusion_reason: str | None = None
    extracted_data: dict[str, Any] = Field(default_factory=dict)


class EnrichmentResult(BaseModel):
    organization_name: str
    normalized_name: str
    website_domain: str | None = None
    country: str | None = None
    region: str | None = None
    industry: str | None = None
    size_band: str | None = None
    enrichment_confidence: float = 0.0
    provenance: dict[str, Any] = Field(default_factory=dict)
    public_contacts: list[dict[str, Any]] = Field(default_factory=list)


class Scorecard(BaseModel):
    retrieval_score: int
    formal_opportunity_score: int
    pre_position_score: int
    account_intent_score: int
    install_base_trigger_score: int
    service_fit_score: int
    buyer_quality_score: int
    corroboration_score: int
    total_score: int
    recommendation: PursuitRecommendation


class OpportunityDraft(BaseModel):
    title: str
    summary: str | None = None
    app_family: str
    business_process: str
    service_type: str
    evidence_grade: EvidenceGrade
    signal_lane: SignalLane
    recommended_action: PursuitRecommendation
    route_to_market: RouteToMarket
    d365_confidence: float
    procurement_type: str | None = None
    country: str | None = None
    buyer_name: str | None = None
    publication_date: datetime | None = None
    close_date: datetime | None = None
    budget_value: Decimal | None = None
    budget_currency: str | None = None
    source_url: str
    response_url: str | None = None
    procurement_id: str | None = None
    raw_excerpt: str | None = None
    retrieval_score: float = 0.0
    formal_opportunity_score: float = 0.0
    pre_position_score: float = 0.0
    account_intent_score: float = 0.0
    install_base_trigger_score: float = 0.0
    service_fit_score: float = 0.0
    buyer_quality_score: float = 0.0
    corroboration_score: float = 0.0
    opportunity_score: int = 0
    source_trust: float = 0.0
    matched_positive_terms: list[str] = Field(default_factory=list)
    matched_negative_terms: list[str] = Field(default_factory=list)
    language_status: str | None = None
    english_evidence_source: str | None = None
    current_actionability_state: CurrentActionabilityState | None = None
    english_sufficiency_score: float = 0.0
    english_shell_only_flag: bool = False
    seller_readable_summary_en: str | None = None
    seller_readable_title_en_flag: bool = False
    corroboration_count: int = 1
    discovery_query_id: str | None = None
    discovery_query_text: str | None = None
    query_family: str | None = None
    source_discovery_confidence: float = 0.0
    public_access_mode: PublicAccessMode = "public"
    account_heat_score: float = 0.0
    installed_product_guess: str | None = None
    installed_product_evidence: str | None = None
    trigger_type: str | None = None
    trigger_strength: float = 0.0
    procurement_cycle_stage: str | None = None
    vehicle_type: str | None = None
    incumbent_vendor: str | None = None
    incumbent_expiry_guess: str | None = None
    buyer_intent_evidence: dict[str, Any] = Field(default_factory=dict)
    legacy_evidence: dict[str, Any] = Field(default_factory=dict)
    portal_fingerprint: str | None = None
    known_blind_spot_reason: str | None = None
    exclusion_reason: str | None = None
    scorecard: Scorecard
    next_action: str
    dedupe_fingerprint: str
    tags: list[str] = Field(default_factory=list)


class MarketSignalDraft(BaseModel):
    title: str
    summary: str | None = None
    signal_type: str
    source_url: str
    signal_lane: SignalLane
    recommended_action: PursuitRecommendation
    route_to_market: RouteToMarket
    region: str | None = None
    country: str | None = None
    confidence: float
    retrieval_score: float = 0.0
    source_trust: float = 0.0
    account_heat_score: float = 0.0
    trigger_type: str | None = None
    trigger_strength: float = 0.0
    public_access_mode: PublicAccessMode = "public"
    english_evidence_source: str | None = None
    buyer_intent_evidence: dict[str, Any] = Field(default_factory=dict)
    legacy_evidence: dict[str, Any] = Field(default_factory=dict)
    query_family: str | None = None
    discovery_query_id: str | None = None
    discovery_query_text: str | None = None
    portal_fingerprint: str | None = None
    known_blind_spot_reason: str | None = None
    corroboration_count: int = 1
    tags: list[str] = Field(default_factory=list)
    raw_excerpt: str | None = None


class CompiledQueryPreview(BaseModel):
    source_name: str
    query_id: str
    mode: str
    phase: str
    query_family: str
    signal_lane: SignalLane | None = None
    target_field: str
    query_text: str
    negative_terms: list[str] = Field(default_factory=list)
    required_anchors: list[str] = Field(default_factory=list)


class DiscoveryCandidateDraft(BaseModel):
    candidate_name: str
    endpoint: str
    acquisition_method: str
    parsing_mode: str
    region: str | None = None
    country: str | None = None
    source_family: str | None = None
    signal_lane: SignalLane | None = None
    discovery_mode: str | None = None
    portal_fingerprint: str | None = None
    public_access_mode: PublicAccessMode = "public"
    language_support: list[str] = Field(default_factory=list)
    content_types: list[str] = Field(default_factory=list)
    robots_status: str | None = None
    access_notes: str | None = None
    confidence: float = 0.0
    auto_enable_eligible: bool = False
    known_blind_spot_reason: str | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)


class RetrievalExplanation(BaseModel):
    retrieval_score: float
    source_trust: float
    language_status: str
    signal_lane: SignalLane | None = None
    recommended_action: PursuitRecommendation | None = None
    matched_positive_terms: list[str] = Field(default_factory=list)
    matched_negative_terms: list[str] = Field(default_factory=list)
    exclusion_reason: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class GenericPageTarget(BaseModel):
    url: HttpUrl
    label: str
    country: str | None = None
    procurement_type: str | None = None
