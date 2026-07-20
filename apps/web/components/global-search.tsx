"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { Input } from "@fluentui/react-components";

export function GlobalSearch() {
  const [value, setValue] = useState("");
  const router = useRouter();

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!value.trim()) {
      router.push("/opportunities");
      return;
    }
    router.push(`/opportunities?keyword=${encodeURIComponent(value.trim())}`);
  }

  return (
    <form onSubmit={onSubmit}>
      <Input
        aria-label="Global opportunity search"
        value={value}
        onChange={(_, data) => setValue(data.value)}
        placeholder="Search buyers, leads, signals"
      />
    </form>
  );
}
