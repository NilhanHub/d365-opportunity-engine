import { DataGridTable } from "@/components/data-grid-table";
import { PageHeader } from "@/components/page-header";
import { Panel } from "@/components/panel";
import { ApiRecord, fetchJson } from "@/lib/api";

export default async function SignalsPage() {
  const signals = await fetchJson<ApiRecord>("/api/signals?limit=200");
  return (
    <>
      <PageHeader title="Signals" subtitle="Direct outreach and install-base triggers kept separate from bid-now opportunities." />
      <Panel title="Market Signals" description={`${signals.total ?? signals.items?.length ?? 0} signals in the current view.`}>
        <DataGridTable
          rows={signals.items ?? []}
          columns={[
            { key: "title", label: "Title" },
            { key: "data_mode", label: "Mode", type: "status" },
            { key: "signal_type", label: "Signal Type" },
            { key: "signal_lane", label: "Lane", type: "status" },
            { key: "recommended_action", label: "Action", type: "status" },
            { key: "retrieval_score", label: "Retrieval", type: "number" },
            { key: "trigger_strength", label: "Trigger", type: "number" },
            { key: "country", label: "Country" },
            { key: "created_at", label: "Created" }
          ]}
        />
      </Panel>
    </>
  );
}
