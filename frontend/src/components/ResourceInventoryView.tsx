import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { getScanResourceSummary, getSiteResourceSummary, listScanResources, listSiteResources } from "../api/client";
import type { ResourceInventoryItem, ScanProjectionStatus } from "../types/scans";
import { formatBytes, formatDate, plural } from "../utils/format";
import { useUrlPagination } from "../utils/useUrlPagination";
import { scanResultQueryOptions } from "../utils/scanQueryOptions";
import { Button } from "./ui/Button";
import { EmptyState } from "./ui/EmptyState";
import { ErrorBanner } from "./ui/ErrorBanner";
import { LoadingBlock } from "./ui/Loading";
import { PaginatedTableControls } from "./ui/PaginatedTableControls";
import { StatusBadge } from "./ui/StatusBadge";
import { inputClass } from "./ui/styles";

const resourceKinds = ["image", "document", "stylesheet", "script", "font", "video", "audio", "archive", "feed", "manifest", "structured_data", "other", "unknown"];

export function ResourceInventoryView({ scope, id, scanStatus, projectionStatus }: { scope: "scan" | "site"; id: string; scanStatus?: string; projectionStatus?: ScanProjectionStatus }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const pagination = useUrlPagination({ prefix: "resources" });
  const query = buildResourceQuery(searchParams, pagination.limit, pagination.offset);
  const resultOptions = scope === "scan" ? scanResultQueryOptions(scanStatus, projectionStatus) : {};
  const projectionKey = projectionStatus?.current_build?.id ?? projectionStatus?.projection_status ?? "dynamic";
  const resources = useQuery({
    queryKey: [`${scope}-resources`, id, projectionKey, query],
    queryFn: () => scope === "scan" ? listScanResources(id, query) : listSiteResources(id, query),
    placeholderData: (previous) => previous,
    ...resultOptions
  });
  const summary = useQuery({
    queryKey: [`${scope}-resource-summary`, id, projectionKey],
    queryFn: () => scope === "scan" ? getScanResourceSummary(id) : getSiteResourceSummary(id),
    ...resultOptions
  });
  useEffect(() => pagination.ensureValid(resources.data?.total), [pagination, resources.data?.total]);
  const controls = <PaginatedTableControls total={resources.data?.total ?? 0} limit={pagination.limit} offset={pagination.offset} onPageChange={pagination.setPage} onPageSizeChange={pagination.setPageSize} itemLabel="Resource" isLoading={resources.isFetching && !resources.isLoading} />;
  const detailBase = scope === "scan" ? `/scans/${id}/resources` : `/sites/${id}/resources`;

  if (resources.error || summary.error) return <ErrorBanner error={resources.error ?? summary.error} title="Could not load Resources" />;
  return <div className="space-y-4">
    {scope === "scan" && projectionStatus?.projection_source === "dynamic" && projectionStatus.projection_status !== "not_terminal" ? <p className="text-sm text-stone-600" role="status">Preparing optimized results. Current evidence remains available.</p> : null}
    <ResourceSummary summary={summary.data} loading={summary.isLoading} />
    <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <input aria-label="Search Resources" value={searchParams.get("search") ?? ""} onChange={(event) => setResourceParam(setSearchParams, "search", event.target.value)} placeholder="Search URL or filename" className={`${inputClass()} xl:col-span-2`} />
        <select aria-label="Resource kind" value={searchParams.get("resource_kind") ?? ""} onChange={(event) => setResourceParam(setSearchParams, "resource_kind", event.target.value)} className={inputClass()}>
          <option value="">All Resource kinds</option>
          {resourceKinds.map((kind) => <option key={kind} value={kind}>{kindLabel(kind)}</option>)}
        </select>
        <select aria-label="Resource evidence state" value={searchParams.get("evidence_state") ?? "any"} onChange={(event) => setResourceParam(setSearchParams, "evidence_state", event.target.value === "any" ? "" : event.target.value)} className={inputClass()}>
          <option value="any">Observed and discovered</option><option value="observed">Observed only</option><option value="discovered_only">Discovered only</option>
        </select>
        <select aria-label="Resource scope state" value={searchParams.get("scope_state") ?? "any"} onChange={(event) => setResourceParam(setSearchParams, "scope_state", event.target.value === "any" ? "" : event.target.value)} className={inputClass()}>
          <option value="any">Any scope</option><option value="in_scope">In scope</option><option value="out_of_scope">Out of scope</option>
        </select>
        <input aria-label="Resource MIME type" value={searchParams.get("mime_type") ?? ""} onChange={(event) => setResourceParam(setSearchParams, "mime_type", event.target.value)} placeholder="MIME type" className={inputClass()} />
        <input aria-label="Resource file extension" value={searchParams.get("extension") ?? ""} onChange={(event) => setResourceParam(setSearchParams, "extension", event.target.value)} placeholder="Extension" className={inputClass()} />
        <input aria-label="Resource host" value={searchParams.get("host") ?? ""} onChange={(event) => setResourceParam(setSearchParams, "host", event.target.value)} placeholder="Host" className={inputClass()} />
        <input aria-label="Resource HTTP status" type="number" value={searchParams.get("status") ?? ""} onChange={(event) => setResourceParam(setSearchParams, "status", event.target.value)} placeholder="HTTP status" className={inputClass()} />
        <select aria-label="Sort Resources" value={searchParams.get("sort") ?? "url"} onChange={(event) => setResourceParam(setSearchParams, "sort", event.target.value)} className={inputClass()}>
          <option value="url">URL</option><option value="kind">Kind</option><option value="mime_type">MIME type</option><option value="http_status">HTTP status</option><option value="declared_size">Declared size</option><option value="occurrence_count">Occurrences</option><option value="source_page_count">Source Pages</option><option value="latest_discovered">Latest discovery</option>
        </select>
        <select aria-label="Resource sort direction" value={searchParams.get("direction") ?? "asc"} onChange={(event) => setResourceParam(setSearchParams, "direction", event.target.value)} className={inputClass()}><option value="asc">Ascending</option><option value="desc">Descending</option></select>
        <Button type="button" variant="ghost" onClick={() => clearResourceParams(setSearchParams, searchParams)}>Clear filters</Button>
      </div>
    </section>
    {controls}
    {resources.isLoading ? <LoadingBlock label="Loading Resources..." /> : null}
    {!resources.isLoading && !resources.data?.items.length ? <EmptyState title="No Resources found" message="Resources appear when non-HTML responses or embedded file references are retained in this scope." /> : null}
    {resources.data?.items.length ? <ResourceTable items={resources.data.items} detailBase={detailBase} /> : null}
    {controls}
  </div>;
}

