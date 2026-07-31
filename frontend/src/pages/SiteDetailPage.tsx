import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import {
  addManualUrls,
  createSource,
  deleteSite,
  deleteSource,
  discoverRobots,
  getSite,
  listInventory,
  listSources,
  refreshSource,
  updateSite
} from "../api/client";
import { Button } from "../components/ui/Button";
import { DefinitionList } from "../components/ui/DefinitionList";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorBanner } from "../components/ui/ErrorBanner";
import { Field } from "../components/ui/Field";
import { LoadingBlock } from "../components/ui/Loading";
import { StatusBadge } from "../components/ui/StatusBadge";
import { classificationLabel } from "../types/siteClassifications";
import type { InventoryItem, Site, UrlSource } from "../types/scans";
import { formatDate, plural } from "../utils/format";

export function SiteDetailPage() {
  const { siteId = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = searchParams.get("tab") ?? "overview";
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const site = useQuery({ queryKey: ["site", siteId], queryFn: () => getSite(siteId) });
  const toggleActive = useMutation({
    mutationFn: (next: boolean) => updateSite(siteId, { is_active: next }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["site", siteId] });
      await queryClient.invalidateQueries({ queryKey: ["sites"] });
    }
  });
  const remove = useMutation({
    mutationFn: () => deleteSite(siteId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["sites"] });
      navigate("/sites");
    }
  });

  if (site.isLoading) return <PageFrame><LoadingBlock label="Loading site..." /></PageFrame>;
  if (site.error) return <PageFrame><ErrorBanner error={site.error} title="Could not load site" /></PageFrame>;
  if (!site.data) return <PageFrame><EmptyState title="Site not found" message="The saved site may have been deleted." /></PageFrame>;

  return (
    <PageFrame>
      <div className="mb-5 flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="mb-2 text-sm text-stone-500"><Link to="/sites" className="underline">Sites</Link> / {site.data.name}</div>
          <h1 className="truncate text-2xl font-semibold">{site.data.name}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <StatusBadge status={site.data.is_active ? "completed" : "interrupted"} label={site.data.is_active ? "Active" : "Inactive"} />
            <span className="font-mono text-xs text-stone-600">{site.data.base_url}</span>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {site.data.is_active ? <Link className="rounded-md border border-neutral-900 bg-neutral-900 px-3 py-2 text-sm font-medium text-white" to={`/scans/new?site_id=${site.data.id}`}>Run scan</Link> : null}
          <Link className="rounded-md border border-stone-300 bg-white px-3 py-2 text-sm font-medium" to={`/sites/${site.data.id}/edit`}>Edit site</Link>
          <Button type="button" loading={toggleActive.isPending} onClick={() => toggleActive.mutate(!site.data!.is_active)}>{site.data.is_active ? "Disable" : "Reactivate"}</Button>
          {site.data.total_scan_count === 0 ? <Button type="button" variant="danger" loading={remove.isPending} onClick={() => {
            if (window.confirm(`Delete ${site.data?.name}? This cannot be undone.`)) remove.mutate();
          }}>Delete</Button> : null}
        </div>
      </div>
      {toggleActive.error || remove.error ? <ErrorBanner error={toggleActive.error ?? remove.error} title="Site action failed" /> : null}
      <div className="mb-5 flex gap-2 border-b border-stone-200 text-sm">
        {["overview", "scans", "sources", "inventory"].map((item) => (
          <button key={item} type="button" onClick={() => setTab(setSearchParams, item)} className={`border-b-2 px-3 py-2 capitalize ${tab === item ? "border-neutral-900 text-neutral-900" : "border-transparent text-stone-500"}`}>{item}</button>
        ))}
      </div>
      {tab === "overview" ? <OverviewTab site={site.data} /> : null}
      {tab === "scans" ? <ScansTab site={site.data} /> : null}
      {tab === "sources" ? <SourcesTab site={site.data} /> : null}
      {tab === "inventory" ? <InventoryTab site={site.data} /> : null}
    </PageFrame>
  );
}

function PageFrame({ children }: { children: React.ReactNode }) {
  return <section className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">{children}</section>;
}

