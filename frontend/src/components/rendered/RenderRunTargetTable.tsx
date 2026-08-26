import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { listRenderRunTargets } from "../../api/client";
import type { RenderRunTarget } from "../../types/scans";
import { formatDate, formatStatus } from "../../utils/format";
import { useUrlPagination } from "../../utils/useUrlPagination";
import { Button } from "../ui/Button";
import { EmptyState } from "../ui/EmptyState";
import { ErrorBanner } from "../ui/ErrorBanner";
import { LoadingBlock } from "../ui/Loading";
import { PaginatedTableControls } from "../ui/PaginatedTableControls";
import { StatusBadge } from "../ui/StatusBadge";
import { inputClass } from "../ui/styles";

const OUTCOMES: Array<[RenderRunTarget["presentation_state"], string]> = [
  ["successful", "Successful"],
  ["no_content", "No content"],
  ["redirect", "HTTP redirect"],
  ["http_error", "HTTP error"],
  ["rate_limited", "Rate limited"],
  ["not_attempted_host_throttled", "Not attempted - host throttled"],
  ["technical_failure", "Technical failure"],
  ["evidence_deleted", "Evidence deleted"],
  ["not_attempted", "Not attempted"],
];

export function RenderRunTargetTable({ siteId, runId, selected, onSelectedChange }: { siteId: string; runId: string; selected: number[]; onSelectedChange: (ids: number[]) => void }) {
  const [params, setParams] = useSearchParams();
  const pagination = useUrlPagination({ prefix: "render_targets" });
  const query = buildQuery(params, pagination.limit, pagination.offset);
  const targets = useQuery({
    queryKey: ["render-run-targets", siteId, runId, query],
    queryFn: () => listRenderRunTargets(siteId, runId, query),
    placeholderData: (previous) => previous,
  });
  useEffect(() => pagination.ensureValid(targets.data?.total), [pagination, targets.data?.total]);
  if (targets.error) return <ErrorBanner error={targets.error} title="Could not load Render Run targets" />;
  const pageIds = targets.data?.items.map((item) => item.target_id) ?? [];
  const allSelected = pageIds.length > 0 && pageIds.every((id) => selected.includes(id));
  const controls = <PaginatedTableControls total={targets.data?.total ?? 0} limit={pagination.limit} offset={pagination.offset} onPageChange={pagination.setPage} onPageSizeChange={pagination.setPageSize} itemLabel="Render target" isLoading={targets.isFetching && !targets.isLoading} />;
  return <div className="space-y-4">
    <section className="rounded-md border border-stone-200 bg-white p-4"><div className="grid gap-3 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_auto]">
      <input aria-label="Search Render Run targets" value={params.get("search") ?? ""} onChange={(event) => setParam(setParams, "search", event.target.value)} placeholder="Search target URL" className={inputClass()} />
      <select aria-label="Target state" value={params.get("outcome") ?? ""} onChange={(event) => setParam(setParams, "outcome", event.target.value)} className={inputClass()}><option value="">All target states</option>{OUTCOMES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
      <Button type="button" variant="ghost" onClick={() => setParams((current) => { const next = new URLSearchParams(current); next.delete("search"); next.delete("outcome"); next.delete("render_targets_offset"); return next; })}>Clear filters</Button>
    </div></section>
    {controls}
    {targets.isLoading ? <LoadingBlock label="Loading Render Run targets..." /> : null}
    {!targets.isLoading && !targets.data?.items.length ? <EmptyState title="No targets match" message="Clear filters or broaden the target search." /> : null}
    {targets.data?.items.length ? <div className="overflow-x-auto rounded-md border border-stone-200 bg-white"><table className="min-w-full text-left text-sm"><thead className="bg-stone-100 text-xs uppercase text-stone-500"><tr><th className="w-10 px-3 py-2"><input type="checkbox" aria-label="Select all Render Run targets on this page" checked={allSelected} onChange={(event) => onSelectedChange(event.target.checked ? [...new Set([...selected, ...pageIds])] : selected.filter((id) => !pageIds.includes(id)))} /></th><th className="px-3 py-2">Page</th><th className="px-3 py-2">Target state / Outcome</th><th className="px-3 py-2">Navigation</th><th className="px-3 py-2">Duration</th><th className="px-3 py-2">Warnings</th><th className="px-3 py-2">Browser evidence</th><th className="px-3 py-2">Captured / deleted</th></tr></thead><tbody>{targets.data.items.map((item) => <tr key={item.target_id} className="border-t border-stone-100 align-top hover:bg-stone-50">
      <td className="px-3 py-2"><input type="checkbox" aria-label={`Select ${item.requested_url}`} checked={selected.includes(item.target_id)} onChange={(event) => onSelectedChange(event.target.checked ? [...selected, item.target_id] : selected.filter((id) => id !== item.target_id))} /></td>
      <td className="max-w-xl px-3 py-2">{item.observation_id ? <Link className="block truncate underline" to={`/sites/${siteId}/rendered/observations/${item.observation_id}`}>{item.requested_url}</Link> : <span className="block truncate">{item.requested_url}</span>}<span className="text-xs text-stone-500">Target {item.position}</span></td>
      <td className="px-3 py-2"><StatusBadge status={item.presentation_state} label={stateLabel(item.presentation_state)} /></td>
      <td className="px-3 py-2">{item.navigation_http_status == null ? "Not available" : `HTTP ${item.navigation_http_status}`}</td>
      <td className="px-3 py-2">{item.duration_ms == null ? "Not available" : `${item.duration_ms} ms`}</td>
      <td className="px-3 py-2">{item.warning_count ?? 0}<span className="block text-xs text-stone-500">{item.page_error_count ?? 0} Page errors</span></td>
      <td className="px-3 py-2">{item.has_browser_evidence ? <Link className="underline" to={`/sites/${siteId}/rendered/observations/${item.observation_id}`}>Inspect evidence</Link> : "No retained evidence"}</td>
      <td className="whitespace-nowrap px-3 py-2">{item.evidence_deleted_at ? `Deleted ${formatDate(item.evidence_deleted_at)}` : item.finished_at ? formatDate(item.finished_at) : "Not attempted"}</td>
    </tr>)}</tbody></table></div> : null}
    {controls}
  </div>;
}

function stateLabel(value: RenderRunTarget["presentation_state"]) {
  if (value === "not_attempted_host_throttled") return "Not attempted - host throttled";
  if (value === "evidence_deleted") return "Evidence deleted";
  if (value === "not_attempted") return "Not attempted";
  return formatStatus(value);
}

function buildQuery(params: URLSearchParams, limit: number, offset: number) {
  const query = new URLSearchParams();
  for (const key of ["search", "outcome"]) {
    const value = params.get(key);
    if (value) query.append(key, value);
  }
  query.set("limit", String(limit));
  query.set("offset", String(offset));
  return `?${query.toString()}`;
}

function setParam(setParams: ReturnType<typeof useSearchParams>[1], key: string, value: string) {
  setParams((current) => {
    const next = new URLSearchParams(current);
    if (value) next.set(key, value); else next.delete(key);
    next.delete("render_targets_offset");
    return next;
  });
}
