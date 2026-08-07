import { ArrowDown, ArrowUp } from "lucide-react";
import type { ThHTMLAttributes } from "react";

export type SortDirection = "asc" | "desc";

type SortableTableHeaderProps = Omit<ThHTMLAttributes<HTMLTableCellElement>, "onChange"> & {
  column: string;
  label: string;
  activeColumn: string | null;
  direction: SortDirection | null;
  onChange: (column: string | null, direction: SortDirection | null) => void;
  defaultDirection?: SortDirection;
};

export function SortableTableHeader({
  column,
  label,
  activeColumn,
  direction,
  onChange,
  defaultDirection = "asc",
  className = "",
  ...props
}: SortableTableHeaderProps) {
  const active = activeColumn === column;
  const setDirection = (nextDirection: SortDirection) => {
    onChange(
      active && direction === nextDirection ? null : column,
      active && direction === nextDirection ? null : nextDirection,
    );
  };

  return (
    <th
      {...props}
      scope="col"
      aria-sort={active ? (direction === "desc" ? "descending" : "ascending") : "none"}
      className={`whitespace-nowrap px-3 py-2 ${active ? "font-bold text-stone-950" : "font-medium"} ${className}`}
    >
      <span className="inline-flex items-center gap-1">
        <button
          type="button"
          className="rounded-sm text-left focus:outline-none focus:ring-2 focus:ring-neutral-900"
          onClick={() => onChange(active ? null : column, active ? null : defaultDirection)}
          title={active ? `Restore default ${label} ordering` : `Sort by ${label}`}
        >
          {label}
        </button>
        <span className="inline-flex" aria-label={`${label} sort direction`}>
          <button
            type="button"
            className={`rounded-sm p-0.5 focus:outline-none focus:ring-2 focus:ring-neutral-900 ${active && direction === "asc" ? "text-stone-950" : "text-stone-400 hover:text-stone-700"}`}
            onClick={() => setDirection("asc")}
            title={active && direction === "asc" ? "Restore default ordering" : `Sort ${label} ascending`}
            aria-label={active && direction === "asc" ? `Restore default ${label} ordering` : `Sort ${label} ascending`}
          >
            <ArrowUp aria-hidden="true" size={14} strokeWidth={2.25} />
          </button>
          <button
            type="button"
            className={`rounded-sm p-0.5 focus:outline-none focus:ring-2 focus:ring-neutral-900 ${active && direction === "desc" ? "text-stone-950" : "text-stone-400 hover:text-stone-700"}`}
            onClick={() => setDirection("desc")}
            title={active && direction === "desc" ? "Restore default ordering" : `Sort ${label} descending`}
            aria-label={active && direction === "desc" ? `Restore default ${label} ordering` : `Sort ${label} descending`}
          >
            <ArrowDown aria-hidden="true" size={14} strokeWidth={2.25} />
          </button>
        </span>
      </span>
    </th>
  );
}
