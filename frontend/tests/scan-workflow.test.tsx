import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CopyButton } from "../src/components/ui/CopyButton";
import { StatusBadge } from "../src/components/ui/StatusBadge";
import { displayError } from "../src/utils/errors";
import { NewScanPage } from "../src/pages/NewScanPage";
import { PageDetailPage } from "../src/pages/PageDetailPage";
import { ScanDetailPage } from "../src/pages/ScanDetailPage";
import { ScansPage } from "../src/pages/ScansPage";
import { SiteDetailPage } from "../src/pages/SiteDetailPage";
import { SiteFormPage } from "../src/pages/SiteFormPage";
import { SitesPage } from "../src/pages/SitesPage";
import type { PageList, Scan, Snapshot } from "../src/types/scans";

const api = vi.hoisted(() => ({
  createScan: vi.fn(),
  getScan: vi.fn(),
  listPages: vi.fn(),
  listErrors: vi.fn(),
  getSnapshot: vi.fn(),
  getLinks: vi.fn(),
  getInboundLinks: vi.fn(),
  getHtml: vi.fn(),
  cancelScan: vi.fn(),
  getScanDeletePreview: vi.fn(),
  deleteScan: vi.fn(),
  listScanHistory: vi.fn(),
  listScans: vi.fn(),
  listSites: vi.fn(),
  getSite: vi.fn(),
  createSite: vi.fn(),
  updateSite: vi.fn(),
  deleteSite: vi.fn(),
  createSiteScan: vi.fn(),
  listSiteScans: vi.fn(),
  listSources: vi.fn(),
  createSource: vi.fn(),
  deleteSource: vi.fn(),
  refreshSource: vi.fn(),
  discoverRobots: vi.fn(),
  listSourceEntries: vi.fn(),
  addManualUrls: vi.fn(),
  listInventory: vi.fn(),
  listScanSeeds: vi.fn()
}));

vi.mock("../src/api/client", () => ({
  ...api,
  defaultScope: () => ({
    allowed_host_patterns: [],
    excluded_host_patterns: [],
    included_path_prefixes: ["/"],
    excluded_path_prefixes: ["/wp-admin/", "/wp-login.php"],
    follow_subdomains: false,
    max_pages: 100,
    max_depth: 3,
    respect_robots_txt: false,
    request_timeout_seconds: 10,
    max_html_response_bytes: 2000000,
    concurrent_requests_per_host: 2,
    delay_between_requests_ms: 0,
    user_agent: "ArtsenDesignScanner/0.1",
    drop_query_parameters: ["utm_*", "gclid", "fbclid", "msclkid"],
    allow_private_networks: false,
    max_redirects: 10
  })
}));

