import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { deleteScan, getScanDeletePreview, listScanHistory } from "../api/client";
import { Button } from "../components/ui/Button";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorBanner } from "../components/ui/ErrorBanner";
import { LoadingBlock } from "../components/ui/Loading";
import { PaginatedTableControls } from "../components/ui/PaginatedTableControls";
import { StatusBadge } from "../components/ui/StatusBadge";
import { SortableTableHeader, type SortDirection } from "../components/ui/SortableTableHeader";
import { inputClass } from "../components/ui/styles";
import type { Scan, ScanDeletePreview } from "../types/scans";
import { formatBytes, formatDate, formatDuration, hostnameFromUrl, isTerminalStatus } from "../utils/format";
import { useDocumentTitle } from "../utils/useDocumentTitle";
import { useUrlPagination } from "../utils/useUrlPagination";

const statusOptions = ["completed", "completed_with_errors", "failed", "cancelled", "interrupted", "queued", "running"];

export function ScansPage() {
  useDocumentTitle("All Scans");
  const [searchParams, setSearchParams] = useSearchParams();
  const pagination = useUrlPagination({ prefix: "scans", defaultLimit: 25 });
  const queryClient = useQueryClient();
  const [success, setSuccess] = useState<string | null>(null);
  const [deleteState, setDeleteState] = useState<{ scan: Scan; preview?: ScanDeletePreview; error?: unknown } | null>(null);
  const query = buildHistoryQuery(searchParams, pagination.limit, pagination.offset);
  const scans = useQuery({ queryKey: ["scan-history", query], queryFn: () => listScanHistory(query) });
  const preview = useMutation({
    mutationFn: (scan: Scan) => getScanDeletePreview(String(scan.id)),
    onSuccess: (data, scan) => setDeleteState({ scan, preview: data }),
    onError: (error, scan) => setDeleteState({ scan, error })
  });
  const remove = useMutation({
    mutationFn: (scan: Scan) => deleteScan(String(scan.id)),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["scans"] });
      await queryClient.invalidateQueries({ queryKey: ["scan-history"] });
      setDeleteState(null);
      setSuccess("Scan deleted.");
      const remainingOnPage = (scans.data?.items.length ?? 1) - 1;
      if (remainingOnPage <= 0 && pagination.offset > 0) {
        pagination.setPage(Math.max(1, pagination.currentPage - 1));
      }
    }
  });

  useEffect(() => {
    if (!success) return;
    const timer = window.setTimeout(() => setSuccess(null), 3500);
    return () => window.clearTimeout(timer);
  }, [success]);
  useEffect(() => pagination.ensureValid(scans.data?.total), [scans.data?.total, pagination]);
  const controls = scans.data ? <PaginatedTableControls total={scans.data.total} limit={pagination.limit} offset={pagination.offset} onPageChange={pagination.setPage} onPageSizeChange={pagination.setPageSize} itemLabel="scan" isLoading={scans.isFetching && !scans.isLoading} /> : null;

  return (
    <section className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
      <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="text-sm text-stone-500">Scans</div>
          <h1 className="mt-1 text-2xl font-semibold text-stone-950">All scans</h1>
        </div>
        <Link to="/scans/new" className="rounded-md border border-neutral-900 bg-neutral-900 px-3 py-2 text-sm font-medium text-white hover:bg-neutral-700 focus:outline-none focus:ring-2 focus:ring-neutral-900 focus:ring-offset-2">
          New scan
        </Link>
      </div>
      <section className="mb-4 rounded-md border border-stone-200 bg-white p-4 shadow-sm">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <input aria-label="Search scans" value={searchParams.get("search") ?? ""} onChange={(event) => updateHistoryParam(setSearchParams, "search", event.target.value || null)} placeholder="Search starting URL" className={`${inputClass()} md:col-span-2`} />
          <select aria-label="Scan status" value={searchParams.get("status") ?? ""} onChange={(event) => updateHistoryParam(setSearchParams, "status", event.target.value || null)} className={inputClass()}>
            <option value="">Any status</option>
            {statusOptions.map((status) => <option key={status} value={status}>{status.replace(/_/g, " ")}</option>)}
          </select>
        </div>
        <div className="mt-3">
          <Button type="button" variant="ghost" onClick={() => setSearchParams({ scans_limit: String(pagination.limit), scans_offset: "0" })}>Clear filters</Button>
        </div>
      </section>
      {success ? <div className="mb-4 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-900">{success}</div> : null}
      {scans.error ? <ErrorBanner error={scans.error} title="Could not load scan history" /> : null}
      {scans.isLoading ? <LoadingBlock label="Loading scan history..." /> : null}
      {!scans.isLoading && !scans.data?.items.length ? <EmptyState title="No scans found" message={hasHistoryFilters(searchParams) ? "Clear filters or broaden the search." : "Create a scan to start building history."} /> : null}
      {controls ? <div className="mb-4">{controls}</div> : null}
      {scans.data?.items.length ? (
        <div className="overflow-x-auto rounded-md border border-stone-200 bg-white shadow-sm">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-stone-100 text-xs uppercase text-stone-500">
              <tr>
                {[["starting_url", "Starting URL"], ["status", "Status"], ["created_at", "Created"], ["started_at", "Started"], ["finished_at", "Finished"], ["duration", "Duration"], ["discovered_count", "Counts"], ["stop_reason", "Stop reason"]].map(([column, label]) => <SortableTableHeader key={column} column={column} label={label} activeColumn={searchParams.get("sort")} direction={searchParams.get("direction") as SortDirection | null} onChange={(column, direction) => setHistorySort(setSearchParams, column, direction)} defaultDirection={column.endsWith("_at") ? "desc" : "asc"} />)}
                <th className="px-3 py-2 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {scans.data.items.map((scan) => (
                <tr key={scan.id} className="border-t border-stone-100 align-top">
                  <td className="max-w-md px-3 py-2">
                    <Link to={`/scans/${scan.id}`} className="block truncate font-medium text-stone-950 underline" title={scan.starting_url}>
                      {scan.website_property_name ?? hostnameFromUrl(scan.starting_url)}
                    </Link>
                    <span className="block text-xs text-stone-500">{scan.website_property_name ? "Saved site" : "Ad hoc"}</span>
                    <span className="block truncate font-mono text-xs text-stone-500">{scan.starting_url}</span>
                  </td>
                  <td className="px-3 py-2"><StatusBadge status={scan.status} /></td>
                  <td className="px-3 py-2">{formatDate(scan.created_at)}</td>
                  <td className="px-3 py-2">{formatDate(scan.started_at)}</td>
                  <td className="px-3 py-2">{formatDate(scan.finished_at)}</td>
                  <td className="px-3 py-2">{formatDuration(scan.started_at, scan.finished_at)}</td>
                  <td className="whitespace-nowrap px-3 py-2">
                    <span className="block">{scan.discovered_count} discovered</span>
                    <span className="block">{scan.fetched_count} fetched</span>
                    <span className="block">{scan.failed_count} failed</span>
                    <span className="block">{scan.skipped_count} skipped</span>
                  </td>
                  <td className="max-w-xs px-3 py-2">{scan.stop_reason ?? "None"}</td>
                  <td className="px-3 py-2">
                    <div className="flex flex-wrap gap-2">
                      <Link to={`/scans/${scan.id}`} className="text-sm font-medium underline">Open</Link>
                      <Link to={rerunUrl(scan)} className="text-sm font-medium underline">Run again</Link>
                      {isTerminalStatus(scan.status) ? (
                        <button type="button" className="text-sm font-medium text-red-700 underline" onClick={() => preview.mutate(scan)}>
                          Delete
                        </button>
                      ) : null}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {controls ? <div className="mt-4">{controls}</div> : null}
      {deleteState ? (
        <DeleteDialog
          state={deleteState}
          loading={preview.isPending}
          deleting={remove.isPending}
          error={deleteState.error ?? remove.error}
          onCancel={() => {
            if (!remove.isPending) setDeleteState(null);
          }}
          onConfirm={() => remove.mutate(deleteState.scan)}
        />
      ) : null}
    </section>
  );
}

function setHistorySort(setSearchParams: ReturnType<typeof useSearchParams>[1], column: string | null, direction: SortDirection | null) {
  setSearchParams((current) => {
    const next = new URLSearchParams(current);
    if (column && direction) { next.set("sort", column); next.set("direction", direction); }
    else { next.delete("sort"); next.delete("direction"); }
    next.delete("scans_offset");
    return next;
  });
}

function DeleteDialog({ state, loading, deleting, error, onCancel, onConfirm }: { state: { scan: Scan; preview?: ScanDeletePreview }; loading: boolean; deleting: boolean; error: unknown; onCancel: () => void; onConfirm: () => void }) {
  const preview = state.preview;
  return (
    <div role="dialog" aria-modal="true" aria-labelledby="delete-scan-title" className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
      <div className="w-full max-w-lg rounded-md border border-stone-200 bg-white p-5 shadow-xl">
        <h2 id="delete-scan-title" className="text-lg font-semibold text-stone-950">Delete this scan?</h2>
        <p className="mt-2 break-all font-mono text-xs text-stone-600">{state.scan.starting_url}</p>
        {loading ? <div className="mt-4"><LoadingBlock label="Loading deletion summary..." /></div> : null}
        {preview ? (
          <div className="mt-4 space-y-3 text-sm text-stone-700">
            <p>
              This will permanently delete {preview.snapshots} page snapshots and {preview.link_occurrences} link occurrences.
              Estimated storage reclaimed: {formatBytes(preview.stored_html_bytes_reclaimable)}.
            </p>
            <dl className="grid grid-cols-2 gap-3">
              <SummaryTerm label="Status" value={preview.status.replace(/_/g, " ")} />
              <SummaryTerm label="Unique resources" value={String(preview.unique_resources)} />
              <SummaryTerm label="Exclusive captures" value={String(preview.exclusive_html_blobs)} />
              <SummaryTerm label="Shared captures retained" value={String(preview.shared_html_blobs)} />
            </dl>
            <p className="font-medium text-red-800">This action cannot be undone.</p>
            {preview.reason ? <p className="text-amber-700">{preview.reason}</p> : null}
            {preview.warnings.length ? <Warnings warnings={preview.warnings} /> : null}
          </div>
        ) : null}
        {error ? <div className="mt-4"><ErrorBanner error={error} title="Could not delete scan" /></div> : null}
        <div className="mt-5 flex justify-end gap-2">
          <Button type="button" onClick={onCancel} disabled={deleting}>Cancel</Button>
          <Button type="button" variant="danger" loading={deleting} disabled={!preview?.can_delete} onClick={onConfirm}>
            {deleting ? "Deleting..." : "Delete scan"}
          </Button>
        </div>
      </div>
    </div>
  );
}

function SummaryTerm({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-stone-200 bg-stone-50 px-3 py-2">
      <dt className="text-xs font-medium uppercase text-stone-500">{label}</dt>
      <dd className="mt-1">{value}</dd>
    </div>
  );
}

function Warnings({ warnings }: { warnings: string[] }) {
  return (
    <details className="rounded-md border border-amber-200 bg-amber-50 p-3">
      <summary className="cursor-pointer font-medium text-amber-900">Cleanup warnings</summary>
      <ul className="mt-2 list-disc pl-5 text-amber-800">
        {warnings.map((warning) => <li key={warning}>{warning}</li>)}
      </ul>
    </details>
  );
}

function buildHistoryQuery(searchParams: URLSearchParams, limit: number, offset: number) {
  const params = new URLSearchParams();
  for (const key of ["search", "status", "sort", "direction"]) {
    const value = searchParams.get(key);
    if (value) params.set(key, value);
  }
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  return `?${params.toString()}`;
}

function updateHistoryParam(setSearchParams: ReturnType<typeof useSearchParams>[1], key: string, value: string | null, resetOffset = true) {
  setSearchParams((current) => {
    const next = new URLSearchParams(current);
    if (value) next.set(key, value);
    else next.delete(key);
    if (resetOffset) next.set("scans_offset", "0");
    return next;
  });
}

function hasHistoryFilters(searchParams: URLSearchParams) {
  return ["search", "status"].some((key) => searchParams.has(key));
}

function rerunUrl(scan: Scan) {
  const params = new URLSearchParams({
    starting_url: scan.starting_url,
    scope: JSON.stringify(scan.scope_config)
  });
  return `/scans/new?${params.toString()}`;
}
