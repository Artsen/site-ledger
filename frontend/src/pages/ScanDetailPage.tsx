import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { cancelScan, getScan, listErrors, listPages } from "../api/client";
import { Button } from "../components/ui/Button";
import { CopyButton } from "../components/ui/CopyButton";
import { DefinitionList } from "../components/ui/DefinitionList";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorBanner } from "../components/ui/ErrorBanner";
import { LoadingBlock } from "../components/ui/Loading";
import { StatusBadge } from "../components/ui/StatusBadge";
import { Tabs } from "../components/ui/Tabs";
import { inputClass } from "../components/ui/styles";
import type { Page, Scan, Snapshot } from "../types/scans";
import { compactUrl, formatDate, formatDuration, formatStatus, hostnameFromUrl, isTerminalStatus, plural } from "../utils/format";

const pageSizes = [25, 50, 100];

export function ScanDetailPage() {
  const { scanId = "" } = useParams();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const tab = searchParams.get("tab") ?? "overview";
  const [searchDraft, setSearchDraft] = useState(searchParams.get("search") ?? "");
  const scan = useQuery({
    queryKey: ["scan", scanId],
    queryFn: () => getScan(scanId),
    refetchInterval: (query) => (isTerminalStatus(query.state.data?.status ?? "") ? false : 1500),
    retry: (failureCount, error) => (error instanceof Error && error.message.includes("not be found") ? false : failureCount < 2)
  });
  const isActiveScan = Boolean(scan.data && !isTerminalStatus(scan.data.status));

  useEffect(() => {
    const timer = window.setTimeout(() => updateParam(setSearchParams, "search", searchDraft || null, { offset: null }), 350);
    return () => window.clearTimeout(timer);
  }, [searchDraft, setSearchParams]);

  const pageQuery = useMemo(() => buildPageQuery(searchParams), [searchParams]);
  const pages = useQuery({
    queryKey: ["pages", scanId, pageQuery],
    queryFn: () => listPages(scanId, pageQuery),
    refetchInterval: isActiveScan ? 2000 : false,
    placeholderData: (previous) => previous
  });
  const errors = useQuery({
    queryKey: ["errors", scanId],
    queryFn: () => listErrors(scanId),
    enabled: tab === "errors" || tab === "overview",
    refetchInterval: isActiveScan ? 3000 : false
  });
  const cancel = useMutation({
    mutationFn: () => cancelScan(scanId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["scan", scanId] });
      await queryClient.invalidateQueries({ queryKey: ["scans"] });
    }
  });

  if (scan.isLoading) return <PageFrame><LoadingBlock label="Loading scan..." /></PageFrame>;
  if (scan.error) return <PageFrame><ErrorBanner error={scan.error} title="Could not load scan" /></PageFrame>;
  if (!scan.data) return <PageFrame><EmptyState title="Scan not found" message="The scan may have been deleted or is unavailable." /></PageFrame>;

  const pageTotal = pages.data?.total ?? scan.data.fetched_count;
  const tabs = [
    { id: "overview", label: "Overview" },
    { id: "pages", label: "Pages", count: pageTotal },
    { id: "errors", label: "Errors", count: errors.data?.length ?? scan.data.failed_count }
  ];

  return (
    <PageFrame>
      <div className="mb-5 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="mb-2 text-sm text-stone-500">Scans / {hostnameFromUrl(scan.data.starting_url)}</div>
          <h1 className="truncate text-xl font-semibold text-stone-950">{scan.data.starting_url}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <StatusBadge status={scan.data.status} />
            <span className="text-sm text-stone-600">Created {formatDate(scan.data.created_at)}</span>
            {scan.isFetching ? <span className="text-xs text-stone-500" aria-live="polite">Refreshing</span> : null}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {isActiveScan ? (
            <Button
              type="button"
              variant="danger"
              loading={cancel.isPending}
              onClick={() => {
                if (window.confirm("Cancel this scan? Partial results will remain available.")) cancel.mutate();
              }}
            >
              Cancel scan
            </Button>
          ) : null}
          <Button type="button" onClick={() => navigate(newScanUrl(scan.data))}>New scan using these settings</Button>
          <CopyButton value={scan.data.starting_url} label="Copy starting URL" />
        </div>
      </div>

      <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-5">
        <Metric label="Discovered" value={scan.data.discovered_count} />
        <Metric label="Fetched" value={scan.data.fetched_count} />
        <Metric label="Queued" value={scan.data.queued_count} />
        <Metric label="Failed" value={scan.data.failed_count} />
        <Metric label="Skipped" value={scan.data.skipped_count} />
      </div>

      {cancel.error ? <div className="mb-4"><ErrorBanner error={cancel.error} title="Could not cancel scan" /></div> : null}

      <Tabs tabs={tabs} active={tab} onChange={(next) => updateParam(setSearchParams, "tab", next === "overview" ? null : next)} />

      <div className="mt-5">
        {tab === "overview" ? <Overview scan={scan.data} pages={pages.data?.items ?? []} errors={errors.data ?? []} scanId={scanId} /> : null}
        {tab === "pages" ? (
          <PagesView
            scanId={scanId}
            pages={pages.data?.items ?? []}
            total={pages.data?.total ?? 0}
            loading={pages.isLoading}
            error={pages.error}
            searchDraft={searchDraft}
            setSearchDraft={setSearchDraft}
            searchParams={searchParams}
            setSearchParams={setSearchParams}
            activeScan={isActiveScan}
          />
        ) : null}
        {tab === "errors" ? <ErrorsView scanId={scanId} errors={errors.data ?? []} loading={errors.isLoading} error={errors.error} /> : null}
      </div>
    </PageFrame>
  );
}

