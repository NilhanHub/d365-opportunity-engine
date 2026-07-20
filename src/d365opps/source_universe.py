from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from d365opps.authenticity import classify_domain, normalize_host
from d365opps.config import get_settings
from d365opps.forensics import json_default, sha256_bytes


PRODUCT_ANCHORS = (
    "dynamics 365",
    "microsoft dynamics",
    "business central",
    "power platform",
    "power apps",
    "power automate",
    "power pages",
    "dataverse",
    "copilot studio",
    "dynamics ax",
    "dynamics nav",
    "navision",
    "finance and operations",
    "f&o",
    "dynamics crm",
)
SERVICE_HINTS = (
    "implementation",
    "migration",
    "upgrade",
    "support",
    "managed service",
    "managed support",
    "consulting",
    "consultancy",
    "integration",
    "rollout",
    "deployment",
    "customization",
    "enhancement",
    "training",
    "testing",
    "assessment",
    "roadmap",
)
PROCUREMENT_HINTS = (
    "tender",
    "rfp",
    "rfq",
    "itt",
    "ifb",
    "eoi",
    "rfi",
    "procurement",
    "bid",
    "notice",
    "framework",
    "call-off",
    "supplier",
    "vendor",
    "contract",
)
PREPOSITION_HINTS = (
    "market consultation",
    "market engagement",
    "prior information",
    "pipeline notice",
    "indicative",
    "planned procurement",
    "supply arrangement",
    "standing offer",
    "framework agreement",
)
AWARD_HINTS = (
    "award notice",
    "contract award",
    "awarded",
    "award date",
    "awarded value",
    "contract details",
)
TRIGGER_HINTS = (
    "job posting",
    "careers",
    "vacancy",
    "annual plan",
    "budget",
    "strategy",
    "modernisation",
    "modernization",
    "transformation",
    "migration",
)
NEGATIVE_HINTS = (
    "sap",
    "s/4hana",
    "salesforce",
    "netsuite",
    "oracle ebs",
    "hubspot",
    "zoho",
    "crew resource management",
    "copilote",
)
POTENTIAL_PRODUCT_HINTS = (
    "crm",
    "customer relationship management",
    "erp",
    "enterprise resource planning",
    "microsoft 365",
    "sharepoint",
    "azure",
    "power bi",
    "workflow automation",
    "low-code",
    "low code",
    "case management",
    "business application",
    "business applications",
    "productivity platform",
    "customer service platform",
)
POTENTIAL_COMMERCIAL_HINTS = (
    "digital transformation",
    "applications modernisation",
    "applications modernization",
    "line-of-business system",
    "business system",
    "enterprise platform",
    "data platform",
    "integration platform",
    "back-office system",
    "front-office system",
    "business process automation",
)
ENGLISH_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "this",
    "that",
    "will",
    "service",
    "services",
    "contract",
    "notice",
    "buyer",
    "open",
    "submission",
    "market",
    "consultation",
    "support",
    "implementation",
    "supplier",
    "public",
    "procurement",
}


STATIC_SUPRANATIONAL_SURFACES: list[dict[str, Any]] = [
    {"name": "TED Search API", "country": "EU", "url": "https://api.ted.europa.eu/v3/notices/search", "family": "supranational_procurement", "kind": "api"},
    {"name": "TED Browse", "country": "EU", "url": "https://ted.europa.eu/en/search/result", "family": "supranational_procurement", "kind": "portal"},
    {"name": "EU Funding and Tenders", "country": "EU", "url": "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-search", "family": "supranational_procurement", "kind": "portal"},
    {"name": "EU Funding and Tenders Search", "country": "EU", "url": "https://funding-tenders.ec.europa.eu/search", "family": "supranational_procurement", "kind": "search"},
    {"name": "UNGM Public Notices", "country": "UN", "url": "https://www.ungm.org/Public/Notice", "family": "supranational_procurement", "kind": "portal"},
    {"name": "UNGM Contract Awards", "country": "UN", "url": "https://www.ungm.org/Public/ContractAward", "family": "supranational_procurement", "kind": "awards"},
    {"name": "World Bank Current Opportunities", "country": "INT", "url": "https://projects.worldbank.org/en/projects-operations/procurement", "family": "supranational_procurement", "kind": "portal"},
    {"name": "World Bank Procurement Notices", "country": "INT", "url": "https://www.worldbank.org/en/projects-operations/procurement/newbusiness", "family": "supranational_procurement", "kind": "portal"},
    {"name": "World Bank Upcoming Opportunities", "country": "INT", "url": "https://www.worldbank.org/en/projects-operations/products-and-services/brief/procurement-new-business-opportunities", "family": "supranational_procurement", "kind": "pipeline"},
    {"name": "ADB Procurement Notices", "country": "INT", "url": "https://www.adb.org/business-opportunities/tenders", "family": "supranational_procurement", "kind": "portal"},
    {"name": "IADB Procurement", "country": "INT", "url": "https://www.iadb.org/en/how-we-can-work-together/procurement", "family": "supranational_procurement", "kind": "portal"},
    {"name": "EBRD Procurement Notices", "country": "INT", "url": "https://www.ebrd.com/work-with-us/procurement/notices.html", "family": "supranational_procurement", "kind": "portal"},
    {"name": "AfDB Procurement", "country": "INT", "url": "https://www.afdb.org/en/projects-and-operations/procurement", "family": "supranational_procurement", "kind": "portal"},
    {"name": "UNDP Procurement Notices", "country": "UN", "url": "https://procurement-notices.undp.org/", "family": "supranational_procurement", "kind": "portal"},
    {"name": "UNICEF Supply Tenders", "country": "UN", "url": "https://www.unicef.org/supply/invitation-to-bid", "family": "supranational_procurement", "kind": "portal"},
    {"name": "UNOPS Tender Notices", "country": "UN", "url": "https://www.unops.org/business-opportunities", "family": "supranational_procurement", "kind": "portal"},
    {"name": "NATO Procurement", "country": "INT", "url": "https://www.nspa.nato.int/business/procurement", "family": "supranational_procurement", "kind": "portal"},
    {"name": "European Investment Bank Procurement", "country": "EU", "url": "https://www.eib.org/en/about/procurement", "family": "supranational_procurement", "kind": "portal"}
]


INDIA_EPROCURE_STATE_PORTALS: list[tuple[str, str]] = [
    ("CPPP Central eProcure", "https://eprocure.gov.in/eprocure/app"),
    ("CPPP Central Public Procurement", "https://eprocure.gov.in/cppp/"),
    ("Maharashtra eTendering", "https://mahatenders.gov.in/nicgep/app"),
    ("Kerala eTender", "https://etenders.kerala.gov.in/nicgep/app"),
    ("Tamil Nadu Tenders", "https://tntenders.gov.in/nicgep/app"),
    ("Assam Tenders", "https://assamtenders.gov.in/nicgep/app"),
    ("Bihar eProcurement", "https://eproc2.bihar.gov.in/EPSV2Web/"),
    ("Chhattisgarh eProcurement", "https://eproc.cgstate.gov.in/nicgep/app"),
    ("Goa eTender", "https://eproc.goa.gov.in/nicgep/app"),
    ("Haryana eProcurement", "https://etenders.hry.nic.in/nicgep/app"),
    ("Himachal Pradesh Tenders", "https://hptenders.gov.in/nicgep/app"),
    ("Jammu and Kashmir Tenders", "https://jktenders.gov.in/nicgep/app"),
    ("Jharkhand Tenders", "https://jharkhandtenders.gov.in/nicgep/app"),
    ("Karnataka Public Procurement", "https://kppp.karnataka.gov.in/"),
    ("Madhya Pradesh eTendering", "https://mptenders.gov.in/nicgep/app"),
    ("Odisha Tenders", "https://odishatenders.gov.in/nicgep/app"),
    ("Punjab eProcurement", "https://eproc.punjab.gov.in/nicgep/app"),
    ("Rajasthan eProcurement", "https://eproc.rajasthan.gov.in/nicgep/app"),
    ("Sikkim Tender", "https://sikkimtender.gov.in/nicgep/app"),
    ("Tripura Tenders", "https://tripuratenders.gov.in/nicgep/app"),
    ("Uttarakhand Tenders", "https://uktenders.gov.in/nicgep/app"),
    ("West Bengal eTender", "https://wbtenders.gov.in/nicgep/app"),
    ("Uttar Pradesh eTender", "https://etender.up.nic.in/nicgep/app"),
    ("Andaman eProcurement", "https://eproc.andaman.gov.in/nicgep/app"),
    ("Arunachal Pradesh Tenders", "https://eproc.arunachal.gov.in/nicgep/app"),
    ("Nagaland Tenders", "https://nagalandtenders.gov.in/nicgep/app"),
]


STATIC_OFFICIAL_NATIONAL_SURFACES: list[dict[str, Any]] = [
    {"name": "Find a Tender Search", "country": "GB", "url": "https://www.find-tender.service.gov.uk/Search", "kind": "search"},
    {"name": "Find a Tender Results", "country": "GB", "url": "https://www.find-tender.service.gov.uk/Search/Results", "kind": "portal"},
    {"name": "Contracts Finder Search", "country": "GB", "url": "https://www.contractsfinder.service.gov.uk/Search", "kind": "search"},
    {"name": "Contracts Finder Results", "country": "GB", "url": "https://www.contractsfinder.service.gov.uk/Search/Results", "kind": "portal"},
    {"name": "Contracts Finder OCDS Search", "country": "GB", "url": "https://www.contractsfinder.service.gov.uk/Published/Notices/OCDS/Search", "kind": "api"},
    {"name": "Ireland eTenders Home", "country": "IE", "url": "https://www.etenders.gov.ie/epps/home.do", "kind": "portal"},
    {"name": "Ireland eTenders Search", "country": "IE", "url": "https://www.etenders.gov.ie/epps/viewCFTSAction.do", "kind": "search"},
    {"name": "Ireland eTenders Open Tenders", "country": "IE", "url": "https://www.etenders.gov.ie/epps/cft/prepareViewCfTWS.do", "kind": "portal"},
    {"name": "Ireland eTenders Awards", "country": "IE", "url": "https://www.etenders.gov.ie/epps/viewAwardedCFTSAction.do", "kind": "awards"},
    {"name": "HILMA Public Notices", "country": "FI", "url": "https://www.hankintailmoitukset.fi/en/public", "kind": "portal"},
    {"name": "HILMA Procurement Notices", "country": "FI", "url": "https://www.hankintailmoitukset.fi/en/public/procurement-notices", "kind": "portal"},
    {"name": "HILMA Procurement Plans", "country": "FI", "url": "https://www.hankintailmoitukset.fi/en/public/procurement-plans", "kind": "pipeline"},
    {"name": "HILMA Search API", "country": "FI", "url": "https://www.hankintailmoitukset.fi/fi/public/api/notice-search", "kind": "api"},
    {"name": "TenderNed Home", "country": "NL", "url": "https://www.tenderned.nl", "kind": "portal"},
    {"name": "TenderNed Announcements", "country": "NL", "url": "https://www.tenderned.nl/aankondigingen/overzicht", "kind": "portal"},
    {"name": "TenderNed All Publications", "country": "NL", "url": "https://www.tenderned.nl/aankondigingen/overzicht/alle-publicaties", "kind": "portal"},
    {"name": "TenderNed About Procurement", "country": "NL", "url": "https://www.tenderned.nl/aanbesteden", "kind": "supplier"},
    {"name": "GETS Opportunities", "country": "NZ", "url": "https://www.gets.govt.nz/ExternalIndex.htm", "kind": "portal"},
    {"name": "GETS Agency Portal", "country": "NZ", "url": "https://www.gets.govt.nz", "kind": "portal"},
    {"name": "GETS Notice Search", "country": "NZ", "url": "https://www.gets.govt.nz/ExternalIndex.htm", "kind": "search"},
    {"name": "AusTender Home", "country": "AU", "url": "https://www.tenders.gov.au", "kind": "portal"},
    {"name": "AusTender Current ATM", "country": "AU", "url": "https://www.tenders.gov.au/Atm/List", "kind": "portal"},
    {"name": "AusTender Contract Notices", "country": "AU", "url": "https://www.tenders.gov.au/Cn/List", "kind": "awards"},
    {"name": "AusTender Contract Listings", "country": "AU", "url": "https://www.tenders.gov.au/Contract/List", "kind": "history"},
    {"name": "AusTender SON Listings", "country": "AU", "url": "https://www.tenders.gov.au/Son/List", "kind": "framework"},
    {"name": "CanadaBuys Tender Opportunities", "country": "CA", "url": "https://canadabuys.canada.ca/en/tender-opportunities", "kind": "portal"},
    {"name": "CanadaBuys Award Notices", "country": "CA", "url": "https://canadabuys.canada.ca/en/tender-opportunities/contract-award-notices", "kind": "awards"},
    {"name": "CanadaBuys Standing Offers", "country": "CA", "url": "https://canadabuys.canada.ca/en/tender-opportunities/standing-offers-and-supply-arrangements", "kind": "framework"},
    {"name": "CanadaBuys Contract History", "country": "CA", "url": "https://canadabuys.canada.ca/en/tender-opportunities/contract-history", "kind": "history"},
    {"name": "CanadaBuys Procurement Data", "country": "CA", "url": "https://canadabuys.canada.ca/en/tender-opportunities/data", "kind": "dataset"},
    {"name": "GeBIZ Opportunities", "country": "SG", "url": "https://www.gebiz.gov.sg/ptn/opportunity/opportunityListing.xhtml", "kind": "portal"},
    {"name": "GeBIZ Award Notices", "country": "SG", "url": "https://www.gebiz.gov.sg/ptn/award/awardNoticeList.xhtml", "kind": "awards"},
    {"name": "GeBIZ Indicative Procurement", "country": "SG", "url": "https://www.gebiz.gov.sg/ptn/indicative/indicativeList.xhtml", "kind": "pipeline"},
    {"name": "GeBIZ Supplier Guide", "country": "SG", "url": "https://www.gebiz.gov.sg/", "kind": "supplier"},
    {"name": "PhilGEPS Home", "country": "PH", "url": "https://notices.philgeps.gov.ph/", "kind": "portal"},
    {"name": "PhilGEPS Open Opportunities", "country": "PH", "url": "https://notices.philgeps.gov.ph/GEPSNONPILOT/Tender/SplashOpenOpportunities.aspx", "kind": "portal"},
    {"name": "PhilGEPS Bid Notices", "country": "PH", "url": "https://notices.philgeps.gov.ph/GEPSNONPILOT/Tender/SplashBidOpportunitiesAbstractUI.aspx", "kind": "portal"},
    {"name": "PhilGEPS Awards", "country": "PH", "url": "https://notices.philgeps.gov.ph/GEPSNONPILOT/Tender/SplashAwardNoticeAbstractUI.aspx", "kind": "awards"},
    {"name": "South Africa eTenders Home", "country": "ZA", "url": "https://www.etenders.gov.za/", "kind": "portal"},
    {"name": "South Africa Advertised Tenders", "country": "ZA", "url": "https://www.etenders.gov.za/Home/Tenders", "kind": "portal"},
    {"name": "South Africa Awarded Tenders", "country": "ZA", "url": "https://www.etenders.gov.za/Home/Awarded", "kind": "awards"},
    {"name": "South Africa Procurement Plans", "country": "ZA", "url": "https://www.etenders.gov.za/Home/Plans", "kind": "pipeline"},
    {"name": "Kenya Tenders Portal", "country": "KE", "url": "https://tenders.go.ke/", "kind": "portal"},
    {"name": "Kenya Tender Notices", "country": "KE", "url": "https://tenders.go.ke/website/tenders/index", "kind": "portal"},
    {"name": "Kenya Awards", "country": "KE", "url": "https://tenders.go.ke/website/awards/index", "kind": "awards"},
    {"name": "Jamaica GOJEP Home", "country": "JM", "url": "https://www.gojep.gov.jm/epps/home.do", "kind": "portal"},
    {"name": "Jamaica GOJEP Search", "country": "JM", "url": "https://www.gojep.gov.jm/epps/quickSearchAction.do", "kind": "search"},
    {"name": "Jamaica GOJEP Open Tenders", "country": "JM", "url": "https://www.gojep.gov.jm/epps/viewCFTOpenTenderAction.do", "kind": "portal"},
    {"name": "Jamaica GOJEP Awards", "country": "JM", "url": "https://www.gojep.gov.jm/epps/viewAwardedCFTSAction.do", "kind": "awards"},
    {"name": "Chile Mercado Publico", "country": "CL", "url": "https://www.mercadopublico.cl/Home", "kind": "portal"},
    {"name": "Chile Mercado Publico Licitaciones", "country": "CL", "url": "https://www.mercadopublico.cl/Home/BusquedaLicitacion", "kind": "search"},
    {"name": "Chile Mercado Publico Convenio Marco", "country": "CL", "url": "https://www.mercadopublico.cl/Home/Convenios", "kind": "framework"},
    {"name": "Colombia SECOP II", "country": "CO", "url": "https://www.colombiacompra.gov.co/secop-ii", "kind": "portal"},
    {"name": "Colombia SECOP Search", "country": "CO", "url": "https://community.secop.gov.co/Public/Tendering/OpportunitySearch/Index", "kind": "search"},
    {"name": "Colombia TVEC", "country": "CO", "url": "https://www.colombiacompra.gov.co/tienda-virtual-del-estado-colombiano", "kind": "framework"},
    {"name": "Mexico Compranet", "country": "MX", "url": "https://upcp-compranet.hacienda.gob.mx/", "kind": "portal"},
    {"name": "Mexico Compranet Oportunidades", "country": "MX", "url": "https://upcp-compranet.hacienda.gob.mx/sitiopublico/#/", "kind": "search"},
    {"name": "Mexico Compranet Contratos", "country": "MX", "url": "https://upcp-compranet.hacienda.gob.mx/sitiopublico/#/contratos", "kind": "history"},
    {"name": "Ecuador SERCOP", "country": "EC", "url": "https://www.compraspublicas.gob.ec/ProcesoContratacion/compras/", "kind": "portal"},
    {"name": "Ecuador SERCOP Busqueda", "country": "EC", "url": "https://www.compraspublicas.gob.ec/ProcesoContratacion/compras/PC/buscarProceso.cpe", "kind": "search"},
    {"name": "Ecuador SERCOP Catalogo", "country": "EC", "url": "https://www.compraspublicas.gob.ec/ProcesoContratacion/compras/IC/catalogo.cpe", "kind": "framework"},
] + [
    {"name": name, "country": "IN", "url": url, "kind": "portal"} for name, url in INDIA_EPROCURE_STATE_PORTALS
]


