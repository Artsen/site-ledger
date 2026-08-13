import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import {
  getComparison,
  getComparisonLink,
  getComparisonLinkOccurrences,
  getComparisonPage,
  getComparisonPageSourceDiff,
  getComparisonResource,
} from "../api/client";
import { Button } from "../components/ui/Button";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorBanner } from "../components/ui/ErrorBanner";
import { LoadingBlock } from "../components/ui/Loading";
import { StatusBadge } from "../components/ui/StatusBadge";
import { formatStatus } from "../utils/format";
import { immutableComparisonQueryOptions } from "../utils/comparisonQueryOptions";
import { useDocumentTitle } from "../utils/useDocumentTitle";

export function PageComparisonDetailPage() {
  const { siteId = "", comparisonId = "", resourceId = "" } = useParams();
  const [showDiff, setShowDiff] = useState(false);
  const [diffMode, setDiffMode] = useState<"exact" | "meaningful">("exact");
  const page = useQuery({ queryKey: ["comparison-page", siteId, comparisonId, resourceId], queryFn: () => getComparisonPage(siteId, comparisonId, resourceId), ...immutableComparisonQueryOptions });
  const comparison = useQuery({ queryKey: ["comparison", siteId, comparisonId], queryFn: () => getComparison(siteId, comparisonId), ...immutableComparisonQueryOptions });
  const diff = useQuery({ queryKey: ["comparison-source-diff", siteId, comparisonId, resourceId, diffMode], queryFn: () => getComparisonPageSourceDiff(siteId, comparisonId, resourceId, diffMode), enabled: showDiff, ...immutableComparisonQueryOptions });
  useDocumentTitle(page.data ? `Page change - ${page.data.normalized_url}` : "Page comparison");
  if (page.isLoading || comparison.isLoading) return <Frame><LoadingBlock label="Loading Page comparison..." /></Frame>;
  if (page.error || comparison.error) return <Frame><ErrorBanner error={page.error ?? comparison.error} title="Could not load Page comparison" /></Frame>;
  if (!page.data || !comparison.data) return <Frame><EmptyState title="Page comparison not found" message="This result may belong to a superseded or deleted comparison." /></Frame>;
  const item = page.data; const overview = comparison.data; const baseline = item.baseline_json; const target = item.target_json;
  return <Frame>
    <Header siteId={siteId} comparisonId={comparisonId} title="Page comparison" subtitle={item.normalized_url} />
    <div className="mb-5 flex flex-wrap items-center gap-2"><StatusBadge status={item.presence_state} label={formatStatus(item.presence_state)} /><StatusBadge status={item.primary_change_class} label={formatStatus(item.primary_change_class)} /><span className="text-sm text-stone-600">Baseline Scan {overview.comparison.baseline_scan_id} to Target Scan {overview.comparison.target_scan_id}</span></div>
    {overview.comparison.current_build?.warnings_json.length ? <section className="mb-5 border-l-4 border-amber-500 bg-amber-50 px-4 py-3 text-sm"><strong>Coverage warnings</strong><p className="mt-1">{overview.comparison.current_build.warnings_json.map(formatStatus).join("; ")}</p></section> : null}
    <section className="grid grid-cols-1 gap-5 lg:grid-cols-2"><Side title="Baseline observation" values={baseline} snapshotId={item.baseline_snapshot_id} scanId={overview.comparison.baseline_scan_id} /><Side title="Target observation" values={target} snapshotId={item.target_snapshot_id} scanId={overview.comparison.target_scan_id} /></section>
    <section className="mt-6 border-y border-stone-200 py-5"><h2 className="font-semibold">Change signals</h2><div className="mt-3 grid grid-cols-2 gap-3 text-sm md:grid-cols-4">{[["Content", item.document_content_state], ["Metadata", item.metadata_state], ["Technical", item.technical_state], ["Raw source", item.exact_source_state], ["Normalized source", item.normalized_source_state], ["HTTP status", item.http_status_changed], ["Inbound links", item.inbound_links_changed], ["Outbound links", item.outbound_links_changed]].map(([label, value]) => <div key={String(label)}><span className="block text-stone-500">{label}</span><strong>{typeof value === "boolean" ? (value ? "Changed" : "Same") : formatStatus(String(value))}</strong></div>)}</div>{item.source_difference_categories_json.length ? <p className="mt-4 text-sm"><span className="text-stone-500">Evidence categories: </span>{item.source_difference_categories_json.map(formatStatus).join(", ")}</p> : null}</section>
    <section className="mt-6"><h2 className="font-semibold">Retrieval metrics</h2><p className="mt-1 text-sm text-stone-600">Observed timing and transfer differences are measurements, not automatic structural changes.</p><div className="mt-3 flex flex-wrap gap-6 text-sm"><span>Response: {signed(item.response_time_ms_delta, " ms")}</span><span>Network: {signed(item.network_bytes_delta, " B")}</span><span>Raw HTML: {signed(item.raw_html_size_delta, " B")}</span><span>Stored HTML: {signed(item.stored_html_size_delta, " B")}</span></div></section>
    <section className="mt-6"><div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-semibold">Source diff</h2><p className="text-sm text-stone-600">Meaningful mode suppresses only differences covered by explicit volatile rules.</p></div><div className="flex items-center gap-3"><div className="inline-flex border border-stone-300" role="group" aria-label="Source diff mode"><button type="button" aria-pressed={diffMode === "exact"} onClick={() => { setDiffMode("exact"); setShowDiff(true); }} className={`px-3 py-2 text-sm ${diffMode === "exact" ? "bg-stone-900 text-white" : "bg-white"}`}>Exact</button><button type="button" aria-pressed={diffMode === "meaningful"} onClick={() => { setDiffMode("meaningful"); setShowDiff(true); }} className={`border-l border-stone-300 px-3 py-2 text-sm ${diffMode === "meaningful" ? "bg-stone-900 text-white" : "bg-white"}`}>Meaningful</button></div><Button type="button" onClick={() => setShowDiff(true)}>View diff</Button></div></div>{diff.isLoading ? <LoadingBlock label="Calculating bounded source diff..." /> : null}{diff.error ? <ErrorBanner error={diff.error} title="Could not load source diff" /> : null}{diff.data ? <div className="mt-3"><StatusBadge status={diff.data.state} label={formatStatus(diff.data.state)} />{diff.data.diff_text ? <pre className="mt-3 max-h-[34rem] overflow-auto whitespace-pre-wrap border border-stone-200 bg-stone-50 p-3 font-mono text-xs">{diff.data.diff_text}</pre> : null}</div> : null}</section>
  </Frame>;
}