function PageFrame({ children }: { children: React.ReactNode }) {
  return <section className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">{children}</section>;
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md border border-stone-200 bg-white px-4 py-3 shadow-sm">
      <div className="text-xs font-medium uppercase text-stone-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold">{value}</div>
    </div>
  );
}

function Overview({ scan, pages, errors, scanId }: { scan: Scan; pages: Page[]; errors: Snapshot[]; scanId: string }) {
  const httpErrors = pages.filter((page) => page.http_status != null && page.http_status >= 400).length;
  const crawlerFailures = errors.filter((error) => error.error_type).length;
  const active = !isTerminalStatus(scan.status);
  return (
    <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
      <div className="space-y-5">
        {active ? (
          <div className="rounded-md border border-sky-200 bg-sky-50 p-4 text-sm text-sky-950">
            <div className="font-medium">Fetched {scan.fetched_count} of {scan.discovered_count} discovered pages</div>
            <div className="mt-1">{scan.queued_count} pages currently queued. More pages may still be discovered.</div>
          </div>
        ) : null}
        <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
          <h2 className="mb-4 text-base font-semibold">Scan summary</h2>
          <DefinitionList
            items={[
              { label: "Starting URL", value: scan.starting_url, copyValue: scan.starting_url },
              { label: "Status", value: <StatusBadge status={scan.status} /> },
              { label: "Started", value: formatDate(scan.started_at) },
              { label: "Finished", value: formatDate(scan.finished_at) },
              { label: "Duration", value: formatDuration(scan.started_at, scan.finished_at ?? undefined) },
              { label: "Stop reason", value: scan.stop_reason ?? (active ? "Running" : "Not recorded") },
              { label: "HTTP error responses", value: httpErrors },
              { label: "Crawler or network failures", value: crawlerFailures },
              { label: "Fatal error", value: scan.fatal_error_message ?? "None" }
            ]}
          />
        </section>
        <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
          <h2 className="mb-4 text-base font-semibold">Scope configuration</h2>
          <ScopeSummary scope={scan.scope_config} />
          <details className="mt-4">
            <summary className="cursor-pointer text-sm font-medium">View scan configuration</summary>
            <pre className="mt-3 max-h-80 overflow-auto rounded-md border border-stone-200 bg-stone-50 p-3 text-xs">{JSON.stringify(scan.scope_config, null, 2)}</pre>
          </details>
        </section>
      </div>
      <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
        <h2 className="mb-3 text-base font-semibold">{active ? "Recent scan activity" : "Recent pages"}</h2>
        {pages.length ? (
          <div className="space-y-2">
            {pages.slice(0, 10).map((page) => (
              <Link key={page.id} to={`/scans/${scanId}/pages/${page.id}`} className="block rounded-md border border-stone-200 px-3 py-2 text-sm hover:bg-stone-50 focus:outline-none focus:ring-2 focus:ring-neutral-900">
                <span className="flex items-center justify-between gap-2">
                  <span className="min-w-0 truncate font-mono text-xs">{compactUrl(page.requested_url)}</span>
                  <StatusBadge status={page.error_type ? "failed" : page.fetch_state} label={page.http_status ? String(page.http_status) : formatStatus(page.fetch_state)} />
                </span>
                <span className="mt-1 block text-xs text-stone-500">Depth {page.depth}{page.response_time_ms != null ? `, ${page.response_time_ms} ms` : ""}</span>
              </Link>
            ))}
          </div>
        ) : active ? (
          <EmptyState title="Waiting for pages" message="Scan activity will appear as pages are fetched." />
        ) : (
          <EmptyState title="No pages recorded" message="This scan did not store page snapshots." />
        )}
      </section>
    </div>
  );
}

