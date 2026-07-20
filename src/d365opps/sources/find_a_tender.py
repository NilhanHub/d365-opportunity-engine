from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from d365opps.schemas import FetchBatch
from d365opps.sources.global_sources import ListingPortalSource
from d365opps.sources.public_portals import _portal_search_text


class FindATenderSource(ListingPortalSource):
    source_name = "find_a_tender"

    def fetch(self, source, since: datetime, cursor: str | None = None, query: Any | None = None, budget: Any | None = None) -> FetchBatch:
        del since
        query = query or self.query_compiler.render_for_source(source, self.query_compiler.primary_query(source))
        base_url = source.endpoint.replace("/Find/Notice/Results", "/Search")
        url = urljoin(base_url, cursor) if cursor and not str(cursor).startswith("http") else (cursor or base_url)
        params = {}
        if not cursor and query and query.remote_supported and not query.browse_only:
            params["keywords"] = _portal_search_text(
                query,
                fallback="Microsoft Dynamics",
                quote_multiword=False,
                single_term=True,
            )
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
        detail_limit = int(getattr(budget, "max_detail_pages", source.config_json.get("max_detail_pages", 20)) or 0)
        base_host = urlparse(str(response.url)).netloc
        detail_urls = []
        for detail_url in self._detail_urls(soup, str(response.url), source, limit=max(detail_limit * 3, detail_limit)):
            parsed = urlparse(detail_url)
            if parsed.netloc != base_host:
                continue
            if "/Notice/" not in parsed.path:
                continue
            detail_urls.append(detail_url)
            if len(detail_urls) >= detail_limit:
                break
        for detail_url in detail_urls:
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
