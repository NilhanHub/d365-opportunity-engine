from __future__ import annotations

import json
from types import SimpleNamespace

from d365opps.sources.global_sources import (
    GebizSource,
    OcdsRegistrySource,
    SouthAfricaAwardedTendersSource,
    SouthAfricaETendersSource,
    SouthAfricaProcurementPlansSource,
)
from d365opps.sources.contracts_finder import ContractsFinderSource
from d365opps.sources.public_portals import _portal_search_text
from d365opps.sources.ted import TedSource


def test_contracts_finder_extracts_ocds_release() -> None:
    adapter = ContractsFinderSource()
    payload = {
        "releases": [
            {
                "ocid": "ocds-1",
                "id": "release-1",
                "date": "2026-04-10T12:00:00Z",
                "tag": ["tender"],
                "tender": {
                    "id": "tender-1",
                    "title": "Dynamics 365 CRM implementation",
                    "description": "Implementation of Dynamics 365 Sales.",
                    "procurementMethod": "open",
                    "procurementMethodDetails": "Open procedure",
                    "value": {"amount": 150000, "currency": "GBP"},
                    "tenderPeriod": {"endDate": "2026-04-20T12:00:00Z"},
                    "classification": {"id": "72000000"},
                },
                "buyer": {"id": "buyer-1", "name": "City Council"},
                "parties": [
                    {
                        "id": "buyer-1",
                        "name": "City Council",
                        "address": {"countryName": "GB"},
                        "contactPoint": {"name": "Sam Taylor", "email": "sam@example.gov.uk"},
                    }
                ],
            }
        ]
    }
    source = SimpleNamespace(country="GB")
    raw_document = SimpleNamespace(canonical_url="https://example.gov.uk/contracts/1")

    evidence = adapter.extract(source, raw_document, json.dumps(payload).encode("utf-8"))

    assert len(evidence) == 1
    assert evidence[0].buyer_name == "City Council"
    assert evidence[0].contact_email == "sam@example.gov.uk"
    assert evidence[0].budget_currency == "GBP"


def test_ted_extracts_notice() -> None:
    adapter = TedSource()
    payload = {
        "notices": [
            {
                "publication-number": "12345-2026",
                "buyer-name": {"hun": ["Regionális egészségügyi hatóság"], "eng": ["Regional Health Authority"]},
                "publication-date": "2026-04-09+01:00",
                "notice-title": {
                    "hun": ["Dynamics 365 Business Central támogatási szolgáltatások"],
                    "eng": ["Dynamics 365 Business Central support services"],
                },
                "links": {
                    "xml": {"MUL": "https://ted.europa.eu/en/notice/12345-2026/xml"},
                    "pdf": {"ENG": "https://ted.europa.eu/en/notice/12345-2026/pdf"},
                },
            }
        ]
    }
    source = SimpleNamespace(country="GB")
    raw_document = SimpleNamespace(canonical_url="https://api.ted.europa.eu/v3/notices/search")

    evidence = adapter.extract(source, raw_document, json.dumps(payload).encode("utf-8"))

    assert len(evidence) == 1
    assert evidence[0].procurement_id == "12345-2026"
    assert evidence[0].buyer_name == "Regional Health Authority"
    assert evidence[0].title == "Dynamics 365 Business Central support services"
    assert "ted" in evidence[0].tags


def test_portal_search_text_can_select_single_safe_term() -> None:
    rendered = SimpleNamespace(
        abstract_query_text='"Dynamics 365" "Microsoft Power Platform" "Business Central"',
        rendered_query_text='"Dynamics 365" "Microsoft Power Platform" "Business Central"',
        required_anchors=["Dynamics 365", "Power Platform", "Business Central"],
        metadata={},
        query_id="abc123",
    )

    search_text = _portal_search_text(rendered, quote_multiword=False, single_term=True)

    assert search_text in {"Dynamics 365", "Microsoft Power Platform", "Business Central"}


def test_ocds_registry_extracts_registry_entries() -> None:
    adapter = OcdsRegistrySource()
    html = """
    <html><body>
      <article>
        <h2><a href="https://data.example.org/publisher">Finland: Public Procurement Portal</a></h2>
        <p>Monthly OCDS export for procurement data and awards.</p>
      </article>
    </body></html>
    """
    source = SimpleNamespace(country=None, acquisition_method=SimpleNamespace(value="dataset"), name="ocds_registry")
    raw_document = SimpleNamespace(canonical_url="https://data.open-contracting.org/en/search/", metadata_json={})

    evidence = adapter.extract(source, raw_document, html.encode("utf-8"))

    assert len(evidence) == 1
    assert evidence[0].record_type == "source_registry_entry"
    assert evidence[0].procurement_id == "publisher"
    assert evidence[0].buyer_country == "Finland"


