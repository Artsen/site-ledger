import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, Accessibility, Braces, FileStack, Gauge, GitCompareArrows, MonitorUp, Plus, SearchCheck, Settings } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { getSiteIntelligence } from "../../api/siteIntelligence";
import { createCollectionPlan, previewCollectionPlan } from "../../api/collectionPlans";
import { Button } from "../../components/ui/Button";
import { ErrorBanner } from "../../components/ui/ErrorBanner";
import { LoadingBlock } from "../../components/ui/Loading";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { siteAreaHref, type SiteArea } from "../../navigation/workspaceNavigation";
import type { Site } from "../../types/scans";
import type { CollectionCoverage, CollectionPlanRequest } from "../../types/collectionPlans";
import type { EvidenceCoverage, EvidenceClock } from "../../types/siteIntelligence";
import { formatDate, formatStatus } from "../../utils/format";

function clockDate(clock: EvidenceClock) {
  return clock.latest_observed_at ?? clock.latest_completed_at;
}

function Coverage({ value }: { value: EvidenceCoverage }) {
  const percent = value.ratio === null ? null : Math.round(value.ratio * 100);
  return (
    <div className="mt-2">
      <div className="flex items-baseline justify-between gap-3 text-sm">
        <span>{value.observed.toLocaleString()} of {value.eligible.toLocaleString()}</span>
        <span className="font-medium">{percent === null ? "Not applicable" : `${percent}%`}</span>
      </div>
      <div className="mt-1 h-1.5 overflow-hidden rounded bg-stone-200" aria-hidden="true">
        <div className="h-full bg-emerald-600" style={{ width: `${percent ?? 0}%` }} />
      </div>
    </div>
  );
}

function EvidencePanel({ title, area, icon: Icon, coverage, clock, children, site }: {
  title: string; area: SiteArea; icon: typeof FileStack; coverage: EvidenceCoverage;
  clock: EvidenceClock; children?: React.ReactNode; site: Site;
}) {
  const observed = clockDate(clock);
  return (
    <section className="border-t border-stone-200 py-4 first:border-t-0">
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 items-center gap-2"><Icon className="h-4 w-4 text-stone-500" /><h3 className="text-sm font-semibold">{title}</h3></div>
        <Link className="text-xs font-medium text-stone-700 underline" to={siteAreaHref(site.id, area)}>Open</Link>
      </div>
      <Coverage value={coverage} />
      <p className="mt-2 text-xs text-stone-500">{observed ? `Observed ${formatDate(observed, { timeZone: site.display_timezone, showTimeZone: true })}` : "No current evidence"}</p>
      {children}
    </section>
  );
}

function planRequest(coverage: CollectionCoverage): CollectionPlanRequest {
  const context = coverage.evidence_domain === "performance"
    ? { provider: coverage.context.provider, dimension: coverage.context.dimension }
    : coverage.evidence_domain === "accessibility"
      ? { profile: coverage.context.profile }
      : {};
  return { evidence_domain: coverage.evidence_domain, target_mode: "missing_current", context };
}

function collectionLabel(coverage: CollectionCoverage) {
  if (coverage.context.provider) return `${formatStatus(coverage.context.provider)} / ${formatStatus(coverage.context.dimension)}`;
  if (coverage.context.profile) return formatStatus(coverage.context.profile);
  return coverage.evidence_domain === "render" ? "Current capture profile" : "Current extractor";
}

