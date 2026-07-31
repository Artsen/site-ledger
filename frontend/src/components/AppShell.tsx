import { useQuery } from "@tanstack/react-query";
import { NavLink, Outlet, useParams } from "react-router-dom";

import { listScans } from "../api/client";
import { formatRelativeDate, formatStatus, hostnameFromUrl, isTerminalStatus } from "../utils/format";
import { EmptyState } from "./ui/EmptyState";
import { LoadingBlock } from "./ui/Loading";
import { StatusBadge } from "./ui/StatusBadge";

export function AppShell() {
  const { scanId } = useParams();
  const scans = useQuery({
    queryKey: ["scans"],
    queryFn: listScans,
    refetchInterval: (query) => (query.state.data?.some((scan) => !isTerminalStatus(scan.status)) ? 5000 : false)
  });

  return (
    <div className="min-h-screen bg-[#f7f7f5] text-stone-950 lg:flex">
      <aside className="border-b border-stone-200 bg-stone-100/80 px-3 py-3 lg:sticky lg:top-0 lg:h-screen lg:w-72 lg:shrink-0 lg:overflow-y-auto lg:border-b-0 lg:border-r">
        <div className="flex items-center justify-between gap-3 lg:block">
          <NavLink to="/scans/new" className="block rounded-md px-3 py-2 text-base font-semibold focus:outline-none focus:ring-2 focus:ring-neutral-900 focus:ring-offset-2">
            Artsen Design Scanner
          </NavLink>
          <NavLink
            to="/scans/new"
            className={({ isActive }) =>
              `rounded-md px-3 py-2 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-neutral-900 focus:ring-offset-2 lg:mt-4 lg:block ${
                isActive ? "bg-white text-stone-950 shadow-sm" : "text-stone-700 hover:bg-stone-200"
              }`
            }
          >
            New Scan
          </NavLink>
          <NavLink
            to="/sites"
            className={({ isActive }) =>
              `rounded-md px-3 py-2 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-neutral-900 focus:ring-offset-2 lg:mt-2 lg:block ${
                isActive ? "bg-white text-stone-950 shadow-sm" : "text-stone-700 hover:bg-stone-200"
              }`
            }
          >
            Sites
          </NavLink>
          <NavLink
            to="/scans"
            end
            className={({ isActive }) =>
              `rounded-md px-3 py-2 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-neutral-900 focus:ring-offset-2 lg:mt-2 lg:block ${
                isActive ? "bg-white text-stone-950 shadow-sm" : "text-stone-700 hover:bg-stone-200"
              }`
            }
          >
            All scans
          </NavLink>
        </div>

        <div className="mt-4 hidden lg:block">
          <div className="mb-2 px-3 text-xs font-medium uppercase text-stone-500">Recent scans</div>
          {scans.isLoading ? <LoadingBlock label="Loading scans..." /> : null}
          {scans.error ? <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">Recent scans could not be loaded.</div> : null}
          {!scans.isLoading && !scans.error && !scans.data?.length ? <EmptyState title="No scans yet" message="Start a scan to see it here." /> : null}
          <nav aria-label="Recent scans" className="space-y-1">
            {scans.data?.map((scan) => {
              const active = String(scan.id) === scanId;
              const label = scan.website_property_name ?? hostnameFromUrl(scan.starting_url);
              return (
                <NavLink
                  key={scan.id}
                  to={`/scans/${scan.id}`}
                  className={`block rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-neutral-900 focus:ring-offset-2 ${
                    active ? "bg-white shadow-sm" : "text-stone-700 hover:bg-stone-200"
                  }`}
                  title={scan.starting_url}
                >
                  <span className="block truncate font-medium text-stone-900">{label}</span>
                  <span className="block truncate text-xs text-stone-500">{scan.website_property_name ? "Saved site" : "Ad hoc"}</span>
                  <span className="mt-1 flex items-center justify-between gap-2">
                    <span className="truncate text-xs text-stone-500">{formatRelativeDate(scan.created_at)}</span>
                    <StatusBadge status={scan.status} label={shortStatus(scan.status)} />
                  </span>
                  {scan.status === "completed_with_errors" || scan.failed_count > 0 ? (
                    <span className="mt-1 block text-xs text-amber-700">{scan.failed_count} errors</span>
                  ) : null}
                </NavLink>
              );
            })}
          </nav>
        </div>
      </aside>
      <main className="min-w-0 flex-1">
        <Outlet />
      </main>
    </div>
  );
}

function shortStatus(status: string) {
  if (status === "completed_with_errors") return "Errors";
  if (status === "queued") return "Queued";
  if (status === "running") return "Running";
  if (status === "completed") return "Done";
  return formatStatus(status);
}
