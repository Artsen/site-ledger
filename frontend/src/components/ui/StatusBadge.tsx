import { formatStatus, statusTone } from "../../utils/format";

export function StatusBadge({ status, label }: { status: string | null | undefined; label?: string }) {
  const tone = statusTone(status);
  const classes = {
    neutral: "border-stone-300 bg-stone-100 text-stone-700",
    success: "border-emerald-300 bg-emerald-50 text-emerald-800",
    warning: "border-amber-300 bg-amber-50 text-amber-800",
    danger: "border-red-300 bg-red-50 text-red-800",
    info: "border-sky-300 bg-sky-50 text-sky-800"
  };
  return (
    <span className={`inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium ${classes[tone]}`}>
      {label ?? formatStatus(status)}
    </span>
  );
}
