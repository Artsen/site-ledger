import type { LucideIcon } from "lucide-react";
import {
  Activity,
  Accessibility,
  Bot,
  Boxes,
  ChartNoAxesCombined,
  CircleGauge,
  ClipboardList,
  FileStack,
  FolderKanban,
  GitCompareArrows,
  Gauge,
  Globe2,
  ListTree,
  Network,
  NotebookPen,
  Play,
  ScanSearch,
  SearchCheck,
  MonitorUp,
  Settings,
  Tags,
} from "lucide-react";

export type SiteArea =
  | "overview"
  | "scans"
  | "collection-plans"
  | "pages"
  | "resources"
  | "sources"
  | "inventory"
  | "ai-documents"
  | "comparisons"
  | "findings"
  | "performance"
  | "accessibility"
  | "rendered"
  | "graph"
  | "categories"
  | "category-rules"
  | "notes"
  | "settings";

export type SiteNavigationItem = {
  area: SiteArea;
  label: string;
  icon: LucideIcon;
  segment: string;
};

export type SiteNavigationGroup = {
  label: "Observe" | "Analyze" | "Manage";
  items: SiteNavigationItem[];
};

export const globalNavigation = [
  { label: "New Scan", href: "/scans/new", icon: Play },
  { label: "Sites", href: "/sites", icon: Globe2 },
  { label: "All Scans", href: "/scans", icon: Activity },
] as const;

export const siteNavigation: SiteNavigationGroup[] = [
  {
    label: "Observe",
    items: [
      { area: "overview", label: "Overview", icon: CircleGauge, segment: "" },
      { area: "scans", label: "Scans", icon: ScanSearch, segment: "scans" },
      { area: "collection-plans", label: "Collection Plans", icon: ClipboardList, segment: "collection-plans" },
      { area: "pages", label: "Pages", icon: FileStack, segment: "pages" },
      { area: "resources", label: "Resources", icon: Boxes, segment: "resources" },
      { area: "sources", label: "Sources", icon: FolderKanban, segment: "sources" },
      { area: "inventory", label: "URL Inventory", icon: ListTree, segment: "inventory" },
      { area: "ai-documents", label: "AI Documents", icon: Bot, segment: "ai-documents" },
    ],
  },
  {
    label: "Analyze",
    items: [
      { area: "findings", label: "Findings", icon: SearchCheck, segment: "findings" },
      { area: "comparisons", label: "Comparisons", icon: GitCompareArrows, segment: "comparisons" },
      { area: "performance", label: "Performance", icon: Gauge, segment: "performance" },
      { area: "accessibility", label: "Accessibility", icon: Accessibility, segment: "accessibility" },
      { area: "rendered", label: "Rendered", icon: MonitorUp, segment: "rendered" },
      { area: "graph", label: "Graph", icon: Network, segment: "graph" },
    ],
  },
  {
    label: "Manage",
    items: [
      { area: "categories", label: "Categories", icon: Tags, segment: "categories" },
      { area: "category-rules", label: "Category Rules", icon: ChartNoAxesCombined, segment: "category-rules" },
      { area: "notes", label: "Notes", icon: NotebookPen, segment: "notes" },
      { area: "settings", label: "Site Settings", icon: Settings, segment: "settings" },
    ],
  },
];

const allSiteItems = siteNavigation.flatMap((group) => group.items);

export function siteAreaHref(siteId: string | number, area: SiteArea) {
  const item = allSiteItems.find((candidate) => candidate.area === area);
  const base = `/sites/${siteId}`;
  return item?.segment ? `${base}/${item.segment}` : base;
}

export function siteIdFromPath(pathname: string) {
  return pathname.match(/^\/sites\/(\d+)(?:\/|$)/)?.[1] ?? null;
}

export function siteAreaFromPath(pathname: string): SiteArea {
  const match = pathname.match(/^\/sites\/\d+(?:\/([^/]+))?/);
  const segment = match?.[1] ?? "";
  if (segment === "edit") return "settings";
  if (segment === "pages") return "pages";
  if (segment === "resources") return "resources";
  if (segment === "comparisons") return "comparisons";
  if (segment === "performance") return "performance";
  if (segment === "accessibility") return "accessibility";
  if (segment === "rendered") return "rendered";
  return allSiteItems.find((item) => item.segment === segment)?.area ?? "overview";
}

export function switchSiteHref(pathname: string, nextSiteId: string | number) {
  return siteAreaHref(nextSiteId, siteAreaFromPath(pathname));
}

export function isSiteAreaActive(pathname: string, siteId: string | number, area: SiteArea) {
  if (siteIdFromPath(pathname) !== String(siteId)) return false;
  return siteAreaFromPath(pathname) === area;
}
