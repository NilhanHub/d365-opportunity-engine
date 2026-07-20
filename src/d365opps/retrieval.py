from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from importlib import resources
from typing import Any
from urllib.parse import urlparse

from d365opps.config import get_settings
from d365opps.models import PublicAccessMode, RadarLane, RecommendedAction, RouteToMarket, SourceRegistry


WORD_RE = re.compile(r"[a-z0-9&+/#-]+", re.IGNORECASE)


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.lower().split())


def _hash_id(*parts: str) -> str:
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()
    return digest[:12]


def _contains_phrase(text: str, phrase: str) -> bool:
    return normalize_text(phrase) in text


def _clamp(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    return max(lower, min(upper, value))


@dataclass(frozen=True, slots=True)
class CompiledQuery:
    source_name: str
    query_id: str
    mode: str
    phase: str
    query_family: str
    signal_lane: str | None
    target_field: str
    query_text: str
    negative_terms: tuple[str, ...]
    required_anchors: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_name": self.source_name,
            "query_id": self.query_id,
            "mode": self.mode,
            "phase": self.phase,
            "query_family": self.query_family,
            "signal_lane": self.signal_lane,
            "target_field": self.target_field,
            "query_text": self.query_text,
            "negative_terms": list(self.negative_terms),
            "required_anchors": list(self.required_anchors),
        }


@dataclass(frozen=True, slots=True)
class RenderedQuery:
    source_name: str
    query_id: str
    mode: str
    phase: str
    query_family: str
    signal_lane: str | None
    target_field: str
    abstract_query_text: str
    rendered_query_text: str
    negative_terms: tuple[str, ...]
    required_anchors: tuple[str, ...]
    renderer: str
    remote_supported: bool
    browse_only: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_name": self.source_name,
            "query_id": self.query_id,
            "mode": self.mode,
            "phase": self.phase,
            "query_family": self.query_family,
            "signal_lane": self.signal_lane,
            "target_field": self.target_field,
            "abstract_query_text": self.abstract_query_text,
            "query_text": self.rendered_query_text,
            "negative_terms": list(self.negative_terms),
            "required_anchors": list(self.required_anchors),
            "renderer": self.renderer,
            "remote_supported": self.remote_supported,
            "browse_only": self.browse_only,
            "metadata": self.metadata,
        }


@dataclass(frozen=True, slots=True)
class QueryExecutionPlan:
    source_name: str
    mode: str
    queries: tuple[RenderedQuery, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_name": self.source_name,
            "mode": self.mode,
            "queries": [query.as_dict() for query in self.queries],
        }


@dataclass(frozen=True, slots=True)
class LanguageDecision:
    status: str
    confidence: float
    source: str
    details: dict[str, Any]


@dataclass(frozen=True, slots=True)
class RetrievalAssessment:
    retrieval_score: float
    source_trust: float
    language_status: str
    language_details: dict[str, Any]
    english_evidence_source: str | None
    matched_positive_terms: tuple[str, ...]
    matched_negative_terms: tuple[str, ...]
    matched_service_terms: tuple[str, ...]
    matched_procurement_terms: tuple[str, ...]
    matched_route_terms: tuple[str, ...]
    matched_trigger_terms: tuple[str, ...]
    signal_lane: RadarLane | None
    recommended_action: RecommendedAction
    route_to_market: RouteToMarket
    formal_opportunity_score: float
    pre_position_score: float
    account_intent_score: float
    install_base_trigger_score: float
    service_fit_score: float
    buyer_quality_score: float
    corroboration_score: float
    account_heat_score: float
    procurement_cycle_stage: str | None
    vehicle_type: str | None
    installed_product_guess: str | None
    installed_product_evidence: str | None
    trigger_type: str | None
    trigger_strength: float
    incumbent_vendor: str | None
    incumbent_expiry_guess: str | None
    buyer_intent_evidence: dict[str, Any]
    legacy_evidence: dict[str, Any]
    query_family: str | None
    exclusion_reason: str | None
    query_id: str | None
    query_text: str | None
    source_discovery_confidence: float
    corroboration_count: int
    portal_fingerprint: str | None
    public_access_mode: PublicAccessMode
    known_blind_spot_reason: str | None
    component_scores: dict[str, float]
    lane_rationale: dict[str, Any]

    @property
    def passes_signal_threshold(self) -> bool:
        return self.exclusion_reason is None and self.retrieval_score >= get_settings().signal_min_score

    @property
    def passes_opportunity_threshold(self) -> bool:
        return (
            self.exclusion_reason is None
            and self.retrieval_score >= get_settings().retrieval_min_score
            and self.recommended_action != RecommendedAction.REJECT
            and self.signal_lane is not None
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "retrieval_score": self.retrieval_score,
            "source_trust": self.source_trust,
            "language_status": self.language_status,
            "language_details": self.language_details,
            "english_evidence_source": self.english_evidence_source,
            "matched_positive_terms": list(self.matched_positive_terms),
            "matched_negative_terms": list(self.matched_negative_terms),
            "matched_service_terms": list(self.matched_service_terms),
            "matched_procurement_terms": list(self.matched_procurement_terms),
            "matched_route_terms": list(self.matched_route_terms),
            "matched_trigger_terms": list(self.matched_trigger_terms),
            "signal_lane": self.signal_lane.value if self.signal_lane else None,
            "recommended_action": self.recommended_action.value,
            "route_to_market": self.route_to_market.value,
            "formal_opportunity_score": self.formal_opportunity_score,
            "pre_position_score": self.pre_position_score,
            "account_intent_score": self.account_intent_score,
            "install_base_trigger_score": self.install_base_trigger_score,
            "service_fit_score": self.service_fit_score,
            "buyer_quality_score": self.buyer_quality_score,
            "corroboration_score": self.corroboration_score,
            "account_heat_score": self.account_heat_score,
            "procurement_cycle_stage": self.procurement_cycle_stage,
            "vehicle_type": self.vehicle_type,
            "installed_product_guess": self.installed_product_guess,
            "installed_product_evidence": self.installed_product_evidence,
            "trigger_type": self.trigger_type,
            "trigger_strength": self.trigger_strength,
            "query_family": self.query_family,
            "exclusion_reason": self.exclusion_reason,
            "query_id": self.query_id,
            "query_text": self.query_text,
            "source_discovery_confidence": self.source_discovery_confidence,
            "corroboration_count": self.corroboration_count,
            "portal_fingerprint": self.portal_fingerprint,
            "public_access_mode": self.public_access_mode.value,
            "known_blind_spot_reason": self.known_blind_spot_reason,
            "component_scores": self.component_scores,
            "lane_rationale": self.lane_rationale,
        }


