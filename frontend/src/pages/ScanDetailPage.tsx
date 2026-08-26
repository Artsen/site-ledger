import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { buildScanProjection, cancelScan, createRenderRun, createScanNote, deleteScan, getScan, getScanDeletePreview, getScanProjectionStatus, getWorkerHealth, listErrors, listJobs, listPages, listScanNotes, listScanRenderedObservations, listScanSeeds, rebuildScanProjection } from "../api/client";
import { NotesPanel } from "../components/NotesPanel";
import { RenderedObservationTable } from "../components/RenderedObservationTable";
import { LegacyRenderBulkDeleteAction, RenderScanDeleteAction } from "../components/rendered/RenderedEvidenceDeletionActions";
import { ResourceInventoryView } from "../components/ResourceInventoryView";
import { Button } from "../components/ui/Button";
import { CopyButton } from "../components/ui/CopyButton";
import { DefinitionList } from "../components/ui/DefinitionList";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorBanner } from "../components/ui/ErrorBanner";
import { LoadingBlock } from "../components/ui/Loading";
import { PaginatedTableControls } from "../components/ui/PaginatedTableControls";
import { StatusBadge } from "../components/ui/StatusBadge";
import { SortableTableHeader, type SortDirection } from "../components/ui/SortableTableHeader";
import { Tabs } from "../components/ui/Tabs";
import { inputClass } from "../components/ui/styles";
import { ScanGraphView } from "../features/graph/ScanGraphView";
import type { Job, WorkerHealth } from "../types/jobs";
import type { Page, RenderedObservationIndexItem, Scan, ScanSeed, Snapshot } from "../types/scans";
import { compactUrl, formatBytes, formatDate, formatDuration, formatStatus, isTerminalStatus, plural } from "../utils/format";
import { useDocumentTitle } from "../utils/useDocumentTitle";
import { useUrlPagination } from "../utils/useUrlPagination";
import { useTableSort } from "../utils/useTableSort";
import { projectionStatusRefetchInterval, scanResultQueryOptions } from "../utils/scanQueryOptions";

