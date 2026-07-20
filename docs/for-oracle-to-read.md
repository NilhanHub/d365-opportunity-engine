# For Oracle to Read

## Current Objective
Run the 3000+/1400-source global lawful public-source campaign from this repo, keep canonical truth and admissibility intact, and prove the actual breadth, attempt coverage, and blocker mix from artifacts alone.

## Current Failure or Uncertainty
- This pass is the 3000+/1400-source global attempt campaign, not another bounded baseline.
- The main blocker is breadth and lawful attempt coverage, not missing accountability surfaces.
- The repo must now prove exactly how many public source surfaces were built, attempted, blocked, and yielding in the latest global campaign.
- Yield remains far below attempt breadth, so blocker proof by source family, country, and attempt outcome still matters.

## Exact Reproduction
1. Initialize the database with `d365-opps init-db`.
2. Seed sources with `d365-opps seed-sources`.
3. Run `d365-opps build-source-universe --target-size 3000`.
4. Run `d365-opps attempt-source-universe --concurrency 120`.
5. Run `d365-opps build-oracle-bundle`.
6. Run `d365-opps refresh-oracle-instructions` so this file points at the latest source-campaign outputs.

## Expected Behavior
- Canonical latest pointers (`artifacts/runs/latest`, `artifacts/verification/latest`, and `artifacts/oracle/d365-opps-oracle-latest.zip`) only advance from an admissible official-public live run.
- The latest source campaign builds and attempts a genuinely broad public source universe, not a narrow bounded subset.
- Campaign artifacts must show exact family, country, and blocker distributions for every attempted surface.
- Canonical Oracle packaging must include the latest source-campaign artifacts alongside the live/public admissibility surfaces.

## Campaign Acceptance Thresholds
- `source_universe_total >= 3000`.
- `attempted_source_surfaces == source_universe_total`.
- Every attempted surface must emit an explicit outcome and blocker proof when it does not yield.
- Blocker categories must include at least CAPTCHA, robots, policy/terms, auth, network, rate-limit, parser failure, unsupported content, and invalid/removed source states when observed.

## Actual Behavior
- Latest admissibility verdict: `rejected`.
- Previous canonical/latest candidate rejection reasons: `none`.
- Harness schema status: `unknown`.
- Current retained D365 count: `unknown`; seller-ready bid-now: `unknown`; seller-ready pre-position: `unknown`; production-ready public no-auth sources: `unknown`.
- Latest source campaign universe: `unknown`; attempted: `unknown`; successful: `unknown`; docs-returning: `unknown`; production-ready public no-auth campaign sources: `unknown`.

## Relevant Paths
- `src/d365opps/pipeline.py`
- `src/d365opps/source_universe.py`
- `src/d365opps/retrieval.py`
- `src/d365opps/ops.py`
- `src/d365opps/diagnostics.py`
- `src/d365opps/verification.py`
- `src/d365opps/oracle_bundle.py`
- `src/d365opps/exporters.py`
- `src/d365opps/oracle_instructions.py`
- `src/d365opps/pitchability.py`
- `src/d365opps/metric_catalog.py`
- `src/d365opps/sources/public_portals.py`
- `src/d365opps/sources/global_sources.py`
- `src/d365opps/sources/find_a_tender.py`
- `src/d365opps/sources/ted.py`
- `src/d365opps/data/source_pack.json`
- `src/d365opps/data/retrieval_rules.json`
- `docs/metric-catalog.md`
- `docs/architecture.md`
- `docs/agent-handoff.md`
- `docs/verification.md`
- `docs/export-policy.md`
- `harness/agent-native-repo-harness-map.json`
- `docs/verification-operator-guide.md`
- `artifacts/source_campaign/latest`

## Required Artifacts
- Latest job run id: `7b8f44dd-52a8-4bac-9989-c3ee9ecd0965`
- Latest live-public verification bundle: `artifacts/verification/latest-live-public`
- Latest verification snapshot: `artifacts/verification/latest-live-public`
- Latest live-public accountability bundle: `artifacts/runs/latest-live-public`
- Latest accountability snapshot: `artifacts/runs/latest-live-public`
- Latest source campaign snapshot: `artifacts/source_campaign/latest`
- Latest rejected candidate path: ``
- Latest Oracle zip: `artifacts/oracle/d365-opps-oracle-latest.zip`
- Fresh `run_verdict.md`, `realness_report.md`, `canonical_bundle_admissibility_report.md`, `official_regression_truth_report.md`, `known_current_examples_report.md`, `source_productionization_report.md`, `source_gap_report.md`, `source_yield_matrix.json`, `lead_funnel_report.md`, `ui_truth_audit.md`, `repo_harness_compliance_report.md`, `harness_schema_validation_report.json`, `dead_weight_audit.md`, and `truth_consistency_report.json` from the latest live-public accountability run.
- Fresh source-campaign artifacts: `source_universe_full.json`, `attempt_all_sources_report.json`, `blocked_sources_report.json`, `free_source_onboarding_guide.md`, `source_productionization_report.json`, `source_yield_matrix.json`, `prime_hits_report.json`, `potential_hits_report.json`, `potential_hits_top12.json`, and `global_source_campaign_verdict.json`.
- Real screenshots under the latest live-public verification/accountability bundle; placeholders are disallowed for canonical latest.