@dataclass(frozen=True, slots=True)
class RetrievalRuleSet:
    core_product_terms: tuple[str, ...]
    legacy_product_terms: tuple[str, ...]
    priority_product_terms: tuple[str, ...]
    anchored_short_terms: tuple[str, ...]
    service_verbs: tuple[str, ...]
    procurement_verbs: tuple[str, ...]
    route_to_market_terms: tuple[str, ...]
    pre_position_terms: tuple[str, ...]
    direct_outreach_terms: tuple[str, ...]
    trigger_terms: tuple[str, ...]
    active_notice_terms: tuple[str, ...]
    job_posting_terms: tuple[str, ...]
    migration_patterns: tuple[str, ...]
    generic_terms: tuple[str, ...]
    hard_negative_terms: tuple[str, ...]
    false_friend_patterns: tuple[str, ...]
    coexistence_exceptions: tuple[str, ...]
    english_markers: tuple[str, ...]
    portal_fingerprints: dict[str, list[str]]
    source_profiles: dict[str, dict[str, Any]]

    @classmethod
    def load(cls) -> "RetrievalRuleSet":
        return load_retrieval_rules()

    @property
    def positive_product_terms(self) -> tuple[str, ...]:
        return self.core_product_terms + self.legacy_product_terms

    def source_profile(self, source_name: str) -> dict[str, Any]:
        return self.source_profiles.get(source_name, {})

    def match_terms(self, text: str, terms: tuple[str, ...]) -> list[str]:
        normalized = normalize_text(text)
        matches: list[str] = []
        for term in terms:
            normalized_term = normalize_text(term)
            if len(normalized_term) <= 3 and normalized_term.isalpha():
                pattern = re.compile(rf"(?<![a-z0-9]){re.escape(normalized_term)}(?![a-z0-9])")
                if pattern.search(normalized):
                    matches.append(term)
                continue
            if _contains_phrase(normalized, term):
                matches.append(term)
        return matches

    def match_positive_terms(self, text: str) -> list[str]:
        normalized = normalize_text(text)
        long_form_terms = tuple(term for term in self.positive_product_terms if term not in self.anchored_short_terms)
        matches = self.match_terms(normalized, long_form_terms)
        for term in self.anchored_short_terms:
            pattern = re.compile(rf"(?<![a-z0-9]){re.escape(term.lower())}(?![a-z0-9])")
            if not pattern.search(normalized):
                continue
            if term == "BC":
                if "business central" in normalized or "navision" in normalized or "dynamics" in normalized:
                    matches.append(term)
                continue
            if term == "CE":
                if "customer engagement" in normalized or "dynamics" in normalized:
                    matches.append(term)
                continue
            matches.append(term)
        return sorted(set(matches))

    def match_negative_terms(self, text: str) -> list[str]:
        normalized = normalize_text(text)
        matches = self.match_terms(normalized, self.hard_negative_terms)
        matches.extend(self.match_terms(normalized, self.false_friend_patterns))
        return sorted(set(matches))

    def has_coexistence_exception(self, text: str) -> bool:
        normalized = normalize_text(text)
        return any(_contains_phrase(normalized, phrase) for phrase in self.coexistence_exceptions)

    def detect_portal_fingerprint(self, text: str) -> str | None:
        normalized = normalize_text(text)
        for name, patterns in self.portal_fingerprints.items():
            if any(pattern.lower() in normalized for pattern in patterns):
                return name
        return None


@lru_cache(maxsize=1)
def load_retrieval_rules() -> RetrievalRuleSet:
    payload = json.loads(resources.files("d365opps.data").joinpath("retrieval_rules.json").read_text(encoding="utf-8"))
    return RetrievalRuleSet(
        core_product_terms=tuple(payload["core_product_terms"]),
        legacy_product_terms=tuple(payload["legacy_product_terms"]),
        priority_product_terms=tuple(payload["priority_product_terms"]),
        anchored_short_terms=tuple(payload["anchored_short_terms"]),
        service_verbs=tuple(payload["service_verbs"]),
        procurement_verbs=tuple(payload["procurement_verbs"]),
        route_to_market_terms=tuple(payload["route_to_market_terms"]),
        pre_position_terms=tuple(payload["pre_position_terms"]),
        direct_outreach_terms=tuple(payload["direct_outreach_terms"]),
        trigger_terms=tuple(payload["trigger_terms"]),
        active_notice_terms=tuple(payload["active_notice_terms"]),
        job_posting_terms=tuple(payload["job_posting_terms"]),
        migration_patterns=tuple(payload["migration_patterns"]),
        generic_terms=tuple(payload["generic_terms"]),
        hard_negative_terms=tuple(payload["hard_negative_terms"]),
        false_friend_patterns=tuple(payload["false_friend_patterns"]),
        coexistence_exceptions=tuple(payload["coexistence_exceptions"]),
        english_markers=tuple(payload["english_markers"]),
        portal_fingerprints=payload["portal_fingerprints"],
        source_profiles=payload["source_profiles"],
    )


