import { useState } from "react";

import { displayError } from "../../utils/errors";

export function ErrorBanner({ error, title = "Request failed" }: { error: unknown; title?: string }) {
  const [open, setOpen] = useState(false);
  const display = displayError(error);
  return (
    <div role="alert" className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900">
      <div className="font-medium">{title}</div>
      <div className="mt-1">{display.message}</div>
      {display.detail ? (
        <details className="mt-2" open={open} onToggle={(event) => setOpen(event.currentTarget.open)}>
          <summary className="cursor-pointer text-xs font-medium">Technical details</summary>
          <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap rounded border border-red-200 bg-white p-2 text-xs text-red-950">{display.detail}</pre>
        </details>
      ) : null}
    </div>
  );
}
