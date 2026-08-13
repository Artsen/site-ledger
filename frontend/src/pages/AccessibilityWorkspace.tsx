import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useOutletContext, useParams, useSearchParams } from "react-router-dom";

import {
  accessibilityPayloadUrl,
  cancelAccessibilityRun,
  createAccessibilityRun,
  getAccessibilityCapabilities,
  getAccessibilityObservation,
  getAccessibilityPages,
  getAccessibilityPayload,
  getAccessibilityRule,
  getAccessibilityRules,
  getAccessibilityRun,
  getAccessibilitySummary,
  getPageAccessibility,
  getPageLatestAccessibility,
  listAccessibilityRuns,
  listSitePages,
} from "../api/client";
import { Button } from "../components/ui/Button";
import { DefinitionList } from "../components/ui/DefinitionList";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorBanner } from "../components/ui/ErrorBanner";
import { LoadingBlock } from "../components/ui/Loading";
import { PaginatedTableControls } from "../components/ui/PaginatedTableControls";
import { StatusBadge } from "../components/ui/StatusBadge";
import { SortableTableHeader } from "../components/ui/SortableTableHeader";
import { Tabs } from "../components/ui/Tabs";
import type {
  AccessibilityCapabilities,
  AccessibilityObservation,
  AccessibilityProfile,
  AccessibilityRun,
  AccessibilityRunPayload,
} from "../types/accessibility";
import type { Site } from "../types/scans";
import { formatDate, formatStatus } from "../utils/format";
import { useUrlPagination } from "../utils/useUrlPagination";

type WorkspaceContext = { site: Site };
type View = "overview" | "pages" | "rules" | "runs";
const TERMINAL = new Set(["completed", "completed_with_errors", "failed", "cancelled", "interrupted"]);
const RAW_RENDER_LIMIT = 200_000;

export function SiteAccessibilityPage() {
  const { site } = useOutletContext<WorkspaceContext>();
  const [searchParams, setSearchParams] = useSearchParams();
  const [collecting, setCollecting] = useState(false);
  const requested = searchParams.get("view");
  const view: View = requested === "pages" || requested === "rules" || requested === "runs" ? requested : "overview";
  const capabilities = useQuery({ queryKey: ["accessibility-capabilities"], queryFn: getAccessibilityCapabilities });
  const summary = useQuery({ queryKey: ["accessibility-summary", String(site.id)], queryFn: () => getAccessibilitySummary(String(site.id)) });
  const runs = useQuery({
    queryKey: ["accessibility-runs", String(site.id)],
    queryFn: () => listAccessibilityRuns(String(site.id), "?limit=25"),
    refetchInterval: (query) => query.state.data?.items.some((run) => !TERMINAL.has(run.status)) ? 2_000 : false,
  });
  if (capabilities.isLoading || summary.isLoading || runs.isLoading) return <LoadingBlock label="Loading Accessibility workspace..." />;
  if (capabilities.error) return <ErrorBanner error={capabilities.error} title="Could not load Accessibility capabilities" />;
  if (summary.error) return <ErrorBanner error={summary.error} title="Could not load Accessibility summary" />;
  if (runs.error) return <ErrorBanner error={runs.error} title="Could not load Accessibility runs" />;
  const latestRun = runs.data?.items[0];
  return <div className="space-y-5">
    <header className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between"><div><h1 className="text-xl font-semibold">Accessibility</h1><p className="mt-1 text-sm text-stone-600">Automated Accessibility evidence from deterministic Desktop and Mobile browser audits.</p></div><Button type="button" variant="primary" onClick={() => setCollecting(true)}>Run Accessibility Audit</Button></header>
    <p className="rounded-md border border-sky-200 bg-sky-50 p-3 text-sm text-sky-950"><strong>Automated checks are limited.</strong> Detectable issues and Needs Review evidence do not establish WCAG conformance.</p>
    <section className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-stone-200 bg-stone-200 lg:grid-cols-4"><Summary label="Latest run" value={latestRun ? formatStatus(latestRun.presentation_status ?? latestRun.status) : "None"} /><Summary label="Pages audited" value={String(summary.data?.pages_audited ?? 0)} /><Summary label="Pages with violations" value={String(summary.data?.pages_with_violations ?? 0)} /><Summary label="Needs Review" value={String(summary.data?.needs_review_rules ?? 0)} /></section>
    <Tabs tabs={[{ id: "overview", label: "Overview" }, { id: "pages", label: "Pages" }, { id: "rules", label: "Rules" }, { id: "runs", label: "Runs", count: runs.data?.total }]} active={view} onChange={(next) => setSearchParams(next === "overview" ? {} : { view: next })} />
    {view === "overview" ? <Overview summary={summary.data} latestRun={latestRun} /> : null}
    {view === "pages" ? <PagesView siteId={String(site.id)} /> : null}
    {view === "rules" ? <RulesView siteId={String(site.id)} /> : null}
    {view === "runs" ? <RunsTable siteId={String(site.id)} runs={runs.data?.items ?? []} /> : null}
    {collecting && capabilities.data ? <CollectAccessibilityPanel siteId={String(site.id)} capabilities={capabilities.data} onClose={() => setCollecting(false)} /> : null}
  </div>;
}

