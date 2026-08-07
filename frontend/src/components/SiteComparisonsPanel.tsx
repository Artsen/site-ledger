import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import {
  cancelComparison,
  createComparison,
  deleteComparison,
  getComparison,
  getComparisonStatus,
  listComparisonLinks,
  listComparisonPages,
  listComparisonResources,
  listComparisons,
  listSiteScans,
  rebuildComparison,
} from "../api/client";
import type { ComparisonLink, ComparisonPage, ComparisonResource, ComparisonScan, ScanComparisonBuild } from "../types/comparisons";
import type { Site } from "../types/scans";
import {
  comparisonIsBuilding,
  comparisonStatusRefetchInterval,
  immutableComparisonQueryOptions,
} from "../utils/comparisonQueryOptions";
import { formatDate, formatStatus } from "../utils/format";
import { useUrlPagination } from "../utils/useUrlPagination";
import { Button } from "./ui/Button";
import { EmptyState } from "./ui/EmptyState";
import { ErrorBanner } from "./ui/ErrorBanner";
import { LoadingBlock } from "./ui/Loading";
import { PaginatedTableControls } from "./ui/PaginatedTableControls";
import { SortableTableHeader, type SortDirection } from "./ui/SortableTableHeader";
import { StatusBadge } from "./ui/StatusBadge";
import { Tabs } from "./ui/Tabs";

const TERMINAL = new Set(["completed", "completed_with_errors", "failed", "cancelled", "interrupted"]);
const AUTOMATIC = new Set(["completed", "completed_with_errors"]);

export function SiteComparisonsPanel({ site }: { site: Site }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const selectedId = searchParams.get("comparison_id") ?? "";
  const comparisons = useQuery({
    queryKey: ["comparisons", String(site.id)],
    queryFn: () => listComparisons(String(site.id), "?limit=100"),
  });
  const scans = useQuery({
    queryKey: ["site-comparison-scans", String(site.id)],
    queryFn: () => listSiteScans(String(site.id), "?limit=250&sort=created_at&direction=desc"),
  });
  const eligible = useMemo(
    () => (scans.data?.items ?? []).filter((scan) => TERMINAL.has(scan.status)),
    [scans.data?.items],
  );
  const defaults = useMemo(() => {
    const preferred = eligible.filter((scan) => AUTOMATIC.has(scan.status));
    const candidates = preferred.length >= 2 ? preferred : eligible;
    return { target: candidates[0]?.id ?? 0, baseline: candidates[1]?.id ?? 0 };
  }, [eligible]);
  const [baselineId, setBaselineId] = useState(0);
  const [targetId, setTargetId] = useState(0);
  useEffect(() => {
    if (!baselineId && defaults.baseline) setBaselineId(defaults.baseline);
    if (!targetId && defaults.target) setTargetId(defaults.target);
  }, [baselineId, defaults, targetId]);
  const create = useMutation({
    mutationFn: () => createComparison(String(site.id), baselineId, targetId),
    onSuccess: async (data) => {
      await queryClient.invalidateQueries({ queryKey: ["comparisons", String(site.id)] });
      setComparisonParam(setSearchParams, "comparison_id", String(data.comparison.id));
    },
  });

  return (
    <div className="space-y-5">
      <section className="border-b border-stone-200 pb-5">
        <h2 className="text-base font-semibold">Compare prepared Scan results</h2>
        <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
          <label className="text-sm">
            <span className="mb-1 block font-medium">Baseline Scan</span>
            <select aria-label="Baseline Scan" value={baselineId || ""} onChange={(event) => setBaselineId(Number(event.target.value))} className="w-full rounded-md border border-stone-300 bg-white px-3 py-2">
              <option value="">Choose older Scan</option>
              {eligible.map((scan) => <option key={scan.id} value={scan.id}>Scan {scan.id} - {formatStatus(scan.status)} - {formatDate(scan.created_at, { timeZone: site.display_timezone })}</option>)}
            </select>
          </label>
          <label className="text-sm">
            <span className="mb-1 block font-medium">Target Scan</span>
            <select aria-label="Target Scan" value={targetId || ""} onChange={(event) => setTargetId(Number(event.target.value))} className="w-full rounded-md border border-stone-300 bg-white px-3 py-2">
              <option value="">Choose newer Scan</option>
              {eligible.map((scan) => <option key={scan.id} value={scan.id}>Scan {scan.id} - {formatStatus(scan.status)} - {formatDate(scan.created_at, { timeZone: site.display_timezone })}</option>)}
            </select>
          </label>
          <Button type="button" className="self-end" loading={create.isPending} disabled={!baselineId || !targetId || baselineId === targetId} onClick={() => create.mutate()}>Compare</Button>
        </div>
        {baselineId === targetId && baselineId ? <p className="mt-2 text-sm text-red-700">Baseline and Target must be different Scans.</p> : null}
        {create.error ? <div className="mt-3"><ErrorBanner error={create.error} title="Could not start comparison" /></div> : null}
      </section>

      {comparisons.isLoading ? <LoadingBlock label="Loading comparison history..." /> : null}
      {comparisons.error ? <ErrorBanner error={comparisons.error} title="Could not load comparisons" /> : null}
      {comparisons.data?.items.length ? (
        <div className="flex flex-wrap gap-2" aria-label="Comparison history">
          {comparisons.data.items.map((comparison) => (
            <button key={comparison.id} type="button" onClick={() => setComparisonParam(setSearchParams, "comparison_id", String(comparison.id))} className={`border-b-2 px-2 py-2 text-left text-sm ${selectedId === String(comparison.id) ? "border-neutral-900 font-semibold" : "border-transparent text-stone-600"}`}>
              Scan {comparison.baseline_scan_id} to {comparison.target_scan_id}
              <span className="ml-2 text-xs text-stone-500">{formatStatus(comparison.active_build?.status ?? comparison.current_build?.status ?? "queued")}</span>
            </button>
          ))}
        </div>
      ) : !comparisons.isLoading ? <EmptyState title="No comparisons yet" message="Choose two terminal Scans to create the first deterministic comparison." /> : null}
      {selectedId ? <ComparisonWorkspace site={site} comparisonId={selectedId} /> : null}
    </div>
  );
}

