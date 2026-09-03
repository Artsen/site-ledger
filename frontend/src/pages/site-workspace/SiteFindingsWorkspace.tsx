import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Check, Play, Search, Trash2, Undo2, X } from "lucide-react";
import { FormEvent, useEffect, useId, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { createFindingEvaluation, deleteFinding, getFinding, listFindingEvaluations, listFindings, resetSiteFindings, setFindingAcknowledged } from "../../api/findings";
import { invalidateSiteIntelligence } from "../../api/queryKeys";
import { Button } from "../../components/ui/Button";
import { EmptyState } from "../../components/ui/EmptyState";
import { ErrorBanner } from "../../components/ui/ErrorBanner";
import { LoadingBlock } from "../../components/ui/Loading";
import { PaginatedTableControls } from "../../components/ui/PaginatedTableControls";
import { StatusBadge } from "../../components/ui/StatusBadge";
import type { Finding, FindingAssessment, FindingEvaluation, FindingSitemapRefreshNode } from "../../types/findings";
import type { Site } from "../../types/scans";
import { formatDate, formatStatus } from "../../utils/format";
import { useUrlPagination } from "../../utils/useUrlPagination";

export function SiteFindingsWorkspace({ site }: { site: Site }) {
  const [params, setParams] = useSearchParams();
  const view = params.get("view") === "evaluations" ? "evaluations" : "current";
  const queryClient = useQueryClient();
  const run = useMutation({
    mutationFn: () => createFindingEvaluation(site.id),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["finding-evaluations", String(site.id)] }),
        invalidateSiteIntelligence(queryClient, site.id),
      ]);
      setParams({ view: "evaluations" });
    },
  });
  return <div className="space-y-5">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="inline-flex rounded-md border border-stone-300 bg-white p-1" aria-label="Findings view">
        <button type="button" className={`rounded px-3 py-1.5 text-sm ${view === "current" ? "bg-stone-900 text-white" : "text-stone-700"}`} onClick={() => setParams({})}>Current</button>
        <button type="button" className={`rounded px-3 py-1.5 text-sm ${view === "evaluations" ? "bg-stone-900 text-white" : "text-stone-700"}`} onClick={() => setParams({ view: "evaluations" })}>Evaluations</button>
      </div>
      <Button variant="primary" loading={run.isPending} onClick={() => run.mutate()}><Play className="mr-2 size-4" />Run evaluation</Button>
    </div>
    {run.error ? <ErrorBanner error={run.error} title="Could not create Finding evaluation" /> : null}
    {view === "current" ? <CurrentFindings site={site} /> : <EvaluationHistory site={site} />}
    <section className="border-t border-red-200 pt-4">
      <h2 className="text-sm font-semibold text-red-900">Administrative reset</h2>
      <p className="mt-1 max-w-3xl text-sm text-stone-600">Discard this Site's rebuildable Finding interpretation history while preserving collected website evidence.</p>
      <FindingDestructiveAction
        label="Reset Findings..."
        title="Reset Findings for this Site?"
        description="This permanently deletes all Finding evaluations, Findings, assessment history, acknowledgements, and Finding evidence references for this Site. Collected website evidence is not deleted. You can run the current Finding evaluator again afterward to rebuild Findings from retained evidence."
        confirmationPhrase="RESET"
        onConfirm={() => resetSiteFindings(site.id)}
        onSuccess={async () => {
          await invalidateFindingQueries(queryClient, site.id);
          setParams({});
        }}
      />
    </section>
  </div>;
}

