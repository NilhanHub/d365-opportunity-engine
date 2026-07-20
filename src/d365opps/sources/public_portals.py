from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from urllib.parse import parse_qs, urljoin, urlparse
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from bs4 import BeautifulSoup

from d365opps.config import get_settings
from d365opps.retrieval import QueryCompiler
from d365opps.schemas import ExtractedEvidence, FetchBatch
from d365opps.sources.base import BaseSourceAdapter


CPV_CODE_RE = re.compile(r"\b\d{8}\b")
QUOTED_TERM_RE = re.compile(r'"([^"]+)"')
PORTAL_TERM_MAP = {
    "business central": "Microsoft Business Central",
    "customer engagement": "Microsoft Dynamics Customer Engagement",
    "dataverse": "Microsoft Dataverse",
    "power platform": "Microsoft Power Platform",
    "power apps": "Microsoft Power Apps",
    "power automate": "Microsoft Power Automate",
    "power pages": "Microsoft Power Pages",
}


def _currency_code(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip().upper()
    return value if len(value) <= 3 else None


def _canonical_portal_term(value: str) -> str:
    term = " ".join(str(value).split())
    return PORTAL_TERM_MAP.get(term.lower(), term)


def _selected_portal_terms(rendered: Any, *, fallback: str = "Microsoft Dynamics") -> list[str]:
    quoted_terms: list[str] = []
    for text in (
        getattr(rendered, "abstract_query_text", None),
        getattr(rendered, "rendered_query_text", None),
    ):
        for term in QUOTED_TERM_RE.findall(str(text or "")):
            canonical = _canonical_portal_term(term)
            if canonical and canonical not in quoted_terms:
                quoted_terms.append(canonical)
    if quoted_terms:
        return quoted_terms[:4]
    anchors = [str(term).strip() for term in getattr(rendered, "required_anchors", []) if str(term).strip()]
    if not anchors:
        return [fallback]
    anchors = [_canonical_portal_term(anchor) for anchor in anchors]
    ordered: list[str] = []
    preferred_markers = ("microsoft dynamics", "dynamics 365", "power platform", "business central", "dataverse")
    for marker in preferred_markers:
        for anchor in anchors:
            if marker in anchor.lower() and anchor not in ordered:
                ordered.append(anchor)
    for anchor in anchors:
        if anchor not in ordered:
            ordered.append(anchor)
    return ordered or [fallback]


def _portal_search_text(
    rendered: Any,
    *,
    fallback: str = "Microsoft Dynamics",
    quote_multiword: bool | None = None,
    single_term: bool = False,
) -> str:
    if quote_multiword is None:
        metadata = getattr(rendered, "metadata", {}) or {}
        quote_multiword = bool(metadata.get("quote_multiword", True))
    ordered = _selected_portal_terms(rendered, fallback=fallback)
    query_id = str(getattr(rendered, "query_id", "") or "")
    selected = ordered[0]
    if query_id:
        slot = int(hashlib.sha1(query_id.encode("utf-8")).hexdigest()[:4], 16) % len(ordered)
        selected = ordered[slot] or fallback
    if single_term:
        return f'"{selected}"' if quote_multiword and " " in selected else selected
    if ordered:
        return " ".join(f'"{term}"' if quote_multiword and " " in term else term for term in ordered[:4])
    return f'"{selected}"' if quote_multiword and " " in selected else selected


class HilmaSource(BaseSourceAdapter):
    source_name = "hilma_notices"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.query_compiler = QueryCompiler()

    def fetch(self, source, since: datetime, cursor: str | None = None, query: Any | None = None, budget: Any | None = None) -> FetchBatch:
        del budget
        rendered = query or self.query_compiler.render_for_source(source, self.query_compiler.primary_query(source))
        limit = int((source.config_json or {}).get("limit", 50))
        offset = int(cursor or 0)
        endpoint = (source.config_json or {}).get("search_endpoint") or source.endpoint
        params = {
            "lang": "en",
            "search": _portal_search_text(rendered, single_term=True),
            "$filter": "isLatest eq true",
            "$orderby": "datePublished desc",
            "$top": limit,
            "$skip": offset,
        }
        response = self.client.get(endpoint, params=params)
        response.raise_for_status()
        body = response.json()
        items = body.get("value", [])
        document = self._json_document(
            external_id=f"hilma-{rendered.query_id}-{offset}",
            url=str(response.url),
            payload=body,
            metadata={
                "count": len(items),
                "query_id": rendered.query_id,
                "query_text": rendered.rendered_query_text,
                "abstract_query_text": rendered.abstract_query_text,
                "query_family": rendered.query_family,
                "phase": rendered.phase,
                "target_field": rendered.target_field,
                "renderer": rendered.renderer,
                "since": since.isoformat(),
            },
        )
        next_cursor = str(offset + limit) if len(items) >= limit else None
        return FetchBatch(documents=[document], next_cursor=next_cursor)

    def extract(self, source, raw_document, payload: bytes) -> list[ExtractedEvidence]:
        body = json.loads(payload.decode("utf-8"))
        metadata = getattr(raw_document, "metadata_json", {}) or {}
        since = self._parse_dt(metadata.get("since"))
        evidence: list[ExtractedEvidence] = []
        for item in body.get("value", []):
            published_at = self._parse_dt(item.get("datePublished"))
            if since and published_at and published_at < since:
                continue
            procurement_project_id = item.get("procurementProjectId") or item.get("id")
            notice_id = item.get("id")
            detail_url = f"https://www.hankintailmoitukset.fi/en/public/procurement/{procurement_project_id}/notice/{notice_id}/overview"
            close_date = self._parse_dt(item.get("tendersOrRequestsToParticipateDueDateTime")) or self._parse_dt(item.get("expirationDate"))
            summary = item.get("projectShortDescription") or item.get("objectDescriptions") or item.get("projectTitle")
            cpv_codes = sorted(set(CPV_CODE_RE.findall(item.get("cpvCodes") or "")))
            evidence.append(
                ExtractedEvidence(
                    title=item.get("projectTitle") or item.get("noticeNumber") or f"HILMA notice {notice_id}",
                    summary=summary,
                    buyer_name=item.get("organisationName"),
                    buyer_country="FI",
                    notice_type=item.get("mainType"),
                    procurement_type=item.get("mainType"),
                    publication_date=published_at,
                    close_date=close_date,
                    budget_value=Decimal(str(item["estimatedValue"])) if item.get("estimatedValue") not in {None, ""} else None,
                    budget_currency=_currency_code(item.get("currency")),
                    source_url=detail_url,
                    response_url=detail_url,
                    cpv_codes=cpv_codes,
                    classification_codes=cpv_codes,
                    tags=["hilma", str(item.get("mainType") or "").lower()],
                    procurement_id=item.get("noticeNumber") or item.get("noticeOjsNumber") or str(notice_id),
                    raw_excerpt=(item.get("objectDescriptions") or item.get("projectShortDescription") or "")[:2000] or None,
                    acquisition_method=getattr(source.acquisition_method, "value", None),
                    source_provenance={"upstream": source.name, "raw_document": raw_document.canonical_url},
                    discovery_query_id=metadata.get("query_id"),
                    discovery_query_text=metadata.get("query_text"),
                    query_family=metadata.get("query_family"),
                    extracted_data=item,
                )
            )
        return evidence


class IrelandETendersSource(BaseSourceAdapter):
    source_name = "ireland_etenders"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.query_compiler = QueryCompiler()

    def fetch(self, source, since: datetime, cursor: str | None = None, query: Any | None = None, budget: Any | None = None) -> FetchBatch:
        del cursor, budget
        rendered = query or self.query_compiler.render_for_source(source, self.query_compiler.primary_query(source))
        endpoint = (source.config_json or {}).get("search_endpoint") or "https://www.etenders.gov.ie/epps/viewCFTSAction.do"
        data = {
            "isExport": "true",
            "isFTS": "true",
            "isQuickSearch": "true",
            "freeText": _portal_search_text(rendered, quote_multiword=False, single_term=True),
            "type": "cftFTS",
            "tableUid": "searchCft",
        }
        response = self.client.post(endpoint, data=data)
        response.raise_for_status()
        document = self._html_document(
            url=str(response.url),
            payload=response.content,
            metadata={
                "query_id": rendered.query_id,
                "query_text": rendered.rendered_query_text,
                "abstract_query_text": rendered.abstract_query_text,
                "query_family": rendered.query_family,
                "phase": rendered.phase,
                "target_field": rendered.target_field,
                "renderer": rendered.renderer,
                "since": since.isoformat(),
            },
        )
        return FetchBatch(documents=[document], next_cursor=None)

    def extract(self, source, raw_document, payload: bytes) -> list[ExtractedEvidence]:
        metadata = getattr(raw_document, "metadata_json", {}) or {}
        since = self._parse_dt(metadata.get("since"))
        text = payload.decode("utf-8", errors="ignore")
        rows = list(csv.DictReader(io.StringIO(text)))
        evidence: list[ExtractedEvidence] = []
        for row in rows:
            published_at = self._parse_dt(row.get("DATE_PUBLISHED"))
            if since and published_at and published_at < since:
                continue
            description = row.get("DESCRIPTION") or None
            detail_type = "prepareViewCfTDPSWS.do" if "DPS" in (row.get("PROCEDURE") or "").upper() else "prepareViewCfTWS.do"
            detail_url = f"https://www.etenders.gov.ie/epps/{detail_type}?resourceId={row.get('ID')}"
            cft_status = row.get("CFT_STATUS") or None
            estimated_value = row.get("ESTIMATED_VALUE") or None
            budget_value: Decimal | None = None
            if estimated_value:
                cleaned = re.sub(r"[^0-9.]", "", estimated_value)
                if cleaned:
                    budget_value = Decimal(cleaned)
            evidence.append(
                ExtractedEvidence(
                    title=row.get("TITLE") or f"eTenders notice {row.get('ID')}",
                    summary=description,
                    buyer_name=row.get("AUTHORITY") or None,
                    buyer_country=source.country,
                    notice_type=cft_status,
                    procurement_type=row.get("PROCEDURE") or cft_status,
                    publication_date=published_at,
                    close_date=self._parse_dt(row.get("SUBMISSION_DEADLINE")),
                    budget_value=budget_value,
                    budget_currency="EUR" if budget_value is not None else None,
                    source_url=detail_url,
                    response_url=detail_url,
                    tags=["ireland_etenders", normalize_csv_tag(cft_status)],
                    procurement_id=row.get("ID"),
                    raw_excerpt=(description or "")[:2000] or None,
                    acquisition_method=getattr(source.acquisition_method, "value", None),
                    source_provenance={"upstream": source.name, "raw_document": raw_document.canonical_url},
                    discovery_query_id=metadata.get("query_id"),
                    discovery_query_text=metadata.get("query_text"),
                    query_family=metadata.get("query_family"),
                    extracted_data={**row, "CFT_STATUS": cft_status},
                )
            )
        return evidence


def normalize_csv_tag(value: str | None) -> str:
    if not value:
        return "status_unknown"
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


class WorldBankSource(BaseSourceAdapter):
    source_name = "world_bank_current"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.query_compiler = QueryCompiler()

    def fetch(self, source, since: datetime, cursor: str | None = None, query: Any | None = None, budget: Any | None = None) -> FetchBatch:
        del budget
        settings = get_settings()
        rendered = query or self.query_compiler.render_for_source(source, self.query_compiler.primary_query(source))
        offset = int(cursor or 0)
        endpoint = (source.config_json or {}).get("api_endpoint") or source.endpoint
        params = {
            "format": "json",
            "apilang": "en",
            "rows": int((source.config_json or {}).get("limit", 25)),
            "os": offset,
            "qterm": _portal_search_text(rendered, quote_multiword=False, single_term=True),
            "srt": "submission_date desc,id asc",
        }
        response = self.client.get(endpoint, params=params)
        response.raise_for_status()
        body = response.json()
        items = body.get("procnotices", []) or []
        document = self._json_document(
            external_id=f"world-bank-{rendered.query_id}-{offset}",
            url=str(response.url),
            payload=body,
            metadata={
                "count": len(items),
                "query_id": rendered.query_id,
                "query_text": rendered.rendered_query_text,
                "abstract_query_text": rendered.abstract_query_text,
                "query_family": rendered.query_family,
                "phase": rendered.phase,
                "target_field": rendered.target_field,
                "renderer": rendered.renderer,
                "since": since.isoformat(),
            },
        )
        total = int(body.get("total") or 0)
        next_cursor = str(offset + params["rows"]) if (offset + params["rows"]) < total and items else None
        return FetchBatch(documents=[document], next_cursor=next_cursor)

    def extract(self, source, raw_document, payload: bytes) -> list[ExtractedEvidence]:
        body = json.loads(payload.decode("utf-8"))
        metadata = getattr(raw_document, "metadata_json", {}) or {}
        since = self._parse_dt(metadata.get("since"))
        evidence: list[ExtractedEvidence] = []
        for item in body.get("procnotices", []) or []:
            published_at = self._parse_dt(item.get("noticedate"))
            if since and published_at and published_at < since:
                continue
            notice_type = _text(item.get("notice_type"))
            if source.name == "world_bank_current" and any(
                marker in notice_type.lower() for marker in ("expression of interest", "contract award", "general procurement notice")
            ):
                continue
            detail_url = f"https://projects.worldbank.org/en/projects-operations/procurement-detail/{item.get('id')}"
            description = item.get("bid_description") or item.get("notice_text")
            evidence.append(
                ExtractedEvidence(
                    title=item.get("bid_description") or item.get("project_name") or f"World Bank notice {item.get('id')}",
                    summary=item.get("project_name"),
                    buyer_name="World Bank borrower",
                    buyer_country=item.get("project_ctry_name"),
                    notice_type=item.get("notice_type"),
                    procurement_type=item.get("procurement_method_name") or item.get("notice_type"),
                    publication_date=published_at,
                    close_date=self._parse_dt(item.get("submission_date")),
                    source_url=detail_url,
                    response_url=detail_url,
                    tags=["world_bank", normalize_csv_tag(item.get("notice_type"))],
                    procurement_id=item.get("id"),
                    raw_excerpt=(description or "")[:2000] or None,
                    acquisition_method=getattr(source.acquisition_method, "value", None),
                    source_provenance={"upstream": source.name, "raw_document": raw_document.canonical_url},
                    discovery_query_id=metadata.get("query_id"),
                    discovery_query_text=metadata.get("query_text"),
                    query_family=metadata.get("query_family"),
                    extracted_data=item,
                )
            )
        return evidence


def _text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


def _nested_value(value: Any, *keys: str) -> str | None:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    text = _text(current)
    return text or None


def _first_value(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if item.get(key) not in {None, ""}:
            return item.get(key)
    return None


def _joined_text(values: list[str]) -> str | None:
    cleaned = [_text(value) for value in values if _text(value)]
    return " | ".join(cleaned) if cleaned else None


def _gets_label_map(html: bytes) -> dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    labels: dict[str, str] = {}
    for label in soup.select("td.label-cell"):
        key = _text(label.get_text(" ", strip=True)).rstrip(":")
        value_cell = label.find_next_sibling("td")
        value = _text(value_cell.get_text(" ", strip=True) if value_cell else "")
        if key and value:
            labels[key] = value
    return labels


def _gets_summary(html: bytes) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    for selector in (
        "#tenderNoticeDescription",
        "div.noticeDescription",
        "div.description",
        "div#content",
    ):
        node = soup.select_one(selector)
        if node:
            text = _text(node.get_text(" ", strip=True))
            if text:
                return text[:4000]
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    return _text(title)[:4000] or None


def _gets_detail_id(url: str) -> str | None:
    query = parse_qs(urlparse(url).query)
    ids = query.get("id") or query.get("ID")
    return ids[0] if ids else None


class WorldBankUpcomingSource(WorldBankSource):
    source_name = "world_bank_upcoming"

    def extract(self, source, raw_document, payload: bytes) -> list[ExtractedEvidence]:
        rows = super().extract(source, raw_document, payload)
        filtered: list[ExtractedEvidence] = []
        for row in rows:
            notice_type = _text((row.extracted_data or {}).get("notice_type") or row.notice_type)
            if "expression of interest" in notice_type.lower() or "upcoming" in notice_type.lower():
                filtered.append(row)
        return filtered


class WorldBankPotentialSource(WorldBankSource):
    source_name = "world_bank_potential"

    def extract(self, source, raw_document, payload: bytes) -> list[ExtractedEvidence]:
        rows = super().extract(source, raw_document, payload)
        filtered: list[ExtractedEvidence] = []
        for row in rows:
            notice_type = _text((row.extracted_data or {}).get("notice_type") or row.notice_type)
            if any(marker in notice_type.lower() for marker in ("general procurement notice", "contract award", "pipeline", "potential")):
                filtered.append(row)
        return filtered


class TenderNedSource(BaseSourceAdapter):
    source_name = "tenderned"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.query_compiler = QueryCompiler()

    def fetch(self, source, since: datetime, cursor: str | None = None, query: Any | None = None, budget: Any | None = None) -> FetchBatch:
        del budget
        rendered = query or self.query_compiler.render_for_source(source, self.query_compiler.primary_query(source))
        config = source.config_json or {}
        endpoint = config.get("api_endpoint") or source.endpoint
        page = int(cursor or 0)
        params = {
            "page": page,
            "size": int(config.get("limit", 25)),
            config.get("search_param", "search"): _portal_search_text(rendered, quote_multiword=False, single_term=True),
        }
        response = self.client.get(endpoint, params=params)
        response.raise_for_status()
        body = response.json()
        document = self._json_document(
            external_id=f"tenderned-{rendered.query_id}-{page}",
            url=str(response.url),
            payload=body,
            metadata={
                "query_id": rendered.query_id,
                "query_text": rendered.rendered_query_text,
                "abstract_query_text": rendered.abstract_query_text,
                "query_family": rendered.query_family,
                "phase": rendered.phase,
                "target_field": rendered.target_field,
                "renderer": rendered.renderer,
                "since": since.isoformat(),
            },
        )
        next_cursor = str(page + 1) if body.get("content") and not body.get("last", True) else None
        return FetchBatch(documents=[document], next_cursor=next_cursor)

    def extract(self, source, raw_document, payload: bytes) -> list[ExtractedEvidence]:
        body = json.loads(payload.decode("utf-8"))
        metadata = getattr(raw_document, "metadata_json", {}) or {}
        since = self._parse_dt(metadata.get("since"))
        evidence: list[ExtractedEvidence] = []
        for item in body.get("content", []) or []:
            published_at = self._parse_dt(item.get("publicatieDatum"))
            if since and published_at and published_at < since:
                continue
            type_publication = _nested_value(item.get("typePublicatie"), "omschrijving")
            procedure = _nested_value(item.get("procedure"), "omschrijving")
            status = _nested_value(item.get("publicatiestatus"), "omschrijving")
            close_date = self._parse_dt(
                _first_value(
                    item,
                    "sluitingsDatum",
                    "sluitingsDatumMarktconsultatie",
                    "sluitingsdatum",
                )
            )
            detail_href = _nested_value(item.get("link"), "href") or ""
            detail_url = urljoin("https://www.tenderned.nl", detail_href) if detail_href else str(raw_document.canonical_url)
            summary = _first_value(item, "opdrachtBeschrijving", "omschrijving", "aanbestedingNaam")
            tags = [
                "tenderned",
                normalize_csv_tag(type_publication),
                normalize_csv_tag(procedure),
            ]
            evidence.append(
                ExtractedEvidence(
                    title=_text(item.get("aanbestedingNaam")) or f"TenderNed notice {item.get('publicatieId')}",
                    summary=_text(summary) or None,
                    buyer_name=_text(item.get("opdrachtgeverNaam")) or None,
                    buyer_country="NL",
                    notice_type=type_publication or status,
                    procurement_type=procedure or type_publication or status,
                    publication_date=published_at,
                    close_date=close_date,
                    source_url=detail_url,
                    response_url=detail_url,
                    tags=[tag for tag in tags if tag and tag != "status_unknown"],
                    procurement_id=str(item.get("publicatieId") or ""),
                    raw_excerpt=_text(summary)[:2000] or None,
                    acquisition_method=getattr(source.acquisition_method, "value", None),
                    source_provenance={"upstream": source.name, "raw_document": raw_document.canonical_url},
                    discovery_query_id=metadata.get("query_id"),
                    discovery_query_text=metadata.get("query_text"),
                    query_family=metadata.get("query_family"),
                    extracted_data=item,
                )
            )
        return evidence


class GetsTenderSource(BaseSourceAdapter):
    source_name = "gets_tenders"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.query_compiler = QueryCompiler()

    def fetch(self, source, since: datetime, cursor: str | None = None, query: Any | None = None, budget: Any | None = None) -> FetchBatch:
        del cursor
        rendered = query or self.query_compiler.render_for_source(source, self.query_compiler.primary_query(source))
        config = source.config_json or {}
        search_endpoint = config.get("search_endpoint") or "https://www.gets.govt.nz/ExternalTenderSearching.htm"
        search_text = _portal_search_text(rendered)
        response = self.client.get(search_endpoint, params={"SearchingText": search_text, "submit": "Search"})
        response.raise_for_status()
        html = response.text
        detail_urls: list[str] = []
        for href in re.findall(r"ExternalTenderDetails\.htm\?id=\d+", html):
            url = urljoin(str(response.url), href)
            if url not in detail_urls:
                detail_urls.append(url)
        detail_limit = min(
            int(config.get("detail_limit", 12)),
            int(getattr(budget, "max_detail_pages", config.get("detail_limit", 12)) or config.get("detail_limit", 12)),
        )
        documents = [
            self._html_document(
                url=str(response.url),
                payload=response.content,
                metadata={
                    "query_id": rendered.query_id,
                    "query_text": rendered.rendered_query_text,
                    "abstract_query_text": rendered.abstract_query_text,
                    "query_family": rendered.query_family,
                    "phase": rendered.phase,
                    "target_field": rendered.target_field,
                    "renderer": rendered.renderer,
                    "since": since.isoformat(),
                    "stage": "list",
                    "detail_urls": detail_urls[:detail_limit],
                },
            )
        ]
        for index, detail_url in enumerate(detail_urls[:detail_limit]):
            detail_response = self.client.get(detail_url)
            detail_response.raise_for_status()
            documents.append(
                self._html_document(
                    url=str(detail_response.url),
                    payload=detail_response.content,
                    metadata={
                        "query_id": rendered.query_id,
                        "query_text": rendered.rendered_query_text,
                        "abstract_query_text": rendered.abstract_query_text,
                        "query_family": rendered.query_family,
                        "phase": rendered.phase,
                        "target_field": rendered.target_field,
                        "renderer": rendered.renderer,
                        "since": since.isoformat(),
                        "stage": "detail",
                        "detail_index": index,
                    },
                )
            )
        return FetchBatch(documents=documents, next_cursor=None)

    def extract(self, source, raw_document, payload: bytes) -> list[ExtractedEvidence]:
        metadata = getattr(raw_document, "metadata_json", {}) or {}
        if metadata.get("stage") != "detail":
            return []
        since = self._parse_dt(metadata.get("since"))
        labels = _gets_label_map(payload)
        open_date = self._parse_dt(labels.get("Open Date"))
        close_date = self._parse_dt(labels.get("Close Date"))
        if since and open_date and open_date < since:
            return []
        detail_id = _gets_detail_id(str(raw_document.canonical_url)) or labels.get("RFx ID")
        title = labels.get("Tender Name") or f"GETS tender {detail_id or 'unknown'}"
        buyer_name = None
        soup = BeautifulSoup(payload, "html.parser")
        page_title = _text(soup.title.get_text(" ", strip=True) if soup.title else "")
        if " | " in page_title and " - " in page_title:
            _, rhs = page_title.split(" | ", 1)
            buyer_name = rhs.split(" - ", 1)[0]
        summary = _gets_summary(payload)
        contact = labels.get("Contact")
        contact_name = None
        contact_phone = None
        if contact:
            tokens = contact.rsplit(" ", 1)
            contact_name = tokens[0]
            if len(tokens) > 1 and re.search(r"\d", tokens[1]):
                contact_phone = tokens[1]
        categories = labels.get("Categories")
        classification_codes = [categories] if categories else []
        return [
            ExtractedEvidence(
                title=title,
                summary=summary,
                buyer_name=buyer_name,
                buyer_country="NZ",
                buyer_region=labels.get("Regions"),
                notice_type=labels.get("Tender Type"),
                procurement_type=labels.get("Tender Type"),
                publication_date=open_date,
                close_date=close_date,
                source_url=str(raw_document.canonical_url),
                response_url=str(raw_document.canonical_url),
                contact_name=contact_name,
                contact_phone=contact_phone,
                classification_codes=classification_codes,
                tags=[
                    "gets_tenders",
                    normalize_csv_tag(labels.get("Tender Type")),
                    normalize_csv_tag(labels.get("Regions")),
                ],
                procurement_id=detail_id,
                raw_excerpt=(summary or title)[:2000],
                acquisition_method=getattr(source.acquisition_method, "value", None),
                source_provenance={"upstream": source.name, "raw_document": raw_document.canonical_url},
                discovery_query_id=metadata.get("query_id"),
                discovery_query_text=metadata.get("query_text"),
                query_family=metadata.get("query_family"),
                extracted_data=labels,
            )
        ]