function Summary({ label, value }: { label: string; value: string }) {
  return <div className="min-w-0 bg-white p-4"><div className="text-xs font-medium uppercase text-stone-500">{label}</div><div className="mt-1 truncate text-lg font-semibold">{value}</div></div>;
}

function Overview({ summary, latestRun }: { summary?: Awaited<ReturnType<typeof getAccessibilitySummary>>; latestRun?: AccessibilityRun }) {
  if (!summary?.pages_audited) return <EmptyState title="No Accessibility evidence" message="Run an automated audit for one or more known Pages to begin an immutable history." />;
  return <div className="space-y-4"><section className="grid gap-px overflow-hidden rounded-md border border-stone-200 bg-stone-200 sm:grid-cols-2 lg:grid-cols-4"><Summary label="Profiles observed" value={String(summary.profiles_audited)} /><Summary label="Violation rules" value={String(summary.violation_rules)} /><Summary label="Affected elements" value={String(summary.affected_nodes)} /><Summary label="Failed latest audits" value={String(summary.failed_latest)} /></section><section className="border-y border-stone-200 py-4"><h2 className="font-semibold">Current impact evidence</h2><div className="mt-3 flex flex-wrap gap-2">{Object.entries(summary.impact_counts).map(([impact, count]) => <ImpactBadge key={impact} impact={impact} count={count} />)}{!Object.keys(summary.impact_counts).length ? <span className="text-sm text-stone-500">No violation impact evidence.</span> : null}</div></section><p className="text-sm text-stone-600">Latest observation: {summary.latest_observed_at ? formatDate(summary.latest_observed_at) : "None"}. Latest run: {latestRun ? `Run ${latestRun.id}` : "None"}.</p></div>;
}

function ImpactBadge({ impact, count }: { impact: string | null; count?: number }) {
  const label = impact ? formatStatus(impact) : "Unknown";
  return <span className="inline-flex rounded-md border border-stone-300 bg-stone-100 px-2 py-1 text-xs font-medium">{label}{count == null ? "" : `: ${count}`}</span>;
}