function CurrentFindings({ site }: { site: Site }) {
  const [params, setParams] = useSearchParams();
  const pagination = useUrlPagination({ prefix: "findings", defaultLimit: 50 });
  const search = params.get("search") ?? "";
  const state = params.get("state") ?? "";
  const type = params.get("type") ?? "";
  const severity = params.get("severity") ?? "";
  const acknowledged = params.get("acknowledged") ?? "";
  const queryString = new URLSearchParams({ limit: String(pagination.limit), offset: String(pagination.offset) });
  if (search) queryString.set("search", search);
  if (state) queryString.set("condition_state", state);
  if (type) queryString.set("finding_type", type);
  if (severity) queryString.set("severity", severity);
  if (acknowledged) queryString.set("acknowledged", acknowledged);
  const query = useQuery({ queryKey: ["findings", String(site.id), queryString.toString()], queryFn: () => listFindings(site.id, queryString.toString()), placeholderData: (old) => old });
  const submit = (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); const value = new FormData(event.currentTarget).get("search")?.toString().trim() ?? ""; const next = new URLSearchParams(params); if (value) next.set("search", value); else next.delete("search"); next.delete("findings_page"); setParams(next); };
  const setFilter = (name: string, value: string) => { const next = new URLSearchParams(params); if (value) next.set(name, value); else next.delete(name); next.delete("findings_page"); setParams(next); };
  if (query.isLoading) return <LoadingBlock label="Loading Findings..." />;
  if (query.error) return <ErrorBanner error={query.error} title="Could not load Findings" />;
  const data = query.data!;
  const controls = <PaginatedTableControls total={data.total} limit={data.limit} offset={data.offset} itemLabel="finding" isLoading={query.isFetching} onPageChange={pagination.setPage} onPageSizeChange={pagination.setPageSize} />;
  return <div className="space-y-4">
    <form className="flex flex-wrap gap-2" onSubmit={submit}><label className="relative min-w-64 flex-1"><Search className="absolute left-3 top-2.5 size-4 text-stone-400"/><span className="sr-only">Search Page URL</span><input name="search" defaultValue={search} placeholder="Search Page URL" className="w-full rounded-md border border-stone-300 py-2 pl-9 pr-3 text-sm" /></label><select aria-label="Finding type" value={type} onChange={(event) => setFilter("type", event.target.value)} className="rounded-md border border-stone-300 bg-white px-3 py-2 text-sm"><option value="">All finding types</option>{Object.entries(detectorLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><select aria-label="Condition state" value={state} onChange={(event) => setFilter("state", event.target.value)} className="rounded-md border border-stone-300 bg-white px-3 py-2 text-sm"><option value="">All states</option><option value="detected">Detected</option><option value="unknown">Unknown</option><option value="resolved">Resolved</option></select><select aria-label="Severity" value={severity} onChange={(event) => setFilter("severity", event.target.value)} className="rounded-md border border-stone-300 bg-white px-3 py-2 text-sm"><option value="">All severities</option><option value="medium">Medium</option><option value="high">High</option></select><select aria-label="Workflow acknowledgement" value={acknowledged} onChange={(event) => setFilter("acknowledged", event.target.value)} className="rounded-md border border-stone-300 bg-white px-3 py-2 text-sm"><option value="">All workflow states</option><option value="false">Open</option><option value="true">Acknowledged</option></select><Button type="submit">Apply</Button></form>
    {data.items.length ? <>{controls}<div className="overflow-x-auto rounded-md border border-stone-200 bg-white"><table className="min-w-full text-left text-sm"><thead className="bg-stone-100 text-xs uppercase text-stone-500"><tr><th className="px-3 py-2">Page</th><th className="px-3 py-2">Finding</th><th className="px-3 py-2">State</th><th className="px-3 py-2">Severity</th><th className="px-3 py-2">First detected</th><th className="px-3 py-2">Last evidence</th><th className="px-3 py-2">Workflow</th></tr></thead><tbody>{data.items.map((finding) => <tr key={finding.id} className="border-t border-stone-100"><td className="max-w-md px-3 py-2"><Link className="block truncate font-medium underline" to={`/sites/${site.id}/findings/${finding.id}`}>{finding.page_url}</Link></td><td className="px-3 py-2"><FindingLabel finding={finding}/></td><td className="px-3 py-2"><StatusBadge status={finding.condition_state}/></td><td className="px-3 py-2"><StatusBadge status={finding.current_severity ?? "none"}/></td><td className="whitespace-nowrap px-3 py-2">{formatDate(finding.first_detected_at, { timeZone: site.display_timezone })}</td><td className="whitespace-nowrap px-3 py-2">{formatDate(finding.last_evaluated_evidence_at, { timeZone: site.display_timezone })}</td><td className="px-3 py-2">{finding.acknowledged_at ? "Acknowledged" : "Open"}</td></tr>)}</tbody></table></div>{controls}</> : <EmptyState title="No current Findings" message="No operational conditions match the current filters." />}
  </div>;
}

function EvaluationHistory({ site }: { site: Site }) {
  const pagination = useUrlPagination({ prefix: "finding_evaluations", defaultLimit: 25 });
  const query = useQuery({ queryKey: ["finding-evaluations", String(site.id), pagination.limit, pagination.offset], queryFn: () => listFindingEvaluations(site.id, `limit=${pagination.limit}&offset=${pagination.offset}`), refetchInterval: (state) => state.state.data?.items.some((item) => item.status === "queued" || item.status === "running") ? 1500 : false });
  if (query.isLoading) return <LoadingBlock label="Loading Finding evaluations..."/>;
  if (query.error) return <ErrorBanner error={query.error} title="Could not load Finding evaluations"/>;
  const data = query.data!;
  if (!data.items.length) return <EmptyState title="No evaluations" message="Run an evaluation after a terminal Scan is available."/>;
  return <div className="space-y-4"><PaginatedTableControls total={data.total} limit={data.limit} offset={data.offset} itemLabel="evaluation" onPageChange={pagination.setPage} onPageSizeChange={pagination.setPageSize}/><div className="overflow-x-auto rounded-md border border-stone-200 bg-white"><table className="min-w-full text-left text-sm"><thead className="bg-stone-100 text-xs uppercase text-stone-500"><tr><th className="px-3 py-2">Evaluation</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Bundle</th><th className="px-3 py-2">Evidence selection</th><th className="px-3 py-2">Evidence horizon</th><th className="px-3 py-2">Active Pages</th><th className="px-3 py-2">Detector outcomes</th><th className="px-3 py-2">Transitions</th></tr></thead><tbody>{data.items.map((item) => <tr key={item.id} className="border-t border-stone-100 align-top"><td className="px-3 py-2 font-medium">#{item.id}</td><td className="px-3 py-2"><StatusBadge status={item.status}/></td><td className="whitespace-nowrap px-3 py-2 font-mono text-xs">{item.detector_bundle_identity}</td><td className="whitespace-nowrap px-3 py-2 text-xs"><EvidenceManifestSummary evaluation={item}/></td><td className="px-3 py-2">{formatDate(item.evidence_horizon_at, { timeZone: site.display_timezone })}</td><td className="px-3 py-2">{item.active_page_count}</td><td className="min-w-96 px-3 py-2"><DetectorSummary evaluation={item}/></td><td className="px-3 py-2">{item.created_finding_count} new, {item.resolved_finding_count} resolved, {item.reopened_finding_count} reopened</td></tr>)}</tbody></table></div><p className="text-xs text-stone-500">Detector counts cover every active Page, including clear and unknown outcomes that are intentionally not persisted as Findings.</p></div>;
}

const detectorLabels: Record<string, string> = {
  page_http_error: "HTTP errors",
  page_static_fetch_failure: "Static fetch failures",
  page_noindex: "Noindex",
  page_indexability_conflict: "Indexability conflicts",
  page_missing_title: "Missing titles",
  page_invalid_canonical: "Invalid canonicals",
  page_multiple_canonicals: "Multiple canonicals",
  page_canonical_target_http_error: "Canonical target errors",
  page_non_html_representation: "Non-HTML representations",
  page_broken_internal_links: "Broken internal links",
  page_internal_links_to_redirects: "Internal links to redirects",
  sitemap_page_http_error: "Sitemap Page HTTP error",
  sitemap_page_noindex: "Sitemap Page is noindex",
  sitemap_page_redirect: "Sitemap Page redirects",
};

function FindingLabel({ finding }: { finding: Finding }) {
  const summary = findingListSummary(finding.finding_type, finding.current_evidence_summary);
  return <><span>{finding.finding_label || formatStatus(finding.finding_type)}</span>{summary ? <p className="mt-0.5 text-xs text-stone-500">{summary}</p> : null}</>;
}

function findingListSummary(findingType: string, details: Record<string, unknown>) {
  if (findingType === "page_broken_internal_links") return `${String(details.broken_target_count ?? 0)} broken targets`;
  if (findingType === "page_internal_links_to_redirects") return `${String(details.redirect_target_count ?? 0)} redirect targets`;
  if (findingType === "sitemap_page_http_error") return `HTTP ${String(details.http_status ?? "unknown")} · declared in ${sitemapSourceLabel(details)}`;
  if (findingType === "sitemap_page_noindex") return `noindex · declared in ${sitemapSourceLabel(details)}`;
  if (findingType === "sitemap_page_redirect") return `redirects to ${String(details.normalized_final_url ?? details.final_url ?? "unknown")} · declared in ${sitemapSourceLabel(details)}`;
  return null;
}

function sitemapSourceLabel(details: Record<string, unknown>) {
  const count = Number(details.sitemap_source_count ?? 0);
  return count === 1 ? "1 sitemap Source" : `${count} sitemap Sources`;
}

function EvidenceManifestSummary({ evaluation }: { evaluation: FindingEvaluation }) {
  const roots = evaluation.evidence_manifest_json?.sitemap_roots;
  if (!roots) return <span className="text-stone-500">Scan #{evaluation.source_scan_id ?? "not retained"}</span>;
  const usable = roots.reduce((count, item) => count + countUsableSitemapLeaves(item.refresh_tree), 0);
  return <span>Scan #{evaluation.source_scan_id ?? "not retained"} · {roots.length} sitemap roots · {usable} usable refreshes</span>;
}

function countUsableSitemapLeaves(node: FindingSitemapRefreshNode | null): number {
  if (!node) return 0;
  if (node.sitemap_document_type === "urlset") {
    return node.membership_materialized && ["completed", "completed_with_errors"].includes(node.status) ? 1 : 0;
  }
  return node.children.reduce((count, child) => count + countUsableSitemapLeaves(child), 0);
}

function DetectorSummary({ evaluation }: { evaluation: FindingEvaluation }) {
  const entries = Object.entries(evaluation.detector_summary_json ?? {});
  if (!entries.length) return <span className="text-stone-500">Not available for this historical evaluation</span>;
  return <div className="space-y-1.5">{entries.map(([type, summary]) => <div key={type}><p><span className="font-medium">{detectorLabels[type] ?? formatStatus(type)}</span> <span className="text-stone-600">{summary.detected} detected · {summary.clear} clear · {summary.unknown} unknown</span></p>{summary.unknown > 0 && Object.keys(summary.reason_counts).length ? <details className="text-xs text-stone-500"><summary className="cursor-pointer">Unknown reasons</summary><ul className="mt-1 space-y-0.5 pl-3">{Object.entries(summary.reason_counts).map(([reason, count]) => <li key={reason}>{formatStatus(reason)}: {count}</li>)}</ul></details> : null}</div>)}</div>;
}

export function SiteFindingDetailPage({ site }: { site: Site }) {
  const { findingId = "" } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ["finding", String(site.id), findingId], queryFn: () => getFinding(site.id, findingId) });
  const workflow = useMutation({ mutationFn: (acknowledged: boolean) => setFindingAcknowledged(site.id, findingId, acknowledged), onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: ["finding"] }); await queryClient.invalidateQueries({ queryKey: ["findings"] }); await invalidateSiteIntelligence(queryClient, site.id); } });
  if (query.isLoading) return <LoadingBlock label="Loading Finding history..."/>;
  if (query.error) return <ErrorBanner error={query.error} title="Could not load Finding"/>;
  const finding = query.data!;
  return <div className="space-y-6"><div><Link to={`/sites/${site.id}/findings`} className="text-sm underline">Findings</Link><p className="mt-2 text-sm font-medium text-stone-600">{finding.finding_label || formatStatus(finding.finding_type)}</p><h2 className="mt-1 break-all text-lg font-semibold">{finding.page_url}</h2><div className="mt-2 flex flex-wrap gap-2"><StatusBadge status={finding.condition_state}/><StatusBadge status={finding.current_severity ?? "none"}/><StatusBadge status={finding.acknowledged_at ? "acknowledged" : "unacknowledged"}/></div></div><div className="flex flex-wrap gap-2">{finding.acknowledged_at ? <Button loading={workflow.isPending} onClick={() => workflow.mutate(false)}><Undo2 className="mr-2 size-4"/>Unacknowledge</Button> : <Button loading={workflow.isPending} onClick={() => workflow.mutate(true)}><Check className="mr-2 size-4"/>Acknowledge</Button>}<Link className="inline-flex min-h-9 items-center rounded-md border border-stone-300 bg-white px-3 py-2 text-sm font-medium" to={`/sites/${site.id}/pages/${finding.web_resource_id}`}>Open Page</Link></div><section><h3 className="text-base font-semibold">Assessment history</h3><div className="mt-3 divide-y divide-stone-200 rounded-md border border-stone-200 bg-white">{finding.assessments.map((assessment) => <article key={assessment.id} className="p-4"><div className="flex flex-wrap items-center justify-between gap-2"><div className="flex gap-2"><StatusBadge status={assessment.outcome}/>{assessment.severity ? <StatusBadge status={assessment.severity}/> : null}</div><time className="text-xs text-stone-500">{formatDate(assessment.evidence_observed_at, { timeZone: site.display_timezone, showTimeZone: true })}</time></div><p className="mt-2 text-sm">{assessmentSummary(finding.finding_type, assessment)}</p><SitemapMembershipSamples findingType={finding.finding_type} assessment={assessment}/><TopologyTargetSamples findingType={finding.finding_type} assessment={assessment}/><p className="mt-1 text-xs text-stone-500">{formatStatus(String(assessment.details_json.transition ?? assessment.outcome))}</p><p className="mt-1 font-mono text-xs text-stone-500">{assessment.evaluation.evaluator_version} / {assessment.evaluation.detector_bundle_identity} / evaluation {assessment.finding_evaluation_id}</p><ul className="mt-3 space-y-1 text-sm">{assessment.evidence_references.map((reference) => <li key={reference.id}>{reference.retained && reference.href ? <Link className="underline" to={reference.href}>{formatStatus(reference.role)}: {formatStatus(reference.evidence_kind)} {reference.evidence_id}</Link> : <span>{formatStatus(reference.role)}: {formatStatus(reference.evidence_kind)} {reference.evidence_id} (no longer retained)</span>}<time className="ml-2 text-xs text-stone-500">{formatDate(reference.evidence_observed_at, { timeZone: site.display_timezone, showTimeZone: true })}</time></li>)}</ul></article>)}</div></section><section className="border-t border-stone-200 pt-4 text-xs text-stone-500"><p>Logical identity: {finding.finding_type} / {finding.logical_key_version}</p><p className="mt-1 break-all font-mono">{finding.fingerprint_sha256}</p></section><section className="border-t border-red-200 pt-4"><FindingDestructiveAction label="Delete Finding..." title="Delete this Finding?" description="This permanently deletes this Finding's lifecycle and assessment history, including its acknowledgement. Collected website evidence is preserved. The completed evaluation that produced this Finding is not reset, so deleting one Finding does not make that same evaluation run again." onConfirm={() => deleteFinding(site.id, findingId)} onSuccess={async () => { await invalidateFindingQueries(queryClient, site.id); navigate(`/sites/${site.id}/findings`); }}/></section></div>;
}

