# Architecture

The system is a Python acquisition and classification engine with a Next.js internal operator UI.

Core layers:
- Source adapters and retrieval planning in `src/d365opps/pipeline.py`
- Lifecycle and pitchability truth in `src/d365opps/lifecycle.py` and `src/d365opps/pitchability.py`
- Read-model/API surfaces in `src/d365opps/ops.py` and `src/d365opps/api.py`
- Accountability and forensic bundles in `src/d365opps/verification.py`
- Oracle packaging in `src/d365opps/oracle_bundle.py`

Canonical truth flow:
1. Acquisition fetches documents and attachments.
2. Extraction emits evidence.
3. Retention keeps only D365-anchored or valid legacy-trigger records.
4. Commercial actionability derives current state and recommended action.
5. Seller handoff applies the strict seller-ready gate.
6. Verification bundles and accountability runs publish the result.
