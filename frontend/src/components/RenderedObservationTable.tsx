import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { listScanRenderedObservations } from "../api/client";
import { formatDate } from "../utils/format";
import { useUrlPagination } from "../utils/useUrlPagination";
import { Button } from "./ui/Button";
import { EmptyState } from "./ui/EmptyState";
import { ErrorBanner } from "./ui/ErrorBanner";
import { LoadingBlock } from "./ui/Loading";
import { PaginatedTableControls } from "./ui/PaginatedTableControls";
import { StatusBadge } from "./ui/StatusBadge";
import { inputClass } from "./ui/styles";

export function RenderedObservationTable({ scanId, renderMode }: { scanId: string; renderMode: string }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const pagination = useUrlPagination({ prefix: "rendered" });
  const query = buildQuery(searchParams, pagination.limit, pagination.offset);
  const rendered = useQuery({ queryKey: ["scan-rendered-observations", scanId, query], queryFn: () => listScanRenderedObservations(scanId, query), placeholderData: (previous) => previous });
  useEffect(() => pagination.ensureValid(rendered.data?.total), [pagination, rendered.data?.total]);
  const controls = <PaginatedTableControls total={rendered.data?.total ?? 0} limit={pagination.limit} offset={pagination.offset} onPageChange={pagination.setPage} onPageSizeChange={pagination.setPageSize} itemLabel="rendered capture" isLoading={rendered.isFetching && !rendered.isLoading} />;
  if (rendered.error) return <ErrorBanner error={rendered.error} title="Could not load rendered captures" />;
  return <div className="space-y-4">
    <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm"><div className="grid grid-cols-1 gap-3 md:grid-cols-3 xl:grid-cols-6">
      <input aria-label="Search rendered captures" value={searchParams.get("search") ?? ""} onChange={(event) => setParam(setSearchParams, "search", event.target.value)} placeholder="Search URL or title" className={`${inputClass()} xl:col-span-2`} />
      <select aria-label="Rendered capture state" value={searchParams.get("render_state") ?? ""} onChange={(event) => setParam(setSearchParams, "render_state", event.target.value)} className={inputClass()}><option value="">All capture states</option>{["completed", "completed_with_warnings", "failed", "skipped", "cancelled", "interrupted"].map((state) => <option key={state} value={state}>{state.replace(/_/g, " ")}</option>)}</select>
      <input aria-label="Browser navigation status" type="number" value={searchParams.get("navigation_status") ?? ""} onChange={(event) => setParam(setSearchParams, "navigation_status", event.target.value)} placeholder="Navigation status" className={inputClass()} />
      <select aria-label="Rendered warning filter" value={searchParams.get("has_warnings") ?? ""} onChange={(event) => setParam(setSearchParams, "has_warnings", event.target.value)} className={inputClass()}><option value="">Any warnings</option><option value="true">Has warnings</option><option value="false">No warnings</option></select>
      <select aria-label="Rendered error filter" value={searchParams.get("has_errors") ?? ""} onChange={(event) => setParam(setSearchParams, "has_errors", event.target.value)} className={inputClass()}><option value="">Any Page errors</option><option value="true">Has Page errors</option><option value="false">No Page errors</option></select>
      <select aria-label="Rendered screenshot filter" value={searchParams.get("has_screenshot") ?? ""} onChange={(event) => setParam(setSearchParams, "has_screenshot", event.target.value)} className={inputClass()}><option value="">Any screenshot state</option><option value="true">Has viewport screenshot</option><option value="false">No viewport screenshot</option></select>
      <select aria-label="Sort rendered captures" value={searchParams.get("sort") ?? "capture_time"} onChange={(event) => setParam(setSearchParams, "sort", event.target.value)} className={inputClass()}><option value="capture_time">Capture time</option><option value="page_url">Page URL</option><option value="capture_state">Capture state</option><option value="duration">Duration</option><option value="navigation_status">Navigation status</option><option value="warning_count">Warnings</option><option value="page_error_count">Page errors</option></select>
      <select aria-label="Rendered sort direction" value={searchParams.get("direction") ?? "desc"} onChange={(event) => setParam(setSearchParams, "direction", event.target.value)} className={inputClass()}><option value="desc">Descending</option><option value="asc">Ascending</option></select>
      <Button type="button" variant="ghost" onClick={() => clearParams(setSearchParams)}>Clear filters</Button>
    </div></section>
    {controls}
    {rendered.isLoading ? <LoadingBlock label="Loading rendered captures..." /> : null}
    {!rendered.isLoading && !rendered.data?.items.length ? <RenderedEmptyState renderMode={renderMode} filtered={hasFilters(searchParams)} /> : null}
    {rendered.data?.items.length ? <div className="overflow-x-auto rounded-md border border-stone-200 bg-white shadow-sm"><table className="min-w-full text-left text-sm"><thead className="bg-stone-100 text-xs uppercase text-stone-500"><tr>{["Page", "Capture", "Navigation", "Duration", "Warnings", "Browser evidence", "Captured"].map((header) => <th key={header} scope="col" className="px-3 py-2 font-medium">{header}</th>)}</tr></thead><tbody>{rendered.data.items.map((item) => <tr key={item.id} className="border-t border-stone-100 align-top hover:bg-stone-50">
      <td className="max-w-xl px-3 py-2"><Link to={`/scans/${scanId}/pages/${item.snapshot_id}?tab=rendered`} className="block truncate underline" aria-label={`Open rendered evidence for ${item.static_final_url ?? item.page_title ?? `snapshot ${item.snapshot_id}`}`}>{item.page_title ?? "Untitled Page"}</Link><span className="block truncate font-mono text-xs text-stone-500">{item.static_final_url}</span></td>
      <td className="px-3 py-2"><StatusBadge status={item.capture_state} /></td><td className="px-3 py-2">{item.navigation_http_status ?? "Not available"}</td><td className="px-3 py-2">{item.duration_ms == null ? "Not available" : `${item.duration_ms} ms`}</td>
      <td className="px-3 py-2">{item.warning_count}<span className="block text-xs text-stone-500">{item.page_error_count} Page errors</span></td>
      <td className="px-3 py-2 text-xs">{[item.has_viewport_screenshot ? "Viewport" : "", item.has_full_page_screenshot ? "Full page" : "", item.has_rendered_dom ? "DOM" : ""].filter(Boolean).join(", ") || "No artifacts"}<span className="block text-stone-500">{item.blocked_request_count} blocked, {item.console_message_count} console</span></td>
      <td className="whitespace-nowrap px-3 py-2">{formatDate(item.finished_at)}</td>
    </tr>)}</tbody></table></div> : null}
    {controls}
  </div>;
}

