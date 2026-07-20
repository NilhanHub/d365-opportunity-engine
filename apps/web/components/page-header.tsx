"use client";

import { Text } from "@fluentui/react-components";

export function PageHeader({
  title,
  subtitle,
  actions
}: {
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="page-header">
      <div>
        <Text as="h1" size={700} weight="semibold">
          {title}
        </Text>
        {subtitle ? (
          <Text size={200} className="muted">
            {subtitle}
          </Text>
        ) : null}
      </div>
      {actions ? <div className="page-header-actions">{actions}</div> : null}
    </div>
  );
}
