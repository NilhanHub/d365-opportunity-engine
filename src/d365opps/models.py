from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from d365opps.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Lane(str, enum.Enum):
    OPPORTUNITY = "opportunity"
    SIGNAL = "signal"


class RadarLane(str, enum.Enum):
    FORMAL_PROCUREMENT = "formal_procurement"
    PRE_POSITIONING = "pre_positioning"
    DIRECT_OUTREACH = "direct_outreach"
    INSTALL_BASE_TRIGGER = "install_base_trigger"


class RecommendedAction(str, enum.Enum):
    BID_NOW = "bid_now"
    PRE_POSITION = "pre_position"
    RENEWAL_WATCH = "renewal_watch"
    AWARD_WATCH = "award_watch"
    INSTALL_BASE_TRIGGER = "install_base_trigger"
    OUTREACH_NOW = "outreach_now"
    MONITOR = "monitor"
    REJECT = "reject"


class CurrentActionabilityState(str, enum.Enum):
    OPEN_BID = "open_bid"
    OPEN_CONSULTATION = "open_consultation"
    PRE_MARKET_ENGAGEMENT = "pre_market_engagement"
    PLANNED_PROCUREMENT = "planned_procurement"
    FRAMEWORK_OR_VEHICLE = "framework_or_vehicle"
    AWARD_NOTICE = "award_notice"
    CONTRACT_DETAILS_ONLY = "contract_details_only"
    CLOSED_SUBMISSION = "closed_submission"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    AWARDED = "awarded"
    MONITOR_ONLY = "monitor_only"
    UNKNOWN = "unknown"


class RouteToMarket(str, enum.Enum):
    FORMAL_BID = "formal_bid"
    FRAMEWORK_VEHICLE = "framework_vehicle"
    VENDOR_REGISTRATION = "vendor_registration"
    RENEWAL_WATCH = "renewal_watch"
    DIRECT_OUTREACH = "direct_outreach"
    PARTNER_WITH_INCUMBENT = "partner_with_incumbent"
    UNKNOWN = "unknown"


class PublicAccessMode(str, enum.Enum):
    PUBLIC = "public"
    ACCOUNT_OPTIONAL = "account_optional"
    ACCOUNT_REQUIRED = "account_required"
    INVITATION_ONLY = "invitation_only"
    UNSUPPORTED = "unsupported"


class AcquisitionMethod(str, enum.Enum):
    API = "api"
    HTML = "html"
    PLAYWRIGHT = "playwright"
    RSS = "rss"
    OCDS = "ocds"
    SITEMAP = "sitemap"
    DATASET = "dataset"
    SEARCH_API = "search_api"


class ParsingMode(str, enum.Enum):
    JSON = "json"
    HTML = "html"
    XML = "xml"
    PDF = "pdf"
    OCDS = "ocds"
    RSS = "rss"


