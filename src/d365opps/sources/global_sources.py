from __future__ import annotations

import json
import re
from datetime import datetime
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup

from d365opps.retrieval import QueryCompiler
from d365opps.schemas import ExtractedEvidence, FetchBatch
from d365opps.sources.base import BaseSourceAdapter
from d365opps.sources.public_portals import _portal_search_text


DATE_RE = re.compile(r"\b(?:20\d{2}[-/]\d{2}[-/]\d{2}|\d{1,2}\s+[A-Za-z]{3,9}\s+20\d{2})\b")
CURRENCY_RE = re.compile(r"(?P<currency>USD|EUR|GBP|AUD|NZD|CAD|SGD|KES|JMD|INR|PHP|\$|£|€)\s?(?P<amount>[0-9][0-9,]*(?:\.[0-9]{2})?)", re.IGNORECASE)
QUOTED_TERM_RE = re.compile(r'"([^"]+)"')


def _text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


def _normalize_tag(value: str | None) -> str:
    if not value:
        return "status_unknown"
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _absolute_url(base_url: str, href: str | None) -> str | None:
    if not href:
        return None
    return urljoin(base_url, href)


def _query_terms(query: Any | None) -> list[str]:
    texts = [getattr(query, "abstract_query_text", None), getattr(query, "rendered_query_text", None)]
    terms: list[str] = []
    for text in texts:
        for term in QUOTED_TERM_RE.findall(str(text or "")):
            cleaned = _text(term)
            if cleaned and cleaned not in terms:
                terms.append(cleaned)
    if terms:
        return terms[:4]
    anchors = [_text(term) for term in getattr(query, "required_anchors", []) if _text(term)]
    return anchors[:4]


def _source_metadata(raw_document) -> dict[str, Any]:
    return getattr(raw_document, "metadata_json", {}) or {}


def _row_text(node: BeautifulSoup | Any) -> str:
    return _text(node.get_text(" ", strip=True) if node else "")


def _gebiz_doc_code(href: str | None) -> str | None:
    if not href:
        return None
    return parse_qs(urlparse(href).query).get("docCode", [None])[0]


def _south_africa_dt_params(*, page: int, page_size: int, status: int, search_text: str) -> dict[str, str]:
    return {
        "draw": str(page + 1),
        "columns[0][data]": "icon",
        "columns[0][name]": "",
        "columns[0][searchable]": "true",
        "columns[0][orderable]": "false",
        "columns[0][search][value]": "",
        "columns[0][search][regex]": "false",
        "columns[1][data]": "description",
        "columns[1][name]": "",
        "columns[1][searchable]": "true",
        "columns[1][orderable]": "true",
        "columns[1][search][value]": "",
        "columns[1][search][regex]": "false",
        "columns[2][data]": "advertisedDate",
        "columns[2][name]": "",
        "columns[2][searchable]": "true",
        "columns[2][orderable]": "false",
        "columns[2][search][value]": "",
        "columns[2][search][regex]": "false",
        "columns[3][data]": "closingDate",
        "columns[3][name]": "",
        "columns[3][searchable]": "true",
        "columns[3][orderable]": "true",
        "columns[3][search][value]": "",
        "columns[3][search][regex]": "false",
        "order[0][column]": "2",
        "order[0][dir]": "desc",
        "start": str(page * page_size),
        "length": str(page_size),
        "search[value]": search_text,
        "search[regex]": "false",
        "status": str(status),
    }


