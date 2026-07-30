import { ReactNode } from "react";

import { CopyButton } from "./CopyButton";

export type DefinitionItem = {
  label: string;
  value: ReactNode;
  copyValue?: string | null;
};

export function DefinitionList({ items }: { items: DefinitionItem[] }) {
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-3 text-sm md:grid-cols-2">
      {items.map((item) => (
        <div key={item.label} className="border-b border-stone-200 pb-3">
          <dt className="text-xs font-medium uppercase text-stone-500">{item.label}</dt>
          <dd className="mt-1 flex min-w-0 items-start justify-between gap-2 text-stone-900">
            <span className="min-w-0 break-words">{item.value || "Not available"}</span>
            {item.copyValue ? <CopyButton value={item.copyValue} /> : null}
          </dd>
        </div>
      ))}
    </dl>
  );
}
