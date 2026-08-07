import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import {
  cancelSourceRefresh,
  deleteAiDocumentSource,
  getAiDocumentSource,
  getAiDocumentTree,
  getAiSourceDeletePreview,
  listAiDocumentRefreshes,
  listAiDocuments,
  listAiReferences,
  listAiValidations,
  refreshSource,
  updateAiDocumentSource,
} from "../api/client";
import { Button } from "../components/ui/Button";
import { DefinitionList } from "../components/ui/DefinitionList";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorBanner } from "../components/ui/ErrorBanner";
import { LoadingBlock } from "../components/ui/Loading";
import { PaginatedTableControls } from "../components/ui/PaginatedTableControls";
import { StatusBadge } from "../components/ui/StatusBadge";
import { SortableTableHeader } from "../components/ui/SortableTableHeader";
import { Tabs } from "../components/ui/Tabs";
import type { AiDocumentSettings } from "../types/aiDocuments";
import { formatBytes, formatDate, formatStatus } from "../utils/format";
import { useDocumentTitle } from "../utils/useDocumentTitle";
import { useUrlPagination } from "../utils/useUrlPagination";
import { useTableSort } from "../utils/useTableSort";

const tabItems = ["overview", "tree", "files", "declared", "validation", "history", "settings"];

export function AiDocumentSourcePage() {
  const { sourceId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") ?? "overview";
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const source = useQuery({ queryKey: ["ai-source", sourceId], queryFn: () => getAiDocumentSource(sourceId) });
  useDocumentTitle(source.data?.name ?? "AI Document Source");
  const refresh = useMutation({
    mutationFn: () => refreshSource(String(source.data!.website_property_id), sourceId),
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: ["ai-source", sourceId] }),
  });
  const cancel = useMutation({ mutationFn: (id: number) => cancelSourceRefresh(String(id)), onSuccess: async () => queryClient.invalidateQueries({ queryKey: ["ai-source", sourceId] }) });
  const remove = useMutation({ mutationFn: () => deleteAiDocumentSource(sourceId), onSuccess: () => navigate(`/sites/${source.data?.website_property_id}?tab=sources`) });

  if (source.isLoading) return <PageFrame><LoadingBlock label="Loading AI Document Source..." /></PageFrame>;
  if (source.error) return <PageFrame><ErrorBanner error={source.error} title="Could not load AI Document Source" /></PageFrame>;
  if (!source.data) return <PageFrame><EmptyState title="Source not found" message="This AI Document Source is unavailable." /></PageFrame>;
  const active = source.data.last_refresh_status === "running" || source.data.last_refresh_status === "queued";
  return <PageFrame>
    <div className="mb-5 flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
      <div className="min-w-0">
        <div className="mb-2 text-sm text-stone-500"><Link className="underline" to={`/sites/${source.data.website_property_id}?tab=sources`}>{source.data.site_name}</Link> / Sources / AI Document Source</div>
        <h1 className="truncate text-2xl font-semibold">{source.data.name}</h1>
        <div className="mt-2 flex flex-wrap items-center gap-2"><StatusBadge status={source.data.last_refresh_status ?? "never_refreshed"} label={formatStatus(source.data.last_refresh_status ?? "never refreshed")} /><span className="max-w-3xl truncate font-mono text-xs text-stone-600">{source.data.entry_url}</span></div>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button type="button" loading={refresh.isPending} disabled={active || !source.data.is_active} onClick={() => refresh.mutate()}>Refresh</Button>
        {active && source.data.latest_source_refresh_id ? <Button type="button" variant="danger" loading={cancel.isPending} onClick={() => cancel.mutate(source.data!.latest_source_refresh_id!)}>Cancel</Button> : null}
        <a className="rounded-md border border-stone-300 bg-white px-3 py-2 text-sm font-medium" href={source.data.entry_url} target="_blank" rel="noreferrer">Open live document</a>
      </div>
    </div>
    {refresh.error || cancel.error || remove.error ? <ErrorBanner error={refresh.error ?? cancel.error ?? remove.error} title="Source action failed" /> : null}
    <Tabs tabs={tabItems.map((id) => ({ id, label: id === "declared" ? "Declared URLs" : id[0].toUpperCase() + id.slice(1) }))} active={tab} onChange={(next) => setParams((current) => { const copy = new URLSearchParams(current); copy.set("tab", next); return copy; })} />
    <div className="mt-5">
      {tab === "overview" ? <Overview source={source.data} /> : null}
      {tab === "tree" ? <Tree sourceId={sourceId} refreshId={source.data.latest_refresh_id} /> : null}
      {tab === "files" ? <Files sourceId={sourceId} refreshId={source.data.latest_refresh_id} /> : null}
      {tab === "declared" ? <Declared sourceId={sourceId} refreshId={source.data.latest_refresh_id} /> : null}
      {tab === "validation" ? <Validation sourceId={sourceId} refreshId={source.data.latest_refresh_id} /> : null}
      {tab === "history" ? <History sourceId={sourceId} /> : null}
      {tab === "settings" ? <Settings source={source.data} onSaved={() => queryClient.invalidateQueries({ queryKey: ["ai-source", sourceId] })} onDelete={async () => { const preview = await getAiSourceDeletePreview(sourceId); if (window.confirm(`Delete this Source and ${preview.refresh_count} refreshes, ${preview.snapshot_count} snapshots, and ${preview.reference_count} references? ${formatBytes(preview.reclaimable_storage_bytes)} can be reclaimed; unrelated Scan and Page evidence is preserved.`)) remove.mutate(); }} /> : null}
    </div>
  </PageFrame>;
}

