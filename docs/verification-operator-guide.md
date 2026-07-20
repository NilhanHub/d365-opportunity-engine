# Verification Operator Guide

## Core workflow

1. Open `/diagnostics`.
2. If the dashboard is empty or suspiciously low, inspect:
   - `dataset_diagnosis.json`
   - `ROOT_CAUSE_REPORT.md`
   - `source_health.json`
3. If a source looks healthy, verify it with:
   - `source_canaries.ndjson`
   - `fetch_events.ndjson`
   - `source_state_transitions.ndjson`
4. If a query family looks noisy or dead, inspect:
   - `query_executions.ndjson`
   - `pipeline_events.ndjson`
5. If a lead matters, trace it from:
   - overview KPI
   - opportunity row
   - evidence row
   - raw document/blob metadata

## Commands

```powershell
d365-opps doctor
d365-opps explain-zero
d365-opps verify-pack
d365-opps refresh-oracle-instructions
```

## Bundle location

- `artifacts/verification/latest/`
- `artifacts/verification/latest.zip`
- `artifacts/runs/latest/`
- `artifacts/runs/latest.zip`

Enable real screenshot capture by setting:

- `D365_OPPS_SCREENSHOT_CAPTURE_ENABLED=true`
- `D365_OPPS_WEB_BASE_URL=http://localhost:3000`

## What each file answers

- `status.json`: LIVE / DEMO / MIXED and generation metadata
- `source_inventory.json`: what sources exist and whether they are enabled
- `source_health.json`: current evidence-backed source state
- `source_readiness.json`: configured vs enabled vs blocked vs candidate mix
- `source_canaries.ndjson`: whether core public sources are actually reachable and parseable
- `query_executions.ndjson`: which queries were compiled, rendered, and executed
- `fetch_events.ndjson`: which URLs were contacted and with what result
- `pipeline_events.ndjson`: canonical forensic timeline
- `dataset_diagnosis.json`: ranked root causes when output is empty or implausibly low
- `ROOT_CAUSE_REPORT.md`: concise human-readable summary for reviewers
- `artifacts/runs/latest/pitchability_report.md`: whether there are any real pitchable leads
- `artifacts/runs/latest/truth_consistency_report.json`: whether KPIs, rollups, and source truth agree

## Redaction

Bundles show whether credentials are present and whether onboarding/connectivity succeeded, but secrets are redacted. Review `config.redacted.json` and `environment.redacted.json` instead of local env files.