beforeEach(() => {
  window.localStorage.clear();
  vi.useRealTimers();
  Object.values(api).forEach((mock) => mock.mockReset());
  api.createScan.mockResolvedValue({ id: 44 });
  api.getScan.mockResolvedValue(scanFixture);
  api.listPages.mockResolvedValue(emptyPageList);
  api.listErrors.mockResolvedValue([]);
  api.getSnapshot.mockResolvedValue(snapshotFixture);
  api.getLinks.mockResolvedValue(linkFixtures);
  api.getInboundLinks.mockResolvedValue(inboundFixture);
  api.getHtml.mockResolvedValue("<html><body><script>window.executed = true</script><h1>Source</h1></body></html>");
  api.cancelScan.mockResolvedValue({ ...scanFixture, status: "cancelled" });
  api.getScanDeletePreview.mockResolvedValue({
    scan_id: 1,
    starting_url: "https://example.com/",
    can_delete: true,
    status: "completed",
    snapshots: 2,
    link_occurrences: 3,
    unique_resources: 2,
    html_blobs_referenced: 2,
    exclusive_html_blobs: 1,
    shared_html_blobs: 1,
    html_blobs_deleted: 1,
    raw_html_bytes_reclaimable: 1200,
    stored_html_bytes_reclaimable: 500,
    reason: null,
    warnings: []
  });
  api.deleteScan.mockResolvedValue({
    deleted_scan_id: 1,
    snapshots_deleted: 2,
    link_occurrences_deleted: 3,
    resources_deleted: 1,
    html_blob_records_deleted: 1,
    html_blob_files_deleted: 1,
    html_blobs_deleted: 1,
    raw_html_bytes_reclaimed: 1200,
    stored_html_bytes_reclaimed: 500,
    warnings: []
  });
  api.listScanHistory.mockResolvedValue({ items: [scanFixture], total: 1, limit: 25, offset: 0 });
  api.listSites.mockResolvedValue({ items: [siteFixture], total: 1, limit: 25, offset: 0 });
  api.getSite.mockResolvedValue(siteDetailFixture);
  api.createSite.mockResolvedValue(siteDetailFixture);
  api.updateSite.mockResolvedValue(siteDetailFixture);
  api.deleteSite.mockResolvedValue({ deleted_site_id: 3 });
  api.createSiteScan.mockResolvedValue({ ...scanFixture, id: 45, website_property_id: 3, website_property_name: "Example Site", website_property_base_url: "https://example.com/" });
  api.listSiteScans.mockResolvedValue({ items: [{ ...scanFixture, website_property_id: 3, website_property_name: "Example Site", website_property_base_url: "https://example.com/" }], total: 1, limit: 25, offset: 0 });
  api.listSources.mockResolvedValue({ items: [sourceFixture], total: 1, limit: 25, offset: 0 });
  api.createSource.mockResolvedValue(sourceFixture);
  api.deleteSource.mockResolvedValue({ deleted_source_id: 4 });
  api.refreshSource.mockResolvedValue(refreshFixture);
  api.discoverRobots.mockResolvedValue(refreshFixture);
  api.listSourceEntries.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
  api.addManualUrls.mockResolvedValue({ source: sourceFixture, items: [], accepted_count: 1, rejected_count: 1, duplicate_count: 0 });
  api.listInventory.mockResolvedValue({ items: [inventoryFixture], total: 1, limit: 50, offset: 0 });
  api.listScanSeeds.mockResolvedValue({ items: [seedFixture], total: 1, limit: 50, offset: 0 });
});

afterEach(() => cleanup());

