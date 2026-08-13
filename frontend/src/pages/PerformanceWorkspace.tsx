import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useOutletContext, useParams, useSearchParams } from "react-router-dom";

import {
  cancelPerformanceRun,
  createPerformanceRun,
  getLatestPerformance,
  getPagePerformance,
  getPageLatestPerformance,
  getPerformancePayload,
  getPerformanceObservation,
  getPerformanceProviders,
  getPerformanceRun,
  listPerformanceRuns,
  performancePayloadUrl,
} from "../api/client";
import { Button } from "../components/ui/Button";
import { CollectionPageSelector } from "../components/observability/CollectionPageSelector";
import { DefinitionList } from "../components/ui/DefinitionList";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorBanner } from "../components/ui/ErrorBanner";
import { LoadingBlock } from "../components/ui/Loading";
import { PaginatedTableControls } from "../components/ui/PaginatedTableControls";
import { StatusBadge } from "../components/ui/StatusBadge";
import { Tabs } from "../components/ui/Tabs";
import type {
  PerformanceObservation,
  PerformanceObservationList,
  PerformanceProviderCapabilities,
  PerformanceRun,
  PerformanceRunPayload,
} from "../types/performance";
import type { Site } from "../types/scans";
import { formatDate, formatStatus } from "../utils/format";
import { useUrlPagination } from "../utils/useUrlPagination";

type WorkspaceContext = { site: Site };
type View = "overview" | "lab" | "field" | "runs";
const TERMINAL = new Set(["completed", "completed_with_errors", "failed", "cancelled", "interrupted"]);
const RAW_RENDER_LIMIT = 200_000;

export function SitePerformancePage() {
  const { site } = useOutletContext<WorkspaceContext>();
  const [searchParams, setSearchParams] = useSearchParams();
  const [collecting, setCollecting] = useState(false);
  const pagination = useUrlPagination({ prefix: "performance", defaultLimit: 100 });
  const requested = searchParams.get("view");
  const view: View = requested === "lab" || requested === "field" || requested === "runs" ? requested : "overview";
  const capabilities = useQuery({ queryKey: ["performance-providers", String(site.id)], queryFn: () => getPerformanceProviders(String(site.id)) });
  const provider = view === "lab" ? "pagespeed" : view === "field" ? "crux" : undefined;
  const latest = useQuery({ queryKey: ["performance-latest", String(site.id), provider, pagination.limit, pagination.offset], queryFn: () => getLatestPerformance(String(site.id), `?limit=${pagination.limit}&offset=${pagination.offset}${provider ? `&provider=${provider}` : ""}`), placeholderData: (previous) => previous });
  const runs = useQuery({
    queryKey: ["performance-runs", String(site.id)],
    queryFn: () => listPerformanceRuns(String(site.id), "?limit=25"),
    refetchInterval: (query) => query.state.data?.items.some((run) => !TERMINAL.has(run.status)) ? 2_000 : false,
  });
  if (capabilities.isLoading || latest.isLoading || runs.isLoading) return <LoadingBlock label="Loading Performance workspace..." />;
  if (capabilities.error) return <ErrorBanner error={capabilities.error} title="Could not load provider status" />;
  if (latest.error) return <ErrorBanner error={latest.error} title="Could not load Performance observations" />;
  if (runs.error) return <ErrorBanner error={runs.error} title="Could not load Performance runs" />;
  const configured = Boolean(capabilities.data?.pagespeed.configured && capabilities.data.crux.configured);
  const latestRun = runs.data?.items[0];
  const measuredPages = latest.data?.measured_page_count ?? 0;
  const fieldPhone = latest.data?.field_available_phone_page_count ?? 0;
  const fieldDesktop = latest.data?.field_available_desktop_page_count ?? 0;
  return <div className="space-y-5">
    <header className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div><h1 className="text-xl font-semibold">Performance</h1><p className="mt-1 text-sm text-stone-600">PageSpeed lab and CrUX field evidence are collected and retained separately.</p></div>
      <Button type="button" variant="primary" disabled={!configured} onClick={() => setCollecting(true)}>Collect Performance</Button>
    </header>
    {!configured ? <div className="rounded-md border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950"><strong>Google providers are not configured.</strong><p className="mt-1">Set <code>SITE_LEDGER_GOOGLE_API_KEY</code> in the backend environment, then restart the API and worker.</p></div> : null}
    <section className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-stone-200 bg-stone-200 lg:grid-cols-4">
      <Summary label="Latest run" value={latestRun ? formatStatus(latestRun.presentation_status ?? latestRun.status) : "None"} />
      <Summary label="Latest collection" value={latestRun ? formatDate(latestRun.created_at, { timeZone: site.display_timezone }) : "No evidence"} />
      <Summary label="Pages measured" value={String(measuredPages)} />
      <Summary label="Phone field coverage" value={`${fieldPhone} / ${measuredPages} Pages`} />
      <Summary label="Desktop field coverage" value={`${fieldDesktop} / ${measuredPages} Pages`} />
    </section>
    <Tabs tabs={[{ id: "overview", label: "Overview" }, { id: "lab", label: "Lab" }, { id: "field", label: "Field" }, { id: "runs", label: "Runs", count: runs.data?.total }]} active={view} onChange={(next) => setSearchParams(next === "overview" ? {} : { view: next })} />
    {view === "runs" ? <RunsTable siteId={String(site.id)} runs={runs.data?.items ?? []} /> : <LatestEvidence siteId={String(site.id)} data={latest.data} pagination={pagination} />}
    {collecting && capabilities.data ? <CollectPanel siteId={String(site.id)} capabilities={capabilities.data} onClose={() => setCollecting(false)} /> : null}
  </div>;
}