function Overview({ source }: { source: Awaited<ReturnType<typeof getAiDocumentSource>> }) {
  return <div className="space-y-5">
    <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
      <h2 className="mb-4 text-base font-semibold">Current source state</h2>
      <DefinitionList items={[
        { label: "Site", value: source.site_name },
        { label: "Entry point", value: source.entry_url, copyValue: source.entry_url },
        { label: "Discovery", value: formatStatus(source.discovery_mode) },
        { label: "Last refreshed", value: formatDate(source.last_successful_refresh_at) },
        { label: "Saved documents", value: source.document_count },
        { label: "Declared references", value: source.reference_count },
        { label: "Current Inventory URLs", value: source.current_entry_count },
        { label: "Validation messages", value: source.warning_count },
        { label: "Retained evidence", value: formatBytes(source.retained_bytes) },
      ]} />
    </section>
    <section className="rounded-md border border-stone-200 bg-white p-4 text-sm text-stone-600 shadow-sm">AI Document Source refreshes are immutable Source evidence. They do not create Scan observations, change Page metadata, or add links to the Scan graph.</section>
  </div>;
}

function Tree({ sourceId, refreshId }: { sourceId: string; refreshId: number | null }) {
  const query = useQuery({ queryKey: ["ai-tree", sourceId, refreshId], queryFn: () => getAiDocumentTree(sourceId, refreshId!), enabled: refreshId != null });
  if (!refreshId) return <EmptyState title="No refresh evidence" message="Refresh this Source to build its document graph." />;
  if (query.isLoading) return <LoadingBlock label="Loading document tree..." />;
  if (query.error) return <ErrorBanner error={query.error} title="Could not load document tree" />;
  return <section className="rounded-md border border-stone-200 bg-white shadow-sm"><ul className="divide-y divide-stone-100">{query.data?.items.map(({ snapshot, parent_count, cycle }) => <li key={snapshot.id} className="flex flex-wrap items-center gap-3 px-4 py-3" style={{ paddingLeft: `${Math.min(snapshot.parent_depth_min, 10) * 20 + 16}px` }}><span className="font-mono text-xs">{snapshot.final_url ?? snapshot.requested_url}</span><span className="text-xs text-stone-500">{formatStatus(snapshot.document_kind)}</span>{parent_count > 1 ? <span className="text-xs text-blue-700">{parent_count} parents</span> : null}{cycle ? <span className="text-xs text-amber-800">Cycle</span> : null}{snapshot.raw_sha256 ? <Link className="text-xs underline" to={`/ai-document-snapshots/${snapshot.id}`}>Saved evidence</Link> : null}</li>)}</ul></section>;
}

