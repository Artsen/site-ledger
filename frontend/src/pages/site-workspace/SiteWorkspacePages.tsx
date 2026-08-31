import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";
import { Link, Navigate, useLocation, useNavigate, useOutletContext, useParams, useSearchParams } from "react-router-dom";

import { createSiteNote, deleteSite, getScanProjectionStatus, listSiteNotes, listSiteScans } from "../../api/client";
import { NotesPanel } from "../../components/NotesPanel";
import { ResourceInventoryView } from "../../components/ResourceInventoryView";
import { SiteComparisonsPanel } from "../../components/SiteComparisonsPanel";
import { EmptyState } from "../../components/ui/EmptyState";
import { ErrorBanner } from "../../components/ui/ErrorBanner";
import { LoadingBlock } from "../../components/ui/Loading";
import { PaginatedTableControls } from "../../components/ui/PaginatedTableControls";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { Button } from "../../components/ui/Button";
import { ScanGraphView } from "../../features/graph/ScanGraphView";
import { siteAreaHref, type SiteArea } from "../../navigation/workspaceNavigation";
import { SiteFormPage } from "../SiteFormPage";
import { SiteCategoriesSection, SiteInventorySection, SitePagesSection, SiteSourcesSection } from "../SiteWorkspaceSections";
import { formatDate } from "../../utils/format";
import { useUrlPagination } from "../../utils/useUrlPagination";
import type { SiteWorkspaceContext } from "./SiteWorkspaceLayout";
import { SiteIntelligenceOverview } from "./SiteIntelligenceOverview";
import { CollectionPlansWorkspace } from "./CollectionPlansWorkspace";
import { SiteFindingDetailPage as FindingDetail, SiteFindingsWorkspace } from "./SiteFindingsWorkspace";

function useSiteWorkspace() {
  return useOutletContext<SiteWorkspaceContext>().site;
}

export function SiteOverviewPage() {
  return <SiteIntelligenceOverview site={useSiteWorkspace()} />;
}

export function SiteCollectionPlansPage() {
  return <CollectionPlansWorkspace site={useSiteWorkspace()} />;
}

export function SitePagesPage() {
  return <SitePagesSection site={useSiteWorkspace()} />;
}

export function SiteFindingsPage() {
  return <SiteFindingsWorkspace site={useSiteWorkspace()} />;
}

export function SiteFindingDetailPage() {
  return <FindingDetail site={useSiteWorkspace()} />;
}

export function SiteResourcesPage() {
  const site = useSiteWorkspace();
  return <div className="space-y-4"><p className="text-sm text-stone-600">Resources are non-HTML files and embedded references retained from Scans. URL Inventory remains the separate set of candidate Page URLs declared by Sources.</p><ResourceInventoryView scope="site" id={String(site.id)} /></div>;
}

export function SiteSourcesPage() {
  return <SiteSourcesSection site={useSiteWorkspace()} mode="sources" />;
}

export function SiteAiDocumentsPage() {
  return <SiteSourcesSection site={useSiteWorkspace()} mode="ai-documents" />;
}

export function SiteInventoryPage() {
  return <SiteInventorySection site={useSiteWorkspace()} />;
}

export function SiteComparisonsPage() {
  return <SiteComparisonsPanel site={useSiteWorkspace()} />;
}

export function SiteCategoriesPage() {
  return <SiteCategoriesSection site={useSiteWorkspace()} view="categories" />;
}

export function SiteCategoryRulesPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const view = searchParams.get("view") === "history" ? "history" : "rules";
  const site = useSiteWorkspace();
  return (
    <div className="space-y-4">
      <div className="inline-flex rounded-md border border-stone-300 bg-white p-1" aria-label="Category Rule view">
        <button type="button" aria-pressed={view === "rules"} onClick={() => setSearchParams({})} className={`rounded px-3 py-1.5 text-sm ${view === "rules" ? "bg-stone-900 text-white" : "text-stone-700"}`}>Rules</button>
        <button type="button" aria-pressed={view === "history"} onClick={() => setSearchParams({ view: "history" })} className={`rounded px-3 py-1.5 text-sm ${view === "history" ? "bg-stone-900 text-white" : "text-stone-700"}`}>Evaluation History</button>
      </div>
      <SiteCategoriesSection site={site} view={view} />
    </div>
  );
}

export function SiteNotesPage() {
  const site = useSiteWorkspace();
  return <NotesPanel queryKey={["site-notes", String(site.id)]} list={(query) => listSiteNotes(String(site.id), query)} create={(body, pinned) => createSiteNote(String(site.id), body, pinned)} context={site.name} />;
}

export function SiteSettingsPage() {
  const site = useSiteWorkspace();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const remove = useMutation({
    mutationFn: () => deleteSite(String(site.id)),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["sites"] });
      navigate("/sites");
    },
  });
  return <div className="space-y-8"><SiteFormPage mode="edit" embedded />{site.total_scan_count === 0 ? <section className="max-w-5xl border-t border-red-200 pt-5"><h2 className="text-base font-semibold text-red-900">Delete Site</h2><p className="mt-1 text-sm text-stone-600">Permanently remove this Site. This action is available only before any Scan history exists.</p><Button type="button" variant="danger" loading={remove.isPending} onClick={() => { if (window.confirm(`Delete ${site.name}? This cannot be undone.`)) remove.mutate(); }} className="mt-3">Delete Site</Button>{remove.error ? <div className="mt-3"><ErrorBanner error={remove.error} title="Could not delete Site" /></div> : null}</section> : null}</div>;
}

