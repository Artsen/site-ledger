import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { lazy } from "react";
import ReactDOM from "react-dom/client";
import { Navigate, RouterProvider, createBrowserRouter } from "react-router-dom";

import { AppShell } from "./components/AppShell";
import "./styles/index.css";

const PageDetailPage = lazyNamed(() => import("./pages/PageDetailPage"), "PageDetailPage");
const PersistentPageDetailPage = lazyNamed(() => import("./pages/PersistentPageDetailPage"), "PersistentPageDetailPage");
const ScanDetailPage = lazyNamed(() => import("./pages/ScanDetailPage"), "ScanDetailPage");
const ScansPage = lazyNamed(() => import("./pages/ScansPage"), "ScansPage");
const SitesPage = lazyNamed(() => import("./pages/SitesPage"), "SitesPage");
const NewScanPage = lazyNamed(() => import("./pages/NewScanPage"), "NewScanPage");
const AiDocumentEvidencePage = lazyNamed(() => import("./pages/AiDocumentEvidencePage"), "AiDocumentEvidencePage");
const AiDocumentSourcePage = lazyNamed(() => import("./pages/AiDocumentSourcePage"), "AiDocumentSourcePage");
const SiteWorkspaceLayout = lazyNamed(() => import("./pages/site-workspace/SiteWorkspaceLayout"), "SiteWorkspaceLayout");
const SiteFormPage = lazyNamed<{ mode: "create" | "edit"; embedded?: boolean }>(() => import("./pages/SiteFormPage"), "SiteFormPage");
const ResourceDetailPage = lazyNamed<{ scope: "site" | "scan" }>(() => import("./pages/ResourceDetailPage"), "ResourceDetailPage");
const SitePerformancePage = lazyNamed(() => import("./pages/PerformanceWorkspace"), "SitePerformancePage");
const PerformanceRunPage = lazyNamed(() => import("./pages/PerformanceWorkspace"), "PerformanceRunPage");
const PerformanceEvidencePage = lazyNamed(() => import("./pages/PerformanceWorkspace"), "PerformanceEvidencePage");
const SiteAccessibilityPage = lazyNamed(() => import("./pages/AccessibilityWorkspace"), "SiteAccessibilityPage");
const AccessibilityRunPage = lazyNamed(() => import("./pages/AccessibilityWorkspace"), "AccessibilityRunPage");
const AccessibilityRulePage = lazyNamed(() => import("./pages/AccessibilityWorkspace"), "AccessibilityRulePage");
const AccessibilityEvidencePage = lazyNamed(() => import("./pages/AccessibilityWorkspace"), "AccessibilityEvidencePage");

function lazyWorkspacePage(name: keyof typeof import("./pages/site-workspace/SiteWorkspacePages")) {
  return lazyNamed(() => import("./pages/site-workspace/SiteWorkspacePages"), name);
}

const LegacySiteRedirect = lazyWorkspacePage("LegacySiteRedirect");
const SiteAiDocumentsPage = lazyWorkspacePage("SiteAiDocumentsPage");
const SiteCategoriesPage = lazyWorkspacePage("SiteCategoriesPage");
const SiteCategoryRulesPage = lazyWorkspacePage("SiteCategoryRulesPage");
const SiteComparisonsPage = lazyWorkspacePage("SiteComparisonsPage");
const SiteGraphPage = lazyWorkspacePage("SiteGraphPage");
const SiteInventoryPage = lazyWorkspacePage("SiteInventoryPage");
const SiteNotesPage = lazyWorkspacePage("SiteNotesPage");
const SitePagesPage = lazyWorkspacePage("SitePagesPage");
const SiteResourcesPage = lazyWorkspacePage("SiteResourcesPage");
const SiteScansPage = lazyWorkspacePage("SiteScansPage");
const SiteSettingsPage = lazyWorkspacePage("SiteSettingsPage");
const SiteSourcesPage = lazyWorkspacePage("SiteSourcesPage");

const PageComparisonDetailPage = lazyNamed(() => import("./pages/ComparisonDetailPages"), "PageComparisonDetailPage");
const ResourceComparisonDetailPage = lazyNamed(() => import("./pages/ComparisonDetailPages"), "ResourceComparisonDetailPage");
const LinkComparisonDetailPage = lazyNamed(() => import("./pages/ComparisonDetailPages"), "LinkComparisonDetailPage");

const router = createBrowserRouter([
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/scans/new" replace /> },
      { path: "sites", element: <SitesPage /> },
      { path: "sites/new", element: <SiteFormPage mode="create" /> },
      {
        path: "sites/:siteId",
        element: <SiteWorkspaceLayout />,
        children: [
          { index: true, element: <LegacySiteRedirect /> },
          { path: "scans", element: <SiteScansPage /> },
          { path: "pages", element: <SitePagesPage /> },
          { path: "pages/:resourceId", element: <PersistentPageDetailPage /> },
          { path: "resources", element: <SiteResourcesPage /> },
          { path: "resources/:resourceId", element: <ResourceDetailPage scope="site" /> },
          { path: "sources", element: <SiteSourcesPage /> },
          { path: "inventory", element: <SiteInventoryPage /> },
          { path: "ai-documents", element: <SiteAiDocumentsPage /> },
          { path: "ai-documents/evidence/:snapshotId", element: <AiDocumentEvidencePage /> },
          { path: "ai-documents/:sourceId", element: <AiDocumentSourcePage /> },
          { path: "comparisons", element: <SiteComparisonsPage /> },
          { path: "performance", element: <SitePerformancePage /> },
          { path: "performance/runs/:runId", element: <PerformanceRunPage /> },
          { path: "performance/evidence/:observationId", element: <PerformanceEvidencePage /> },
          { path: "accessibility", element: <SiteAccessibilityPage /> },
          { path: "accessibility/runs/:runId", element: <AccessibilityRunPage /> },
          { path: "accessibility/rules/:ruleId", element: <AccessibilityRulePage /> },
          { path: "accessibility/evidence/:observationId", element: <AccessibilityEvidencePage /> },
          { path: "comparisons/:comparisonId/pages/:resourceId", element: <PageComparisonDetailPage /> },
          { path: "comparisons/:comparisonId/resources/:resourceId", element: <ResourceComparisonDetailPage /> },
          { path: "comparisons/:comparisonId/links/:sourceResourceId/:targetResourceId", element: <LinkComparisonDetailPage /> },
          { path: "graph", element: <SiteGraphPage /> },
          { path: "categories", element: <SiteCategoriesPage /> },
          { path: "category-rules", element: <SiteCategoryRulesPage /> },
          { path: "notes", element: <SiteNotesPage /> },
          { path: "settings", element: <SiteSettingsPage /> },
          { path: "edit", element: <Navigate to="../settings" replace /> },
        ],
      },
      { path: "ai-document-sources/:sourceId", element: <AiDocumentSourcePage /> },
      { path: "ai-document-snapshots/:snapshotId", element: <AiDocumentEvidencePage /> },
      { path: "scans", element: <ScansPage /> },
      { path: "scans/new", element: <NewScanPage /> },
      { path: "scans/:scanId", element: <ScanDetailPage /> },
      { path: "scans/:scanId/pages/:snapshotId", element: <PageDetailPage /> },
      { path: "scans/:scanId/resources/:resourceId", element: <ResourceDetailPage scope="scan" /> }
    ]
  }
]);

const queryClient = new QueryClient();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </React.StrictMode>
);

function lazyNamed<Props extends object = Record<string, never>>(loader: () => Promise<unknown>, key: string) {
  return lazy(async () => ({ default: (await loader() as Record<string, React.ComponentType<Props>>)[key] }));
}

