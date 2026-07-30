import { CopyButton } from "./CopyButton";

export function UrlText({ value, secondary = false }: { value: string | null | undefined; secondary?: boolean }) {
  if (!value) return <span className="text-stone-500">Not available</span>;
  return (
    <span className={`inline-flex min-w-0 max-w-full items-center gap-1 ${secondary ? "text-stone-600" : "text-stone-900"}`}>
      <span title={value} className="min-w-0 truncate font-mono text-xs">
        {value}
      </span>
      <CopyButton value={value} />
    </span>
  );
}
