from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class KeywordBucket:
    name: str
    keywords: tuple[str, ...]


APP_FAMILIES: tuple[KeywordBucket, ...] = (
    KeywordBucket("Sales", ("dynamics 365 sales", "sales hub", "crm sales", "sales automation")),
    KeywordBucket(
        "Customer Service",
        ("dynamics 365 customer service", "customer service", "case management", "omnichannel"),
    ),
    KeywordBucket("Contact Center", ("contact center", "call center", "voice channel", "ccaas")),
    KeywordBucket("Field Service", ("field service", "dispatch", "work order", "mobile technician")),
    KeywordBucket(
        "Customer Insights",
        ("customer insights", "journeys", "customer data platform", "dataverse marketing"),
    ),
    KeywordBucket("Finance", ("dynamics 365 finance", "finance transformation", "record to report", "gl")),
    KeywordBucket(
        "Supply Chain Management",
        ("supply chain", "warehouse", "procurement transformation", "planning", "inventory"),
    ),
    KeywordBucket("Commerce", ("commerce", "point of sale", "retail operations", "ecommerce")),
    KeywordBucket("Project Operations", ("project operations", "psa", "project accounting")),
    KeywordBucket("Human Resources", ("human resources", "hr transformation", "hire to retire")),
    KeywordBucket("Business Central", ("business central", "navision", "dynamics nav", "bc implementation", "bc support")),
    KeywordBucket("Dataverse / Power Platform", ("dataverse", "power platform", "power automate", "power apps")),
    KeywordBucket("AI / Copilot", ("copilot studio", "microsoft copilot", "ai assistant")),
)

BUSINESS_PROCESSES: tuple[KeywordBucket, ...] = (
    KeywordBucket("Prospect to Quote", ("lead", "pipeline", "quote", "sales cycle")),
    KeywordBucket("Case to Resolution", ("ticket", "case", "service desk", "customer service")),
    KeywordBucket("Service to Deliver", ("work order", "dispatch", "field service", "maintenance")),
    KeywordBucket("Order to Cash", ("order to cash", "order management", "billing", "invoice")),
    KeywordBucket("Source to Pay", ("procure to pay", "p2p", "sourcing", "supplier")),
    KeywordBucket("Record to Report", ("general ledger", "consolidation", "financial reporting")),
    KeywordBucket("Hire to Retire", ("employee lifecycle", "recruitment", "payroll", "benefits")),
    KeywordBucket("Project to Profit", ("project accounting", "resource management", "timesheet")),
    KeywordBucket("Inventory to Deliver", ("warehouse", "inventory", "distribution", "logistics")),
    KeywordBucket("Administer to Operate", ("governance", "security", "administration", "alm")),
)

SERVICE_TYPES: tuple[KeywordBucket, ...] = (
    KeywordBucket("Advisory", ("assessment", "roadmap", "strategy", "discovery", "workshop")),
    KeywordBucket("Implementation", ("implementation", "deployment", "rollout", "go-live", "modernize")),
    KeywordBucket("Integration", ("integration", "interface", "api", "middleware", "migration")),
    KeywordBucket("Development", ("customization", "development", "plugin", "extension", "build", "enhancement")),
    KeywordBucket("Testing", ("sit", "uat", "testing", "quality assurance", "regression")),
    KeywordBucket("Hypercare", ("hypercare", "cutover", "stabilization", "rescue")),
    KeywordBucket("Managed Services", ("managed service", "support", "maintenance", "ams", "run service", "managed support")),
    KeywordBucket("AI / Copilot", ("copilot studio", "microsoft copilot", "automation")),
)

HIGH_SIGNAL_TERMS: tuple[str, ...] = (
    "dynamics 365",
    "microsoft dynamics",
    "dynamics crm",
    "business central",
    "dataverse",
    "power platform",
    "power automate",
    "power apps",
    "copilot studio",
)

PROCUREMENT_TERMS: tuple[str, ...] = (
    "rfp",
    "tender",
    "itt",
    "itq",
    "procurement",
    "solicitation",
    "request for proposal",
    "request for information",
    "sources sought",
    "managed services",
    "support services",
)

QUERY_PACK_TERMS: tuple[str, ...] = (
    '"Dynamics 365"',
    '"Microsoft Dynamics"',
    '"Business Central"',
    "Dataverse",
    '"Power Platform"',
    '"Power Apps"',
    '"Dynamics 365 Finance"',
    '"Dynamics 365 Customer Service"',
    '"Dynamics 365 Field Service"',
    '"Copilot Studio"',
    '"field service"',
    '"customer service"',
    '"contact center"',
)

COUNTRY_TO_REGION: dict[str, str] = {
    "GB": "UK",
    "UK": "UK",
    "US": "North America",
    "USA": "North America",
    "IE": "Europe",
    "AU": "ANZ",
    "NZ": "ANZ",
    "DE": "Europe",
    "FR": "Europe",
    "ES": "Europe",
    "NL": "Europe",
}