function Files({ sourceId, refreshId }: { sourceId: string; refreshId: number | null }) {
  const [params, setParams] = useSearchParams();
  const pagination = useUrlPagination({ prefix: "ai_files" });
  const queryParams = new URLSearchParams({ limit: String(pagination.limit), offset: String(pagination.offset) });
  for (const key of ["file_search", "file_kind", "file_change"]) { const value = params.get(key); if (value) queryParams.set(key.replace("file_", key === "file_search" ? "search" : key === "file_kind" ? "kind" : "changed"), value); }
  const query = useQuery({ queryKey: ["ai-files", sourceId, refreshId, queryParams.toString()], queryFn: () => listAiDocuments(sourceId, refreshId!, `?${queryParams}`), enabled: refreshId != null, placeholderData: (previous) => previous });
  const fileItems = query.data?.items ?? [];
  const fileValues = { url: (item: (typeof fileItems)[number]) => item.final_url ?? item.requested_url, role: (item: (typeof fileItems)[number]) => item.document_role, kind: (item: (typeof fileItems)[number]) => item.document_kind, status: (item: (typeof fileItems)[number]) => item.http_status, mime: (item: (typeof fileItems)[number]) => item.normalized_mime_type, size: (item: (typeof fileItems)[number]) => item.raw_byte_size, hash: (item: (typeof fileItems)[number]) => item.raw_sha256, parents: (item: (typeof fileItems)[number]) => item.parent_count };
  const fileSort = useTableSort(fileItems, fileValues);
  useEffect(() => pagination.ensureValid(query.data?.total), [query.data?.total, pagination]);
  if (!refreshId) return <EmptyState title="No saved files" message="Refresh this Source to retrieve accepted documents." />;
  const controls = query.data ? <PaginatedTableControls total={query.data.total} limit={pagination.limit} offset={pagination.offset} onPageChange={pagination.setPage} onPageSizeChange={pagination.setPageSize} itemLabel="file" isLoading={query.isFetching && !query.isLoading} /> : null;
  return <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
    <div className="mb-4 grid gap-3 md:grid-cols-3"><input aria-label="Search AI document files" placeholder="Search URL or title" value={params.get("file_search") ?? ""} onChange={(event) => setFilter(setParams, "file_search", event.target.value, "ai_files_offset")} className="rounded-md border border-stone-300 px-3 py-2 text-sm" /><select aria-label="Document kind" value={params.get("file_kind") ?? ""} onChange={(event) => setFilter(setParams, "file_kind", event.target.value, "ai_files_offset")} className="rounded-md border border-stone-300 px-3 py-2 text-sm"><option value="">All document kinds</option><option value="markdown_document">Markdown</option><option value="llms_index">AI indexes</option><option value="llms_full">Corpus documents</option><option value="openapi_specification">OpenAPI</option><option value="asyncapi_specification">AsyncAPI</option></select><select aria-label="Change state" value={params.get("file_change") ?? ""} onChange={(event) => setFilter(setParams, "file_change", event.target.value, "ai_files_offset")} className="rounded-md border border-stone-300 px-3 py-2 text-sm"><option value="">All change states</option><option value="new">New</option><option value="changed">Changed</option><option value="unchanged">Unchanged</option></select></div>
    {query.isLoading ? <LoadingBlock label="Loading saved files..." /> : null}{query.error ? <ErrorBanner error={query.error} title="Could not load saved files" /> : null}{controls}<div className="overflow-x-auto"><table className="mt-4 min-w-full text-left text-sm"><thead className="bg-stone-100 text-xs uppercase text-stone-500"><tr>{[["url", "URL"], ["role", "Role"], ["kind", "Kind"], ["status", "Status"], ["mime", "MIME"], ["size", "Size"], ["hash", "Hash"], ["parents", "Parents"]].map(([column, label]) => <SortableTableHeader key={column} column={column} label={label} activeColumn={fileSort.sort?.column ?? null} direction={fileSort.sort?.direction ?? null} onChange={fileSort.changeSort} />)}<th className="px-3 py-2 font-medium">Evidence</th></tr></thead><tbody>{fileSort.sortedItems.map((item) => <tr key={item.id} className="border-t border-stone-100"><td className="max-w-sm truncate px-3 py-2 font-mono text-xs">{item.final_url ?? item.requested_url}</td><td className="px-3 py-2">{formatStatus(item.document_role)}</td><td className="px-3 py-2">{formatStatus(item.document_kind)}</td><td className="px-3 py-2">{item.http_status ?? item.fetch_state}</td><td className="px-3 py-2">{item.normalized_mime_type ?? "Unknown"}</td><td className="px-3 py-2">{formatBytes(item.raw_byte_size)}</td><td className="max-w-28 truncate px-3 py-2 font-mono text-xs">{item.raw_sha256 ?? "Not retained"}</td><td className="px-3 py-2">{item.parent_count}</td><td className="px-3 py-2">{item.raw_sha256 ? <Link className="underline" to={`/ai-document-snapshots/${item.id}`}>Open</Link> : "Unavailable"}</td></tr>)}</tbody></table></div>{controls ? <div className="mt-4">{controls}</div> : null}
  </section>;
}

