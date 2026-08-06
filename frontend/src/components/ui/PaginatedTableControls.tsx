import { pageTokens, paginationState, TABLE_PAGE_SIZES } from "../../utils/pagination";
import { Button } from "./Button";

type Props = {
  total: number;
  limit: number;
  offset: number;
  onPageChange: (page: number) => void;
  onPageSizeChange: (size: number) => void;
  itemLabel: string;
  isLoading?: boolean;
  disabled?: boolean;
  allowedPageSizes?: readonly number[];
  compact?: boolean;
};

export function PaginatedTableControls({ total, limit, offset, onPageChange, onPageSizeChange, itemLabel, isLoading = false, disabled = false, allowedPageSizes = TABLE_PAGE_SIZES, compact = false }: Props) {
  const state = paginationState(total, limit, offset);
  const pluralLabel = total === 1 ? itemLabel : pluralize(itemLabel);
  const unavailable = disabled || isLoading;
  return <nav aria-label={`${pluralize(itemLabel)} pagination`} className="flex flex-wrap items-center justify-between gap-3 text-sm text-stone-600">
    <span aria-atomic="true">{total ? `Showing ${state.firstVisibleItem}-${state.lastVisibleItem} of ${total.toLocaleString()} ${pluralLabel}` : `Showing 0 ${pluralLabel}`}{isLoading ? " (refreshing)" : ""}</span>
    <div className="flex flex-wrap items-center gap-2">
      <label className="flex items-center gap-2"><span className={compact ? "sr-only" : "hidden sm:inline"}>Rows</span><select aria-label={`${itemLabel} rows per page`} value={limit} disabled={unavailable} onChange={(event) => onPageSizeChange(Number(event.target.value))} className="rounded-md border border-stone-300 bg-white px-2 py-1 focus:outline-none focus:ring-2 focus:ring-neutral-900">{allowedPageSizes.map((size) => <option key={size} value={size}>{size}</option>)}</select></label>
      <Button type="button" className="hidden sm:inline-flex" disabled={unavailable || !state.canGoPrevious} onClick={() => onPageChange(1)}>First</Button>
      <Button type="button" disabled={unavailable || !state.canGoPrevious} onClick={() => onPageChange(state.currentPage - 1)}>Previous</Button>
      <div className="hidden items-center gap-1 md:flex">{pageTokens(state.totalPages, state.currentPage).map((token) => typeof token === "number" ? <button key={token} type="button" aria-label={token === state.currentPage ? `Page ${token}` : `Go to Page ${token}`} aria-current={token === state.currentPage ? "page" : undefined} disabled={unavailable || token === state.currentPage} onClick={() => onPageChange(token)} className={`min-h-9 min-w-9 rounded-md border px-2 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-neutral-900 ${token === state.currentPage ? "border-neutral-900 bg-neutral-900 text-white disabled:opacity-100" : "border-stone-300 bg-white"}`}>{token}</button> : <span key={token} aria-hidden="true" className="px-1">...</span>)}</div>
      <span className="md:hidden" aria-current="page">Page {state.currentPage} of {state.totalPages}</span>
      <Button type="button" disabled={unavailable || !state.canGoNext} onClick={() => onPageChange(state.currentPage + 1)}>Next</Button>
      <Button type="button" className="hidden sm:inline-flex" disabled={unavailable || !state.canGoNext} onClick={() => onPageChange(state.totalPages)}>Last</Button>
    </div>
  </nav>;
}

function pluralize(label: string) {
  if (label.endsWith("y")) return `${label.slice(0, -1)}ies`;
  if (label.endsWith("s")) return label;
  return `${label}s`;
}