STATIC_HOSTED_PLATFORM_SURFACES: list[dict[str, Any]] = [
    {"name": "EU Supply Public Tenders UK", "country": "GB", "url": "https://uk.eu-supply.com/ctm/supplier/publictenders", "platform": "eu_supply"},
    {"name": "EU Supply Public Tenders EU", "country": "EU", "url": "https://eu.eu-supply.com/ctm/supplier/publictenders", "platform": "eu_supply"},
    {"name": "EU Supply Denmark", "country": "DK", "url": "https://dk.eu-supply.com/ctm/supplier/publictenders", "platform": "eu_supply"},
    {"name": "EU Supply Netherlands", "country": "NL", "url": "https://nl.eu-supply.com/ctm/supplier/publictenders", "platform": "eu_supply"},
    {"name": "EU Supply Sweden", "country": "SE", "url": "https://se.eu-supply.com/ctm/supplier/publictenders", "platform": "eu_supply"},
    {"name": "EU Supply Norway", "country": "NO", "url": "https://no.eu-supply.com/ctm/supplier/publictenders", "platform": "eu_supply"},
    {"name": "EU Supply Finland", "country": "FI", "url": "https://fi.eu-supply.com/ctm/supplier/publictenders", "platform": "eu_supply"},
    {"name": "EU Supply Germany", "country": "DE", "url": "https://de.eu-supply.com/ctm/supplier/publictenders", "platform": "eu_supply"},
    {"name": "EU Supply Belgium", "country": "BE", "url": "https://be.eu-supply.com/ctm/supplier/publictenders", "platform": "eu_supply"},
    {"name": "EU Supply Ireland", "country": "IE", "url": "https://ie.eu-supply.com/ctm/supplier/publictenders", "platform": "eu_supply"},
    {"name": "Mercell Public Tenders", "country": "EU", "url": "https://www.mercell.com/en/tender/public-tenders", "platform": "mercell"},
    {"name": "Mercell Source to Contract", "country": "EU", "url": "https://s2c.mercell.com/buyer/publictenders", "platform": "mercell"},
    {"name": "Bids and Tenders Canada", "country": "CA", "url": "https://www.bidsandtenders.ca", "platform": "bidsandtenders"},
    {"name": "Bonfire Open Opportunities", "country": "CA", "url": "https://bonfirehub.com/publicagencyportal", "platform": "bonfire"},
    {"name": "Delta eSourcing", "country": "GB", "url": "https://www.delta-esourcing.com/delta/viewNotice.html", "platform": "delta_esourcing"},
    {"name": "In-Tend Host", "country": "GB", "url": "https://in-tendhost.co.uk", "platform": "in_tend"},
    {"name": "Jaggaer Supplier Portal", "country": "EU", "url": "https://www.jaggaer.com/solutions/supplier-management/", "platform": "jaggaer"},
    {"name": "Ivalua Procurement", "country": "EU", "url": "https://www.ivalua.com", "platform": "ivalua"},
    {"name": "Oracle Procurement Public Portal", "country": "INT", "url": "https://www.oracle.com/procurement/", "platform": "oracle_procurement"},
    {"name": "SAP Business Network Discovery", "country": "INT", "url": "https://discovery.ariba.com", "platform": "ariba"},
    {"name": "Coupa Sourcing", "country": "INT", "url": "https://sourcing.coupa.com", "platform": "coupa"},
    {"name": "Proactis Supplier Network", "country": "GB", "url": "https://www.proactisplaza.com", "platform": "proactis"},
    {"name": "Mercell Norway", "country": "NO", "url": "https://www.mercell.com/nb-no/anbud", "platform": "mercell"},
    {"name": "Mercell Sweden", "country": "SE", "url": "https://www.mercell.com/sv-se/upphandlingar", "platform": "mercell"},
    {"name": "Mercell Finland", "country": "FI", "url": "https://www.mercell.com/fi-fi/hankinnat", "platform": "mercell"},
    {"name": "Mercell Netherlands", "country": "NL", "url": "https://www.mercell.com/nl-nl/aanbestedingen", "platform": "mercell"},
    {"name": "Mercell Denmark", "country": "DK", "url": "https://www.mercell.com/da-dk/udbud", "platform": "mercell"},
    {"name": "Mercell Germany", "country": "DE", "url": "https://www.mercell.com/de-de/ausschreibungen", "platform": "mercell"},
    {"name": "Mercell Poland", "country": "PL", "url": "https://www.mercell.com/pl-pl/przetargi", "platform": "mercell"},
    {"name": "Mercell Estonia", "country": "EE", "url": "https://www.mercell.com/et-ee/hanked", "platform": "mercell"},
    {"name": "Mercell Latvia", "country": "LV", "url": "https://www.mercell.com/lv-lv/iepirkumi", "platform": "mercell"},
    {"name": "Mercell Lithuania", "country": "LT", "url": "https://www.mercell.com/lt-lt/pirkimai", "platform": "mercell"},
    {"name": "Bids and Tenders Ontario", "country": "CA", "url": "https://www.bidsandtenders.ca/municipalities", "platform": "bidsandtenders"},
    {"name": "Bids and Tenders Toronto", "country": "CA", "url": "https://bids.toronto.ca/Module/Tenders/en", "platform": "bidsandtenders"},
    {"name": "Bids and Tenders Brampton", "country": "CA", "url": "https://brampton.bidsandtenders.ca/Module/Tenders/en", "platform": "bidsandtenders"},
    {"name": "Bids and Tenders Ajax", "country": "CA", "url": "https://ajax.bidsandtenders.ca/Module/Tenders/en", "platform": "bidsandtenders"},
    {"name": "Bids and Tenders Halton", "country": "CA", "url": "https://halton.bidsandtenders.ca/Module/Tenders/en", "platform": "bidsandtenders"},
    {"name": "Bids and Tenders Hamilton", "country": "CA", "url": "https://hamilton.bidsandtenders.ca/Module/Tenders/en", "platform": "bidsandtenders"},
    {"name": "Bonfire Public Opportunities", "country": "US", "url": "https://www.gobonfire.com/opportunities", "platform": "bonfire"},
    {"name": "Bonfire University of Waterloo", "country": "CA", "url": "https://uwaterloo.bonfirehub.ca/portal", "platform": "bonfire"},
    {"name": "Bonfire Western University", "country": "CA", "url": "https://uwo.bonfirehub.ca/portal", "platform": "bonfire"},
    {"name": "Bonfire Brock University", "country": "CA", "url": "https://brocku.bonfirehub.ca/portal", "platform": "bonfire"},
    {"name": "Bonfire York University", "country": "CA", "url": "https://yorku.bonfirehub.ca/portal", "platform": "bonfire"},
    {"name": "Bonfire Brampton", "country": "CA", "url": "https://brampton.bonfirehub.ca/portal", "platform": "bonfire"},
    {"name": "Delta Public Sector Notices", "country": "GB", "url": "https://www.delta-esourcing.com", "platform": "delta_esourcing"},
    {"name": "Delta View Notice", "country": "GB", "url": "https://www.delta-esourcing.com/delta/viewNotice.html", "platform": "delta_esourcing"},
    {"name": "Delta Tenderbox", "country": "GB", "url": "https://www.delta-esourcing.com/tenders/UK-title/", "platform": "delta_esourcing"},
    {"name": "In-Tend Public Sector", "country": "GB", "url": "https://in-tendhost.co.uk", "platform": "in_tend"},
    {"name": "In-Tend Southampton", "country": "GB", "url": "https://in-tendhost.co.uk/southampton/aspx/Home", "platform": "in_tend"},
    {"name": "In-Tend Education Portal", "country": "GB", "url": "https://in-tendhost.co.uk/educationportal/aspx/Home", "platform": "in_tend"},
    {"name": "In-Tend West Lothian", "country": "GB", "url": "https://in-tendhost.co.uk/westlothian/aspx/Home", "platform": "in_tend"},
    {"name": "In-Tend Basingstoke", "country": "GB", "url": "https://in-tendhost.co.uk/basingstoke/aspx/Home", "platform": "in_tend"},
    {"name": "In-Tend Home Options", "country": "GB", "url": "https://in-tendhost.co.uk/homeoptions/aspx/Home", "platform": "in_tend"},
    {"name": "SAP Business Network Discovery Search", "country": "INT", "url": "https://discovery.ariba.com/rfx", "platform": "ariba"},
    {"name": "SAP Business Network Discovery Opportunities", "country": "INT", "url": "https://discovery.ariba.com/rfx/public/publicAribaDiscovery", "platform": "ariba"},
    {"name": "Coupa Public Sourcing Opportunities", "country": "INT", "url": "https://sourcing.coupa.com/opportunities", "platform": "coupa"},
    {"name": "Coupa Public Events", "country": "INT", "url": "https://sourcing.coupa.com/events", "platform": "coupa"},
    {"name": "Proactis Supplier Network Opportunities", "country": "GB", "url": "https://www.proactisplaza.com/supplier-network", "platform": "proactis"},
    {"name": "Jaggaer Supplier Hub", "country": "EU", "url": "https://www.jaggaer.com/suppliers/", "platform": "jaggaer"},
    {"name": "Ivalua Supplier Portal", "country": "EU", "url": "https://www.ivalua.com/supplier-management/", "platform": "ivalua"},
    {"name": "Oracle Supplier Portal", "country": "INT", "url": "https://www.oracle.com/procurement/supplier-portal/", "platform": "oracle_procurement"}
]


BUYER_DOMAIN_SEEDS: list[tuple[str, str, str, str]] = [
    ("uk_gov", "United Kingdom Government", "GB", "https://www.gov.uk"),
    ("scot_gov", "Scottish Government", "GB", "https://www.gov.scot"),
    ("wales_gov", "Welsh Government", "GB", "https://www.gov.wales"),
    ("nhs_england", "NHS England", "GB", "https://www.england.nhs.uk"),
    ("nhsbt", "NHS Blood and Transplant", "GB", "https://www.nhsbt.nhs.uk"),
    ("tfl", "Transport for London", "GB", "https://tfl.gov.uk"),
    ("manchester_council", "Manchester City Council", "GB", "https://www.manchester.gov.uk"),
    ("leeds_council", "Leeds City Council", "GB", "https://www.leeds.gov.uk"),
    ("irish_gov", "Government of Ireland", "IE", "https://www.gov.ie"),
    ("hse_ie", "Health Service Executive", "IE", "https://www.hse.ie"),
    ("bim_ie", "BIM Ireland", "IE", "https://www.bim.ie"),
    ("comreg_ie", "ComReg", "IE", "https://www.comreg.ie"),
    ("iwa_ie", "Irish Wheelchair Association", "IE", "https://www.iwa.ie"),
    ("redcross_ie", "Irish Red Cross", "IE", "https://www.redcross.ie"),
    ("helsinki", "City of Helsinki", "FI", "https://www.hel.fi"),
    ("finnvera", "Finnvera", "FI", "https://www.finnvera.fi"),
    ("business_finland", "Business Finland", "FI", "https://www.businessfinland.fi"),
    ("aalto", "Aalto University", "FI", "https://www.aalto.fi"),
    ("amsterdam", "Municipality of Amsterdam", "NL", "https://www.amsterdam.nl"),
    ("tennet", "TenneT", "NL", "https://www.tennet.eu"),
    ("rijkswaterstaat", "Rijkswaterstaat", "NL", "https://www.rijkswaterstaat.nl"),
    ("tudelft", "TU Delft", "NL", "https://www.tudelft.nl"),
    ("wellington", "Wellington City Council", "NZ", "https://wellington.govt.nz"),
    ("auckland_transport", "Auckland Transport", "NZ", "https://at.govt.nz"),
    ("otago", "University of Otago", "NZ", "https://www.otago.ac.nz"),
    ("transport_nsw", "Transport for NSW", "AU", "https://www.transport.nsw.gov.au"),
    ("vic_health", "Victoria Health", "AU", "https://www.health.vic.gov.au"),
    ("monash", "Monash University", "AU", "https://www.monash.edu"),
    ("unsw", "UNSW", "AU", "https://www.unsw.edu.au"),
    ("queensland", "Queensland Government", "AU", "https://www.qld.gov.au"),
    ("canada", "Government of Canada", "CA", "https://www.canada.ca"),
    ("toronto", "City of Toronto", "CA", "https://www.toronto.ca"),
    ("bc", "British Columbia Government", "CA", "https://www2.gov.bc.ca"),
    ("ubc", "University of British Columbia", "CA", "https://www.ubc.ca"),
    ("mcgill", "McGill University", "CA", "https://www.mcgill.ca"),
    ("treasury_za", "National Treasury South Africa", "ZA", "https://www.treasury.gov.za"),
    ("capetown", "City of Cape Town", "ZA", "https://www.capetown.gov.za"),
    ("gauteng", "Gauteng Government", "ZA", "https://www.gauteng.gov.za"),
    ("ppra_ke", "Public Procurement Regulatory Authority Kenya", "KE", "https://ppra.go.ke"),
    ("transport_ke", "Transport Kenya", "KE", "https://www.transport.go.ke"),
    ("ketraco", "KETRACO", "KE", "https://www.ketraco.co.ke"),
    ("jamaica_gov", "Government of Jamaica", "JM", "https://www.gov.jm"),
    ("mof_jm", "Jamaica Ministry of Finance", "JM", "https://mof.gov.jm"),
    ("gojep", "GOJEP Jamaica", "JM", "https://www.gojep.gov.jm"),
    ("india_gov", "Government of India", "IN", "https://www.india.gov.in"),
    ("nic_in", "National Informatics Centre", "IN", "https://www.nic.in"),
    ("railtel", "RailTel India", "IN", "https://www.railtel.in"),
    ("dbm_ph", "Department of Budget and Management Philippines", "PH", "https://www.dbm.gov.ph"),
    ("govph", "Government of the Philippines", "PH", "https://www.gov.ph"),
    ("dost_ph", "DOST Philippines", "PH", "https://www.dost.gov.ph"),
    ("tech_gov_sg", "GovTech Singapore", "SG", "https://www.tech.gov.sg"),
    ("singhealth", "SingHealth", "SG", "https://www.singhealth.com.sg"),
    ("gov_sg", "Government of Singapore", "SG", "https://www.gov.sg"),
    ("world_bank", "World Bank", "INT", "https://www.worldbank.org"),
    ("ungm", "UNGM", "UN", "https://www.ungm.org"),
    ("eu_commission", "European Commission", "EU", "https://commission.europa.eu"),
    ("ebrd", "EBRD", "INT", "https://www.ebrd.com"),
    ("adb", "ADB", "INT", "https://www.adb.org"),
    ("afdb", "AfDB", "INT", "https://www.afdb.org"),
    ("undp", "UNDP", "UN", "https://www.undp.org"),
    ("unicef", "UNICEF", "UN", "https://www.unicef.org")
]


BUYER_DIRECT_PATHS: list[tuple[str, str]] = [
    ("procurement", "/procurement"),
    ("suppliers", "/suppliers"),
    ("vendor_registration", "/vendor-registration"),
]
TRIGGER_PATHS: list[tuple[str, str]] = [
    ("careers", "/careers"),
]

HOST_TEMPLATE_PROCUREMENT_PATHS: list[tuple[str, str]] = [
    ("procurement", "/procurement"),
    ("procurement_tenders", "/procurement/tenders"),
    ("procurement_contracts", "/procurement/contracts"),
    ("procurement_pipeline", "/procurement/pipeline"),
    ("procurement_plans", "/procurement-plans"),
    ("suppliers", "/suppliers"),
    ("supplier_information", "/supplier-information"),
    ("vendor_registration", "/vendor-registration"),
    ("tenders", "/tenders"),
    ("tenders_contracts", "/tenders-and-contracts"),
    ("business_opportunities", "/business-opportunities"),
    ("opportunities", "/opportunities"),
    ("sourcing", "/sourcing"),
    ("frameworks", "/frameworks"),
    ("contract_awards", "/contract-awards"),
    ("market_engagement", "/market-engagement"),
    ("market_consultation", "/market-consultation"),
    ("standing_offers", "/standing-offers"),
]

