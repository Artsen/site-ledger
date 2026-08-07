import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { deleteSite, listSites } from "../api/client";
import { Button } from "../components/ui/Button";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorBanner } from "../components/ui/ErrorBanner";
import { LoadingBlock } from "../components/ui/Loading";
import { PaginatedTableControls } from "../components/ui/PaginatedTableControls";
import { StatusBadge } from "../components/ui/StatusBadge";
import { SortableTableHeader, type SortDirection } from "../components/ui/SortableTableHeader";
import { inputClass } from "../components/ui/styles";
import { classificationLabel } from "../types/siteClassifications";
import type { SiteListItem } from "../types/scans";
import { formatDate } from "../utils/format";
import { useDocumentTitle } from "../utils/useDocumentTitle";
import { useUrlPagination } from "../utils/useUrlPagination";

export function SitesPage() {
  useDocumentTitle("Sites");
  const [searchParams, setSearchParams] = useSearchParams();
  const pagination = useUrlPagination({ prefix: "sites", defaultLimit: 25 });
  const queryClient = useQueryClient();
  const query = buildSiteQuery(searchParams, pagination.limit, pagination.offset);
  const sites = useQuery({ queryKey: ["sites", query], queryFn: () => listSites(query) });
  useEffect(() => pagination.ensureValid(sites.data?.total), [pagination, sites.data?.total]);
  const remove = useMutation({
    mutationFn: (site: SiteListItem) => deleteSite(String(site.id)),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["sites"] });
    }
  });
  const controls = sites.data ? <PaginatedTableControls total={sites.data.total} limit={pagination.limit} offset={pagination.offset} onPageChange={pagination.setPage} onPageSizeChange={pagination.setPageSize} itemLabel="site" isLoading={sites.isFetching && !sites.isLoading} /> : null;

  return (
    <section className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
      <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="text-sm text-stone-500">Sites</div>
          <h1 className="mt-1 text-2xl font-semibold text-stone-950">Saved sites</h1>
        </div>
        <Link to="/sites/new" className="rounded-md border border-neutral-900 bg-neutral-900 px-3 py-2 text-sm font-medium text-white hover:bg-neutral-700">Create site</Link>
      </div>
      <section className="mb-4 rounded-md border border-stone-200 bg-white p-4 shadow-sm">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-4 lg:grid-cols-7">
          <input aria-label="Search sites" value={searchParams.get("search") ?? ""} onChange={(event) => updateParam(setSearchParams, "search", event.target.value || null)} placeholder="Search name or URL" className={`${inputClass()} md:col-span-2`} />
          <FilterInput label="Group" param="group_key" placeholder="Any group" searchParams={searchParams} setSearchParams={setSearchParams} />
          <input aria-label="Locale" value={searchParams.get("locale") ?? ""} onChange={(event) => updateParam(setSearchParams, "locale", event.target.value || null)} placeholder="Locale" className={inputClass()} />
          <FilterInput label="Platform" param="platform_key" placeholder="Any platform" searchParams={searchParams} setSearchParams={setSearchParams} />
          <FilterInput label="Ownership" param="ownership_key" placeholder="Any owner" searchParams={searchParams} setSearchParams={setSearchParams} />
          <select aria-label="Active state" value={searchParams.get("active_state") ?? "active"} onChange={(event) => updateParam(setSearchParams, "active_state", event.target.value === "active" ? null : event.target.value)} className={inputClass()}>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
            <option value="all">All</option>
          </select>
        </div>
        <div className="mt-3"><Button type="button" variant="ghost" onClick={() => setSearchParams({ sites_limit: String(pagination.limit), sites_offset: "0" })}>Clear filters</Button></div>
      </section>
      {sites.error || remove.error ? <ErrorBanner error={sites.error ?? remove.error} title="Site request failed" /> : null}
      {sites.isLoading ? <LoadingBlock label="Loading sites..." /> : null}
      {!sites.isLoading && !sites.data?.items.length ? <EmptyState title="No sites found" message="Create a saved site or adjust the filters." /> : null}
      {controls ? <div className="mb-4">{controls}</div> : null}
      {sites.data?.items.length ? <SitesTable sites={sites.data.items} activeSort={searchParams.get("sort")} direction={searchParams.get("direction") as SortDirection | null} onSort={(column, direction) => setTableSort(setSearchParams, column, direction, "sites_offset")} onDelete={(site) => {
        if (window.confirm(`Delete ${site.name}? Sites with scans cannot be deleted.`)) remove.mutate(site);
      }} /> : null}
      {controls ? <div className="mt-4">{controls}</div> : null}
    </section>
  );
}

