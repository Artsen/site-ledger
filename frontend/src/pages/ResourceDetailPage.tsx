import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { getScanResource, getSiteResource, listScanResourceOccurrences, listSiteResourceHistory, listSiteResourceOccurrences } from "../api/client";
import { ResourceEvidenceBadge, ResourceKindBadge } from "../components/ResourceInventoryView";
import { CopyButton } from "../components/ui/CopyButton";
import { DefinitionList } from "../components/ui/DefinitionList";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorBanner } from "../components/ui/ErrorBanner";
import { LoadingBlock } from "../components/ui/Loading";
import { PaginatedTableControls } from "../components/ui/PaginatedTableControls";
import { StatusBadge } from "../components/ui/StatusBadge";
import { SortableTableHeader } from "../components/ui/SortableTableHeader";
import { Tabs } from "../components/ui/Tabs";
import type { ResourceOccurrence } from "../types/scans";
import { formatBytes, formatDate, formatScopeDecision } from "../utils/format";
import { useDocumentTitle } from "../utils/useDocumentTitle";
import { useUrlPagination } from "../utils/useUrlPagination";
import { useTableSort } from "../utils/useTableSort";

export function ResourceDetailPage({ scope }: { scope: "scan" | "site" }) {
  const { scanId = "", siteId = "", resourceId = "" } = useParams();
  const id = scope === "scan" ? scanId : siteId;
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = searchParams.get("tab") ?? "overview";
  const usedPagination = useUrlPagination({ prefix: "used", total: undefined });
  const historyPagination = useUrlPagination({ prefix: "history", total: undefined });
  const detail = useQuery({ queryKey: [`${scope}-resource`, id, resourceId], queryFn: () => scope === "scan" ? getScanResource(id, resourceId) : getSiteResource(id, resourceId) });
  const occurrences = useQuery({ queryKey: [`${scope}-resource-occurrences`, id, resourceId, usedPagination.limit, usedPagination.offset], queryFn: () => scope === "scan" ? listScanResourceOccurrences(id, resourceId, `?limit=${usedPagination.limit}&offset=${usedPagination.offset}`) : listSiteResourceOccurrences(id, resourceId, `?limit=${usedPagination.limit}&offset=${usedPagination.offset}`), enabled: tab === "used-by-pages", placeholderData: (previous) => previous });
  const history = useQuery({ queryKey: ["site-resource-history", id, resourceId, historyPagination.limit, historyPagination.offset], queryFn: () => listSiteResourceHistory(id, resourceId, `?limit=${historyPagination.limit}&offset=${historyPagination.offset}`), enabled: scope === "site" && tab === "scans", placeholderData: (previous) => previous });
  useEffect(() => usedPagination.ensureValid(occurrences.data?.total), [occurrences.data?.total, usedPagination]);
  useEffect(() => historyPagination.ensureValid(history.data?.total), [history.data?.total, historyPagination]);
  useDocumentTitle(detail.data?.resource.effective_kind_label ?? "Resource");
  if (detail.isLoading) return <PageFrame><LoadingBlock label="Loading Resource..." /></PageFrame>;
  if (detail.error) return <PageFrame><ErrorBanner error={detail.error} title="Could not load Resource" /></PageFrame>;
  if (!detail.data) return <PageFrame><EmptyState title="Resource not found" message="The retained evidence may have been deleted." /></PageFrame>;
  const item = detail.data.resource;
  const tabs = scope === "scan" ? [{ id: "overview", label: "Overview" }, { id: "used-by-pages", label: "Used by Pages", count: item.occurrence_count }, { id: "observations", label: "Observations", count: item.observed ? 1 : 0 }] : [{ id: "overview", label: "Overview" }, { id: "scans", label: "Scans", count: item.scan_count }, { id: "used-by-pages", label: "Used by Pages", count: item.occurrence_count }];
  const back = scope === "scan" ? `/scans/${id}?tab=resources` : `/sites/${id}/resources`;
  return <PageFrame>
    <div className="mb-5 flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between"><div className="min-w-0"><div className="mb-2 text-sm text-stone-500"><Link to={back} className="underline">Resources</Link> / {item.effective_kind_label}</div><h1 className="break-all text-xl font-semibold">{item.content_disposition_filename ?? item.path.split("/").slice(-1)[0] ?? item.normalized_url}</h1><p className="mt-2 break-all font-mono text-xs text-stone-600">{item.normalized_url}</p><div className="mt-2 flex gap-2"><ResourceKindBadge kind={item.effective_kind} label={item.effective_kind_label} /><ResourceEvidenceBadge observed={item.observed} /></div></div><div className="flex gap-2"><a href={item.normalized_url} target="_blank" rel="noreferrer" className="rounded-md border border-stone-300 bg-white px-3 py-2 text-sm font-medium">Open live Resource</a><CopyButton value={item.normalized_url} label="Copy Resource URL" /></div></div>
    <Tabs tabs={tabs} active={tab} onChange={(next) => setSearchParams(next === "overview" ? {} : { tab: next })} />
    <div className="mt-5">
      {tab === "overview" ? <ResourceOverview item={item} detail={detail.data} /> : null}
      {tab === "used-by-pages" ? occurrences.isLoading ? <LoadingBlock label="Loading Resource occurrences..." /> : occurrences.error ? <ErrorBanner error={occurrences.error} title="Could not load occurrences" /> : <PaginatedSection controls={<PaginatedTableControls total={occurrences.data?.total ?? 0} limit={usedPagination.limit} offset={usedPagination.offset} onPageChange={usedPagination.setPage} onPageSizeChange={usedPagination.setPageSize} itemLabel="occurrence" isLoading={occurrences.isFetching} />}><OccurrenceView items={occurrences.data?.items ?? []} scanId={scope === "scan" ? id : undefined} siteId={scope === "site" ? id : undefined} /></PaginatedSection> : null}
      {tab === "observations" && scope === "scan" ? item.snapshot_id ? <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm"><h2 className="mb-3 text-base font-semibold">Static Resource observation</h2><DefinitionList items={[{ label: "Snapshot", value: item.snapshot_id }, { label: "HTTP status", value: item.http_status }, { label: "MIME type", value: item.normalized_mime_type }, { label: "Observed", value: formatDate(item.fetched_at) }, { label: "Transferred", value: formatBytes(item.network_bytes_transferred) }, { label: "Declared size", value: formatBytes(item.declared_content_length) }]} /></section> : <EmptyState title="Discovered-only Resource" message="This Scan retained a reference but made no separate Resource request." /> : null}
      {tab === "scans" && scope === "site" ? history.isLoading ? <LoadingBlock label="Loading Resource history..." /> : history.error ? <ErrorBanner error={history.error} title="Could not load Resource history" /> : <PaginatedSection controls={<PaginatedTableControls total={history.data?.total ?? 0} limit={historyPagination.limit} offset={historyPagination.offset} onPageChange={historyPagination.setPage} onPageSizeChange={historyPagination.setPageSize} itemLabel="Scan" isLoading={history.isFetching} />}><HistoryView items={history.data?.items ?? []} siteId={id} /></PaginatedSection> : null}
    </div>
  </PageFrame>;
}

function ResourceOverview({ item, detail }: { item: Awaited<ReturnType<typeof getScanResource>>["resource"]; detail: Awaited<ReturnType<typeof getScanResource>> }) {
  return <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm"><h2 className="mb-4 text-base font-semibold">Resource evidence</h2><DefinitionList items={[
    { label: "URL", value: item.normalized_url, copyValue: item.normalized_url }, { label: "Resource kind", value: item.effective_kind_label }, { label: "Classification source", value: item.classification_source }, { label: "Evidence", value: item.observed ? "Observed" : "Discovered only" }, { label: "MIME type", value: item.normalized_mime_type }, { label: "Extension", value: item.file_extension ? `.${item.file_extension}` : null }, { label: "HTTP status", value: item.http_status }, { label: "Requested URL", value: detail.requested_url }, { label: "Final URL", value: item.final_url }, { label: "Content-Disposition filename", value: item.content_disposition_filename }, { label: "Declared size", value: formatBytes(item.declared_content_length) }, { label: "Bytes inspected or transferred", value: formatBytes(item.network_bytes_transferred) }, { label: "Response body state", value: detail.response_body_state }, { label: "Inspected prefix", value: formatBytes(detail.inspected_prefix_byte_count) }, { label: "Response time", value: item.response_time_ms == null ? null : `${item.response_time_ms} ms` }, { label: "First discovery", value: formatDate(item.first_discovered_at) }, { label: "Latest discovery", value: formatDate(item.latest_discovered_at) }, { label: "Occurrences", value: item.occurrence_count }, { label: "Source Pages", value: item.source_page_count }, { label: "Scope", value: `${item.in_scope_occurrence_count} in / ${item.out_of_scope_occurrence_count} out` }
  ]} /></section>;
}

