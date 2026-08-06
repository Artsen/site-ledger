import type { PageCategory } from "../types/scans";
import { formatStatus } from "../utils/format";

const categoryStyles: Record<string, string> = {
  stone: "border-stone-300 bg-stone-100 text-stone-800",
  red: "border-red-300 bg-red-50 text-red-800",
  orange: "border-orange-300 bg-orange-50 text-orange-900",
  amber: "border-amber-300 bg-amber-50 text-amber-900",
  green: "border-green-300 bg-green-50 text-green-900",
  teal: "border-teal-300 bg-teal-50 text-teal-900",
  blue: "border-blue-300 bg-blue-50 text-blue-900",
  indigo: "border-indigo-300 bg-indigo-50 text-indigo-900",
  violet: "border-violet-300 bg-violet-50 text-violet-900",
  pink: "border-pink-300 bg-pink-50 text-pink-900"
};

export function PageCategoryBadges({ categories = [] }: { categories?: PageCategory[] }) {
  if (!categories.length) return <span className="text-sm text-stone-500">Uncategorized</span>;
  return (
    <span className="flex flex-wrap gap-1.5">
      {categories.map((category) => (
        <span key={category.id} className={`inline-flex items-center gap-1 rounded border px-2 py-0.5 text-xs font-medium ${categoryStyles[category.color_key] ?? categoryStyles.stone}`}>
          {category.name}
          {!category.is_active ? <span className="font-normal">(Archived)</span> : null}
        </span>
      ))}
    </span>
  );
}

export function WorkflowStatusBadge({ status }: { status: string }) {
  const style = status === "approved" ? "border-green-300 bg-green-50 text-green-900" : status === "needs_review" ? "border-amber-300 bg-amber-50 text-amber-900" : status === "deprecated" || status === "archived" ? "border-stone-300 bg-stone-100 text-stone-700" : "border-blue-300 bg-blue-50 text-blue-900";
  return <span className={`inline-flex rounded border px-2 py-0.5 text-xs font-medium ${style}`}>{formatStatus(status)}</span>;
}

export function LinkRoleBadge({ role, label, rule }: { role: string | null; label?: string; rule?: string | null }) {
  return (
    <span title={rule ? `Classified by ${formatStatus(rule)}` : "Recorded before link-role classification"} className="inline-flex rounded border border-teal-300 bg-teal-50 px-2 py-0.5 text-xs font-medium text-teal-900">
      {label ?? (role ? formatStatus(role) : "Unclassified legacy link")}
    </span>
  );
}