function Declared({ sourceId, refreshId }: { sourceId: string; refreshId: number | null }) {
  const pagination = useUrlPagination({ prefix: "ai_refs" });
  const query = useQuery({ queryKey: ["ai-references", sourceId, refreshId, pagination.limit, pagination.offset], queryFn: () => listAiReferences(sourceId, refreshId!, `?limit=${pagination.limit}&offset=${pagination.offset}`), enabled: refreshId != null, placeholderData: (previous) => previous });
  const referenceItems = query.data?.items ?? [];
  const referenceValues = { url: (item: (typeof referenceItems)[number]) => item.normalized_target_url ?? item.raw_url, section: (item: (typeof referenceItems)[number]) => item.section_title, label: (item: (typeof referenceItems)[number]) => item.label, optional: (item: (typeof referenceItems)[number]) => item.optional, scope: (item: (typeof referenceItems)[number]) => item.scope_decision, classification: (item: (typeof referenceItems)[number]) => item.inferred_kind, inventory: (item: (typeof referenceItems)[number]) => item.inventory_entry_id != null };
  const referenceSort = useTableSort(referenceItems, referenceValues);
  useEffect(() => pagination.ensureValid(query.data?.total), [query.data?.total, pagination]);
  if (!refreshId) return <EmptyState title="No declared URLs" message="Refresh this Source to parse declared references." />;
  const controls = query.data ? <PaginatedTableControls total={query.data.total} limit={pagination.limit} offset={pagination.offset} onPageChange={pagination.setPage} onPageSizeChange={pagination.setPageSize} itemLabel="declared URL" isLoading={query.isFetching && !query.isLoading} /> : null;
  return <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">{controls}<div className="overflow-x-auto"><table className="mt-4 min-w-full text-left text-sm"><thead className="bg-stone-100 text-xs uppercase text-stone-500"><tr>{[["url", "URL"], ["section", "Section"], ["label", "Label"], ["optional", "Optional"], ["scope", "Scope"], ["classification", "Classification"], ["inventory", "Inventory"]].map(([column, label]) => <SortableTableHeader key={column} column={column} label={label} activeColumn={referenceSort.sort?.column ?? null} direction={referenceSort.sort?.direction ?? null} onChange={referenceSort.changeSort} />)}</tr></thead><tbody>{referenceSort.sortedItems.map((item) => <tr key={item.id} className="border-t border-stone-100 align-top"><td className="max-w-sm px-3 py-2"><span className="block truncate font-mono text-xs">{item.normalized_target_url ?? item.raw_url}</span>{item.description ? <span className="mt-1 block text-xs text-stone-500">{item.description}</span> : null}</td><td className="px-3 py-2">{item.section_title ?? "Unsectioned"}</td><td className="px-3 py-2">{item.label ?? "Unlabeled"}</td><td className="px-3 py-2">{item.optional ? "Optional" : "Required"}</td><td className="px-3 py-2">{formatStatus(item.scope_decision)}</td><td className="px-3 py-2">{formatStatus(item.inferred_kind)}</td><td className="px-3 py-2">{item.inventory_entry_id ? "Current origin" : "Reference only"}</td></tr>)}</tbody></table></div>{controls ? <div className="mt-4">{controls}</div> : null}</section>;
}