class ListingPortalSource(BaseSourceAdapter):
    source_name = "listing_portal"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.query_compiler = QueryCompiler()

    def fetch(self, source, since: datetime, cursor: str | None = None, query: Any | None = None, budget: Any | None = None) -> FetchBatch:
        del since
        url = cursor or source.endpoint
        params = {}
        if query and getattr(query, "remote_supported", False):
            search_param = source.config_json.get("search_param")
            if search_param:
                params[search_param] = query.rendered_query_text
        response = self.client.get(url, params=params or None)
        response.raise_for_status()
        query_metadata = self._query_metadata(query)
        listing_document = self._html_document(
            url=str(response.url),
            payload=response.content,
            metadata={**query_metadata, "stage": "listing"},
        )
        documents = [listing_document]
        soup = BeautifulSoup(response.content, "html.parser")
        detail_limit = int(getattr(budget, "max_detail_pages", source.config_json.get("max_detail_pages", 15)) or 0)
        for detail_url in self._detail_urls(soup, str(response.url), source, limit=detail_limit):
            detail_response = self.client.get(detail_url)
            detail_response.raise_for_status()
            documents.append(
                self._html_document(
                    url=str(detail_response.url),
                    payload=detail_response.content,
                    metadata={**query_metadata, "stage": "detail", "listing_url": str(response.url)},
                )
            )
        next_cursor = self._next_page_url(soup, str(response.url))
        return FetchBatch(documents=documents, next_cursor=next_cursor)

    def extract(self, source, raw_document, payload: bytes) -> list[ExtractedEvidence]:
        soup = BeautifulSoup(payload, "html.parser")
        stage = (raw_document.metadata_json or {}).get("stage", "listing")
        if stage == "detail":
            detail = self._extract_detail_notice(source, raw_document, soup)
            return [detail] if detail else []
        return self._extract_listing_cards(source, raw_document, soup)

    def _extract_listing_cards(self, source, raw_document, soup: BeautifulSoup) -> list[ExtractedEvidence]:
        card_selector = source.config_json.get("item_selector") or "article, li, tr, .listing, .opportunity"
        cards = soup.select(card_selector)
        if not cards:
            cards = [soup]
        evidence: list[ExtractedEvidence] = []
        for card in cards[:40]:
            text = card.get_text(" ", strip=True)
            if len(text) < 20:
                continue
            anchor = card.find("a", href=True)
            title_node = card.find(["h1", "h2", "h3"]) or anchor or soup.find("title")
            title = title_node.get_text(" ", strip=True) if title_node else raw_document.canonical_url
            href = urljoin(raw_document.canonical_url, anchor["href"]) if anchor else raw_document.canonical_url
            summary_node = card.find("p") or card.find("div")
            summary = summary_node.get_text(" ", strip=True)[:1200] if summary_node else None
            dates = [self._parse_dt(item) for item in DATE_RE.findall(text)]
            dates = [item for item in dates if item is not None]
            publication_date = dates[0] if dates else None
            close_date = dates[1] if len(dates) > 1 else publication_date
            evidence.append(
                ExtractedEvidence(
                    title=title,
                    summary=summary,
                    buyer_country=source.country,
                    procurement_type=f"{source.name} listing",
                    publication_date=publication_date,
                    close_date=close_date,
                    source_url=href,
                    response_url=href,
                    tags=[source.name],
                    raw_excerpt=text[:1500],
                    acquisition_method=source.acquisition_method.value,
                    source_provenance={"upstream": source.name, "stage": "listing"},
                    discovery_query_id=raw_document.metadata_json.get("query_id"),
                    discovery_query_text=raw_document.metadata_json.get("query_text"),
                    query_family=raw_document.metadata_json.get("query_family"),
                    extracted_data={"html_source": raw_document.canonical_url},
                )
            )
        return evidence

    def _extract_detail_notice(self, source, raw_document, soup: BeautifulSoup) -> ExtractedEvidence | None:
        page_text = soup.get_text(" ", strip=True)
        if len(page_text) < 40:
            return None
        title_node = soup.find("h1") or soup.find("h2") or soup.find("title")
        title = title_node.get_text(" ", strip=True) if title_node else raw_document.canonical_url
        summary = None
        meta_description = soup.find("meta", attrs={"name": "description"})
        if meta_description and meta_description.get("content"):
            summary = str(meta_description["content"]).strip()
        elif soup.find("p"):
            summary = " ".join(node.get_text(" ", strip=True) for node in soup.find_all("p")[:3])[:1800]
        publication_date = self._labeled_date(page_text, ("publication date", "published", "posted", "issue date"))
        close_date = self._labeled_date(page_text, ("closing date", "deadline", "closing", "response date", "submission date"))
        if close_date is None:
            dates = [self._parse_dt(item) for item in DATE_RE.findall(page_text)]
            dates = [item for item in dates if item is not None]
            if dates:
                publication_date = publication_date or dates[0]
                close_date = dates[-1]
        buyer_name = self._labeled_value(page_text, ("buyer", "contracting authority", "organisation", "organization", "agency", "entity"))
        buyer_country = self._labeled_value(page_text, ("country", "location")) or source.country
        budget_value, budget_currency = self._budget_value(page_text)
        procurement_id = self._labeled_value(page_text, ("notice id", "procurement id", "reference", "tender id", "notice number"))
        attachment_urls = []
        attachment_metadata = []
        for anchor in soup.find_all("a", href=True):
            href = urljoin(raw_document.canonical_url, anchor["href"])
            lower = href.lower()
            if lower.endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx")):
                attachment_urls.append(href)
                attachment_metadata.append({"url": href, "title": anchor.get_text(" ", strip=True) or "attachment"})
        alternate_links = {
            link.get("hreflang", "").lower(): urljoin(raw_document.canonical_url, link["href"])
            for link in soup.find_all("link", attrs={"rel": "alternate", "href": True})
        }
        return ExtractedEvidence(
            title=title,
            summary=summary,
            buyer_name=buyer_name,
            buyer_country=buyer_country,
            procurement_type=f"{source.name} detail page",
            publication_date=publication_date,
            close_date=close_date,
            budget_value=budget_value,
            budget_currency=budget_currency,
            source_url=raw_document.canonical_url,
            response_url=raw_document.canonical_url,
            attachment_urls=attachment_urls,
            attachment_metadata=attachment_metadata,
            procurement_id=procurement_id,
            tags=[source.name, "detail_page"],
            raw_excerpt=page_text[:2000],
            acquisition_method=source.acquisition_method.value,
            source_provenance={
                "upstream": source.name,
                "stage": "detail",
                "listing_url": raw_document.metadata_json.get("listing_url"),
            },
            discovery_query_id=raw_document.metadata_json.get("query_id"),
            discovery_query_text=raw_document.metadata_json.get("query_text"),
            query_family=raw_document.metadata_json.get("query_family"),
            extracted_data={
                "html_source": raw_document.canonical_url,
                "alternate_links": alternate_links,
                "stage": "detail",
            },
        )

    def _detail_urls(self, soup: BeautifulSoup, base_url: str, source, *, limit: int) -> list[str]:
        if limit <= 0:
            return []
        selector = source.config_json.get("detail_link_selector")
        anchors = soup.select(selector) if selector else []
        if not anchors:
            card_selector = source.config_json.get("item_selector") or "article, li, tr, .listing, .opportunity"
            for card in soup.select(card_selector):
                anchor = card.find("a", href=True)
                if anchor:
                    anchors.append(anchor)
        urls: list[str] = []
        seen: set[str] = set()
        for anchor in anchors:
            href = anchor.get("href")
            if not href:
                continue
            absolute = urljoin(base_url, href)
            if absolute in seen:
                continue
            seen.add(absolute)
            urls.append(absolute)
            if len(urls) >= limit:
                break
        return urls

    def _next_page_url(self, soup: BeautifulSoup, base_url: str) -> str | None:
        selectors = [
            'a[rel="next"]',
            'link[rel="next"]',
            'a[aria-label*="next" i]',
            'a[title*="next" i]',
        ]
        for selector in selectors:
            node = soup.select_one(selector)
            href = node.get("href") if node else None
            if href:
                return urljoin(base_url, href)
        for anchor in soup.find_all("a", href=True):
            if "next" in anchor.get_text(" ", strip=True).lower():
                return urljoin(base_url, anchor["href"])
        return None

    def _query_metadata(self, query: Any | None) -> dict[str, Any]:
        if not query:
            return {}
        return {
            "query_id": getattr(query, "query_id", None),
            "query_text": getattr(query, "rendered_query_text", None),
            "abstract_query_text": getattr(query, "abstract_query_text", None),
            "query_family": getattr(query, "query_family", None),
            "phase": getattr(query, "phase", None),
            "target_field": getattr(query, "target_field", None),
            "renderer": getattr(query, "renderer", None),
        }

    def _labeled_value(self, text: str, labels: tuple[str, ...]) -> str | None:
        for label in labels:
            match = re.search(rf"{re.escape(label)}\s*[:\-]\s*(?P<value>[^|.;]{{3,140}})", text, re.IGNORECASE)
            if match:
                return match.group("value").strip()
        return None

    def _labeled_date(self, text: str, labels: tuple[str, ...]) -> datetime | None:
        for label in labels:
            match = re.search(
                rf"{re.escape(label)}\s*[:\-]?\s*(?P<value>(?:20\d{{2}}[-/]\d{{2}}[-/]\d{{2}}|\d{{1,2}}\s+[A-Za-z]{{3,9}}\s+20\d{{2}}))",
                text,
                re.IGNORECASE,
            )
            if match:
                return self._parse_dt(match.group("value"))
        return None

    def _budget_value(self, text: str) -> tuple[Decimal | None, str | None]:
        match = CURRENCY_RE.search(text)
        if not match:
            return None, None
        amount = Decimal(match.group("amount").replace(",", ""))
        currency = match.group("currency").upper()
        currency = {"$": "USD", "£": "GBP", "€": "EUR"}.get(currency, currency)
        return amount, currency


