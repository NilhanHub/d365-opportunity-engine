import { ActionButton } from "@/components/action-button";
import { DataGridTable } from "@/components/data-grid-table";
import { PageHeader } from "@/components/page-header";
import { Panel } from "@/components/panel";
import { ApiRecord, fetchJson } from "@/lib/api";

export default async function ExportsPage() {
  const exportsPayload = await fetchJson<ApiRecord>("/api/exports");
  return (
    <>
      <PageHeader
        title="Exports + Dataset Readiness"
        subtitle="Export history, generated files, row counts, and schema visibility."
        actions={<ActionButton label="Export Current Dataset" path="/api/actions/export" body={{ fmt: "both", filters: {} }} />}
      />
      <section className="split-grid">
        <Panel title="Export History" description="Latest generated export directories.">
          <DataGridTable
            rows={exportsPayload.items ?? []}
            columns={[
              { key: "generated_at", label: "Generated" },
              { key: "directory", label: "Directory" },
              { key: "files", label: "Files" },
              { key: "row_counts", label: "Row Counts" }
            ]}
          />
        </Panel>
        <Panel title="Schema Browser" description="Available exported field names.">
          <DataGridTable
            rows={(exportsPayload.schema_fields ?? []).map((field: string) => ({ id: field, field }))}
            columns={[{ key: "field", label: "Field" }]}
          />
        </Panel>
      </section>
    </>
  );
}
