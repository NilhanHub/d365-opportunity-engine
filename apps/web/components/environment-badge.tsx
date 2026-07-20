"use client";

import { useEffect, useMemo, useState } from "react";
import { Badge, Text } from "@fluentui/react-components";
import { apiBase } from "@/lib/api";

type StatusPayload = {
  data_mode?: "LIVE" | "DEMO" | "MIXED";
  demo_mode?: boolean;
  live_records?: number;
  demo_records?: number;
  last_live_refresh?: string | null;
};

const badgeColor: Record<string, "success" | "danger" | "warning" | "informative"> = {
  LIVE: "success",
  DEMO: "danger",
  MIXED: "warning"
};

export function EnvironmentBadge() {
  const [status, setStatus] = useState<StatusPayload | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch(`${apiBase}/api/status`, {
      cache: "no-store",
      headers: { Accept: "application/json" }
    })
      .then((response) => response.json())
      .then((payload: StatusPayload) => {
        if (!cancelled) {
          setStatus(payload);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setStatus({ data_mode: "LIVE", demo_mode: false, live_records: 0, demo_records: 0 });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const mode = status?.data_mode ?? "LIVE";
  const detail = useMemo(() => {
    if (!status) {
      return "Checking data mode";
    }
    return `Live ${status.live_records ?? 0}  Demo ${status.demo_records ?? 0}`;
  }, [status]);

  return (
    <div className="environment-badge">
      <Badge appearance="filled" color={badgeColor[mode] ?? "informative"}>
        {mode}
      </Badge>
      <Text size={200} className="muted">
        {detail}
      </Text>
    </div>
  );
}