class OcdsRegistrySource(ListingPortalSource):
    source_name = "ocds_registry"

    def fetch(self, source, since: datetime, cursor: str | None = None, query: Any | None = None, budget: Any | None = None) -> FetchBatch:
        del budget
        query = query or self.query_compiler.render_for_source(source, self.query_compiler.primary_query(source))
        url = cursor or (source.config_json or {}).get("search_endpoint") or source.endpoint
        response = self.client.get(url)
        response.raise_for_status()
        document = self._html_document(
            url=str(response.url),
            payload=response.content,
            metadata={**self._query_metadata(query), "stage": "registry_search", "since": since.isoformat()},
        )
        next_cursor = self._next_page_url(BeautifulSoup(response.content, "html.parser"), str(response.url))
        return FetchBatch(documents=[document], next_cursor=next_cursor)

    def extract(self, source, raw_document, payload: bytes) -> list[ExtractedEvidence]:
        soup = BeautifulSoup(payload, "html.parser")
        metadata = _source_metadata(raw_document)
        evidence: list[ExtractedEvidence] = []
        for article in soup.find_all("article")[:100]:
            anchor = article.find("a", href=True)
            title_node = article.find(["h2", "h3"]) or anchor
            title = _row_text(title_node)
            href = _absolute_url(str(raw_document.canonical_url), anchor["href"] if anchor else None)
            if not title or not href:
                continue
            summary = _row_text(article)
            buyer_country = title.split(":", 1)[0].strip() if ":" in title else None
            procurement_id = urlparse(href).path.rstrip("/").split("/")[-1] or title
            evidence.append(
                ExtractedEvidence(
                    record_type="source_registry_entry",
                    title=title,
                    summary=summary[:1800] or None,
                    buyer_name=title.split(":", 1)[-1].strip() if ":" in title else None,
                    buyer_country=buyer_country,
                    notice_type="OCP registry publisher",
                    procurement_type="OCP registry publisher",
                    source_url=href,
                    response_url=href,
                    tags=["ocds_registry", "source_discovery"],
                    procurement_id=procurement_id,
                    raw_excerpt=summary[:2000] or None,
                    acquisition_method=source.acquisition_method.value,
                    source_provenance={"upstream": source.name, "raw_document": raw_document.canonical_url},
                    discovery_query_id=metadata.get("query_id"),
                    discovery_query_text=metadata.get("query_text"),
                    query_family=metadata.get("query_family"),
                    extracted_data={"stage": metadata.get("stage"), "source_url": href},
                )
            )
        return evidence