async function invalidateFindingQueries(queryClient: ReturnType<typeof useQueryClient>, siteId: string | number) {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: ["finding"] }),
    queryClient.invalidateQueries({ queryKey: ["findings", String(siteId)] }),
    queryClient.invalidateQueries({ queryKey: ["finding-evaluations", String(siteId)] }),
    queryClient.invalidateQueries({ queryKey: ["jobs"] }),
    invalidateSiteIntelligence(queryClient, siteId),
  ]);
}

function FindingDestructiveAction({ label, title, description, confirmationPhrase, onConfirm, onSuccess }: { label: string; title: string; description: string; confirmationPhrase?: string; onConfirm: () => Promise<unknown>; onSuccess: () => void | Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [confirmation, setConfirmation] = useState("");
  const titleId = useId();
  const descriptionId = useId();
  const dialogRef = useRef<HTMLElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const mutation = useMutation({ mutationFn: onConfirm, onSuccess: async () => { await onSuccess(); setOpen(false); setConfirmation(""); } });
  useEffect(() => {
    if (!open) return;
    const dialog = dialogRef.current;
    const trigger = triggerRef.current;
    const focusable = () => Array.from(dialog?.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), [href], [tabindex]:not([tabindex="-1"])') ?? []);
    focusable()[0]?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !mutation.isPending) {
        event.preventDefault();
        setOpen(false);
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
      trigger?.focus();
    };
  }, [open, mutation.isPending]);
  const confirmed = !confirmationPhrase || confirmation === confirmationPhrase;
  return <><Button ref={triggerRef} type="button" variant="danger" className="mt-3" onClick={() => setOpen(true)}><Trash2 className="mr-2 size-4"/>{label}</Button>{open ? <section ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={titleId} aria-describedby={descriptionId} className="fixed inset-0 z-50 overflow-y-auto bg-black/40 p-3 sm:p-8"><div className="mx-auto max-w-xl rounded-md bg-white p-4 shadow-xl sm:p-6"><header className="flex items-start justify-between gap-3"><div><h2 id={titleId} className="flex items-center gap-2 text-lg font-semibold text-red-800"><AlertTriangle className="size-5"/>{title}</h2><p id={descriptionId} className="mt-2 text-sm text-stone-600">{description}</p></div><button type="button" aria-label="Close dialog" disabled={mutation.isPending} onClick={() => setOpen(false)} className="rounded p-2 hover:bg-stone-100 disabled:opacity-60"><X className="size-5"/></button></header>{confirmationPhrase ? <label className="mt-5 block text-sm font-medium">Type <code>{confirmationPhrase}</code> to confirm<input aria-label={`Type ${confirmationPhrase} to confirm`} value={confirmation} autoComplete="off" onChange={(event) => setConfirmation(event.target.value)} className="mt-2 w-full rounded-md border border-stone-300 px-3 py-2 font-mono"/></label> : null}{mutation.error ? <div className="mt-4"><ErrorBanner error={mutation.error} title="Could not complete Finding deletion"/></div> : null}<div className="mt-5 flex justify-end gap-2"><Button type="button" disabled={mutation.isPending} onClick={() => setOpen(false)}>Cancel</Button><Button type="button" variant="danger" loading={mutation.isPending} disabled={!confirmed} onClick={() => mutation.mutate()}>Delete permanently</Button></div></div></section> : null}</>;
}

