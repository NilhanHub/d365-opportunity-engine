# D365 Opps Agents

This repository is the public-web Microsoft Dynamics 365 opportunity engine.

System-of-record surfaces:
- Runtime pipeline and acquisition logic: `src/d365opps/pipeline.py`
- Commercial truth and seller gating: `src/d365opps/pitchability.py`
- Verification and accountability artifacts: `src/d365opps/verification.py`
- Oracle handoff instructions and packaging: `docs/for-oracle-to-read.md`, `src/d365opps/oracle_bundle.py`

Canonical artifact surfaces:
- Latest accountability run: `artifacts/runs/latest/`
- Latest verification bundle: `artifacts/verification/latest/`
- Latest Oracle bundle: `artifacts/oracle/d365-opps-oracle-latest.zip`

Default operator rule:
- Use seller-ready exports and truth reports before raw acquisition counters.