function ResourceSummary({ summary, loading }: { summary?: { unique_resources: number; observed_resources: number; discovered_only_resources: number; total_occurrences: number; kind_counts: Record<string, number> }; loading: boolean }) {
  if (loading) return <LoadingBlock label="Loading Resource summary..." />;
  if (!summary) return null;
  const metrics = [
    ["Unique Resources", summary.unique_resources], ["Observed", summary.observed_resources], ["Discovered only", summary.discovered_only_resources], ["Occurrences", summary.total_occurrences],
    ["Images", summary.kind_counts.image ?? 0], ["Documents", summary.kind_counts.document ?? 0], ["Scripts", summary.kind_counts.script ?? 0], ["Stylesheets", summary.kind_counts.stylesheet ?? 0], ["Fonts", summary.kind_counts.font ?? 0]
  ];
  return <div className="grid grid-cols-2 gap-3 md:grid-cols-5">{metrics.map(([label, value]) => <div key={label} className="rounded-md border border-stone-200 bg-white px-3 py-2 shadow-sm"><div className="text-xs font-medium uppercase text-stone-500">{label}</div><div className="mt-1 text-xl font-semibold">{value}</div></div>)}</div>;
}

function ResourceTable({ items, detailBase }: { items: ResourceInventoryItem[]; detailBase: string }) {
  return <div className="overflow-x-auto rounded-md border border-stone-200 bg-white shadow-sm"><table className="min-w-full text-left text-sm"><thead className="bg-stone-100 text-xs uppercase text-stone-500"><tr>{["Type", "Resource", "MIME", "Status", "Size", "Observation", "Used by", "Scope", "Latest evidence"].map((header) => <th key={header} scope="col" className="px-3 py-2 font-medium">{header}</th>)}</tr></thead><tbody>{items.map((item) => <tr key={item.resource_id} className="border-t border-stone-100 align-top hover:bg-stone-50">
    <td className="px-3 py-2"><ResourceKindBadge kind={item.effective_kind} label={item.effective_kind_label} /><span className="mt-1 block text-xs text-stone-500">{item.classification_source}</span></td>
    <td className="max-w-xl px-3 py-2"><Link to={`${detailBase}/${item.resource_id}`} className="block truncate font-mono text-xs underline" title={item.normalized_url}>{item.normalized_url}</Link><span className="mt-1 block text-xs text-stone-500">{item.file_extension ? `.${item.file_extension}` : "No extension"}</span></td>
    <td className="max-w-xs px-3 py-2">{item.normalized_mime_type ?? "Not observed"}</td>
    <td className="px-3 py-2">{item.http_status ? <StatusBadge status={String(item.http_status)} label={String(item.http_status)} /> : "Not observed"}</td>
    <td className="px-3 py-2">{item.declared_content_length == null ? "Not declared" : formatBytes(item.declared_content_length)}</td>
    <td className="px-3 py-2"><ResourceEvidenceBadge observed={item.observed} /></td>
    <td className="px-3 py-2">{plural(item.source_page_count, "Page")}<span className="block text-xs text-stone-500">{plural(item.occurrence_count, "occurrence")}</span></td>
    <td className="px-3 py-2">{item.in_scope_occurrence_count} in / {item.out_of_scope_occurrence_count} out</td>
    <td className="whitespace-nowrap px-3 py-2">{formatDate(item.fetched_at ?? item.latest_discovered_at)}</td>
  </tr>)}</tbody></table></div>;
}