function Validation({ sourceId, refreshId }: { sourceId: string; refreshId: number | null }) {
  const query = useQuery({ queryKey: ["ai-validation", sourceId, refreshId], queryFn: () => listAiValidations(sourceId, refreshId!), enabled: refreshId != null });
  if (!refreshId) return <EmptyState title="Not validated" message="No AI document refresh has been recorded. A missing llms.txt file is not a Site failure." />;
  if (query.isLoading) return <LoadingBlock label="Loading validation evidence..." />;
  return <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm"><h2 className="text-base font-semibold">Evidence-based diagnostics</h2><p className="mt-1 text-sm text-stone-600">Declarations describe saved evidence; they do not override robots policy or authorize crawling. llms-full.txt is optional.</p>{query.data?.length ? <ul className="mt-4 divide-y divide-stone-100">{query.data.map((item) => <li key={item.id} className="py-3"><strong className="text-sm">{formatStatus(item.code)}</strong><p className="text-sm text-stone-600">{item.message}</p></li>)}</ul> : <EmptyState title="No validation messages" message="The latest retained refresh produced no diagnostics." />}</section>;
}

function History({ sourceId }: { sourceId: string }) {
  const pagination = useUrlPagination({ prefix: "ai_history" });
  const query = useQuery({ queryKey: ["ai-history", sourceId, pagination.limit, pagination.offset], queryFn: () => listAiDocumentRefreshes(sourceId, `?limit=${pagination.limit}&offset=${pagination.offset}`), placeholderData: (previous) => previous });
  const historyItems = query.data?.items ?? [];
  const historyValues = { refresh: (item: (typeof historyItems)[number]) => Date.parse(item.created_at), status: (item: (typeof historyItems)[number]) => item.status, saved: (item: (typeof historyItems)[number]) => item.document_saved_count, changed: (item: (typeof historyItems)[number]) => item.document_changed_count, unchanged: (item: (typeof historyItems)[number]) => item.document_unchanged_count, failures: (item: (typeof historyItems)[number]) => item.document_failed_count, references: (item: (typeof historyItems)[number]) => item.reference_count, retained: (item: (typeof historyItems)[number]) => item.total_retained_bytes };
  const historySort = useTableSort(historyItems, historyValues);
  useEffect(() => pagination.ensureValid(query.data?.total), [query.data?.total, pagination]);
  const controls = query.data ? <PaginatedTableControls total={query.data.total} limit={pagination.limit} offset={pagination.offset} onPageChange={pagination.setPage} onPageSizeChange={pagination.setPageSize} itemLabel="refresh" isLoading={query.isFetching && !query.isLoading} /> : null;
  return <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">{controls}<div className="overflow-x-auto"><table className="mt-4 min-w-full text-left text-sm"><thead className="bg-stone-100 text-xs uppercase text-stone-500"><tr>{[["refresh", "Refresh"], ["status", "Status"], ["saved", "Saved"], ["changed", "Changed"], ["unchanged", "Unchanged"], ["failures", "Failures"], ["references", "References"], ["retained", "Retained"]].map(([column, label]) => <SortableTableHeader key={column} column={column} label={label} activeColumn={historySort.sort?.column ?? null} direction={historySort.sort?.direction ?? null} onChange={historySort.changeSort} defaultDirection={column === "refresh" ? "desc" : "asc"} />)}</tr></thead><tbody>{historySort.sortedItems.map((item) => <tr key={item.id} className="border-t border-stone-100"><td className="px-3 py-2">{formatDate(item.created_at)}</td><td className="px-3 py-2"><StatusBadge status={item.status} label={formatStatus(item.status)} /></td><td className="px-3 py-2">{item.document_saved_count}</td><td className="px-3 py-2">{item.document_changed_count}</td><td className="px-3 py-2">{item.document_unchanged_count}</td><td className="px-3 py-2">{item.document_failed_count}</td><td className="px-3 py-2">{item.reference_count}</td><td className="px-3 py-2">{formatBytes(item.total_retained_bytes)}</td></tr>)}</tbody></table></div>{controls ? <div className="mt-4">{controls}</div> : null}</section>;
}

