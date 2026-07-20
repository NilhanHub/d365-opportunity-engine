import { ActionButton } from "@/components/action-button";
import { DataGridTable } from "@/components/data-grid-table";
import { PageHeader } from "@/components/page-header";
import { Panel } from "@/components/panel";
import { ApiRecord, fetchJson } from "@/lib/api";

export default async function SettingsPage() {
  const sources = await fetchJson<ApiRecord>("/api/sources?limit=50");
  const savedViews = await fetchJson<ApiRecord[]>("/api/saved-views");

  return (
    <>
      <PageHeader title="Settings / Ops" subtitle="Low-friction operator controls, review toggles, and saved views." />
      <section className="split-grid">
        <Panel title="Operator Actions" description="Safe operator actions against the live API.">
          <div className="summary-pair">
            <ActionButton label="Refresh Sources" path="/api/actions/refresh" body={{ include_disabled: false }} />
            <ActionButton label="Discover Sources" path="/api/actions/discover-sources" body={{ limit: 20 }} />
            <ActionButton label="Export Dataset" path="/api/actions/export" body={{ fmt: "both", filters: {} }} />
          </div>
        </Panel>
        <Panel title="Saved Views" description="Reusable shared filters for operators and analysts.">
          <DataGridTable
            rows={savedViews}
            columns={[
              { key: "name", label: "Name" },
              { key: "route", label: "Route" },
              { key: "description", label: "Description" },
              { key: "density", label: "Density" }
            ]}
          />
        </Panel>
      </section>
      <Panel title="Quick Source Status" description="Top of the stack source controls and health snapshot.">
        <DataGridTable
          rows={(sources.items ?? []).slice(0, 12)}
          columns={[
            { key: "name", label: "Source" },
            { key: "enabled", label: "Enabled" },
            { key: "operational_state", label: "Operational", type: "status" },
            { key: "yield_state", label: "Yield", type: "status" },
            { key: "recommended_fix", label: "Recommended Fix" }
          ]}
        />
      </Panel>
    </>
  );
}
