import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, ExternalLink } from "lucide-react";
import { Link, useParams } from "react-router-dom";

import { cancelCollectionPlan, getCollectionPlan, listCollectionPlans } from "../../api/collectionPlans";
import { invalidateSiteIntelligence } from "../../api/queryKeys";
import { Button } from "../../components/ui/Button";
import { EmptyState } from "../../components/ui/EmptyState";
import { ErrorBanner } from "../../components/ui/ErrorBanner";
import { LoadingBlock } from "../../components/ui/Loading";
import { StatusBadge } from "../../components/ui/StatusBadge";
import type { Site } from "../../types/scans";
import { formatDate, formatStatus } from "../../utils/format";

const ACTIVE = new Set(["queued", "running", "cancelling"]);

function contextLabel(context: Record<string, string>) {
  if (context.provider) return `${formatStatus(context.provider)} / ${formatStatus(context.dimension)}`;
  if (context.profile) return formatStatus(context.profile);
  if (context.profile_version) return "Current render profile";
  return "Current structured-content extractor";
}

export function CollectionPlansWorkspace({ site }: { site: Site }) {
  const { planId } = useParams();
  return planId ? <PlanDetail site={site} planId={planId} /> : <PlanList site={site} />;
}

function PlanList({ site }: { site: Site }) {
  const query = useQuery({
    queryKey: ["collection-plans", String(site.id)],
    queryFn: () => listCollectionPlans(site.id, "?limit=100"),
    refetchInterval: (state) => state.state.data?.items.some((item) => ACTIVE.has(item.status)) ? 2000 : false,
  });
  if (query.isLoading) return <LoadingBlock label="Loading Collection Plans..." />;
  if (query.error) return <ErrorBanner error={query.error} title="Could not load Collection Plans" />;
  if (!query.data?.items.length) return <EmptyState title="No Collection Plans" message="Use an Evidence Coverage action on Overview to collect missing current evidence." />;
  return (
    <div className="space-y-4">
      <header><h2 className="text-base font-semibold">Collection Plans</h2><p className="mt-1 text-sm text-stone-600">Frozen missing-current target selections and their native collection batches.</p></header>
      <div className="overflow-x-auto rounded-md border border-stone-200 bg-white">
        <table className="min-w-full text-left text-sm"><thead className="bg-stone-100 text-xs uppercase text-stone-500"><tr><th className="px-3 py-2">Plan</th><th className="px-3 py-2">Evidence</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Progress</th><th className="px-3 py-2">Created</th></tr></thead><tbody>{query.data.items.map((plan) => <tr key={plan.id} className="border-t border-stone-100"><td className="px-3 py-2"><Link className="font-medium underline" to={`/sites/${site.id}/collection-plans/${plan.id}`}>Plan {plan.id}</Link></td><td className="px-3 py-2"><span className="block font-medium">{formatStatus(plan.evidence_domain)}</span><span className="text-xs text-stone-500">{contextLabel(plan.context)}</span></td><td className="px-3 py-2"><StatusBadge status={plan.status} /></td><td className="px-3 py-2 tabular-nums">{plan.progress.processed_target_count.toLocaleString()} / {plan.target_count.toLocaleString()}</td><td className="whitespace-nowrap px-3 py-2">{formatDate(plan.created_at, { timeZone: site.display_timezone, showTimeZone: true })}</td></tr>)}</tbody></table>
      </div>
    </div>
  );
}