function Summary({ label, value }: { label: string; value: string }) {
  return <div className="min-w-0 bg-white p-4"><div className="text-xs font-medium uppercase text-stone-500">{label}</div><div className="mt-1 truncate text-lg font-semibold">{value}</div></div>;
}

function LatestEvidence({ siteId, data, pagination }: { siteId: string; data?: PerformanceObservationList; pagination: ReturnType<typeof useUrlPagination> }) {
  const observations = data?.items ?? [];
  if (!observations.length) return <EmptyState title="No Performance evidence" message="Collect Performance for one or more known Pages to begin a history." />;
  const controls = data ? <PaginatedTableControls total={data.total} limit={data.limit} offset={data.offset} onPageChange={pagination.setPage} onPageSizeChange={pagination.setPageSize} itemLabel="observation" /> : null;
  return <div className="space-y-3">{controls}<ObservationTable siteId={siteId} observations={observations} />{controls}</div>;
}

function ObservationTable({ siteId, observations }: { siteId: string; observations: PerformanceObservation[] }) {
  const groups = new Map<string, PerformanceObservation[]>();
  for (const observation of observations) {
    const key = observation.web_resource_id ? `page:${observation.web_resource_id}` : `origin:${observation.requested_target}`;
    groups.set(key, [...(groups.get(key) ?? []), observation]);
  }
  return <div className="overflow-x-auto rounded-md border border-stone-200 bg-white"><table className="min-w-full text-left text-sm">
    <thead className="bg-stone-100 text-xs uppercase text-stone-500"><tr><th className="px-3 py-2">Target</th><th className="px-3 py-2">Evidence by dimension</th></tr></thead>
    <tbody>{[...groups.entries()].map(([key, items]) => { const first = items[0]; return <tr key={key} className="border-t border-stone-100 align-top">
      <td className="max-w-xs px-3 py-2"><span className="block font-medium">{first.target_kind === "origin" ? "Site origin" : "Page"}</span>{first.web_resource_id ? <Link className="block truncate font-mono text-xs underline" to={`/sites/${siteId}/pages/${first.web_resource_id}`}>{first.page_url}</Link> : <span className="block truncate font-mono text-xs text-stone-500">{first.requested_target}</span>}</td>
      <td className="px-3 py-2"><div className="grid gap-3 sm:grid-cols-2">{items.map((item) => <div key={item.id} className="min-w-0 border-l-2 border-stone-200 pl-3"><div className="flex flex-wrap items-center gap-2"><strong>{item.provider === "pagespeed" ? "PageSpeed Lab" : "CrUX Field"} {formatStatus(item.dimension)}</strong><StatusBadge status={item.outcome} label={item.outcome === "unavailable" ? "URL-level field data unavailable" : undefined} /></div><div className="mt-1"><MetricSummary observation={item} /></div>{item.error_message ? <span className={`mt-1 block text-xs ${item.outcome === "failed" ? "text-red-700" : "text-stone-600"}`}>{item.error_message}</span> : null}<div className="mt-2 flex flex-wrap gap-3 text-xs"><span>{formatDate(item.observed_at)}</span><Link className="underline" to={`/sites/${siteId}/performance/observations/${item.id}`}>Inspect result</Link></div></div>)}</div></td>
    </tr>; })}</tbody>
  </table></div>;
}

