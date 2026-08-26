import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MonitorUp, RotateCcw, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useOutletContext, useParams } from "react-router-dom";

import {
  cancelRenderRun,
  createRenderRun,
  getRenderRun,
  getPageRenderHistory,
  getRenderCapabilities,
  getSiteRenderedObservation,
  listRenderRunObservations,
  listRenderRuns,
  rerenderTargets,
} from "../api/client";
import { CollectionPageSelector } from "../components/observability/CollectionPageSelector";
import { RenderedObservationTable } from "../components/RenderedObservationTable";
import { RenderedObservationView } from "../components/RenderedObservationView";
import { Button } from "../components/ui/Button";
import { DefinitionList } from "../components/ui/DefinitionList";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorBanner } from "../components/ui/ErrorBanner";
import { LoadingBlock } from "../components/ui/Loading";
import { PaginatedTableControls } from "../components/ui/PaginatedTableControls";
import { StatusBadge } from "../components/ui/StatusBadge";
import { inputClass } from "../components/ui/styles";
import type { RenderCapabilities, RenderRun, ScopeConfig, Site } from "../types/scans";
import { formatDate, formatStatus } from "../utils/format";
import { useUrlPagination } from "../utils/useUrlPagination";

type WorkspaceContext = { site: Site };
const TERMINAL = new Set(["completed", "completed_with_errors", "failed", "cancelled", "interrupted"]);

export function SiteRenderedPage() {
  const { site } = useOutletContext<WorkspaceContext>();
  const [creating, setCreating] = useState(false);
  const pagination = useUrlPagination({ prefix: "render_runs", defaultLimit: 25 });
  const runs = useQuery({
    queryKey: ["render-runs", String(site.id), pagination.limit, pagination.offset],
    queryFn: () => listRenderRuns(String(site.id), `?limit=${pagination.limit}&offset=${pagination.offset}`),
    refetchInterval: (query) => query.state.data?.items.some((run) => !TERMINAL.has(run.status)) ? 2_000 : false,
  });
  useEffect(() => pagination.ensureValid(runs.data?.total), [pagination, runs.data?.total]);
  if (runs.isLoading) return <LoadingBlock label="Loading Render Runs..." />;
  if (runs.error) return <ErrorBanner error={runs.error} title="Could not load Render Runs" />;
  const latest = runs.data?.items[0];
  return <div className="space-y-5">
    <header className="flex flex-wrap items-start justify-between gap-3"><div><h1 className="text-xl font-semibold">Rendered</h1><p className="mt-1 text-sm text-stone-600">Durable browser evidence collected independently of static Scans.</p></div><Button type="button" variant="primary" onClick={() => setCreating(true)}><MonitorUp className="mr-2 size-4" />Run renders</Button></header>
    <section className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-stone-200 bg-stone-200 md:grid-cols-4"><Summary label="Latest run" value={latest ? `Run ${latest.id}` : "None"} /><Summary label="Status" value={latest ? formatStatus(latest.presentation_status ?? latest.status) : "No evidence"} /><Summary label="Successful" value={String(latest?.completed_count ?? 0)} /><Summary label="Artifacts" value={String(latest?.artifact_count ?? 0)} /></section>
    {!runs.data?.items.length ? <EmptyState title="No Render Runs" message="Choose active Pages and run browser rendering without starting a Scan." /> : <RunHistory siteId={String(site.id)} runs={runs.data.items} />}
    {runs.data?.total ? <PaginatedTableControls total={runs.data.total} limit={pagination.limit} offset={pagination.offset} onPageChange={pagination.setPage} onPageSizeChange={pagination.setPageSize} itemLabel="Render Run" /> : null}
    {creating ? <StartRenderRun siteId={String(site.id)} onClose={() => setCreating(false)} /> : null}
  </div>;
}

function Summary({ label, value }: { label: string; value: string }) {
  return <div className="min-w-0 bg-white p-4"><div className="text-xs font-medium uppercase text-stone-500">{label}</div><div className="mt-1 truncate text-lg font-semibold">{value}</div></div>;
}