function ScopeSummary({ scope }: { scope: Record<string, unknown> }) {
  const included = asStringArray(scope.included_path_prefixes);
  const excluded = asStringArray(scope.excluded_path_prefixes);
  const dropped = asStringArray(scope.drop_query_parameters);
  const hosts = asStringArray(scope.allowed_host_patterns);
  return (
    <div className="flex flex-wrap gap-2 text-xs">
      <span className="rounded-md border border-stone-200 bg-stone-50 px-2 py-1">{hosts.length ? plural(hosts.length, "allowed host") : "Exact starting hostname"}</span>
      <span className="rounded-md border border-stone-200 bg-stone-50 px-2 py-1">{scope.follow_subdomains ? "Subdomains included" : "Subdomains excluded"}</span>
      <span className="rounded-md border border-stone-200 bg-stone-50 px-2 py-1">{included.filter((path) => path !== "/").length ? plural(included.length, "included path") : "All paths included"}</span>
      <span className="rounded-md border border-stone-200 bg-stone-50 px-2 py-1">{excluded.length ? plural(excluded.length, "path exclusion") : "No path exclusions"}</span>
      <span className="rounded-md border border-stone-200 bg-stone-50 px-2 py-1">{dropped.length ? `${dropped.length} query parameters removed` : "No query parameters removed"}</span>
    </div>
  );
}

function PagesView({
  scanId,
  pages,
  total,
  loading,
  error,
  searchDraft,
  setSearchDraft,
  searchParams,
  setSearchParams,
  activeScan
}: {
  scanId: string;
  pages: Page[];
  total: number;
  loading: boolean;
  error: unknown;
  searchDraft: string;
  setSearchDraft: (value: string) => void;
  searchParams: URLSearchParams;
  setSearchParams: ReturnType<typeof useSearchParams>[1];
  activeScan: boolean;
}) {
  const limit = Number(searchParams.get("limit") ?? 50);
  const offset = Number(searchParams.get("offset") ?? 0);
  if (error) return <ErrorBanner error={error} title="Could not load pages" />;
  return (
    <div className="space-y-4">
      <div className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-6">
          <input aria-label="Search pages" value={searchDraft} onChange={(event) => setSearchDraft(event.target.value)} placeholder="Search URLs or titles" className={`${inputClass()} lg:col-span-2`} />
          <input aria-label="HTTP status" value={searchParams.get("status") ?? ""} onChange={(event) => updateParam(setSearchParams, "status", event.target.value || null, { offset: null })} placeholder="Status" className={inputClass()} />
          <input aria-label="Host filter" value={searchParams.get("host") ?? ""} onChange={(event) => updateParam(setSearchParams, "host", event.target.value || null, { offset: null })} placeholder="Host" className={inputClass()} />
          <input aria-label="Minimum depth" type="number" min={0} value={searchParams.get("min_depth") ?? ""} onChange={(event) => updateParam(setSearchParams, "min_depth", event.target.value || null, { offset: null })} placeholder="Min depth" className={inputClass()} />
          <input aria-label="Maximum depth" type="number" min={0} value={searchParams.get("max_depth") ?? ""} onChange={(event) => updateParam(setSearchParams, "max_depth", event.target.value || null, { offset: null })} placeholder="Max depth" className={inputClass()} />
          <input aria-label="Path prefix" value={searchParams.get("path_prefix") ?? ""} onChange={(event) => updateParam(setSearchParams, "path_prefix", event.target.value || null, { offset: null })} placeholder="/path/" className={inputClass()} />
          <select aria-label="Error state" value={searchParams.get("error_state") ?? "any"} onChange={(event) => updateParam(setSearchParams, "error_state", event.target.value === "any" ? null : event.target.value, { offset: null })} className={inputClass()}>
            <option value="any">All states</option>
            <option value="with_errors">Errors only</option>
            <option value="without_errors">No crawler errors</option>
          </select>
          <select aria-label="Sort pages" value={searchParams.get("sort") ?? "requested_url"} onChange={(event) => updateParam(setSearchParams, "sort", event.target.value, { offset: null })} className={inputClass()}>
            <option value="requested_url">URL</option>
            <option value="status">HTTP status</option>
            <option value="title">Title</option>
            <option value="depth">Depth</option>
            <option value="duration">Duration</option>
          </select>
          <select aria-label="Sort direction" value={searchParams.get("direction") ?? "asc"} onChange={(event) => updateParam(setSearchParams, "direction", event.target.value, { offset: null })} className={inputClass()}>
            <option value="asc">Ascending</option>
            <option value="desc">Descending</option>
          </select>
          <label className="flex items-center gap-2 rounded-md border border-stone-200 bg-white px-3 py-2 text-sm">
            <input type="checkbox" checked={searchParams.get("error_state") === "with_errors"} onChange={(event) => updateParam(setSearchParams, "error_state", event.target.checked ? "with_errors" : null, { offset: null })} className="size-4 rounded border-stone-300 focus:ring-neutral-900" />
            Error-only
          </label>
          <Button type="button" variant="ghost" onClick={() => setSearchParams(tabOnly(searchParams))}>Clear filters</Button>
        </div>
      </div>
      <Pagination total={total} limit={limit} offset={offset} setSearchParams={setSearchParams} />
      {loading ? <LoadingBlock label="Loading pages..." /> : null}
      {!loading && pages.length === 0 ? (
        <EmptyState
          title={activeScan ? "Pages are still being discovered" : hasFilters(searchParams) ? "No pages match these filters" : "No pages recorded"}
          message={activeScan ? "Fetched pages will appear here as the scan progresses." : hasFilters(searchParams) ? "Clear filters or broaden the search." : "This scan did not return page snapshots."}
        />
      ) : (
        <PageTable scanId={scanId} pages={pages} />
      )}
      <Pagination total={total} limit={limit} offset={offset} setSearchParams={setSearchParams} />
    </div>
  );
}

