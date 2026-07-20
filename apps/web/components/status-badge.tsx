"use client";

import React from "react";
import { Badge } from "@fluentui/react-components";

function appearanceForStatus(value: string) {
  if (["healthy", "active", "approved", "bid_now"].includes(value)) {
    return "filled";
  }
  if (["degraded", "pending_review", "pre_position", "monitor"].includes(value)) {
    return "tint";
  }
  if (["throttled", "blocked", "auth_required", "parser_broken", "rejected", "reject"].includes(value)) {
    return "outline";
  }
  return "ghost";
}

function colorForStatus(value: string): "success" | "warning" | "danger" | "informative" | "important" | "subtle" {
  if (["healthy", "approved", "bid_now", "active"].includes(value)) {
    return "success";
  }
  if (["degraded", "throttled", "pending_review", "pre_position", "monitor"].includes(value)) {
    return "warning";
  }
  if (["blocked", "auth_required", "parser_broken", "rejected", "reject"].includes(value)) {
    return "danger";
  }
  if (["candidate", "enabled_not_yet_successful"].includes(value)) {
    return "informative";
  }
  return "subtle";
}

export function StatusBadge({ value }: { value: string | null | undefined }) {
  const normalized = value ?? "unknown";
  return (
    <Badge appearance={appearanceForStatus(normalized)} color={colorForStatus(normalized)}>
      {normalized.replaceAll("_", " ")}
    </Badge>
  );
}