class CrawlStatus(str, enum.Enum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class CandidateStatus(str, enum.Enum):
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class ClusterStatus(str, enum.Enum):
    OPEN = "open"
    WON = "won"
    LOST = "lost"
    MONITOR = "monitor"


class SourceHealthStatus(str, enum.Enum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILING = "failing"


class DiscoveryStatus(str, enum.Enum):
    PENDING_REVIEW = "pending_review"
    ENABLED = "enabled"
    REJECTED = "rejected"


class JobType(str, enum.Enum):
    REFRESH = "refresh"
    DISCOVER_SOURCES = "discover_sources"
    REPROCESS = "reprocess"
    EXPORT = "export"
    APPROVE_SOURCE = "approve_source"
    REJECT_SOURCE = "reject_source"
    CANARY_SWEEP = "canary_sweep"
    VERIFY_PACK = "verify_pack"
    DOCTOR = "doctor"


class OperationalState(str, enum.Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    THROTTLED = "throttled"
    BLOCKED = "blocked"
    ROBOTS_DISALLOWED = "robots_disallowed"
    AUTH_REQUIRED = "auth_required"
    PARSER_BROKEN = "parser_broken"
    UNSTABLE = "unstable"
    DISABLED = "disabled"
    CANDIDATE = "candidate"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class YieldState(str, enum.Enum):
    HIGH_YIELD = "high_yield"
    NORMAL_YIELD = "normal_yield"
    LOW_YIELD = "low_yield"
    ZERO_YIELD = "zero_yield"
    NOISY = "noisy"
    STALE = "stale"
    UNKNOWN = "unknown"


class ForthcomingState(str, enum.Enum):
    ACTIVE = "active"
    DISCOVERED_PENDING_REVIEW = "discovered_pending_review"
    APPROVED_PENDING_ENABLE = "approved_pending_enable"
    ENABLED_NOT_YET_SUCCESSFUL = "enabled_not_yet_successful"
    UNSUPPORTED = "unsupported"
    INTENTIONALLY_DISABLED = "intentionally_disabled"


class IssueSeverity(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SourceRegistry(Base):
    __tablename__ = "source_registry"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    lane: Mapped[Lane] = mapped_column(Enum(Lane), nullable=False)
    tier: Mapped[int] = mapped_column(nullable=False)
    region: Mapped[str | None] = mapped_column(String(50))
    country: Mapped[str | None] = mapped_column(String(8))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_seed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    cadence: Mapped[str | None] = mapped_column(String(64))
    acquisition_method: Mapped[AcquisitionMethod] = mapped_column(Enum(AcquisitionMethod), nullable=False)
    parsing_mode: Mapped[ParsingMode] = mapped_column(Enum(ParsingMode), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(512), nullable=False)
    legal_notes: Mapped[str | None] = mapped_column(Text)
    access_notes: Mapped[str | None] = mapped_column(Text)
    source_family: Mapped[str | None] = mapped_column(String(64))
    rate_limit_per_minute: Mapped[int | None] = mapped_column()
    health_status: Mapped[SourceHealthStatus] = mapped_column(
        Enum(SourceHealthStatus),
        default=SourceHealthStatus.UNKNOWN,
        nullable=False,
    )
    public_access_mode: Mapped[PublicAccessMode] = mapped_column(
        Enum(PublicAccessMode),
        default=PublicAccessMode.PUBLIC,
        nullable=False,
    )
    last_successful_fetch_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_attempted_fetch_at: Mapped[datetime | None] = mapped_column(DateTime)
    robots_status: Mapped[str | None] = mapped_column(String(64))
    language_support_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    content_types_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    supported_lanes_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    discovery_provenance_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_discovery_confidence: Mapped[float] = mapped_column(default=0.0, nullable=False)
    search_capabilities_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_capability_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    rate_limit_policy_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    known_blind_spot_reason: Mapped[str | None] = mapped_column(Text)
    source_authenticity_class: Mapped[str | None] = mapped_column(String(32))
    canonical_allowed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    crawl_runs: Mapped[list["CrawlRun"]] = relationship(back_populates="source")
    raw_documents: Mapped[list["RawDocument"]] = relationship(back_populates="source")
    discovery_candidates: Mapped[list["SourceDiscoveryCandidate"]] = relationship(back_populates="upstream_source")


class CrawlRun(Base):
    __tablename__ = "crawl_run"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    source_id: Mapped[str] = mapped_column(ForeignKey("source_registry.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[CrawlStatus] = mapped_column(Enum(CrawlStatus), default=CrawlStatus.STARTED, nullable=False)
    cursor: Mapped[str | None] = mapped_column(String(255))
    documents_fetched: Mapped[int] = mapped_column(default=0, nullable=False)
    evidence_extracted: Mapped[int] = mapped_column(default=0, nullable=False)
    candidates_created: Mapped[int] = mapped_column(default=0, nullable=False)
    errors_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    source: Mapped[SourceRegistry] = relationship(back_populates="crawl_runs")


class RawDocument(Base):
    __tablename__ = "raw_document"
    __table_args__ = (UniqueConstraint("source_id", "external_id", "checksum", name="uq_raw_document_external"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    source_id: Mapped[str] = mapped_column(ForeignKey("source_registry.id"), nullable=False)
    crawl_run_id: Mapped[str | None] = mapped_column(ForeignKey("crawl_run.id"))
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    canonical_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    document_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    blob_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    source: Mapped[SourceRegistry] = relationship(back_populates="raw_documents")
    evidence_records: Mapped[list["EvidenceRecord"]] = relationship(back_populates="raw_document")


class AccountCluster(Base):
    __tablename__ = "account_cluster"
    __table_args__ = (UniqueConstraint("cluster_key", name="uq_account_cluster_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    cluster_key: Mapped[str] = mapped_column(String(255), nullable=False)
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False)
    website_domain: Mapped[str | None] = mapped_column(String(255))
    country: Mapped[str | None] = mapped_column(String(16))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    latest_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    heat_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    buyer_quality_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    installed_product_guess: Mapped[str | None] = mapped_column(String(128))
    installed_product_evidence: Mapped[str | None] = mapped_column(Text)
    trigger_strength: Mapped[float] = mapped_column(default=0.0, nullable=False)
    corroboration_count: Mapped[int] = mapped_column(default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    opportunity_candidates: Mapped[list["OpportunityCandidate"]] = relationship(back_populates="account_cluster")
    market_signals: Mapped[list["MarketSignal"]] = relationship(back_populates="account_cluster")


class SignalCluster(Base):
    __tablename__ = "signal_cluster"
    __table_args__ = (UniqueConstraint("cluster_key", name="uq_signal_cluster_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    cluster_key: Mapped[str] = mapped_column(String(255), nullable=False)
    canonical_title: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_buyer: Mapped[str | None] = mapped_column(String(255))
    signal_lane: Mapped[RadarLane] = mapped_column(Enum(RadarLane), nullable=False)
    country: Mapped[str | None] = mapped_column(String(16))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    latest_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    corroboration_count: Mapped[int] = mapped_column(default=1, nullable=False)
    recommended_action: Mapped[RecommendedAction] = mapped_column(
        Enum(RecommendedAction),
        default=RecommendedAction.MONITOR,
        nullable=False,
    )
    route_to_market: Mapped[RouteToMarket] = mapped_column(
        Enum(RouteToMarket),
        default=RouteToMarket.UNKNOWN,
        nullable=False,
    )

    market_signals: Mapped[list["MarketSignal"]] = relationship(back_populates="signal_cluster")


class EvidenceRecord(Base):
    __tablename__ = "evidence_record"
    __table_args__ = (UniqueConstraint("raw_document_id", "source_url", "title", name="uq_evidence_record_doc_title"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    raw_document_id: Mapped[str] = mapped_column(ForeignKey("raw_document.id"), nullable=False)
    source_id: Mapped[str] = mapped_column(ForeignKey("source_registry.id"), nullable=False)
    record_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    buyer_name: Mapped[str | None] = mapped_column(String(255))
    buyer_country: Mapped[str | None] = mapped_column(String(16))
    buyer_region: Mapped[str | None] = mapped_column(String(64))
    notice_type: Mapped[str | None] = mapped_column(String(128))
    procurement_type: Mapped[str | None] = mapped_column(String(128))
    publication_date: Mapped[datetime | None] = mapped_column(DateTime)
    close_date: Mapped[datetime | None] = mapped_column(DateTime)
    budget_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    budget_currency: Mapped[str | None] = mapped_column(String(8))
    source_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    response_url: Mapped[str | None] = mapped_column(String(1024))
    contact_name: Mapped[str | None] = mapped_column(String(255))
    contact_email: Mapped[str | None] = mapped_column(String(255))
    contact_phone: Mapped[str | None] = mapped_column(String(64))
    cpv_codes_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    attachment_urls_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    attachment_metadata_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    lot_titles_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    product_mentions_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    service_mentions_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    classification_codes_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    tags_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    procurement_id: Mapped[str | None] = mapped_column(String(255))
    raw_excerpt: Mapped[str | None] = mapped_column(Text)
    acquisition_method: Mapped[str | None] = mapped_column(String(32))
    source_provenance_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    language_status: Mapped[str | None] = mapped_column(String(64))
    language_details_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    english_evidence_source: Mapped[str | None] = mapped_column(String(64))
    current_actionability_state: Mapped[CurrentActionabilityState | None] = mapped_column(Enum(CurrentActionabilityState))
    english_sufficiency_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    english_shell_only_flag: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    seller_readable_summary_en: Mapped[str | None] = mapped_column(Text)
    seller_readable_title_en_flag: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    retrieval_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    formal_opportunity_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    pre_position_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    account_intent_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    install_base_trigger_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    service_fit_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    buyer_quality_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    corroboration_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    source_trust: Mapped[float] = mapped_column(default=0.0, nullable=False)
    matched_positive_terms_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    matched_negative_terms_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    discovery_query_id: Mapped[str | None] = mapped_column(String(64))
    discovery_query_text: Mapped[str | None] = mapped_column(Text)
    query_family: Mapped[str | None] = mapped_column(String(64))
    source_discovery_confidence: Mapped[float] = mapped_column(default=0.0, nullable=False)
    signal_lane: Mapped[RadarLane | None] = mapped_column(Enum(RadarLane))
    recommended_action: Mapped[RecommendedAction | None] = mapped_column(Enum(RecommendedAction))
    route_to_market: Mapped[RouteToMarket | None] = mapped_column(Enum(RouteToMarket))
    account_heat_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    installed_product_guess: Mapped[str | None] = mapped_column(String(128))
    installed_product_evidence: Mapped[str | None] = mapped_column(Text)
    trigger_type: Mapped[str | None] = mapped_column(String(128))
    trigger_strength: Mapped[float] = mapped_column(default=0.0, nullable=False)
    procurement_cycle_stage: Mapped[str | None] = mapped_column(String(128))
    vehicle_type: Mapped[str | None] = mapped_column(String(128))
    incumbent_vendor: Mapped[str | None] = mapped_column(String(255))
    incumbent_expiry_guess: Mapped[str | None] = mapped_column(String(64))
    buyer_intent_evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    legacy_evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    portal_fingerprint: Mapped[str | None] = mapped_column(String(64))
    public_access_mode: Mapped[PublicAccessMode] = mapped_column(
        Enum(PublicAccessMode),
        default=PublicAccessMode.PUBLIC,
        nullable=False,
    )
    known_blind_spot_reason: Mapped[str | None] = mapped_column(String(255))
    exclusion_reason: Mapped[str | None] = mapped_column(String(128))
    extracted_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    raw_document: Mapped[RawDocument] = relationship(back_populates="evidence_records")
    opportunity_candidates: Mapped[list["OpportunityCandidate"]] = relationship(back_populates="evidence_record")
    market_signals: Mapped[list["MarketSignal"]] = relationship(back_populates="evidence_record")
    exclusion_audits: Mapped[list["ExclusionAudit"]] = relationship(back_populates="evidence_record")


class Organization(Base):
    __tablename__ = "organization"
    __table_args__ = (UniqueConstraint("normalized_name", "website_domain", name="uq_organization_identity"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False)
    website_domain: Mapped[str | None] = mapped_column(String(255))
    country: Mapped[str | None] = mapped_column(String(16))
    region: Mapped[str | None] = mapped_column(String(32))
    industry: Mapped[str | None] = mapped_column(String(128))
    size_band: Mapped[str | None] = mapped_column(String(64))
    registry_payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    enrichment_confidence: Mapped[float] = mapped_column(default=0.0, nullable=False)
    provenance_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    contacts: Mapped[list["Contact"]] = relationship(back_populates="organization")


class Contact(Base):
    __tablename__ = "contact"
    __table_args__ = (UniqueConstraint("organization_id", "email", "full_name", name="uq_contact_identity"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(ForeignKey("organization.id"), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(64))
    role: Mapped[str | None] = mapped_column(String(128))
    public_source_url: Mapped[str | None] = mapped_column(String(1024))
    enrichment_payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    enrichment_confidence: Mapped[float] = mapped_column(default=0.0, nullable=False)
    provenance_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    organization: Mapped[Organization] = relationship(back_populates="contacts")


class OpportunityCluster(Base):
    __tablename__ = "opportunity_cluster"
    __table_args__ = (UniqueConstraint("cluster_key", name="uq_cluster_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    cluster_key: Mapped[str] = mapped_column(String(255), nullable=False)
    canonical_title: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_buyer: Mapped[str | None] = mapped_column(String(255))
    country: Mapped[str | None] = mapped_column(String(16))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    latest_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    evidence_grade: Mapped[str | None] = mapped_column(String(4))
    aggregate_score: Mapped[int] = mapped_column(default=0, nullable=False)
    corroboration_count: Mapped[int] = mapped_column(default=1, nullable=False)
    corroborating_sources_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[ClusterStatus] = mapped_column(Enum(ClusterStatus), default=ClusterStatus.OPEN, nullable=False)

    candidates: Mapped[list["OpportunityCandidate"]] = relationship(back_populates="cluster")


class OpportunityCandidate(Base):
    __tablename__ = "opportunity_candidate"
    __table_args__ = (UniqueConstraint("evidence_record_id", name="uq_candidate_evidence"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    evidence_record_id: Mapped[str] = mapped_column(ForeignKey("evidence_record.id"), nullable=False)
    organization_id: Mapped[str | None] = mapped_column(ForeignKey("organization.id"))
    account_cluster_id: Mapped[str | None] = mapped_column(ForeignKey("account_cluster.id"))
    cluster_id: Mapped[str | None] = mapped_column(ForeignKey("opportunity_cluster.id"))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    app_family: Mapped[str] = mapped_column(String(128), nullable=False)
    business_process: Mapped[str] = mapped_column(String(128), nullable=False)
    service_type: Mapped[str] = mapped_column(String(128), nullable=False)
    evidence_grade: Mapped[str] = mapped_column(String(4), nullable=False)
    signal_lane: Mapped[RadarLane] = mapped_column(Enum(RadarLane), nullable=False)
    recommended_action: Mapped[RecommendedAction] = mapped_column(Enum(RecommendedAction), nullable=False)
    route_to_market: Mapped[RouteToMarket] = mapped_column(Enum(RouteToMarket), nullable=False)
    d365_confidence: Mapped[float] = mapped_column(nullable=False)
    country: Mapped[str | None] = mapped_column(String(16))
    procurement_type: Mapped[str | None] = mapped_column(String(128))
    publication_date: Mapped[datetime | None] = mapped_column(DateTime)
    close_date: Mapped[datetime | None] = mapped_column(DateTime)
    budget_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    budget_currency: Mapped[str | None] = mapped_column(String(8))
    source_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    response_url: Mapped[str | None] = mapped_column(String(1024))
    procurement_id: Mapped[str | None] = mapped_column(String(255))
    raw_excerpt: Mapped[str | None] = mapped_column(Text)
    retrieval_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    formal_opportunity_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    pre_position_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    account_intent_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    install_base_trigger_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    service_fit_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    buyer_quality_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    corroboration_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    opportunity_score: Mapped[int] = mapped_column(default=0, nullable=False)
    source_trust: Mapped[float] = mapped_column(default=0.0, nullable=False)
    matched_positive_terms_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    matched_negative_terms_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    language_status: Mapped[str | None] = mapped_column(String(64))
    english_evidence_source: Mapped[str | None] = mapped_column(String(64))
    current_actionability_state: Mapped[CurrentActionabilityState | None] = mapped_column(Enum(CurrentActionabilityState))
    english_sufficiency_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    english_shell_only_flag: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    seller_readable_summary_en: Mapped[str | None] = mapped_column(Text)
    seller_readable_title_en_flag: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sales_handoff_state: Mapped[str] = mapped_column(String(32), default="reject", nullable=False)
    corroboration_count: Mapped[int] = mapped_column(default=1, nullable=False)
    discovery_query_id: Mapped[str | None] = mapped_column(String(64))
    discovery_query_text: Mapped[str | None] = mapped_column(Text)
    query_family: Mapped[str | None] = mapped_column(String(64))
    source_discovery_confidence: Mapped[float] = mapped_column(default=0.0, nullable=False)
    public_access_mode: Mapped[PublicAccessMode] = mapped_column(
        Enum(PublicAccessMode),
        default=PublicAccessMode.PUBLIC,
        nullable=False,
    )
    account_heat_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    installed_product_guess: Mapped[str | None] = mapped_column(String(128))
    installed_product_evidence: Mapped[str | None] = mapped_column(Text)
    trigger_type: Mapped[str | None] = mapped_column(String(128))
    trigger_strength: Mapped[float] = mapped_column(default=0.0, nullable=False)
    procurement_cycle_stage: Mapped[str | None] = mapped_column(String(128))
    vehicle_type: Mapped[str | None] = mapped_column(String(128))
    incumbent_vendor: Mapped[str | None] = mapped_column(String(255))
    incumbent_expiry_guess: Mapped[str | None] = mapped_column(String(64))
    buyer_intent_evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    legacy_evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    portal_fingerprint: Mapped[str | None] = mapped_column(String(64))
    known_blind_spot_reason: Mapped[str | None] = mapped_column(String(255))
    exclusion_reason: Mapped[str | None] = mapped_column(String(128))
    score_breakdown_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    total_score: Mapped[int] = mapped_column(default=0, nullable=False)
    pursuit_recommendation: Mapped[str] = mapped_column(String(32), nullable=False)
    next_action: Mapped[str] = mapped_column(String(255), nullable=False)
    dedupe_fingerprint: Mapped[str] = mapped_column(String(255), nullable=False)
    tags_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[CandidateStatus] = mapped_column(
        Enum(CandidateStatus),
        default=CandidateStatus.PENDING_REVIEW,
        nullable=False,
    )
    review_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    evidence_record: Mapped[EvidenceRecord] = relationship(back_populates="opportunity_candidates")
    cluster: Mapped[OpportunityCluster | None] = relationship(back_populates="candidates")
    account_cluster: Mapped[AccountCluster | None] = relationship(back_populates="opportunity_candidates")


class MarketSignal(Base):
    __tablename__ = "market_signal"
    __table_args__ = (UniqueConstraint("evidence_record_id", name="uq_signal_evidence"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    evidence_record_id: Mapped[str] = mapped_column(ForeignKey("evidence_record.id"), nullable=False)
    organization_id: Mapped[str | None] = mapped_column(ForeignKey("organization.id"))
    account_cluster_id: Mapped[str | None] = mapped_column(ForeignKey("account_cluster.id"))
    signal_cluster_id: Mapped[str | None] = mapped_column(ForeignKey("signal_cluster.id"))
    signal_type: Mapped[str] = mapped_column(String(64), nullable=False)
    signal_lane: Mapped[RadarLane] = mapped_column(Enum(RadarLane), nullable=False)
    recommended_action: Mapped[RecommendedAction] = mapped_column(Enum(RecommendedAction), nullable=False)
    route_to_market: Mapped[RouteToMarket] = mapped_column(Enum(RouteToMarket), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    region: Mapped[str | None] = mapped_column(String(32))
    country: Mapped[str | None] = mapped_column(String(16))
    confidence: Mapped[float] = mapped_column(default=0.0, nullable=False)
    retrieval_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    source_trust: Mapped[float] = mapped_column(default=0.0, nullable=False)
    account_heat_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    trigger_type: Mapped[str | None] = mapped_column(String(128))
    trigger_strength: Mapped[float] = mapped_column(default=0.0, nullable=False)
    public_access_mode: Mapped[PublicAccessMode] = mapped_column(
        Enum(PublicAccessMode),
        default=PublicAccessMode.PUBLIC,
        nullable=False,
    )
    english_evidence_source: Mapped[str | None] = mapped_column(String(64))
    buyer_intent_evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    legacy_evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    query_family: Mapped[str | None] = mapped_column(String(64))
    discovery_query_id: Mapped[str | None] = mapped_column(String(64))
    discovery_query_text: Mapped[str | None] = mapped_column(Text)
    portal_fingerprint: Mapped[str | None] = mapped_column(String(64))
    known_blind_spot_reason: Mapped[str | None] = mapped_column(String(255))
    corroboration_count: Mapped[int] = mapped_column(default=1, nullable=False)
    tags_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    raw_excerpt: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    evidence_record: Mapped[EvidenceRecord] = relationship(back_populates="market_signals")
    account_cluster: Mapped[AccountCluster | None] = relationship(back_populates="market_signals")
    signal_cluster: Mapped[SignalCluster | None] = relationship(back_populates="market_signals")


class SourceDiscoveryCandidate(Base):
    __tablename__ = "source_discovery_candidate"
    __table_args__ = (UniqueConstraint("endpoint", name="uq_source_discovery_candidate_endpoint"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    upstream_source_id: Mapped[str | None] = mapped_column(ForeignKey("source_registry.id"))
    candidate_name: Mapped[str] = mapped_column(String(128), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(1024), nullable=False)
    acquisition_method: Mapped[AcquisitionMethod] = mapped_column(Enum(AcquisitionMethod), nullable=False)
    parsing_mode: Mapped[ParsingMode] = mapped_column(Enum(ParsingMode), nullable=False)
    region: Mapped[str | None] = mapped_column(String(64))
    country: Mapped[str | None] = mapped_column(String(16))
    source_family: Mapped[str | None] = mapped_column(String(64))
    signal_lane: Mapped[RadarLane | None] = mapped_column(Enum(RadarLane))
    discovery_mode: Mapped[str | None] = mapped_column(String(64))
    portal_fingerprint: Mapped[str | None] = mapped_column(String(64))
    public_access_mode: Mapped[PublicAccessMode] = mapped_column(
        Enum(PublicAccessMode),
        default=PublicAccessMode.PUBLIC,
        nullable=False,
    )
    language_support_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    content_types_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    robots_status: Mapped[str | None] = mapped_column(String(64))
    access_notes: Mapped[str | None] = mapped_column(Text)
    discovery_status: Mapped[DiscoveryStatus] = mapped_column(
        Enum(DiscoveryStatus),
        default=DiscoveryStatus.PENDING_REVIEW,
        nullable=False,
    )
    confidence: Mapped[float] = mapped_column(default=0.0, nullable=False)
    auto_enable_eligible: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    known_blind_spot_reason: Mapped[str | None] = mapped_column(Text)
    provenance_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    upstream_source: Mapped[SourceRegistry | None] = relationship(back_populates="discovery_candidates")


class ExclusionAudit(Base):
    __tablename__ = "exclusion_audit"
    __table_args__ = (UniqueConstraint("evidence_record_id", "reason", name="uq_exclusion_audit_evidence_reason"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    evidence_record_id: Mapped[str] = mapped_column(ForeignKey("evidence_record.id"), nullable=False)
    reason: Mapped[str] = mapped_column(String(128), nullable=False)
    retrieval_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    language_status: Mapped[str | None] = mapped_column(String(64))
    matched_positive_terms_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    matched_negative_terms_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    evidence_record: Mapped[EvidenceRecord] = relationship(back_populates="exclusion_audits")


class JobRun(Base):
    __tablename__ = "job_run"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    source_id: Mapped[str | None] = mapped_column(ForeignKey("source_registry.id"))
    crawl_run_id: Mapped[str | None] = mapped_column(ForeignKey("crawl_run.id"))
    job_type: Mapped[JobType] = mapped_column(Enum(JobType), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[CrawlStatus] = mapped_column(Enum(CrawlStatus), default=CrawlStatus.STARTED, nullable=False)
    duration_ms: Mapped[int | None] = mapped_column()
    trace_id: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(64))
    mode: Mapped[str | None] = mapped_column(String(64))
    source_names_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    budget_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    query_count: Mapped[int] = mapped_column(default=0, nullable=False)
    sources_attempted: Mapped[int] = mapped_column(default=0, nullable=False)
    sources_succeeded: Mapped[int] = mapped_column(default=0, nullable=False)
    sources_failed: Mapped[int] = mapped_column(default=0, nullable=False)
    sources_zero_yield: Mapped[int] = mapped_column(default=0, nullable=False)
    sources_untested: Mapped[int] = mapped_column(default=0, nullable=False)
    run_reason: Mapped[str | None] = mapped_column(String(128))
    initiated_by: Mapped[str | None] = mapped_column(String(128))
    documents_fetched: Mapped[int] = mapped_column(default=0, nullable=False)
    evidence_extracted: Mapped[int] = mapped_column(default=0, nullable=False)
    candidates_created: Mapped[int] = mapped_column(default=0, nullable=False)
    opportunities_created: Mapped[int] = mapped_column(default=0, nullable=False)
    retries: Mapped[int] = mapped_column(default=0, nullable=False)
    bytes_fetched: Mapped[int] = mapped_column(default=0, nullable=False)
    errors_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    verification_bundle_path: Mapped[str | None] = mapped_column(String(1024))
    verification_bundle_sha256: Mapped[str | None] = mapped_column(String(64))
    diagnostic_summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    run_kind: Mapped[str | None] = mapped_column(String(64))
    evidence_class: Mapped[str | None] = mapped_column(String(64))
    oracle_admissible: Mapped[bool | None] = mapped_column(Boolean)
    admissibility_fail_reasons_json: Mapped[list[str]] = mapped_column(JSON, default=list)


class SourceFetchEvent(Base):
    __tablename__ = "source_fetch_event"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    source_id: Mapped[str | None] = mapped_column(ForeignKey("source_registry.id"))
    crawl_run_id: Mapped[str | None] = mapped_column(ForeignKey("crawl_run.id"))
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(64))
    span_id: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(64))
    query_id: Mapped[str | None] = mapped_column(String(64))
    query_family: Mapped[str | None] = mapped_column(String(64))
    page_index: Mapped[int] = mapped_column(default=0, nullable=False)
    cursor_in: Mapped[str | None] = mapped_column(String(255))
    cursor_out: Mapped[str | None] = mapped_column(String(255))
    parent_url: Mapped[str | None] = mapped_column(String(1024))
    detail_url: Mapped[str | None] = mapped_column(String(1024))
    request_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    request_method: Mapped[str] = mapped_column(String(16), default="GET", nullable=False)
    response_status_code: Mapped[int | None] = mapped_column()
    latency_ms: Mapped[int | None] = mapped_column()
    bytes: Mapped[int] = mapped_column(default=0, nullable=False)
    bytes_received: Mapped[int] = mapped_column(default=0, nullable=False)
    bytes_stored: Mapped[int] = mapped_column(default=0, nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(128))
    was_retry: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    retry_count: Mapped[int] = mapped_column(default=0, nullable=False)
    robots_status: Mapped[str | None] = mapped_column(String(64))
    parser_used: Mapped[str | None] = mapped_column(String(64))
    adapter_name: Mapped[str | None] = mapped_column(String(128))
    adapter_version: Mapped[str | None] = mapped_column(String(32))
    stage: Mapped[str | None] = mapped_column(String(64))
    list_or_detail: Mapped[str | None] = mapped_column(String(32))
    attempt_number: Mapped[int] = mapped_column(default=1, nullable=False)
    backoff_ms: Mapped[int | None] = mapped_column()
    network_error_stage: Mapped[str | None] = mapped_column(String(64))
    http_protocol: Mapped[str | None] = mapped_column(String(32))
    tls_error_flag: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    dns_error_flag: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    transport_error_flag: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    success_flag: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    issue_code: Mapped[str | None] = mapped_column(String(64))
    error_class: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    english_detected: Mapped[bool | None] = mapped_column(Boolean)
    documents_emitted: Mapped[int] = mapped_column(default=0, nullable=False)
    evidence_emitted: Mapped[int] = mapped_column(default=0, nullable=False)
    request_headers_redacted_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    response_headers_redacted_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    rate_limit_headers_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    response_body_sha256: Mapped[str | None] = mapped_column(String(64))
    response_blob_path: Mapped[str | None] = mapped_column(String(1024))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class SourceIssue(Base):
    __tablename__ = "source_issue"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    source_id: Mapped[str | None] = mapped_column(ForeignKey("source_registry.id"))
    crawl_run_id: Mapped[str | None] = mapped_column(ForeignKey("crawl_run.id"))
    issue_code: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[IssueSeverity] = mapped_column(Enum(IssueSeverity), default=IssueSeverity.MEDIUM, nullable=False)
    state: Mapped[str] = mapped_column(String(32), default="open", nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    frequency: Mapped[int] = mapped_column(default=1, nullable=False)
    example_url: Mapped[str | None] = mapped_column(String(1024))
    example_status_code: Mapped[int | None] = mapped_column()
    error_class: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    impact_on_yield: Mapped[str | None] = mapped_column(Text)
    recommended_remediation: Mapped[str | None] = mapped_column(Text)
    owner: Mapped[str | None] = mapped_column(String(128))
    note: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(64))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class SourceDailyMetric(Base):
    __tablename__ = "source_daily_metric"
    __table_args__ = (UniqueConstraint("source_id", "metric_date", name="uq_source_daily_metric"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    source_id: Mapped[str] = mapped_column(ForeignKey("source_registry.id"), nullable=False)
    metric_date: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    documents_fetched: Mapped[int] = mapped_column(default=0, nullable=False)
    evidence_extracted: Mapped[int] = mapped_column(default=0, nullable=False)
    market_signals_created: Mapped[int] = mapped_column(default=0, nullable=False)
    opportunities_created: Mapped[int] = mapped_column(default=0, nullable=False)
    approved_opportunities: Mapped[int] = mapped_column(default=0, nullable=False)
    success_rate: Mapped[float] = mapped_column(default=0.0, nullable=False)
    avg_latency_ms: Mapped[float] = mapped_column(default=0.0, nullable=False)
    rate_429: Mapped[float] = mapped_column(default=0.0, nullable=False)
    rate_403: Mapped[float] = mapped_column(default=0.0, nullable=False)
    timeout_rate: Mapped[float] = mapped_column(default=0.0, nullable=False)
    parser_failure_rate: Mapped[float] = mapped_column(default=0.0, nullable=False)
    english_acceptance_rate: Mapped[float] = mapped_column(default=0.0, nullable=False)
    field_completeness_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    unique_buyers_found: Mapped[int] = mapped_column(default=0, nullable=False)
    operational_state: Mapped[OperationalState] = mapped_column(Enum(OperationalState), default=OperationalState.UNKNOWN, nullable=False)
    yield_state: Mapped[YieldState] = mapped_column(Enum(YieldState), default=YieldState.UNKNOWN, nullable=False)


class PipelineEvent(Base):
    __tablename__ = "pipeline_event"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    level: Mapped[str] = mapped_column(String(16), default="info", nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    service: Mapped[str] = mapped_column(String(64), nullable=False)
    component: Mapped[str | None] = mapped_column(String(128))
    phase: Mapped[str | None] = mapped_column(String(64))
    run_id: Mapped[str | None] = mapped_column(String(64))
    job_run_id: Mapped[str | None] = mapped_column(String(36))
    crawl_run_id: Mapped[str | None] = mapped_column(String(36))
    source_id: Mapped[str | None] = mapped_column(String(36))
    source_name: Mapped[str | None] = mapped_column(String(128))
    query_id: Mapped[str | None] = mapped_column(String(64))
    query_family: Mapped[str | None] = mapped_column(String(64))
    document_id: Mapped[str | None] = mapped_column(String(36))
    evidence_id: Mapped[str | None] = mapped_column(String(36))
    opportunity_id: Mapped[str | None] = mapped_column(String(36))
    account_id: Mapped[str | None] = mapped_column(String(36))
    trace_id: Mapped[str | None] = mapped_column(String(64))
    span_id: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(64))
    message: Mapped[str | None] = mapped_column(Text)
    issue_code: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str | None] = mapped_column(String(64))
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class SourceStateTransition(Base):
    __tablename__ = "source_state_transition"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    source_id: Mapped[str] = mapped_column(ForeignKey("source_registry.id"), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    previous_operational_state: Mapped[OperationalState | None] = mapped_column(Enum(OperationalState))
    new_operational_state: Mapped[OperationalState] = mapped_column(Enum(OperationalState), nullable=False)
    previous_yield_state: Mapped[YieldState | None] = mapped_column(Enum(YieldState))
    new_yield_state: Mapped[YieldState] = mapped_column(Enum(YieldState), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(64))
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    run_id: Mapped[str | None] = mapped_column(String(64))
    trace_id: Mapped[str | None] = mapped_column(String(64))


class SourceCanaryResult(Base):
    __tablename__ = "source_canary_result"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    source_id: Mapped[str] = mapped_column(ForeignKey("source_registry.id"), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    canary_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    docs_seen: Mapped[int] = mapped_column(default=0, nullable=False)
    expected_marker_found: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    parser_ok: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    latency_ms: Mapped[int | None] = mapped_column()
    issue_code: Mapped[str | None] = mapped_column(String(64))
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    trace_id: Mapped[str | None] = mapped_column(String(64))


class QueryExecution(Base):
    __tablename__ = "query_execution"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    source_id: Mapped[str | None] = mapped_column(ForeignKey("source_registry.id"))
    crawl_run_id: Mapped[str | None] = mapped_column(ForeignKey("crawl_run.id"))
    query_id: Mapped[str] = mapped_column(String(64), nullable=False)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    renderer: Mapped[str | None] = mapped_column(String(64))
    abstract_query_text: Mapped[str | None] = mapped_column(Text)
    rendered_query_text: Mapped[str | None] = mapped_column(Text)
    query_family: Mapped[str | None] = mapped_column(String(64))
    phase: Mapped[str | None] = mapped_column(String(32))
    target_field: Mapped[str | None] = mapped_column(String(64))
    negatives_applied_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    was_executed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    skip_reason: Mapped[str | None] = mapped_column(String(128))
    watermark_in: Mapped[str | None] = mapped_column(String(255))
    watermark_out: Mapped[str | None] = mapped_column(String(255))
    cursor_count: Mapped[int] = mapped_column(default=0, nullable=False)
    duplicate_fetches_avoided: Mapped[int] = mapped_column(default=0, nullable=False)
    browse_only_pass: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str | None] = mapped_column(String(64))
    trace_id: Mapped[str | None] = mapped_column(String(64))
    requests: Mapped[int] = mapped_column(default=0, nullable=False)
    hits: Mapped[int] = mapped_column(default=0, nullable=False)
    docs: Mapped[int] = mapped_column(default=0, nullable=False)
    evidence: Mapped[int] = mapped_column(default=0, nullable=False)
    opps: Mapped[int] = mapped_column(default=0, nullable=False)
    signals: Mapped[int] = mapped_column(default=0, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class UiSavedView(Base):
    __tablename__ = "ui_saved_view"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    route: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    filters_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    columns_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    density: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