export function ScanDetailPage() {
  const { scanId = "" } = useParams();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const tab = searchParams.get("tab") ?? "overview";
  const [searchDraft, setSearchDraft] = useState(searchParams.get("search") ?? "");
  const [selectedRendered, setSelectedRendered] = useState<number[]>([]);
  const [loadedRendered, setLoadedRendered] = useState<RenderedObservationIndexItem[]>([]);
  const scan = useQuery({
    queryKey: ["scan", scanId],
    queryFn: () => getScan(scanId),
    refetchInterval: (query) => {
      const value = query.state.data;
      const scanFinished = isTerminalStatus(value?.status ?? "");
      const renderFinished = !value?.render_run_id || isTerminalStatus(value.render_run_status ?? "");
      return scanFinished && renderFinished ? false : 1500;
    },
    retry: (failureCount, error) => (error instanceof Error && error.message.includes("not be found") ? false : failureCount < 2)
  });
  useDocumentTitle(scan.data ? `Scan ${scan.data.id}` : scanId ? `Scan ${scanId}` : "Scan");
  const isActiveScan = Boolean(scan.data && !isTerminalStatus(scan.data.status));
  const projection = useQuery({
    queryKey: ["scan-projection", scanId],
    queryFn: () => getScanProjectionStatus(scanId),
    enabled: Boolean(scan.data),
    refetchInterval: (query) => projectionStatusRefetchInterval(query.state.data)
  });
  const jobs = useQuery({
    queryKey: ["jobs", "scan", scanId],
    queryFn: () => listJobs(`?scan_id=${encodeURIComponent(scanId)}&limit=1`),
    enabled: Boolean(scan.data),
    refetchInterval: (query) => {
      const job = query.state.data?.items[0];
      return job && !isTerminalStatus(job.status) ? 1500 : false;
    },
    placeholderData: (previous) => previous
  });
  const workerHealth = useQuery({
    queryKey: ["worker-health"],
    queryFn: getWorkerHealth,
    enabled: Boolean(scan.data && (isActiveScan || jobs.data?.items[0] && !isTerminalStatus(jobs.data.items[0].status))),
    refetchInterval: 5000,
    placeholderData: (previous) => previous
  });
  const latestJob = jobs.data?.items[0];

  useEffect(() => {
    if (tab !== "pages") return;
    if (searchDraft === (searchParams.get("search") ?? "")) return;
    const timer = window.setTimeout(() => updateParam(setSearchParams, "search", searchDraft || null, { pages_offset: null }), 350);
    return () => window.clearTimeout(timer);
  }, [searchDraft, searchParams, setSearchParams, tab]);

  const pageQuery = useMemo(() => buildPageQuery(searchParams), [searchParams]);
  const projectionKey = projection.data?.current_build?.id ?? projection.data?.projection_status ?? "unknown";
  const pages = useQuery({
    queryKey: ["pages", scanId, projectionKey, pageQuery],
    queryFn: () => listPages(scanId, pageQuery),
    enabled: tab === "overview" || tab === "pages",
    ...scanResultQueryOptions(scan.data?.status, projection.data),
    placeholderData: (previous) => previous
  });
  const errors = useQuery({
    queryKey: ["errors", scanId],
    queryFn: () => listErrors(scanId),
    enabled: tab === "errors" || tab === "overview",
    refetchInterval: isActiveScan ? 3000 : false
  });
  const seeds = useQuery({
    queryKey: ["scan-seeds", scanId],
    queryFn: () => listScanSeeds(scanId),
    enabled: tab === "inputs"
  });
  const recentRendered = useQuery({
    queryKey: ["scan-rendered-observations", scanId, "overview"],
    queryFn: () => listScanRenderedObservations(scanId, "?sort=capture_time&direction=desc&limit=5"),
    enabled: tab === "overview" && Boolean(scan.data?.rendered_attempted_count || scan.data?.render_run_id),
    refetchInterval: scan.data?.render_run_id && !isTerminalStatus(scan.data.render_run_status ?? "") ? 1500 : false
  });
  const cancel = useMutation({
    mutationFn: () => cancelScan(scanId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["scan", scanId] });
      await queryClient.invalidateQueries({ queryKey: ["scans"] });
    }
  });
  const deletePreview = useQuery({
    queryKey: ["scan-delete-preview", scanId],
    queryFn: () => getScanDeletePreview(scanId),
    enabled: tab === "overview" && Boolean(scan.data && isTerminalStatus(scan.data.status))
  });
  const remove = useMutation({
    mutationFn: () => deleteScan(scanId),
    onSuccess: async () => {
      queryClient.removeQueries({ predicate: (query) => query.queryKey.some((part) => String(part) === scanId) });
      await queryClient.invalidateQueries({ queryKey: ["scans"] });
      await queryClient.invalidateQueries({ queryKey: ["scan-history"] });
      navigate("/scans");
    }
  });
  const prepareProjection = useMutation({
    mutationFn: () => projection.data?.can_rebuild ? rebuildScanProjection(scanId) : buildScanProjection(scanId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["scan-projection", scanId] });
    }
  });
  const rerenderLegacy = useMutation({
    mutationFn: () => createRenderRun(
      String(scan.data?.website_property_id),
      [...new Set(loadedRendered.filter((item) => selectedRendered.includes(item.id)).map((item) => item.resource_id))],
      "site_workspace",
    ),
    onSuccess: (run) => navigate(`/sites/${scan.data?.website_property_id}/rendered/runs/${run.id}`),
  });

  if (scan.isLoading) return <PageFrame><LoadingBlock label="Loading scan..." /></PageFrame>;
  if (scan.error) return <PageFrame><ErrorBanner error={scan.error} title="Could not load scan" /></PageFrame>;
  if (!scan.data) return <PageFrame><EmptyState title="Scan not found" message="The scan may have been deleted or is unavailable." /></PageFrame>;

  const pageTotal = scan.data.html_page_observed_count || pages.data?.total || 0;
  const tabs = [
    { id: "overview", label: "Overview" },
    { id: "inputs", label: "Inputs", count: seeds.data?.total },
    { id: "pages", label: "Pages", count: pageTotal },
    { id: "resources", label: "Resources", count: scan.data.resource_discovered_count },
    { id: "rendered", label: "Rendered", count: scan.data.rendered_attempted_count },
    { id: "errors", label: "Errors", count: errors.data?.length ?? scan.data.failed_count },
    { id: "graph", label: "Graph" },
    { id: "notes", label: "Notes" }
  ];

  return (
    <PageFrame>
      <div className="mb-5 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="mb-2 text-sm text-stone-500">{scan.data.website_property_id ? <><Link className="underline" to={`/sites/${scan.data.website_property_id}/scans`}>{scan.data.website_property_name ?? "Site"}</Link> / </> : null}<Link className="underline" to="/scans">Scans</Link> / {scan.data.website_property_id ? "Saved Site observation" : "Ad hoc observation"}</div>
          <h1 className="truncate text-xl font-semibold text-stone-950">{scan.data.starting_url}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <StatusBadge status={scan.data.status} />
            <span className="text-sm text-stone-600">Created {formatDate(scan.data.created_at, { timeZone: scan.data.website_property_display_timezone, showTimeZone: true })}</span>
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
        <Metric label="Final failed" value={scan.data.failed_count} />
        <Metric label="Skipped" value={scan.data.skipped_count} />
      </div>
      {scan.data.render_run_id ? <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-md border border-stone-200 bg-white p-3 text-sm"><span>Browser Render Run #{scan.data.render_run_id} <StatusBadge status={scan.data.render_run_status ?? "queued"} /></span><Link className="font-medium underline" to={scan.data.website_property_id ? `/sites/${scan.data.website_property_id}/rendered/runs/${scan.data.render_run_id}` : `/scans/${scanId}?tab=rendered`}>{scan.data.website_property_id ? "Open Render Run" : "View rendered observations"}</Link></div> : null}
      {scan.data.scope_config.render_mode !== "none" ? <Link to={`/scans/${scanId}?tab=rendered`} className="mb-6 grid grid-cols-2 gap-3 rounded-md focus:outline-none focus:ring-2 focus:ring-neutral-900 md:grid-cols-4 xl:grid-cols-8" aria-label="View historical Scan-bound rendered captures"><Metric label="Successful renders" value={recentRendered.data?.summary?.successful_renders ?? scan.data.rendered_completed_count} /><Metric label="No content" value={recentRendered.data?.summary?.no_content_responses ?? 0} /><Metric label="Redirects" value={recentRendered.data?.summary?.redirect_responses ?? 0} /><Metric label="HTTP errors (not 429)" value={recentRendered.data?.summary?.http_error_responses ?? 0} /><Metric label="Rate limited" value={recentRendered.data?.summary?.rate_limited ?? 0} /><Metric label="Not attempted" value={recentRendered.data?.summary?.skipped_after_throttling ?? scan.data.rendered_skipped_count} /><Metric label="Technical failures" value={recentRendered.data?.summary?.technical_failures ?? scan.data.rendered_failed_count} /><Metric label="Artifacts" value={recentRendered.data?.summary?.artifacts_retained ?? scan.data.rendered_artifact_count} /></Link> : null}

      {latestJob && !isTerminalStatus(latestJob.status) ? <JobNotice job={latestJob} workerHealth={workerHealth.data} /> : null}
      {projection.data && projection.data.projection_status !== "not_terminal" ? <ProjectionNotice status={projection.data.projection_status} canBuild={projection.data.can_build} canRebuild={projection.data.can_rebuild} errorMessage={projection.data.active_build?.error_message ?? projection.data.latest_build?.error_message} loading={prepareProjection.isPending} onBuild={() => prepareProjection.mutate()} /> : null}
      {prepareProjection.error ? <div className="mb-4"><ErrorBanner error={prepareProjection.error} title="Could not prepare results" /></div> : null}
      {cancel.error ? <div className="mb-4"><ErrorBanner error={cancel.error} title="Could not cancel scan" /></div> : null}
      {remove.error ? <div className="mb-4"><ErrorBanner error={remove.error} title="Could not delete scan" /></div> : null}

      <Tabs tabs={tabs} active={tab} onChange={(next) => {
        setSearchDraft("");
        const nextParams = new URLSearchParams();
        if (next !== "overview") nextParams.set("tab", next);
        setSearchParams(nextParams);
      }} />

      <div className="mt-5">
        {tab === "overview" ? (
          <Overview
            scan={scan.data}
            job={latestJob}
            workerHealth={workerHealth.data}
            pages={pages.data?.items ?? []}
            errors={errors.data ?? []}
            scanId={scanId}
            recentRendered={recentRendered.data?.items ?? []}
            deletePreview={deletePreview.data}
            deleteLoading={deletePreview.isLoading}
            deleting={remove.isPending}
            onDelete={() => {
              if (window.confirm("Permanently delete this scan? This cannot be undone.")) remove.mutate();
            }}
          />
        ) : null}
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
        {tab === "resources" ? <ResourceInventoryView scope="scan" id={scanId} scanStatus={scan.data.status} projectionStatus={projection.data} /> : null}
        {tab === "rendered" ? <div className="space-y-4">{selectedRendered.length ? <div className="flex flex-wrap gap-2"><Button type="button" loading={rerenderLegacy.isPending} disabled={!scan.data.website_property_id} onClick={() => rerenderLegacy.mutate()}>Rerender selected ({selectedRendered.length})</Button><LegacyRenderBulkDeleteAction scanId={scanId} observationIds={selectedRendered} onDeleted={() => setSelectedRendered([])} /></div> : null}{rerenderLegacy.error ? <ErrorBanner error={rerenderLegacy.error} title="Could not rerender selected Pages" /> : null}<RenderedObservationTable scanId={scanId} renderMode={scan.data.scope_config.render_mode} poll={Boolean(scan.data.render_run_id && !isTerminalStatus(scan.data.render_run_status ?? ""))} selectedObservationIds={selectedRendered} onSelectedObservationIdsChange={setSelectedRendered} onLoadedItemsChange={setLoadedRendered} /><section className="border-t border-stone-200 pt-4"><RenderScanDeleteAction scanId={scanId} onDeleted={() => setSelectedRendered([])} /></section></div> : null}
        {tab === "inputs" ? <InputsView seeds={seeds.data?.items ?? []} loading={seeds.isLoading} error={seeds.error} /> : null}
        {tab === "errors" ? <ErrorsView scanId={scanId} errors={errors.data ?? []} loading={errors.isLoading} error={errors.error} /> : null}
        {tab === "graph" ? <ScanGraphView scan={scan.data} projectionStatus={projection.data} /> : null}
        {tab === "notes" ? <NotesPanel queryKey={["scan-notes", scanId]} list={(query) => listScanNotes(scanId, query)} create={(body, pinned) => createScanNote(scanId, body, pinned)} context={`Scan ${scanId}`} /> : null}
      </div>
    </PageFrame>
  );
}