HOST_TEMPLATE_TRIGGER_PATHS: list[tuple[str, str]] = [
    ("careers", "/careers"),
    ("jobs", "/jobs"),
    ("vacancies", "/vacancies"),
    ("digital_strategy", "/digital-strategy"),
    ("digital_transformation", "/digital-transformation"),
    ("strategy", "/strategy"),
    ("roadmap", "/roadmap"),
    ("budget", "/budget"),
    ("annual_plan", "/annual-plan"),
    ("board_papers", "/board-papers"),
]


@dataclass(slots=True)
class SourceSurface:
    source_key: str
    family: str
    family_group: str
    source_name: str
    country: str | None
    region: str | None
    canonical_url: str
    authenticity_class: str
    canonical_allowed: bool
    acquisition_mode: str
    attempt_strategy: str
    surface_kind: str
    discovery_provenance: str
    upstream_source: str | None = None
    source_platform: str | None = None
    language_hint: str | None = None
    notes: str | None = None


@dataclass(slots=True)
class AttemptResult:
    source_key: str
    source_name: str
    family: str
    family_group: str
    country: str | None
    canonical_url: str
    authenticity_class: str
    canonical_allowed: bool
    attempt_strategy: str
    request_method: str
    attempt_status: str
    http_status: int | None
    error_class: str | None
    issue_code: str | None
    content_type: str | None
    english_sufficiency_score: float
    extracted_docs_count: int
    retained_records_count: int
    seller_ready_records_count: int
    lanes_detected: list[str]
    matched_positive_terms: list[str]
    matched_negative_terms: list[str]
    blocker_reason: str | None
    next_action: str
    response_sha256: str | None
    response_sample_path: str | None
    robots_status: str | None
    platform_fingerprint: str | None
    latency_ms: int | None
    as_of_utc: str


