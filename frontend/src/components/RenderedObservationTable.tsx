import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { listScanRenderedObservations } from "../api/client";
import { formatDate } from "../utils/format";
import { useUrlPagination } from "../utils/useUrlPagination";
import { renderOutcomeLabel } from "../utils/renderedOutcome";
import { Button } from "./ui/Button";
import { EmptyState } from "./ui/EmptyState";
import { ErrorBanner } from "./ui/ErrorBanner";
import { LoadingBlock } from "./ui/Loading";
import { PaginatedTableControls } from "./ui/PaginatedTableControls";
import { StatusBadge } from "./ui/StatusBadge";
import { SortableTableHeader, type SortDirection } from "./ui/SortableTableHeader";
import { inputClass } from "./ui/styles";
import type { RenderedObservationIndexList } from "../types/scans";

type RenderedObservationTableProps = {
  scanId?: string;
  renderMode: string;
  queryKey?: readonly unknown[];
  loadObservations?: (query: string) => Promise<RenderedObservationIndexList>;
  observationHref?: (observationId: number, snapshotId: number | null) => string;
  selectedTargetIds?: number[];
  onSelectedTargetIdsChange?: (targetIds: number[]) => void;
  selectedObservationIds?: number[];
  onSelectedObservationIdsChange?: (observationIds: number[]) => void;
  onLoadedItemsChange?: (items: RenderedObservationIndexList["items"]) => void;
  poll?: boolean;
};