function PagesView({ siteId }: { siteId: string }) {
  const [params, setParams] = useSearchParams();
  const pagination = useUrlPagination({ prefix: "a11y_pages", defaultLimit: 100 });
  const search = params.get("search") ?? "";
  const outcome = params.get("outcome") ?? "";
  const filter = params.get("filter") ?? "";
  const requestedSort = params.get("sort");
  const sort = ["page", "audited", "desktop", "mobile", "critical", "serious", "needs_review"].includes(requestedSort ?? "") ? requestedSort : null;
  const direction = params.get("direction") === "asc" ? "asc" : "desc";
  const query = new URLSearchParams({ limit: String(pagination.limit), offset: String(pagination.offset), sort: sort ?? "audited", direction });
  if (search) query.set("search", search);
  if (outcome) query.set("outcome", outcome);
  if (filter === "violations") query.set("has_violations", "true");
  if (filter === "review") query.set("needs_review", "true");
  if (filter === "critical" || filter === "serious") query.set("impact", filter);
  const pages = useQuery({ queryKey: ["accessibility-pages", siteId, query.toString()], queryFn: () => getAccessibilityPages(siteId, `?${query}`), placeholderData: (previous) => previous });
  const update = (key: string, value: string) => setParams((current) => { const next = new URLSearchParams(current); if (value) next.set(key, value); else next.delete(key); next.delete("a11y_pages_page"); return next; }, { replace: true });
  const changeSort = (column: string | null, nextDirection: "asc" | "desc" | null) => setParams((current) => { const next = new URLSearchParams(current); if (column && nextDirection) { next.set("sort", column); next.set("direction", nextDirection); } else { next.delete("sort"); next.delete("direction"); } next.delete("a11y_pages_page"); return next; }, { replace: true });
  if (pages.error) return <ErrorBanner error={pages.error} title="Could not load Accessibility Pages" />;
  const controls = pages.data ? <PaginatedTableControls total={pages.data.total} limit={pages.data.limit} offset={pages.data.offset} onPageChange={pagination.setPage} onPageSizeChange={pagination.setPageSize} itemLabel="Page" /> : null;
  return <div className="space-y-3"><div className="grid gap-2 sm:grid-cols-3"><input aria-label="Search audited Pages" value={search} onChange={(event) => update("search", event.target.value)} placeholder="Search Page URL" className="rounded-md border border-stone-300 px-3 py-2 text-sm" /><select aria-label="Filter by latest outcome" value={outcome} onChange={(event) => update("outcome", event.target.value)} className="rounded-md border border-stone-300 px-3 py-2 text-sm"><option value="">Any latest outcome</option><option value="ready">Ready</option><option value="failed">Failed</option></select><select aria-label="Filter Accessibility Pages" value={filter} onChange={(event) => update("filter", event.target.value)} className="rounded-md border border-stone-300 px-3 py-2 text-sm"><option value="">All evidence</option><option value="violations">Has violations</option><option value="review">Needs Review</option><option value="critical">Critical impact</option><option value="serious">Serious impact</option></select></div>{pages.isLoading ? <LoadingBlock label="Loading audited Pages..." /> : !pages.data?.items.length ? <EmptyState title="No audited Pages match" message="Change the filters or run an Accessibility audit." /> : <>{controls}<div className="overflow-x-auto rounded-md border border-stone-200 bg-white"><table className="min-w-full text-left text-sm"><thead className="bg-stone-100 text-xs uppercase text-stone-500"><tr>{[["page", "Page"], ["audited", "Last audited"], ["desktop", "Desktop violations"], ["mobile", "Mobile violations"], ["critical", "Critical"], ["serious", "Serious"], ["needs_review", "Needs Review"]].map(([key, label]) => <SortableTableHeader key={key} column={key} label={label} activeColumn={sort} direction={sort ? direction : null} onChange={changeSort} defaultDirection={key === "audited" ? "desc" : "asc"} />)}</tr></thead><tbody>{pages.data.items.map((item) => <tr key={item.page_id} className="border-t border-stone-100 align-top"><td className="max-w-sm px-3 py-2"><Link className="block truncate font-mono text-xs underline" to={`/sites/${siteId}/pages/${item.page_id}?tab=accessibility`}>{item.page_url}</Link></td><td className="whitespace-nowrap px-3 py-2">{formatDate(item.last_audited_at)}</td><td className="px-3 py-2"><ProfileCount outcome={item.desktop_outcome} count={item.desktop_violations} /></td><td className="px-3 py-2"><ProfileCount outcome={item.mobile_outcome} count={item.mobile_violations} /></td><td className="px-3 py-2 tabular-nums">{item.critical_rules}</td><td className="px-3 py-2 tabular-nums">{item.serious_rules}</td><td className="px-3 py-2 tabular-nums">{item.needs_review_rules}</td></tr>)}</tbody></table></div>{controls}</>}</div>;
}

function ProfileCount({ outcome, count }: { outcome: string | null; count: number }) {
  if (!outcome) return <span className="text-stone-500">Not observed</span>;
  if (outcome === "failed") return <StatusBadge status="failed" />;
  return <span className="tabular-nums">{count}</span>;
}