function RunHistory({ siteId, runs }: { siteId: string; runs: RenderRun[] }) {
  return <div className="overflow-x-auto rounded-md border border-stone-200 bg-white"><table className="min-w-full text-left text-sm"><thead className="bg-stone-100 text-xs uppercase text-stone-500"><tr><th className="px-3 py-2">Run</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Progress</th><th className="px-3 py-2">Successful</th><th className="px-3 py-2">Errors</th><th className="px-3 py-2">Rate limited</th><th className="px-3 py-2">Skipped</th><th className="px-3 py-2">Artifacts</th><th className="px-3 py-2">Started</th><th className="px-3 py-2">Finished</th></tr></thead><tbody>{runs.map((run) => <tr key={run.id} className="border-t border-stone-100"><td className="px-3 py-2"><Link className="font-medium underline" to={`/sites/${siteId}/rendered/runs/${run.id}`}>Run {run.id}</Link><span className="block text-xs text-stone-500">{formatStatus(run.trigger)}{run.source_scan_id ? ` / Scan ${run.source_scan_id}` : ""}</span></td><td className="px-3 py-2"><StatusBadge status={run.presentation_status ?? run.status} /></td><td className="px-3 py-2 tabular-nums">{run.completed_count + run.failed_count + run.skipped_count} / {run.target_count}</td><td className="px-3 py-2 tabular-nums">{run.summary.successful_renders}</td><td className="px-3 py-2 tabular-nums">{run.summary.http_error_responses + run.summary.technical_failures}</td><td className="px-3 py-2 tabular-nums">{run.summary.rate_limited}</td><td className="px-3 py-2 tabular-nums">{run.summary.skipped_after_throttling}</td><td className="px-3 py-2 tabular-nums">{run.artifact_count}</td><td className="whitespace-nowrap px-3 py-2">{run.started_at ? formatDate(run.started_at) : "Waiting"}</td><td className="whitespace-nowrap px-3 py-2">{run.finished_at ? formatDate(run.finished_at) : "In progress"}</td></tr>)}</tbody></table></div>;
}

function StartRenderRun({ siteId, onClose }: { siteId: string; onClose: () => void }) {
  const [selected, setSelected] = useState<number[]>([]);
  const [configuration, setConfiguration] = useState<Partial<ScopeConfig>>({});
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const dialogRef = useRef<HTMLElement>(null);
  const capabilities = useQuery({ queryKey: ["render-capabilities"], queryFn: getRenderCapabilities });
  const create = useMutation({ mutationFn: () => createRenderRun(siteId, selected, "site_workspace", configuration), onSuccess: async (run) => { await queryClient.invalidateQueries({ queryKey: ["render-runs", siteId] }); navigate(`/sites/${siteId}/rendered/runs/${run.id}`); } });
  useEffect(() => { dialogRef.current?.querySelector<HTMLElement>("button")?.focus(); }, []);
  return <section ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="start-render-title" className="fixed inset-0 z-50 overflow-y-auto bg-black/40 p-3 sm:p-8"><div className="mx-auto max-w-3xl rounded-md bg-white p-4 shadow-xl sm:p-6"><header className="flex items-start justify-between gap-3"><div><h2 id="start-render-title" className="text-lg font-semibold">Run renders</h2><p className="text-sm text-stone-600">Targets and browser configuration are frozen when the Run is queued.</p></div><button type="button" aria-label="Close Render Run" onClick={onClose} className="rounded p-2 hover:bg-stone-100"><X size={20} /></button></header><div className="mt-5"><CollectionPageSelector siteId={siteId} selected={selected} hardLimit={1_000} label="Rendered capture" onChange={setSelected} /></div>{capabilities.data ? <RenderSettings capabilities={capabilities.data} configuration={configuration} onChange={setConfiguration} /> : capabilities.error ? <div className="mt-4"><ErrorBanner error={capabilities.error} title="Could not load browser settings" /></div> : <LoadingBlock label="Loading browser settings..." />}<div className="mt-5 flex justify-end gap-2 border-t border-stone-200 pt-4"><Button type="button" onClick={onClose}>Cancel</Button><Button type="button" variant="primary" loading={create.isPending} disabled={!selected.length || !capabilities.data} onClick={() => create.mutate()}>Queue {selected.length} {selected.length === 1 ? "Page" : "Pages"}</Button></div>{create.error ? <div className="mt-3"><ErrorBanner error={create.error} title="Could not start Render Run" /></div> : null}</div></section>;
}