function ComparisonWorkspace({ site, comparisonId }: { site: Site; comparisonId: string }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const tab = searchParams.get("comparison_tab") ?? "overview";
  const status = useQuery({
    queryKey: ["comparison-status", String(site.id), comparisonId],
    queryFn: () => getComparisonStatus(String(site.id), comparisonId),
    refetchInterval: (query) => comparisonStatusRefetchInterval(query.state.data),
    refetchOnWindowFocus: false,
  });
  const readyBuildId = status.data?.comparison.current_build_id;
  const ready = useQuery({
    queryKey: ["comparison", String(site.id), comparisonId, readyBuildId],
    queryFn: () => getComparison(String(site.id), comparisonId),
    enabled: Boolean(readyBuildId),
    ...immutableComparisonQueryOptions,
  });
  const data = ready.data
    ? {
        ...ready.data,
        comparison: {
          ...ready.data.comparison,
          active_build: status.data?.comparison.active_build ?? null,
        },
      }
    : status.data;
  const rebuild = useMutation({
    mutationFn: () => rebuildComparison(String(site.id), comparisonId),
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: ["comparison-status", String(site.id), comparisonId] }),
  });
  const cancel = useMutation({
    mutationFn: () => cancelComparison(String(site.id), comparisonId),
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: ["comparison-status", String(site.id), comparisonId] }),
  });
  const remove = useMutation({
    mutationFn: () => deleteComparison(String(site.id), comparisonId),
    onSuccess: async () => {
      queryClient.removeQueries({ queryKey: ["comparison", String(site.id), comparisonId] });
      queryClient.removeQueries({ queryKey: ["comparison-status", String(site.id), comparisonId] });
      await queryClient.invalidateQueries({ queryKey: ["comparisons", String(site.id)] });
      setComparisonParam(setSearchParams, "comparison_id", "");
    },
  });
  if (status.isLoading) return <LoadingBlock label="Loading comparison..." />;
  if (status.error) return <ErrorBanner error={status.error} title="Could not load comparison" />;
  if (!data) return null;
  const active = data.comparison.active_build;
  const building = comparisonIsBuilding(data);
  return (
    <section className="space-y-4">
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-stone-200 pb-4">
        <div>
          <h2 className="text-lg font-semibold">Scan {data.comparison.baseline_scan_id} to Scan {data.comparison.target_scan_id}</h2>
          <p className="mt-1 text-sm text-stone-600">Baseline is always shown first. Absence means not observed in Target, not removal from the website.</p>
        </div>
        <div className="flex gap-2">
          {building ? <Button type="button" onClick={() => cancel.mutate()} loading={cancel.isPending}>Cancel</Button> : <Button type="button" onClick={() => rebuild.mutate()} loading={rebuild.isPending}>Rebuild</Button>}
          <Button type="button" variant="danger" loading={remove.isPending} disabled={building} onClick={() => { if (window.confirm("Delete this derived comparison? Scan evidence will remain.")) remove.mutate(); }}>Delete</Button>
        </div>
      </header>
      {active ? <BuildState build={active} /> : null}
      {rebuild.error || cancel.error || remove.error ? <ErrorBanner error={rebuild.error ?? cancel.error ?? remove.error} title="Comparison action failed" /> : null}
      {data.comparison.current_build ? (
        <>
          <Tabs tabs={[{ id: "overview", label: "Overview" }, { id: "pages", label: "Pages", count: data.comparison.current_build.page_result_count }, { id: "resources", label: "Resources", count: data.comparison.current_build.resource_result_count }, { id: "links", label: "Links", count: data.comparison.current_build.link_result_count }]} active={tab} onChange={(next) => setComparisonTab(setSearchParams, next)} />
          {tab === "overview" ? <ComparisonOverview data={data} site={site} /> : null}
          {tab === "pages" ? <ComparisonPages siteId={String(site.id)} comparisonId={comparisonId} /> : null}
          {tab === "resources" ? <ComparisonResources siteId={String(site.id)} comparisonId={comparisonId} /> : null}
          {tab === "links" ? <ComparisonLinks siteId={String(site.id)} comparisonId={comparisonId} /> : null}
        </>
      ) : !active ? <EmptyState title="Comparison is not ready" message="Prepared Scan results are required before comparison can begin." /> : null}
    </section>
  );
}