class QueryCompiler:
    def __init__(self, rules: RetrievalRuleSet | None = None) -> None:
        self.rules = rules or load_retrieval_rules()

    def compile_for_source(self, source: SourceRegistry | str) -> list[CompiledQuery]:
        source_name = source if isinstance(source, str) else source.name
        profile = self.rules.source_profile(source_name)
        fields = tuple(profile.get("query_fields", ["title", "description"]))
        negative_terms = tuple(self.rules.hard_negative_terms + self.rules.false_friend_patterns)
        queries: list[CompiledQuery] = []
        family_specs = (
            (
                "formal_procurement",
                RadarLane.FORMAL_PROCUREMENT.value,
                "exact_phrase",
                tuple(self.rules.priority_product_terms[:6]),
                tuple(self.rules.service_verbs[:8]),
                tuple(self.rules.procurement_verbs[:10]),
            ),
            (
                "pre_positioning",
                RadarLane.PRE_POSITIONING.value,
                "lane_specific",
                tuple(self.rules.priority_product_terms[:5]),
                tuple(self.rules.route_to_market_terms[:8]),
                tuple(self.rules.pre_position_terms[:10]),
            ),
            (
                "direct_outreach",
                RadarLane.DIRECT_OUTREACH.value,
                "field_constrained",
                tuple(self.rules.priority_product_terms[:6]),
                tuple(self.rules.service_verbs[:8]),
                tuple(self.rules.direct_outreach_terms[:10]),
            ),
            (
                "install_base_trigger",
                RadarLane.INSTALL_BASE_TRIGGER.value,
                "trigger_hunt",
                tuple(self.rules.legacy_product_terms[:8]),
                tuple(self.rules.service_verbs[:8]),
                tuple(self.rules.trigger_terms[:10]),
            ),
        )
        for family, lane, mode, anchors, intent_terms, context_terms in family_specs:
            for field in fields:
                exact_query = self._render_query(field, anchors, intent_terms[:4], context_terms[:4])
                queries.append(
                    CompiledQuery(
                        source_name=source_name,
                        query_id=_hash_id(source_name, family, field, "exact", exact_query),
                        mode=mode,
                        phase="exact",
                        query_family=family,
                        signal_lane=lane,
                        target_field=field,
                        query_text=exact_query,
                        negative_terms=negative_terms,
                        required_anchors=anchors,
                    )
                )
                expanded_query = self._render_query(field, anchors, intent_terms, context_terms)
                queries.append(
                    CompiledQuery(
                        source_name=source_name,
                        query_id=_hash_id(source_name, family, field, "expanded", expanded_query),
                        mode=mode,
                        phase="expanded",
                        query_family=family,
                        signal_lane=lane,
                        target_field=field,
                        query_text=expanded_query,
                        negative_terms=negative_terms,
                        required_anchors=anchors,
                    )
                )
        return queries

    def primary_query(
        self,
        source: SourceRegistry | str,
        *,
        lane: str | None = None,
        query_family: str | None = None,
    ) -> CompiledQuery:
        queries = self.compile_for_source(source)
        for query in queries:
            if query_family and query.query_family == query_family:
                return query
            if lane and query.signal_lane == lane:
                return query
        return queries[0]

    def render_for_source(self, source: SourceRegistry, query: CompiledQuery) -> RenderedQuery:
        profile = self.rules.source_profile(source.name)
        capabilities = dict(source.search_capabilities_json or {})
        supports_query = bool(capabilities.get("supports_query"))
        supports_field_queries = bool(capabilities.get("supports_field_queries"))
        renderer = str(
            profile.get("query_renderer")
            or capabilities.get("renderer")
            or (source.config_json or {}).get("query_renderer")
            or self._default_renderer(source, supports_query=supports_query)
        )
        terms = self._extract_terms(query.query_text)
        if renderer == "ted_api":
            rendered = self._render_ted_query(terms)
            return RenderedQuery(
                source_name=source.name,
                query_id=query.query_id,
                mode=query.mode,
                phase=query.phase,
                query_family=query.query_family,
                signal_lane=query.signal_lane,
                target_field=query.target_field,
                abstract_query_text=query.query_text,
                rendered_query_text=rendered,
                negative_terms=query.negative_terms,
                required_anchors=query.required_anchors,
                renderer=renderer,
                remote_supported=True,
                metadata={"profile": profile.get("name"), "supports_field_queries": True},
            )
        if renderer == "plain_keywords":
            rendered = self._render_plain_query(terms)
            return RenderedQuery(
                source_name=source.name,
                query_id=query.query_id,
                mode=query.mode,
                phase=query.phase,
                query_family=query.query_family,
                signal_lane=query.signal_lane,
                target_field=query.target_field,
                abstract_query_text=query.query_text,
                rendered_query_text=rendered,
                negative_terms=query.negative_terms,
                required_anchors=query.required_anchors,
                renderer=renderer,
                remote_supported=True,
                metadata={"profile": profile.get("name"), "supports_field_queries": False, "quote_multiword": True},
            )
        if renderer == "plain_keywords_unquoted":
            rendered = self._render_plain_query(terms, quote_multiword=False)
            return RenderedQuery(
                source_name=source.name,
                query_id=query.query_id,
                mode=query.mode,
                phase=query.phase,
                query_family=query.query_family,
                signal_lane=query.signal_lane,
                target_field=query.target_field,
                abstract_query_text=query.query_text,
                rendered_query_text=rendered,
                negative_terms=query.negative_terms,
                required_anchors=query.required_anchors,
                renderer=renderer,
                remote_supported=True,
                metadata={"profile": profile.get("name"), "supports_field_queries": False, "quote_multiword": False},
            )
        if renderer == "structured_boolean" and supports_query:
            rendered = query.query_text if supports_field_queries else self._render_boolean_query(terms)
            return RenderedQuery(
                source_name=source.name,
                query_id=query.query_id,
                mode=query.mode,
                phase=query.phase,
                query_family=query.query_family,
                signal_lane=query.signal_lane,
                target_field=query.target_field,
                abstract_query_text=query.query_text,
                rendered_query_text=rendered,
                negative_terms=query.negative_terms,
                required_anchors=query.required_anchors,
                renderer=renderer,
                remote_supported=True,
                metadata={"profile": profile.get("name"), "supports_field_queries": supports_field_queries},
            )
        browse_text = self._render_browse_hint(query)
        return RenderedQuery(
            source_name=source.name,
            query_id=query.query_id,
            mode=query.mode,
            phase=query.phase,
            query_family=query.query_family,
            signal_lane=query.signal_lane,
            target_field=query.target_field,
            abstract_query_text=query.query_text,
            rendered_query_text=browse_text,
            negative_terms=query.negative_terms,
            required_anchors=query.required_anchors,
            renderer="browse_only",
            remote_supported=False,
            browse_only=True,
            metadata={"profile": profile.get("name"), "supports_field_queries": False},
        )

    def _render_query(
        self,
        field: str,
        product_terms: tuple[str, ...],
        service_terms: tuple[str, ...],
        procurement_terms: tuple[str, ...],
    ) -> str:
        products = " OR ".join(f'"{term}"' for term in product_terms)
        services = " OR ".join(f'"{term}"' for term in service_terms)
        procurement = " OR ".join(f'"{term}"' for term in procurement_terms)
        return f'{field}:(({products}) AND ({services}) AND ({procurement}))'

    def _default_renderer(self, source: SourceRegistry, *, supports_query: bool) -> str:
        if source.name == "ted":
            return "ted_api"
        if source.name == "find_a_tender":
            return "plain_keywords"
        if supports_query and source.acquisition_method.value in {"api", "search_api"}:
            return "structured_boolean"
        if supports_query and source.acquisition_method.value in {"html", "rss"}:
            return "plain_keywords"
        return "browse_only"

    def _extract_terms(self, query_text: str) -> list[str]:
        quoted = [match.strip() for match in re.findall(r'"([^"]+)"', query_text)]
        if quoted:
            return list(dict.fromkeys(quoted))
        tokens = [token for token in WORD_RE.findall(query_text) if len(token) > 2]
        return list(dict.fromkeys(tokens))

    def _render_plain_query(
        self,
        terms: list[str],
        *,
        anchor_limit: int = 2,
        context_limit: int = 2,
        quote_multiword: bool = True,
    ) -> str:
        anchors = [term for term in terms if term in self.rules.positive_product_terms or term in self.rules.anchored_short_terms]
        context = [term for term in terms if term not in anchors]
        selected = list(dict.fromkeys((anchors[:anchor_limit] or terms[:2]) + context[:context_limit]))
        return " ".join(f'"{term}"' if quote_multiword and " " in term else term for term in selected)

    def _render_boolean_query(self, terms: list[str], *, anchor_limit: int = 4, context_limit: int = 4) -> str:
        anchors = [term for term in terms if term in self.rules.positive_product_terms or term in self.rules.anchored_short_terms]
        context = [term for term in terms if term not in anchors]
        anchor_expr = " OR ".join(f'"{term}"' for term in anchors[:anchor_limit] or terms[:2])
        context_expr = " OR ".join(f'"{term}"' for term in context[:context_limit])
        if context_expr:
            return f"({anchor_expr}) AND ({context_expr})"
        return anchor_expr

    def _render_ted_query(self, terms: list[str]) -> str:
        anchors = [term for term in terms if term in self.rules.positive_product_terms or term in self.rules.anchored_short_terms]
        context = [term for term in terms if term not in anchors]
        anchor_expr = " OR ".join(f'FT ~ "{term}"' for term in anchors[:4] or terms[:2])
        context_expr = " OR ".join(f'FT ~ "{term}"' for term in context[:4])
        if context_expr:
            return f"({anchor_expr}) AND ({context_expr})"
        return anchor_expr

    def _render_browse_hint(self, query: CompiledQuery) -> str:
        anchors = ", ".join(query.required_anchors[:4])
        return f"browse {query.query_family} for {anchors}"