function RenderSettings({ capabilities, configuration, onChange }: { capabilities: RenderCapabilities; configuration: Partial<ScopeConfig>; onChange: (value: Partial<ScopeConfig>) => void }) {
  const numberField = (field: "render_viewport_width" | "render_viewport_height" | "render_navigation_timeout_seconds" | "render_load_timeout_seconds", label: string) => { const limits = capabilities.limits[field]; const value = Number(configuration[field] ?? capabilities.defaults[field]); return <label className="text-sm"><span className="mb-1 block font-medium">{label}</span><input aria-label={label} type="number" min={limits.minimum} max={limits.maximum} value={value} onChange={(event) => onChange({ ...configuration, [field]: Number(event.target.value) })} className={inputClass()} /></label>; };
  return <fieldset className="mt-5 border-t border-stone-200 pt-5"><legend className="font-medium">Browser settings</legend><div className="mt-3 grid gap-3 sm:grid-cols-2">{numberField("render_viewport_width", "Viewport width")}{numberField("render_viewport_height", "Viewport height")}{numberField("render_navigation_timeout_seconds", "Navigation timeout (seconds)")}{numberField("render_load_timeout_seconds", "Load timeout (seconds)")}<label className="text-sm"><span className="mb-1 block font-medium">Color scheme</span><select aria-label="Color scheme" value={String(configuration.render_color_scheme ?? capabilities.defaults.render_color_scheme)} onChange={(event) => onChange({ ...configuration, render_color_scheme: event.target.value as ScopeConfig["render_color_scheme"] })} className={inputClass()}><option value="light">Light</option><option value="dark">Dark</option><option value="no-preference">No preference</option></select></label><label className="flex items-center gap-2 self-end pb-2 text-sm"><input type="checkbox" checked={Boolean(configuration.render_capture_full_page ?? capabilities.defaults.render_capture_full_page)} onChange={(event) => onChange({ ...configuration, render_capture_full_page: event.target.checked })} className="size-4 rounded border-stone-300" />Capture full-page screenshot</label></div></fieldset>;
}

