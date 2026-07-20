import { DataGridTable } from "@/components/data-grid-table";
import { PageHeader } from "@/components/page-header";
import { Panel } from "@/components/panel";
import { ApiRecord, fetchJson } from "@/lib/api";

export default async function IssuesPage() {
  const issues = await fetchJson<ApiRecord>("/api/issues?limit=200");
  return (
    <>
      <PageHeader title="Source Issues / Blockers Console" subtitle="Normalized incidents showing what is blocking, throttling, drifting, or not worth fixing." />
      <Panel title="Active Issues" description={`${issues.total ?? issues.items?.length ?? 0} tracked source issues.`}>
        <DataGridTable
          rows={issues.items ?? []}
          columns={[
            { key: "issue_code", label: "Issue" },
            { key: "severity", label: "Severity", type: "status" },
            { key: "state", label: "State", type: "status" },
            { key: "frequency", label: "Frequency", type: "number" },
            { key: "example_status_code", label: "HTTP", type: "number" },
            { key: "impact_on_yield", label: "Impact" },
            { key: "recommended_remediation", label: "Recommended Remediation" }
          ]}
        />
      </Panel>
    </>
  );
}
