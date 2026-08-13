import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Menu, X } from "lucide-react";
import { Suspense, useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { listScanHistory, listSites } from "../api/client";
import { productName, productTagline } from "../config/brand";
import {
  globalNavigation,
  isSiteAreaActive,
  siteAreaHref,
  siteIdFromPath,
  siteNavigation,
  switchSiteHref,
} from "../navigation/workspaceNavigation";
import { formatRelativeDate, formatStatus, hostnameFromUrl, isTerminalStatus } from "../utils/format";
import { SiteLedgerMark } from "./SiteLedgerMark";
import { LoadingBlock } from "./ui/Loading";
import { StatusBadge } from "./ui/StatusBadge";

const SIDEBAR_STORAGE_KEY = "site-ledger.sidebar-collapsed";

export function AppShell() {
  const location = useLocation();
  const navigate = useNavigate();
  const currentSiteId = siteIdFromPath(location.pathname);
  const currentScanId = location.pathname.match(/^\/scans\/(\d+)(?:\/|$)/)?.[1] ?? null;
  const [collapsed, setCollapsed] = useState(readSidebarPreference);
  const [mobileOpen, setMobileOpen] = useState(false);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const drawerRef = useRef<HTMLElement>(null);

  const sites = useQuery({
    queryKey: ["sites", "workspace-catalog"],
    queryFn: () => listSites("?limit=100&offset=0&sort=name&direction=asc"),
    staleTime: 30_000,
  });
  const scans = useQuery({
    queryKey: ["scan-history", "workspace-recent"],
    queryFn: () => listScanHistory("?limit=6&offset=0&sort=created_at&direction=desc"),
    refetchInterval: (query) =>
      query.state.data?.items.some((scan) => !isTerminalStatus(scan.status)) ? 5000 : false,
  });
  const currentSite = sites.data?.items.find((site) => String(site.id) === currentSiteId);

  useEffect(() => {
    try {
      window.localStorage.setItem(SIDEBAR_STORAGE_KEY, String(collapsed));
    } catch {
      // Navigation remains usable when browser storage is unavailable.
    }
  }, [collapsed]);

  useEffect(() => {
    setMobileOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (!mobileOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    drawerRef.current?.focus();
    const handleDrawerKeys = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setMobileOpen(false);
        menuButtonRef.current?.focus();
      }
      if (event.key === "Tab" && drawerRef.current) {
        const focusable = Array.from(drawerRef.current.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'));
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    };
    window.addEventListener("keydown", handleDrawerKeys);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", handleDrawerKeys);
    };
  }, [mobileOpen]);

  const sidebar = (
    <SidebarContent
      collapsed={collapsed}
      currentScanId={currentScanId}
      currentSiteId={currentSiteId}
      currentSiteName={currentSite?.name}
      currentSiteHostname={currentSite ? hostnameFromUrl(currentSite.base_url) : undefined}
      pathname={location.pathname}
      scans={scans.data?.items ?? []}
      scansLoading={scans.isLoading}
      scansError={Boolean(scans.error)}
      sites={sites.data?.items ?? []}
      sitesLoading={sites.isLoading}
      sitesError={Boolean(sites.error)}
      onNavigate={() => setMobileOpen(false)}
      onSiteChange={(siteId) => navigate(switchSiteHref(location.pathname, siteId))}
    />
  );

  return (
    <div className="min-h-screen bg-[#f7f7f5] text-stone-950 lg:flex">
      <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-stone-200 bg-stone-100 px-4 lg:hidden">
        <button
          ref={menuButtonRef}
          type="button"
          className="grid size-9 place-items-center rounded-md text-stone-700 hover:bg-stone-200 focus:outline-none focus:ring-2 focus:ring-neutral-900"
          aria-label="Open navigation"
          aria-expanded={mobileOpen}
          onClick={() => setMobileOpen(true)}
        >
          <Menu className="size-5" aria-hidden="true" />
        </button>
        <SiteLedgerMark className="size-7 text-stone-950" />
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold">{currentSite?.name ?? productName}</div>
          {currentSite ? <div className="truncate text-xs text-stone-500">Site workspace</div> : null}
        </div>
      </header>

      {mobileOpen ? (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button
            type="button"
            className="absolute inset-0 bg-black/35"
            aria-label="Close navigation"
            onClick={() => {
              setMobileOpen(false);
              menuButtonRef.current?.focus();
            }}
          />
          <aside
            ref={drawerRef}
            tabIndex={-1}
            aria-label="Workspace navigation"
            className="relative h-full w-[min(88vw,19rem)] overflow-y-auto border-r border-stone-200 bg-stone-100 shadow-xl outline-none"
          >
            <button
              type="button"
              className="absolute right-3 top-3 z-10 grid size-9 place-items-center rounded-md hover:bg-stone-200 focus:outline-none focus:ring-2 focus:ring-neutral-900"
              aria-label="Close navigation"
              onClick={() => {
                setMobileOpen(false);
                menuButtonRef.current?.focus();
              }}
            >
              <X className="size-5" aria-hidden="true" />
            </button>
            {sidebar}
          </aside>
        </div>
      ) : null}

      <aside
        className={`sticky top-0 hidden h-screen shrink-0 border-r border-stone-200 bg-stone-100 transition-[width] duration-150 lg:block ${collapsed ? "w-16" : "w-72"}`}
        aria-label="Workspace navigation"
      >
        <div className="h-full overflow-y-auto overflow-x-hidden">{sidebar}</div>
        <button
          type="button"
          className="absolute -right-3 top-16 grid size-6 place-items-center rounded-full border border-stone-300 bg-white text-stone-600 shadow-sm hover:text-stone-950 focus:outline-none focus:ring-2 focus:ring-neutral-900"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          onClick={() => setCollapsed((value) => !value)}
        >
          {collapsed ? <ChevronRight className="size-4" /> : <ChevronLeft className="size-4" />}
        </button>
      </aside>

      <main className="min-w-0 flex-1">
        <Suspense fallback={<div className="p-6 text-sm text-stone-500">Loading workspace...</div>}>
          <Outlet />
        </Suspense>
      </main>
    </div>
  );
}

type SidebarContentProps = {
  collapsed: boolean;
  currentScanId: string | null;
  currentSiteId: string | null;
  currentSiteName?: string;
  currentSiteHostname?: string;
  pathname: string;
  scans: Awaited<ReturnType<typeof listScanHistory>>["items"];
  scansLoading: boolean;
  scansError: boolean;
  sites: Awaited<ReturnType<typeof listSites>>["items"];
  sitesLoading: boolean;
  sitesError: boolean;
  onNavigate: () => void;
  onSiteChange: (siteId: string) => void;
};

function SidebarContent(props: SidebarContentProps) {
  const showLabels = !props.collapsed;
  return (
    <div className="flex min-h-full flex-col px-2 py-3">
      <NavLink
        to="/sites"
        onClick={props.onNavigate}
        aria-label={`${productName} Sites`}
        className="flex h-11 items-center gap-3 rounded-md px-2 focus:outline-none focus:ring-2 focus:ring-neutral-900"
      >
        <SiteLedgerMark className="size-8 shrink-0 text-stone-950" />
        {showLabels ? (
          <span className="min-w-0">
            <span className="block text-base font-semibold">{productName}</span>
            <span className="block truncate text-xs text-stone-500">{productTagline}</span>
          </span>
        ) : null}
      </NavLink>

      <nav aria-label="Global" className="mt-3 space-y-1">
        {globalNavigation.map((item) => (
          <WorkspaceLink key={item.href} href={item.href} label={item.label} icon={item.icon} collapsed={!showLabels} onClick={props.onNavigate} />
        ))}
      </nav>

      {props.currentSiteId ? (
        <div className="mt-5 border-t border-stone-200 pt-4">
          {showLabels ? (
            <div className="px-2">
              <label htmlFor="site-switcher" className="mb-1 block text-xs font-medium uppercase text-stone-500">Current Site</label>
              <select
                id="site-switcher"
                value={props.currentSiteId}
                disabled={props.sitesLoading || props.sitesError || props.sites.length === 0}
                onChange={(event) => props.onSiteChange(event.target.value)}
                className="w-full rounded-md border border-stone-300 bg-white px-2 py-2 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-neutral-900"
              >
                {props.sitesLoading ? <option value={props.currentSiteId}>Loading Sites...</option> : null}
                {props.sitesError ? <option value={props.currentSiteId}>Site catalog unavailable</option> : null}
                {!props.sitesLoading && !props.sitesError && props.sites.length === 0 ? (
                  <option value={props.currentSiteId}>{props.currentSiteName ?? `Site ${props.currentSiteId}`}</option>
                ) : null}
                {props.currentSiteName && !props.sites.some((site) => String(site.id) === props.currentSiteId) ? (
                  <option value={props.currentSiteId}>{props.currentSiteName}</option>
                ) : null}
                {props.sites.map((site) => <option key={site.id} value={site.id}>{site.name}</option>)}
              </select>
              {props.currentSiteHostname ? <div className="mt-1 truncate text-xs text-stone-500">{props.currentSiteHostname}</div> : null}
              {props.sitesError ? <div className="mt-1 text-xs text-red-700">Could not load Sites</div> : null}
            </div>
          ) : (
            <div className="mx-auto grid size-9 place-items-center rounded-md bg-white text-sm font-semibold" title={props.currentSiteName ?? "Current Site"}>
              {(props.currentSiteName ?? "S").slice(0, 1).toUpperCase()}
            </div>
          )}
          <nav aria-label="Site workspace" className="mt-3 space-y-4">
            {siteNavigation.map((group) => (
              <div key={group.label}>
                {showLabels ? <div className="mb-1 px-2 text-xs font-medium uppercase text-stone-500">{group.label}</div> : null}
                <div className="space-y-1">
                  {group.items.map((item) => (
                    <WorkspaceLink
                      key={item.area}
                      href={siteAreaHref(props.currentSiteId!, item.area)}
                      label={item.label}
                      icon={item.icon}
                      collapsed={!showLabels}
                      active={isSiteAreaActive(props.pathname, props.currentSiteId!, item.area)}
                      onClick={props.onNavigate}
                    />
                  ))}
                </div>
              </div>
            ))}
          </nav>
        </div>
      ) : null}

      <div className="mt-5 border-t border-stone-200 pt-4">
        {showLabels ? <div className="mb-2 px-2 text-xs font-medium uppercase text-stone-500">Recent scans</div> : null}
        {props.scansLoading && showLabels ? <LoadingBlock label="Loading scans..." /> : null}
        {props.scansError && showLabels ? <div className="px-2 text-xs text-red-700">Recent scans unavailable</div> : null}
        <nav aria-label="Recent scans" className="space-y-1">
          {props.scans.map((scan) => {
            const label = scan.website_property_name ?? hostnameFromUrl(scan.starting_url);
            return (
              <NavLink
                key={scan.id}
                to={`/scans/${scan.id}`}
                onClick={props.onNavigate}
                title={`${label} - ${formatStatus(scan.status)}`}
                className={`block rounded-md px-2 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-neutral-900 ${String(scan.id) === props.currentScanId ? "bg-white shadow-sm" : "text-stone-700 hover:bg-stone-200"}`}
              >
                {showLabels ? (
                  <>
                    <span className="block truncate font-medium text-stone-900">{label}</span>
                    <span className="mt-1 flex items-center justify-between gap-2">
                      <span className="truncate text-xs text-stone-500">{formatRelativeDate(scan.created_at)}</span>
                      <StatusBadge status={scan.status} label={shortStatus(scan.status)} />
                    </span>
                  </>
                ) : (
                  <span className="mx-auto block size-2 rounded-full bg-stone-500" aria-hidden="true" />
                )}
              </NavLink>
            );
          })}
        </nav>
      </div>

      {showLabels ? (
        <div className="mt-auto border-t border-stone-200 px-2 pt-4 text-xs text-stone-500">
          <span className={`mr-2 inline-block size-2 rounded-full ${props.scansError ? "bg-red-500" : "bg-emerald-600"}`} />
          {props.scansError ? "API unavailable" : "Local workspace"}
        </div>
      ) : null}
    </div>
  );
}

function WorkspaceLink({ href, label, icon: Icon, collapsed, active, onClick }: { href: string; label: string; icon: React.ComponentType<{ className?: string; "aria-hidden"?: boolean | "true" | "false" }>; collapsed: boolean; active?: boolean; onClick: () => void }) {
  return (
    <NavLink
      to={href}
      end={href === "/sites" || href === "/scans" || /^\/sites\/\d+$/.test(href)}
      onClick={onClick}
      title={collapsed ? label : undefined}
      className={({ isActive }) => `flex h-9 items-center gap-3 rounded-md px-2 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-neutral-900 ${active ?? isActive ? "bg-white text-stone-950 shadow-sm" : "text-stone-700 hover:bg-stone-200"}`}
    >
      <Icon className="size-4 shrink-0" aria-hidden="true" />
      {collapsed ? <span className="sr-only">{label}</span> : <span className="truncate">{label}</span>}
    </NavLink>
  );
}

function shortStatus(status: string) {
  if (status === "completed_with_errors") return "Errors";
  if (status === "queued") return "Queued";
  if (status === "running") return "Running";
  if (status === "completed") return "Done";
  return formatStatus(status);
}

function readSidebarPreference() {
  try {
    return window.localStorage.getItem(SIDEBAR_STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}