function PageTable({ pages, scanId }: { pages: Page[]; scanId: string }) {
  return (
    <div className="overflow-x-auto rounded-md border border-stone-200 bg-white shadow-sm">
      <table className="min-w-full text-left text-sm">
        <thead className="bg-stone-100 text-xs uppercase text-stone-500">
          <tr>
            {["Status", "URL", "Title", "Depth", "Content type", "Duration", "Inbound", "Error"].map((header) => (
              <th key={header} scope="col" className="whitespace-nowrap px-3 py-2 font-medium">{header}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {pages.map((page) => {
            const finalDifferent = page.final_url && page.final_url !== page.requested_url;
            return (
              <tr key={page.id} className="border-t border-stone-100 hover:bg-stone-50">
                <td className="whitespace-nowrap px-3 py-2">
                  <StatusBadge status={page.error_type ? "failed" : page.fetch_state} label={page.http_status ? String(page.http_status) : formatStatus(page.fetch_state)} />
                </td>
                <td className="max-w-[32rem] px-3 py-2">
                  <Link to={`/scans/${scanId}/pages/${page.id}`} className="block min-w-0 focus:outline-none focus:ring-2 focus:ring-neutral-900">
                    <span title={page.requested_url} className="block truncate font-mono text-xs text-stone-950">{page.requested_url}</span>
                    {finalDifferent ? <span title={page.final_url ?? ""} className="mt-1 block truncate font-mono text-xs text-stone-500">Final: {page.final_url}</span> : null}
                  </Link>
                </td>
                <td className="max-w-xs truncate px-3 py-2">{page.title || "Untitled"}</td>
                <td className="px-3 py-2">{page.depth}</td>
                <td className="max-w-xs truncate px-3 py-2">{page.content_type ?? "Not available"}</td>
                <td className="whitespace-nowrap px-3 py-2">{page.response_time_ms != null ? `${page.response_time_ms} ms` : "Not available"}</td>
                <td className="px-3 py-2">{page.inbound_occurrence_count}</td>
                <td className="max-w-xs truncate px-3 py-2">{page.error_type ? formatStatus(page.error_type) : "None"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Pagination({ total, limit, offset, setSearchParams }: { total: number; limit: number; offset: number; setSearchParams: ReturnType<typeof useSearchParams>[1] }) {
  const page = Math.floor(offset / limit) + 1;
  const pages = Math.max(1, Math.ceil(total / limit));
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-stone-600">
      <div>
        Page {page} of {pages}, {plural(total, "result")}
      </div>
      <div className="flex items-center gap-2">
        <select aria-label="Page size" value={limit} onChange={(event) => updateParam(setSearchParams, "limit", event.target.value, { offset: null })} className="rounded-md border border-stone-300 bg-white px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-neutral-900">
          {pageSizes.map((size) => <option key={size} value={size}>{size} rows</option>)}
        </select>
        <Button type="button" disabled={offset <= 0} onClick={() => updateParam(setSearchParams, "offset", String(Math.max(0, offset - limit)))}>Previous</Button>
        <Button type="button" disabled={offset + limit >= total} onClick={() => updateParam(setSearchParams, "offset", String(offset + limit))}>Next</Button>
      </div>
    </div>
  );
}

function ErrorsView({ scanId, errors, loading, error }: { scanId: string; errors: Snapshot[]; loading: boolean; error: unknown }) {
  if (error) return <ErrorBanner error={error} title="Could not load errors" />;
  if (loading) return <LoadingBlock label="Loading errors..." />;
  if (!errors.length) return <EmptyState title="No crawler errors" message="HTTP error responses without crawler failures are available in the Pages tab." />;
  const groups = groupErrors(errors);
  return (
    <div className="space-y-5">
      {Object.entries(groups).map(([group, items]) => (
        <section key={group} className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
          <h2 className="text-base font-semibold">{group}</h2>
          <div className="mt-3 divide-y divide-stone-100">
            {items.map((item) => (
              <Link key={item.id} to={`/scans/${scanId}/pages/${item.id}`} className="block py-3 text-sm hover:bg-stone-50 focus:outline-none focus:ring-2 focus:ring-neutral-900">
                <div className="flex flex-wrap items-center gap-2">
                  <StatusBadge status="failed" label={formatStatus(item.error_type ?? "error")} />
                  {item.http_status ? <StatusBadge status={String(item.http_status)} label={String(item.http_status)} /> : null}
                  <span className="text-xs text-stone-500">Depth {item.crawl_depth}</span>
                </div>
                <div className="mt-1 min-w-0 truncate font-mono text-xs">{item.requested_url}</div>
                {item.error_message ? <div className="mt-1 text-stone-700">{item.error_message}</div> : null}
              </Link>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function groupErrors(errors: Snapshot[]) {
  return errors.reduce<Record<string, Snapshot[]>>((groups, error) => {
    const key = error.error_type?.includes("unsafe")
      ? "Unsafe destination failures"
      : error.error_type?.includes("scope")
        ? "Scope-related failures"
        : error.error_type?.includes("large")
          ? "Response-too-large failures"
          : error.error_type?.includes("unsupported")
            ? "Unsupported content types"
            : "Network and crawler failures";
    groups[key] = [...(groups[key] ?? []), error];
    return groups;
  }, {});
}

function buildPageQuery(searchParams: URLSearchParams) {
  const params = new URLSearchParams();
  for (const key of ["search", "status", "host", "path_prefix", "min_depth", "max_depth", "error_state", "sort", "direction", "limit", "offset"]) {
    const value = searchParams.get(key);
    if (value) params.set(key, value);
  }
  return `?${params.toString()}`;
}

function updateParam(setSearchParams: ReturnType<typeof useSearchParams>[1], key: string, value: string | null, resets: Record<string, string | null> = {}) {
  setSearchParams((current) => {
    const next = new URLSearchParams(current);
    if (value) next.set(key, value);
    else next.delete(key);
    for (const [resetKey, resetValue] of Object.entries(resets)) {
      if (resetValue) next.set(resetKey, resetValue);
      else next.delete(resetKey);
    }
    return next;
  });
}

function tabOnly(searchParams: URLSearchParams) {
  const next = new URLSearchParams();
  const tab = searchParams.get("tab");
  if (tab) next.set("tab", tab);
  return next;
}

function hasFilters(searchParams: URLSearchParams) {
  return ["search", "status", "host", "path_prefix", "min_depth", "max_depth", "error_state"].some((key) => searchParams.has(key));
}

function asStringArray(value: unknown) {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function newScanUrl(scan: Scan) {
  const params = new URLSearchParams({
    starting_url: scan.starting_url,
    scope: JSON.stringify(scan.scope_config)
  });
  return `/scans/new?${params.toString()}`;
}