function BuildState({ build }: { build: ScanComparisonBuild }) {
  const total = build.validation_json ? build.page_result_count + build.resource_result_count + build.link_result_count : 0;
  return <div className="border-l-4 border-amber-500 bg-amber-50 px-4 py-3 text-sm"><strong>{build.status === "waiting_for_projections" ? "Preparing Scan results" : "Building comparison"}</strong><span className="ml-2 text-stone-600">{formatStatus(build.status)}{total ? ` - ${total.toLocaleString()} results staged` : ""}</span>{build.error_message ? <p className="mt-1 text-red-700">{build.error_message}</p> : null}</div>;
}

function ComparisonOverview({ data, site }: { data: import("../types/comparisons").ScanComparisonOverview; site: Site }) {
  const build = data.comparison.current_build!;
  return <div className="space-y-5 pt-4">
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <ScanSide label="Baseline" scan={data.comparison.baseline_scan} timezone={site.display_timezone} projection={build.baseline_projection_version} />
      <ScanSide label="Target" scan={data.comparison.target_scan} timezone={site.display_timezone} projection={build.target_projection_version} />
    </div>
    <section className="border-y border-stone-200 py-4"><div className="flex flex-wrap items-center gap-3"><StatusBadge status={build.coverage_state ?? "limited"} label={formatStatus(build.coverage_state ?? "limited")} /><span className="text-sm text-stone-600">Coverage describes collection comparability, not confidence.</span></div>{build.warnings_json.length ? <ul className="mt-3 grid gap-1 text-sm text-amber-800">{build.warnings_json.map((warning) => <li key={warning}>{formatStatus(warning)}</li>)}</ul> : null}</section>
    {data.summary ? <div className="grid grid-cols-1 gap-4 md:grid-cols-3"><Summary label="Pages" values={data.summary.pages} /><Summary label="Resources" values={data.summary.resources} /><Summary label="Links" values={data.summary.links} /></div> : null}
    <dl className="grid grid-cols-1 gap-3 text-sm md:grid-cols-2"><div><dt className="text-stone-500">Comparison version</dt><dd className="font-mono text-xs">{build.comparison_version}</dd></div><div><dt className="text-stone-500">Checksum</dt><dd className="break-all font-mono text-xs">{build.comparison_checksum_sha256}</dd></div></dl>
  </div>;
}