function TopologyTargetSamples({ findingType, assessment }: { findingType: string; assessment: FindingAssessment }) {
  if (!["page_broken_internal_links", "page_internal_links_to_redirects"].includes(findingType)) return null;
  const samples = Array.isArray(assessment.details_json.target_samples) ? assessment.details_json.target_samples : [];
  return <>{samples.length ? <ul className="mt-2 space-y-1 text-sm">{samples.map((value, index) => {
    const sample = value && typeof value === "object" ? value as Record<string, unknown> : {};
    const requested = String(sample.requested_url ?? "Unknown target");
    const result = findingType === "page_broken_internal_links" ? `HTTP ${String(sample.http_status ?? "unknown")}` : String(sample.final_url ?? "Unknown final URL");
    return <li key={`${requested}-${index}`} className="break-all font-mono text-xs">{requested} -&gt; {result}</li>;
  })}</ul> : null}{assessment.details_json.evidence_truncated ? <p className="mt-2 text-xs text-stone-500">Evidence sample limited to {String(assessment.details_json.evidence_sample_count)} occurrences.</p> : null}</>;
}

function SitemapMembershipSamples({ findingType, assessment, timeZone }: { findingType: string; assessment: FindingAssessment; timeZone?: string | null }) {
  if (!findingType.startsWith("sitemap_page_")) return null;
  const samples = Array.isArray(assessment.details_json.sitemap_membership_samples) ? assessment.details_json.sitemap_membership_samples : [];
  return <>{samples.length ? <ul className="mt-2 space-y-1 text-xs text-stone-600">{samples.map((value, index) => {
    const sample = value && typeof value === "object" ? value as Record<string, unknown> : {};
    return <li key={`${String(sample.source_entry_observation_id)}-${index}`}><span className="break-all font-mono">{String(sample.raw_url ?? sample.normalized_url ?? "Unknown sitemap URL")}</span> · Source #{String(sample.url_source_id)} · refresh #{String(sample.source_refresh_id)} · {formatDate(String(sample.source_refresh_finished_at), { timeZone, showTimeZone: true })}</li>;
  })}</ul> : null}{assessment.details_json.membership_evidence_truncated ? <p className="mt-2 text-xs text-stone-500">Membership evidence sample limited to {String(assessment.details_json.membership_sample_count)} declarations.</p> : null}</>;
}