function RulesView({ siteId }: { siteId: string }) {
  const [params, setParams] = useSearchParams();
  const pagination = useUrlPagination({ prefix: "a11y_rules", defaultLimit: 50 });
  const resultType = params.get("result_type") ?? "";
  const impact = params.get("impact") ?? "";
  const profile = params.get("profile") ?? "";
  const query = new URLSearchParams({ limit: String(pagination.limit), offset: String(pagination.offset) });
  if (resultType) query.set("result_type", resultType);
  if (impact) query.set("impact", impact);
  if (profile) query.set("profile", profile);
  const rules = useQuery({ queryKey: ["accessibility-rules", siteId, query.toString()], queryFn: () => getAccessibilityRules(siteId, `?${query}`), placeholderData: (previous) => previous });
  const update = (key: string, value: string) => setParams((current) => { const next = new URLSearchParams(current); if (value) next.set(key, value); else next.delete(key); next.delete("a11y_rules_page"); return next; }, { replace: true });
  if (rules.error) return <ErrorBanner error={rules.error} title="Could not load Accessibility rules" />;
  if (rules.isLoading) return <LoadingBlock label="Loading Accessibility rules..." />;
  const controls = rules.data ? <PaginatedTableControls total={rules.data.total} limit={rules.data.limit} offset={rules.data.offset} onPageChange={pagination.setPage} onPageSizeChange={pagination.setPageSize} itemLabel="rule" /> : null;
  return <div className="space-y-3"><div className="grid gap-2 sm:grid-cols-3"><select aria-label="Rule result type" value={resultType} onChange={(event) => update("result_type", event.target.value)} className="rounded-md border border-stone-300 px-3 py-2 text-sm"><option value="">Violations and Needs Review</option><option value="violation">Violations</option><option value="incomplete">Needs Review</option></select><select aria-label="Rule impact" value={impact} onChange={(event) => update("impact", event.target.value)} className="rounded-md border border-stone-300 px-3 py-2 text-sm"><option value="">Any impact</option>{["critical", "serious", "moderate", "minor"].map((value) => <option key={value} value={value}>{formatStatus(value)}</option>)}</select><select aria-label="Audit profile" value={profile} onChange={(event) => update("profile", event.target.value)} className="rounded-md border border-stone-300 px-3 py-2 text-sm"><option value="">Any profile</option><option value="desktop">Desktop</option><option value="mobile">Mobile</option></select></div>{!rules.data?.items.length ? <EmptyState title="No current rule evidence" message="Latest ready audits have no matching violations or Needs Review results." /> : <>{controls}<div className="overflow-x-auto rounded-md border border-stone-200 bg-white"><table className="min-w-full text-left text-sm"><thead className="bg-stone-100 text-xs uppercase text-stone-500"><tr><th className="px-3 py-2">Rule</th><th className="px-3 py-2">Result</th><th className="px-3 py-2">Impact</th><th className="px-3 py-2">Pages</th><th className="px-3 py-2">Elements</th><th className="hidden px-3 py-2 md:table-cell">Profiles / standards</th></tr></thead><tbody>{rules.data.items.map((rule) => <tr key={`${rule.result_type}:${rule.rule_id}:${rule.impact}`} className="border-t border-stone-100 align-top"><td className="px-3 py-2"><Link className="font-medium underline" to={`/sites/${siteId}/accessibility/rules/${rule.rule_id}?result_type=${rule.result_type}`}>{rule.help || rule.rule_id}</Link><span className="block font-mono text-xs text-stone-500">{rule.rule_id}</span></td><td className="px-3 py-2"><StatusBadge status={rule.result_type === "incomplete" ? "needs_review" : "violation"} label={rule.result_type === "incomplete" ? "Needs Review" : "Violation"} /></td><td className="px-3 py-2"><ImpactBadge impact={rule.impact} /></td><td className="px-3 py-2 tabular-nums">{rule.pages_affected}</td><td className="px-3 py-2 tabular-nums">{rule.affected_nodes}</td><td className="hidden max-w-xs px-3 py-2 text-xs md:table-cell"><span className="block">{rule.profiles.map(formatStatus).join(", ")}</span><span className="block text-stone-500">{rule.tags.filter((tag) => tag.startsWith("wcag")).join(", ")}</span></td></tr>)}</tbody></table></div>{controls}</>}</div>;
}

function RunsTable({ siteId, runs }: { siteId: string; runs: AccessibilityRun[] }) {
  if (!runs.length) return <EmptyState title="No Accessibility runs" message="Automated Accessibility audits are manual and on demand." />;
  return <div className="overflow-x-auto rounded-md border border-stone-200 bg-white"><table className="min-w-full text-left text-sm"><thead className="bg-stone-100 text-xs uppercase text-stone-500"><tr><th className="px-3 py-2">Run</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Profiles</th><th className="px-3 py-2">Progress</th><th className="hidden px-3 py-2 sm:table-cell">Results</th><th className="hidden px-3 py-2 md:table-cell">Created</th></tr></thead><tbody>{runs.map((run) => <tr key={run.id} className="border-t border-stone-100"><td className="px-3 py-2"><Link className="font-medium underline" to={`/sites/${siteId}/accessibility/runs/${run.id}`}>Run {run.id}</Link><span className="block text-xs text-stone-500">{run.target_count} Pages / {run.observation_count} audits</span></td><td className="px-3 py-2"><StatusBadge status={run.presentation_status ?? run.status} /></td><td className="px-3 py-2">{run.configuration_json.profiles.map(formatStatus).join(", ")}</td><td className="px-3 py-2 tabular-nums">{run.completed_count} / {run.observation_count}</td><td className="hidden px-3 py-2 sm:table-cell">{run.ready_count} ready, {run.failed_count} failed</td><td className="hidden whitespace-nowrap px-3 py-2 md:table-cell">{formatDate(run.created_at)}</td></tr>)}</tbody></table></div>;
}

