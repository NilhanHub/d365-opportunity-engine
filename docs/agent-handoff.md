# Agent Handoff

When handing this repo to another agent:

1. Read `docs/for-oracle-to-read.md`.
2. Inspect `artifacts/runs/latest/run_verdict.md`.
3. Use `artifacts/runs/latest/current_pipeline_truth_report.json` and `artifacts/runs/latest/cross_surface_truth_report.json` for counts.
4. Use `artifacts/runs/latest/source_gap_report.json` and `artifacts/runs/latest/source_yield_matrix.json` for source-level blockers.
5. Use `artifacts/runs/latest/seller_ready_bid_now_leads.csv` and `artifacts/runs/latest/seller_ready_pre_position_leads.csv` for sales-ready outputs.

Do not infer truth from screenshots alone.