export function ResourceKindBadge({ kind, label = kindLabel(kind) }: { kind: string; label?: string }) {
  return <span className="inline-flex rounded-md border border-stone-300 bg-stone-50 px-2 py-1 text-xs font-medium text-stone-800">{label}</span>;
}

export function ResourceEvidenceBadge({ observed }: { observed: boolean }) {
  return <StatusBadge status={observed ? "completed" : "queued"} label={observed ? "Observed" : "Discovered only"} />;
}

function buildResourceQuery(searchParams: URLSearchParams, limit: number, offset: number) {
  const query = new URLSearchParams();
  for (const key of ["search", "resource_kind", "mime_type", "extension", "host", "status", "evidence_state", "scope_state", "location_state", "min_size", "max_size", "has_multiple_source_pages", "sort", "direction"]) {
    const value = searchParams.get(key); if (value) query.set(key, value);
  }
  query.set("limit", String(limit)); query.set("offset", String(offset));
  return `?${query.toString()}`;
}

function setResourceParam(setSearchParams: ReturnType<typeof useSearchParams>[1], key: string, value: string) { setSearchParams((current) => { const next = new URLSearchParams(current); if (value) next.set(key, value); else next.delete(key); next.delete("resources_offset"); return next; }); }
function clearResourceParams(setSearchParams: ReturnType<typeof useSearchParams>[1], current: URLSearchParams) { const next = new URLSearchParams(); const tab = current.get("tab"); if (tab) next.set("tab", tab); setSearchParams(next); }
function kindLabel(kind: string) { return kind === "html_page" ? "HTML Page" : kind === "structured_data" ? "Structured data" : kind.split("_").map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`).join(" "); }
