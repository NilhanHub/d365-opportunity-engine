import { ActionButton } from "@/components/action-button";
import { CandidateReviewList } from "@/components/candidate-review-list";
import { DataGridTable } from "@/components/data-grid-table";
import { PageHeader } from "@/components/page-header";
import { Panel } from "@/components/panel";
import { ApiRecord, fetchJson } from "@/lib/api";

export default async function DiscoveryPage() {
  const candidates = await fetchJson<ApiRecord>("/api/discovery/candidates?limit=200");
  const rows = candidates.items ?? [];

  return (
    <>
      <PageHeader
        title="Discovery & Candidate Sources"
        subtitle="New source candidates, provenance, review status, and enablement pipeline."
        actions={<ActionButton label="Run Discovery" path="/api/actions/discover-sources" body={{ limit: 25 }} />}
      />
      <section className="split-grid">
        <Panel title="Review Queue" description={`${candidates.total ?? rows.length} discovered candidate sources.`}>
          <DataGridTable
            rows={rows}
            columns={[
              { key: "candidate_name", label: "Candidate" },
              { key: "country", label: "Country" },
              { key: "acquisition_method", label: "Method" },
              { key: "portal_fingerprint", label: "Fingerprint" },
              { key: "review_status", label: "Review", type: "status" },
              { key: "forthcoming_state", label: "Forthcoming", type: "status" },
              { key: "confidence", label: "Confidence", type: "number" },
              { key: "discovered_from", label: "Discovered From" }
            ]}
          />
        </Panel>
        <Panel title="Workflow" description="Discovered -> reviewed -> enabled -> yielding.">
          <DataGridTable
            rows={[
              { id: "a", stage: "Discovered", count: rows.length },
              { id: "b", stage: "Pending review", count: rows.filter((item: ApiRecord) => item.review_status === "pending_review").length },
              { id: "c", stage: "Queued enablement", count: rows.filter((item: ApiRecord) => item.forthcoming_state === "approved_pending_enable").length }
            ]}
            columns={[
              { key: "stage", label: "Stage" },
              { key: "count", label: "Count", type: "number" }
            ]}
          />
        </Panel>
      </section>
      <Panel title="Candidate Actions" description="Approve or reject discovered sources from the operator cockpit.">
        <CandidateReviewList items={(rows as Array<ApiRecord>).slice(0, 5).map((row) => ({
          id: String(row.id),
          candidate_name: String(row.candidate_name),
          country: row.country ? String(row.country) : undefined,
          confidence: row.confidence ? Number(row.confidence) : undefined
        }))} />
      </Panel>
    </>
  );
}