function SitesTable({ sites, activeSort, direction, onSort, onDelete }: { sites: SiteListItem[]; activeSort: string | null; direction: SortDirection | null; onSort: (column: string | null, direction: SortDirection | null) => void; onDelete: (site: SiteListItem) => void }) {
  const columns = [
    ["name", "Site"],
    ["classification", "Classification"],
    ["state", "State"],
    ["latest_scan_at", "Latest scan"],
    ["scan_count", "Scans"],
  ];
  return (
    <div className="overflow-x-auto rounded-md border border-stone-200 bg-white shadow-sm">
      <table className="min-w-full text-left text-sm">
        <thead className="bg-stone-100 text-xs uppercase text-stone-500">
          <tr>{columns.map(([column, label]) => <SortableTableHeader key={column} column={column} label={label} activeColumn={activeSort} direction={direction} onChange={onSort} />)}<th className="px-3 py-2 font-medium">Actions</th></tr>
        </thead>
        <tbody>
          {sites.map((site) => (
            <tr key={site.id} className="border-t border-stone-100 align-top">
              <td className="max-w-md px-3 py-2">
                <Link to={`/sites/${site.id}`} className="block truncate font-medium underline">{site.name}</Link>
                <span className="block truncate font-mono text-xs text-stone-500">{site.base_url}</span>
              </td>
              <td className="px-3 py-2 text-xs text-stone-600">
                <span className="block">{classificationLabel(site.group_key)}</span>
                <span className="block">{classificationLabel(site.platform_key)}</span>
                <span className="block">{classificationLabel(site.ownership_key)}{site.locale ? `, ${site.locale}` : ""}</span>
              </td>
              <td className="px-3 py-2"><StatusBadge status={site.is_active ? "completed" : "interrupted"} label={site.is_active ? "Active" : "Inactive"} /></td>
              <td className="px-3 py-2">{site.latest_scan_status ? <><StatusBadge status={site.latest_scan_status} /><span className="mt-1 block text-xs text-stone-500">{formatDate(site.latest_scan_date)}</span></> : "No scans"}</td>
              <td className="px-3 py-2">{site.total_scan_count}</td>
              <td className="px-3 py-2">
                <div className="flex flex-wrap gap-2">
                  <Link className="underline" to={`/sites/${site.id}`}>Open</Link>
                  <Link className="underline" to={`/scans/new?site_id=${site.id}`}>Run scan</Link>
                  <Link className="underline" to={`/sites/${site.id}/edit`}>Edit</Link>
                  {site.total_scan_count === 0 ? <button type="button" className="text-red-700 underline" onClick={() => onDelete(site)}>Delete</button> : null}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function setTableSort(setSearchParams: ReturnType<typeof useSearchParams>[1], column: string | null, direction: SortDirection | null, offsetKey: string) {
  setSearchParams((current) => {
    const next = new URLSearchParams(current);
    if (column && direction) { next.set("sort", column); next.set("direction", direction); }
    else { next.delete("sort"); next.delete("direction"); }
    next.delete(offsetKey);
    return next;
  });
}

function FilterInput({ label, param, placeholder, searchParams, setSearchParams }: { label: string; param: string; placeholder: string; searchParams: URLSearchParams; setSearchParams: ReturnType<typeof useSearchParams>[1] }) {
  return (
    <input aria-label={label} value={searchParams.get(param) ?? ""} onChange={(event) => updateParam(setSearchParams, param, event.target.value || null)} placeholder={placeholder} className={inputClass()} />
  );
}

function buildSiteQuery(searchParams: URLSearchParams, limit: number, offset: number) {
  const params = new URLSearchParams();
  for (const key of ["search", "group_key", "locale", "platform_key", "ownership_key", "active_state", "sort", "direction"]) {
    const value = searchParams.get(key);
    if (value) params.set(key, value);
  }
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  return `?${params.toString()}`;
}

function updateParam(setSearchParams: ReturnType<typeof useSearchParams>[1], key: string, value: string | null, resetOffset = true) {
  setSearchParams((current) => {
    const next = new URLSearchParams(current);
    if (value) next.set(key, value);
    else next.delete(key);
    if (resetOffset) next.delete("sites_offset");
    return next;
  });
}