function ScanSide({ label, scan, timezone, projection }: { label: string; scan: ComparisonScan; timezone: string | null; projection: string | null }) {
  return <section className="border-l-2 border-stone-300 pl-4"><h3 className="font-semibold">{label}: Scan {scan.id}</h3><p className="mt-1 text-sm">{formatDate(scan.created_at, { timeZone: timezone })}</p><p className="text-sm text-stone-600">{formatStatus(scan.status)} - {scan.starting_url}</p><p className="mt-2 font-mono text-xs text-stone-500">{projection ?? "Preparing results"}</p></section>;
}

function Summary({ label, values }: { label: string; values: Record<string, number> }) {
  return <section className="border-t-2 border-neutral-900 pt-3"><h3 className="font-semibold">{label}</h3><dl className="mt-2 grid gap-1 text-sm">{Object.entries(values).slice(0, 8).map(([key, value]) => <div key={key} className="flex justify-between gap-3"><dt className="text-stone-600">{formatStatus(key)}</dt><dd className="font-medium tabular-nums">{value.toLocaleString()}</dd></div>)}</dl></section>;
}

function ComparisonPages({ siteId, comparisonId }: { siteId: string; comparisonId: string }) {
  const [params, setParams] = useSearchParams();
  const pagination = useUrlPagination({ prefix: "comparison_pages" });
  const query = comparisonQuery(params, ["comparison_search", "comparison_presence", "comparison_change", "comparison_content", "comparison_head", "comparison_sort", "comparison_direction", "comparison_show_all"]);
  query.set("changed_only", params.get("comparison_show_all") === "true" ? "false" : "true"); query.set("limit", String(pagination.limit)); query.set("offset", String(pagination.offset));
  const result = useQuery({ queryKey: ["comparison-pages", siteId, comparisonId, query.toString()], queryFn: () => listComparisonPages(siteId, comparisonId, `?${query}`), ...immutableComparisonQueryOptions });
  useEffect(() => pagination.ensureValid(result.data?.total), [pagination, result.data?.total]);
  const sort = params.get("comparison_sort"); const direction = params.get("comparison_direction") as SortDirection | null;
  return <ResultSection loading={result.isLoading} error={result.error} title="Pages" controls={<FilterRow params={params} setParams={setParams} kind="pages" />} pagination={result.data ? <PaginatedTableControls total={result.data.total} limit={pagination.limit} offset={pagination.offset} onPageChange={pagination.setPage} onPageSizeChange={pagination.setPageSize} itemLabel="Page difference" /> : null} empty={!result.data?.items.length}>
    {result.data?.items.length ? <PagesTable items={result.data.items} siteId={siteId} comparisonId={comparisonId} sort={sort} direction={direction} onSort={(column, next) => setComparisonSort(setParams, column, next)} /> : null}
  </ResultSection>;
}