export function SiteScansPage() {
  const site = useSiteWorkspace();
  const pagination = useUrlPagination({ prefix: "site_scans", defaultLimit: 25 });
  const scans = useQuery({
    queryKey: ["site-scans", String(site.id), pagination.limit, pagination.offset],
    queryFn: () => listSiteScans(String(site.id), `?limit=${pagination.limit}&offset=${pagination.offset}&sort=created_at&direction=desc`),
    placeholderData: (previous) => previous,
  });
  if (scans.isLoading) return <LoadingBlock label="Loading Site scans..." />;
  if (scans.error) return <ErrorBanner error={scans.error} title="Could not load Site scans" />;
  if (!scans.data?.items.length) return <EmptyState title="No scans yet" message="Run a scan from this Site to build its observation history." />;
  const controls = <PaginatedTableControls total={scans.data.total} limit={scans.data.limit} offset={scans.data.offset} onPageChange={pagination.setPage} onPageSizeChange={pagination.setPageSize} itemLabel="scan" isLoading={scans.isFetching} />;
  return (
    <div className="space-y-4">
      {controls}
      <div className="overflow-x-auto rounded-md border border-stone-200 bg-white">
        <table className="min-w-full text-left text-sm"><thead className="bg-stone-100 text-xs uppercase text-stone-500"><tr><th className="px-3 py-2">Scan</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Created</th><th className="px-3 py-2">Discovered</th><th className="px-3 py-2">Failed</th></tr></thead><tbody>{scans.data.items.map((scan) => <tr key={scan.id} className="border-t border-stone-100"><td className="px-3 py-2"><Link to={`/scans/${scan.id}`} className="font-medium underline">Scan {scan.id}</Link></td><td className="px-3 py-2"><StatusBadge status={scan.status} /></td><td className="whitespace-nowrap px-3 py-2">{formatDate(scan.created_at, { timeZone: site.display_timezone, showTimeZone: true })}</td><td className="px-3 py-2">{scan.discovered_count}</td><td className="px-3 py-2">{scan.failed_count}</td></tr>)}</tbody></table>
      </div>
      {controls}
    </div>
  );
}

export function SiteGraphPage() {
  const site = useSiteWorkspace();
  const [searchParams, setSearchParams] = useSearchParams();
  const scans = useQuery({ queryKey: ["site-graph-scans", String(site.id)], queryFn: () => listSiteScans(String(site.id), "?limit=100&sort=created_at&direction=desc") });
  const eligible = useMemo(() => scans.data?.items.filter((scan) => scan.status === "completed" || scan.status === "completed_with_errors") ?? [], [scans.data?.items]);
  const requestedId = searchParams.get("scan_id");
  const selected = eligible.find((scan) => String(scan.id) === requestedId) ?? eligible[0];
  const projection = useQuery({ queryKey: ["scan-projection", String(selected?.id ?? "")], queryFn: () => getScanProjectionStatus(String(selected!.id)), enabled: Boolean(selected) });
  if (scans.isLoading) return <LoadingBlock label="Loading graph scans..." />;
  if (scans.error) return <ErrorBanner error={scans.error} title="Could not load graph scans" />;
  if (!selected) return <EmptyState title="No completed scan" message="Complete a Site scan before opening its graph." />;
  return <div className="space-y-4"><label className="block max-w-sm text-sm font-medium">Graph evidence<select aria-label="Graph scan" value={selected.id} onChange={(event) => setSearchParams({ scan_id: event.target.value })} className="mt-1 block w-full rounded-md border border-stone-300 bg-white px-3 py-2"><option value={selected.id}>Scan {selected.id} - {formatDate(selected.created_at, { timeZone: site.display_timezone })}</option>{eligible.filter((scan) => scan.id !== selected.id).map((scan) => <option key={scan.id} value={scan.id}>Scan {scan.id} - {formatDate(scan.created_at, { timeZone: site.display_timezone })}</option>)}</select></label>{projection.isLoading ? <LoadingBlock label="Preparing graph..." /> : <ScanGraphView scan={selected} projectionStatus={projection.data} />}</div>;
}

const legacyAreas: Record<string, SiteArea> = {
  overview: "overview", scans: "scans", pages: "pages", resources: "resources", sources: "sources",
  inventory: "inventory", comparisons: "comparisons", categories: "categories", notes: "notes", graph: "graph",
  performance: "performance",
  findings: "findings",
};

export function LegacySiteRedirect() {
  const { siteId = "" } = useParams();
  const location = useLocation();
  const params = new URLSearchParams(location.search);
  const legacyTab = params.get("tab");
  if (!legacyTab) return <SiteOverviewPage />;
  const area = legacyAreas[legacyTab] ?? "overview";
  params.delete("tab");
  const query = params.toString();
  return <Navigate replace to={`${siteAreaHref(siteId, area)}${query ? `?${query}` : ""}`} />;
}