export function RenderedObservationTable({ scanId, renderMode, queryKey, loadObservations, observationHref, selectedTargetIds = [], onSelectedTargetIdsChange, selectedObservationIds = [], onSelectedObservationIdsChange, onLoadedItemsChange, poll = false }: RenderedObservationTableProps) {
  const [searchParams, setSearchParams] = useSearchParams();
  const pagination = useUrlPagination({ prefix: "rendered" });
  const query = buildQuery(searchParams, pagination.limit, pagination.offset);
  const rendered = useQuery({ queryKey: [...(queryKey ?? ["scan-rendered-observations", scanId]), query], queryFn: () => loadObservations ? loadObservations(query) : listScanRenderedObservations(scanId ?? "", query), placeholderData: (previous) => previous, refetchInterval: poll ? 1500 : false });
  useEffect(() => pagination.ensureValid(rendered.data?.total), [pagination, rendered.data?.total]);
  useEffect(() => { if (rendered.data) onLoadedItemsChange?.(rendered.data.items); }, [onLoadedItemsChange, rendered.data]);
  const controls = <PaginatedTableControls total={rendered.data?.total ?? 0} limit={pagination.limit} offset={pagination.offset} onPageChange={pagination.setPage} onPageSizeChange={pagination.setPageSize} itemLabel="rendered capture" isLoading={rendered.isFetching && !rendered.isLoading} />;
  if (rendered.error) return <ErrorBanner error={rendered.error} title="Could not load rendered captures" />;
  return <div className="space-y-4">
    {rendered.data?.summary ? <RenderedOutcomeSummary summary={rendered.data.summary} /> : null}
    <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm"><div className="grid grid-cols-1 gap-3 md:grid-cols-3 xl:grid-cols-6">
      <input aria-label="Search rendered captures" value={searchParams.get("search") ?? ""} onChange={(event) => setParam(setSearchParams, "search", event.target.value)} placeholder="Search URL or title" className={`${inputClass()} xl:col-span-2`} />
      <select aria-label="Rendered capture state" value={searchParams.get("render_state") ?? ""} onChange={(event) => setParam(setSearchParams, "render_state", event.target.value)} className={inputClass()}><option value="">All capture states</option>{["completed", "completed_with_warnings", "failed", "skipped", "cancelled", "interrupted"].map((state) => <option key={state} value={state}>{state.replace(/_/g, " ")}</option>)}</select>
      <input aria-label="Browser navigation status" type="number" value={searchParams.get("navigation_status") ?? ""} onChange={(event) => setParam(setSearchParams, "navigation_status", event.target.value)} placeholder="Navigation status" className={inputClass()} />
      <select aria-label="Rendered warning filter" value={searchParams.get("has_warnings") ?? ""} onChange={(event) => setParam(setSearchParams, "has_warnings", event.target.value)} className={inputClass()}><option value="">Any warnings</option><option value="true">Has warnings</option><option value="false">No warnings</option></select>
      <select aria-label="Rendered error filter" value={searchParams.get("has_errors") ?? ""} onChange={(event) => setParam(setSearchParams, "has_errors", event.target.value)} className={inputClass()}><option value="">Any Page errors</option><option value="true">Has Page errors</option><option value="false">No Page errors</option></select>
      <select aria-label="Rendered screenshot filter" value={searchParams.get("has_screenshot") ?? ""} onChange={(event) => setParam(setSearchParams, "has_screenshot", event.target.value)} className={inputClass()}><option value="">Any screenshot state</option><option value="true">Has viewport screenshot</option><option value="false">No viewport screenshot</option></select>
      {onSelectedTargetIdsChange || onSelectedObservationIdsChange ? <fieldset className="md:col-span-3 xl:col-span-6"><legend className="mb-2 text-xs font-medium uppercase text-stone-500">Outcomes</legend><div className="flex flex-wrap gap-x-4 gap-y-2">{OUTCOMES.map(([value, label]) => <label key={value} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={searchParams.getAll("outcome").includes(value)} onChange={(event) => toggleMultiParam(setSearchParams, "outcome", value, event.target.checked)} className="size-4 rounded border-stone-300" />{label}</label>)}</div></fieldset> : null}
      <select aria-label="Sort rendered captures" value={searchParams.get("sort") ?? "capture_time"} onChange={(event) => setParam(setSearchParams, "sort", event.target.value)} className={inputClass()}><option value="capture_time">Capture time</option><option value="page_url">Page URL</option><option value="capture_state">Capture state</option><option value="duration">Duration</option><option value="navigation_status">Navigation status</option><option value="warning_count">Warnings</option><option value="page_error_count">Page errors</option></select>
      <select aria-label="Rendered sort direction" value={searchParams.get("direction") ?? "desc"} onChange={(event) => setParam(setSearchParams, "direction", event.target.value)} className={inputClass()}><option value="desc">Descending</option><option value="asc">Ascending</option></select>
      <Button type="button" variant="ghost" onClick={() => clearParams(setSearchParams)}>Clear filters</Button>
    </div></section>
    {controls}
    {rendered.isLoading ? <LoadingBlock label="Loading rendered captures..." /> : null}
    {!rendered.isLoading && !rendered.data?.items.length ? <RenderedEmptyState renderMode={renderMode} filtered={hasFilters(searchParams)} /> : null}
    {rendered.data?.items.length ? <div className="overflow-x-auto rounded-md border border-stone-200 bg-white shadow-sm"><table className="min-w-full text-left text-sm"><thead className="bg-stone-100 text-xs uppercase text-stone-500"><tr>{onSelectedTargetIdsChange || onSelectedObservationIdsChange ? <th className="w-10 px-3 py-2"><input type="checkbox" aria-label="Select all rendered observations on this page" checked={Boolean(rendered.data.items.length) && rendered.data.items.filter((item) => onSelectedTargetIdsChange ? item.render_run_target_id != null : item.render_run_target_id == null).every((item) => onSelectedTargetIdsChange ? selectedTargetIds.includes(item.render_run_target_id!) : selectedObservationIds.includes(item.id))} onChange={(event) => { if (onSelectedTargetIdsChange) { const ids = rendered.data.items.flatMap((item) => item.render_run_target_id == null ? [] : [item.render_run_target_id]); onSelectedTargetIdsChange(event.target.checked ? [...new Set([...selectedTargetIds, ...ids])] : selectedTargetIds.filter((id) => !ids.includes(id))); } else if (onSelectedObservationIdsChange) { const ids = rendered.data.items.filter((item) => item.render_run_target_id == null).map((item) => item.id); onSelectedObservationIdsChange(event.target.checked ? [...new Set([...selectedObservationIds, ...ids])] : selectedObservationIds.filter((id) => !ids.includes(id))); } }} /></th> : null}{[["page_url", "Page"], ["capture_state", "Capture"], ["navigation_status", "Navigation"], ["duration", "Duration"], ["warning_count", "Warnings"], ["browser_evidence", "Browser evidence"], ["capture_time", "Captured"]].map(([column, label]) => <SortableTableHeader key={column} column={column} label={label} activeColumn={searchParams.get("sort")} direction={searchParams.get("direction") as SortDirection | null} onChange={(column, direction) => setRenderedSort(setSearchParams, column, direction)} defaultDirection={column === "capture_time" ? "desc" : "asc"} />)}</tr></thead><tbody>{rendered.data.items.map((item) => <tr key={item.id} className="border-t border-stone-100 align-top hover:bg-stone-50">
      {onSelectedTargetIdsChange || onSelectedObservationIdsChange ? <td className="px-3 py-2"><input type="checkbox" aria-label={`Select ${item.static_final_url ?? item.page_title ?? `observation ${item.id}`}`} disabled={onSelectedTargetIdsChange ? item.render_run_target_id == null : item.render_run_target_id != null} checked={onSelectedTargetIdsChange ? item.render_run_target_id != null && selectedTargetIds.includes(item.render_run_target_id) : selectedObservationIds.includes(item.id)} onChange={(event) => { if (onSelectedTargetIdsChange && item.render_run_target_id != null) onSelectedTargetIdsChange(event.target.checked ? [...selectedTargetIds, item.render_run_target_id] : selectedTargetIds.filter((id) => id !== item.render_run_target_id)); else if (onSelectedObservationIdsChange && item.render_run_target_id == null) onSelectedObservationIdsChange(event.target.checked ? [...selectedObservationIds, item.id] : selectedObservationIds.filter((id) => id !== item.id)); }} /></td> : null}
      <td className="max-w-xl px-3 py-2"><Link to={observationHref ? observationHref(item.id, item.snapshot_id) : `/scans/${scanId}/pages/${item.snapshot_id}?tab=rendered`} className="block truncate underline" aria-label={`Open rendered evidence for ${item.static_final_url ?? item.page_title ?? `observation ${item.id}`}`}>{item.page_title ?? "Untitled Page"}</Link><span className="block truncate font-mono text-xs text-stone-500">{item.static_final_url}</span></td>
      <td className="px-3 py-2"><StatusBadge status={item.capture_state} label={renderOutcomeLabel(item)} />{item.error_message ? <span className="mt-1 block max-w-xs text-xs text-stone-500">{item.error_message}</span> : null}</td><td className="px-3 py-2">{item.navigation_http_status == null ? "Not attempted" : `HTTP ${item.navigation_http_status}`}</td><td className="px-3 py-2">{item.duration_ms == null ? "Not available" : `${item.duration_ms} ms`}</td>
      <td className="px-3 py-2">{item.warning_count}<span className="block text-xs text-stone-500">{item.page_error_count} Page errors</span></td>
      <td className="px-3 py-2 text-xs">{[item.has_viewport_screenshot ? "Viewport" : "", item.has_full_page_screenshot ? "Full page" : "", item.has_rendered_dom ? "DOM" : ""].filter(Boolean).join(", ") || "No artifacts"}<span className="block text-stone-500">{item.blocked_request_count} blocked, {item.console_message_count} console</span></td>
      <td className="whitespace-nowrap px-3 py-2">{formatDate(item.finished_at)}</td>
    </tr>)}</tbody></table></div> : null}
    {controls}
  </div>;
}