function ProjectionNotice({ status, canBuild, canRebuild, errorMessage, loading, onBuild }: { status: string; canBuild: boolean; canRebuild: boolean; errorMessage?: string | null; loading: boolean; onBuild: () => void }) {
  const ready = status === "ready";
  const building = status === "queued" || status === "building";
  const failed = status === "failed" || status === "cancelled";
  const label = ready ? "Optimized results ready" : building ? "Building optimized results" : failed ? "Optimized results failed; using current evidence" : "Using current evidence while optimized results are prepared";
  return <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-md border border-stone-200 bg-stone-50 px-3 py-2 text-sm" role="status" aria-live="polite">
    <div><span className="font-medium text-stone-800">{label}</span>{failed && errorMessage ? <span className="ml-2 text-stone-600">{errorMessage}</span> : null}</div>
    {(canBuild || canRebuild) ? <Button type="button" variant="ghost" loading={loading} onClick={onBuild}>{canRebuild ? "Rebuild results" : "Prepare results"}</Button> : null}
  </div>;
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

function Overview({
  scan,
  job,
  workerHealth,
  pages,
  errors,
  scanId,
  recentRendered,
  deletePreview,
  deleteLoading,
  deleting,
  onDelete
}: {
  scan: Scan;
  job?: Job;
  workerHealth?: WorkerHealth;
  pages: Page[];
  errors: Snapshot[];
  scanId: string;
  recentRendered: RenderedObservationIndexItem[];
  deletePreview?: {
    can_delete: boolean;
    snapshots: number;
    link_occurrences: number;
    unique_resources: number;
    html_blobs_referenced: number;
    exclusive_html_blobs: number;
    shared_html_blobs: number;
    html_blobs_deleted: number;
    stored_html_bytes_reclaimable: number;
    rendered_observations?: number;
    rendered_artifacts?: number;
    artifact_blobs_referenced?: number;
    exclusive_artifact_blobs?: number;
    shared_artifact_blobs?: number;
    stored_artifact_bytes_reclaimable?: number;
    reason: string | null;
    warnings: string[];
  };
  deleteLoading: boolean;
  deleting: boolean;
  onDelete: () => void;
}) {
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
          <h2 className="mb-4 text-base font-semibold">Static request attempts</h2>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
            <Metric label="Attempts" value={scan.static_request_attempt_count} />
            <Metric label="Retry requests" value={scan.static_retry_request_count} />
            <Metric label="Recovered" value={scan.static_recovered_after_retry_count} />
            <Metric label="Exhausted" value={scan.static_retry_exhausted_count} />
            <Metric label="Connect timeouts" value={scan.static_connection_timeout_count} />
            <Metric label="Read timeouts" value={scan.static_read_timeout_count} />
            <Metric label="Connection errors" value={scan.static_connection_error_count} />
          </div>
          <p className="mt-3 text-xs text-stone-600">Attempt errors are retained as evidence. Final failed Pages are counted separately above.</p>
        </section>
        <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
          <h2 className="mb-4 text-base font-semibold">Scan summary</h2>
          <DefinitionList
            items={[
              { label: "Starting URL", value: scan.starting_url, copyValue: scan.starting_url },
              { label: "Site", value: scan.website_property_name ? <Link to={`/sites/${scan.website_property_id}`} className="underline">{scan.website_property_name}</Link> : "Ad hoc" },
              { label: "Status", value: <StatusBadge status={scan.status} /> },
              ...(job ? [
                { label: "Job", value: <StatusBadge status={job.presentation_status} label={formatStatus(job.presentation_status)} /> },
                { label: "Current operation", value: job.current_operation ?? job.progress_unit ?? "Not reported" },
                { label: "Worker", value: job.worker_id ?? (workerHealth?.queued_work_has_worker === false ? "Waiting for worker" : "Not claimed yet") }
              ] : []),
              { label: "Started", value: formatDate(scan.started_at, { timeZone: scan.website_property_display_timezone, showTimeZone: true }) },
              { label: "Finished", value: formatDate(scan.finished_at, { timeZone: scan.website_property_display_timezone, showTimeZone: true }) },
              { label: "Duration", value: formatDuration(scan.started_at, scan.finished_at ?? undefined) },
              { label: "Stop reason", value: scan.stop_reason ?? (active ? "Running" : "Not recorded") },
              { label: "HTTP error responses", value: httpErrors },
              { label: "Crawler or network failures", value: crawlerFailures },
              { label: "Fatal error", value: scan.fatal_error_message ?? "None" }
            ]}
          />
        </section>
        <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
          <div className="mb-3 flex items-center justify-between gap-3"><h2 className="text-base font-semibold">Rendered captures</h2><Link to={`/scans/${scanId}?tab=rendered`} className="text-sm font-medium underline">View rendered captures</Link></div>
          {recentRendered.length ? <div className="divide-y divide-stone-100">{recentRendered.map((item) => <Link key={item.id} to={`/scans/${scanId}/pages/${item.snapshot_id}?tab=rendered`} className="flex items-center justify-between gap-3 py-2 text-sm hover:bg-stone-50"><span className="min-w-0"><span className="block truncate">{item.page_title ?? "Untitled Page"}</span><span className="block truncate font-mono text-xs text-stone-500">{item.static_final_url}</span></span><span className="flex shrink-0 items-center gap-2"><StatusBadge status={item.capture_state} label={item.navigation_http_status === 429 ? "Rate limited" : item.error_type === "host_rate_limit_circuit_open" ? "Not attempted - host throttled" : undefined} /><span className="text-xs text-stone-500">{item.duration_ms == null ? "" : `${item.duration_ms} ms`}</span></span></Link>)}</div> : <p className="text-sm text-stone-600">{scan.scope_config.render_mode === "none" ? "Browser rendering was not requested for this Scan." : "No rendered observations were recorded."}</p>}
        </section>
        <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
          <h2 className="mb-4 text-base font-semibold">Scope configuration</h2>
          <ScopeSummary scope={scan.scope_config} />
          <details className="mt-4">
            <summary className="cursor-pointer text-sm font-medium">View scan configuration</summary>
            <pre className="mt-3 max-h-80 overflow-auto rounded-md border border-stone-200 bg-stone-50 p-3 text-xs">{JSON.stringify(scan.scope_config, null, 2)}</pre>
          </details>
        </section>
        {isTerminalStatus(scan.status) ? (
          <section className="rounded-md border border-red-200 bg-white p-4 shadow-sm">
            <h2 className="mb-3 text-base font-semibold text-red-900">Delete scan</h2>
            {deleteLoading ? <LoadingBlock label="Loading delete preview..." /> : null}
            {deletePreview ? (
              <div className="space-y-3 text-sm">
                <p className="text-stone-700">
                  Deleting this scan removes {deletePreview.snapshots} page snapshots and {deletePreview.link_occurrences} link occurrences.
                  {deletePreview.exclusive_html_blobs} of {deletePreview.html_blobs_referenced} referenced HTML captures will be deleted because no other scan uses them.
                  {deletePreview.shared_html_blobs} shared captures will be retained. Estimated storage reclaimed: {formatBytes(deletePreview.stored_html_bytes_reclaimable)}.
                  {deletePreview.rendered_observations ? ` ${deletePreview.rendered_observations} rendered observations and ${deletePreview.rendered_artifacts ?? 0} artifact associations are included; ${deletePreview.shared_artifact_blobs ?? 0} shared rendered blobs remain. Additional rendered storage reclaimed: ${formatBytes(deletePreview.stored_artifact_bytes_reclaimable ?? 0)}.` : ""}
                </p>
                {deletePreview.reason ? <p className="text-amber-700">{deletePreview.reason}</p> : null}
                <Button type="button" variant="danger" disabled={!deletePreview.can_delete} loading={deleting} onClick={onDelete}>
                  Delete scan permanently
                </Button>
              </div>
            ) : null}
          </section>
        ) : null}
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

function JobNotice({ job, workerHealth }: { job: Job; workerHealth?: WorkerHealth }) {
  const waitingForWorker = job.presentation_status === "waiting_for_worker" || (job.status === "queued" && workerHealth?.queued_work_has_worker === false);
  const cancelling = job.presentation_status === "cancelling";
  const tone = waitingForWorker ? "border-amber-200 bg-amber-50 text-amber-950" : cancelling ? "border-red-200 bg-red-50 text-red-950" : "border-sky-200 bg-sky-50 text-sky-950";
  const progress = job.progress_total && job.progress_current != null
    ? `${job.progress_current} of ${job.progress_total} ${job.progress_unit ?? "items"}`
    : job.progress_current != null
      ? `${job.progress_current} ${job.progress_unit ?? "items"}`
      : null;
  return (
    <div className={`mb-4 rounded-md border p-4 text-sm ${tone}`} aria-live="polite">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge status={job.presentation_status} label={formatStatus(job.presentation_status)} />
        <span className="font-medium">
          {waitingForWorker ? "Queued scan is waiting for a worker" : cancelling ? "Cancellation has been requested" : job.current_operation ?? "Scan job is active"}
        </span>
      </div>
      <div className="mt-1">
        {progress ? `${progress}. ` : ""}
        {job.worker_id ? `Worker ${job.worker_id}` : waitingForWorker ? "Start the background worker to process queued work." : "The job has not been claimed yet."}
      </div>
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
  const pagination = useUrlPagination({ prefix: "pages", total });
  const controls = <PaginatedTableControls total={total} limit={pagination.limit} offset={pagination.offset} onPageChange={pagination.setPage} onPageSizeChange={pagination.setPageSize} itemLabel="Page" isLoading={loading && pages.length > 0} />;
  if (error) return <ErrorBanner error={error} title="Could not load pages" />;
  return (
    <div className="space-y-4">
      <div className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-6">
          <input aria-label="Search pages" value={searchDraft} onChange={(event) => setSearchDraft(event.target.value)} placeholder="Search URLs or titles" className={`${inputClass()} lg:col-span-2`} />
          <input aria-label="HTTP status" value={searchParams.get("status") ?? ""} onChange={(event) => updateParam(setSearchParams, "status", event.target.value || null, { pages_offset: null })} placeholder="Status" className={inputClass()} />
          <input aria-label="Host filter" value={searchParams.get("host") ?? ""} onChange={(event) => updateParam(setSearchParams, "host", event.target.value || null, { pages_offset: null })} placeholder="Host" className={inputClass()} />
          <input aria-label="Minimum depth" type="number" min={0} value={searchParams.get("min_depth") ?? ""} onChange={(event) => updateParam(setSearchParams, "min_depth", event.target.value || null, { pages_offset: null })} placeholder="Min depth" className={inputClass()} />
          <input aria-label="Maximum depth" type="number" min={0} value={searchParams.get("max_depth") ?? ""} onChange={(event) => updateParam(setSearchParams, "max_depth", event.target.value || null, { pages_offset: null })} placeholder="Max depth" className={inputClass()} />
          <input aria-label="Path prefix" value={searchParams.get("path_prefix") ?? ""} onChange={(event) => updateParam(setSearchParams, "path_prefix", event.target.value || null, { pages_offset: null })} placeholder="/path/" className={inputClass()} />
          <select aria-label="Error state" value={searchParams.get("error_state") ?? "any"} onChange={(event) => updateParam(setSearchParams, "error_state", event.target.value === "any" ? null : event.target.value, { pages_offset: null })} className={inputClass()}>
            <option value="any">All states</option>
            <option value="with_errors">Errors only</option>
            <option value="without_errors">No crawler errors</option>
          </select>
          <select aria-label="Rendered state" value={searchParams.get("rendered_state") ?? "any"} onChange={(event) => updateParam(setSearchParams, "rendered_state", event.target.value === "any" ? null : event.target.value, { pages_offset: null })} className={inputClass()}>
            <option value="any">Any rendered state</option><option value="not_requested">Not requested</option><option value="captured">Captured</option><option value="captured_with_warnings">Captured with warnings</option><option value="failed">Failed</option><option value="skipped">Skipped</option><option value="interrupted">Interrupted</option>
          </select>
          <select aria-label="Sort pages" value={searchParams.get("sort") ?? "requested_url"} onChange={(event) => updateParam(setSearchParams, "sort", event.target.value, { pages_offset: null })} className={inputClass()}>
            <option value="requested_url">URL</option>
            <option value="status">HTTP status</option>
            <option value="title">Title</option>
            <option value="depth">Depth</option>
            <option value="duration">Duration</option>
            <option value="rendered_state">Rendered state</option>
          </select>
          <select aria-label="Sort direction" value={searchParams.get("direction") ?? "asc"} onChange={(event) => updateParam(setSearchParams, "direction", event.target.value, { pages_offset: null })} className={inputClass()}>
            <option value="asc">Ascending</option>
            <option value="desc">Descending</option>
          </select>
          <label className="flex items-center gap-2 rounded-md border border-stone-200 bg-white px-3 py-2 text-sm">
            <input type="checkbox" checked={searchParams.get("error_state") === "with_errors"} onChange={(event) => updateParam(setSearchParams, "error_state", event.target.checked ? "with_errors" : null, { pages_offset: null })} className="size-4 rounded border-stone-300 focus:ring-neutral-900" />
            Error-only
          </label>
          <Button type="button" variant="ghost" onClick={() => setSearchParams(tabOnly(searchParams))}>Clear filters</Button>
        </div>
      </div>
      {controls}
      {loading ? <LoadingBlock label="Loading pages..." /> : null}
      {!loading && pages.length === 0 ? (
        <EmptyState
          title={activeScan ? "Pages are still being discovered" : hasFilters(searchParams) ? "No pages match these filters" : "No pages recorded"}
          message={activeScan ? "Fetched pages will appear here as the scan progresses." : hasFilters(searchParams) ? "Clear filters or broaden the search." : "This scan did not return page snapshots."}
        />
      ) : (
        <PageTable scanId={scanId} pages={pages} activeSort={searchParams.get("sort")} direction={searchParams.get("direction") as SortDirection | null} onSort={(column, direction) => setScanPageSort(setSearchParams, column, direction)} />
      )}
      {controls}
    </div>
  );
}

function PageTable({ pages, scanId, activeSort, direction, onSort }: { pages: Page[]; scanId: string; activeSort: string | null; direction: SortDirection | null; onSort: (column: string | null, direction: SortDirection | null) => void }) {
  return (
    <div className="overflow-x-auto rounded-md border border-stone-200 bg-white shadow-sm">
      <table className="min-w-full text-left text-sm">
        <thead className="bg-stone-100 text-xs uppercase text-stone-500">
          <tr>
            {[["status", "Status"], ["requested_url", "URL"], ["title", "Title"], ["depth", "Depth"], ["content_type", "Content type"], ["duration", "Duration"], ["inbound", "Inbound"], ["rendered_state", "Rendered"], ["error", "Error"]].map(([column, label]) => <SortableTableHeader key={column} column={column} label={label} activeColumn={activeSort} direction={direction} onChange={onSort} />)}
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
                <td className="px-3 py-2">
                  <span className="block">{page.inbound_occurrence_count}</span>
                  <span className="block text-xs text-stone-500">{page.inbound_source_page_count} sources</span>
                </td>
                <td className="whitespace-nowrap px-3 py-2">{page.rendered_capture_state ? <Link to={`/scans/${scanId}/pages/${page.id}?tab=rendered`} aria-label={`Open rendered evidence for ${page.requested_url}`} className="inline-block rounded-md focus:outline-none focus:ring-2 focus:ring-neutral-900"><StatusBadge status={page.rendered_capture_state} /></Link> : "Not attempted"}</td>
                <td className="max-w-xs truncate px-3 py-2">{page.error_type ? formatStatus(page.error_type) : "None"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function setScanPageSort(setSearchParams: ReturnType<typeof useSearchParams>[1], column: string | null, direction: SortDirection | null) {
  setSearchParams((current) => {
    const next = new URLSearchParams(current);
    if (column && direction) { next.set("sort", column); next.set("direction", direction); }
    else { next.delete("sort"); next.delete("direction"); }
    next.delete("pages_offset");
    return next;
  });
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

function InputsView({ seeds, loading, error }: { seeds: ScanSeed[]; loading: boolean; error: unknown }) {
  const values = { url: (seed: ScanSeed) => seed.normalized_url ?? seed.requested_url, queue: (seed: ScanSeed) => seed.queue_state, scope: (seed: ScanSeed) => seed.scope_decision, origins: (seed: ScanSeed) => seed.origins.length };
  const { sortedItems, sort, changeSort } = useTableSort(seeds, values);
  if (error) return <ErrorBanner error={error} title="Could not load scan inputs" />;
  if (loading) return <LoadingBlock label="Loading scan inputs..." />;
  if (!seeds.length) return <EmptyState title="No saved inputs" message="This scan was created before URL inventory inputs were recorded." />;
  return (
    <div className="overflow-x-auto rounded-md border border-stone-200 bg-white shadow-sm">
      <table className="min-w-full text-left text-sm">
        <thead className="bg-stone-100 text-xs uppercase text-stone-500">
          <tr>{[["url", "URL"], ["queue", "Queue"], ["scope", "Scope"], ["origins", "Origins"]].map(([column, label]) => <SortableTableHeader key={column} column={column} label={label} activeColumn={sort?.column ?? null} direction={sort?.direction ?? null} onChange={changeSort} />)}</tr>
        </thead>
        <tbody>
          {sortedItems.map((seed) => (
            <tr key={seed.id} className="border-t border-stone-100 align-top">
              <td className="max-w-xl px-3 py-2 font-mono text-xs">{seed.normalized_url ?? seed.requested_url}</td>
              <td className="px-3 py-2">{seed.queue_state}</td>
              <td className="px-3 py-2">{seed.scope_decision}</td>
              <td className="px-3 py-2 text-xs">
                {seed.origins.map((origin) => (
                  <div key={origin.id}>{origin.origin_type}{origin.raw_url ? ` - ${origin.raw_url}` : ""}</div>
                ))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
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
  for (const key of ["search", "status", "host", "path_prefix", "min_depth", "max_depth", "error_state", "rendered_state", "sort", "direction"]) {
    const value = searchParams.get(key);
    if (value) params.set(key, value);
  }
  params.set("limit", searchParams.get("pages_limit") ?? "50");
  params.set("offset", searchParams.get("pages_offset") ?? "0");
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
  return ["search", "status", "host", "path_prefix", "min_depth", "max_depth", "error_state", "rendered_state"].some((key) => searchParams.has(key));
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
