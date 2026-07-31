import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";

import { deleteSite, getSite, updateSite } from "../api/client";
import { Button } from "../components/ui/Button";
import { DefinitionList } from "../components/ui/DefinitionList";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorBanner } from "../components/ui/ErrorBanner";
import { LoadingBlock } from "../components/ui/Loading";
import { StatusBadge } from "../components/ui/StatusBadge";
import { classificationLabel } from "../types/siteClassifications";
import type { Site } from "../types/scans";
import { formatDate, plural } from "../utils/format";

export function SiteDetailPage() {
  const { siteId = "" } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const site = useQuery({ queryKey: ["site", siteId], queryFn: () => getSite(siteId) });
  const toggleActive = useMutation({
    mutationFn: (next: boolean) => updateSite(siteId, { is_active: next }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["site", siteId] });
      await queryClient.invalidateQueries({ queryKey: ["sites"] });
    }
  });
  const remove = useMutation({
    mutationFn: () => deleteSite(siteId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["sites"] });
      navigate("/sites");
    }
  });

  if (site.isLoading) return <PageFrame><LoadingBlock label="Loading site..." /></PageFrame>;
  if (site.error) return <PageFrame><ErrorBanner error={site.error} title="Could not load site" /></PageFrame>;
  if (!site.data) return <PageFrame><EmptyState title="Site not found" message="The saved site may have been deleted." /></PageFrame>;

  return (
    <PageFrame>
      <div className="mb-5 flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="mb-2 text-sm text-stone-500"><Link to="/sites" className="underline">Sites</Link> / {site.data.name}</div>
          <h1 className="truncate text-2xl font-semibold">{site.data.name}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <StatusBadge status={site.data.is_active ? "completed" : "interrupted"} label={site.data.is_active ? "Active" : "Inactive"} />
            <span className="font-mono text-xs text-stone-600">{site.data.base_url}</span>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {site.data.is_active ? <Link className="rounded-md border border-neutral-900 bg-neutral-900 px-3 py-2 text-sm font-medium text-white" to={`/scans/new?site_id=${site.data.id}`}>Run scan</Link> : null}
          <Link className="rounded-md border border-stone-300 bg-white px-3 py-2 text-sm font-medium" to={`/sites/${site.data.id}/edit`}>Edit site</Link>
          <Button type="button" loading={toggleActive.isPending} onClick={() => toggleActive.mutate(!site.data!.is_active)}>{site.data.is_active ? "Disable" : "Reactivate"}</Button>
          {site.data.total_scan_count === 0 ? <Button type="button" variant="danger" loading={remove.isPending} onClick={() => {
            if (window.confirm(`Delete ${site.data?.name}? This cannot be undone.`)) remove.mutate();
          }}>Delete</Button> : null}
        </div>
      </div>
      {toggleActive.error || remove.error ? <ErrorBanner error={toggleActive.error ?? remove.error} title="Site action failed" /> : null}
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="space-y-5">
          <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
            <h2 className="mb-4 text-base font-semibold">Site details</h2>
            <DefinitionList items={[
              { label: "Base URL", value: site.data.base_url, copyValue: site.data.base_url },
              { label: "Description", value: site.data.description ?? "Not provided" },
              { label: "Group", value: classificationLabel(site.data.group_key) },
              { label: "Locale", value: site.data.locale ?? "Not specified" },
              { label: "Platform", value: classificationLabel(site.data.platform_key) },
              { label: "Ownership", value: classificationLabel(site.data.ownership_key) },
              { label: "Created", value: formatDate(site.data.created_at) },
              { label: "Updated", value: formatDate(site.data.updated_at) }
            ]} />
          </section>
          <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
            <h2 className="mb-3 text-base font-semibold">Saved scope</h2>
            <ScopeSummary site={site.data} />
            <details className="mt-4">
              <summary className="cursor-pointer text-sm font-medium">View saved scope JSON</summary>
              <pre className="mt-3 max-h-80 overflow-auto rounded-md border border-stone-200 bg-stone-50 p-3 text-xs">{JSON.stringify(site.data.scope_config, null, 2)}</pre>
            </details>
          </section>
        </div>
        <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
          <h2 className="mb-3 text-base font-semibold">Recent scans</h2>
          <div className="mb-3 text-sm text-stone-600">{plural(site.data.total_scan_count, "scan")}</div>
          {site.data.recent_scans.length ? (
            <div className="space-y-2">
              {site.data.recent_scans.map((scan) => (
                <Link key={scan.id} to={`/scans/${scan.id}`} className="block rounded-md border border-stone-200 px-3 py-2 text-sm hover:bg-stone-50">
                  <StatusBadge status={scan.status} />
                  <span className="mt-1 block text-xs text-stone-500">{formatDate(scan.created_at)} · {scan.discovered_count} discovered · {scan.failed_count} failed</span>
                </Link>
              ))}
            </div>
          ) : <EmptyState title="No scans yet" message="Run a scan from this site to build history." />}
        </section>
      </div>
    </PageFrame>
  );
}

function PageFrame({ children }: { children: React.ReactNode }) {
  return <section className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">{children}</section>;
}

function ScopeSummary({ site }: { site: Site }) {
  const scope = site.scope_config;
  const allowed = scope.allowed_host_patterns.length;
  const included = scope.included_path_prefixes.filter((path) => path !== "/").length;
  return (
    <div className="flex flex-wrap gap-2 text-xs">
      <span className="rounded-md border border-stone-200 bg-stone-50 px-2 py-1">{allowed ? plural(allowed, "allowed host") : `Exact hostname from ${new URL(site.base_url).hostname}`}</span>
      <span className="rounded-md border border-stone-200 bg-stone-50 px-2 py-1">{scope.follow_subdomains ? "Subdomains included" : "Subdomains excluded"}</span>
      <span className="rounded-md border border-stone-200 bg-stone-50 px-2 py-1">{included ? plural(included, "included path") : "All paths included"}</span>
      <span className="rounded-md border border-stone-200 bg-stone-50 px-2 py-1">Maximum {scope.max_pages} pages</span>
      <span className="rounded-md border border-stone-200 bg-stone-50 px-2 py-1">Maximum depth {scope.max_depth}</span>
    </div>
  );
}