function Settings({ source, onSaved, onDelete }: { source: Awaited<ReturnType<typeof getAiDocumentSource>>; onSaved: () => void; onDelete: () => void }) {
  const [entry, setEntry] = useState(source.entry_url);
  const [settings, setSettings] = useState<AiDocumentSettings>(source.settings);
  const [active, setActive] = useState(source.is_active);
  const save = useMutation({ mutationFn: () => updateAiDocumentSource(String(source.id), { entry_url: entry, name: source.name, discovery_mode: source.discovery_mode, is_active: active, settings }), onSuccess: onSaved });
  function submit(event: FormEvent) { event.preventDefault(); save.mutate(); }
  const numericSettings = ["max_nesting_depth", "max_index_documents", "max_total_documents", "max_individual_document_bytes", "max_total_retained_bytes", "max_total_network_bytes"] as const;
  return <form onSubmit={submit} className="space-y-5"><section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm"><label className="block text-sm font-medium">Entry URL<input value={entry} onChange={(event) => setEntry(event.target.value)} className="mt-1 w-full rounded-md border border-stone-300 px-3 py-2 font-mono text-sm" /></label><label className="mt-4 flex items-center gap-2 text-sm"><input type="checkbox" checked={active} onChange={(event) => setActive(event.target.checked)} /> Active</label><label className="mt-4 flex items-center gap-2 text-sm"><input type="checkbox" checked={settings.save_declared_documents} onChange={(event) => setSettings({ ...settings, save_declared_documents: event.target.checked })} /> Retrieve indexes and declared textual documents</label><label className="mt-3 flex items-center gap-2 text-sm"><input type="checkbox" checked={settings.follow_external_documents} onChange={(event) => setSettings({ ...settings, follow_external_documents: event.target.checked })} /> Follow external documents</label><div className="mt-4 grid gap-3 md:grid-cols-3">{numericSettings.map((key) => <label key={key} className="text-xs font-medium uppercase text-stone-500">{formatStatus(key)}<input type="number" min={1} value={settings[key]} onChange={(event) => setSettings({ ...settings, [key]: Number(event.target.value) })} className="mt-1 w-full rounded-md border border-stone-300 px-3 py-2 text-sm text-stone-950" /></label>)}</div><div className="mt-4 grid gap-3 md:grid-cols-2"><label className="text-xs font-medium uppercase text-stone-500">Request timeout seconds<input aria-label="Request timeout seconds" type="number" min={1} max={120} step={1} value={settings.request_timeout_seconds} onChange={(event) => setSettings({ ...settings, request_timeout_seconds: Number(event.target.value) })} className="mt-1 w-full rounded-md border border-stone-300 px-3 py-2 text-sm text-stone-950" /></label><label className="text-xs font-medium uppercase text-stone-500">Maximum attempts<input aria-label="Maximum attempts" type="number" min={1} max={5} step={1} value={settings.max_attempts} onChange={(event) => setSettings({ ...settings, max_attempts: Number(event.target.value) })} className="mt-1 w-full rounded-md border border-stone-300 px-3 py-2 text-sm text-stone-950" /></label></div><div className="mt-4"><Button type="submit" loading={save.isPending}>Save settings</Button></div>{save.error ? <div className="mt-3"><ErrorBanner error={save.error} title="Could not save settings" /></div> : null}</section><section className="rounded-md border border-red-200 bg-white p-4"><h2 className="font-semibold text-red-800">Delete Source</h2><p className="my-2 text-sm text-stone-600">Deletion removes this Source's refresh evidence and current origins while preserving unrelated Sites, Pages, Scans, and shared blobs.</p><Button type="button" variant="danger" onClick={onDelete}>Preview and delete</Button></section></form>;
}

function PageFrame({ children }: { children: React.ReactNode }) { return <div className="mx-auto max-w-[1500px] px-4 py-6 sm:px-6">{children}</div>; }
function setFilter(setParams: ReturnType<typeof useSearchParams>[1], key: string, value: string, offset: string) { setParams((current) => { const next = new URLSearchParams(current); if (value) next.set(key, value); else next.delete(key); next.delete(offset); return next; }); }