function PagesTable({ items, siteId, comparisonId, sort, direction, onSort }: { items: ComparisonPage[]; siteId: string; comparisonId: string; sort: string | null; direction: SortDirection | null; onSort: (column: string | null, direction: SortDirection | null) => void }) {
  const headers = [["url", "URL"], ["presence", "Presence"], ["change", "Change"], ["baseline_status", "HTTP baseline"], ["target_status", "HTTP target"], ["changed_field_count", "Changed fields"], ["response_time_delta", "Response delta"], ["byte_delta", "Byte delta"]];
  return <Table><thead className="bg-stone-100 text-xs uppercase text-stone-500"><tr>{headers.map(([column, label]) => <SortableTableHeader key={column} column={column} label={label} activeColumn={sort} direction={direction} onChange={onSort} defaultDirection={column.includes("delta") || column === "changed_field_count" ? "desc" : "asc"} />)}<th className="px-3 py-2">Actions</th></tr></thead><tbody>{items.map((item) => <tr key={item.id} className="border-t border-stone-100 align-top"><td className="max-w-md px-3 py-2"><Link className="break-all font-mono text-xs underline" to={`/sites/${siteId}/comparisons/${comparisonId}/pages/${item.resource_id}`}>{item.normalized_url}</Link></td><td className="px-3 py-2"><StatusBadge status={item.presence_state} label={formatStatus(item.presence_state)} /></td><td className="px-3 py-2">{formatStatus(item.change_state)}</td><td className="px-3 py-2 tabular-nums">{item.baseline_http_status ?? "-"}</td><td className="px-3 py-2 tabular-nums">{item.target_http_status ?? "-"}</td><td className="px-3 py-2 tabular-nums">{item.changed_field_count}</td><td className="px-3 py-2 tabular-nums">{signed(item.response_time_ms_delta, " ms")}</td><td className="px-3 py-2 tabular-nums">{signed(item.network_bytes_delta, " B")}</td><td className="px-3 py-2"><Link className="underline" to={`/sites/${siteId}/comparisons/${comparisonId}/pages/${item.resource_id}`}>Open</Link></td></tr>)}</tbody></Table>;
}

function ComparisonResources({ siteId, comparisonId }: { siteId: string; comparisonId: string }) {
  const [params, setParams] = useSearchParams(); const pagination = useUrlPagination({ prefix: "comparison_resources" });
  const query = comparisonQuery(params, ["comparison_search", "comparison_presence", "comparison_change", "comparison_sort", "comparison_direction"]); query.set("limit", String(pagination.limit)); query.set("offset", String(pagination.offset));
  const result = useQuery({ queryKey: ["comparison-resources", siteId, comparisonId, query.toString()], queryFn: () => listComparisonResources(siteId, comparisonId, `?${query}`), ...immutableComparisonQueryOptions }); useEffect(() => pagination.ensureValid(result.data?.total), [pagination, result.data?.total]);
  return <ResultSection loading={result.isLoading} error={result.error} title="Resources" controls={<FilterRow params={params} setParams={setParams} kind="resources" />} pagination={result.data ? <PaginatedTableControls total={result.data.total} limit={pagination.limit} offset={pagination.offset} onPageChange={pagination.setPage} onPageSizeChange={pagination.setPageSize} itemLabel="Resource difference" /> : null} empty={!result.data?.items.length}>{result.data?.items.length ? <ResourcesTable items={result.data.items} siteId={siteId} comparisonId={comparisonId} sort={params.get("comparison_sort")} direction={params.get("comparison_direction") as SortDirection | null} onSort={(column, next) => setComparisonSort(setParams, column, next)} /> : null}</ResultSection>;
}

function ResourcesTable({ items, siteId, comparisonId, sort, direction, onSort }: { items: ComparisonResource[]; siteId: string; comparisonId: string; sort: string | null; direction: SortDirection | null; onSort: (column: string | null, direction: SortDirection | null) => void }) {
  const headers = [["url", "URL"], ["presence", "Presence"], ["change", "Change"], ["kind", "Kind target"], ["mime", "MIME target"], ["status", "HTTP target"], ["size_delta", "Size delta"], ["occurrence_delta", "Occurrences delta"]];
  return <Table><thead className="bg-stone-100 text-xs uppercase text-stone-500"><tr>{headers.map(([column, label]) => <SortableTableHeader key={column} column={column} label={label} activeColumn={sort} direction={direction} onChange={onSort} />)}<th className="px-3 py-2">Actions</th></tr></thead><tbody>{items.map((item) => <tr key={item.id} className="border-t border-stone-100"><td className="max-w-md break-all px-3 py-2 font-mono text-xs">{item.normalized_url}</td><td className="px-3 py-2">{formatStatus(item.presence_state)}</td><td className="px-3 py-2">{formatStatus(item.change_state)}</td><td className="px-3 py-2">{formatStatus(item.target_kind ?? item.baseline_kind ?? "unknown")}</td><td className="px-3 py-2">{item.target_mime_type ?? "-"}</td><td className="px-3 py-2">{item.target_http_status ?? "-"}</td><td className="px-3 py-2">{signed(item.declared_size_delta, " B")}</td><td className="px-3 py-2">{signed(item.occurrence_delta)}</td><td className="px-3 py-2"><Link className="underline" to={`/sites/${siteId}/comparisons/${comparisonId}/resources/${item.resource_id}`}>Open</Link></td></tr>)}</tbody></Table>;
}