class OpenTenderSource(ListingPortalSource):
    source_name = "opentender_search"


class CanadaBuysSource(ListingPortalSource):
    source_name = "canada_buys_tenders"


class CanadaBuysLegacySource(ListingPortalSource):
    source_name = "canada_buys"


class CanadaBuysAwardsSource(ListingPortalSource):
    source_name = "canada_buys_awards"


class CanadaBuysContractHistorySource(ListingPortalSource):
    source_name = "canada_buys_contract_history"


class CanadaBuysStandingOffersSource(ListingPortalSource):
    source_name = "canada_buys_standing_offers"


class AusTenderSource(ListingPortalSource):
    source_name = "austender_atm"


class AusTenderLegacySource(ListingPortalSource):
    source_name = "austender"


class AusTenderContractsSource(ListingPortalSource):
    source_name = "austender_contract_notices"


class GetsSource(ListingPortalSource):
    source_name = "gets_tenders"


class GetsLegacySource(ListingPortalSource):
    source_name = "gets"


class GetsAwardsSource(ListingPortalSource):
    source_name = "gets_awards"


class UngmSource(ListingPortalSource):
    source_name = "ungm_public_notices"


class UngmLegacySource(ListingPortalSource):
    source_name = "ungm"


class WorldBankSource(ListingPortalSource):
    source_name = "world_bank_current"