function OverviewTab({ site }: { site: Site }) {
  return (
    <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
      <div className="space-y-5">
        <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
          <h2 className="mb-4 text-base font-semibold">Site details</h2>
          <DefinitionList items={[
            { label: "Base URL", value: site.base_url, copyValue: site.base_url },
            { label: "Description", value: site.description ?? "Not provided" },
            { label: "Group", value: classificationLabel(site.group_key) },
            { label: "Locale", value: site.locale ?? "Not specified" },
            { label: "Platform", value: classificationLabel(site.platform_key) },
            { label: "Ownership", value: classificationLabel(site.ownership_key) },
            { label: "Created", value: formatDate(site.created_at) },
            { label: "Updated", value: formatDate(site.updated_at) }
          ]} />
        </section>
        <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
          <h2 className="mb-3 text-base font-semibold">Saved scope</h2>
          <ScopeSummary site={site} />
          <details className="mt-4">
            <summary className="cursor-pointer text-sm font-medium">View saved scope JSON</summary>
            <pre className="mt-3 max-h-80 overflow-auto rounded-md border border-stone-200 bg-stone-50 p-3 text-xs">{JSON.stringify(site.scope_config, null, 2)}</pre>
          </details>
        </section>
      </div>
      <ScansTab site={site} compact />
    </div>
  );
}

function ScansTab({ site, compact = false }: { site: Site; compact?: boolean }) {
  return (
    <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
      <h2 className="mb-3 text-base font-semibold">Recent scans</h2>
      <div className="mb-3 text-sm text-stone-600">{plural(site.total_scan_count, "scan")}</div>
      {site.recent_scans.length ? (
        <div className={compact ? "space-y-2" : "grid grid-cols-1 gap-2 md:grid-cols-2"}>
          {site.recent_scans.map((scan) => (
            <Link key={scan.id} to={`/scans/${scan.id}`} className="block rounded-md border border-stone-200 px-3 py-2 text-sm hover:bg-stone-50">
              <StatusBadge status={scan.status} />
              <span className="mt-1 block text-xs text-stone-500">{formatDate(scan.created_at)} - {scan.discovered_count} discovered - {scan.failed_count} failed</span>
            </Link>
          ))}
        </div>
      ) : <EmptyState title="No scans yet" message="Run a scan from this site to build history." />}
    </section>
  );
}