function OccurrenceView({ items, scanId, siteId }: { items: ResourceOccurrence[]; scanId?: string; siteId?: string }) {
  const values = { source: (item: ResourceOccurrence) => item.source_title ?? item.source_url, reference: (item: ResourceOccurrence) => `${item.occurrence_source} ${item.relation_type}`, context: (item: ResourceOccurrence) => item.anchor_text ?? item.alt_text, scope: (item: ResourceOccurrence) => item.scope_decision, dom: (item: ResourceOccurrence) => item.dom_path, discovered: (item: ResourceOccurrence) => Date.parse(item.discovered_at) };
  const { sortedItems, sort, changeSort } = useTableSort(items, values);
  if (!items.length) return <EmptyState title="No retained occurrences" message="This Resource was observed directly without a retained source Page reference." />;
  const columns = [["source", "Source Page"], ["reference", "Reference"], ["context", "Context"], ["scope", "Scope"], ["dom", "DOM path"], ["discovered", "Discovered"]];
  return <div className="overflow-x-auto rounded-md border border-stone-200 bg-white shadow-sm"><table className="min-w-full text-left text-sm"><thead className="bg-stone-100 text-xs uppercase text-stone-500"><tr>{columns.map(([column, label]) => <SortableTableHeader key={column} column={column} label={label} activeColumn={sort?.column ?? null} direction={sort?.direction ?? null} onChange={changeSort} defaultDirection={column === "discovered" ? "desc" : "asc"} />)}</tr></thead><tbody>{sortedItems.map((item) => { const pageUrl = scanId ? `/scans/${scanId}/pages/${item.source_snapshot_id}` : siteId ? `/sites/${siteId}/pages/${item.source_resource_id}` : null; return <tr key={`${item.occurrence_source}-${item.occurrence_id}`} className="border-t border-stone-100 align-top"><td className="max-w-md px-3 py-2">{pageUrl ? <Link to={pageUrl} className="block truncate underline">{item.source_title ?? "Untitled Page"}</Link> : <span>{item.source_title ?? "Untitled Page"}</span>}<span className="block truncate font-mono text-xs text-stone-500">{item.source_url}</span></td><td className="px-3 py-2">{item.occurrence_source === "anchor" ? "Anchor link" : `${item.element_tag} ${item.attribute_name}`}<span className="block text-xs text-stone-500">{item.relation_type}</span></td><td className="max-w-sm px-3 py-2">{item.anchor_text ?? item.alt_text ?? "No text"}<span className="block text-xs text-stone-500">{[item.srcset_descriptor, item.rel, item.media, item.as_hint].filter(Boolean).join(" | ")}</span></td><td className="px-3 py-2"><StatusBadge status={item.in_scope ? "completed" : "interrupted"} label={formatScopeDecision(item.scope_decision)} /></td><td className="max-w-sm break-all px-3 py-2 font-mono text-xs">{item.dom_path ?? "Not available"}</td><td className="whitespace-nowrap px-3 py-2">{formatDate(item.discovered_at)}</td></tr>; })}</tbody></table></div>;
}