function RenderedOutcomeSummary({ summary }: { summary: RenderedObservationIndexList["summary"] }) {
  const throttled = summary.rate_limited + summary.skipped_after_throttling;
  return <>
    {throttled ? <div className="rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-950" role="alert"><span className="font-medium">Browser rendering was rate limited.</span> HTTP error responses did not receive normal Page artifacts.{summary.skipped_after_throttling ? ` ${summary.skipped_after_throttling} Pages were not attempted after host throttling.` : ""}</div> : null}
    <section aria-label="Rendered outcome summary" className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
      <SummaryMetric label="Successful renders" value={summary.successful_renders} />
      <SummaryMetric label="No-content responses" value={summary.no_content_responses} />
      <SummaryMetric label="HTTP redirects" value={summary.redirect_responses} />
      <SummaryMetric label="HTTP errors (not 429)" value={summary.http_error_responses} />
      <SummaryMetric label="Rate limited" value={summary.rate_limited} />
      <SummaryMetric label="Skipped after throttling" value={summary.skipped_after_throttling} />
      <SummaryMetric label="Technical failures" value={summary.technical_failures} />
      <SummaryMetric label="Artifacts retained" value={summary.artifacts_retained} />
    </section>
  </>;
}

function SummaryMetric({ label, value }: { label: string; value: number }) {
  return <div className="border-l-2 border-stone-300 px-3 py-1"><div className="text-xs font-medium uppercase text-stone-500">{label}</div><div className="mt-1 text-xl font-semibold text-stone-900">{value}</div></div>;
}