function CollectionCoverageActions({ site, values }: { site: Site; values: CollectionCoverage[] }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [visiblePreview, setVisiblePreview] = useState<Awaited<ReturnType<typeof previewCollectionPlan>> | null>(null);
  const previewMutation = useMutation({
    mutationFn: (coverage: CollectionCoverage) => previewCollectionPlan(site.id, planRequest(coverage)),
    onSuccess: setVisiblePreview,
  });
  const mutation = useMutation({
    mutationFn: async (coverage: CollectionCoverage) => {
      const payload = planRequest(coverage);
      const preview = await previewCollectionPlan(site.id, payload);
      if (!preview.missing) throw new Error("No missing current evidence remains for this context.");
      const batchSizes = Array.from({ length: preview.estimated_batch_count }, (_, index) => Math.min(preview.batch_size, preview.missing - index * preview.batch_size));
      const confirmed = window.confirm(`Collect ${preview.missing.toLocaleString()} missing Page${preview.missing === 1 ? "" : "s"}?\n\nCurrent identity:\n${preview.context_identity}\n\nPer-Run limit: ${preview.batch_size.toLocaleString()} Pages\nSite Ledger will create ${preview.estimated_batch_count} bounded batch${preview.estimated_batch_count === 1 ? "" : "es"}:\n${batchSizes.map((size, index) => `Batch ${index + 1}: ${size.toLocaleString()}`).join("\n")}\n\nCovered: ${preview.covered.toLocaleString()}\nAlready in flight: ${preview.in_flight.toLocaleString()}\nIneligible: ${preview.ineligible.toLocaleString()}\n\nTargets will be frozen when collection starts.`);
      if (!confirmed) return null;
      return createCollectionPlan(site.id, payload);
    },
    onSuccess: async (plan) => {
      if (!plan) return;
      await queryClient.invalidateQueries({ queryKey: ["site-intelligence", String(site.id)] });
      await queryClient.invalidateQueries({ queryKey: ["collection-plans", String(site.id)] });
      navigate(`/sites/${site.id}/collection-plans/${plan.id}`);
    },
  });
  return (
    <section className="border-b border-stone-200 py-4">
      <div className="flex items-center justify-between gap-3"><div><h3 className="text-sm font-semibold">Current collection contexts</h3><p className="mt-1 text-xs text-stone-500">Collect only active Pages without compatible current evidence.</p></div><Link className="text-xs font-medium underline" to={siteAreaHref(site.id, "collection-plans")}>History</Link></div>
      <div className="mt-3 divide-y divide-stone-100 border-y border-stone-100">{values.map((coverage) => <div key={coverage.context_identity} className="flex flex-wrap items-center justify-between gap-3 py-3"><div><span className="text-sm font-medium">{formatStatus(coverage.evidence_domain)} / {collectionLabel(coverage)}</span><p className="mt-0.5 text-xs text-stone-500">{coverage.covered.toLocaleString()} covered, {coverage.in_flight.toLocaleString()} in flight, {coverage.missing.toLocaleString()} missing{coverage.ineligible ? `, ${coverage.ineligible.toLocaleString()} ineligible` : ""}</p></div><div className="flex gap-2"><Button type="button" variant="ghost" className="min-h-8 px-2 py-1 text-xs" loading={previewMutation.isPending && previewMutation.variables?.context_identity === coverage.context_identity} disabled={coverage.missing === 0 || previewMutation.isPending} onClick={() => previewMutation.mutate(coverage)}>View missing</Button><Button type="button" className="min-h-8 px-2 py-1 text-xs" loading={mutation.isPending && mutation.variables?.context_identity === coverage.context_identity} disabled={!coverage.collectable || coverage.missing === 0 || mutation.isPending} title={coverage.non_collectable_reason ?? undefined} onClick={() => mutation.mutate(coverage)}><Plus className="mr-1 size-3.5" />Collect missing</Button></div></div>)}</div>
      {visiblePreview ? <div className="mt-3 rounded-md border border-stone-200 bg-stone-50 p-3"><div className="flex items-center justify-between gap-3"><div><h4 className="text-sm font-semibold">Missing preview</h4><p className="text-xs text-stone-500">Showing {visiblePreview.targets.length} of {visiblePreview.target_total.toLocaleString()} authoritative targets. Ineligible Pages are excluded.</p></div><Button variant="ghost" className="min-h-8 px-2 py-1 text-xs" onClick={() => setVisiblePreview(null)}>Close</Button></div><div className="mt-3 max-h-64 overflow-auto"><table className="min-w-full text-left text-xs"><thead className="text-stone-500"><tr><th className="pb-2 pr-3">Page</th><th className="pb-2 pr-3">Identity</th><th className="pb-2">Reason / source</th></tr></thead><tbody>{visiblePreview.targets.map((target) => <tr key={target.web_resource_id} className="border-t border-stone-200 align-top"><td className="max-w-lg break-all py-2 pr-3 font-mono">{target.requested_url}</td><td className="py-2 pr-3 tabular-nums">{target.web_resource_id}</td><td className="py-2">{formatStatus(target.selection_reason)}{target.source_snapshot_id ? <span className="block text-stone-500">Snapshot {target.source_snapshot_id} / Blob {target.content_blob_id}</span> : null}</td></tr>)}</tbody></table></div></div> : null}
      {previewMutation.error ? <div className="mt-3"><ErrorBanner error={previewMutation.error} title="Could not preview missing Pages" /></div> : null}
      {mutation.error ? <div className="mt-3"><ErrorBanner error={mutation.error} title="Could not create Collection Plan" /></div> : null}
    </section>
  );
}

