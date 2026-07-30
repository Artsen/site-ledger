import { useQuery } from "@tanstack/react-query";
import { NavLink, Outlet } from "react-router-dom";

import { listScans } from "../api/client";

export function AppShell() {
  const scans = useQuery({ queryKey: ["scans"], queryFn: listScans, refetchInterval: 5000 });
  return (
    <div className="flex min-h-screen">
      <aside className="w-72 shrink-0 border-r border-stone-200 bg-stone-100 px-4 py-5">
        <div className="mb-6 text-base font-semibold">Artsen Design Scanner</div>
        <NavLink
          to="/scans/new"
          className={({ isActive }) =>
            `mb-4 block rounded-md px-3 py-2 text-sm ${isActive ? "bg-white shadow-sm" : "hover:bg-stone-200"}`
          }
        >
          New Scan
        </NavLink>
        <div className="mb-2 px-3 text-xs font-medium uppercase tracking-wide text-stone-500">Recent scans</div>
        <div className="space-y-1">
          {scans.data?.map((scan) => (
            <NavLink
              key={scan.id}
              to={`/scans/${scan.id}`}
              className="block truncate rounded-md px-3 py-2 text-sm text-stone-700 hover:bg-stone-200"
              title={scan.starting_url}
            >
              <span className="block truncate">{scan.starting_url}</span>
              <span className="text-xs text-stone-500">{scan.status}</span>
            </NavLink>
          ))}
        </div>
      </aside>
      <main className="min-w-0 flex-1 bg-[#fbfbfa]">
        <Outlet />
      </main>
    </div>
  );
}