function MetricSummary({ observation }: { observation: PerformanceObservation }) {
  if (observation.outcome !== "ready") return <span className="text-stone-500">No metrics</span>;
  const keys = observation.provider === "pagespeed" ? ["performance_score", "lcp", "cls"] : ["lcp", "inp", "cls"];
  return <div className="flex min-w-44 flex-wrap gap-x-3 gap-y-1">{keys.map((key) => observation.metrics_json[key] ? <span key={key}><strong className="uppercase">{key === "performance_score" ? "Score" : key}</strong> {formatMetric(key, observation.metrics_json[key].value, observation.metrics_json[key].unit)}</span> : null)}</div>;
}

function formatMetric(key: string, value: number, unit: string) {
  if (key === "performance_score") return String(Math.round(value * 100));
  if (unit === "ms" && value >= 1_000) return `${(value / 1_000).toFixed(2)} s`;
  if (unit === "score") return value.toFixed(3).replace(/0+$/, "").replace(/\.$/, "");
  return `${Math.round(value)} ${unit}`;
}

function RunsTable({ siteId, runs }: { siteId: string; runs: PerformanceRun[] }) {
  if (!runs.length) return <EmptyState title="No Performance runs" message="Performance collection is manual and on demand." />;
  return <div className="overflow-x-auto rounded-md border border-stone-200 bg-white"><table className="min-w-full text-left text-sm"><thead className="bg-stone-100 text-xs uppercase text-stone-500"><tr><th className="px-3 py-2">Run</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Progress</th><th className="hidden px-3 py-2 sm:table-cell">Results</th><th className="hidden px-3 py-2 md:table-cell">Created</th></tr></thead><tbody>{runs.map((run) => <tr key={run.id} className="border-t border-stone-100"><td className="px-3 py-2"><Link className="font-medium underline" to={`/sites/${siteId}/performance/runs/${run.id}`}>Run {run.id}</Link><span className="block text-xs text-stone-500">{run.target_count} Pages / {run.request_count} requests</span></td><td className="px-3 py-2"><StatusBadge status={run.presentation_status ?? run.status} /></td><td className="px-3 py-2 tabular-nums">{run.completed_count} / {run.request_count}</td><td className="hidden px-3 py-2 sm:table-cell">{run.ready_count} ready, {run.unavailable_count} unavailable, {run.failed_count} failed</td><td className="hidden whitespace-nowrap px-3 py-2 md:table-cell">{formatDate(run.created_at)}</td></tr>)}</tbody></table></div>;
}