class WorldBankLegacySource(ListingPortalSource):
    source_name = "world_bank"


class WorldBankUpcomingSource(ListingPortalSource):
    source_name = "world_bank_upcoming"


class WorldBankPotentialSource(ListingPortalSource):
    source_name = "world_bank_potential"


class GebizSource(ListingPortalSource):
    source_name = "gebiz_opportunities"

    def fetch(self, source, since: datetime, cursor: str | None = None, query: Any | None = None, budget: Any | None = None) -> FetchBatch:
        del budget
        query = query or self.query_compiler.render_for_source(source, self.query_compiler.primary_query(source))
        response = self.client.get(cursor or source.endpoint)
        response.raise_for_status()
        document = self._html_document(
            url=str(response.url),
            payload=response.content,
            metadata={**self._query_metadata(query), "stage": "listing", "since": since.isoformat()},
        )
        return FetchBatch(documents=[document], next_cursor=None)

    def extract(self, source, raw_document, payload: bytes) -> list[ExtractedEvidence]:
        soup = BeautifulSoup(payload, "html.parser")
        metadata = _source_metadata(raw_document)
        since = self._parse_dt(metadata.get("since"))
        evidence: list[ExtractedEvidence] = []
        for link in soup.find_all("a", href=True):
            href = link.get("href")
            if not href or "directlink.xhtml?docCode=" not in href:
                continue
            title = _row_text(link)
            if not title:
                continue
            main = link.find_parent("div", class_="formRow_MAIN")
            if main is None:
                continue
            agency_text = ""
            published_text = ""
            category_text = ""
            sibling = main
            for _ in range(4):
                sibling = sibling.find_next_sibling()
                if sibling is None:
                    break
                safe_text = _row_text(sibling)
                if safe_text.startswith("Agency "):
                    agency_text = safe_text.removeprefix("Agency ").strip()
                elif safe_text.startswith("Published "):
                    published_text = safe_text.removeprefix("Published ").strip()
                elif safe_text.startswith("Procurement Category "):
                    category_text = safe_text.removeprefix("Procurement Category ").strip()
                    break
            publication_date = self._parse_dt(published_text)
            if since and publication_date and publication_date < since:
                continue
            source_url = _absolute_url(str(raw_document.canonical_url), href) or str(raw_document.canonical_url)
            procurement_id = _gebiz_doc_code(source_url) or title
            summary_parts = [part for part in (agency_text, category_text) if part]
            evidence.append(
                ExtractedEvidence(
                    title=title,
                    summary=" | ".join(summary_parts) or None,
                    buyer_name=agency_text or None,
                    buyer_country="SG",
                    notice_type="GeBIZ opportunity",
                    procurement_type=category_text or "GeBIZ opportunity",
                    publication_date=publication_date,
                    source_url=source_url,
                    response_url=source_url,
                    tags=["gebiz", _normalize_tag(category_text)],
                    procurement_id=procurement_id,
                    raw_excerpt=_text(" ".join([title, agency_text, published_text, category_text]))[:2000] or None,
                    acquisition_method=source.acquisition_method.value,
                    source_provenance={"upstream": source.name, "raw_document": raw_document.canonical_url},
                    discovery_query_id=metadata.get("query_id"),
                    discovery_query_text=metadata.get("query_text"),
                    query_family=metadata.get("query_family"),
                    extracted_data={
                        "agency": agency_text,
                        "published": published_text,
                        "procurement_category": category_text,
                    },
                )
            )
        return evidence