def test_gebiz_extracts_current_opportunity_rows() -> None:
    adapter = GebizSource()
    html = """
    <html><body>
      <div class="formRow_MAIN">
        <span><a href="/ptn/opportunity/directlink.xhtml?docCode=ABC123">Microsoft Dynamics 365 support services</a></span>
      </div>
      <div class="formOutputText_MAIN form2_ROW-SEPARATOR">Agency National Environment Agency</div>
      <div class="formOutputText_MAIN form2_ROW-SEPARATOR">Published 15 Apr 2026 05:50 PM</div>
      <div class="formOutputText_MAIN">Procurement Category IT Software =&gt; Business Systems</div>
    </body></html>
    """
    source = SimpleNamespace(country="SG", acquisition_method=SimpleNamespace(value="html"), name="gebiz_opportunities")
    raw_document = SimpleNamespace(canonical_url="https://www.gebiz.gov.sg/ptn/opportunity/BOListing.xhtml?origin=menu", metadata_json={})

    evidence = adapter.extract(source, raw_document, html.encode("utf-8"))

    assert len(evidence) == 1
    assert evidence[0].procurement_id == "ABC123"
    assert evidence[0].buyer_name == "National Environment Agency"
    assert evidence[0].buyer_country == "SG"


def test_south_africa_etenders_extracts_current_tenders() -> None:
    adapter = SouthAfricaETendersSource()
    payload = {
        "recordsTotal": 1,
        "recordsFiltered": 1,
        "data": [
            {
                "id": 153587,
                "tender_No": "RFQ/IT/2026/10251660",
                "description": "Microsoft Dynamics 365 support and maintenance services",
                "category": "Information Technology Services",
                "type": "Request for Quotation",
                "organ_of_State": "ESKOM",
                "department": "ESKOM",
                "status": "Published",
                "closing_Date": "2026-05-06T11:00:00",
                "date_Published": "2026-04-15T00:00:00",
                "province": "Mpumalanga",
                "contactPerson": "mulisa khomunala",
                "email": "contact@example.gov.za",
                "telephone": "013-680-3266",
            }
        ],
    }
    source = SimpleNamespace(country="ZA", acquisition_method=SimpleNamespace(value="api"), name="south_africa_etenders")
    raw_document = SimpleNamespace(canonical_url="https://www.etenders.gov.za/Home/PaginatedTenderOpportunities", metadata_json={})

    evidence = adapter.extract(source, raw_document, json.dumps(payload).encode("utf-8"))

    assert len(evidence) == 1
    assert evidence[0].procurement_id == "RFQ/IT/2026/10251660"
    assert evidence[0].buyer_name == "ESKOM"
    assert evidence[0].buyer_country == "ZA"


def test_south_africa_procurement_plans_extracts_rows() -> None:
    adapter = SouthAfricaProcurementPlansSource()
    html = """
    <table>
      <tr>
        <th>Department</th><th>Description</th><th>Envisaged advert date</th><th>Envisaged closing date</th><th>Envisaged award date</th>
      </tr>
      <tr>
        <td>National Treasury</td>
        <td>Microsoft Dynamics 365 implementation services</td>
        <td>2026/04/15 00:00:00</td>
        <td>2026/05/18 00:00:00</td>
        <td>2026/06/26 00:00:00</td>
      </tr>
    </table>
    """
    source = SimpleNamespace(country="ZA", acquisition_method=SimpleNamespace(value="html"), name="south_africa_procurement_plans")
    raw_document = SimpleNamespace(canonical_url="https://www.etenders.gov.za/Home/ProcurementPlans", metadata_json={})

    evidence = adapter.extract(source, raw_document, html.encode("utf-8"))

    assert len(evidence) == 1
    assert evidence[0].buyer_name == "National Treasury"
    assert evidence[0].notice_type == "Procurement plan"


def test_south_africa_awarded_tenders_extracts_rows() -> None:
    adapter = SouthAfricaAwardedTendersSource()
    html = """
    <table>
      <tr>
        <th>Category</th><th>Description</th><th>Tender No</th><th>Province</th><th>Organ_of_State</th><th>Closing_Date</th>
      </tr>
      <tr>
        <td>Information Technology</td>
        <td>Business Central development and support</td>
        <td>ZA-BC-2026-01</td>
        <td>8</td>
        <td>Department of Finance</td>
        <td>2026/05/20 10:00:00</td>
      </tr>
    </table>
    """
    source = SimpleNamespace(country="ZA", acquisition_method=SimpleNamespace(value="html"), name="south_africa_awarded_tenders")
    raw_document = SimpleNamespace(canonical_url="https://www.etenders.gov.za/Home/AwardedTenders", metadata_json={})

    evidence = adapter.extract(source, raw_document, html.encode("utf-8"))

    assert len(evidence) == 1
    assert evidence[0].procurement_id == "ZA-BC-2026-01"
    assert evidence[0].buyer_name == "Department of Finance"