class QueryExecutionPlanner:
    def __init__(self, query_compiler: QueryCompiler | None = None) -> None:
        self.query_compiler = query_compiler or QueryCompiler()
        self.settings = get_settings()

    def plan(self, source: SourceRegistry, *, mode: str = "incremental_sync") -> QueryExecutionPlan:
        compiled_queries = self.query_compiler.compile_for_source(source)
        rendered_queries = [self.query_compiler.render_for_source(source, query) for query in compiled_queries]
        deduped: list[RenderedQuery] = []
        seen: set[tuple[str, str, str, str]] = set()
        source_config = dict(source.config_json or {})
        query_agnostic = bool(source_config.get("query_agnostic"))
        for query in rendered_queries:
            if query_agnostic:
                key = (
                    "query_agnostic",
                    source.name,
                    "",
                    "",
                )
            elif query.remote_supported:
                if query.renderer in {"plain_keywords", "plain_keywords_unquoted"} and not query.metadata.get("supports_field_queries", True):
                    key = (
                        query.query_family,
                        query.renderer,
                        normalize_text(query.rendered_query_text),
                        "",
                    )
                else:
                    key = (
                        query.query_family,
                        query.phase,
                        query.target_field,
                        query.rendered_query_text,
                    )
            else:
                key = (
                    "browse_only",
                    source.name if query_agnostic else query.query_family,
                    "",
                    f"browse:{source.name}",
                )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(query)
        limit = self.settings.backfill_query_fanout_limit if mode == "bootstrap_backfill" else self.settings.query_fanout_limit
        return QueryExecutionPlan(source_name=source.name, mode=mode, queries=tuple(deduped[:limit]))