class GebizLegacySource(ListingPortalSource):
    source_name = "gebiz"


class GebizIndicativeSource(ListingPortalSource):
    source_name = "gebiz_indicative"


class SouthAfricaETendersSource(ListingPortalSource):
    source_name = "south_africa_etenders"

    def fetch(self, source, since: datetime, cursor: str | None = None, query: Any | None = None, budget: Any | None = None) -> FetchBatch:
        query = query or self.query_compiler.render_for_source(source, self.query_compiler.primary_query(source))
        page = int(cursor or 0)
        config = source.config_json or {}
        page_size = int(config.get("limit", 20))
        endpoint = config.get("api_endpoint") or source.endpoint
        status = int(config.get("status", 1))
        search_text = _portal_search_text(query, quote_multiword=False, single_term=True)
        response = self.client.get(
            endpoint,
            params=_south_africa_dt_params(page=page, page_size=page_size, status=status, search_text=search_text),
            headers={"X-Requested-With": "XMLHttpRequest", "Referer": config.get("referer") or "https://www.etenders.gov.za/Home/opportunities?id=1"},
        )
        response.raise_for_status()
        body = response.json()
        document = self._json_document(
            external_id=f"south-africa-etenders-{query.query_id}-{page}",
            url=str(response.url),
            payload=body,
            metadata={**self._query_metadata(query), "stage": "listing", "since": since.isoformat(), "page": page},
        )
        total = int(body.get("recordsFiltered") or body.get("recordsTotal") or 0)
        next_cursor = str(page + 1) if ((page + 1) * page_size) < total else None
        return FetchBatch(documents=[document], next_cursor=next_cursor)

    def extract(self, source, raw_document, payload: bytes) -> list[ExtractedEvidence]:
        body = json.loads(payload.decode("utf-8"))
        metadata = _source_metadata(raw_document)
        since = self._parse_dt(metadata.get("since"))
        evidence: list[ExtractedEvidence] = []
        for item in body.get("data", []) or []:
            publication_date = self._parse_dt(item.get("date_Published"))
            if since and publication_date and publication_date < since:
                continue
            close_date = self._parse_dt(item.get("closing_Date"))
            description = _text(item.get("description"))
            province = _text(item.get("province") or ((item.get("provinces") or {}).get("name")))
            buyer_name = _text(item.get("organ_of_State") or item.get("department"))
            procurement_id = _text(item.get("tender_No") or item.get("ocid") or item.get("id"))
            source_url = f"https://www.etenders.gov.za/Home/opportunities?id=1&tender={procurement_id or item.get('id')}"
            evidence.append(
                ExtractedEvidence(
                    title=description or f"South Africa tender {procurement_id or item.get('id')}",
                    summary=_text(" | ".join(part for part in (buyer_name, province, _text(item.get('category')), _text(item.get('type'))) if part)) or None,
                    buyer_name=buyer_name or None,
                    buyer_country="ZA",
                    buyer_region=province or None,
                    notice_type=_text(item.get("status") or item.get("type")) or "currently advertised tender",
                    procurement_type=_text(item.get("type") or item.get("category")) or "currently advertised tender",
                    publication_date=publication_date,
                    close_date=close_date,
                    contact_name=_text(item.get("contactPerson")) or None,
                    contact_email=_text(item.get("email")) or None,
                    contact_phone=_text(item.get("telephone")) or None,
                    source_url=source_url,
                    response_url=source_url,
                    tags=["south_africa_etenders", _normalize_tag(item.get("type")), _normalize_tag(item.get("category"))],
                    procurement_id=procurement_id or None,
                    raw_excerpt=description[:2000] or None,
                    acquisition_method=source.acquisition_method.value,
                    source_provenance={"upstream": source.name, "raw_document": raw_document.canonical_url},
                    discovery_query_id=metadata.get("query_id"),
                    discovery_query_text=metadata.get("query_text"),
                    query_family=metadata.get("query_family"),
                    extracted_data=item,
                )
            )
        return evidence


