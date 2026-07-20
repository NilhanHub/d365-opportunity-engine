import { ActionButton } from "@/components/action-button";
import { LiveRunsPanel } from "@/components/live-runs-panel";
import { PageHeader } from "@/components/page-header";
import { ApiList, fetchJson, JsonRecord } from "@/lib/api";

export default async function RunsPage() {
  const runs = await fetchJson<ApiList<JsonRecord>>("/api/runs?limit=200");
  return (
    <>
      <PageHeader
        title="Crawl Runs + Job Monitor"
        subtitle="Refreshes, discovery runs, exports, and run-level fetch telemetry."
        actions={<ActionButton label="Refresh Enabled Sources" path="/api/actions/refresh" body={{ include_disabled: false }} />}
      />
      <LiveRunsPanel initialRuns={runs} />
    </>
  );
}