export function ResourceComparisonDetailPage() {
  const { siteId = "", comparisonId = "", resourceId = "" } = useParams();
  const resource = useQuery({ queryKey: ["comparison-resource", siteId, comparisonId, resourceId], queryFn: () => getComparisonResource(siteId, comparisonId, resourceId), ...immutableComparisonQueryOptions });
  const comparison = useQuery({ queryKey: ["comparison", siteId, comparisonId], queryFn: () => getComparison(siteId, comparisonId), ...immutableComparisonQueryOptions });
  useDocumentTitle(resource.data ? `Resource change - ${resource.data.normalized_url}` : "Resource comparison");
  if (resource.isLoading || comparison.isLoading) return <Frame><LoadingBlock label="Loading Resource comparison..." /></Frame>;
  if (resource.error || comparison.error) return <Frame><ErrorBanner error={resource.error ?? comparison.error} title="Could not load Resource comparison" /></Frame>;
  if (!resource.data || !comparison.data) return <Frame><EmptyState title="Resource comparison not found" message="The selected derived result is unavailable." /></Frame>;
  const item = resource.data;
  return <Frame><Header siteId={siteId} comparisonId={comparisonId} title="Resource comparison" subtitle={item.normalized_url} /><div className="mb-5 flex gap-2"><StatusBadge status={item.presence_state} label={formatStatus(item.presence_state)} /><StatusBadge status={item.change_state} label={formatStatus(item.change_state)} /></div><section className="grid grid-cols-1 gap-5 lg:grid-cols-2"><Side title="Baseline metadata" values={item.baseline_json} snapshotId={item.baseline_snapshot_id} scanId={comparison.data.comparison.baseline_scan_id} /><Side title="Target metadata" values={item.target_json} snapshotId={item.target_snapshot_id} scanId={comparison.data.comparison.target_scan_id} /></section><section className="mt-6 border-l-4 border-stone-400 bg-stone-50 px-4 py-3 text-sm"><strong>Resource body comparison is not available.</strong><p className="mt-1 text-stone-600">This view compares retained Resource metadata only and does not claim that body content is unchanged.</p></section></Frame>;
}

