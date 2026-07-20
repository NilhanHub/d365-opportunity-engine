"use client";

import Link from "next/link";
import { Card, Text } from "@fluentui/react-components";

export function KpiCard({
  label,
  value,
  href,
  hint
}: {
  label: string;
  value: string | number;
  href?: string;
  hint?: string;
}) {
  const body = (
    <Card className="kpi-card" appearance="outline">
      <Text size={200} weight="medium">
        {label}
      </Text>
      <Text size={700} weight="semibold">
        {value}
      </Text>
      {hint ? (
        <Text size={200} className="muted">
          {hint}
        </Text>
      ) : null}
    </Card>
  );
  return href ? <Link href={href}>{body}</Link> : body;
}