function ObservationTable({ siteId, observations }: { siteId: string; observations: AccessibilityObservation[] }) {
  return <div className="overflow-x-auto rounded-md border border-stone-200 bg-white"><table className="min-w-full text-left text-sm"><thead className="bg-stone-100 text-xs uppercase text-stone-500"><tr><th className="px-3 py-2">Page</th><th className="px-3 py-2">Profile / outcome</th><th className="px-3 py-2">Violations</th><th className="px-3 py-2">Needs Review</th><th className="hidden px-3 py-2 md:table-cell">Observed</th><th className="px-3 py-2">Raw</th></tr></thead><tbody>{observations.map((item) => <tr key={item.id} className="border-t border-stone-100 align-top"><td className="max-w-sm px-3 py-2"><Link className="block truncate font-mono text-xs underline" to={`/sites/${siteId}/pages/${item.web_resource_id}?tab=accessibility`}>{item.page_url ?? item.requested_url}</Link></td><td className="px-3 py-2"><span className="block font-medium">{formatStatus(item.profile)}</span><StatusBadge status={item.outcome} />{item.error_message ? <span className="mt-1 block max-w-sm text-xs text-red-700">{item.error_message}</span> : null}</td><td className="px-3 py-2 tabular-nums">{item.outcome === "ready" ? `${item.violation_rule_count} rules / ${item.violation_node_count} elements` : "Unavailable"}</td><td className="px-3 py-2 tabular-nums">{item.outcome === "ready" ? `${item.incomplete_rule_count} rules` : "Unavailable"}</td><td className="hidden whitespace-nowrap px-3 py-2 md:table-cell">{formatDate(item.observed_at)}</td><td className="px-3 py-2">{item.payload_sha256 ? <Link className="underline" to={`/sites/${siteId}/accessibility/evidence/${item.id}`}>View</Link> : "None"}</td></tr>)}</tbody></table></div>;
}

export function AccessibilityRunPage() {
  const { site } = useOutletContext<WorkspaceContext>();
  const { runId = "" } = useParams();
  const queryClient = useQueryClient();
  const run = useQuery({ queryKey: ["accessibility-run", String(site.id), runId], queryFn: () => getAccessibilityRun(String(site.id), runId, "?limit=500"), refetchInterval: (query) => query.state.data && !TERMINAL.has(query.state.data.status) ? 2_000 : false });
  const cancel = useMutation({ mutationFn: () => cancelAccessibilityRun(String(site.id), runId), onSuccess: () => queryClient.invalidateQueries({ queryKey: ["accessibility-run", String(site.id), runId] }) });
  if (run.isLoading) return <LoadingBlock label="Loading Accessibility run..." />;
  if (run.error) return <ErrorBanner error={run.error} title="Could not load Accessibility run" />;
  if (!run.data) return null;
  const value = run.data;
  return <div className="space-y-5"><header className="flex flex-wrap items-start justify-between gap-3"><div><Link className="text-sm underline" to={`/sites/${site.id}/accessibility?view=runs`}>Accessibility runs</Link><h1 className="mt-1 text-xl font-semibold">Run {value.id}</h1></div>{!TERMINAL.has(value.status) ? <Button type="button" variant="danger" loading={cancel.isPending} onClick={() => cancel.mutate()}>Cancel run</Button> : null}</header><section className="rounded-md border border-stone-200 bg-white p-4"><DefinitionList items={[{ label: "Status", value: <StatusBadge status={value.presentation_status ?? value.status} /> }, { label: "Progress", value: `${value.completed_count} of ${value.observation_count} browser audits` }, { label: "Ready", value: value.ready_count }, { label: "Failed", value: value.failed_count }, { label: "Profiles", value: value.configuration_json.profiles.map(formatStatus).join(", ") }, { label: "Effective ruleset", value: `${value.ruleset_profile} (${value.ruleset_rule_count} rules)` }, { label: "Ruleset SHA-256", value: value.ruleset_sha256, copyValue: value.ruleset_sha256 }, { label: "axe-core", value: value.axe_core_version }, { label: "Created", value: formatDate(value.created_at) }, { label: "Finished", value: value.finished_at ? formatDate(value.finished_at) : "In progress" }]} />{value.error_summary ? <p className="mt-4 text-sm text-red-700">{value.error_summary}</p> : null}</section>{value.observations.items.length ? <ObservationTable siteId={String(site.id)} observations={value.observations.items} /> : <EmptyState title="No observations committed yet" message="The worker commits each Page/profile audit independently." />}</div>;
}