class LanguageGate:
    def __init__(self, rules: RetrievalRuleSet | None = None) -> None:
        self.rules = rules or load_retrieval_rules()

    def assess(self, evidence) -> LanguageDecision:
        explicit_languages = {
            str(value).lower()
            for value in (
                evidence.language_status,
                evidence.extracted_data.get("language"),
                evidence.extracted_data.get("lang"),
            )
            if value
        }
        if any(lang.startswith("en") for lang in explicit_languages):
            return LanguageDecision("english_metadata", 1.0, "metadata", {"languages": sorted(explicit_languages)})
        alternate_links = evidence.extracted_data.get("alternate_links") or {}
        if isinstance(alternate_links, dict):
            for key, value in alternate_links.items():
                if str(key).lower().startswith("en") and value:
                    return LanguageDecision("english_alternate", 0.95, "alternate", {"alternate_url": value})
        attachment_metadata = evidence.attachment_metadata or []
        attachment_text = " ".join(item.get("excerpt", "") for item in attachment_metadata if isinstance(item, dict))
        fields = (
            ("title", evidence.title or ""),
            ("summary", evidence.summary or ""),
            ("excerpt", evidence.raw_excerpt or ""),
            ("attachment", attachment_text),
        )
        best_field = "unknown"
        best_score = 0.0
        best_hits = 0
        for label, value in fields:
            score, hits = self._english_score(value)
            if score > best_score:
                best_field = label
                best_score = score
                best_hits = hits
        if best_score >= 0.22 and best_hits >= 2:
            return LanguageDecision("english", round(best_score, 3), best_field, {"marker_hits": best_hits})
        if best_score >= 0.12 and best_hits >= 1:
            return LanguageDecision("mixed_with_english", round(best_score, 3), best_field, {"marker_hits": best_hits})
        return LanguageDecision("non_english_only", round(best_score, 3), best_field, {"marker_hits": best_hits})

    def _english_score(self, text: str) -> tuple[float, int]:
        normalized = normalize_text(text)
        if not normalized:
            return 0.0, 0
        tokens = WORD_RE.findall(normalized)
        if not tokens:
            return 0.0, 0
        marker_hits = sum(1 for marker in self.rules.english_markers if marker in tokens or marker in normalized)
        ascii_letters = sum(1 for char in normalized if char.isascii() and (char.isalpha() or char.isspace()))
        ascii_ratio = ascii_letters / max(len(normalized), 1)
        lexical_ratio = marker_hits / max(len(tokens), 1)
        return min(1.0, (ascii_ratio * 0.65) + min(0.35, lexical_ratio * 4.0)), marker_hits


