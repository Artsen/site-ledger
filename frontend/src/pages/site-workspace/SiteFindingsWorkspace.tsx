import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Play, Search, Undo2 } from "lucide-react";
import { FormEvent } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { createFindingEvaluation, getFinding, listFindingEvaluations, listFindings, setFindingAcknowledged } from "../../api/findings";
import { invalidateSiteIntelligence } from "../../api/queryKeys";
import { Button } from "../../components/ui/Button";
import { EmptyState } from "../../components/ui/EmptyState";
import { ErrorBanner } from "../../components/ui/ErrorBanner";
import { LoadingBlock } from "../../components/ui/Loading";
import { PaginatedTableControls } from "../../components/ui/PaginatedTableControls";
import { StatusBadge } from "../../components/ui/StatusBadge";
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
  </div>;
}

function CurrentFindings({ site }: { site: Site }) {
  const [params, setParams] = useSearchParams();
  const pagination = useUrlPagination({ prefix: "findings", defaultLimit: 50 });
  const search = params.get("search") ?? "";
  const state = params.get("state") ?? "";
  const queryString = new URLSearchParams({ limit: String(pagination.limit), offset: String(pagination.offset) });
  if (search) queryString.set("search", search);
  if (state) queryString.set("condition_state", state);
  const query = useQuery({ queryKey: ["findings", String(site.id), queryString.toString()], queryFn: () => listFindings(site.id, queryString.toString()), placeholderData: (old) => old });
  const submit = (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); const value = new FormData(event.currentTarget).get("search")?.toString().trim() ?? ""; const next = new URLSearchParams(params); if (value) next.set("search", value); else next.delete("search"); next.delete("findings_page"); setParams(next); };
  if (query.isLoading) return <LoadingBlock label="Loading Findings..." />;
  if (query.error) return <ErrorBanner error={query.error} title="Could not load Findings" />;
  const data = query.data!;
  const controls = <PaginatedTableControls total={data.total} limit={data.limit} offset={data.offset} itemLabel="finding" isLoading={query.isFetching} onPageChange={pagination.setPage} onPageSizeChange={pagination.setPageSize} />;
  return <div className="space-y-4">
    <form className="flex flex-wrap gap-2" onSubmit={submit}><label className="relative min-w-64 flex-1"><Search className="absolute left-3 top-2.5 size-4 text-stone-400"/><span className="sr-only">Search Page URL</span><input name="search" defaultValue={search} placeholder="Search Page URL" className="w-full rounded-md border border-stone-300 py-2 pl-9 pr-3 text-sm" /></label><select aria-label="Condition state" value={state} onChange={(event) => { const next = new URLSearchParams(params); if (event.target.value) next.set("state", event.target.value); else next.delete("state"); setParams(next); }} className="rounded-md border border-stone-300 bg-white px-3 py-2 text-sm"><option value="">All states</option><option value="detected">Detected</option><option value="unknown">Unknown</option><option value="resolved">Resolved</option></select><Button type="submit">Apply</Button></form>
    {data.items.length ? <>{controls}<div className="overflow-x-auto rounded-md border border-stone-200 bg-white"><table className="min-w-full text-left text-sm"><thead className="bg-stone-100 text-xs uppercase text-stone-500"><tr><th className="px-3 py-2">Page</th><th className="px-3 py-2">Finding</th><th className="px-3 py-2">State</th><th className="px-3 py-2">Severity</th><th className="px-3 py-2">First detected</th><th className="px-3 py-2">Last evidence</th><th className="px-3 py-2">Workflow</th></tr></thead><tbody>{data.items.map((finding) => <tr key={finding.id} className="border-t border-stone-100"><td className="max-w-md px-3 py-2"><Link className="block truncate font-medium underline" to={`/sites/${site.id}/findings/${finding.id}`}>{finding.page_url}</Link></td><td className="px-3 py-2">Page HTTP error</td><td className="px-3 py-2"><StatusBadge status={finding.condition_state}/></td><td className="px-3 py-2"><StatusBadge status={finding.current_severity ?? "none"}/></td><td className="whitespace-nowrap px-3 py-2">{formatDate(finding.first_detected_at, { timeZone: site.display_timezone })}</td><td className="whitespace-nowrap px-3 py-2">{formatDate(finding.last_evaluated_evidence_at, { timeZone: site.display_timezone })}</td><td className="px-3 py-2">{finding.acknowledged_at ? "Acknowledged" : "Open"}</td></tr>)}</tbody></table></div>{controls}</> : <EmptyState title="No current Findings" message="No operational conditions match the current filters." />}
  </div>;
}