export function AccessibilityRulePage() {
  const { site } = useOutletContext<WorkspaceContext>();
  const { ruleId = "" } = useParams();
  const [params] = useSearchParams();
  const pagination = useUrlPagination({ prefix: "rule", defaultLimit: 50 });
  const resultType = params.get("result_type") === "incomplete" ? "incomplete" : "violation";
  const detail = useQuery({ queryKey: ["accessibility-rule", String(site.id), ruleId, resultType, pagination.limit, pagination.offset], queryFn: () => getAccessibilityRule(String(site.id), ruleId, `?result_type=${resultType}&limit=${pagination.limit}&offset=${pagination.offset}`) });
  if (detail.isLoading) return <LoadingBlock label="Loading rule evidence..." />;
  if (detail.error) return <ErrorBanner error={detail.error} title="Could not load rule evidence" />;
  if (!detail.data) return null;
  const value = detail.data;
  const controls = <PaginatedTableControls total={value.total} limit={value.limit} offset={value.offset} onPageChange={pagination.setPage} onPageSizeChange={pagination.setPageSize} itemLabel="affected element" />;
  return <div className="space-y-5"><header><Link className="text-sm underline" to={`/sites/${site.id}/accessibility?view=rules`}>Accessibility rules</Link><h1 className="mt-1 text-xl font-semibold">{value.help || value.rule_id}</h1><p className="font-mono text-xs text-stone-500">{value.rule_id}</p></header><section className="rounded-md border border-stone-200 bg-white p-4"><DefinitionList items={[{ label: "Result", value: resultType === "incomplete" ? "Needs Review" : "Violation" }, { label: "Impact", value: formatStatus(value.impact) }, { label: "Description", value: value.description }, { label: "Pages affected", value: value.pages_affected }, { label: "Affected elements", value: value.affected_nodes }, { label: "Standards tags", value: value.tags.join(", ") }, { label: "Detector guidance", value: value.help_url ? <a href={value.help_url} target="_blank" rel="noreferrer" className="underline">Open axe guidance <ExternalLink className="inline" size={14} /></a> : "None" }]} /></section>{controls}<div className="space-y-3">{value.occurrences.map((item) => <article key={item.node.id} className="rounded-md border border-stone-200 bg-white p-4"><div className="flex flex-wrap items-start justify-between gap-2"><div className="min-w-0"><Link className="block truncate font-mono text-xs underline" to={`/sites/${site.id}/pages/${item.page_id}?tab=accessibility`}>{item.page_url}</Link><span className="text-xs text-stone-500">{formatStatus(item.profile)} / {formatDate(item.observed_at)}</span></div><ImpactBadge impact={item.impact} /></div><dl className="mt-3 grid gap-3 text-sm"><div><dt className="font-medium">Target</dt><dd><code className="break-all">{JSON.stringify(item.node.target_json)}</code></dd></div><div><dt className="font-medium">Failure summary</dt><dd className="whitespace-pre-wrap">{item.node.failure_summary}</dd></div><div><dt className="font-medium">HTML snippet{item.node.html_truncated ? " (truncated)" : ""}</dt><dd><pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-all rounded bg-stone-950 p-3 text-xs text-stone-100">{item.node.html_snippet}</pre></dd></div></dl></article>)}</div>{controls}</div>;
}

export function AccessibilityEvidencePage() {
  const { site } = useOutletContext<WorkspaceContext>();
  const { observationId = "" } = useParams();
  const payload = useQuery({ queryKey: ["accessibility-payload", observationId], queryFn: () => getAccessibilityPayload(Number(observationId)) });
  const metadata = useQuery({ queryKey: ["accessibility-observation", String(site.id), observationId], queryFn: () => getAccessibilityObservation(String(site.id), Number(observationId)) });
  if (payload.isLoading || metadata.isLoading) return <LoadingBlock label="Loading raw Accessibility evidence..." />;
  if (payload.error) return <ErrorBanner error={payload.error} title="Could not load raw Accessibility evidence" />;
  if (metadata.error) return <ErrorBanner error={metadata.error} title="Could not load Accessibility observation" />;
  if (!metadata.data) return null;
  const observation = metadata.data;
  const content = payload.data ?? "";
  const truncated = content.length > RAW_RENDER_LIMIT;
  return <div className="space-y-4"><header><Link className="text-sm underline" to={`/sites/${site.id}/accessibility/runs/${observation.accessibility_run_id}`}>Run {observation.accessibility_run_id}</Link><h1 className="mt-1 text-xl font-semibold">Raw Accessibility evidence</h1></header><section className="rounded-md border border-stone-200 bg-white p-4"><DefinitionList items={[{ label: "Requested URL", value: observation.requested_url }, { label: "Final URL", value: observation.final_url }, { label: "Profile", value: formatStatus(observation.profile) }, { label: "Observed", value: formatDate(observation.observed_at) }, { label: "axe-core", value: observation.axe_core_version }, { label: "Detector SHA-256", value: observation.detector_bundle_sha256, copyValue: observation.detector_bundle_sha256 }, { label: "Ruleset", value: observation.ruleset_profile }, { label: "Ruleset SHA-256", value: observation.ruleset_sha256, copyValue: observation.ruleset_sha256 }, { label: "Normalization", value: observation.normalization_version }, { label: "Payload SHA-256", value: observation.payload_sha256, copyValue: observation.payload_sha256 }]} /></section>{truncated ? <p className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm">Browser display is limited to {RAW_RENDER_LIMIT.toLocaleString()} characters. The retained payload remains exact. <a className="underline" href={accessibilityPayloadUrl(observation.id)} target="_blank" rel="noreferrer">Open full payload <ExternalLink className="inline" size={14} /></a></p> : null}<pre tabIndex={0} className="max-h-[65vh] overflow-auto whitespace-pre-wrap break-all rounded-md border border-stone-300 bg-stone-950 p-4 font-mono text-xs text-stone-100">{content.slice(0, RAW_RENDER_LIMIT)}</pre></div>;
}

export function PageAccessibilityPanel({ siteId, resourceId }: { siteId: string; resourceId: string }) {
  const [collecting, setCollecting] = useState(false);
  const pagination = useUrlPagination({ prefix: "accessibility_history", defaultLimit: 25 });
  const history = useQuery({ queryKey: ["page-accessibility", siteId, resourceId, pagination.limit, pagination.offset], queryFn: () => getPageAccessibility(siteId, resourceId, `?limit=${pagination.limit}&offset=${pagination.offset}`) });
  const current = useQuery({ queryKey: ["page-accessibility-latest", siteId, resourceId], queryFn: () => getPageLatestAccessibility(siteId, resourceId) });
  const capabilities = useQuery({ queryKey: ["accessibility-capabilities"], queryFn: getAccessibilityCapabilities });
  if (history.isLoading || current.isLoading || capabilities.isLoading) return <LoadingBlock label="Loading Page Accessibility..." />;
  if (history.error) return <ErrorBanner error={history.error} title="Could not load Page Accessibility" />;
  if (current.error) return <ErrorBanner error={current.error} title="Could not load latest Page Accessibility" />;
  const latest = new Map((current.data?.items ?? []).map((item) => [item.profile, item]));
  const controls = history.data?.items.length ? <PaginatedTableControls total={history.data.total} limit={history.data.limit} offset={history.data.offset} onPageChange={pagination.setPage} onPageSizeChange={pagination.setPageSize} itemLabel="observation" /> : null;
  return <div className="space-y-4"><div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-semibold">Automated Accessibility evidence</h2><p className="text-sm text-stone-600">Independent browser observations; not a WCAG conformance determination.</p></div><Button type="button" variant="primary" onClick={() => setCollecting(true)}>Audit this Page</Button></div><section className="grid gap-3 sm:grid-cols-2">{(["desktop", "mobile"] as const).map((profile) => <div key={profile} className="rounded-md border border-stone-200 bg-white p-3"><h3 className="text-xs font-medium uppercase text-stone-500">Latest {formatStatus(profile)}</h3><div className="mt-2"><LatestProfile observation={latest.get(profile)} /></div></div>)}</section>{controls}{history.data?.items.length ? <ObservationTable siteId={siteId} observations={history.data.items} /> : <EmptyState title="No Page Accessibility history" message="Run an audit to collect the first immutable observation." />}{controls}{collecting && capabilities.data ? <CollectAccessibilityPanel siteId={siteId} capabilities={capabilities.data} initialResourceId={Number(resourceId)} onClose={() => setCollecting(false)} /> : null}</div>;
}

function LatestProfile({ observation }: { observation?: AccessibilityObservation }) {
  if (!observation) return <span className="text-sm text-stone-500">Not observed</span>;
  return <div className="space-y-1 text-sm"><StatusBadge status={observation.outcome} />{observation.outcome === "ready" ? <><p><strong>{observation.violation_rule_count}</strong> violation rules / {observation.violation_node_count} elements</p><p><strong>{observation.incomplete_rule_count}</strong> Needs Review rules</p></> : <p className="text-red-700">{observation.error_message ?? "Audit failed."}</p>}</div>;
}

function CollectAccessibilityPanel({ siteId, capabilities, onClose, initialResourceId }: { siteId: string; capabilities: AccessibilityCapabilities; onClose: () => void; initialResourceId?: number }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const dialogRef = useRef<HTMLElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<number[]>(initialResourceId ? [initialResourceId] : []);
  const [desktop, setDesktop] = useState(true);
  const [mobile, setMobile] = useState(true);
  const limit = 10;
  const pages = useQuery({ queryKey: ["accessibility-page-selector", siteId, search, page], queryFn: () => listSitePages(siteId, `?search=${encodeURIComponent(search)}&limit=${limit}&offset=${(page - 1) * limit}&sort=url&direction=asc`) });
  const profiles: AccessibilityProfile[] = [...(desktop ? ["desktop" as const] : []), ...(mobile ? ["mobile" as const] : [])];
  const auditCount = selected.length * profiles.length;
  const payload: AccessibilityRunPayload = { resource_ids: selected, profiles, trigger: initialResourceId ? "page_workspace" : "site_workspace" };
  const create = useMutation({ mutationFn: () => createAccessibilityRun(siteId, payload), onSuccess: async (run) => { await queryClient.invalidateQueries({ queryKey: ["accessibility-runs", siteId] }); navigate(`/sites/${siteId}/accessibility/runs/${run.id}`); } });
  const pageLimit = Math.min(capabilities.default_page_limit, capabilities.hard_page_limit);
  const toggle = (id: number) => setSelected((current) => current.includes(id) ? current.filter((value) => value !== id) : current.length < pageLimit ? [...current, id] : current);
  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const dialog = dialogRef.current;
    const focusable = () => Array.from(dialog?.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), select:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])') ?? []);
    focusable()[0]?.focus();
    const handleKeyDown = (event: KeyboardEvent) => { if (event.key === "Escape") { event.preventDefault(); closeRef.current(); return; } if (event.key !== "Tab") return; const items = focusable(); if (!items.length) return; const first = items[0]; const last = items[items.length - 1]; if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); } else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); } };
    dialog?.addEventListener("keydown", handleKeyDown);
    return () => { dialog?.removeEventListener("keydown", handleKeyDown); previous?.focus(); };
  }, []);
  return <section ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="collect-accessibility-title" className="fixed inset-0 z-50 overflow-y-auto bg-black/40 p-3 sm:p-8"><div className="mx-auto max-w-3xl rounded-md bg-white p-4 shadow-xl sm:p-6"><header className="flex items-start justify-between gap-3"><div><h2 id="collect-accessibility-title" className="text-lg font-semibold">Run Accessibility Audit</h2><p className="text-sm text-stone-600">Select up to {pageLimit} Pages. Browser audits run serially.</p></div><button type="button" aria-label="Close Accessibility audit" onClick={onClose} className="rounded p-2 hover:bg-stone-100"><X size={20} /></button></header>{!initialResourceId ? <div className="mt-5 space-y-3"><input aria-label="Search Pages for Accessibility" value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} placeholder="Search known Pages" className="w-full rounded-md border border-stone-300 px-3 py-2 text-sm" />{pages.isLoading ? <LoadingBlock label="Loading Pages..." /> : pages.error ? <ErrorBanner error={pages.error} title="Could not load Pages" /> : <><div className="divide-y rounded-md border border-stone-200">{pages.data?.items.map((item) => <label key={item.resource_id} className="flex cursor-pointer items-start gap-3 p-3 hover:bg-stone-50"><input type="checkbox" className="mt-1" checked={selected.includes(item.resource_id)} disabled={!selected.includes(item.resource_id) && selected.length >= pageLimit} onChange={() => toggle(item.resource_id)} /><span className="min-w-0"><span className="block truncate font-medium">{item.latest_title ?? "Untitled Page"}</span><span className="block truncate font-mono text-xs text-stone-500">{item.normalized_url}</span></span></label>)}</div>{pages.data ? <PaginatedTableControls compact total={pages.data.total} limit={limit} offset={(page - 1) * limit} onPageChange={setPage} onPageSizeChange={() => undefined} allowedPageSizes={[limit]} itemLabel="Page" /> : null}</>}</div> : null}<fieldset className="mt-5 border-t border-stone-200 pt-5"><legend className="font-medium">Audit profiles</legend><Check label="Desktop (1440 × 900)" checked={desktop} onChange={setDesktop} /><Check label="Mobile (390 × 844)" checked={mobile} onChange={setMobile} /></fieldset><p className="mt-4 rounded-md bg-stone-100 p-3 text-sm"><strong>{selected.length}</strong> Pages × <strong>{profiles.length}</strong> profiles = <strong>{auditCount}</strong> browser audits.</p><p className="mt-3 text-xs text-stone-600">Automated detection cannot evaluate every WCAG 2.2 A/AA requirement. Incomplete results are retained as Needs Review evidence.</p><div className="mt-5 flex flex-col gap-3 border-t border-stone-200 pt-4 sm:flex-row sm:items-center sm:justify-end"><Button type="button" onClick={onClose}>Cancel</Button><Button type="button" variant="primary" loading={create.isPending} disabled={!selected.length || !profiles.length} onClick={() => create.mutate()}>Start {auditCount} audits</Button></div>{create.error ? <div className="mt-3"><ErrorBanner error={create.error} title="Could not start Accessibility audit" /></div> : null}</div></section>;
}

function Check({ label, checked, onChange }: { label: string; checked: boolean; onChange: (checked: boolean) => void }) {
  return <label className="mt-2 flex items-center gap-2 text-sm"><input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />{label}</label>;
}