function RenderedEmptyState({ renderMode, filtered }: { renderMode: string; filtered: boolean }) {
  if (filtered) return <EmptyState title="No rendered captures match" message="Clear filters or broaden the rendered evidence search." />;
  if (renderMode === "none") return <EmptyState title="Rendering was disabled" message="Browser rendering was not requested for this Scan." />;
  return <EmptyState title="No rendered captures" message="No eligible HTML Pages completed browser capture. Failed, skipped, or interrupted attempts will appear here when recorded." />;
}
function buildQuery(params: URLSearchParams, limit: number, offset: number) { const query = new URLSearchParams(); const mapping: Array<[string, string]> = [["render_state", "capture_state"], ["has_errors", "has_page_errors"], ["has_screenshot", "has_viewport_screenshot"]]; for (const key of ["search", "navigation_status", "has_warnings", "sort", "direction"]) { const value = params.get(key); if (value) query.set(key, value); } for (const [from, to] of mapping) { const value = params.get(from); if (value) query.set(to, value); } query.set("limit", String(limit)); query.set("offset", String(offset)); return `?${query.toString()}`; }
function setParam(setSearchParams: ReturnType<typeof useSearchParams>[1], key: string, value: string) { setSearchParams((current) => { const next = new URLSearchParams(current); if (value) next.set(key, value); else next.delete(key); next.delete("rendered_offset"); return next; }); }
function clearParams(setSearchParams: ReturnType<typeof useSearchParams>[1]) { setSearchParams({ tab: "rendered" }); }
function hasFilters(params: URLSearchParams) { return ["search", "render_state", "navigation_status", "has_warnings", "has_errors", "has_screenshot"].some((key) => params.has(key)); }