## Exact Oracle Bundle Recipe
- Include: `README.md`, `pyproject.toml`, `compose*.yaml`.
- Include: `AGENTS.md`, `CODEOWNERS`, `.gitattributes`.
- Include: `docs/for-oracle-to-read.md`, `docs/operator-guide.md`, `docs/verification-operator-guide.md`, `docs/metric-catalog.md`, `docs/architecture.md`, `docs/agent-handoff.md`, `docs/verification.md`, `docs/export-policy.md`.
- Include: `harness/**`.
- Include: `src/d365opps/**`.
- Include: `tests/test_pitchability_truth.py`, `tests/test_verification.py`, and `tests/fixtures/**` when present.
- Include: `artifacts/verification/latest-live-public`.
- Include: `artifacts/runs/latest-live-public`.
- Include: `artifacts/source_campaign/latest`.
- Emit one canonical zip at `artifacts/oracle/d365-opps-oracle-latest.zip` with the actual selected files inside it.

## Admissibility Gates
- `run_kind` must be `live_public_baseline` or `live_public_expanded`.
- `evidence_class` must be `official_public`.
- No placeholder source names, placeholder domains, or fixture/demo records may appear in seller-ready outputs.
- Real screenshots are required; placeholder screenshots reject the candidate.
- Harness schema validation must pass with zero errors and zero template markers.
- Official regression truth must pass required positive and negative cases.
- Minimum live-public admissibility thresholds must pass, and the source-expansion release thresholds must either pass or emit exact blocker proof by source, lane, query family, lifecycle class, English sufficiency, and extraction completeness.

## Sanitization Rules
- Exclude `node_modules`, `.next`, browser caches, temp DB sidecars, `.pytest_cache`, Playwright caches, and recursive artifact junk.
- Exclude blobs and DB dumps unless explicitly requested.
- Redact tokens, API keys, Authorization/Cookie headers, and sensitive query parameters.

## Acceptance Evidence Required
- A fresh admissible live-public accountability run under `artifacts/runs/<timestamp>-accountability-<run-id>/` and synced to `artifacts/runs/latest-live-public/`.
- A fresh admissible live-public verification bundle under `artifacts/verification/<run-id-or-timestamp>/` and synced to `artifacts/verification/latest-live-public/`.
- `current_pipeline_truth_report`, `run_verdict`, `realness_report`, `canonical_bundle_admissibility_report`, `official_regression_truth_report`, `source_productionization_report`, `source_gap_report`, `source_yield_matrix`, `lead_funnel_report`, `ui_truth_audit`, and `repo_harness_compliance_report` all agree.
- `artifacts/oracle/d365-opps-oracle-latest.zip` is rebuilt only from the admissible live-public pointers.

## Known Suspects / Hypotheses
- The default `var/d365opps.db` can still hold synthetic or debug residue; canonical latest must never derive from it unless the run is classified/admitted correctly.
- Some official sources will still pass canaries but fail commercial thresholds within a bounded window; that must reject the canonical candidate rather than pretend success.
- Placeholder screenshots or non-schema-valid harness files must reject canonical latest even if the pipeline itself fetched real records.

## Recent Instrumentation Changes
- Added canonical run admissibility, source authenticity gating, official-domain inventory, realness reporting, and class-specific latest pointers.
- Added schema-valid harness validation and canonical Oracle build refusal when latest live-public evidence is inadmissible.
- Added UI truth audit and placeholder screenshot rejection for canonical bundles.

## Evidence Delta vs Prior Canonical Bundle
- This pass expands the source universe and attempt ledger materially beyond the earlier bounded campaign.
- The latest source campaign should show higher family-C official portal coverage, higher family-D hosted instance coverage, and a complete attempt ledger for every discovered surface.
- The evidence delta is now measured in source-universe breadth, attempted surfaces, successful probes, docs-returning sources, and blocker distribution, in addition to retained/seller-ready yield.

## Dead-Weight Deletions
- Remove stale wrapper zips, recursive artifact junk, placeholder screenshots in canonical paths, and dead fixture/debug debris from canonical surfaces.

## Harness Compliance Delta
- The harness map must validate against the supplied April 14, 2026 schema exactly; minimum-shape placeholder maps are no longer accepted.

_Generated: 2026-07-19T16:14:59.881668+00:00_