function SourcesTab({ site }: { site: Site }) {
  const queryClient = useQueryClient();
  const [sitemapUrl, setSitemapUrl] = useState("");
  const [manualUrls, setManualUrls] = useState("");
  const sources = useQuery({ queryKey: ["sources", String(site.id)], queryFn: () => listSources(String(site.id), "?active_state=all&limit=100") });
  const addSitemap = useMutation({
    mutationFn: () => createSource(String(site.id), { source_type: "sitemap", name: sitemapUrl, source_url: sitemapUrl, is_active: true, discovery_mode: "configured", settings_json: {} }),
    onSuccess: async () => {
      setSitemapUrl("");
      await queryClient.invalidateQueries({ queryKey: ["sources", String(site.id)] });
    }
  });
  const refresh = useMutation({
    mutationFn: (source: UrlSource) => refreshSource(String(site.id), String(source.id)),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["sources", String(site.id)] });
      await queryClient.invalidateQueries({ queryKey: ["inventory", String(site.id)] });
    }
  });
  const robots = useMutation({
    mutationFn: () => discoverRobots(String(site.id)),
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: ["sources", String(site.id)] })
  });
  const manual = useMutation({
    mutationFn: () => addManualUrls(String(site.id), manualUrls),
    onSuccess: async () => {
      setManualUrls("");
      await queryClient.invalidateQueries({ queryKey: ["sources", String(site.id)] });
      await queryClient.invalidateQueries({ queryKey: ["inventory", String(site.id)] });
    }
  });
  const remove = useMutation({
    mutationFn: (source: UrlSource) => deleteSource(String(site.id), String(source.id)),
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: ["sources", String(site.id)] })
  });

  function submitSitemap(event: FormEvent) {
    event.preventDefault();
    if (sitemapUrl.trim()) addSitemap.mutate();
  }

  return (
    <div className="space-y-5">
      {addSitemap.error || refresh.error || robots.error || manual.error || remove.error ? <ErrorBanner error={addSitemap.error ?? refresh.error ?? robots.error ?? manual.error ?? remove.error} title="Source request failed" /> : null}
      <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
        <div className="flex flex-col gap-3 md:flex-row md:items-end">
          <form onSubmit={submitSitemap} className="flex flex-1 flex-col gap-2 md:flex-row md:items-end">
            <Field id="sitemap-url" label="Sitemap source">
              <input id="sitemap-url" value={sitemapUrl} onChange={(event) => setSitemapUrl(event.target.value)} placeholder="https://www.example.com/sitemap.xml" className="w-full rounded-md border border-stone-300 px-3 py-2 text-sm" />
            </Field>
            <Button type="submit" loading={addSitemap.isPending}>Add sitemap</Button>
          </form>
          <Button type="button" loading={robots.isPending} onClick={() => robots.mutate()}>Discover from robots.txt</Button>
        </div>
      </section>
      <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
        <h2 className="mb-3 text-base font-semibold">Manual URLs</h2>
        <textarea value={manualUrls} onChange={(event) => setManualUrls(event.target.value)} rows={5} className="w-full rounded-md border border-stone-300 px-3 py-2 font-mono text-xs" placeholder={"/manual-page/\nhttps://www.example.com/landing"} />
        <div className="mt-2"><Button type="button" loading={manual.isPending} disabled={!manualUrls.trim()} onClick={() => manual.mutate()}>Add manual URLs</Button></div>
        {manual.data ? <div className="mt-2 text-sm text-stone-600">{manual.data.accepted_count} accepted - {manual.data.rejected_count} rejected - {manual.data.duplicate_count} duplicates</div> : null}
      </section>
      <section className="rounded-md border border-stone-200 bg-white shadow-sm">
        <h2 className="p-4 text-base font-semibold">Sources</h2>
        {sources.isLoading ? <LoadingBlock label="Loading sources..." /> : null}
        {sources.data?.items.length ? <SourceTable sources={sources.data.items} onRefresh={(source) => refresh.mutate(source)} onDelete={(source) => {
          if (window.confirm(`Delete source ${source.name}? Scan history will be preserved.`)) remove.mutate(source);
        }} /> : !sources.isLoading ? <EmptyState title="No sources" message="Add a sitemap, discover from robots.txt, or paste manual URLs." /> : null}
      </section>
    </div>
  );
}

