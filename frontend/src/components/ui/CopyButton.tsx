import { useState } from "react";

import { Button } from "./Button";

export function CopyButton({ value, label = "Copy" }: { value: string | null | undefined; label?: string }) {
  const [copied, setCopied] = useState(false);
  const disabled = !value;

  async function copy() {
    if (!value) return;
    await navigator.clipboard.writeText(value);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1400);
  }

  return (
    <Button type="button" variant="ghost" disabled={disabled} onClick={copy} aria-label={`${label}${copied ? " copied" : ""}`} className="px-2 py-1 text-xs">
      {copied ? "Copied" : label}
    </Button>
  );
}
