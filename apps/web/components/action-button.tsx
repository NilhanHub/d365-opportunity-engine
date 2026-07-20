"use client";

import { useState } from "react";
import { Button, Spinner } from "@fluentui/react-components";
import { postJson } from "@/lib/api";

export function ActionButton({
  label,
  path,
  body
}: {
  label: string;
  path: string;
  body: Record<string, unknown>;
}) {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<string | null>(null);

  return (
    <div className="action-button-wrap">
      <Button
        appearance="secondary"
        disabled={loading}
        onClick={async () => {
          setLoading(true);
          setResult(null);
          try {
            await postJson(path, body);
            setResult("Queued");
          } catch (error) {
            setResult(error instanceof Error ? error.message : "Failed");
          } finally {
            setLoading(false);
          }
        }}
      >
        {loading ? <Spinner size="tiny" /> : null}
        {label}
      </Button>
      {result ? <span className="muted">{result}</span> : null}
    </div>
  );
}