function PlanDetail({ site, planId }: { site: Site; planId: string }) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["collection-plan", String(site.id), planId],
    queryFn: () => getCollectionPlan(site.id, planId),
    refetchInterval: (state) => ACTIVE.has(state.state.data?.status ?? "") ? 2000 : false,
  });
  const cancel = useMutation({
    mutationFn: () => cancelCollectionPlan(site.id, planId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["collection-plan", String(site.id), planId] });
      await queryClient.invalidateQueries({ queryKey: ["collection-plans", String(site.id)] });
      await invalidateSiteIntelligence(queryClient, site.id);
    },
  });
  if (query.isLoading) return <LoadingBlock label="Loading Collection Plan..." />;
  if (query.error) return <ErrorBanner error={query.error} title="Could not load Collection Plan" />;
  const plan = query.data;
  if (!plan) return null;
  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-start justify-between gap-3"><div><Link className="text-sm underline" to={`/sites/${site.id}/collection-plans`}>Collection Plans</Link><h2 className="mt-1 text-xl font-semibold">Plan {plan.id}</h2><p className="mt-1 text-sm text-stone-600">{formatStatus(plan.evidence_domain)} / {contextLabel(plan.context)}</p></div>{ACTIVE.has(plan.status) ? <Button variant="danger" loading={cancel.isPending} onClick={() => cancel.mutate()}><Ban className="mr-2 size-4" />Cancel remaining work</Button> : null}</header>
      {cancel.error ? <ErrorBanner error={cancel.error} title="Could not cancel Collection Plan" /> : null}
      <section className="rounded-md border border-stone-200 bg-white p-4"><div className="flex flex-wrap items-center gap-3"><StatusBadge status={plan.status} /><strong className="tabular-nums">{plan.progress.processed_target_count.toLocaleString()} of {plan.target_count.toLocaleString()} Pages processed</strong></div><dl className="mt-4 grid gap-3 text-sm sm:grid-cols-3"><div><dt className="text-xs text-stone-500">At creation</dt><dd>{plan.covered_count_at_creation} covered / {plan.in_flight_count_at_creation} in flight</dd></div><div><dt className="text-xs text-stone-500">Frozen batches</dt><dd>{plan.batch_count} at up to {plan.batch_size} Pages</dd></div><div><dt className="text-xs text-stone-500">Created</dt><dd>{formatDate(plan.created_at, { timeZone: site.display_timezone, showTimeZone: true })}</dd></div></dl></section>
      <div className="overflow-x-auto rounded-md border border-stone-200 bg-white"><table className="min-w-full text-left text-sm"><thead className="bg-stone-100 text-xs uppercase text-stone-500"><tr><th className="px-3 py-2">Batch</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Progress</th><th className="px-3 py-2">Native run</th><th className="px-3 py-2">Job</th></tr></thead><tbody>{plan.batches.map((batch) => { const runId = batch.performance_run_id ?? batch.accessibility_run_id ?? batch.render_run_id; const runArea = batch.performance_run_id ? "performance" : batch.accessibility_run_id ? "accessibility" : batch.render_run_id ? "rendered" : null; return <tr key={batch.id} className="border-t border-stone-100"><td className="px-3 py-2 font-medium">{batch.position + 1}</td><td className="px-3 py-2"><StatusBadge status={batch.status} /></td><td className="px-3 py-2 tabular-nums">{batch.processed_target_count} / {batch.target_count}</td><td className="px-3 py-2">{runId && runArea ? <Link className="inline-flex items-center gap-1 underline" to={`/sites/${site.id}/${runArea}/runs/${runId}`}>Run {runId}<ExternalLink className="size-3" /></Link> : "Structured-content job"}</td><td className="px-3 py-2 tabular-nums">{batch.background_job_id ?? "Missing"}</td></tr>; })}</tbody></table></div>
      <details className="rounded-md border border-stone-200 bg-white p-4 text-sm"><summary className="cursor-pointer font-medium">Frozen provenance</summary><dl className="mt-3 space-y-2 break-all text-xs"><div><dt className="text-stone-500">Planner</dt><dd>{plan.planner_version}</dd></div><div><dt className="text-stone-500">Context identity</dt><dd>{plan.context_identity}</dd></div><div><dt className="text-stone-500">Target checksum</dt><dd>{plan.target_selection_sha256}</dd></div></dl></details>
    </div>
  );
}