function RenderedEmptyState({ renderMode, filtered }: { renderMode: string; filtered: boolean }) {
  if (filtered) return <EmptyState title="No rendered captures match" message="Clear filters or broaden the rendered evidence search." />;
  if (renderMode === "none") return <EmptyState title="Rendering was disabled" message="Browser rendering was not requested for this Scan." />;
  return <EmptyState title="No rendered captures" message="No eligible HTML Pages completed browser capture. Failed, skipped, or interrupted attempts will appear here when recorded." />;
}
const OUTCOMES = [["successful", "Successful"], ["no_content", "No content"], ["redirect", "HTTP redirect"], ["http_error", "HTTP error"], ["rate_limited", "Rate limited"], ["not_attempted", "Not attempted"], ["technical_failure", "Technical failure"]] as const;
function buildQuery(params: URLSearchParams, limit: number, offset: number) { const query = new URLSearchParams(); const mapping: Array<[string, string]> = [["render_state", "capture_state"], ["has_errors", "has_page_errors"], ["has_screenshot", "has_viewport_screenshot"]]; for (const key of ["search", "navigation_status", "has_warnings", "sort", "direction"]) { const value = params.get(key); if (value) query.set(key, value); } for (const value of params.getAll("outcome")) query.append("outcome", value); for (const [from, to] of mapping) { const value = params.get(from); if (value) query.set(to, value); } query.set("limit", String(limit)); query.set("offset", String(offset)); return `?${query.toString()}`; }
function setParam(setSearchParams: ReturnType<typeof useSearchParams>[1], key: string, value: string) { setSearchParams((current) => { const next = new URLSearchParams(current); if (value) next.set(key, value); else next.delete(key); next.delete("rendered_offset"); return next; }); }
function toggleMultiParam(setSearchParams: ReturnType<typeof useSearchParams>[1], key: string, value: string, checked: boolean) { setSearchParams((current) => { const next = new URLSearchParams(current); const values = new Set(next.getAll(key)); if (checked) values.add(value); else values.delete(value); next.delete(key); for (const item of values) next.append(key, item); next.delete("rendered_offset"); return next; }); }
function setRenderedSort(setSearchParams: ReturnType<typeof useSearchParams>[1], column: string | null, direction: SortDirection | null) { setSearchParams((current) => { const next = new URLSearchParams(current); if (column && direction) { next.set("sort", column); next.set("direction", direction); } else { next.delete("sort"); next.delete("direction"); } next.delete("rendered_offset"); return next; }); }
function clearParams(setSearchParams: ReturnType<typeof useSearchParams>[1]) { setSearchParams((current) => current.get("tab") === "rendered" ? new URLSearchParams({ tab: "rendered" }) : new URLSearchParams()); }
function hasFilters(params: URLSearchParams) { return ["search", "render_state", "navigation_status", "has_warnings", "has_errors", "has_screenshot", "outcome"].some((key) => params.has(key)); }