export function LinkComparisonDetailPage() {
  const { siteId = "", comparisonId = "", sourceResourceId = "", targetResourceId = "" } = useParams();
  const link = useQuery({ queryKey: ["comparison-link", siteId, comparisonId, sourceResourceId, targetResourceId], queryFn: () => getComparisonLink(siteId, comparisonId, sourceResourceId, targetResourceId), ...immutableComparisonQueryOptions });
  const comparison = useQuery({ queryKey: ["comparison", siteId, comparisonId], queryFn: () => getComparison(siteId, comparisonId), ...immutableComparisonQueryOptions });
  const occurrences = useQuery({ queryKey: ["comparison-link-occurrences", siteId, comparisonId, sourceResourceId, targetResourceId], queryFn: () => getComparisonLinkOccurrences(siteId, comparisonId, sourceResourceId, targetResourceId, "?limit=250"), ...immutableComparisonQueryOptions });
  useDocumentTitle("Link comparison");
  if (link.isLoading || comparison.isLoading) return <Frame><LoadingBlock label="Loading Link comparison..." /></Frame>;
  if (link.error || comparison.error) return <Frame><ErrorBanner error={link.error ?? comparison.error} title="Could not load Link comparison" /></Frame>;
  if (!link.data || !comparison.data) return <Frame><EmptyState title="Link comparison not found" message="The selected edge is unavailable." /></Frame>;
  const item = link.data;
  return <Frame><Header siteId={siteId} comparisonId={comparisonId} title="Link comparison" subtitle={`${item.source_url} to ${item.target_url}`} /><div className="mb-5 flex flex-wrap gap-2"><StatusBadge status={item.presence_state} label={formatStatus(item.presence_state)} /><StatusBadge status={item.change_state} label={formatStatus(item.change_state)} /><span className="text-sm">Occurrences {item.baseline_occurrence_count} to {item.target_occurrence_count} ({signed(item.occurrence_delta)})</span></div><section className="grid grid-cols-1 gap-5 lg:grid-cols-2"><Side title="Baseline edge" values={item.baseline_json} snapshotId={item.baseline_source_snapshot_id} scanId={comparison.data.comparison.baseline_scan_id} /><Side title="Target edge" values={item.target_json} snapshotId={item.target_source_snapshot_id} scanId={comparison.data.comparison.target_scan_id} /></section><section className="mt-6"><h2 className="font-semibold">Exact occurrence multiset</h2><p className="mt-1 text-sm text-stone-600">Identical duplicate links retain their observed multiplicity.</p>{occurrences.isLoading ? <LoadingBlock label="Loading exact link evidence..." /> : null}{occurrences.error ? <ErrorBanner error={occurrences.error} title="Could not load occurrence differences" /> : null}<div className="mt-3 space-y-2">{occurrences.data?.items.map((entry) => <details key={`${entry.state}-${entry.fingerprint}`} className="border-b border-stone-200 py-2"><summary className="cursor-pointer text-sm"><strong>{formatStatus(entry.state)}</strong> - {entry.count} occurrence{entry.count === 1 ? "" : "s"}</summary><pre className="mt-2 overflow-auto whitespace-pre-wrap bg-stone-50 p-3 text-xs">{JSON.stringify(entry.occurrence, null, 2)}</pre></details>)}</div>{occurrences.data?.truncated ? <p className="mt-3 text-sm text-amber-800">Occurrence comparison reached its safety bound.</p> : null}</section></Frame>;
}

function Header({ siteId, comparisonId, title, subtitle }: { siteId: string; comparisonId: string; title: string; subtitle: string }) { return <header className="mb-5"><Link className="text-sm text-stone-500 underline" to={`/sites/${siteId}/comparisons?comparison_id=${comparisonId}`}>Back to comparison</Link><h1 className="mt-2 text-2xl font-semibold">{title}</h1><p className="mt-1 break-all font-mono text-xs text-stone-600">{subtitle}</p></header>; }
function Side({ title, values, snapshotId, scanId }: { title: string; values: Record<string, unknown> | null; snapshotId: number | null; scanId: number }) { return <section className="border-t-2 border-neutral-900 pt-3"><div className="flex items-center justify-between gap-3"><h2 className="font-semibold">{title}</h2>{snapshotId ? <Link className="text-sm underline" to={`/scans/${scanId}/pages/${snapshotId}`}>Observation {snapshotId}</Link> : null}</div>{values ? <dl className="mt-3 grid gap-2 text-sm">{Object.entries(values).map(([key, value]) => <div key={key} className="grid grid-cols-[9rem_minmax(0,1fr)] gap-3 border-b border-stone-100 pb-1"><dt className="text-stone-500">{formatStatus(key)}</dt><dd className="min-w-0 break-all">{display(value)}</dd></div>)}</dl> : <p className="mt-3 text-sm text-stone-600">Not observed as this representation.</p>}</section>; }
function display(value: unknown) { if (value == null || value === "") return "Not available"; if (typeof value === "boolean") return value ? "Yes" : "No"; if (typeof value === "object") return JSON.stringify(value); return String(value); }
function signed(value: number | null, suffix = "") { return value == null ? "Not available" : `${value > 0 ? "+" : ""}${value.toLocaleString()}${suffix}`; }
function Frame({ children }: { children: React.ReactNode }) { return <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">{children}</main>; }