class SouthAfricaProcurementPlansSource(ListingPortalSource):
    source_name = "south_africa_procurement_plans"

    def fetch(self, source, since: datetime, cursor: str | None = None, query: Any | None = None, budget: Any | None = None) -> FetchBatch:
        del cursor, query, budget
        response = self.client.get(source.endpoint)
        response.raise_for_status()
        document = self._html_document(
            url=str(response.url),
            payload=response.content,
            metadata={"stage": "listing", "since": since.isoformat()},
        )
        return FetchBatch(documents=[document], next_cursor=None)

    def extract(self, source, raw_document, payload: bytes) -> list[ExtractedEvidence]:
        soup = BeautifulSoup(payload, "html.parser")
        metadata = _source_metadata(raw_document)
        since = self._parse_dt(metadata.get("since"))
        table = soup.find("table")
        if table is None:
            return []
        evidence: list[ExtractedEvidence] = []
        for row in table.find_all("tr")[1:]:
            cells = [_row_text(cell) for cell in row.find_all("td")]
            if len(cells) < 5:
                continue
            publication_date = self._parse_dt(cells[2])
            if since and publication_date and publication_date < since:
                continue
            evidence.append(
                ExtractedEvidence(
                    title=cells[1],
                    summary=cells[1][:1800] or None,
                    buyer_name=cells[0] or None,
                    buyer_country="ZA",
                    notice_type="Procurement plan",
                    procurement_type="Procurement plan",
                    publication_date=publication_date,
                    close_date=self._parse_dt(cells[3]),
                    source_url=str(raw_document.canonical_url),
                    response_url=str(raw_document.canonical_url),
                    tags=["south_africa_procurement_plans", "planned_procurement"],
                    raw_excerpt=_text(" | ".join(cells))[:2000] or None,
                    acquisition_method=source.acquisition_method.value,
                    source_provenance={"upstream": source.name, "raw_document": raw_document.canonical_url},
                    extracted_data={
                        "department": cells[0],
                        "description": cells[1],
                        "envisaged_advert_date": cells[2],
                        "envisaged_closing_date": cells[3],
                        "envisaged_award_date": cells[4],
                    },
                )
            )
        return evidence


class SouthAfricaAwardedTendersSource(ListingPortalSource):
    source_name = "south_africa_awarded_tenders"

    def fetch(self, source, since: datetime, cursor: str | None = None, query: Any | None = None, budget: Any | None = None) -> FetchBatch:
        del cursor, query, budget
        response = self.client.get(source.endpoint)
        response.raise_for_status()
        document = self._html_document(
            url=str(response.url),
            payload=response.content,
            metadata={"stage": "listing", "since": since.isoformat()},
        )
        return FetchBatch(documents=[document], next_cursor=None)

    def extract(self, source, raw_document, payload: bytes) -> list[ExtractedEvidence]:
        soup = BeautifulSoup(payload, "html.parser")
        metadata = _source_metadata(raw_document)
        since = self._parse_dt(metadata.get("since"))
        table = soup.find("table")
        if table is None:
            return []
        evidence: list[ExtractedEvidence] = []
        for row in table.find_all("tr")[1:]:
            cells = [_row_text(cell) for cell in row.find_all("td")]
            if len(cells) < 6:
                continue
            close_date = self._parse_dt(cells[5])
            if since and close_date and close_date < since:
                continue
            procurement_id = cells[2] or None
            evidence.append(
                ExtractedEvidence(
                    title=cells[1] or f"South Africa awarded tender {procurement_id or 'unknown'}",
                    summary=_text(" | ".join(part for part in (cells[0], cells[4]) if part)) or None,
                    buyer_name=cells[4] or None,
                    buyer_country="ZA",
                    notice_type="Awarded tender",
                    procurement_type=cells[0] or "Awarded tender",
                    close_date=close_date,
                    source_url=str(raw_document.canonical_url),
                    response_url=str(raw_document.canonical_url),
                    tags=["south_africa_awarded_tenders", "award_notice", _normalize_tag(cells[0])],
                    procurement_id=procurement_id,
                    raw_excerpt=_text(" | ".join(cells))[:2000] or None,
                    acquisition_method=source.acquisition_method.value,
                    source_provenance={"upstream": source.name, "raw_document": raw_document.canonical_url},
                    extracted_data={
                        "category": cells[0],
                        "description": cells[1],
                        "tender_no": cells[2],
                        "province_id": cells[3],
                        "organ_of_state": cells[4],
                        "closing_date": cells[5],
                    },
                )
            )
        return evidence