function EvaluationHistory({ site }: { site: Site }) {
  const pagination = useUrlPagination({ prefix: "finding_evaluations", defaultLimit: 25 });
  const query = useQuery({ queryKey: ["finding-evaluations", String(site.id), pagination.limit, pagination.offset], queryFn: () => listFindingEvaluations(site.id, `limit=${pagination.limit}&offset=${pagination.offset}`), refetchInterval: (state) => state.state.data?.items.some((item) => item.status === "queued" || item.status === "running") ? 1500 : false });
  if (query.isLoading) return <LoadingBlock label="Loading Finding evaluations..."/>;
  if (query.error) return <ErrorBanner error={query.error} title="Could not load Finding evaluations"/>;
  const data = query.data!;
  if (!data.items.length) return <EmptyState title="No evaluations" message="Run an evaluation after a terminal Scan is available."/>;
  return <div className="space-y-4"><PaginatedTableControls total={data.total} limit={data.limit} offset={data.offset} itemLabel="evaluation" onPageChange={pagination.setPage} onPageSizeChange={pagination.setPageSize}/><div className="overflow-x-auto rounded-md border border-stone-200 bg-white"><table className="min-w-full text-left text-sm"><thead className="bg-stone-100 text-xs uppercase text-stone-500"><tr><th className="px-3 py-2">Evaluation</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Evidence horizon</th><th className="px-3 py-2">Pages</th><th className="px-3 py-2">Detected</th><th className="px-3 py-2">Unknown</th><th className="px-3 py-2">Transitions</th></tr></thead><tbody>{data.items.map((item) => <tr key={item.id} className="border-t border-stone-100"><td className="px-3 py-2 font-medium">#{item.id}</td><td className="px-3 py-2"><StatusBadge status={item.status}/></td><td className="px-3 py-2">{formatDate(item.evidence_horizon_at, { timeZone: site.display_timezone })}</td><td className="px-3 py-2">{item.active_page_count}</td><td className="px-3 py-2">{item.detected_count}</td><td className="px-3 py-2">{item.unknown_count}</td><td className="px-3 py-2">{item.created_finding_count} new, {item.resolved_finding_count} resolved, {item.reopened_finding_count} reopened</td></tr>)}</tbody></table></div></div>;
}

export function SiteFindingDetailPage({ site }: { site: Site }) {
  const { findingId = "" } = useParams();
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ["finding", String(site.id), findingId], queryFn: () => getFinding(site.id, findingId) });
  const workflow = useMutation({ mutationFn: (acknowledged: boolean) => setFindingAcknowledged(site.id, findingId, acknowledged), onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: ["finding"] }); await queryClient.invalidateQueries({ queryKey: ["findings"] }); await invalidateSiteIntelligence(queryClient, site.id); } });
  if (query.isLoading) return <LoadingBlock label="Loading Finding history..."/>;
  if (query.error) return <ErrorBanner error={query.error} title="Could not load Finding"/>;
  const finding = query.data!;
  return <div className="space-y-6"><div><Link to={`/sites/${site.id}/findings`} className="text-sm underline">Findings</Link><h2 className="mt-2 break-all text-lg font-semibold">{finding.page_url}</h2><div className="mt-2 flex flex-wrap gap-2"><StatusBadge status={finding.condition_state}/><StatusBadge status={finding.current_severity ?? "none"}/><StatusBadge status={finding.acknowledged_at ? "acknowledged" : "unacknowledged"}/></div></div><div className="flex gap-2">{finding.acknowledged_at ? <Button loading={workflow.isPending} onClick={() => workflow.mutate(false)}><Undo2 className="mr-2 size-4"/>Unacknowledge</Button> : <Button loading={workflow.isPending} onClick={() => workflow.mutate(true)}><Check className="mr-2 size-4"/>Acknowledge</Button>}<Link className="inline-flex min-h-9 items-center rounded-md border border-stone-300 bg-white px-3 py-2 text-sm font-medium" to={`/sites/${site.id}/pages/${finding.web_resource_id}`}>Open Page</Link></div><section><h3 className="text-base font-semibold">Assessment history</h3><div className="mt-3 divide-y divide-stone-200 rounded-md border border-stone-200 bg-white">{finding.assessments.map((assessment) => <article key={assessment.id} className="p-4"><div className="flex flex-wrap items-center justify-between gap-2"><div className="flex gap-2"><StatusBadge status={assessment.outcome}/>{assessment.severity ? <StatusBadge status={assessment.severity}/> : null}</div><time className="text-xs text-stone-500">{formatDate(assessment.evidence_observed_at, { timeZone: site.display_timezone, showTimeZone: true })}</time></div><p className="mt-2 text-sm">{formatStatus(String(assessment.details_json.transition ?? assessment.outcome))}{assessment.details_json.http_status ? `, HTTP ${assessment.details_json.http_status}` : ""}</p><p className="mt-1 font-mono text-xs text-stone-500">{assessment.evaluation.evaluator_version} / {assessment.evaluation.detector_bundle_identity} / evaluation {assessment.finding_evaluation_id}</p><ul className="mt-3 space-y-1 text-sm">{assessment.evidence_references.map((reference) => <li key={reference.id}>{reference.retained && reference.href ? <Link className="underline" to={reference.href}>{formatStatus(reference.evidence_kind)} {reference.evidence_id}</Link> : <span>{formatStatus(reference.evidence_kind)} {reference.evidence_id} (no longer retained)</span>}</li>)}</ul></article>)}</div></section><section className="border-t border-stone-200 pt-4 text-xs text-stone-500"><p>Logical identity: {finding.finding_type} / {finding.logical_key_version}</p><p className="mt-1 break-all font-mono">{finding.fingerprint_sha256}</p></section></div>;
}