function CollectPanel({ siteId, capabilities, onClose, initialResourceId }: { siteId: string; capabilities: PerformanceProviderCapabilities; onClose: () => void; initialResourceId?: number }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const dialogRef = useRef<HTMLElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const [selected, setSelected] = useState<number[]>(initialResourceId ? [initialResourceId] : []);
  const [pagespeed, setPagespeed] = useState(true);
  const [crux, setCrux] = useState(true);
  const [mobile, setMobile] = useState(true);
  const [desktop, setDesktop] = useState(true);
  const [phone, setPhone] = useState(true);
  const [cruxDesktop, setCruxDesktop] = useState(true);
  const [origin, setOrigin] = useState(true);
  const pageSpeedMobile = pagespeed && mobile ? selected.length : 0;
  const pageSpeedDesktop = pagespeed && desktop ? selected.length : 0;
  const cruxPhoneUrl = crux && phone ? selected.length : 0;
  const cruxDesktopUrl = crux && cruxDesktop ? selected.length : 0;
  const cruxPhoneOrigin = crux && origin && phone ? 1 : 0;
  const cruxDesktopOrigin = crux && origin && cruxDesktop ? 1 : 0;
  const requestCount = pageSpeedMobile + pageSpeedDesktop + cruxPhoneUrl + cruxDesktopUrl + cruxPhoneOrigin + cruxDesktopOrigin;
  const payload: PerformanceRunPayload = { resource_ids: selected, providers: [...(pagespeed ? ["pagespeed" as const] : []), ...(crux ? ["crux" as const] : [])], pagespeed_strategies: [...(mobile ? ["mobile" as const] : []), ...(desktop ? ["desktop" as const] : [])], crux_form_factors: [...(phone ? ["PHONE" as const] : []), ...(cruxDesktop ? ["DESKTOP" as const] : [])], include_origin_crux: origin, trigger: initialResourceId ? "page_workspace" : "site_workspace" };
  const create = useMutation({ mutationFn: () => createPerformanceRun(siteId, payload), onSuccess: async (run) => { await queryClient.invalidateQueries({ queryKey: ["performance-runs", siteId] }); navigate(`/sites/${siteId}/performance/runs/${run.id}`); } });
  const runPageLimit = capabilities.hard_page_limit;
  useEffect(() => {
    const previouslyFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const dialog = dialogRef.current;
    const focusable = () => Array.from(dialog?.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), select:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])') ?? []);
    focusable()[0]?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const items = focusable();
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    dialog?.addEventListener("keydown", handleKeyDown);
    return () => {
      dialog?.removeEventListener("keydown", handleKeyDown);
      previouslyFocused?.focus();
    };
  }, []);
  return <section ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="collect-performance-title" className="fixed inset-0 z-50 overflow-y-auto bg-black/40 p-3 sm:p-8"><div className="mx-auto max-w-3xl rounded-md bg-white p-4 shadow-xl sm:p-6">
    <header className="flex items-start justify-between gap-3"><div><h2 id="collect-performance-title" className="text-lg font-semibold">Collect Performance</h2><p className="text-sm text-stone-600">Recommended batch: {capabilities.default_page_limit} Pages. Hard limit: {runPageLimit}. Provider calls run serially.</p></div><button type="button" aria-label="Close Performance collection" onClick={onClose} className="rounded p-2 hover:bg-stone-100"><X size={20} /></button></header>
    {!initialResourceId ? <div className="mt-5"><CollectionPageSelector siteId={siteId} selected={selected} hardLimit={runPageLimit} label="Performance" onChange={setSelected} /></div> : null}
    <div className="mt-5 grid gap-4 border-t border-stone-200 pt-5 md:grid-cols-2"><fieldset><legend className="font-medium">PageSpeed Lab</legend><Check label="PageSpeed" checked={pagespeed} onChange={setPagespeed} disabled={!capabilities.pagespeed.configured} /><Check label="Mobile" checked={mobile} onChange={setMobile} disabled={!pagespeed} /><Check label="Desktop" checked={desktop} onChange={setDesktop} disabled={!pagespeed} /></fieldset><fieldset><legend className="font-medium">CrUX Field</legend><Check label="CrUX" checked={crux} onChange={setCrux} disabled={!capabilities.crux.configured} /><Check label="Phone" checked={phone} onChange={setPhone} disabled={!crux} /><Check label="Desktop" checked={cruxDesktop} onChange={setCruxDesktop} disabled={!crux} /><Check label="Include Site origin" checked={origin} onChange={setOrigin} disabled={!crux} /></fieldset></div>
    <div className="mt-5 border-t border-stone-200 pt-4"><dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-3"><div>PageSpeed Mobile: <strong>{pageSpeedMobile}</strong></div><div>PageSpeed Desktop: <strong>{pageSpeedDesktop}</strong></div><div>CrUX Phone URL: <strong>{cruxPhoneUrl}</strong></div><div>CrUX Desktop URL: <strong>{cruxDesktopUrl}</strong></div><div>CrUX Phone Origin: <strong>{cruxPhoneOrigin}</strong></div><div>CrUX Desktop Origin: <strong>{cruxDesktopOrigin}</strong></div></dl><p className="mt-2 text-sm">Total: <strong>{requestCount}</strong> provider requests.</p>{selected.length > capabilities.default_page_limit ? <p className="mt-3 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm">This exceeds the recommended {capabilities.default_page_limit}-Page batch. Large runs may take significant time and consume provider quota.</p> : null}<div className="mt-4 flex justify-end gap-2"><Button type="button" onClick={onClose}>Cancel</Button><Button type="button" variant="primary" loading={create.isPending} disabled={!selected.length || !requestCount || requestCount > capabilities.max_provider_requests} onClick={() => create.mutate()}>Start collection</Button></div></div>{create.error ? <div className="mt-3"><ErrorBanner error={create.error} title="Could not start Performance collection" /></div> : null}
  </div></section>;
}