class EUFundingTendersSource(ListingPortalSource):
    source_name = "eu_funding_tenders"


class IrelandETendersSource(ListingPortalSource):
    source_name = "ireland_etenders"


class PhilGepsSource(ListingPortalSource):
    source_name = "philgeps"


class KenyaPPIPSource(ListingPortalSource):
    source_name = "kenya_ppip"


class JamaicaGojepSource(ListingPortalSource):
    source_name = "jamaica_gojep"


class IndiaCPPPSource(ListingPortalSource):
    source_name = "india_cppp"


class CoupaPublicSourcingSource(ListingPortalSource):
    source_name = "coupa_public_sourcing"


class SapBusinessNetworkDiscoverySource(ListingPortalSource):
    source_name = "sap_business_network_discovery"


class SearchApiDiscoverySource(BaseSourceAdapter):
    source_name = "search_api"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.query_compiler = QueryCompiler()

    def fetch(self, source, since: datetime, cursor: str | None = None, query: Any | None = None, budget: Any | None = None) -> FetchBatch:
        del since, cursor
        del budget
        query = query or self.query_compiler.render_for_source(source, self.query_compiler.primary_query(source))
        endpoint = source.endpoint
        settings = self.client.headers
        headers = {}
        if source.config_json.get("api_key_header") and source.config_json.get("api_key"):
            headers[source.config_json["api_key_header"]] = source.config_json["api_key"]
        response = self.client.get(endpoint, params={"q": query.rendered_query_text}, headers=headers)
        response.raise_for_status()
        document = self._json_document(
            external_id=f"search-api-{query.query_id}",
            url=str(response.url),
            payload=response.json(),
            metadata={
                "query_id": query.query_id,
                "query_text": query.rendered_query_text,
                "abstract_query_text": query.abstract_query_text,
                "query_family": query.query_family,
                "headers_used": bool(headers),
                "ua": settings.get("User-Agent"),
            },
        )
        return FetchBatch(documents=[document], next_cursor=None)

    def extract(self, source, raw_document, payload: bytes) -> list[ExtractedEvidence]:
        body = self._load_json(payload)
        items = body.get("results") or body.get("items") or []
        evidence: list[ExtractedEvidence] = []
        for item in items[:50]:
            link = item.get("url") or item.get("link") or raw_document.canonical_url
            evidence.append(
                ExtractedEvidence(
                    record_type="search_hit",
                    title=item.get("title") or link,
                    summary=item.get("snippet") or item.get("summary"),
                    buyer_country=source.country,
                    procurement_type="Search API discovery result",
                    publication_date=self._parse_dt(item.get("published_at") or item.get("date")),
                    source_url=link,
                    response_url=link,
                    tags=["search_api", source.name],
                    raw_excerpt=item.get("snippet") or item.get("summary"),
                    acquisition_method=source.acquisition_method.value,
                    source_provenance={"upstream": source.name},
                    discovery_query_id=raw_document.metadata_json.get("query_id"),
                    discovery_query_text=raw_document.metadata_json.get("query_text"),
                    extracted_data=item,
                )
            )
        return evidence