function PaginatedSection({ controls, children }: { controls: React.ReactNode; children: React.ReactNode }) { return <div className="space-y-4">{controls}{children}{controls}</div>; }

function HistoryView({ items, siteId }: { items: Awaited<ReturnType<typeof listSiteResourceHistory>>["items"]; siteId: string }) {
  const values = { scan: (item: (typeof items)[number]) => item.scan_id, evidence: (item: (typeof items)[number]) => item.observed, kind: (item: (typeof items)[number]) => item.effective_kind, mime: (item: (typeof items)[number]) => item.normalized_mime_type, status: (item: (typeof items)[number]) => item.http_status, size: (item: (typeof items)[number]) => item.declared_content_length, occurrences: (item: (typeof items)[number]) => item.occurrence_count, observed: (item: (typeof items)[number]) => item.observed_at ? Date.parse(item.observed_at) : null };
  const { sortedItems, sort, changeSort } = useTableSort(items, values);
  if (!items.length) return <EmptyState title="No retained Scan history" message="No Scan evidence remains for this Resource." />;
  const columns = [["scan", "Scan"], ["evidence", "Evidence"], ["kind", "Kind"], ["mime", "MIME"], ["status", "Status"], ["size", "Size"], ["occurrences", "Occurrences"], ["observed", "Observed"]];
  return <div className="overflow-x-auto rounded-md border border-stone-200 bg-white shadow-sm"><table className="min-w-full text-left text-sm"><thead className="bg-stone-100 text-xs uppercase text-stone-500"><tr>{columns.map(([column, label]) => <SortableTableHeader key={column} column={column} label={label} activeColumn={sort?.column ?? null} direction={sort?.direction ?? null} onChange={changeSort} defaultDirection={column === "observed" ? "desc" : "asc"} />)}</tr></thead><tbody>{sortedItems.map((item) => <tr key={item.scan_id} className="border-t border-stone-100"><td className="px-3 py-2"><Link to={`/scans/${item.scan_id}/resources/${item.resource_id}`} className="underline">Scan {item.scan_id}</Link><span className="block text-xs text-stone-500">{formatDate(item.scan_created_at)}</span></td><td className="px-3 py-2"><ResourceEvidenceBadge observed={item.observed} /></td><td className="px-3 py-2"><ResourceKindBadge kind={item.effective_kind} /></td><td className="px-3 py-2">{item.normalized_mime_type ?? "Not observed"}</td><td className="px-3 py-2">{item.http_status ?? "Not observed"}</td><td className="px-3 py-2">{formatBytes(item.declared_content_length)}</td><td className="px-3 py-2">{item.occurrence_count}</td><td className="px-3 py-2">{formatDate(item.observed_at)}</td></tr>)}</tbody></table><span className="sr-only">Site {siteId}</span></div>;
}

function PageFrame({ children }: { children: React.ReactNode }) { return <section className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">{children}</section>; }
