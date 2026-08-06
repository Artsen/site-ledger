import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";
import { Navigate, RouterProvider, createBrowserRouter } from "react-router-dom";

import { AppShell } from "./components/AppShell";
import { PageDetailPage } from "./pages/PageDetailPage";
import { PersistentPageDetailPage } from "./pages/PersistentPageDetailPage";
import { ResourceDetailPage } from "./pages/ResourceDetailPage";
import { ScanDetailPage } from "./pages/ScanDetailPage";
import { ScansPage } from "./pages/ScansPage";
import { SiteDetailPage } from "./pages/SiteDetailPage";
import { SiteFormPage } from "./pages/SiteFormPage";
import { SitesPage } from "./pages/SitesPage";
import { NewScanPage } from "./pages/NewScanPage";
import "./styles/index.css";

const router = createBrowserRouter([
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/scans/new" replace /> },
      { path: "sites", element: <SitesPage /> },
      { path: "sites/new", element: <SiteFormPage mode="create" /> },
      { path: "sites/:siteId", element: <SiteDetailPage /> },
      { path: "sites/:siteId/pages/:resourceId", element: <PersistentPageDetailPage /> },
      { path: "sites/:siteId/resources/:resourceId", element: <ResourceDetailPage scope="site" /> },
      { path: "sites/:siteId/edit", element: <SiteFormPage mode="edit" /> },
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