function Check({ label, checked, onChange, disabled }: { label: string; checked: boolean; onChange: (checked: boolean) => void; disabled?: boolean }) {
  return <label className="mt-2 flex items-center gap-2 text-sm"><input type="checkbox" checked={checked} disabled={disabled} onChange={(event) => onChange(event.target.checked)} />{label}</label>;
}

export function PerformanceRunPage() {
  const { site } = useOutletContext<WorkspaceContext>();
  const { runId = "" } = useParams();
  const queryClient = useQueryClient();
  const run = useQuery({ queryKey: ["performance-run", String(site.id), runId], queryFn: () => getPerformanceRun(String(site.id), runId, "?limit=500"), refetchInterval: (query) => query.state.data && !TERMINAL.has(query.state.data.status) ? 2_000 : false });
  const cancel = useMutation({ mutationFn: () => cancelPerformanceRun(String(site.id), runId), onSuccess: () => queryClient.invalidateQueries({ queryKey: ["performance-run", String(site.id), runId] }) });
  if (run.isLoading) return <LoadingBlock label="Loading Performance run..." />;
  if (run.error) return <ErrorBanner error={run.error} title="Could not load Performance run" />;
  if (!run.data) return null;
  const value = run.data;
  return <div className="space-y-5"><header className="flex flex-wrap items-start justify-between gap-3"><div><Link className="text-sm underline" to={`/sites/${site.id}/performance?view=runs`}>Performance runs</Link><h1 className="mt-1 text-xl font-semibold">Run {value.id}</h1></div>{!TERMINAL.has(value.status) ? <Button type="button" variant="danger" loading={cancel.isPending} onClick={() => cancel.mutate()}>Cancel run</Button> : null}</header>
    <section className="rounded-md border border-stone-200 bg-white p-4"><DefinitionList items={[{ label: "Status", value: <StatusBadge status={value.presentation_status ?? value.status} /> }, { label: "Progress", value: `${value.completed_count} of ${value.request_count} requests` }, { label: "Ready", value: value.ready_count }, { label: "Unavailable", value: value.unavailable_count }, { label: "Failed", value: value.failed_count }, { label: "Created", value: formatDate(value.created_at) }, { label: "Started", value: value.started_at ? formatDate(value.started_at) : "Not started" }, { label: "Finished", value: value.finished_at ? formatDate(value.finished_at) : "In progress" }, { label: "Providers", value: value.configuration_json.providers.join(", ") }, { label: "Dimensions", value: [...value.configuration_json.pagespeed_strategies, ...value.configuration_json.crux_form_factors].join(", ") }]} />{value.error_summary ? <p className="mt-4 text-sm text-red-700">{value.error_summary}</p> : null}</section>
    <ObservationTable siteId={String(site.id)} observations={value.observations.items} />
  </div>;
}

