# Operator Guide

## What this site is for

The web app is the internal cockpit for:

- source operations
- discovery review
- crawl health
- blocker diagnosis
- opportunity and signal intake
- evidence inspection
- export readiness

It sits on top of the existing pipeline and database. It does not replace the CLI or exporters.

## Live vs demo truth

The stack is now live-first.

- `compose.yaml` starts the live stack by default.
- `compose.demo.yaml` is the explicit demo override.
- The UI top bar shows a persistent `LIVE`, `DEMO`, or `MIXED` badge.
- `/api/status` and the overview screen expose live-record count, demo-record count, last live refresh, and last successful backfill.

Treat `MIXED` as an operational smell. If demo rows were intentionally loaded into the current database, purge them before doing serious analysis:

```powershell
d365-opps purge-demo
```

## How to read the main screens

## Executive Overview

Use this first.

- KPI cards show current intake and source fleet state.
- The dataset-mode panel tells you whether you are looking at live, demo, or mixed rows.
- The intake funnel separates raw documents, evidence, signals, opportunities, and approved/pursue-able records.
- The lane cards separate `formal_procurement`, `pre_positioning`, `direct_outreach`, and `install_base_trigger`.
- Best Leads shows the highest-value opportunities right now.
- Top Problems surfaces the issues actively reducing recall or data quality.
- Recall Sanity warns when healthy source coverage is inconsistent with downstream yield.
- Coverage Gaps highlights countries, source families, and candidate sources that need attention.

## Sources

This is the Source Command Center.

- `operational_state` answers whether the source is reachable and usable.
- `yield_state` answers whether it is actually producing useful output.
- `forthcoming_state` answers whether it is active, pending review, or intentionally disabled.
- `data_mode` tells you whether a row is live, demo, or mixed.
- `parser_implemented`, `backfilled`, `incrementally_syncing`, `yielding_real_records`, and `yielding_d365_records` show whether the source is merely configured or actually contributing real classified output.

Read those three together before deciding whether to fix, disable, or expand a source.

Use the source table to distinguish:

- healthy and productive
- healthy but low-yield
- throttled
- blocked
- credential-missing
- parser-drifting
- present in pack but not yet genuinely live

## Discovery

Use this when looking at newly found buyer or procurement surfaces.

- `confidence` is the discovery heuristic score.
- `discovered_from` and `discovery_provenance` show where it came from.
- `review_status` tracks whether it is still waiting for analyst review.

Approve only sources that have a lawful public path and a realistic English-accessible signal surface.

## Methods and Queries

Use these pages when the engine is noisy or recall looks thin.

- Look for query families with poor downstream yield.
- Compare acquisition method vs parsing mode vs produced opportunity counts.
- Check whether attachment-derived evidence is outperforming page text on a source family.
- Use query preview to verify that the rendered query matches the source capability. HTML portals should receive valid plain-keyword syntax, not fake fielded operators.
- Watch families such as `formal_procurement`, `pre_positioning`, `direct_outreach`, and `install_base_trigger` separately so poor performance in one lane does not hide useful yield in another.

## Runs

Use this when a source or export looks wrong.

- Start with status, duration, error count, and docs/evidence counts.
- The run monitor updates live from `/api/runs/stream`, so refresh/discovery/export jobs should appear without reloading the page.
- Then inspect fetch events, error JSON, and query executions inside the run detail.

There are now two ingestion modes:

- `bootstrap_backfill`
  - initial or periodic wide-history acquisition. Uses larger source-aware budgets and backfill windows.
- `incremental_sync`
  - daily or intraday refresh. Uses smaller moving windows and per-query/per-source watermarks where supported.

If the system looks suspiciously empty, check whether anyone only ran incremental sync against a mostly empty database. The overview now exposes the last successful backfill separately from the last live refresh.

## Issues

This is the blocker board.

Use it to decide:

- what to fix now
- what to slow down
- what to disable
- what to leave as known unsupported

## Opportunities and Signals

These are separate on purpose.

- `opportunities` are pursue-able formal or pre-positioning items.
- `signals` are outreach or install-base leads that still matter commercially, but are not open bids.
- Each record carries `data_mode`, lane metadata, query provenance, and source provenance so you can tell how it entered the system.

Every row should be traceable back to raw evidence.

## Coverage

Use this when planning expansion.

- Look for countries with low source count or low English yield.
- Look for enabled sources stuck in low-yield or noisy states.
- Use the blind-spot register to prioritize next source additions.
- Compare configured sources, live-enabled sources, healthy sources, and yielding D365 sources. Those numbers should not be treated as interchangeable.

## Exports

Use this before handing data downstream.

- Confirm row counts.
- Confirm schema visibility.
- Trigger a fresh export when needed.
- Make sure the export is filtered to live rows if demo mode was ever enabled in the same environment.

## Triggering jobs from the UI

Current operator actions exposed in the UI:

- refresh sources
- bootstrap backfill
- discover sources
- export dataset

The API also supports:

- approve discovered source
- reject discovered source
- reprocess document
- historical re-score
- purge demo rows

## Reading source health signals

Quick rule of thumb:

- `healthy` + `high_yield` is expansion-worthy
- `healthy` + `low_yield` usually means weak query fit or weak source fit
- `throttled` means you need gentler cadence or smaller request surfaces
- `blocked` or `robots_disallowed` means stop trying to brute-force it
- `parser_broken` means the source is still valuable but the adapter drifted
- `auth_required` means the source is only worth continuing if the access path is lawful and documented

Also read yield separately from availability:

- `high_yield`
  - worth widening budgets or adding more corroboration.
- `low_yield`
  - probably reachable, but weak query fit, weak English path, or low-value content.
- `zero_yield`
  - not automatically broken; check whether the source is stale, overly narrow, or recently changed.
- `noisy`
  - reachable, but producing generic ERP/CRM junk, competitor-system noise, or weak extraction.

## Recall sanity

Use the recall-sanity panel as a guardrail against false comfort.

Typical alerts include:

- too many healthy sources but too few qualified opportunities
- a source returning documents but almost no evidence
- evidence being created but almost no opportunities surviving scoring
- a whole query family yielding zero across multiple healthy sources
- sudden source regressions after parser or query changes

Those alerts do not replace analyst judgment, but they should stop you from assuming a tiny output means the market is genuinely quiet.

## Demo mode

Enable demo mode only when you explicitly want a seeded local dataset:

```powershell
docker compose -f compose.yaml -f compose.demo.yaml up --build
```

Use demo mode when:

- standing up a fresh local database
- reviewing the UI without waiting for a live crawl
- validating filters, detail pages, and dashboards

Do not use demo mode as the default operator stack. That was the old failure mode this upgrade removes.

## Known blind spots after this upgrade

- Some public procurement portals still expose very little without account or invitation flows.
- English-only export still suppresses some valid opportunities to audit-only handling.
- Attachment extraction quality still depends on public file quality.
- A few source families are still on improved HTML/detail fallback rather than fully source-native adapters, so extraction depth is uneven.
- Live run streaming is intentionally lightweight; the main UI still centers on explainable tables and recent fetch telemetry rather than a full trace explorer.