function assessmentSummary(findingType: string, assessment: FindingAssessment) {
  const details = assessment.details_json;
  if (findingType === "page_http_error") return details.http_status ? `HTTP ${details.http_status}` : "HTTP status unavailable";
  if (findingType === "page_noindex") {
    const sources = Array.isArray(details.matched_sources) ? details.matched_sources.map((source) => formatStatus(String(source))).join(" and ") : "";
    if (sources) return `noindex via ${sources}`;
    return assessment.outcome === "unknown" ? "Indexability could not be determined" : "No applicable noindex directive";
  }
  if (findingType === "page_indexability_conflict") {
    const meta = typeof details.meta_robots_raw === "string" ? details.meta_robots_raw : "not present";
    const headers = Array.isArray(details.x_robots_tag_raw) ? details.x_robots_tag_raw.join(", ") : "not present";
    return `Meta robots: ${meta}; X-Robots-Tag: ${headers}`;
  }
  if (findingType === "page_canonical_target_http_error") {
    const canonical = typeof details.canonical_url === "string" ? details.canonical_url : "unavailable";
    const status = details.target_http_status ? `; target HTTP ${details.target_http_status}` : "";
    return `Canonical -> ${canonical}${status}`;
  }
  if (findingType === "page_static_fetch_failure") return `${formatStatus(String(details.error_type ?? "unknown failure"))}${details.error_message ? `: ${details.error_message}` : ""}`;
  if (findingType === "page_missing_title") return assessment.outcome === "detected" ? "No non-empty HTML title was observed" : "Observed HTML title is present";
  if (findingType === "page_invalid_canonical") return `Canonical: ${String(details.canonical_url ?? "unavailable")}${details.resolution_error ? `; ${details.resolution_error}` : ""}`;
  if (findingType === "page_multiple_canonicals") return `${String(details.canonical_count ?? "Unknown")} canonical declarations`;
  if (findingType === "page_non_html_representation") return `${formatStatus(String(details.representation_kind ?? "unknown"))} (${String(details.normalized_mime_type ?? details.content_type ?? "content type unavailable")})`;
  if (findingType === "page_broken_internal_links") {
    const targets = Number(details.broken_target_count ?? 0);
    return `${String(details.broken_occurrence_count ?? 0)} broken internal link occurrences across ${targets} target Page${targets === 1 ? "" : "s"}`;
  }
  if (findingType === "page_internal_links_to_redirects") {
    const targets = Number(details.redirect_target_count ?? 0);
    return `${String(details.redirect_occurrence_count ?? 0)} internal link occurrences point to ${targets} redirecting Page${targets === 1 ? "" : "s"}`;
  }
  if (findingType === "sitemap_page_http_error") return `HTTP ${String(details.http_status ?? "unknown")} · declared in ${sitemapSourceLabel(details)}`;
  if (findingType === "sitemap_page_noindex") {
    const sources = Array.isArray(details.matched_sources) ? details.matched_sources.map((source) => formatStatus(String(source))).join(" and ") : "";
    return `${sources ? `noindex via ${sources}` : "Indexability unavailable"} · declared in ${sitemapSourceLabel(details)}`;
  }
  if (findingType === "sitemap_page_redirect") return `${String(details.requested_url ?? "Sitemap Page")} redirects to ${String(details.normalized_final_url ?? details.final_url ?? "unknown")} · declared in ${sitemapSourceLabel(details)}`;
  return formatStatus(String(details.transition ?? assessment.outcome));
}