export function PerformanceEvidencePage() {
  const { site } = useOutletContext<WorkspaceContext>();
  const { observationId = "" } = useParams();
  const payload = useQuery({ queryKey: ["performance-payload", observationId], queryFn: () => getPerformancePayload(Number(observationId)) });
  const latest = useQuery({ queryKey: ["performance-evidence-metadata", String(site.id), observationId], queryFn: () => getPerformanceObservation(String(site.id), Number(observationId)) });
  if (payload.isLoading || latest.isLoading) return <LoadingBlock label="Loading raw Performance evidence..." />;
  if (payload.error) return <ErrorBanner error={payload.error} title="Could not load raw Performance evidence" />;
  const observation = latest.data;
  if (!observation) return <EmptyState title="Evidence not found" message="The observation is not part of the latest Site evidence view. Open it from its Performance run." />;
  const content = payload.data ?? "";
  const truncated = content.length > RAW_RENDER_LIMIT;
  return <div className="space-y-4"><header><Link className="text-sm underline" to={`/sites/${site.id}/performance/runs/${observation.performance_run_id}`}>Run {observation.performance_run_id}</Link><h1 className="mt-1 text-xl font-semibold">Raw provider evidence</h1></header><section className="rounded-md border border-stone-200 bg-white p-4"><DefinitionList items={[{ label: "Provider", value: observation.provider }, { label: "Dimension", value: observation.dimension }, { label: "Outcome", value: observation.outcome }, { label: "Provider adapter", value: observation.provider_adapter_version }, { label: "Normalization", value: observation.normalization_version }, { label: "Payload SHA-256", value: observation.payload_sha256, copyValue: observation.payload_sha256 }, { label: "Raw bytes", value: observation.payload_raw_byte_size?.toLocaleString() }, { label: "Requested target", value: observation.requested_target }, { label: "Provider target", value: observation.provider_target }]} /></section>{truncated ? <p className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm">Browser display is limited to {RAW_RENDER_LIMIT.toLocaleString()} characters. The retained payload remains exact. <a className="underline" href={performancePayloadUrl(observation.id)} target="_blank" rel="noreferrer">Open full payload <ExternalLink className="inline" size={14} /></a></p> : null}<pre tabIndex={0} className="max-h-[65vh] overflow-auto whitespace-pre-wrap break-all rounded-md border border-stone-300 bg-stone-950 p-4 font-mono text-xs text-stone-100">{content.slice(0, RAW_RENDER_LIMIT)}</pre></div>;
}

export function PagePerformancePanel({ siteId, resourceId }: { siteId: string; resourceId: string }) {
  const [collecting, setCollecting] = useState(false);
  const pagination = useUrlPagination({ prefix: "performance_history", defaultLimit: 25 });
  const history = useQuery({ queryKey: ["page-performance", siteId, resourceId, pagination.limit, pagination.offset], queryFn: () => getPagePerformance(siteId, resourceId, `?limit=${pagination.limit}&offset=${pagination.offset}`) });
  const current = useQuery({ queryKey: ["page-performance-latest", siteId, resourceId], queryFn: () => getPageLatestPerformance(siteId, resourceId) });
  const capabilities = useQuery({ queryKey: ["performance-providers", siteId], queryFn: () => getPerformanceProviders(siteId) });
  if (history.isLoading || current.isLoading || capabilities.isLoading) return <LoadingBlock label="Loading Page Performance..." />;
  if (history.error) return <ErrorBanner error={history.error} title="Could not load Page Performance" />;
  const configured = Boolean(capabilities.data?.pagespeed.configured && capabilities.data.crux.configured);
  if (current.error) return <ErrorBanner error={current.error} title="Could not load latest Page Performance" />;
  const latest = latestByDimension(current.data?.items ?? []);
  const controls = history.data?.items.length ? <PaginatedTableControls total={history.data.total} limit={history.data.limit} offset={history.data.offset} onPageChange={pagination.setPage} onPageSizeChange={pagination.setPageSize} itemLabel="observation" /> : null;
  return <div className="space-y-4"><div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-semibold">External Performance evidence</h2><p className="text-sm text-stone-600">Lab and field observations occur independently of Scans.</p></div><Button type="button" variant="primary" disabled={!configured} onClick={() => setCollecting(true)}>Run Performance for this Page</Button></div>{!configured ? <p className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm">Set <code>SITE_LEDGER_GOOGLE_API_KEY</code> to collect Performance evidence.</p> : null}<section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{[["Latest Lab Mobile", latest.get("pagespeed:mobile")], ["Latest Lab Desktop", latest.get("pagespeed:desktop")], ["Latest Field Phone", latest.get("crux:PHONE")], ["Latest Field Desktop", latest.get("crux:DESKTOP")]].map(([label, item]) => <div key={String(label)} className="rounded-md border border-stone-200 bg-white p-3"><h3 className="text-xs font-medium uppercase text-stone-500">{String(label)}</h3><div className="mt-2">{item && typeof item !== "string" ? <><StatusBadge status={item.outcome} /><div className="mt-2 text-sm"><MetricSummary observation={item} /></div></> : <span className="text-sm text-stone-500">Not observed</span>}</div></div>)}</section>{controls}{history.data?.items.length ? <ObservationTable siteId={siteId} observations={history.data.items} /> : <EmptyState title="No Page Performance history" message="Run Performance to collect the first immutable observation." />}{controls}{collecting && capabilities.data ? <CollectPanel siteId={siteId} capabilities={capabilities.data} initialResourceId={Number(resourceId)} onClose={() => setCollecting(false)} /> : null}</div>;
}

function latestByDimension(items: PerformanceObservation[]) {
  const result = new Map<string, PerformanceObservation>();
  for (const item of items) {
    if (item.target_kind === "url" && !result.has(`${item.provider}:${item.dimension}`)) result.set(`${item.provider}:${item.dimension}`, item);
  }
  return result;
}