function ComparisonLinks({ siteId, comparisonId }: { siteId: string; comparisonId: string }) {
  const [params, setParams] = useSearchParams(); const pagination = useUrlPagination({ prefix: "comparison_links" });
  const query = comparisonQuery(params, ["comparison_search", "comparison_presence", "comparison_change", "comparison_sort", "comparison_direction"]); query.set("limit", String(pagination.limit)); query.set("offset", String(pagination.offset));
  const result = useQuery({ queryKey: ["comparison-links", siteId, comparisonId, query.toString()], queryFn: () => listComparisonLinks(siteId, comparisonId, `?${query}`), ...immutableComparisonQueryOptions }); useEffect(() => pagination.ensureValid(result.data?.total), [pagination, result.data?.total]);
  return <ResultSection loading={result.isLoading} error={result.error} title="Links" controls={<FilterRow params={params} setParams={setParams} kind="links" />} pagination={result.data ? <PaginatedTableControls total={result.data.total} limit={pagination.limit} offset={pagination.offset} onPageChange={pagination.setPage} onPageSizeChange={pagination.setPageSize} itemLabel="Link difference" /> : null} empty={!result.data?.items.length}>{result.data?.items.length ? <LinksTable items={result.data.items} siteId={siteId} comparisonId={comparisonId} sort={params.get("comparison_sort")} direction={params.get("comparison_direction") as SortDirection | null} onSort={(column, next) => setComparisonSort(setParams, column, next)} /> : null}</ResultSection>;
}

function LinksTable({ items, siteId, comparisonId, sort, direction, onSort }: { items: ComparisonLink[]; siteId: string; comparisonId: string; sort: string | null; direction: SortDirection | null; onSort: (column: string | null, direction: SortDirection | null) => void }) {
  const headers = [["source", "Source"], ["target", "Target"], ["presence", "Presence"], ["change", "Change"], ["baseline_occurrences", "Baseline occurrences"], ["target_occurrences", "Target occurrences"], ["occurrence_delta", "Delta"]];
  return <Table><thead className="bg-stone-100 text-xs uppercase text-stone-500"><tr>{headers.map(([column, label]) => <SortableTableHeader key={column} column={column} label={label} activeColumn={sort} direction={direction} onChange={onSort} />)}<th className="px-3 py-2">Actions</th></tr></thead><tbody>{items.map((item) => <tr key={item.id} className="border-t border-stone-100 align-top"><td className="max-w-xs break-all px-3 py-2 font-mono text-xs">{item.source_url}</td><td className="max-w-xs break-all px-3 py-2 font-mono text-xs">{item.target_url}</td><td className="px-3 py-2">{formatStatus(item.presence_state)}</td><td className="px-3 py-2">{formatStatus(item.change_state)}</td><td className="px-3 py-2 tabular-nums">{item.baseline_occurrence_count}</td><td className="px-3 py-2 tabular-nums">{item.target_occurrence_count}</td><td className="px-3 py-2 tabular-nums">{signed(item.occurrence_delta)}</td><td className="px-3 py-2"><Link className="underline" to={`/sites/${siteId}/comparisons/${comparisonId}/links/${item.source_resource_id}/${item.target_resource_id}`}>Inspect</Link></td></tr>)}</tbody></Table>;
}

