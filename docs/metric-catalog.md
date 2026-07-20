# Metric Catalog

The canonical metric ontology is implemented in `src/d365opps/metric_catalog.py`.

Stages:
- acquisition: fetch and document volume only
- extraction: parsed/classified evidence volume
- retained_intelligence: retained D365 universe quality
- commercial_actionability: currently actionable commercial records
- seller_readiness: handoff-safe seller outputs

The UI, API, verification bundle, and agent verdicts must derive metrics from that catalog.