export function SiteIntelligenceOverview({ site }: { site: Site }) {
  const query = useQuery({
    queryKey: ["site-intelligence", String(site.id)],
    queryFn: () => getSiteIntelligence(site.id),
    refetchInterval: (state) => state.state.data?.activity.active_job_count ? 2000 : false,
  });
  if (query.isLoading) return <LoadingBlock label="Loading Site intelligence..." />;
  if (query.error) return <ErrorBanner error={query.error} title="Could not load Site intelligence" />;
  const data = query.data;
  if (!data) return null;
  const pageChanges = data.comparison.page_counts;
  return (
    <div className="space-y-6">
      <section>
        <div className="mb-3 flex items-center justify-between gap-4"><h2 className="text-base font-semibold">Site state</h2><Link to={siteAreaHref(site.id, "settings")} className="inline-flex items-center gap-1 text-xs font-medium underline"><Settings className="h-3.5 w-3.5" />Site configuration</Link></div>
        <div className="grid gap-px overflow-hidden rounded-md border border-stone-200 bg-stone-200 sm:grid-cols-2 xl:grid-cols-4">
          <Link to={siteAreaHref(site.id, "pages")} className="bg-white p-4"><span className="text-xs text-stone-500">Active Pages</span><strong className="mt-1 block text-2xl">{data.page_population.active_page_total.toLocaleString()}</strong><span className="text-xs text-stone-500">{data.page_population.suppressed_page_total.toLocaleString()} suppressed</span></Link>
          <div className="bg-white p-4"><span className="text-xs text-stone-500">Latest static Scan</span><strong className="mt-1 block text-base">{data.scan.present ? <Link className="underline" to={`/scans/${data.scan.id}`}>Scan {data.scan.id}</Link> : "No Scan"}</strong><span className="text-xs text-stone-500">{clockDate(data.scan.clock) ? formatDate(clockDate(data.scan.clock)!, { timeZone: site.display_timezone }) : "Not observed"}</span></div>
          <div className="bg-white p-4"><span className="text-xs text-stone-500">Latest comparison</span><strong className="mt-1 block text-base">{data.comparison.present ? <Link className="underline" to={`${siteAreaHref(site.id, "comparisons")}?comparison_id=${data.comparison.comparison_id}`}>Comparison {data.comparison.comparison_id}</Link> : "Not built"}</strong><span className="text-xs text-stone-500">{data.comparison.comparison_version ?? "No compatible V3 evidence"}</span></div>
          <div className="bg-white p-4"><span className="text-xs text-stone-500">Collection activity</span><strong className="mt-1 block text-2xl">{data.activity.active_job_count}</strong><span className="text-xs text-stone-500">{data.activity.running_count} running, {data.activity.queued_count} queued</span></div>
        </div>
      </section>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.4fr)_minmax(320px,0.8fr)]">
        <section className="rounded-md border border-stone-200 bg-white px-4">
          <h2 className="border-b border-stone-200 py-4 text-base font-semibold">Evidence coverage</h2>
          <CollectionCoverageActions site={site} values={data.collection_coverage ?? []} />
          <EvidencePanel title="Static observations" area="scans" icon={FileStack} coverage={data.scan.active_page_observed} clock={data.scan.clock} site={site}><p className="mt-2 text-xs text-stone-600">{data.scan.active_page_fetched.observed.toLocaleString()} successfully fetched in the latest terminal Scan</p></EvidencePanel>
          <EvidencePanel title="Structured Content V2" area="pages" icon={Braces} coverage={data.structured_content.coverage} clock={data.structured_content.clock} site={site}><p className="mt-2 text-xs text-stone-600">{data.structured_content.ready} ready, {data.structured_content.partial} partial, {data.structured_content.not_prepared} not prepared, {data.structured_content.ineligible} without eligible retained HTML</p></EvidencePanel>
          <EvidencePanel title="Retained render evidence" area="rendered" icon={MonitorUp} coverage={data.render.retained_coverage} clock={data.render.clock} site={site}><p className="mt-2 text-xs text-stone-600">{data.render.successful} successful, {data.render.no_content} no content, {data.render.redirect} redirects, {data.render.http_error} HTTP errors, {data.render.rate_limited} rate limited, {data.render.not_attempted_host_throttled} skipped after throttling, {data.render.technical_failure} technical failures.</p><p className="mt-1 text-xs text-stone-600">Latest Run targeted {data.render.latest_run.target_count} Pages; retained Site coverage is calculated independently.</p></EvidencePanel>
          <EvidencePanel title="Accessibility" area="accessibility" icon={Accessibility} coverage={data.accessibility.coverage} clock={data.accessibility.clock} site={site}><p className="mt-2 text-xs text-stone-600">{data.accessibility.pages_with_violations} covered Pages with violations; {data.accessibility.failed_pages} with failed current evidence. Uncovered Pages are not counted as zero violations.</p></EvidencePanel>
          <section className="border-t border-stone-200 py-4"><div className="flex items-center justify-between"><div className="flex items-center gap-2"><Gauge className="h-4 w-4 text-stone-500"/><h3 className="text-sm font-semibold">Performance contexts</h3></div><Link className="text-xs font-medium underline" to={siteAreaHref(site.id, "performance")}>Open</Link></div>{data.performance.contexts.length ? <div className="mt-3 divide-y divide-stone-100 border-y border-stone-100">{data.performance.contexts.map((context) => <div className="py-3" key={`${context.provider}:${context.dimension}:${context.target_kind}:${context.provider_adapter_version}:${context.normalization_version}`}><div className="flex justify-between gap-2 text-sm"><span className="font-medium">{formatStatus(context.provider)} / {formatStatus(context.dimension)}</span><span className="text-xs text-stone-500">{context.ready} ready, {context.unavailable} unavailable, {context.failed} failed</span></div><p className="mt-1 text-xs text-stone-500">{context.target_kind} / {context.provider_adapter_version} / {context.normalization_version}</p><Coverage value={context.coverage} /></div>)}</div> : <p className="mt-2 text-xs text-stone-500">No Performance evidence. Missing measurements do not imply good performance.</p>}</section>
        </section>

        <div className="space-y-5">
          <section className="rounded-md border border-stone-200 bg-white p-4"><div className="flex items-center justify-between"><div className="flex items-center gap-2"><SearchCheck className="h-4 w-4 text-stone-500"/><h2 className="text-base font-semibold">Findings</h2></div><Link className="text-xs font-medium underline" to={siteAreaHref(site.id, "findings")}>Open</Link></div><dl className="mt-3 grid grid-cols-2 gap-3 text-sm"><div><dt className="text-xs text-stone-500">Detected</dt><dd className="font-semibold">{data.findings.detected}</dd></div><div><dt className="text-xs text-stone-500">Unknown</dt><dd className="font-semibold">{data.findings.unknown}</dd></div><div><dt className="text-xs text-stone-500">Acknowledged detected</dt><dd>{data.findings.acknowledged_detected}</dd></div><div><dt className="text-xs text-stone-500">Needs attention</dt><dd>{data.findings.unresolved_total}</dd></div></dl><p className="mt-3 text-xs text-stone-500">{data.findings.latest_evidence_horizon_at ? `Evidence horizon ${formatDate(data.findings.latest_evidence_horizon_at, { timeZone: site.display_timezone })}` : "No Finding evaluation yet"}</p></section>
          <section className="rounded-md border border-stone-200 bg-white p-4"><div className="flex items-center justify-between"><div className="flex items-center gap-2"><GitCompareArrows className="h-4 w-4 text-stone-500"/><h2 className="text-base font-semibold">Recent deterministic change</h2></div><Link className="text-xs font-medium underline" to={siteAreaHref(site.id, "comparisons")}>Comparisons</Link></div>{data.comparison.present ? <><div className="mt-3"><StatusBadge status={data.comparison.clock.source_status} /></div><dl className="mt-3 grid grid-cols-2 gap-3 text-sm">{Object.entries(pageChanges).slice(0, 8).map(([label, value]) => <div key={label}><dt className="text-xs text-stone-500">{formatStatus(label)}</dt><dd className="font-semibold">{String(value)}</dd></div>)}</dl></> : <p className="mt-3 text-sm text-stone-500">No current-compatible Scan Comparison V3 is available.</p>}</section>
          <section className="rounded-md border border-stone-200 bg-white p-4"><div className="flex items-center gap-2"><Activity className="h-4 w-4 text-stone-500"/><h2 className="text-base font-semibold">Current activity</h2></div>{data.activity.jobs.length ? <div className="mt-3 space-y-3">{data.activity.jobs.map((job) => <div key={job.id} className="border-t border-stone-100 pt-3 first:border-0 first:pt-0"><div className="flex justify-between gap-2"><span className="text-sm font-medium">{formatStatus(job.job_type)}</span><StatusBadge status={job.status}/></div><p className="mt-1 text-xs text-stone-500">{job.current_operation ?? "Waiting for progress"}{job.progress_current !== null && job.progress_total !== null ? ` - ${job.progress_current}/${job.progress_total} ${job.progress_unit ?? ""}` : ""}</p></div>)}</div> : <p className="mt-3 text-sm text-stone-500">No Site collection or build work is active.</p>}</section>
          <section className="rounded-md border border-stone-200 bg-white p-4"><h2 className="text-base font-semibold">Sources and inventory</h2><dl className="mt-3 grid grid-cols-2 gap-3 text-sm"><div><dt className="text-xs text-stone-500">Active Sources</dt><dd className="font-semibold">{data.sources.active_source_count}</dd></div><div><dt className="text-xs text-stone-500">Current URLs</dt><dd className="font-semibold">{data.sources.current_inventory_count.toLocaleString()}</dd></div><div><dt className="text-xs text-stone-500">Inactive Sources</dt><dd>{data.sources.inactive_source_count}</dd></div><div><dt className="text-xs text-stone-500">Suppressed URLs</dt><dd>{data.sources.suppressed_inventory_count}</dd></div></dl><div className="mt-3 flex gap-4 text-xs font-medium"><Link className="underline" to={siteAreaHref(site.id, "sources")}>Sources</Link><Link className="underline" to={siteAreaHref(site.id, "inventory")}>URL Inventory</Link></div></section>
        </div>
      </div>
    </div>
  );
}