class SourceUniverseService:
    def __init__(self, session: Session | None = None) -> None:
        self.session = session
        self.settings = get_settings()
        self.repo_root = Path.cwd()
        self.data_root = self.repo_root / "src" / "d365opps" / "data"
        self.artifact_root = self.settings.artifact_root / "source_campaign"
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self.registry_path = self.data_root / "source_universe_registry.jsonl"
        self.family_catalog = json.loads((self.data_root / "source_family_catalog.json").read_text(encoding="utf-8"))
        self.platform_fingerprints = json.loads((self.data_root / "source_platform_fingerprints.json").read_text(encoding="utf-8"))
        self.attempt_policies = json.loads((self.data_root / "source_attempt_policies.json").read_text(encoding="utf-8"))
        self._robots_cache: dict[str, tuple[str, RobotFileParser | None]] = {}

    def build_universe(self, *, target_size: int = 400, include_dynamic: bool = True) -> dict[str, Any]:
        now = datetime.now(UTC)
        stamp = now.strftime("%Y%m%dT%H%M%SZ")
        target = self.artifact_root / stamp
        if target.exists():
            for path in sorted(target.rglob("*"), reverse=True):
                if path.is_file():
                    path.unlink()
                else:
                    path.rmdir()
        target.mkdir(parents=True, exist_ok=True)

        raw_surfaces: list[SourceSurface] = []
        lineage: list[dict[str, Any]] = []

        source_pack_surfaces = self._load_source_pack_surfaces()
        raw_surfaces.extend(source_pack_surfaces)
        lineage.append({"seed": "source_pack", "count": len(source_pack_surfaces)})

        supranational = self._load_supranational_surfaces()
        raw_surfaces.extend(supranational)
        lineage.append({"seed": "static_supranational", "count": len(supranational)})

        official_national = self._load_official_national_surfaces()
        raw_surfaces.extend(official_national)
        lineage.append({"seed": "static_official_national", "count": len(official_national)})

        hosted = self._load_hosted_platform_surfaces()
        raw_surfaces.extend(hosted)
        lineage.append({"seed": "static_hosted_platforms", "count": len(hosted)})

        buyer_direct = self._load_buyer_direct_surfaces()
        raw_surfaces.extend(buyer_direct)
        lineage.append({"seed": "buyer_domain_catalog", "count": len(buyer_direct)})

        if include_dynamic:
            dynamic_surfaces = self._load_ocp_registry_surfaces()
            raw_surfaces.extend(dynamic_surfaces)
            lineage.append({"seed": "ocp_registry_publications", "count": len(dynamic_surfaces)})

            discovered_buyer_surfaces = self._discover_buyer_domain_surfaces()
            raw_surfaces.extend(discovered_buyer_surfaces)
            lineage.append({"seed": "buyer_homepage_discovery", "count": len(discovered_buyer_surfaces)})

        host_template_surfaces = self._expand_host_seed_surfaces(raw_surfaces)
        raw_surfaces.extend(host_template_surfaces)
        lineage.append({"seed": "host_template_expansion", "count": len(host_template_surfaces)})

        deduped, dedupe_report = self._dedupe_surfaces(raw_surfaces)
        if len(deduped) < target_size:
            overflow = self._load_buyer_direct_surfaces(extra_suffix="/business-opportunities")
            deduped, extra_report = self._dedupe_surfaces([*deduped, *overflow])
            dedupe_report["extra_expansion_duplicates_removed"] = extra_report["duplicates_removed"]

        self._write_registry(deduped)

        family_breakdown = self._breakdown_by(deduped, "family")
        country_breakdown = self._breakdown_by(deduped, "country")
        self._write_json(target / "source_universe_full.json", [asdict(item) for item in deduped])
        self._write_csv(target / "source_universe_full.csv", [asdict(item) for item in deduped])
        self._write_json(target / "source_universe_family_breakdown.json", family_breakdown)
        self._write_json(target / "source_universe_country_breakdown.json", country_breakdown)
        self._write_json(target / "source_universe_dedupe_report.json", dedupe_report)
        self._write_json(target / "source_universe_lineage.json", {"generated_at": now.isoformat(), "lineage": lineage})
        self._write_text(
            target / "source_universe_summary.md",
            self._source_universe_summary(deduped, family_breakdown, country_breakdown, dedupe_report, lineage),
        )
        self._sync_latest(target)
        return {
            "path": str(target),
            "latest_path": str(self.artifact_root / "latest"),
            "source_universe_total": len(deduped),
            "family_breakdown": family_breakdown,
            "country_breakdown": country_breakdown,
            "registry_path": str(self.registry_path),
        }

    def attempt_universe(self, *, concurrency: int = 20, rebuild_if_missing: bool = True) -> dict[str, Any]:
        if rebuild_if_missing and not self.registry_path.exists():
            self.build_universe()
        surfaces = self._read_registry()
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        target = self.artifact_root / f"{stamp}-attempts"
        target.mkdir(parents=True, exist_ok=True)
        samples_root = target / "samples"
        samples_root.mkdir(parents=True, exist_ok=True)
        as_of_utc = datetime.now(UTC).isoformat()

        results: list[AttemptResult] = []
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {executor.submit(self._attempt_surface, surface, samples_root, as_of_utc): surface for surface in surfaces}
            for future in as_completed(futures):
                results.append(future.result())
        results.sort(key=lambda item: (item.family_group, item.family, item.source_name, item.source_key))

        blocked = [asdict(item) for item in results if item.attempt_status.startswith("blocked_") or item.attempt_status in {"parser_failed", "unsupported_content", "source_removed_invalid"}]
        onboarding = self._free_onboarding_queue(results)
        matrices = self._campaign_matrices(results)
        productionization = self._productionization_report(results)
        attempt_report = self._attempt_report(results)
        verdict = self._campaign_verdict(results, attempt_report, productionization)
        potential_review = self._potential_hits_review(results, target)

        self._write_jsonl(target / "source_attempt_ledger.jsonl", [asdict(item) for item in results])
        self._write_csv(target / "source_attempt_ledger.csv", [asdict(item) for item in results])
        self._write_json(target / "blocked_sources_report.json", blocked)
        self._write_text(target / "blocked_sources_report.md", self._blocked_markdown(blocked))
        self._write_json(target / "free_source_onboarding_queue.json", onboarding)
        self._write_text(target / "free_account_or_api_onboarding_queue.md", self._onboarding_markdown(onboarding))
        self._write_json(target / "source_attempt_evidence_manifest.json", self._evidence_manifest(results))
        self._write_json(target / "attempt_all_sources_report.json", attempt_report)
        self._write_text(target / "attempt_all_sources_report.md", self._attempt_report_markdown(attempt_report))
        self._write_json(target / "source_yield_matrix.json", matrices["source_yield_matrix"])
        self._write_json(target / "family_coverage_matrix.json", matrices["family_coverage_matrix"])
        self._write_json(target / "country_coverage_matrix.json", matrices["country_coverage_matrix"])
        self._write_json(target / "attempt_status_matrix.json", matrices["attempt_status_matrix"])
        self._write_json(target / "yield_by_source.json", matrices["yield_by_source"])
        self._write_json(target / "yield_by_family.json", matrices["yield_by_family"])
        self._write_json(target / "yield_by_country.json", matrices["yield_by_country"])
        self._write_json(target / "yield_by_lane.json", matrices["yield_by_lane"])
        self._write_json(target / "blocked_by_reason.json", matrices["blocked_by_reason"])
        self._write_json(target / "onboarding_needed_by_source.json", onboarding)
        self._write_json(target / "official_domain_inventory.json", self._official_domain_inventory(results))
        self._write_json(target / "funnel_by_source.json", matrices["funnel_by_source"])
        self._write_json(target / "funnel_by_family.json", matrices["funnel_by_family"])
        self._write_json(target / "funnel_by_country.json", matrices["funnel_by_country"])
        self._write_json(target / "funnel_by_lane.json", matrices["funnel_by_lane"])
        self._write_csv(target / "funnel_by_source.csv", matrices["funnel_by_source"])
        self._write_csv(target / "funnel_by_family.csv", matrices["funnel_by_family"])
        self._write_csv(target / "funnel_by_country.csv", matrices["funnel_by_country"])
        self._write_csv(target / "funnel_by_lane.csv", matrices["funnel_by_lane"])
        self._write_json(target / "source_productionization_report.json", productionization)
        self._write_text(target / "source_productionization_report.md", self._productionization_markdown(productionization))
        self._write_json(target / "global_source_campaign_verdict.json", verdict)
        self._write_text(target / "global_source_campaign_verdict.md", self._campaign_verdict_markdown(verdict))
        self._write_text(target / "free_source_onboarding_guide.md", self._free_onboarding_guide(onboarding))
        self._write_json(target / "official_setup_urls.json", self.attempt_policies.get("free_onboarding", {}))
        self._write_json(target / "prime_hits_report.json", potential_review["prime_hits_report"])
        self._write_text(target / "prime_hits_report.md", self._prime_hits_markdown(potential_review["prime_hits_report"]))
        self._write_json(target / "potential_hits_report.json", potential_review["potential_hits_report"])
        self._write_text(target / "potential_hits_report.md", self._potential_hits_markdown(potential_review["potential_hits_report"]))
        self._write_json(target / "potential_hits_top12.json", potential_review["potential_hits_top12"])
        self._write_csv(target / "potential_hits_top12.csv", potential_review["potential_hits_top12"])
        self._write_json(target / "potential_hits_ai_review.json", potential_review["potential_hits_ai_review"])
        self._merge_latest_universe_artifacts(target)
        self._sync_latest(target)
        return {
            "path": str(target),
            "latest_path": str(self.artifact_root / "latest"),
            "attempted_source_surfaces": len(results),
            "successful_attempted_sources": attempt_report["successful_attempted_sources"],
            "sources_returning_docs": attempt_report["sources_returning_docs"],
            "sources_yielding_retained_d365_records": attempt_report["sources_yielding_retained_d365_records"],
            "sources_yielding_seller_ready_records": attempt_report["sources_yielding_seller_ready_records"],
            "production_ready_public_no_auth_sources": productionization["production_ready_public_no_auth_sources"],
            "seller_ready_total": attempt_report["seller_ready_total"],
            "seller_ready_bid_now_total": attempt_report["seller_ready_bid_now_total"],
            "seller_ready_pre_position_total": attempt_report["seller_ready_pre_position_total"],
            "potential_hits_total": potential_review["potential_hits_report"]["potential_hits_total"],
        }

    def run_campaign(self, *, target_size: int = 400, concurrency: int = 20, include_dynamic: bool = True) -> dict[str, Any]:
        build = self.build_universe(target_size=target_size, include_dynamic=include_dynamic)
        attempts = self.attempt_universe(concurrency=concurrency, rebuild_if_missing=False)
        return {"build": build, "attempts": attempts}

    def _load_source_pack_surfaces(self) -> list[SourceSurface]:
        payload = json.loads((self.data_root / "source_pack.json").read_text(encoding="utf-8"))
        surfaces: list[SourceSurface] = []
        family_map = {
            "official_procurement_api": "official_national_portal",
            "official_procurement_portal": "official_national_portal",
            "multilateral_procurement": "supranational_procurement",
            "registry": "ocds_registry_publisher",
            "hosted_sourcing": "hosted_procurement_instance",
            "feed": "official_national_portal",
            "sitemap": "buyer_direct_procurement",
            "search_api": "buyer_direct_procurement",
            "buyer_web": "buyer_direct_procurement",
        }
        for row in payload:
            family = family_map.get(str(row.get("source_family", "")))
            if family is None:
                family = "official_national_portal" if str(row.get("source_family", "")).startswith("official_") else "buyer_direct_procurement"
            strategy = self.family_catalog.get(family, {}).get("default_strategy", "html_browse")
            authenticity = classify_domain(normalize_host(row.get("endpoint")))
            surfaces.append(
                SourceSurface(
                    source_key=self._source_key(family, row["name"], row.get("country"), row["endpoint"], "seed"),
                    family=family,
                    family_group=self.family_catalog[family]["family_group"],
                    source_name=row["name"],
                    country=row.get("country"),
                    region=row.get("region"),
                    canonical_url=row["endpoint"],
                    authenticity_class=authenticity if authenticity != "unknown" else "official_public",
                    canonical_allowed=(authenticity != "synthetic_fixture"),
                    acquisition_mode=row.get("acquisition_method", "html"),
                    attempt_strategy=row.get("acquisition_method", strategy),
                    surface_kind="seed_source",
                    discovery_provenance="source_pack",
                    upstream_source=row.get("name"),
                    notes=row.get("description"),
                )
            )
        return surfaces

    def _load_supranational_surfaces(self) -> list[SourceSurface]:
        surfaces: list[SourceSurface] = []
        for row in STATIC_SUPRANATIONAL_SURFACES:
            family = row["family"]
            surfaces.append(
                SourceSurface(
                    source_key=self._source_key(family, row["name"], row["country"], row["url"], row["kind"]),
                    family=family,
                    family_group=self.family_catalog[family]["family_group"],
                    source_name=row["name"],
                    country=row["country"],
                    region="Global",
                    canonical_url=row["url"],
                    authenticity_class="official_public",
                    canonical_allowed=True,
                    acquisition_mode="api" if row["kind"] == "api" else "html",
                    attempt_strategy="api_query" if row["kind"] == "api" else "html_browse",
                    surface_kind=row["kind"],
                    discovery_provenance="static_supranational_catalog",
                )
            )
        return surfaces

    def _load_official_national_surfaces(self) -> list[SourceSurface]:
        surfaces: list[SourceSurface] = []
        for row in STATIC_OFFICIAL_NATIONAL_SURFACES:
            family = "official_national_portal"
            kind = row["kind"]
            if kind == "api":
                acquisition_mode = "api"
                attempt_strategy = "api_query"
            elif kind in {"dataset", "history"}:
                acquisition_mode = "dataset"
                attempt_strategy = "dataset_download"
            elif kind == "search":
                acquisition_mode = "html"
                attempt_strategy = "html_search"
            else:
                acquisition_mode = "html"
                attempt_strategy = "html_browse"
            surfaces.append(
                SourceSurface(
                    source_key=self._source_key(family, row["name"], row["country"], row["url"], kind),
                    family=family,
                    family_group=self.family_catalog[family]["family_group"],
                    source_name=row["name"],
                    country=row["country"],
                    region="Global",
                    canonical_url=row["url"],
                    authenticity_class="official_public",
                    canonical_allowed=True,
                    acquisition_mode=acquisition_mode,
                    attempt_strategy=attempt_strategy,
                    surface_kind=kind,
                    discovery_provenance="static_official_national_catalog",
                )
            )
        return surfaces

    def _load_hosted_platform_surfaces(self) -> list[SourceSurface]:
        surfaces: list[SourceSurface] = []
        for row in STATIC_HOSTED_PLATFORM_SURFACES:
            family = "hosted_procurement_instance"
            surfaces.append(
                SourceSurface(
                    source_key=self._source_key(family, row["name"], row["country"], row["url"], row["platform"]),
                    family=family,
                    family_group=self.family_catalog[family]["family_group"],
                    source_name=row["name"],
                    country=row["country"],
                    region="Global",
                    canonical_url=row["url"],
                    authenticity_class="third_party_mirror",
                    canonical_allowed=False,
                    acquisition_mode="html",
                    attempt_strategy="platform_fingerprint_probe",
                    surface_kind="hosted_portal",
                    discovery_provenance="static_platform_catalog",
                    source_platform=row["platform"],
                )
            )
        return surfaces

    def _load_buyer_direct_surfaces(self, *, extra_suffix: str | None = None) -> list[SourceSurface]:
        surfaces: list[SourceSurface] = []
        for key, label, country, base_url in BUYER_DOMAIN_SEEDS:
            for surface_kind, relative_path in BUYER_DIRECT_PATHS:
                target_path = extra_suffix if extra_suffix is not None else relative_path
                url = urljoin(base_url.rstrip("/") + "/", target_path.lstrip("/"))
                family = "buyer_direct_procurement"
                surfaces.append(
                    SourceSurface(
                        source_key=self._source_key(family, f"{label} {surface_kind}", country, url, surface_kind if extra_suffix is None else "business_opportunities"),
                        family=family,
                        family_group=self.family_catalog[family]["family_group"],
                        source_name=f"{label} {surface_kind.replace('_', ' ')}",
                        country=country,
                        region="Global",
                        canonical_url=url,
                        authenticity_class="official_public",
                        canonical_allowed=True,
                        acquisition_mode="html",
                        attempt_strategy="buyer_direct_probe",
                        surface_kind=surface_kind if extra_suffix is None else "business_opportunities",
                        discovery_provenance=f"buyer_domain::{key}",
                        upstream_source=base_url,
                    )
                )
            for surface_kind, relative_path in TRIGGER_PATHS:
                url = urljoin(base_url.rstrip("/") + "/", relative_path.lstrip("/"))
                family = "install_base_trigger"
                surfaces.append(
                    SourceSurface(
                        source_key=self._source_key(family, f"{label} {surface_kind}", country, url, surface_kind),
                        family=family,
                        family_group=self.family_catalog[family]["family_group"],
                        source_name=f"{label} {surface_kind.replace('_', ' ')}",
                        country=country,
                        region="Global",
                        canonical_url=url,
                        authenticity_class="official_public",
                        canonical_allowed=True,
                        acquisition_mode="html",
                        attempt_strategy="job_posting_probe",
                        surface_kind=surface_kind,
                        discovery_provenance=f"buyer_domain::{key}",
                        upstream_source=base_url,
                    )
                )
        return surfaces

    def _load_ocp_registry_surfaces(self) -> list[SourceSurface]:
        surfaces: list[SourceSurface] = []
        try:
            with httpx.Client(
                timeout=min(self.settings.http_timeout_seconds, 20),
                follow_redirects=True,
                headers={"User-Agent": self.settings.user_agent},
            ) as client:
                response = client.get("https://data.open-contracting.org/en/publications.json")
                response.raise_for_status()
                publications = response.json()
        except Exception:
            return surfaces
        for row in publications:
            source_url = row.get("source_url")
            source_id = row.get("source_id") or row.get("id")
            if not source_url:
                continue
            host = normalize_host(source_url)
            authenticity = classify_domain(host)
            surfaces.append(
                SourceSurface(
                    source_key=self._source_key("ocds_registry_publisher", row.get("title") or str(source_id), row.get("country"), source_url, "publication"),
                    family="ocds_registry_publisher",
                    family_group=self.family_catalog["ocds_registry_publisher"]["family_group"],
                    source_name=row.get("title") or str(source_id),
                    country=row.get("country"),
                    region=row.get("region"),
                    canonical_url=source_url,
                    authenticity_class="official_public" if authenticity == "official_public" else (authenticity or "unknown"),
                    canonical_allowed=authenticity != "synthetic_fixture",
                    acquisition_mode="dataset",
                    attempt_strategy="ocds_download",
                    surface_kind="publication_dataset",
                    discovery_provenance=f"ocp_registry::{source_id}",
                    upstream_source=f"https://data.open-contracting.org/en/publication/{source_id}/",
                    language_hint=row.get("language"),
                    notes=f"OCP publication {source_id}",
                )
            )
        return surfaces

    def _discover_buyer_domain_surfaces(self) -> list[SourceSurface]:
        surfaces: list[SourceSurface] = []
        with ThreadPoolExecutor(max_workers=12) as executor:
            futures = {
                executor.submit(self._discover_buyer_domain_links, key, label, country, base_url): (key, label, country, base_url)
                for key, label, country, base_url in BUYER_DOMAIN_SEEDS
            }
            for future in as_completed(futures):
                try:
                    surfaces.extend(future.result())
                except Exception:
                    continue
        return surfaces

    def _discover_buyer_domain_links(self, key: str, label: str, country: str, base_url: str) -> list[SourceSurface]:
        try:
            with httpx.Client(
                timeout=min(self.settings.http_timeout_seconds, 8),
                follow_redirects=True,
                headers={"User-Agent": self.settings.user_agent},
            ) as client:
                response = client.get(base_url)
                response.raise_for_status()
        except Exception:
            return []
        soup = BeautifulSoup(response.text, "html.parser")
        procurement_hits = 0
        trigger_hits = 0
        hosted_hits = 0
        seen: set[str] = set()
        discovered: list[SourceSurface] = []
        home_host = normalize_host(base_url)
        for anchor in soup.find_all("a", href=True):
            href = urljoin(str(response.url), anchor.get("href", ""))
            parsed = urlparse(href)
            if parsed.scheme not in {"http", "https"}:
                continue
            normalized = self._normalize_url(href)
            if normalized in seen:
                continue
            anchor_text = f"{anchor.get_text(' ', strip=True)} {href}".strip().lower()
            fingerprint = self._fingerprint_platform(normalize_host(href), anchor_text)
            if fingerprint and hosted_hits < 3:
                discovered.append(
                    SourceSurface(
                        source_key=self._source_key("hosted_procurement_instance", f"{label} {fingerprint} hosted portal", country, href, "discovered_hosted"),
                        family="hosted_procurement_instance",
                        family_group=self.family_catalog["hosted_procurement_instance"]["family_group"],
                        source_name=f"{label} {fingerprint.replace('_', ' ')} hosted portal",
                        country=country,
                        region="Global",
                        canonical_url=href,
                        authenticity_class="official_public",
                        canonical_allowed=True,
                        acquisition_mode="html",
                        attempt_strategy="platform_fingerprint_probe",
                        surface_kind="discovered_hosted",
                        discovery_provenance=f"buyer_homepage::{key}",
                        upstream_source=base_url,
                        source_platform=fingerprint,
                    )
                )
                hosted_hits += 1
                seen.add(normalized)
                continue
            link_host = normalize_host(href)
            if link_host and home_host and link_host != home_host and not link_host.endswith(f".{home_host}"):
                continue
            if procurement_hits < 4 and any(token in anchor_text for token in ("procurement", "supplier", "vendor", "tender", "contract", "bid", "opportun", "sourcing", "business opportun")):
                discovered.append(
                    SourceSurface(
                        source_key=self._source_key("buyer_direct_procurement", f"{label} discovered procurement page", country, href, "discovered_procurement"),
                        family="buyer_direct_procurement",
                        family_group=self.family_catalog["buyer_direct_procurement"]["family_group"],
                        source_name=f"{label} discovered procurement page",
                        country=country,
                        region="Global",
                        canonical_url=href,
                        authenticity_class="official_public",
                        canonical_allowed=True,
                        acquisition_mode="html",
                        attempt_strategy="buyer_direct_probe",
                        surface_kind="discovered_procurement",
                        discovery_provenance=f"buyer_homepage::{key}",
                        upstream_source=base_url,
                    )
                )
                procurement_hits += 1
                seen.add(normalized)
                continue
            if trigger_hits < 3 and any(token in anchor_text for token in ("career", "job", "vacanc", "strategy", "budget", "annual plan", "transformation", "modernisation", "modernization", "roadmap", "digital")):
                attempt_strategy = "document_probe" if normalized.lower().endswith((".pdf", ".doc", ".docx")) else "job_posting_probe"
                discovered.append(
                    SourceSurface(
                        source_key=self._source_key("install_base_trigger", f"{label} discovered trigger page", country, href, "discovered_trigger"),
                        family="install_base_trigger",
                        family_group=self.family_catalog["install_base_trigger"]["family_group"],
                        source_name=f"{label} discovered trigger page",
                        country=country,
                        region="Global",
                        canonical_url=href,
                        authenticity_class="official_public",
                        canonical_allowed=True,
                        acquisition_mode="document" if attempt_strategy == "document_probe" else "html",
                        attempt_strategy=attempt_strategy,
                        surface_kind="discovered_trigger",
                        discovery_provenance=f"buyer_homepage::{key}",
                        upstream_source=base_url,
                    )
                )
                trigger_hits += 1
                seen.add(normalized)
        return discovered

    def _expand_host_seed_surfaces(self, seeds: list[SourceSurface]) -> list[SourceSurface]:
        selected_by_host: dict[str, SourceSurface] = {}
        for seed in seeds:
            if not seed.canonical_allowed:
                continue
            if seed.family == "hosted_procurement_instance":
                continue
            parsed = urlparse(seed.canonical_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                continue
            host = normalize_host(seed.canonical_url)
            if not host or host in {"example.com", "localhost", "127.0.0.1"}:
                continue
            previous = selected_by_host.get(host)
            if previous is None or self._host_seed_rank(seed) > self._host_seed_rank(previous):
                selected_by_host[host] = seed

        surfaces: list[SourceSurface] = []
        for host, seed in selected_by_host.items():
            parsed = urlparse(seed.canonical_url)
            root = f"{parsed.scheme}://{parsed.netloc}"
            label = re.sub(
                r"\s+(search|results|home|portal|api|opportunities|awards|notices|current|publication page|publication)$",
                "",
                seed.source_name,
                flags=re.I,
            ).strip()
            base_label = label or seed.source_name
            for surface_kind, relative_path in HOST_TEMPLATE_PROCUREMENT_PATHS:
                url = urljoin(root.rstrip("/") + "/", relative_path.lstrip("/"))
                surfaces.append(
                    SourceSurface(
                        source_key=self._source_key("buyer_direct_procurement", f"{base_label} {surface_kind}", seed.country, url, f"host_template_{surface_kind}"),
                        family="buyer_direct_procurement",
                        family_group=self.family_catalog["buyer_direct_procurement"]["family_group"],
                        source_name=f"{base_label} {surface_kind.replace('_', ' ')}",
                        country=seed.country,
                        region=seed.region,
                        canonical_url=url,
                        authenticity_class=seed.authenticity_class or "unknown",
                        canonical_allowed=seed.canonical_allowed,
                        acquisition_mode="html",
                        attempt_strategy="buyer_direct_probe",
                        surface_kind=f"host_template_{surface_kind}",
                        discovery_provenance=f"host_template::{host}",
                        upstream_source=root,
                    )
                )
            for surface_kind, relative_path in HOST_TEMPLATE_TRIGGER_PATHS:
                url = urljoin(root.rstrip("/") + "/", relative_path.lstrip("/"))
                surfaces.append(
                    SourceSurface(
                        source_key=self._source_key("install_base_trigger", f"{base_label} {surface_kind}", seed.country, url, f"host_template_{surface_kind}"),
                        family="install_base_trigger",
                        family_group=self.family_catalog["install_base_trigger"]["family_group"],
                        source_name=f"{base_label} {surface_kind.replace('_', ' ')}",
                        country=seed.country,
                        region=seed.region,
                        canonical_url=url,
                        authenticity_class=seed.authenticity_class or "unknown",
                        canonical_allowed=seed.canonical_allowed,
                        acquisition_mode="html",
                        attempt_strategy="job_posting_probe",
                        surface_kind=f"host_template_{surface_kind}",
                        discovery_provenance=f"host_template::{host}",
                        upstream_source=root,
                    )
                )
        return surfaces

    def _host_seed_rank(self, seed: SourceSurface) -> int:
        score = 0
        if seed.authenticity_class == "official_public":
            score += 4
        elif seed.authenticity_class == "unknown":
            score += 2
        if seed.family == "official_national_portal":
            score += 4
        elif seed.family == "supranational_procurement":
            score += 3
        elif seed.family == "ocds_registry_publisher":
            score += 2
        elif seed.family == "buyer_direct_procurement":
            score += 1
        if seed.country:
            score += 1
        return score

    def _dedupe_surfaces(self, surfaces: list[SourceSurface]) -> tuple[list[SourceSurface], dict[str, Any]]:
        deduped: list[SourceSurface] = []
        seen_by_url: dict[str, SourceSurface] = {}
        duplicates: list[dict[str, Any]] = []
        for surface in surfaces:
            url_key = self._normalize_url(surface.canonical_url)
            if url_key in seen_by_url:
                duplicates.append(
                    {
                        "kept": seen_by_url[url_key].source_key,
                        "dropped": surface.source_key,
                        "reason": "normalized_url_duplicate",
                        "url": surface.canonical_url,
                    }
                )
                continue
            seen_by_url[url_key] = surface
            deduped.append(surface)
        report = {
            "raw_count": len(surfaces),
            "deduped_count": len(deduped),
            "duplicates_removed": len(duplicates),
            "dedupe_key_rule": "lowercase scheme+host+path with query/fragment removed and trailing slash normalized",
            "duplicates": duplicates[:250],
        }
        return deduped, report

    def _attempt_surface(self, surface: SourceSurface, samples_root: Path, as_of_utc: str) -> AttemptResult:
        strategy = surface.attempt_strategy
        policy = self.attempt_policies["strategies"].get(strategy, {})
        timeout = policy.get("timeout_seconds", self.attempt_policies["defaults"]["timeout_seconds"])
        max_bytes = policy.get("read_bytes", self.attempt_policies["defaults"]["max_bytes"])
        host = normalize_host(surface.canonical_url)
        robots_status, _ = self._robots_for(surface.canonical_url)
        if self.attempt_policies["defaults"]["respect_robots"] and robots_status == "blocked":
            return AttemptResult(
                source_key=surface.source_key,
                source_name=surface.source_name,
                family=surface.family,
                family_group=surface.family_group,
                country=surface.country,
                canonical_url=surface.canonical_url,
                authenticity_class=surface.authenticity_class,
                canonical_allowed=surface.canonical_allowed,
                attempt_strategy=strategy,
                request_method="GET",
                attempt_status="blocked_robots",
                http_status=None,
                error_class=None,
                issue_code="robots_disallow",
                content_type=None,
                english_sufficiency_score=0.0,
                extracted_docs_count=0,
                retained_records_count=0,
                seller_ready_records_count=0,
                lanes_detected=[],
                matched_positive_terms=[],
                matched_negative_terms=[],
                blocker_reason="robots.txt disallows the selected probe path",
                next_action="respect_robots_and_skip",
                response_sha256=None,
                response_sample_path=None,
                robots_status=robots_status,
                platform_fingerprint=None,
                latency_ms=None,
                as_of_utc=as_of_utc,
            )

        started = datetime.now(UTC)
        try:
            with httpx.Client(
                timeout=timeout,
                follow_redirects=self.attempt_policies["defaults"]["follow_redirects"],
                headers={"User-Agent": self.settings.user_agent},
            ) as client:
                request_method, response = self._campaign_request(client, surface)
            latency_ms = int((datetime.now(UTC) - started).total_seconds() * 1000)
        except httpx.ConnectTimeout:
            return self._blocked_result(surface, strategy, "blocked_network", "connect_timeout", "network timeout during attempt", robots_status, as_of_utc)
        except httpx.ReadTimeout:
            return self._blocked_result(surface, strategy, "blocked_network", "read_timeout", "read timeout during attempt", robots_status, as_of_utc)
        except httpx.HTTPError as exc:
            return self._blocked_result(surface, strategy, "blocked_network", type(exc).__name__, str(exc), robots_status, as_of_utc)

        status = response.status_code
        content_type = (response.headers.get("content-type") or "").split(";", 1)[0].strip().lower() or None
        body = response.content[:max_bytes]
        sample_path = samples_root / f"{self._safe_filename(surface.source_key)}.sample"
        sample_path.write_bytes(body)
        body_text = self._decode_body(body, content_type)
        page_title = self._extract_title(body_text, content_type)
        platform_fingerprint = self._fingerprint_platform(host, body_text)

        if status == 401:
            return self._finalize_attempt(surface, strategy, request_method, "blocked_auth_required_free", status, "auth_required", content_type, body, sample_path, body_text, robots_status, platform_fingerprint, latency_ms, as_of_utc)
        if status == 403:
            lower = body_text.lower()
            if "captcha" in lower or "challenge" in lower:
                return self._finalize_attempt(surface, strategy, request_method, "blocked_captcha", status, "captcha_or_challenge", content_type, body, sample_path, body_text, robots_status, platform_fingerprint, latency_ms, as_of_utc)
            return self._finalize_attempt(surface, strategy, request_method, "blocked_terms_or_policy", status, "http_403", content_type, body, sample_path, body_text, robots_status, platform_fingerprint, latency_ms, as_of_utc)
        if status == 404:
            return self._finalize_attempt(surface, strategy, request_method, "source_removed_invalid", status, "http_404", content_type, body, sample_path, body_text, robots_status, platform_fingerprint, latency_ms, as_of_utc)
        if status == 429:
            return self._finalize_attempt(surface, strategy, request_method, "blocked_rate_limit", status, "http_429", content_type, body, sample_path, body_text, robots_status, platform_fingerprint, latency_ms, as_of_utc)
        if status >= 500:
            return self._finalize_attempt(surface, strategy, request_method, "blocked_network", status, "http_5xx", content_type, body, sample_path, body_text, robots_status, platform_fingerprint, latency_ms, as_of_utc)
        if content_type and not any(content_type.startswith(prefix) for prefix in ("text/", "application/json", "application/xml", "application/rss+xml", "application/atom+xml")):
            return self._finalize_attempt(surface, strategy, request_method, "unsupported_content", status, "unsupported_content_type", content_type, body, sample_path, body_text, robots_status, platform_fingerprint, latency_ms, as_of_utc)

        analysis = self._analyze_payload(body_text, page_title, surface)
        return AttemptResult(
            source_key=surface.source_key,
            source_name=surface.source_name,
            family=surface.family,
            family_group=surface.family_group,
            country=surface.country,
            canonical_url=surface.canonical_url,
            authenticity_class=surface.authenticity_class,
            canonical_allowed=surface.canonical_allowed,
            attempt_strategy=strategy,
            request_method=request_method,
            attempt_status="success_with_docs" if analysis["docs"] > 0 else "success_no_docs",
            http_status=status,
            error_class=None,
            issue_code=None,
            content_type=content_type,
            english_sufficiency_score=analysis["english_sufficiency_score"],
            extracted_docs_count=analysis["docs"],
            retained_records_count=analysis["retained_records"],
            seller_ready_records_count=analysis["seller_ready_records"],
            lanes_detected=analysis["lanes"],
            matched_positive_terms=analysis["positive_terms"],
            matched_negative_terms=analysis["negative_terms"],
            blocker_reason=None if analysis["docs"] > 0 else "probe succeeded but no obvious document/listing signal was extracted in the sampled payload",
            next_action=analysis["next_action"],
            response_sha256=sha256_bytes(body),
            response_sample_path=str(sample_path),
            robots_status=robots_status,
            platform_fingerprint=platform_fingerprint,
            latency_ms=latency_ms,
            as_of_utc=as_of_utc,
        )

    def _campaign_request(self, client: httpx.Client, surface: SourceSurface) -> tuple[str, httpx.Response]:
        url = surface.canonical_url
        lowered = url.lower()
        if "api.ted.europa.eu/v3/notices/search" in lowered:
            response = client.post(
                url,
                json={
                    "query": 'notice-title ~ "Dynamics 365" OR notice-title ~ "Microsoft Dynamics" OR notice-title ~ "Power Platform"',
                    "limit": 5,
                    "scope": "ALL",
                    "fields": ["publication-number", "notice-title", "buyer-name", "publication-date", "links"],
                },
            )
            return "POST", response
        if "etenders.gov.ie/epps/viewcftsaction.do" in lowered:
            response = client.post(
                url,
                data={
                    "isExport": "true",
                    "isFTS": "true",
                    "isQuickSearch": "true",
                    "freeText": "Microsoft Dynamics",
                    "type": "cftFTS",
                    "tableUid": "searchCft",
                },
            )
            return "POST", response
        if "hankintailmoitukset.fi/fi/public/api/notice-search" in lowered:
            response = client.get(
                url,
                params={
                    "lang": "en",
                    "search": '"Dynamics 365"',
                    "$filter": "isLatest eq true",
                    "$orderby": "datePublished desc",
                    "$top": 5,
                    "$skip": 0,
                },
            )
            return "GET", response
        if "find-tender.service.gov.uk/search" in lowered:
            response = client.get(url, params={"keywords": '"Microsoft Dynamics"'})
            return "GET", response
        if "mercadopublico.cl/home/busquedalicitacion" in lowered:
            response = client.get(url, params={"textoBusqueda": "Microsoft Dynamics"})
            return "GET", response
        response = client.get(url)
        return "GET", response

    def _finalize_attempt(self, surface: SourceSurface, strategy: str, request_method: str, attempt_status: str, status: int, issue_code: str, content_type: str | None, body: bytes, sample_path: Path, body_text: str, robots_status: str | None, platform_fingerprint: str | None, latency_ms: int | None, as_of_utc: str) -> AttemptResult:
        return AttemptResult(
            source_key=surface.source_key,
            source_name=surface.source_name,
            family=surface.family,
            family_group=surface.family_group,
            country=surface.country,
            canonical_url=surface.canonical_url,
            authenticity_class=surface.authenticity_class,
            canonical_allowed=surface.canonical_allowed,
            attempt_strategy=strategy,
            request_method=request_method,
            attempt_status=attempt_status,
            http_status=status,
            error_class=None,
            issue_code=issue_code,
            content_type=content_type,
            english_sufficiency_score=self._english_sufficiency(body_text),
            extracted_docs_count=0,
            retained_records_count=0,
            seller_ready_records_count=0,
            lanes_detected=[],
            matched_positive_terms=[],
            matched_negative_terms=self._matching_terms(body_text.lower(), NEGATIVE_HINTS),
            blocker_reason=f"{attempt_status} during lawful probe",
            next_action=self._blocked_next_action(surface.source_name, attempt_status),
            response_sha256=sha256_bytes(body),
            response_sample_path=str(sample_path),
            robots_status=robots_status,
            platform_fingerprint=platform_fingerprint,
            latency_ms=latency_ms,
            as_of_utc=as_of_utc,
        )

    def _blocked_result(self, surface: SourceSurface, strategy: str, attempt_status: str, issue_code: str, blocker_reason: str, robots_status: str | None, as_of_utc: str) -> AttemptResult:
        return AttemptResult(
            source_key=surface.source_key,
            source_name=surface.source_name,
            family=surface.family,
            family_group=surface.family_group,
            country=surface.country,
            canonical_url=surface.canonical_url,
            authenticity_class=surface.authenticity_class,
            canonical_allowed=surface.canonical_allowed,
            attempt_strategy=strategy,
            request_method="GET",
            attempt_status=attempt_status,
            http_status=None,
            error_class=issue_code,
            issue_code=issue_code,
            content_type=None,
            english_sufficiency_score=0.0,
            extracted_docs_count=0,
            retained_records_count=0,
            seller_ready_records_count=0,
            lanes_detected=[],
            matched_positive_terms=[],
            matched_negative_terms=[],
            blocker_reason=blocker_reason,
            next_action=self._blocked_next_action(surface.source_name, attempt_status),
            response_sha256=None,
            response_sample_path=None,
            robots_status=robots_status,
            platform_fingerprint=None,
            latency_ms=None,
            as_of_utc=as_of_utc,
        )

    def _analyze_payload(self, body_text: str, page_title: str | None, surface: SourceSurface) -> dict[str, Any]:
        text = " ".join(part for part in [page_title or "", body_text] if part).lower()
        positive_terms = self._matching_terms(text, PRODUCT_ANCHORS)
        negative_terms = self._matching_terms(text, NEGATIVE_HINTS)
        procurement_terms = self._matching_terms(text, PROCUREMENT_HINTS)
        service_terms = self._matching_terms(text, SERVICE_HINTS)
        preposition_terms = self._matching_terms(text, PREPOSITION_HINTS)
        award_terms = self._matching_terms(text, AWARD_HINTS)
        trigger_terms = self._matching_terms(text, TRIGGER_HINTS)
        english_sufficiency_score = self._english_sufficiency(text)

        docs = self._estimate_docs(body_text)
        retained_records = 1 if positive_terms and (procurement_terms or service_terms or trigger_terms) and not negative_terms else 0
        seller_ready = 1 if retained_records and english_sufficiency_score >= 0.18 and surface.authenticity_class == "official_public" and surface.canonical_allowed else 0
        lanes: list[str] = []
        if award_terms:
            lanes.append("award_watch")
        if preposition_terms:
            lanes.append("pre_position")
        if "framework" in text or "standing offer" in text or "supply arrangement" in text:
            lanes.append("framework_vehicle")
        if trigger_terms and not procurement_terms:
            lanes.append("install_base_trigger")
        if procurement_terms and not award_terms:
            lanes.append("bid_now")
        if not lanes:
            lanes.append("monitor")
        next_action = "monitor"
        if seller_ready and "bid_now" in lanes:
            next_action = "promote_bid_now"
        elif seller_ready and "pre_position" in lanes:
            next_action = "promote_pre_position"
        elif retained_records:
            next_action = "retain_for_research"
        elif procurement_terms or service_terms:
            next_action = "keep_as_near_miss"
        return {
            "docs": docs,
            "retained_records": retained_records,
            "seller_ready_records": seller_ready,
            "lanes": sorted(set(lanes)),
            "positive_terms": positive_terms,
            "negative_terms": negative_terms,
            "english_sufficiency_score": round(english_sufficiency_score, 4),
            "next_action": next_action,
        }

    def _estimate_docs(self, body_text: str) -> int:
        if not body_text.strip():
            return 0
        soup = BeautifulSoup(body_text, "html.parser")
        title_hits = len(soup.find_all(["article", "li", "tr", "div"], string=re.compile(r"tender|rfp|notice|contract|opportun", re.I)))
        link_hits = len([tag for tag in soup.find_all("a", href=True) if re.search(r"notice|tender|opportun|contract|procurement", tag.get_text(" ", strip=True) or "", re.I)])
        if title_hits or link_hits:
            return min(25, max(title_hits, link_hits))
        trimmed = body_text.lstrip()
        if trimmed.startswith("{") or trimmed.startswith("["):
            return max(1, min(25, body_text.count('"title"') + body_text.count('"ocid"') + body_text.count('"notice"')))
        return 1 if len(body_text.split()) > 40 else 0

    def _english_sufficiency(self, text: str) -> float:
        words = re.findall(r"[a-z]{2,}", text.lower())[:1200]
        if not words:
            return 0.0
        hits = sum(1 for word in words if word in ENGLISH_STOPWORDS)
        ratio = hits / max(len(words), 1)
        return min(1.0, ratio * 8 + hits / 20)

    def _matching_terms(self, text: str, terms: tuple[str, ...]) -> list[str]:
        return sorted({term for term in terms if term in text})

    def _extract_title(self, body_text: str, content_type: str | None) -> str | None:
        if content_type and content_type.startswith("application/json"):
            match = re.search(r'"title"\s*:\s*"([^"]+)"', body_text, re.I)
            return match.group(1) if match else None
        soup = BeautifulSoup(body_text, "html.parser")
        if soup.title and soup.title.string:
            return soup.title.string.strip()
        h1 = soup.find("h1")
        return h1.get_text(" ", strip=True) if h1 else None

    def _fingerprint_platform(self, host: str | None, body_text: str) -> str | None:
        lowered = body_text.lower()
        for key, payload in self.platform_fingerprints.items():
            host_markers = payload.get("host_markers", [])
            if host and any(marker in host for marker in host_markers):
                return key
            if any(marker.lower() in lowered for marker in payload.get("content_markers", [])):
                return key
        return None

    def _robots_for(self, url: str) -> tuple[str, RobotFileParser | None]:
        parsed = urlparse(url)
        root = f"{parsed.scheme}://{parsed.netloc}"
        if root in self._robots_cache:
            status, parser = self._robots_cache[root]
            if parser and not parser.can_fetch(self.settings.user_agent, url):
                return "blocked", parser
            return status, parser
        robots_url = urljoin(root.rstrip("/") + "/", "robots.txt")
        parser = RobotFileParser()
        try:
            with httpx.Client(timeout=3, headers={"User-Agent": self.settings.user_agent}, follow_redirects=True) as client:
                response = client.get(robots_url)
            if response.status_code >= 400:
                self._robots_cache[root] = ("unknown", None)
                return "unknown", None
            parser.parse(response.text.splitlines())
            allowed = parser.can_fetch(self.settings.user_agent, url)
            status = "allowed" if allowed else "blocked"
            self._robots_cache[root] = (status, parser)
            return status, parser
        except Exception:
            self._robots_cache[root] = ("unknown", None)
            return "unknown", None

    def _campaign_matrices(self, results: list[AttemptResult]) -> dict[str, Any]:
        source_yield_matrix: list[dict[str, Any]] = []
        by_family: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        by_country: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        by_lane: Counter[str] = Counter()
        blocked_by_reason: Counter[str] = Counter()
        funnel_by_source: list[dict[str, Any]] = []
        funnel_by_family: list[dict[str, Any]] = []
        funnel_by_country: list[dict[str, Any]] = []
        funnel_by_lane: list[dict[str, Any]] = []
        attempt_status_matrix: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        family_coverage_matrix: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        country_coverage_matrix: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

        for item in results:
            yielded = item.retained_records_count > 0
            source_yield_matrix.append(
                {
                    "source_key": item.source_key,
                    "source_name": item.source_name,
                    "family": item.family,
                    "country": item.country,
                    "attempted_queries": 1,
                    "executed_queries": 1,
                    "returned_documents": item.extracted_docs_count,
                    "retained_records": item.retained_records_count,
                    "current_actionable_records": 1 if any(lane in {"bid_now", "pre_position"} for lane in item.lanes_detected) and item.retained_records_count else 0,
                    "seller_ready_records": item.seller_ready_records_count,
                    "noisy_records": 1 if item.matched_negative_terms and not item.retained_records_count else 0,
                    "zero_yield_flag": not yielded,
                    "partial_yield_flag": item.extracted_docs_count > 0 and not yielded,
                    "attempt_status": item.attempt_status,
                }
            )
            by_family[item.family]["attempted"] += 1
            by_family[item.family]["docs"] += item.extracted_docs_count
            by_family[item.family]["retained"] += item.retained_records_count
            by_family[item.family]["seller_ready"] += item.seller_ready_records_count
            by_country[item.country or "unknown"]["attempted"] += 1
            by_country[item.country or "unknown"]["docs"] += item.extracted_docs_count
            by_country[item.country or "unknown"]["retained"] += item.retained_records_count
            by_country[item.country or "unknown"]["seller_ready"] += item.seller_ready_records_count
            for lane in item.lanes_detected:
                by_lane[lane] += item.retained_records_count or 1
            if item.blocker_reason:
                blocked_by_reason[item.attempt_status] += 1
            attempt_status_matrix[item.family][item.attempt_status] += 1
            family_coverage_matrix[item.family_group][item.attempt_status] += 1
            country_coverage_matrix[item.country or "unknown"][item.attempt_status] += 1
            funnel_by_source.append(
                {
                    "source_key": item.source_key,
                    "source_name": item.source_name,
                    "family": item.family,
                    "country": item.country,
                    "attempts": 1,
                    "docs": item.extracted_docs_count,
                    "retained_d365_records": item.retained_records_count,
                    "seller_ready_records": item.seller_ready_records_count,
                    "attempt_status": item.attempt_status,
                }
            )

        for family, counts in sorted(by_family.items()):
            funnel_by_family.append({"family": family, **counts})
        for country, counts in sorted(by_country.items()):
            funnel_by_country.append({"country": country, **counts})
        for lane, count in sorted(by_lane.items()):
            funnel_by_lane.append({"lane": lane, "records": count})

        return {
            "source_yield_matrix": source_yield_matrix,
            "family_coverage_matrix": family_coverage_matrix,
            "country_coverage_matrix": country_coverage_matrix,
            "attempt_status_matrix": attempt_status_matrix,
            "yield_by_source": source_yield_matrix,
            "yield_by_family": funnel_by_family,
            "yield_by_country": funnel_by_country,
            "yield_by_lane": funnel_by_lane,
            "blocked_by_reason": dict(blocked_by_reason),
            "funnel_by_source": funnel_by_source,
            "funnel_by_family": funnel_by_family,
            "funnel_by_country": funnel_by_country,
            "funnel_by_lane": funnel_by_lane,
        }

    def _productionization_report(self, results: list[AttemptResult]) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        prod_ready = 0
        for item in results:
            production_ready = (
                item.authenticity_class == "official_public"
                and item.attempt_status in {"success_with_docs", "success_no_docs"}
                and item.family in {"official_national_portal", "supranational_procurement", "ocds_registry_publisher"}
            )
            if production_ready:
                prod_ready += 1
            rows.append(
                {
                    "source_key": item.source_key,
                    "source_name": item.source_name,
                    "family": item.family,
                    "country": item.country,
                    "attempt_status": item.attempt_status,
                    "production_ready": production_ready,
                    "yielding_retained_d365": item.retained_records_count > 0,
                    "yielding_seller_ready": item.seller_ready_records_count > 0,
                    "blocker_reason": item.blocker_reason,
                    "next_action": item.next_action,
                }
            )
        return {"generated_at": datetime.now(UTC).isoformat(), "production_ready_public_no_auth_sources": prod_ready, "rows": rows}

    def _attempt_report(self, results: list[AttemptResult]) -> dict[str, Any]:
        status_counts = Counter(item.attempt_status for item in results)
        by_family = Counter(item.family for item in results)
        by_country = Counter(item.country or "unknown" for item in results)
        seller_ready_bid_now = sum(1 for item in results if item.seller_ready_records_count and "bid_now" in item.lanes_detected)
        seller_ready_pre_position = sum(1 for item in results if item.seller_ready_records_count and "pre_position" in item.lanes_detected)
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "source_universe_total": len(results),
            "attempted_source_surfaces": len(results),
            "successful_attempted_sources": sum(1 for item in results if item.attempt_status.startswith("success_")),
            "sources_returning_docs": sum(1 for item in results if item.extracted_docs_count > 0),
            "sources_yielding_retained_d365_records": sum(1 for item in results if item.retained_records_count > 0),
            "sources_yielding_seller_ready_records": sum(1 for item in results if item.seller_ready_records_count > 0),
            "retained_d365_records": sum(item.retained_records_count for item in results),
            "seller_ready_total": sum(item.seller_ready_records_count for item in results),
            "seller_ready_bid_now_total": seller_ready_bid_now,
            "seller_ready_pre_position_total": seller_ready_pre_position,
            "attempt_status_counts": dict(status_counts),
            "family_counts": dict(by_family),
            "country_counts": dict(by_country),
        }

    def _campaign_verdict(self, results: list[AttemptResult], attempt_report: dict[str, Any], productionization: dict[str, Any]) -> dict[str, Any]:
        blocked = Counter(item.attempt_status for item in results if item.attempt_status.startswith("blocked_"))
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "total_source_universe_count": attempt_report["source_universe_total"],
            "total_attempted_count": attempt_report["attempted_source_surfaces"],
            "total_successful_attempts": attempt_report["successful_attempted_sources"],
            "total_blocked_by_captcha": blocked.get("blocked_captcha", 0),
            "total_blocked_by_robots": blocked.get("blocked_robots", 0),
            "total_blocked_by_terms_or_policy": blocked.get("blocked_terms_or_policy", 0),
            "total_blocked_by_free_account_requirement": blocked.get("blocked_auth_required_free", 0),
            "total_blocked_by_paid_account_requirement": blocked.get("blocked_auth_required_paid", 0),
            "total_parser_failures": sum(1 for item in results if item.attempt_status == "parser_failed"),
            "total_docs_returning_sources": attempt_report["sources_returning_docs"],
            "total_retained_d365_yielding_sources": attempt_report["sources_yielding_retained_d365_records"],
            "total_seller_ready_yielding_sources": attempt_report["sources_yielding_seller_ready_records"],
            "production_ready_public_no_auth_sources": productionization["production_ready_public_no_auth_sources"],
            "exact_top_blockers": dict(Counter(item.attempt_status for item in results if item.blocker_reason).most_common(10)),
            "exact_next_onboarding_actions": self._free_onboarding_queue(results)[:20],
            "exact_next_productionization_queue": [row for row in productionization["rows"] if not row["production_ready"]][:20],
        }

    def review_latest_potential_hits(self, *, limit: int | None = None, ai_shortlist: int | None = None, use_ai: bool | None = None, campaign_path: str | None = None) -> dict[str, Any]:
        target = Path(campaign_path) if campaign_path else self.artifact_root / "latest"
        ledger_path = target / "source_attempt_ledger.jsonl"
        if not ledger_path.exists():
            raise RuntimeError(f"Missing source attempt ledger at {ledger_path}")
        results = [AttemptResult(**json.loads(line)) for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        potential_review = self._potential_hits_review(
            results,
            target,
            limit=limit,
            ai_shortlist=ai_shortlist,
            use_ai=use_ai,
        )
        self._write_json(target / "prime_hits_report.json", potential_review["prime_hits_report"])
        self._write_text(target / "prime_hits_report.md", self._prime_hits_markdown(potential_review["prime_hits_report"]))
        self._write_json(target / "potential_hits_report.json", potential_review["potential_hits_report"])
        self._write_text(target / "potential_hits_report.md", self._potential_hits_markdown(potential_review["potential_hits_report"]))
        self._write_json(target / "potential_hits_top12.json", potential_review["potential_hits_top12"])
        self._write_csv(target / "potential_hits_top12.csv", potential_review["potential_hits_top12"])
        self._write_json(target / "potential_hits_ai_review.json", potential_review["potential_hits_ai_review"])
        if target.resolve() == (self.artifact_root / "latest").resolve():
            latest_named = self._latest_attempt_directory()
            if latest_named and latest_named.exists():
                for filename in (
                    "prime_hits_report.json",
                    "prime_hits_report.md",
                    "potential_hits_report.json",
                    "potential_hits_report.md",
                    "potential_hits_top12.json",
                    "potential_hits_top12.csv",
                    "potential_hits_ai_review.json",
                ):
                    source = target / filename
                    destination = latest_named / filename
                    if source.exists():
                        destination.write_bytes(source.read_bytes())
        return {
            "path": str(target),
            "prime_hits_total": potential_review["prime_hits_report"]["prime_hits_total"],
            "potential_hits_total": potential_review["potential_hits_report"]["potential_hits_total"],
            "ai_review_status": potential_review["potential_hits_report"]["ai_review_status"],
        }

    def detail_follow_bucket(
        self,
        *,
        bucket: str = "promising_surface_needs_detail_follow",
        limit: int | None = None,
        campaign_path: str | None = None,
    ) -> dict[str, Any]:
        target = Path(campaign_path) if campaign_path else self.artifact_root / "latest"
        review_path = target / "full_document_intelligent_review.jsonl"
        if not review_path.exists():
            raise RuntimeError(f"Missing full document review at {review_path}")

        rows = [json.loads(line) for line in review_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        bucket_rows = [row for row in rows if row.get("verdict") == bucket]
        bucket_rows.sort(
            key=lambda row: (
                -int(row.get("promising_score") or 0),
                -int(row.get("specificity_score") or 0),
                str(row.get("source_name") or ""),
            )
        )
        selected = bucket_rows[: limit or self.settings.detail_follow_candidate_limit]
        samples_root = target / "detail_follow_samples"
        samples_root.mkdir(parents=True, exist_ok=True)
        as_of_utc = datetime.now(UTC).isoformat()

        results: list[dict[str, Any]] = []
        max_workers = min(self.settings.detail_follow_concurrency, max(len(selected), 1))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(self._detail_follow_candidate, row, samples_root, as_of_utc): row for row in selected}
            for future in as_completed(futures):
                results.append(future.result())
        results.sort(
            key=lambda row: (
                {"promoted_seller_ready": 0, "promoted_research": 1, "watch_only": 2, "still_needs_manual_review": 3, "no_upgrade": 4, "blocked": 5}.get(str(row.get("final_state")), 9),
                -float(row.get("best_detail_score") or 0.0),
                str(row.get("source_name") or ""),
            )
        )

        report = self._detail_follow_report(results, bucket=bucket, source_file=review_path.name)
        bucket_slug = re.sub(r"[^a-z0-9]+", "_", bucket.lower()).strip("_") or "bucket"
        results_path = target / f"detail_follow_{bucket_slug}_results.jsonl"
        report_json_path = target / f"detail_follow_{bucket_slug}_report.json"
        report_md_path = target / f"detail_follow_{bucket_slug}_report.md"
        promoted_seller_ready_path = target / f"detail_follow_{bucket_slug}_promoted_seller_ready.csv"
        promoted_research_path = target / f"detail_follow_{bucket_slug}_promoted_research.csv"
        watch_only_path = target / f"detail_follow_{bucket_slug}_watch_only.csv"

        results_path.write_text("\n".join(json.dumps(row, default=json_default) for row in results) + "\n", encoding="utf-8")
        self._write_json(report_json_path, report)
        self._write_text(report_md_path, self._detail_follow_markdown(report))
        self._write_csv(promoted_seller_ready_path, [row for row in results if row.get("final_state") == "promoted_seller_ready"])
        self._write_csv(promoted_research_path, [row for row in results if row.get("final_state") == "promoted_research"])
        self._write_csv(watch_only_path, [row for row in results if row.get("final_state") == "watch_only"])

        if target.resolve() == (self.artifact_root / "latest").resolve():
            latest_named = self._latest_attempt_directory()
            if latest_named and latest_named.exists():
                for path in (
                    results_path,
                    report_json_path,
                    report_md_path,
                    promoted_seller_ready_path,
                    promoted_research_path,
                    watch_only_path,
                ):
                    destination = latest_named / path.name
                    if path.exists():
                        destination.write_bytes(path.read_bytes())

        return {
            "path": str(target),
            "bucket": bucket,
            "candidates_reviewed": len(results),
            "promoted_seller_ready_total": report["final_state_counts"].get("promoted_seller_ready", 0),
            "promoted_research_total": report["final_state_counts"].get("promoted_research", 0),
            "watch_only_total": report["final_state_counts"].get("watch_only", 0),
        }

    def _potential_hits_review(
        self,
        results: list[AttemptResult],
        target: Path,
        *,
        limit: int | None = None,
        ai_shortlist: int | None = None,
        use_ai: bool | None = None,
    ) -> dict[str, Any]:
        top_limit = limit or self.settings.potential_hits_limit
        shortlist_limit = ai_shortlist or self.settings.potential_hits_ai_shortlist
        ai_enabled = self.settings.potential_hits_ai_enabled if use_ai is None else use_ai
        prime_hits = self._prime_hits_rows(results)
        candidates = self._potential_hit_candidates(results)
        heuristic_ranked = sorted(candidates, key=lambda row: (-row["heuristic_score"], -row["english_sufficiency_score"], row["source_name"]))
        ai_review = self._ai_review_potential_hits(heuristic_ranked[:shortlist_limit], enabled=ai_enabled)
        ai_rows = {row["candidate_id"]: row for row in ai_review.get("reviews", [])}
        for row in candidates:
            review = ai_rows.get(row["candidate_id"])
            if review:
                row["ai_review"] = review
                row["ai_score"] = int(review.get("score") or 0)
                row["ai_promising"] = bool(review.get("promising"))
                row["final_score"] = round(row["heuristic_score"] * 0.45 + row["ai_score"] * 0.55, 2)
                ai_lane = str(review.get("lane") or "").strip()
                if ai_lane and ai_lane not in row["lanes_detected"]:
                    row["lanes_detected"] = sorted({*row["lanes_detected"], ai_lane})
            else:
                row["ai_review"] = None
                row["ai_score"] = None
                row["ai_promising"] = None
                row["final_score"] = float(row["heuristic_score"])
        ranked = sorted(
            candidates,
            key=lambda row: (
                -int(bool(row.get("ai_promising"))),
                -float(row["final_score"]),
                -float(row["heuristic_score"]),
                row["source_name"],
            ),
        )
        top_hits = self._diversify_potential_hits(ranked, limit=top_limit)
        potential_report = {
            "generated_at": datetime.now(UTC).isoformat(),
            "prime_hits_total": len(prime_hits),
            "prime_hits_names": [row["source_name"] for row in prime_hits],
            "docs_returning_non_prime_total": sum(1 for item in results if item.extracted_docs_count > 0 and item.seller_ready_records_count == 0),
            "potential_candidate_pool_total": len(candidates),
            "potential_hits_total": len(top_hits),
            "ai_review_status": ai_review["status"],
            "ai_review_model": ai_review.get("model"),
            "ai_reviewed_candidates": ai_review.get("reviewed_candidates", 0),
            "top_potential_hits": top_hits,
        }
        prime_report = {
            "generated_at": datetime.now(UTC).isoformat(),
            "prime_hits_total": len(prime_hits),
            "prime_hits": prime_hits,
        }
        return {
            "prime_hits_report": prime_report,
            "potential_hits_report": potential_report,
            "potential_hits_top12": top_hits,
            "potential_hits_ai_review": ai_review,
        }

    def _detail_follow_candidate(self, row: dict[str, Any], samples_root: Path, as_of_utc: str) -> dict[str, Any]:
        sample_text = self._read_sample_text(row.get("response_sample_path"))
        original_blockers = list(row.get("why_not_promoted") or [])
        authenticity_blocked = "authenticity_policy_blocks_promotion" in original_blockers
        competitor_blocked = "competitor_false_friend_terms_present" in original_blockers
        detail_candidates = self._extract_detail_candidates(
            sample_text,
            base_url=str(row.get("canonical_url") or ""),
            content_kind=str(row.get("content_kind") or "html"),
            limit=self.settings.detail_follow_per_candidate_limit,
        )
        detail_reviews: list[dict[str, Any]] = []
        blocked_reasons: Counter[str] = Counter()

        for candidate in detail_candidates:
            review = self._fetch_detail_candidate(candidate, row=row, samples_root=samples_root, as_of_utc=as_of_utc)
            detail_reviews.append(review)
            if review.get("blocker_reason"):
                blocked_reasons.update([str(review["blocker_reason"])])

        best = self._best_detail_review(detail_reviews)
        final_state = "no_upgrade"
        final_reason = "no_promotable_detail_found"
        if best:
            if authenticity_blocked or competitor_blocked or best.get("negative_terms"):
                final_state = "no_upgrade"
                final_reason = "authenticity_or_competitor_policy_still_blocks_promotion"
            elif best.get("seller_ready_records"):
                final_state = "promoted_seller_ready"
                final_reason = "strict_anchor_and_commercial_signal_found_in_detail"
            elif best.get("retained_records"):
                final_state = "promoted_research"
                final_reason = "strict_anchor_found_but_not_seller_ready"
            elif best.get("watch_only"):
                final_state = "watch_only"
                final_reason = "detail_is_award_or_history_dominant"
            elif best.get("soft_anchor_terms") and (best.get("procurement_terms") or best.get("service_terms")):
                final_state = "still_needs_manual_review"
                final_reason = "detail_strengthened_case_but_strict_anchor_still_missing"
        elif detail_candidates and blocked_reasons:
            final_state = "blocked"
            final_reason = blocked_reasons.most_common(1)[0][0]
        elif detail_candidates:
            final_state = "still_needs_manual_review"
            final_reason = "detail_follow_attempted_but_no_stronger_signal_found"
        else:
            final_state = "no_upgrade"
            final_reason = "no_candidate_detail_links_found_in_sample"

        return {
            "source_name": row.get("source_name"),
            "country": row.get("country"),
            "family": row.get("family"),
            "canonical_url": row.get("canonical_url"),
            "original_verdict": row.get("verdict"),
            "original_promising_score": row.get("promising_score"),
            "original_blockers": original_blockers,
            "detail_candidate_count": len(detail_candidates),
            "detail_attempted_count": len(detail_reviews),
            "detail_success_count": sum(1 for item in detail_reviews if item.get("http_status") and int(item["http_status"]) < 400),
            "final_state": final_state,
            "final_reason": final_reason,
            "best_detail_score": best.get("detail_score") if best else 0,
            "best_detail_url": best.get("url") if best else None,
            "best_detail_title": best.get("title") if best else None,
            "best_detail_positive_terms": best.get("positive_terms") if best else [],
            "best_detail_soft_anchor_terms": best.get("soft_anchor_terms") if best else [],
            "best_detail_service_terms": best.get("service_terms") if best else [],
            "best_detail_procurement_terms": best.get("procurement_terms") if best else [],
            "best_detail_award_terms": best.get("award_terms") if best else [],
            "best_detail_closed_terms": best.get("closed_terms") if best else [],
            "best_detail_english_sufficiency_score": best.get("english_sufficiency_score") if best else 0.0,
            "best_detail_excerpt": best.get("excerpt") if best else None,
            "detail_reviews": detail_reviews[: min(5, len(detail_reviews))],
        }

    def _extract_detail_candidates(self, sample_text: str, *, base_url: str, content_kind: str, limit: int) -> list[dict[str, Any]]:
        if not sample_text.strip():
            return []
        candidates: dict[str, dict[str, Any]] = {}
        root_host = normalize_host(base_url)
        lowered_kind = content_kind.lower()

        if lowered_kind == "json" or sample_text.lstrip().startswith(("{", "[")):
            for url in self._extract_urls_from_jsonish(sample_text, base_url):
                score = self._detail_candidate_score(url, url, base_url=base_url)
                if score <= 0:
                    continue
                normalized = self._normalize_url(url)
                current = candidates.get(normalized)
                payload = {
                    "url": url,
                    "anchor_text": "",
                    "score": score,
                    "host": normalize_host(url),
                    "same_host": normalize_host(url) == root_host,
                }
                if not current or score > current["score"]:
                    candidates[normalized] = payload
        else:
            soup = BeautifulSoup(sample_text, "html.parser")
            for anchor in soup.find_all("a", href=True):
                href = str(anchor.get("href") or "").strip()
                if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                    continue
                url = urljoin(base_url, href)
                parsed = urlparse(url)
                if parsed.scheme not in {"http", "https"}:
                    continue
                anchor_text = " ".join(part for part in [anchor.get_text(" ", strip=True), href] if part)
                score = self._detail_candidate_score(url, anchor_text, base_url=base_url)
                if score <= 0:
                    continue
                normalized = self._normalize_url(url)
                current = candidates.get(normalized)
                payload = {
                    "url": url,
                    "anchor_text": anchor_text[:300],
                    "score": score,
                    "host": normalize_host(url),
                    "same_host": normalize_host(url) == root_host,
                }
                if not current or score > current["score"]:
                    candidates[normalized] = payload

        ranked = sorted(candidates.values(), key=lambda item: (-int(item["score"]), item["url"]))
        return ranked[:limit]

    def _extract_urls_from_jsonish(self, sample_text: str, base_url: str) -> list[str]:
        urls: set[str] = set()
        try:
            payload = json.loads(sample_text)
            stack = [payload]
            while stack:
                current = stack.pop()
                if isinstance(current, dict):
                    stack.extend(current.values())
                elif isinstance(current, list):
                    stack.extend(current)
                elif isinstance(current, str):
                    candidate = current.replace("\\/", "/").strip()
                    if candidate.startswith(("http://", "https://")):
                        urls.add(candidate)
                    elif candidate.startswith("/"):
                        urls.add(urljoin(base_url, candidate))
        except Exception:
            pass
        for match in re.finditer(r"https?://[^\s\"'<>\\\\]+", sample_text):
            urls.add(match.group(0).replace("\\/", "/"))
        return sorted(urls)

    def _detail_candidate_score(self, url: str, anchor_text: str, *, base_url: str) -> int:
        host = normalize_host(url)
        base_host = normalize_host(base_url)
        lowered = f"{anchor_text} {url}".lower()
        if any(token in lowered for token in ("login", "register", "privacy", "cookie", "accessibility", "contact us", "help center", "manual", "news", "media", "about us", "home")):
            return 0

        score = 0
        if host == base_host:
            score += 12
        elif host and base_host and (host.endswith(f".{base_host}") or base_host.endswith(f".{host}")):
            score += 8
        elif classify_domain(host) == "official_public":
            score += 5

        if re.search(r"notice|tender|contract|award|procurement|opportun|cft|rfx|rfp|supplier|framework|market|consult", lowered):
            score += 18
        if re.search(r"detail|view|publicat|result|search|document|download|attachment", lowered):
            score += 8
        if re.search(r"\b\d{4,}\b|[a-z]{2,}-\d{3,}", lowered):
            score += 6
        if re.search(r"\.pdf($|\?)|download", lowered):
            score += 4
        if len(urlparse(url).path.strip("/").split("/")) >= 2:
            score += 4
        if re.search(r"award|history|archive|closed|cancelled", lowered):
            score -= 4
        return max(score, 0)

    def _fetch_detail_candidate(self, candidate: dict[str, Any], *, row: dict[str, Any], samples_root: Path, as_of_utc: str) -> dict[str, Any]:
        url = str(candidate["url"])
        robots_status, parser = self._robots_for(url)
        if robots_status == "blocked" or (parser and not parser.can_fetch(self.settings.user_agent, url)):
            return {
                "url": url,
                "anchor_text": candidate.get("anchor_text"),
                "detail_score": 0,
                "blocker_reason": "robots_blocked",
                "http_status": None,
                "issue_code": "robots_blocked",
            }

        started = datetime.now(UTC)
        try:
            with httpx.Client(
                timeout=self.settings.http_timeout_seconds,
                follow_redirects=self.attempt_policies["defaults"]["follow_redirects"],
                headers={"User-Agent": self.settings.user_agent},
            ) as client:
                response = client.get(url)
            latency_ms = int((datetime.now(UTC) - started).total_seconds() * 1000)
        except httpx.ConnectTimeout:
            return {"url": url, "anchor_text": candidate.get("anchor_text"), "detail_score": 0, "blocker_reason": "connect_timeout", "http_status": None, "issue_code": "connect_timeout"}
        except httpx.ReadTimeout:
            return {"url": url, "anchor_text": candidate.get("anchor_text"), "detail_score": 0, "blocker_reason": "read_timeout", "http_status": None, "issue_code": "read_timeout"}
        except httpx.HTTPError as exc:
            return {"url": url, "anchor_text": candidate.get("anchor_text"), "detail_score": 0, "blocker_reason": type(exc).__name__, "http_status": None, "issue_code": type(exc).__name__}

        status = response.status_code
        content_type = (response.headers.get("content-type") or "").split(";", 1)[0].strip().lower() or None
        body = response.content[: self.settings.max_attachment_bytes]
        sample_path = samples_root / f"{self._safe_filename(url)}.sample"
        sample_path.write_bytes(body)
        body_text = self._decode_body(body, content_type)
        title = self._extract_title(body_text, content_type)
        if status >= 400:
            return {
                "url": url,
                "anchor_text": candidate.get("anchor_text"),
                "candidate_score": candidate.get("score"),
                "detail_score": 0,
                "http_status": status,
                "content_type": content_type,
                "title": title,
                "latency_ms": latency_ms,
                "response_sample_path": str(sample_path),
                "english_sufficiency_score": 0.0,
                "positive_terms": [],
                "negative_terms": [],
                "soft_anchor_terms": [],
                "service_terms": [],
                "procurement_terms": [],
                "preposition_terms": [],
                "award_terms": [],
                "closed_terms": [],
                "retained_records": 0,
                "seller_ready_records": 0,
                "lanes": [],
                "watch_only": False,
                "blocker_reason": f"http_{status}",
                "issue_code": f"http_{status}",
                "excerpt": re.sub(r"\s+", " ", body_text)[:600],
            }
        analysis = self._analyze_payload(body_text, title, self._row_as_surface(row))
        lowered = " ".join(part for part in [title or "", body_text] if part).lower()
        soft_anchor_terms = self._matching_terms(lowered, POTENTIAL_PRODUCT_HINTS)
        service_terms = self._matching_terms(lowered, SERVICE_HINTS)
        procurement_terms = self._matching_terms(lowered, PROCUREMENT_HINTS)
        preposition_terms = self._matching_terms(lowered, PREPOSITION_HINTS)
        award_terms = self._matching_terms(lowered, AWARD_HINTS)
        closed_terms = sorted({term for term in ("cancelled", "closed", "expired", "award date", "awarded") if term in lowered})
        watch_only = bool(award_terms) and not analysis["positive_terms"]
        detail_score = self._detail_review_score(
            analysis=analysis,
            soft_anchor_terms=soft_anchor_terms,
            service_terms=service_terms,
            procurement_terms=procurement_terms,
            preposition_terms=preposition_terms,
            award_terms=award_terms,
        )
        excerpt = re.sub(r"\s+", " ", BeautifulSoup(body_text, "html.parser").get_text(" ", strip=True))[:1200]

        return {
            "url": url,
            "anchor_text": candidate.get("anchor_text"),
            "candidate_score": candidate.get("score"),
            "detail_score": detail_score,
            "http_status": status,
            "content_type": content_type,
            "title": title,
            "latency_ms": latency_ms,
            "response_sample_path": str(sample_path),
            "english_sufficiency_score": analysis["english_sufficiency_score"],
            "positive_terms": analysis["positive_terms"],
            "negative_terms": analysis["negative_terms"],
            "soft_anchor_terms": soft_anchor_terms,
            "service_terms": service_terms,
            "procurement_terms": procurement_terms,
            "preposition_terms": preposition_terms,
            "award_terms": award_terms,
            "closed_terms": closed_terms,
            "retained_records": analysis["retained_records"],
            "seller_ready_records": analysis["seller_ready_records"],
            "lanes": analysis["lanes"],
            "watch_only": watch_only,
            "blocker_reason": None if status < 400 else f"http_{status}",
            "issue_code": None if status < 400 else f"http_{status}",
            "excerpt": excerpt,
        }

    def _row_as_surface(self, row: dict[str, Any]) -> SourceSurface:
        host = normalize_host(str(row.get("canonical_url") or ""))
        authenticity_class = classify_domain(host)
        canonical_allowed = authenticity_class == "official_public" and "authenticity_policy_blocks_promotion" not in (row.get("why_not_promoted") or [])
        return SourceSurface(
            source_key=str(row.get("source_name") or row.get("canonical_url") or "detail-follow"),
            family=str(row.get("family") or "unknown"),
            family_group="detail_follow",
            source_name=str(row.get("source_name") or "detail-follow"),
            country=row.get("country"),
            region=None,
            canonical_url=str(row.get("canonical_url") or ""),
            authenticity_class=authenticity_class,
            canonical_allowed=canonical_allowed,
            acquisition_mode="detail_follow",
            attempt_strategy="detail_follow",
            surface_kind="detail_follow",
            discovery_provenance="detail_follow_bucket",
        )

    def _detail_review_score(
        self,
        *,
        analysis: dict[str, Any],
        soft_anchor_terms: list[str],
        service_terms: list[str],
        procurement_terms: list[str],
        preposition_terms: list[str],
        award_terms: list[str],
    ) -> float:
        score = 0.0
        if analysis["positive_terms"]:
            score += 60 + len(analysis["positive_terms"]) * 8
        elif soft_anchor_terms:
            score += 24 + len(soft_anchor_terms) * 3
        if procurement_terms:
            score += 14
        if service_terms:
            score += 12
        if preposition_terms:
            score += 8
        if award_terms:
            score += 2
        if analysis["seller_ready_records"]:
            score += 20
        elif analysis["retained_records"]:
            score += 12
        if analysis["negative_terms"]:
            score -= len(analysis["negative_terms"]) * 12
        return round(max(score, 0.0), 2)

    def _best_detail_review(self, reviews: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not reviews:
            return None
        ranked = sorted(
            reviews,
            key=lambda item: (
                -int(bool(item.get("seller_ready_records"))),
                -int(bool(item.get("retained_records"))),
                -float(item.get("detail_score") or 0.0),
                str(item.get("url") or ""),
            ),
        )
        return ranked[0]

    def _detail_follow_report(self, results: list[dict[str, Any]], *, bucket: str, source_file: str) -> dict[str, Any]:
        final_state_counts = Counter(str(row.get("final_state") or "unknown") for row in results)
        final_reason_counts = Counter(str(row.get("final_reason") or "unknown") for row in results)
        country_counts = Counter(str(row.get("country") or "unknown") for row in results)
        family_counts = Counter(str(row.get("family") or "unknown") for row in results)
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "bucket": bucket,
            "source_file": source_file,
            "candidates_reviewed": len(results),
            "final_state_counts": dict(final_state_counts),
            "top_final_reasons": final_reason_counts.most_common(20),
            "top_countries": country_counts.most_common(20),
            "top_families": family_counts.most_common(20),
            "top_upgrades": [row for row in results if row.get("final_state") in {"promoted_seller_ready", "promoted_research"}][:25],
            "top_manual_review": [row for row in results if row.get("final_state") == "still_needs_manual_review"][:25],
            "top_watch_only": [row for row in results if row.get("final_state") == "watch_only"][:25],
        }

    def _detail_follow_markdown(self, report: dict[str, Any]) -> str:
        lines = [
            "# Detail Follow Report",
            "",
            f"- Bucket: {report['bucket']}",
            f"- Source file: {report['source_file']}",
            f"- Candidates reviewed: {report['candidates_reviewed']}",
            "",
            "## Final State Counts",
        ]
        for key, value in sorted(report["final_state_counts"].items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"- {key}: {value}")
        lines.extend(["", "## Top Final Reasons"])
        for key, value in report["top_final_reasons"][:12]:
            lines.append(f"- {key}: {value}")
        lines.extend(["", "## Top Upgrades"])
        for item in report["top_upgrades"][:15]:
            lines.append(
                f"- {item['source_name']} ({item.get('country')}) -> {item['final_state']} | "
                f"best_detail={item.get('best_detail_url') or 'n/a'} | "
                f"anchors={','.join(item.get('best_detail_positive_terms') or item.get('best_detail_soft_anchor_terms') or []) or 'n/a'}"
            )
        lines.extend(["", "## Top Manual Review"])
        for item in report["top_manual_review"][:15]:
            lines.append(
                f"- {item['source_name']} ({item.get('country')}) -> {item['final_reason']} | "
                f"best_detail={item.get('best_detail_url') or 'n/a'} | "
                f"anchors={','.join(item.get('best_detail_positive_terms') or item.get('best_detail_soft_anchor_terms') or []) or 'n/a'}"
            )
        lines.extend(["", "## Top Watch Only"])
        for item in report["top_watch_only"][:15]:
            lines.append(
                f"- {item['source_name']} ({item.get('country')}) -> {item['final_reason']} | "
                f"best_detail={item.get('best_detail_url') or 'n/a'}"
            )
        return "\n".join(lines) + "\n"

    def _diversify_potential_hits(self, ranked: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
        selected: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in ranked:
            group = self._potential_hit_group_key(row)
            if group in seen:
                continue
            selected.append(row)
            seen.add(group)
            if len(selected) >= limit:
                break
        return selected

    def _potential_hit_group_key(self, row: dict[str, Any]) -> str:
        host = normalize_host(str(row.get("canonical_url") or "")) or "unknown"
        if host != "unknown":
            return host
        base_name = re.sub(r"\s+", " ", str(row.get("source_name") or "")).strip().lower()
        return base_name or "unknown"

    def _prime_hits_rows(self, results: list[AttemptResult]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for item in results:
            if not item.seller_ready_records_count:
                continue
            rows.append(
                {
                    "source_key": item.source_key,
                    "source_name": item.source_name,
                    "family": item.family,
                    "country": item.country,
                    "canonical_url": item.canonical_url,
                    "attempt_status": item.attempt_status,
                    "extracted_docs_count": item.extracted_docs_count,
                    "retained_records_count": item.retained_records_count,
                    "seller_ready_records_count": item.seller_ready_records_count,
                    "lanes_detected": item.lanes_detected,
                    "matched_positive_terms": item.matched_positive_terms,
                    "english_sufficiency_score": item.english_sufficiency_score,
                    "next_action": item.next_action,
                }
            )
        rows.sort(key=lambda row: (-row["seller_ready_records_count"], -row["retained_records_count"], row["source_name"]))
        return rows

    def _potential_hit_candidates(self, results: list[AttemptResult]) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        candidate_id = 0
        for item in results:
            if item.attempt_status != "success_with_docs":
                continue
            if item.extracted_docs_count <= 0 or item.seller_ready_records_count > 0:
                continue
            sample_text = self._read_sample_text(item.response_sample_path)
            if not sample_text.strip():
                continue
            title = self._extract_title(sample_text, item.content_type) or item.source_name
            lowered = " ".join(part for part in [title, sample_text] if part).lower()
            soft_anchor_terms = self._matching_terms(lowered, POTENTIAL_PRODUCT_HINTS)
            commercial_hint_terms = self._matching_terms(lowered, POTENTIAL_COMMERCIAL_HINTS)
            procurement_terms = self._matching_terms(lowered, PROCUREMENT_HINTS)
            service_terms = self._matching_terms(lowered, SERVICE_HINTS)
            preposition_terms = self._matching_terms(lowered, PREPOSITION_HINTS)
            award_terms = self._matching_terms(lowered, AWARD_HINTS)
            trigger_terms = self._matching_terms(lowered, TRIGGER_HINTS)
            score, reasons, blockers = self._score_potential_hit(
                item=item,
                soft_anchor_terms=soft_anchor_terms,
                commercial_hint_terms=commercial_hint_terms,
                procurement_terms=procurement_terms,
                service_terms=service_terms,
                preposition_terms=preposition_terms,
                award_terms=award_terms,
                trigger_terms=trigger_terms,
            )
            if score <= 0:
                continue
            candidate_id += 1
            snippet = re.sub(r"\s+", " ", BeautifulSoup(sample_text, "html.parser").get_text(" ", strip=True))[:1000]
            candidates.append(
                {
                    "candidate_id": f"candidate-{candidate_id:04d}",
                    "source_key": item.source_key,
                    "source_name": item.source_name,
                    "family": item.family,
                    "country": item.country,
                    "canonical_url": item.canonical_url,
                    "page_title": title,
                    "attempt_status": item.attempt_status,
                    "extracted_docs_count": item.extracted_docs_count,
                    "english_sufficiency_score": item.english_sufficiency_score,
                    "authenticity_class": item.authenticity_class,
                    "canonical_allowed": item.canonical_allowed,
                    "lanes_detected": item.lanes_detected,
                    "matched_positive_terms": item.matched_positive_terms,
                    "matched_negative_terms": item.matched_negative_terms,
                    "soft_anchor_terms": soft_anchor_terms,
                    "commercial_hint_terms": commercial_hint_terms,
                    "procurement_terms": procurement_terms,
                    "service_terms": service_terms,
                    "pre_position_terms": preposition_terms,
                    "award_terms": award_terms,
                    "trigger_terms": trigger_terms,
                    "next_action": item.next_action,
                    "sample_text_excerpt": snippet,
                    "heuristic_score": round(score, 2),
                    "why_promising": reasons,
                    "seller_ready_blockers": blockers,
                }
            )
        return candidates

    def _score_potential_hit(
        self,
        *,
        item: AttemptResult,
        soft_anchor_terms: list[str],
        commercial_hint_terms: list[str],
        procurement_terms: list[str],
        service_terms: list[str],
        preposition_terms: list[str],
        award_terms: list[str],
        trigger_terms: list[str],
    ) -> tuple[float, list[str], list[str]]:
        score = 0.0
        reasons: list[str] = []
        blockers: list[str] = []

        score += min(item.extracted_docs_count, 25) * 0.8
        if item.authenticity_class == "official_public":
            score += 14
            reasons.append("official public source")
        elif item.authenticity_class == "third_party_mirror":
            score += 4
        else:
            score += 2
            blockers.append("source authenticity is not confirmed official_public")

        if item.canonical_allowed:
            score += 6
        else:
            blockers.append("surface is not canonical-allowed")

        if item.family == "official_national_portal":
            score += 10
            reasons.append("national procurement portal")
        elif item.family == "supranational_procurement":
            score += 8
            reasons.append("supranational procurement source")
        elif item.family == "ocds_registry_publisher":
            score += 4
        elif item.family == "hosted_procurement_instance":
            score += 3

        if item.matched_positive_terms:
            score += 28 + len(item.matched_positive_terms) * 6
            reasons.append("explicit Microsoft/D365 anchor present")
        elif soft_anchor_terms:
            score += 18 + len(soft_anchor_terms) * 4
            reasons.append("adjacent Microsoft/business application hint present")
            blockers.append("strict D365 anchor did not fire")
        else:
            blockers.append("strict and adjacent Microsoft/D365 anchors are weak or absent")

        if procurement_terms:
            score += 14
            reasons.append("procurement language present")
        if service_terms:
            score += 10
            reasons.append("services or implementation language present")
        if commercial_hint_terms:
            score += 8
            reasons.append("commercial transformation signal present")
        if preposition_terms:
            score += 8
            reasons.append("pre-positioning language present")
        if award_terms:
            score += 4
        if trigger_terms:
            score += 6

        if "bid_now" in item.lanes_detected:
            score += 10
        if "pre_position" in item.lanes_detected:
            score += 8
        if "framework_vehicle" in item.lanes_detected:
            score += 6
        if "award_watch" in item.lanes_detected:
            score += 4
        if "install_base_trigger" in item.lanes_detected:
            score += 5

        if item.next_action == "retain_for_research":
            score += 8
        elif item.next_action == "keep_as_near_miss":
            score += 6

        if item.english_sufficiency_score >= 0.18:
            score += 8
            reasons.append("seller-usable English likely")
        elif item.english_sufficiency_score >= 0.1:
            score += 3
            blockers.append("English is below seller-ready threshold")
        else:
            score -= 6
            blockers.append("English sufficiency is weak")

        if item.matched_negative_terms:
            penalty = min(18, len(item.matched_negative_terms) * 8)
            score -= penalty
            blockers.append("negative competitor or false-friend terms present")

        if not procurement_terms and not service_terms and not trigger_terms and not preposition_terms:
            score -= 8
            blockers.append("commercial route-to-market evidence is weak")

        return max(score, 0.0), sorted(set(reasons)), sorted(set(blockers))

    def _ai_review_potential_hits(self, candidates: list[dict[str, Any]], *, enabled: bool) -> dict[str, Any]:
        if not enabled:
            return {"status": "disabled", "model": None, "reviewed_candidates": 0, "reviews": []}
        if not candidates:
            return {"status": "no_candidates", "model": None, "reviewed_candidates": 0, "reviews": []}
        if not self.settings.openai_api_key:
            return {"status": "not_configured", "model": None, "reviewed_candidates": 0, "reviews": []}
        model = self.settings.openai_review_model
        request_candidates = [
            {
                "candidate_id": row["candidate_id"],
                "source_name": row["source_name"],
                "family": row["family"],
                "country": row["country"],
                "canonical_url": row["canonical_url"],
                "page_title": row["page_title"],
                "lanes_detected": row["lanes_detected"],
                "matched_positive_terms": row["matched_positive_terms"],
                "matched_negative_terms": row["matched_negative_terms"],
                "soft_anchor_terms": row["soft_anchor_terms"],
                "commercial_hint_terms": row["commercial_hint_terms"],
                "english_sufficiency_score": row["english_sufficiency_score"],
                "heuristic_score": row["heuristic_score"],
                "seller_ready_blockers": row["seller_ready_blockers"],
                "sample_text_excerpt": row["sample_text_excerpt"][:1200],
            }
            for row in candidates
        ]
        payload = {
            "model": model,
            "input": [
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "Return JSON only. Review these procurement and buyer-intent candidates that failed a strict seller-ready "
                                "D365 gate. Keep seller_ready unchanged. Choose which candidates are the best potential hits for human review. "
                                "A potential hit can still be promising if the page looks commercially relevant but is missing explicit anchors, "
                                "has borderline English, or needs deeper extraction. Score each candidate from 0-100. Favor concrete Microsoft, "
                                "Dynamics, Business Central, Dataverse, Power Platform, CRM, ERP, implementation, migration, support, tender, "
                                "consultation, framework, or transformation signals. Penalize competitor terms, weak commercial context, or "
                                "obvious false positives."
                            ),
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": json.dumps({"candidates": request_candidates}, default=json_default)}],
                },
            ],
            "max_output_tokens": 3000,
            "text": {"format": {"type": "json_object"}},
        }
        headers = {
            "Authorization": f"Bearer {self.settings.openai_api_key}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=90) as client:
                response = client.post(f"{self.settings.openai_base_url.rstrip('/')}/responses", headers=headers, json=payload)
            response.raise_for_status()
            body = response.json()
            text = self._response_output_text(body)
            parsed = json.loads(text)
            reviews = parsed.get("reviews", []) if isinstance(parsed, dict) else []
            normalized: list[dict[str, Any]] = []
            for row in reviews:
                if not isinstance(row, dict) or "candidate_id" not in row:
                    continue
                normalized.append(
                    {
                        "candidate_id": row["candidate_id"],
                        "promising": bool(row.get("promising")),
                        "score": int(row.get("score") or 0),
                        "lane": row.get("lane"),
                        "rationale": row.get("rationale"),
                        "missing_evidence": row.get("missing_evidence") or [],
                        "seller_ready_blockers": row.get("seller_ready_blockers") or [],
                    }
                )
            return {
                "status": "completed",
                "model": model,
                "reviewed_candidates": len(normalized),
                "reviews": normalized,
            }
        except Exception as exc:
            return {
                "status": f"error:{type(exc).__name__}",
                "model": model,
                "reviewed_candidates": 0,
                "reviews": [],
                "error": str(exc),
            }

    def _free_onboarding_queue(self, results: list[AttemptResult]) -> list[dict[str, Any]]:
        queue: list[dict[str, Any]] = []
        policy = self.attempt_policies.get("free_onboarding", {})
        for item in results:
            if item.attempt_status not in {"blocked_auth_required_free", "blocked_auth_required_paid"}:
                continue
            source_token = item.source_name.lower()
            setup = None
            for key, value in policy.items():
                if key in source_token:
                    setup = value
                    break
            queue.append({"source_name": item.source_name, "source_key": item.source_key, "attempt_status": item.attempt_status, "canonical_url": item.canonical_url, "setup_url": setup.get("setup_url") if setup else None, "account_type": setup.get("account_type") if setup else None, "why_onboarding_helps": "This surface required account/API-based access during the lawful probe."})
        return queue

    def _official_domain_inventory(self, results: list[AttemptResult]) -> list[dict[str, Any]]:
        hosts: dict[str, dict[str, Any]] = {}
        for item in results:
            host = normalize_host(item.canonical_url) or "unknown"
            entry = hosts.setdefault(host, {"host": host, "classification": item.authenticity_class, "sources": 0, "successful": 0, "retained": 0, "seller_ready": 0})
            entry["sources"] += 1
            entry["successful"] += 1 if item.attempt_status.startswith("success_") else 0
            entry["retained"] += item.retained_records_count
            entry["seller_ready"] += item.seller_ready_records_count
        return sorted(hosts.values(), key=lambda row: (row["classification"], -row["sources"], row["host"]))

    def _evidence_manifest(self, results: list[AttemptResult]) -> dict[str, Any]:
        return {"generated_at": datetime.now(UTC).isoformat(), "sample_count": sum(1 for item in results if item.response_sample_path), "sample_paths": [item.response_sample_path for item in results if item.response_sample_path][:500]}

    def _source_universe_summary(self, surfaces: list[SourceSurface], family_breakdown: dict[str, int], country_breakdown: dict[str, int], dedupe_report: dict[str, Any], lineage: list[dict[str, Any]]) -> str:
        lines = ["# Source Universe Summary", "", f"- Total distinct source surfaces: {len(surfaces)}", f"- Duplicates removed: {dedupe_report['duplicates_removed']}", "", "## Family Breakdown"]
        for key, value in sorted(family_breakdown.items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"- {key}: {value}")
        lines.extend(["", "## Country Breakdown"])
        for key, value in sorted(country_breakdown.items(), key=lambda item: (-item[1], str(item[0])))[0:40]:
            lines.append(f"- {key}: {value}")
        lines.extend(["", "## Build Lineage"])
        for item in lineage:
            lines.append(f"- {item['seed']}: {item['count']}")
        return "\n".join(lines) + "\n"

    def _blocked_markdown(self, blocked: list[dict[str, Any]]) -> str:
        lines = ["# Blocked Sources Report", ""]
        for item in blocked[:200]:
            lines.append(f"- {item['source_name']} | {item['attempt_status']} | {item.get('canonical_url')} | {item.get('blocker_reason')}")
        return "\n".join(lines) + "\n"

    def _attempt_report_markdown(self, report: dict[str, Any]) -> str:
        lines = ["# Attempt All Sources Report", "", f"- Source universe total: {report['source_universe_total']}", f"- Attempted source surfaces: {report['attempted_source_surfaces']}", f"- Successful attempted sources: {report['successful_attempted_sources']}", f"- Sources returning docs: {report['sources_returning_docs']}", f"- Sources yielding retained D365 records: {report['sources_yielding_retained_d365_records']}", f"- Sources yielding seller-ready records: {report['sources_yielding_seller_ready_records']}", f"- Retained D365 records: {report['retained_d365_records']}", f"- Seller-ready total: {report['seller_ready_total']}", f"- Seller-ready bid-now total: {report['seller_ready_bid_now_total']}", f"- Seller-ready pre-position total: {report['seller_ready_pre_position_total']}", "", "## Attempt Status Counts"]
        for key, value in sorted(report["attempt_status_counts"].items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"- {key}: {value}")
        return "\n".join(lines) + "\n"

    def _onboarding_markdown(self, rows: list[dict[str, Any]]) -> str:
        lines = ["# Free Account or API Onboarding Queue", ""]
        for item in rows:
            lines.append(f"- {item['source_name']} | {item['account_type']} | {item['setup_url']}")
        return "\n".join(lines) + "\n"

    def _free_onboarding_guide(self, rows: list[dict[str, Any]]) -> str:
        lines = ["# Free Source Onboarding Guide", ""]
        if not rows:
            lines.append("- No free-account or API onboarding blockers were observed in this campaign.")
        for item in rows:
            lines.append(f"- {item['source_name']}: {item['why_onboarding_helps']} Setup: {item.get('setup_url') or 'n/a'}")
        return "\n".join(lines) + "\n"

    def _productionization_markdown(self, report: dict[str, Any]) -> str:
        lines = ["# Source Productionization Report", "", f"- Production-ready public no-auth sources: {report['production_ready_public_no_auth_sources']}", "", "## Top Non-Production-Ready Surfaces"]
        count = 0
        for item in report["rows"]:
            if item["production_ready"]:
                continue
            lines.append(f"- {item['source_name']} | {item['attempt_status']} | {item.get('blocker_reason')}")
            count += 1
            if count >= 20:
                break
        return "\n".join(lines) + "\n"

    def _prime_hits_markdown(self, report: dict[str, Any]) -> str:
        lines = ["# Prime Hits Report", "", f"- Prime hits total: {report['prime_hits_total']}", ""]
        for item in report["prime_hits"]:
            lines.append(
                f"- {item['source_name']} | lanes={','.join(item['lanes_detected']) or 'n/a'} | "
                f"docs={item['extracted_docs_count']} | positives={','.join(item['matched_positive_terms']) or 'n/a'} | "
                f"next_action={item['next_action']}"
            )
        return "\n".join(lines) + "\n"

    def _potential_hits_markdown(self, report: dict[str, Any]) -> str:
        lines = [
            "# Potential Hits Report",
            "",
            f"- Prime hits total: {report['prime_hits_total']}",
            f"- Docs-returning non-prime total: {report['docs_returning_non_prime_total']}",
            f"- Potential candidate pool total: {report['potential_candidate_pool_total']}",
            f"- Potential hits total: {report['potential_hits_total']}",
            f"- AI review status: {report['ai_review_status']}",
            "",
            "## Top Potential Hits",
        ]
        for item in report["top_potential_hits"]:
            ai_note = ""
            if item.get("ai_review"):
                ai_note = f" | ai_score={item.get('ai_score')} | ai_promising={item.get('ai_promising')}"
            lines.append(
                f"- {item['source_name']} | score={item['final_score']} | lanes={','.join(item['lanes_detected']) or 'n/a'} | "
                f"anchors={','.join(item['matched_positive_terms'] or item['soft_anchor_terms']) or 'n/a'} | "
                f"blockers={'; '.join(item['seller_ready_blockers']) or 'n/a'}{ai_note}"
            )
        return "\n".join(lines) + "\n"

    def _campaign_verdict_markdown(self, report: dict[str, Any]) -> str:
        lines = ["# Global Source Campaign Verdict", "", f"- Total source universe count: {report['total_source_universe_count']}", f"- Total attempted count: {report['total_attempted_count']}", f"- Total successful attempts: {report['total_successful_attempts']}", f"- Total blocked by CAPTCHA: {report['total_blocked_by_captcha']}", f"- Total blocked by robots: {report['total_blocked_by_robots']}", f"- Total blocked by terms or policy: {report['total_blocked_by_terms_or_policy']}", f"- Total blocked by free-account requirement: {report['total_blocked_by_free_account_requirement']}", f"- Total blocked by paid-account requirement: {report['total_blocked_by_paid_account_requirement']}", f"- Total parser failures: {report['total_parser_failures']}", f"- Total docs-returning sources: {report['total_docs_returning_sources']}", f"- Total retained-D365-yielding sources: {report['total_retained_d365_yielding_sources']}", f"- Total seller-ready-yielding sources: {report['total_seller_ready_yielding_sources']}", f"- Production-ready public no-auth sources: {report['production_ready_public_no_auth_sources']}", "", "## Top Blockers"]
        for key, value in report["exact_top_blockers"].items():
            lines.append(f"- {key}: {value}")
        return "\n".join(lines) + "\n"

    def _blocked_next_action(self, source_name: str, attempt_status: str) -> str:
        if attempt_status == "blocked_auth_required_free":
            return "queue_free_onboarding"
        if attempt_status == "blocked_auth_required_paid":
            return "document_paid_gate"
        if attempt_status == "blocked_robots":
            return "respect_robots_and_skip"
        if attempt_status == "blocked_captcha":
            return "classify_captcha_blocker"
        if attempt_status == "blocked_rate_limit":
            return "reduce_rate_and_retry_later"
        return "record_blocker_and_move_on"

    def _breakdown_by(self, surfaces: list[SourceSurface], field: str) -> dict[str, int]:
        counter: Counter[str] = Counter()
        for item in surfaces:
            value = getattr(item, field) or "unknown"
            counter[str(value)] += 1
        return dict(sorted(counter.items(), key=lambda pair: (-pair[1], pair[0])))

    def _read_registry(self) -> list[SourceSurface]:
        if not self.registry_path.exists():
            return []
        rows: list[SourceSurface] = []
        for line in self.registry_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(SourceSurface(**json.loads(line)))
        return rows

    def _write_registry(self, surfaces: list[SourceSurface]) -> None:
        self.registry_path.write_text("\n".join(json.dumps(asdict(item), default=json_default) for item in surfaces) + "\n", encoding="utf-8")

    def _source_key(self, family: str, name: str, country: str | None, url: str, surface_kind: str) -> str:
        host = normalize_host(url) or "unknown"
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        return f"{family}:{country or 'global'}:{host}:{surface_kind}:{slug[:80]}"

    def _normalize_url(self, url: str) -> str:
        parsed = urlparse(url)
        path = parsed.path.rstrip("/") or "/"
        return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{path}"

    def _safe_filename(self, value: str) -> str:
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")[:72] or "sample"
        digest = sha256_bytes(value.encode("utf-8"))[:12]
        return f"{slug}-{digest}"

    def _decode_body(self, body: bytes, content_type: str | None) -> str:
        for encoding in ("utf-8", "latin-1"):
            try:
                return body.decode(encoding, errors="ignore")
            except Exception:
                continue
        return ""

    def _read_sample_text(self, sample_path: str | None) -> str:
        if not sample_path:
            return ""
        path = Path(sample_path)
        if not path.is_absolute():
            path = self.repo_root / path
        if not path.exists():
            return ""
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            try:
                return path.read_bytes().decode("utf-8", errors="ignore")
            except Exception:
                return ""

    def _response_output_text(self, payload: dict[str, Any]) -> str:
        output = payload.get("output", [])
        for item in output:
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    text = content.get("text")
                    if isinstance(text, str):
                        return text
        return ""

    def _latest_attempt_directory(self) -> Path | None:
        candidates = sorted(
            [path for path in self.artifact_root.iterdir() if path.is_dir() and path.name.endswith("-attempts")],
            key=lambda path: path.name,
            reverse=True,
        )
        return candidates[0] if candidates else None

    def _sync_latest(self, target: Path) -> None:
        latest = self.artifact_root / "latest"
        if latest.exists() or latest.is_symlink():
            if latest.is_symlink() or latest.is_file():
                latest.unlink()
            else:
                for path in sorted(latest.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                    else:
                        path.rmdir()
                latest.rmdir()
        latest.mkdir(parents=True, exist_ok=True)
        for path in sorted(target.rglob("*")):
            relative = path.relative_to(target)
            dest = latest / relative
            if path.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(path.read_bytes())

    def _merge_latest_universe_artifacts(self, target: Path) -> None:
        candidates = sorted(
            [
                path
                for path in self.artifact_root.iterdir()
                if path.is_dir() and path.name != "latest" and "-attempts" not in path.name
            ],
            key=lambda path: path.name,
            reverse=True,
        )
        if not candidates:
            return
        universe_root = candidates[0]
        for filename in (
            "source_universe_full.json",
            "source_universe_full.csv",
            "source_universe_summary.md",
            "source_universe_family_breakdown.json",
            "source_universe_country_breakdown.json",
            "source_universe_dedupe_report.json",
            "source_universe_lineage.json",
        ):
            source = universe_root / filename
            if not source.exists():
                continue
            destination = target / filename
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read_bytes())

    def _write_json(self, path: Path, payload: Any) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, default=json_default), encoding="utf-8")
        return path

    def _write_jsonl(self, path: Path, rows: list[dict[str, Any]]) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(json.dumps(row, default=json_default) for row in rows) + "\n", encoding="utf-8")
        return path

    def _write_text(self, path: Path, payload: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
        return path

    def _write_csv(self, path: Path, rows: list[dict[str, Any]]) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not rows:
            path.write_text("", encoding="utf-8")
            return path
        fieldnames = sorted({key for row in rows for key in row.keys()})
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({key: json.dumps(value, default=json_default) if isinstance(value, (list, dict)) else value for key, value in row.items()})
        return path
