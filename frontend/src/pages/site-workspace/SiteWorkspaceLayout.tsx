import { useQuery } from "@tanstack/react-query";
import { ExternalLink, Play } from "lucide-react";
import { Link, Outlet, useParams } from "react-router-dom";

import { getSite } from "../../api/client";
import { EmptyState } from "../../components/ui/EmptyState";
import { ErrorBanner } from "../../components/ui/ErrorBanner";
import { LoadingBlock } from "../../components/ui/Loading";
import { StatusBadge } from "../../components/ui/StatusBadge";
import type { Site } from "../../types/scans";
import { useDocumentTitle } from "../../utils/useDocumentTitle";

export type SiteWorkspaceContext = { site: Site };

export function SiteWorkspaceLayout() {
  const { siteId = "" } = useParams();
  const site = useQuery({ queryKey: ["site", siteId], queryFn: () => getSite(siteId) });
  useDocumentTitle(site.data?.name ?? "Site");

  if (site.isLoading) return <WorkspaceFrame><LoadingBlock label="Loading Site workspace..." /></WorkspaceFrame>;
  if (site.error) return <WorkspaceFrame><ErrorBanner error={site.error} title="Could not load Site" /></WorkspaceFrame>;
  if (!site.data) return <WorkspaceFrame><EmptyState title="Site not found" message="The saved Site may have been deleted." /></WorkspaceFrame>;

  return (
    <WorkspaceFrame>
      <header className="mb-6 flex flex-col gap-4 border-b border-stone-200 pb-5 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0">
          <div className="mb-1 text-xs font-medium uppercase text-stone-500">Site workspace</div>
          <h1 className="truncate text-2xl font-semibold">{site.data.name}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <StatusBadge status={site.data.is_active ? "completed" : "interrupted"} label={site.data.is_active ? "Active" : "Inactive"} />
            <a href={site.data.base_url} target="_blank" rel="noreferrer" className="inline-flex max-w-full items-center gap-1 truncate font-mono text-xs text-stone-600 hover:underline">
              <span className="truncate">{site.data.base_url}</span><ExternalLink className="size-3 shrink-0" aria-hidden="true" />
            </a>
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          {site.data.is_active ? (
            <Link className="inline-flex items-center gap-2 rounded-md bg-neutral-900 px-3 py-2 text-sm font-medium text-white focus:outline-none focus:ring-2 focus:ring-neutral-900 focus:ring-offset-2" to={`/scans/new?site_id=${site.data.id}`}>
              <Play className="size-4" aria-hidden="true" /> Run scan
            </Link>
          ) : null}
        </div>
      </header>
      <Outlet context={{ site: site.data } satisfies SiteWorkspaceContext} />
    </WorkspaceFrame>
  );
}

export function WorkspaceFrame({ children }: { children: React.ReactNode }) {
  return <section className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">{children}</section>;
}