describe("new scan workflow", () => {
  it("validates and normalizes a bare hostname while showing exact-host scope", async () => {
    renderRoute(<NewScanPage />, "/scans/new");

    fireEvent.change(screen.getByLabelText("Starting URL"), { target: { value: "example.com" } });
    fireEvent.blur(screen.getByLabelText("Starting URL"));

    expect(screen.getByLabelText("Starting URL")).toHaveValue("https://example.com/");
    expect(screen.getByText(/Exact hostname: example.com/i)).toBeInTheDocument();
    expect(screen.getByText(/Subdomains excluded/i)).toBeInTheDocument();
  });

  it("rejects unsupported schemes and invalid numeric values", () => {
    renderRoute(<NewScanPage />, "/scans/new");

    fireEvent.change(screen.getByLabelText("Starting URL"), { target: { value: "ftp://example.com" } });
    fireEvent.change(screen.getByLabelText("Maximum pages"), { target: { value: "0" } });

    expect(screen.getByText(/Only HTTP and HTTPS URLs can be scanned/i)).toBeInTheDocument();
    expect(screen.getByText(/Maximum pages must be between/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start scan" })).toBeDisabled();
  });

  it("preserves list newlines while editing and parses one item per line on submission", async () => {
    renderRoute(<NewScanPage />, "/scans/new");

    fireEvent.change(screen.getByLabelText("Starting URL"), { target: { value: "https://example.com/" } });
    fireEvent.click(screen.getByText("Advanced scope settings"));
    fireEvent.change(screen.getByLabelText("Allowed hosts"), { target: { value: "example.com\nblog.example.com\n" } });

    expect(screen.getByLabelText("Allowed hosts")).toHaveValue("example.com\nblog.example.com\n");
    fireEvent.click(screen.getByRole("button", { name: "Start scan" }));

    await waitFor(() => expect(api.createScan).toHaveBeenCalledTimes(1));
    expect(api.createScan.mock.calls[0][1].allowed_host_patterns).toEqual(["example.com", "blog.example.com"]);
  });

  it("prevents duplicate submission while a scan is being created", async () => {
    let resolveScan: (value: unknown) => void = () => undefined;
    api.createScan.mockReturnValue(new Promise((resolve) => { resolveScan = resolve; }));
    renderRoute(<NewScanPage />, "/scans/new");

    fireEvent.change(screen.getByLabelText("Starting URL"), { target: { value: "https://example.com/" } });
    const button = screen.getByRole("button", { name: "Start scan" });
    fireEvent.click(button);
    fireEvent.click(button);

    await waitFor(() => expect(api.createScan).toHaveBeenCalledTimes(1));
    resolveScan({ id: 44 });
  });
});

describe("scan results workflow", () => {
  it("renders status badges, empty states, and URL-backed page filters", async () => {
    renderRoute(<ScanDetailPage />, "/scans/:scanId", "/scans/1?tab=pages");

    await screen.findByText("No pages recorded");
    expect(screen.getByText("Completed")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Search pages"), { target: { value: "pricing" } });

    await waitFor(() => expect(api.listPages).toHaveBeenLastCalledWith("1", expect.stringContaining("search=pricing")));
  });

  it("keeps page-list pagination offset when search text has not changed", async () => {
    api.listPages.mockResolvedValue({
      items: [pageFixture],
      total: 75,
      limit: 50,
      offset: 0
    });
    renderRoute(<ScanDetailPage />, "/scans/:scanId", "/scans/1?tab=pages");

    fireEvent.click((await screen.findAllByRole("button", { name: "Next" }))[0]);

    await waitFor(() => expect(api.listPages).toHaveBeenLastCalledWith("1", expect.stringContaining("offset=50")));
    await new Promise((resolve) => window.setTimeout(resolve, 450));
    expect(api.listPages).toHaveBeenLastCalledWith("1", expect.stringContaining("offset=50"));
  });

  it("renders a scan status badge with accessible text", () => {
    render(<StatusBadge status="completed_with_errors" />);
    expect(screen.getByText("Completed With Errors")).toBeInTheDocument();
  });
});

describe("saved sites workflow", () => {
  it("renders sites list filters and actions", async () => {
    renderRoute(<SitesPage />, "/sites", "/sites");

    expect(await screen.findByRole("heading", { name: "Saved sites" })).toBeInTheDocument();
    expect(await screen.findByText("Example Site")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Search sites"), { target: { value: "example" } });

    await waitFor(() => expect(api.listSites).toHaveBeenLastCalledWith(expect.stringContaining("search=example")));
  });

  it("creates a site with saved scope and one value per line", async () => {
    renderRoute(<SiteFormPage mode="create" />, "/sites/new", "/sites/new");

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Example Site" } });
    fireEvent.change(screen.getByLabelText("Base URL"), { target: { value: "https://example.com/learn/" } });
    fireEvent.change(screen.getByLabelText("Included path prefixes"), { target: { value: "/learn/\n/docs/" } });
    fireEvent.click(screen.getByRole("button", { name: "Create site" }));

    await waitFor(() => expect(api.createSite).toHaveBeenCalledTimes(1));
    expect(api.createSite.mock.calls[0][0].scope_config.included_path_prefixes).toEqual(["/learn/", "/docs/"]);
  });

  it("blocks saving site settings with invalid numeric scope", async () => {
    renderRoute(<SiteFormPage mode="edit" />, "/sites/:siteId/edit", "/sites/3/edit");

    expect(await screen.findByRole("heading", { name: "Edit site" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Maximum pages"), { target: { value: "" } });

    expect(screen.getByText(/Maximum pages must be between/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save site" })).toBeDisabled();
  });

  it("renders site details and can disable a site", async () => {
    renderRoute(<SiteDetailPage />, "/sites/:siteId", "/sites/3");

    expect(await screen.findByRole("heading", { name: "Example Site" })).toBeInTheDocument();
    expect(screen.getByText("Recent scans")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Disable" }));

    await waitFor(() => expect(api.updateSite).toHaveBeenCalledWith("3", { is_active: false }));
  });

  it("starts a saved-site scan with scan-specific overrides", async () => {
    renderRoute(<NewScanPage />, "/scans/new", "/scans/new?site_id=3");

    expect(await screen.findByLabelText("Site")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Maximum pages"), { target: { value: "7" } });
    fireEvent.click(screen.getByRole("button", { name: "Start scan" }));

    await waitFor(() => expect(api.createSiteScan).toHaveBeenCalledWith("3", expect.objectContaining({ max_pages: 7 }), false, []));
    expect(api.updateSite).not.toHaveBeenCalled();
  });

  it("shows source and inventory tools on site detail", async () => {
    renderRoute(<SiteDetailPage />, "/sites/:siteId", "/sites/3?tab=sources");

    expect(await screen.findByText("Sources")).toBeInTheDocument();
    expect(await screen.findByText("Main sitemap")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(api.refreshSource).toHaveBeenCalledWith("3", "4"));

    fireEvent.click(screen.getByRole("button", { name: /inventory/i }));
    expect(await screen.findByText("https://example.com/a")).toBeInTheDocument();
  });

  it("blocks saved-site scans with invalid scan-specific numeric overrides", async () => {
    renderRoute(<NewScanPage />, "/scans/new", "/scans/new?site_id=3");

    expect(await screen.findByLabelText("Site")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Maximum pages"), { target: { value: "" } });

    expect(screen.getByText(/Maximum pages must be between/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start scan" })).toBeDisabled();
  });
});

describe("scan history workflow", () => {
  it("renders all scans, preserves filters in the URL, and opens delete confirmation", async () => {
    renderRoute(<ScansPage />, "/scans", "/scans");

    expect(await screen.findByRole("heading", { name: "All scans" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Search scans"), { target: { value: "example" } });
    fireEvent.change(screen.getByLabelText("Scan status"), { target: { value: "completed" } });

    await waitFor(() => expect(api.listScanHistory).toHaveBeenLastCalledWith(expect.stringContaining("search=example")));
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));

    expect(await screen.findByRole("dialog", { name: "Delete this scan?" })).toBeInTheDocument();
    expect(screen.getByText(/Estimated storage reclaimed/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Delete scan" }));
    await waitFor(() => expect(api.deleteScan).toHaveBeenCalledWith("1"));
  });
});

describe("page detail workflow", () => {
  it("renders redirect chains as ordered fields", async () => {
    renderRoute(<PageDetailPage />, "/scans/:scanId/pages/:snapshotId", "/scans/1/pages/9");

    expect(await screen.findByText("Redirect chain")).toBeInTheDocument();
    expect(screen.getByText("Hop 1")).toBeInTheDocument();
    expect(screen.getAllByText("https://example.com/new").length).toBeGreaterThan(0);
  });

  it("renders head metadata sections instead of only raw JSON", async () => {
    renderRoute(<PageDetailPage />, "/scans/:scanId/pages/:snapshotId", "/scans/1/pages/9");

    fireEvent.click(await screen.findByRole("tab", { name: "Head" }));

    expect(screen.getByText("Basic metadata")).toBeInTheDocument();
    expect(screen.getByText("Open Graph")).toBeInTheDocument();
    expect(screen.getByText("Structured data")).toBeInTheDocument();
  });

  it("renders individual link occurrences with provenance fields", async () => {
    renderRoute(<PageDetailPage />, "/scans/:scanId/pages/:snapshotId", "/scans/1/pages/9");

    fireEvent.click(await screen.findByRole("tab", { name: /Outgoing links/i }));

    expect((await screen.findAllByText("External")).length).toBeGreaterThan(0);
    expect(screen.getByText("No visible text")).toBeInTheDocument();
    expect(screen.getByText(/aria-label:/)).toBeInTheDocument();
    expect(document.body.textContent).toContain("Download Snagit");
  });

  it("renders inbound link occurrences with scan-specific summary", async () => {
    renderRoute(<PageDetailPage />, "/scans/:scanId/pages/:snapshotId", "/scans/1/pages/9");

    fireEvent.click(await screen.findByRole("tab", { name: /Inbound links/i }));

    expect(await screen.findByText("Inbound link summary")).toBeInTheDocument();
    expect(screen.getByText("Unique source pages")).toBeInTheDocument();
    expect(screen.getByText("Self link")).toBeInTheDocument();
    expect(document.body.textContent).toContain("Source page");
    fireEvent.change(screen.getByLabelText("Search inbound links"), { target: { value: "source" } });
    await waitFor(() => expect(api.getInboundLinks).toHaveBeenLastCalledWith("9", expect.stringContaining("search=source")));
  });

  it("shows raw HTML as escaped text without executing it", async () => {
    renderRoute(<PageDetailPage />, "/scans/:scanId/pages/:snapshotId", "/scans/1/pages/9");

    fireEvent.click(await screen.findByRole("tab", { name: "HTML" }));

    await screen.findByLabelText("Escaped HTML source");
    expect(screen.getByLabelText("Escaped HTML source").textContent).toContain("window.executed = true");
    expect((window as unknown as { executed?: boolean }).executed).toBeUndefined();
  });
});

describe("shared UX utilities", () => {
  it("formats API unavailable errors for users", () => {
    expect(displayError(new TypeError("Failed to fetch")).message).toMatch(/scanner API could not be reached/i);
  });

  it("copies values with feedback", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    render(<CopyButton value="https://example.com/" />);

    fireEvent.click(screen.getByRole("button", { name: "Copy" }));

    await waitFor(() => expect(writeText).toHaveBeenCalledWith("https://example.com/"));
    expect(screen.getByRole("button", { name: "Copy copied" })).toBeInTheDocument();
  });
});

function renderRoute(element: React.ReactElement, path: string, initialEntry = path) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route path={path} element={element} />
          <Route path="*" element={<div />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

const scanFixture: Scan = {
  id: 1,
  website_property_id: null,
  website_property_name: null,
  website_property_base_url: null,
  starting_url: "https://example.com/",
  status: "completed",
  scope_config: {
    allowed_host_patterns: [],
    excluded_host_patterns: [],
    included_path_prefixes: ["/"],
    excluded_path_prefixes: ["/wp-admin/", "/wp-login.php"],
    follow_subdomains: false,
    max_pages: 100,
    max_depth: 3,
    respect_robots_txt: false,
    request_timeout_seconds: 10,
    max_html_response_bytes: 2000000,
    concurrent_requests_per_host: 2,
    delay_between_requests_ms: 0,
    user_agent: "ArtsenDesignScanner/0.1",
    drop_query_parameters: ["utm_*", "gclid", "fbclid", "msclkid"],
    allow_private_networks: false,
    max_redirects: 10
  },
  created_at: "2026-07-30T01:00:00Z",
  started_at: "2026-07-30T01:00:01Z",
  finished_at: "2026-07-30T01:00:03Z",
  discovered_count: 1,
  fetched_count: 1,
  failed_count: 0,
  skipped_count: 0,
  queued_count: 0,
  stop_reason: "max_pages",
  fatal_error_message: null
};

const emptyPageList: PageList = {
  items: [],
  total: 0,
  limit: 50,
  offset: 0
};

const pageFixture = {
  id: 9,
  resource_id: 2,
  requested_url: "https://example.com/page",
  final_url: "https://example.com/page",
  http_status: 200,
  title: "Example page",
  depth: 1,
  content_type: "text/html",
  discovery_source: "https://example.com/",
  inbound_occurrence_count: 1,
  inbound_source_page_count: 1,
  response_time_ms: 50,
  fetch_state: "fetched",
  error_type: null
};

const snapshotFixture: Snapshot = {
  id: 9,
  scan_id: 1,
  resource_id: 2,
  requested_url: "https://example.com/old",
  final_url: "https://example.com/new",
  http_status: 200,
  content_type: "text/html",
  encoding: "utf-8",
  crawl_depth: 1,
  fetched_at: "2026-07-30T01:00:02Z",
  response_time_ms: 123,
  response_headers: {},
  redirect_chain: [{ requested_url: "https://example.com/old", status_code: 301, location: "/new", resolved_url: "https://example.com/new" }],
  html_raw_byte_size: 1200,
  html_stored_byte_size: 500,
  raw_html_sha256: "rawhash",
  head_sha256: "headhash",
  page_title: "Example page",
  html_language: "en",
  meta_description: "Description",
  meta_robots: "index,follow",
  canonical_url: "https://example.com/new",
  parsed_head_json: {
    encoding: "utf-8",
    viewport: "width=device-width, initial-scale=1",
    open_graph: { "og:title": "OG title" },
    twitter: { "twitter:card": "summary" },
    meta: [{ name: "description", content: "Description" }],
    links: [{ rel: "canonical", href: "https://example.com/new" }],
    json_ld: ['{"@context":"https://schema.org","@type":"WebPage"}']
  },
  fetch_state: "fetched",
  error_type: null,
  error_message: null
};

const linkFixtures = [
  {
    id: 1,
    raw_href: "/download",
    resolved_url: "https://example.com/download",
    normalized_target_url: "https://example.com/download",
    target_resource_id: null,
    anchor_text: null,
    title: "Download",
    aria_label: "Download Snagit",
    rel: "nofollow",
    target: "_blank",
    dom_path: "html > body > a",
    in_scope: false,
    scope_decision: "external",
    exclusion_reason: "External host",
    discovered_at: "2026-07-30T01:00:02Z"
  }
];

const inboundFixture = {
  items: [
    {
      ...linkFixtures[0],
      source_snapshot_id: 8,
      source_resource_id: 3,
      source_requested_url: "https://example.com/source",
      source_final_url: "https://example.com/source",
      source_page_title: "Source page",
      source_http_status: 200,
      source_fetch_state: "fetched",
      source_crawl_depth: 0,
      is_self_link: true
    }
  ],
  total: 1,
  limit: 50,
  offset: 0,
  summary: {
    total_occurrences: 1,
    unique_source_pages: 1,
    unique_anchor_texts: 0,
    nofollow_occurrences: 1,
    self_link_occurrences: 1
  }
};

const siteFixture = {
  id: 3,
  name: "Example Site",
  base_url: "https://example.com/",
  normalized_base_url: "https://example.com/",
  description: "A site",
  group_key: "Marketing",
  locale: "en-US",
  platform_key: "WordPress Root",
  ownership_key: "Web Team",
  scope_config: {
    allowed_host_patterns: ["example.com"],
    excluded_host_patterns: [],
    included_path_prefixes: ["/"],
    excluded_path_prefixes: ["/wp-admin/", "/wp-login.php"],
    follow_subdomains: false,
    max_pages: 100,
    max_depth: 3,
    respect_robots_txt: false,
    request_timeout_seconds: 10,
    max_html_response_bytes: 2000000,
    concurrent_requests_per_host: 2,
    delay_between_requests_ms: 0,
    user_agent: "ArtsenDesignScanner/0.1",
    drop_query_parameters: ["utm_*", "gclid", "fbclid", "msclkid"],
    allow_private_networks: false,
    max_redirects: 10
  },
  is_active: true,
  created_at: "2026-07-30T01:00:00Z",
  updated_at: "2026-07-30T01:00:00Z",
  total_scan_count: 1,
  latest_scan_id: 1,
  latest_scan_status: "completed",
  latest_scan_date: "2026-07-30T01:00:00Z",
  latest_scan_discovered_count: 1,
  latest_scan_failed_count: 0
};

const siteDetailFixture = {
  ...siteFixture,
  latest_scan: { ...scanFixture, website_property_id: 3, website_property_name: "Example Site", website_property_base_url: "https://example.com/" },
  recent_scans: [{ ...scanFixture, website_property_id: 3, website_property_name: "Example Site", website_property_base_url: "https://example.com/" }]
};

const sourceFixture = {
  id: 4,
  website_property_id: 3,
  parent_source_id: null,
  root_source_id: null,
  source_type: "sitemap",
  name: "Main sitemap",
  source_url: "https://example.com/sitemap.xml",
  normalized_source_url: "https://example.com/sitemap.xml",
  is_active: true,
  discovery_mode: "configured",
  settings_json: {},
  last_refresh_status: "completed",
  last_refresh_started_at: "2026-07-30T01:00:00Z",
  last_refresh_finished_at: "2026-07-30T01:00:01Z",
  last_successful_refresh_at: "2026-07-30T01:00:01Z",
  last_http_status: 200,
  last_error_type: null,
  last_error_message: null,
  created_at: "2026-07-30T01:00:00Z",
  updated_at: "2026-07-30T01:00:01Z",
  current_entry_count: 2
};

const refreshFixture = {
  id: 5,
  url_source_id: 4,
  status: "completed",
  started_at: "2026-07-30T01:00:00Z",
  finished_at: "2026-07-30T01:00:01Z",
  http_status: 200,
  fetched_url: "https://example.com/sitemap.xml",
  final_url: "https://example.com/sitemap.xml",
  response_bytes: 120,
  content_type: "application/xml",
  discovered_entry_count: 2,
  accepted_entry_count: 2,
  rejected_entry_count: 0,
  child_source_count: 0,
  entries_added: 2,
  entries_updated: 0,
  entries_no_longer_current: 0,
  error_type: null,
  error_message: null,
  warnings_json: []
};

const inventoryFixture = {
  normalized_url: "https://example.com/a",
  resource_id: 2,
  source_count: 2,
  source_types: ["manual", "sitemap"],
  sources: [
    { id: 4, name: "Main sitemap", type: "sitemap", entry_id: 6, raw_url: "https://example.com/a" },
    { id: 7, name: "Manual URLs", type: "manual", entry_id: 8, raw_url: "/a" }
  ],
  scope_decision: "crawlable",
  validation_state: "valid",
  sitemap_lastmod: "2026-01-01",
  latest_scan_status: "completed",
  latest_fetch_date: "2026-07-30T01:00:02Z",
  classification: "source_and_crawl"
};

const seedFixture = {
  id: 9,
  scan_id: 1,
  resource_id: 2,
  normalized_url: "https://example.com/a",
  requested_url: "https://example.com/a",
  depth: 0,
  queue_state: "queued",
  scope_decision: "crawlable",
  exclusion_reason: null,
  created_at: "2026-07-30T01:00:00Z",
  origins: [
    {
      id: 10,
      origin_type: "sitemap",
      url_source_id: 4,
      url_source_entry_id: 6,
      source_refresh_id: 5,
      raw_url: "https://example.com/a",
      metadata_json: {}
    }
  ]
};