class RetrievalScorer:
    def __init__(
        self,
        *,
        rules: RetrievalRuleSet | None = None,
        query_compiler: QueryCompiler | None = None,
        language_gate: LanguageGate | None = None,
    ) -> None:
        self.rules = rules or load_retrieval_rules()
        self.query_compiler = query_compiler or QueryCompiler(self.rules)
        self.language_gate = language_gate or LanguageGate(self.rules)

    def assess(self, evidence, source: SourceRegistry, *, corroboration_count: int = 0) -> RetrievalAssessment:
        full_text = self._compose_text(evidence)
        normalized = normalize_text(full_text)
        language = self.language_gate.assess(evidence)
        core_hits = self.rules.match_terms(normalized, self.rules.core_product_terms)
        legacy_hits = self.rules.match_terms(normalized, self.rules.legacy_product_terms)
        positive_terms = tuple(sorted(set(core_hits + legacy_hits + self.rules.match_positive_terms(normalized))))
        negative_terms = tuple(self.rules.match_negative_terms(normalized))
        service_terms = tuple(sorted(set(self.rules.match_terms(normalized, self.rules.service_verbs))))
        procurement_terms = tuple(sorted(set(self.rules.match_terms(normalized, self.rules.procurement_verbs))))
        route_terms = tuple(sorted(set(self.rules.match_terms(normalized, self.rules.route_to_market_terms))))
        direct_terms = tuple(sorted(set(self.rules.match_terms(normalized, self.rules.direct_outreach_terms))))
        trigger_terms = tuple(
            sorted(
                set(
                    self.rules.match_terms(normalized, self.rules.trigger_terms)
                    + self.rules.match_terms(normalized, self.rules.migration_patterns)
                )
            )
        )
        pre_position_terms = tuple(sorted(set(self.rules.match_terms(normalized, self.rules.pre_position_terms))))
        active_terms = tuple(sorted(set(self.rules.match_terms(normalized, self.rules.active_notice_terms))))
        job_terms = tuple(sorted(set(self.rules.match_terms(normalized, self.rules.job_posting_terms))))
        source_trust = round(self._source_trust(source), 3)
        anchored = bool(positive_terms)
        generic_hits = tuple(sorted(set(self.rules.match_terms(normalized, self.rules.generic_terms))))
        false_friend = any(term in self.rules.false_friend_patterns for term in negative_terms)
        competitor_only = bool(negative_terms) and not self.rules.has_coexistence_exception(normalized) and not anchored
        bare_generic = bool(generic_hits) and not anchored

        exclusion_reason: str | None = None
        if language.status == "non_english_only":
            exclusion_reason = "non_english_only"
        elif false_friend:
            exclusion_reason = "false_friend_match"
        elif competitor_only:
            exclusion_reason = "competitor_tender"
        elif bare_generic:
            exclusion_reason = "missing_microsoft_anchor"
        elif not anchored and not legacy_hits:
            exclusion_reason = "no_d365_anchor"

        freshness = self._freshness_score(evidence.publication_date, evidence.close_date)
        english_access = {
            "english_metadata": 1.0,
            "english_alternate": 0.95,
            "english": 0.9,
            "mixed_with_english": 0.6,
        }.get(language.status, 0.0)
        d365_specificity = min(1.0, (len(positive_terms) * 0.2) + (0.15 if legacy_hits else 0.0))
        serviceability = min(
            1.0,
            (len(service_terms) * 0.14)
            + (0.22 if evidence.response_url else 0.0)
            + (0.16 if evidence.contact_email or evidence.contact_name else 0.0),
        )
        procurement_explicitness = min(
            1.0,
            (len(procurement_terms) * 0.14)
            + (0.2 if evidence.close_date else 0.0)
            + (0.18 if evidence.response_url else 0.0)
            + (0.18 if active_terms else 0.0),
        )
        buyer_explicitness = min(
            1.0,
            (0.38 if evidence.buyer_name else 0.0)
            + (0.16 if evidence.procurement_id else 0.0)
            + (0.2 if evidence.contact_name or evidence.contact_email else 0.0)
            + (0.12 if evidence.buyer_country else 0.0)
            + (0.14 if evidence.response_url else 0.0),
        )
        corroboration = min(1.0, corroboration_count / 4)
        completeness = self._completeness_score(evidence)
        competitor_penalty = 1.0 if competitor_only else 0.0
        ambiguity_penalty = 1.0 if bare_generic or false_friend else (0.45 if not anchored and generic_hits else 0.0)

        service_fit = _clamp((d365_specificity * 35) + (serviceability * 45) + (0.2 * len(service_terms) * 20))
        buyer_quality = _clamp((source_trust * 35) + (buyer_explicitness * 45) + (english_access * 10) + (freshness * 10))
        corroboration_score = _clamp((corroboration * 75) + (0.25 * completeness * 100))

        formal_score = _clamp(
            (procurement_explicitness * 45)
            + (serviceability * 15)
            + (buyer_explicitness * 15)
            + (d365_specificity * 15)
            + (0.1 * len(active_terms) * 50)
        )
        pre_position_score = _clamp(
            (len(pre_position_terms) * 10)
            + (len(route_terms) * 8)
            + (buyer_explicitness * 25)
            + (corroboration * 15)
            + (english_access * 10)
            + (0.25 * len(procurement_terms) * 20)
        )
        account_intent_score = _clamp(
            (len(direct_terms) * 9)
            + (len(job_terms) * 8)
            + (serviceability * 25)
            + (buyer_explicitness * 20)
            + (d365_specificity * 20)
            + (english_access * 10)
        )
        install_base_trigger_score = _clamp(
            (len(legacy_hits) * 14)
            + (len(trigger_terms) * 10)
            + (serviceability * 20)
            + (d365_specificity * 20)
            + (corroboration * 10)
        )

        signal_lane = self._decide_lane(
            formal_score,
            pre_position_score,
            account_intent_score,
            install_base_trigger_score,
            active_terms,
            pre_position_terms,
            direct_terms,
            legacy_hits,
            job_terms,
        )
        route_to_market, procurement_cycle_stage, vehicle_type = self._route_to_market(
            signal_lane,
            normalized,
            pre_position_terms,
            route_terms,
            active_terms,
        )
        installed_product_guess, installed_product_evidence = self._installed_product(legacy_hits)
        trigger_type, trigger_strength = self._trigger_details(
            signal_lane,
            legacy_hits,
            trigger_terms,
            direct_terms,
            normalized,
        )
        portal_fingerprint = self.rules.detect_portal_fingerprint(
            " ".join(filter(None, [source.endpoint, evidence.source_url, evidence.response_url or "", full_text[:1000]]))
        )
        public_access_mode = self._public_access_mode(source, portal_fingerprint)
        recommended_action = self._recommended_action(
            signal_lane,
            formal_score,
            pre_position_score,
            account_intent_score,
            install_base_trigger_score,
            exclusion_reason,
        )
        account_heat_score = round(
            _clamp(max(pre_position_score, account_intent_score, install_base_trigger_score) * 0.55 + buyer_quality * 0.25 + corroboration_score * 0.2),
            2,
        )

        component_scores = {
            "source_trust": source_trust,
            "freshness": freshness,
            "english_accessibility": english_access,
            "d365_specificity": d365_specificity,
            "serviceability": serviceability,
            "procurement_explicitness": procurement_explicitness,
            "buyer_explicitness": buyer_explicitness,
            "corroboration": corroboration,
            "extraction_completeness": completeness,
            "formal_opportunity_score": round(formal_score, 2),
            "pre_position_score": round(pre_position_score, 2),
            "account_intent_score": round(account_intent_score, 2),
            "install_base_trigger_score": round(install_base_trigger_score, 2),
            "service_fit_score": round(service_fit, 2),
            "buyer_quality_score": round(buyer_quality, 2),
            "corroboration_score": round(corroboration_score, 2),
            "competitor_penalty": competitor_penalty,
            "ambiguity_penalty": ambiguity_penalty,
        }
        score = (
            source_trust * 15
            + freshness * 8
            + english_access * 9
            + d365_specificity * 18
            + serviceability * 12
            + procurement_explicitness * 10
            + buyer_explicitness * 8
            + corroboration * 6
            + completeness * 6
            + (max(formal_score, pre_position_score, account_intent_score, install_base_trigger_score) / 100.0) * 8
            - competitor_penalty * 20
            - ambiguity_penalty * 14
        )
        score = _clamp(score)
        if exclusion_reason and score > get_settings().signal_min_score:
            score = min(score, float(get_settings().signal_min_score - 1))

        query_family = signal_lane.value if signal_lane else None
        primary_query = self.query_compiler.primary_query(source, lane=query_family, query_family=query_family) if signal_lane else self.query_compiler.primary_query(source)
        lane_rationale = {
            "active_notice_terms": list(active_terms),
            "pre_position_terms": list(pre_position_terms),
            "direct_outreach_terms": list(direct_terms),
            "job_posting_terms": list(job_terms),
            "legacy_terms": legacy_hits,
            "route_terms": list(route_terms),
        }
        return RetrievalAssessment(
            retrieval_score=round(score, 2),
            source_trust=source_trust,
            language_status=language.status,
            language_details={"source": language.source, **language.details, "confidence": language.confidence},
            english_evidence_source=language.source,
            matched_positive_terms=positive_terms,
            matched_negative_terms=negative_terms,
            matched_service_terms=tuple(sorted(set(service_terms + trigger_terms))),
            matched_procurement_terms=procurement_terms,
            matched_route_terms=route_terms,
            matched_trigger_terms=trigger_terms,
            signal_lane=signal_lane,
            recommended_action=recommended_action,
            route_to_market=route_to_market,
            formal_opportunity_score=round(formal_score, 2),
            pre_position_score=round(pre_position_score, 2),
            account_intent_score=round(account_intent_score, 2),
            install_base_trigger_score=round(install_base_trigger_score, 2),
            service_fit_score=round(service_fit, 2),
            buyer_quality_score=round(buyer_quality, 2),
            corroboration_score=round(corroboration_score, 2),
            account_heat_score=account_heat_score,
            procurement_cycle_stage=procurement_cycle_stage,
            vehicle_type=vehicle_type,
            installed_product_guess=installed_product_guess,
            installed_product_evidence=installed_product_evidence,
            trigger_type=trigger_type,
            trigger_strength=round(trigger_strength, 2),
            incumbent_vendor=self._incumbent_vendor(normalized),
            incumbent_expiry_guess=self._incumbent_expiry(normalized),
            buyer_intent_evidence={"direct_terms": list(direct_terms), "job_terms": list(job_terms)},
            legacy_evidence={"legacy_terms": legacy_hits, "trigger_terms": list(trigger_terms)},
            query_family=query_family,
            exclusion_reason=exclusion_reason,
            query_id=primary_query.query_id,
            query_text=primary_query.query_text,
            source_discovery_confidence=float(getattr(source, "source_discovery_confidence", 0.0) or 0.0),
            corroboration_count=corroboration_count,
            portal_fingerprint=portal_fingerprint,
            public_access_mode=public_access_mode,
            known_blind_spot_reason=getattr(source, "known_blind_spot_reason", None),
            component_scores=component_scores,
            lane_rationale=lane_rationale,
        )

    def _compose_text(self, evidence) -> str:
        parts = [
            evidence.title,
            evidence.summary,
            evidence.raw_excerpt,
            evidence.notice_type,
            evidence.procurement_type,
            " ".join(evidence.lot_titles or []),
            " ".join(evidence.product_mentions or []),
            " ".join(evidence.service_mentions or []),
            " ".join(evidence.tags or []),
        ]
        for attachment in evidence.attachment_metadata or []:
            if isinstance(attachment, dict):
                parts.append(attachment.get("excerpt", ""))
                parts.append(attachment.get("title", ""))
        return " ".join(filter(None, parts))

    def _source_trust(self, source: SourceRegistry) -> float:
        profile = self.rules.source_profile(source.name)
        if profile.get("source_trust") is not None:
            return float(profile["source_trust"])
        host = urlparse(source.endpoint).hostname or ""
        if host.endswith((".gov", ".gov.uk", ".gc.ca", ".gov.au", ".govt.nz", ".go.ke", ".gov.in")):
            return 0.96
        if host.endswith(".int"):
            return 0.94
        if ".org" in host:
            return 0.82
        return 0.72

    def _freshness_score(self, publication_date: datetime | None, close_date: datetime | None) -> float:
        now = datetime.now(UTC)
        if close_date:
            close_dt = close_date if close_date.tzinfo else close_date.replace(tzinfo=UTC)
            days_until_close = (close_dt - now).days
            if days_until_close >= 0:
                if days_until_close <= 14:
                    return 1.0
                if days_until_close <= 45:
                    return 0.85
                return 0.7
        if publication_date:
            published = publication_date if publication_date.tzinfo else publication_date.replace(tzinfo=UTC)
            age_days = (now - published).days
            if age_days <= 14:
                return 1.0
            if age_days <= 45:
                return 0.85
            if age_days <= 120:
                return 0.6
        return 0.45

    def _completeness_score(self, evidence) -> float:
        checks = (
            bool(evidence.title),
            bool(evidence.buyer_name),
            bool(evidence.summary),
            bool(evidence.procurement_id),
            bool(evidence.source_url),
            bool(evidence.close_date),
            bool(evidence.response_url),
            bool(evidence.attachment_urls or evidence.attachment_metadata),
        )
        return round(sum(1 for check in checks if check) / len(checks), 3)

    def _decide_lane(
        self,
        formal_score: float,
        pre_position_score: float,
        account_intent_score: float,
        install_base_trigger_score: float,
        active_terms: tuple[str, ...],
        pre_terms: tuple[str, ...],
        direct_terms: tuple[str, ...],
        legacy_hits: list[str],
        job_terms: tuple[str, ...],
    ) -> RadarLane | None:
        if formal_score >= 48 and active_terms:
            return RadarLane.FORMAL_PROCUREMENT
        if pre_position_score >= 40 and pre_terms:
            return RadarLane.PRE_POSITIONING
        if install_base_trigger_score >= 40 and legacy_hits:
            return RadarLane.INSTALL_BASE_TRIGGER
        if account_intent_score >= 36 and (direct_terms or job_terms):
            return RadarLane.DIRECT_OUTREACH
        best = max(
            (
                (formal_score, RadarLane.FORMAL_PROCUREMENT),
                (pre_position_score, RadarLane.PRE_POSITIONING),
                (account_intent_score, RadarLane.DIRECT_OUTREACH),
                (install_base_trigger_score, RadarLane.INSTALL_BASE_TRIGGER),
            ),
            key=lambda item: item[0],
        )
        return best[1] if best[0] >= get_settings().signal_min_score else None

    def _route_to_market(
        self,
        lane: RadarLane | None,
        normalized: str,
        pre_terms: tuple[str, ...],
        route_terms: tuple[str, ...],
        active_terms: tuple[str, ...],
    ) -> tuple[RouteToMarket, str | None, str | None]:
        if lane == RadarLane.FORMAL_PROCUREMENT:
            return RouteToMarket.FORMAL_BID, "active_solicitation", None
        if lane == RadarLane.PRE_POSITIONING:
            if any(term in pre_terms or term in route_terms for term in ("framework agreement", "standing offer", "supply arrangement", "dynamic purchasing system")):
                return RouteToMarket.FRAMEWORK_VEHICLE, "framework_vehicle", "framework"
            if any(term in pre_terms or term in route_terms for term in ("vendor registration", "supplier onboarding", "pre-qualification", "approved supplier")):
                return RouteToMarket.VENDOR_REGISTRATION, "vendor_registration", "vendor_list"
            if any(term in normalized for term in ("award notice", "contract history", "renewal", "expiry", "incumbent")):
                return RouteToMarket.RENEWAL_WATCH, "renewal_watch", "renewal"
            return RouteToMarket.FRAMEWORK_VEHICLE, "market_engagement", None
        if lane == RadarLane.INSTALL_BASE_TRIGGER:
            return RouteToMarket.DIRECT_OUTREACH, "install_base_trigger", None
        if lane == RadarLane.DIRECT_OUTREACH:
            if any(term in normalized for term in ("incumbent", "award notice")):
                return RouteToMarket.PARTNER_WITH_INCUMBENT, "partner_signal", None
            if active_terms:
                return RouteToMarket.FORMAL_BID, "active_solicitation", None
            return RouteToMarket.DIRECT_OUTREACH, "buyer_intent", None
        return RouteToMarket.UNKNOWN, None, None

    def _installed_product(self, legacy_hits: list[str]) -> tuple[str | None, str | None]:
        if not legacy_hits:
            return None, None
        mapping = {
            "dynamics nav": "Dynamics NAV / Navision",
            "navision": "Dynamics NAV / Navision",
            "dynamics ax": "Dynamics AX / Finance and Operations",
            "finance and operations": "Dynamics AX / Finance and Operations",
            "f&o": "Dynamics AX / Finance and Operations",
            "dynamics crm": "Dynamics CRM",
            "dynamics crm 2016": "Dynamics CRM",
            "dynamics gp": "Dynamics GP / Great Plains",
            "great plains": "Dynamics GP / Great Plains",
            "dynamics sl": "Dynamics SL",
        }
        for term in legacy_hits:
            if term.lower() in mapping:
                return mapping[term.lower()], term
        return legacy_hits[0], legacy_hits[0]

    def _trigger_details(
        self,
        lane: RadarLane | None,
        legacy_hits: list[str],
        trigger_terms: tuple[str, ...],
        direct_terms: tuple[str, ...],
        normalized: str,
    ) -> tuple[str | None, float]:
        if lane == RadarLane.INSTALL_BASE_TRIGGER and legacy_hits:
            if any(term in normalized for term in ("end of support", "on-premises", "on premises", "replace", "modernize")):
                return "migration_pressure", _clamp((len(legacy_hits) * 18) + (len(trigger_terms) * 9))
            if any(term in normalized for term in ("support", "managed service", "managed support", "stabilization", "rescue")):
                return "support_need", _clamp((len(legacy_hits) * 16) + (len(trigger_terms) * 8))
            return "legacy_estate", _clamp((len(legacy_hits) * 15) + (len(trigger_terms) * 7))
        if lane == RadarLane.DIRECT_OUTREACH and direct_terms:
            return "buyer_intent", _clamp((len(direct_terms) * 9) + (len(trigger_terms) * 5))
        return None, 0.0

    def _recommended_action(
        self,
        lane: RadarLane | None,
        formal_score: float,
        pre_position_score: float,
        account_intent_score: float,
        install_base_trigger_score: float,
        exclusion_reason: str | None,
    ) -> RecommendedAction:
        if exclusion_reason:
            return RecommendedAction.REJECT
        if lane == RadarLane.FORMAL_PROCUREMENT:
            return RecommendedAction.BID_NOW if formal_score >= 55 else RecommendedAction.MONITOR
        if lane == RadarLane.PRE_POSITIONING:
            return RecommendedAction.PRE_POSITION if pre_position_score >= 45 else RecommendedAction.MONITOR
        if lane == RadarLane.DIRECT_OUTREACH:
            return RecommendedAction.OUTREACH_NOW if account_intent_score >= 45 else RecommendedAction.MONITOR
        if lane == RadarLane.INSTALL_BASE_TRIGGER:
            return RecommendedAction.OUTREACH_NOW if install_base_trigger_score >= 45 else RecommendedAction.MONITOR
        return RecommendedAction.REJECT

    def _public_access_mode(self, source: SourceRegistry, portal_fingerprint: str | None) -> PublicAccessMode:
        source_mode = getattr(source, "public_access_mode", None)
        if source_mode:
            return source_mode
        if portal_fingerprint in {"ariba", "sap_business_network_discovery", "jaggaer", "oracle_procurement"}:
            return PublicAccessMode.ACCOUNT_OPTIONAL
        return PublicAccessMode.PUBLIC

    def _incumbent_vendor(self, normalized: str) -> str | None:
        match = re.search(r"incumbent vendor[:\s]+([a-z0-9& .,-]{3,80})", normalized)
        return match.group(1).strip().title() if match else None

    def _incumbent_expiry(self, normalized: str) -> str | None:
        match = re.search(r"(?:contract expiry|expires?)[:\s]+([a-z0-9 ,/-]{4,40})", normalized)
        return match.group(1).strip() if match else None
