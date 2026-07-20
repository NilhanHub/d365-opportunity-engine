"use client";

import { Card, Text } from "@fluentui/react-components";

export function Panel({
  title,
  description,
  actions,
  children
}: {
  title: string;
  description?: string;
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <Card appearance="outline" className="panel">
      <div className="page-header">
        <div className="panel-header">
          <Text size={400} weight="semibold">
            {title}
          </Text>
          {description ? (
            <Text size={200} className="muted">
              {description}
            </Text>
          ) : null}
        </div>
        {actions ? <div className="page-header-actions">{actions}</div> : null}
      </div>
      {children}
    </Card>
  );
}