function FilterRow({ params, setParams, kind }: { params: URLSearchParams; setParams: ReturnType<typeof useSearchParams>[1]; kind: "pages" | "resources" | "links" }) {
  return <div className="grid grid-cols-1 gap-3 md:grid-cols-4"><input aria-label={`Search comparison ${kind}`} value={params.get("comparison_search") ?? ""} onChange={(event) => setComparisonFilter(setParams, "comparison_search", event.target.value)} placeholder={`Search ${kind}`} className="rounded-md border border-stone-300 px-3 py-2 text-sm"/><select aria-label="Presence filter" value={params.get("comparison_presence") ?? ""} onChange={(event) => setComparisonFilter(setParams, "comparison_presence", event.target.value)} className="rounded-md border border-stone-300 px-3 py-2 text-sm"><option value="">All presence states</option><option value="newly_observed">Newly observed</option><option value="observed_in_both">Observed in both</option><option value="not_observed_in_target">Not observed in Target</option></select><select aria-label="Change filter" value={params.get("comparison_change") ?? ""} onChange={(event) => setComparisonFilter(setParams, "comparison_change", event.target.value)} className="rounded-md border border-stone-300 px-3 py-2 text-sm"><option value="">All change states</option><option value="changed">Tracked changes</option><option value="no_tracked_change">No tracked change</option><option value="indeterminate">Indeterminate</option></select>{kind === "pages" ? <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={params.get("comparison_show_all") === "true"} onChange={(event) => setComparisonFilter(setParams, "comparison_show_all", event.target.checked ? "true" : "")} />Show all Pages</label> : <span />}</div>;
}

function ResultSection({ loading, error, title, controls, pagination, empty, children }: { loading: boolean; error: Error | null; title: string; controls: React.ReactNode; pagination: React.ReactNode; empty: boolean; children: React.ReactNode }) {
  return <div className="space-y-4 pt-4">{controls}{error ? <ErrorBanner error={error} title={`Could not load ${title}`} /> : null}{loading ? <LoadingBlock label={`Loading ${title}...`} /> : null}{pagination}{!loading && empty ? <EmptyState title={`No ${title} differences`} message="No comparison results match these filters." /> : children}{pagination}</div>;
}
function Table({ children }: { children: React.ReactNode }) { return <div className="overflow-x-auto border-y border-stone-200"><table className="min-w-full text-left text-sm">{children}</table></div>; }
function signed(value: number | null, suffix = "") { return value == null ? "-" : `${value > 0 ? "+" : ""}${value.toLocaleString()}${suffix}`; }

function comparisonQuery(params: URLSearchParams, keys: string[]) { const query = new URLSearchParams(); for (const key of keys) { const value = params.get(key); if (value) query.set(key.replace("comparison_", ""), value); } return query; }
function setComparisonParam(setParams: ReturnType<typeof useSearchParams>[1], key: string, value: string) { setParams((current) => { const next = new URLSearchParams(current); if (value) next.set(key, value); else next.delete(key); next.set("tab", "comparisons"); return next; }); }
function setComparisonTab(setParams: ReturnType<typeof useSearchParams>[1], tab: string) { setParams((current) => { const next = new URLSearchParams(); next.set("tab", "comparisons"); const id = current.get("comparison_id"); if (id) next.set("comparison_id", id); next.set("comparison_tab", tab); return next; }); }
function setComparisonFilter(setParams: ReturnType<typeof useSearchParams>[1], key: string, value: string) { setParams((current) => { const next = new URLSearchParams(current); if (value) next.set(key, value); else next.delete(key); next.delete("comparison_pages_offset"); next.delete("comparison_resources_offset"); next.delete("comparison_links_offset"); return next; }); }
function setComparisonSort(setParams: ReturnType<typeof useSearchParams>[1], column: string | null, direction: SortDirection | null) { setParams((current) => { const next = new URLSearchParams(current); if (column && direction) { next.set("comparison_sort", column); next.set("comparison_direction", direction); } else { next.delete("comparison_sort"); next.delete("comparison_direction"); } next.delete("comparison_pages_offset"); next.delete("comparison_resources_offset"); next.delete("comparison_links_offset"); return next; }); }