function SourceTable({ sources, onRefresh, onDelete }: { sources: UrlSource[]; onRefresh: (source: UrlSource) => void; onDelete: (source: UrlSource) => void }) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-left text-sm">
        <thead className="bg-stone-100 text-xs uppercase text-stone-500"><tr>{["Source", "Type", "Status", "URLs", "Actions"].map((header) => <th key={header} className="px-3 py-2">{header}</th>)}</tr></thead>
        <tbody>
          {sources.map((source) => (
            <tr key={source.id} className="border-t border-stone-100">
              <td className="max-w-md px-3 py-2"><span className="block font-medium">{source.name}</span><span className="block truncate font-mono text-xs text-stone-500">{source.source_url ?? "Manual collection"}</span></td>
              <td className="px-3 py-2 capitalize">{source.source_type}</td>
              <td className="px-3 py-2"><StatusBadge status={source.last_refresh_status ?? "queued"} label={source.last_refresh_status ?? "Never refreshed"} /></td>
              <td className="px-3 py-2">{source.current_entry_count}</td>
              <td className="px-3 py-2"><div className="flex gap-2"><button type="button" className="underline" onClick={() => onRefresh(source)}>Refresh</button><button type="button" className="text-red-700 underline" onClick={() => onDelete(source)}>Delete</button></div></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function InventoryTab({ site }: { site: Site }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const query = new URLSearchParams();
  for (const key of ["search", "source_type", "scope_decision", "validation_state", "offset"]) {
    const value = searchParams.get(key);
    if (value) query.set(key, value);
  }
  const inventory = useQuery({ queryKey: ["inventory", String(site.id), query.toString()], queryFn: () => listInventory(String(site.id), `?${query.toString()}`) });
  return (
    <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
      <div className="mb-4 grid grid-cols-1 gap-3 md:grid-cols-4">
        <input aria-label="Search inventory" value={searchParams.get("search") ?? ""} onChange={(event) => setSearchParam(setSearchParams, "search", event.target.value)} placeholder="Search URLs" className="rounded-md border border-stone-300 px-3 py-2 text-sm" />
        <input aria-label="Source type" value={searchParams.get("source_type") ?? ""} onChange={(event) => setSearchParam(setSearchParams, "source_type", event.target.value)} placeholder="Source type" className="rounded-md border border-stone-300 px-3 py-2 text-sm" />
        <input aria-label="Scope state" value={searchParams.get("scope_decision") ?? ""} onChange={(event) => setSearchParam(setSearchParams, "scope_decision", event.target.value)} placeholder="Scope state" className="rounded-md border border-stone-300 px-3 py-2 text-sm" />
        <input aria-label="Validation state" value={searchParams.get("validation_state") ?? ""} onChange={(event) => setSearchParam(setSearchParams, "validation_state", event.target.value)} placeholder="Validation state" className="rounded-md border border-stone-300 px-3 py-2 text-sm" />
      </div>
      {inventory.isLoading ? <LoadingBlock label="Loading inventory..." /> : null}
      {inventory.data?.items.length ? <InventoryTable items={inventory.data.items} /> : !inventory.isLoading ? <EmptyState title="No inventory URLs" message="Refresh a source or add manual URLs to build this inventory." /> : null}
    </section>
  );
}

function InventoryTable({ items }: { items: InventoryItem[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-left text-sm">
        <thead className="bg-stone-100 text-xs uppercase text-stone-500"><tr>{["URL", "Sources", "Scope", "Validation", "Classification"].map((header) => <th key={header} className="px-3 py-2">{header}</th>)}</tr></thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.normalized_url ?? item.sources.map((source) => source.entry_id).join(",")} className="border-t border-stone-100 align-top">
              <td className="max-w-xl px-3 py-2 font-mono text-xs">{item.normalized_url ?? "Invalid URL"}</td>
              <td className="px-3 py-2">{item.source_count}<details><summary className="cursor-pointer text-xs underline">View</summary><ul className="mt-1 space-y-1 text-xs">{item.sources.map((source) => <li key={String(source.entry_id)}>{String(source.name)} - {String(source.type)}</li>)}</ul></details></td>
              <td className="px-3 py-2">{item.scope_decision}</td>
              <td className="px-3 py-2">{item.validation_state}</td>
              <td className="px-3 py-2">{item.classification}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ScopeSummary({ site }: { site: Site }) {
  const scope = site.scope_config;
  const allowed = scope.allowed_host_patterns.length;
  const included = scope.included_path_prefixes.filter((path) => path !== "/").length;
  return (
    <div className="flex flex-wrap gap-2 text-xs">
      <span className="rounded-md border border-stone-200 bg-stone-50 px-2 py-1">{allowed ? plural(allowed, "allowed host") : `Exact hostname from ${new URL(site.base_url).hostname}`}</span>
      <span className="rounded-md border border-stone-200 bg-stone-50 px-2 py-1">{scope.follow_subdomains ? "Subdomains included" : "Subdomains excluded"}</span>
      <span className="rounded-md border border-stone-200 bg-stone-50 px-2 py-1">{included ? plural(included, "included path") : "All paths included"}</span>
      <span className="rounded-md border border-stone-200 bg-stone-50 px-2 py-1">Maximum {scope.max_pages} pages</span>
      <span className="rounded-md border border-stone-200 bg-stone-50 px-2 py-1">Maximum depth {scope.max_depth}</span>
    </div>
  );
}

function setTab(setSearchParams: ReturnType<typeof useSearchParams>[1], tab: string) {
  setSearchParams((current) => {
    const next = new URLSearchParams(current);
    next.set("tab", tab);
    return next;
  });
}

function setSearchParam(setSearchParams: ReturnType<typeof useSearchParams>[1], key: string, value: string) {
  setSearchParams((current) => {
    const next = new URLSearchParams(current);
    if (value) next.set(key, value);
    else next.delete(key);
    return next;
  });
}