export function RenderRunPage() {
  const { site } = useOutletContext<WorkspaceContext>();
  const { runId = "" } = useParams();
  const [selected, setSelected] = useState<number[]>([]);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const run = useQuery({ queryKey: ["render-run", String(site.id), runId], queryFn: () => getRenderRun(String(site.id), runId, "?limit=1"), refetchInterval: (query) => query.state.data && !TERMINAL.has(query.state.data.status) ? 2_000 : false });
  const cancel = useMutation({ mutationFn: () => cancelRenderRun(String(site.id), runId), onSuccess: () => queryClient.invalidateQueries({ queryKey: ["render-run", String(site.id), runId] }) });
  const rerender = useMutation({ mutationFn: () => rerenderTargets(String(site.id), runId, selected), onSuccess: async (created) => { await queryClient.invalidateQueries({ queryKey: ["render-runs", String(site.id)] }); navigate(`/sites/${site.id}/rendered/runs/${created.id}`); } });
  if (run.isLoading) return <LoadingBlock label="Loading Render Run..." />;
  if (run.error) return <ErrorBanner error={run.error} title="Could not load Render Run" />;
  if (!run.data) return null;
  const value = run.data;
  return <div className="space-y-5"><header className="flex flex-wrap items-start justify-between gap-3"><div><Link className="text-sm underline" to={`/sites/${site.id}/rendered`}>Render Runs</Link><h1 className="mt-1 text-xl font-semibold">Run {value.id}</h1></div><div className="flex gap-2">{selected.length ? <Button type="button" loading={rerender.isPending} onClick={() => rerender.mutate()}><RotateCcw className="mr-2 size-4" />Rerender {selected.length}</Button> : null}{!TERMINAL.has(value.status) ? <Button type="button" variant="danger" loading={cancel.isPending} onClick={() => cancel.mutate()}>Cancel run</Button> : null}</div></header>
    <section className="rounded-md border border-stone-200 bg-white p-4"><DefinitionList items={[{ label: "Status", value: <StatusBadge status={value.presentation_status ?? value.status} /> }, { label: "Progress", value: `${value.completed_count + value.failed_count + value.skipped_count} of ${value.target_count} Pages` }, { label: "Successful / failed / skipped", value: `${value.completed_count} / ${value.failed_count} / ${value.skipped_count}` }, { label: "Trigger", value: formatStatus(value.trigger) }, { label: "Source Scan", value: value.source_scan_id ? <Link className="underline" to={`/scans/${value.source_scan_id}`}>Scan {value.source_scan_id}</Link> : "Not applicable" }, { label: "Viewport", value: `${value.configuration_json.render_viewport_width ?? "Default"} x ${value.configuration_json.render_viewport_height ?? "Default"}` }, { label: "Color scheme", value: formatStatus(String(value.configuration_json.render_color_scheme ?? "Default")) }, { label: "Full-page screenshot", value: value.configuration_json.render_capture_full_page ? "Enabled" : "Disabled" }, { label: "Created", value: formatDate(value.created_at) }, { label: "Started", value: value.started_at ? formatDate(value.started_at) : "Waiting for worker" }, { label: "Finished", value: value.finished_at ? formatDate(value.finished_at) : "In progress" }]} />{value.error_summary ? <p className="mt-4 text-sm text-red-700">{value.error_summary}</p> : null}</section>
    <RenderedObservationTable renderMode="all_eligible" queryKey={["render-run-observations", String(site.id), runId]} loadObservations={(query) => listRenderRunObservations(String(site.id), runId, query)} observationHref={(id) => `/sites/${site.id}/rendered/observations/${id}`} selectedTargetIds={selected} onSelectedTargetIdsChange={setSelected} />
    {rerender.error ? <ErrorBanner error={rerender.error} title="Could not queue rerender" /> : null}
  </div>;
}

export function RenderedEvidencePage() {
  const { site } = useOutletContext<WorkspaceContext>();
  const { observationId = "" } = useParams();
  const observation = useQuery({ queryKey: ["rendered-observation", String(site.id), observationId], queryFn: () => getSiteRenderedObservation(String(site.id), observationId) });
  if (observation.isLoading) return <LoadingBlock label="Loading rendered evidence..." />;
  if (observation.error) return <ErrorBanner error={observation.error} title="Could not load rendered evidence" />;
  if (!observation.data) return null;
  return <div className="space-y-4"><header><Link className="text-sm underline" to={`/sites/${site.id}/rendered/runs/${observation.data.render_run_id}`}>Run {observation.data.render_run_id}</Link><h1 className="mt-1 text-xl font-semibold">Rendered observation {observation.data.id}</h1></header><RenderedObservationView observation={observation.data} /></div>;
}

export function PageRenderedPanel({ siteId, resourceId }: { siteId: string; resourceId: string }) {
  const navigate = useNavigate();
  const create = useMutation({
    mutationFn: () => createRenderRun(siteId, [Number(resourceId)], "page_workspace"),
    onSuccess: (run) => navigate(`/sites/${siteId}/rendered/runs/${run.id}`),
  });
  return <div className="space-y-4"><header className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="font-semibold">Rendered evidence</h2><p className="text-sm text-stone-600">Browser observations are retained independently of Scans.</p></div><Button type="button" variant="primary" loading={create.isPending} onClick={() => create.mutate()}><MonitorUp className="mr-2 size-4" />Render this Page</Button></header>{create.error ? <ErrorBanner error={create.error} title="Could not start Render Run" /> : null}<RenderedObservationTable renderMode="all_eligible" queryKey={["page-render-history", siteId, resourceId]} loadObservations={(query) => getPageRenderHistory(siteId, resourceId, query)} observationHref={(id) => `/sites/${siteId}/rendered/observations/${id}`} /></div>;
}
