import { expect, test, type Page } from "@playwright/test";

test("mocked scan workflow supports creation, filtering, details, and safe HTML", async ({ page }) => {
  await mockApi(page);

  await page.goto("/scans/new");
  await expect(page.getByRole("heading", { name: "Start a new scan" })).toBeVisible();

  await page.getByLabel("Starting URL").fill("example.com");
  await page.getByLabel("Starting URL").blur();
  await expect(page.getByLabel("Starting URL")).toHaveValue("https://example.com/");
  await expect(page.getByText("Exact hostname: example.com")).toBeVisible();

  await page.getByText("Advanced scope settings").click();
  await page.getByRole("textbox", { name: "Allowed hosts" }).fill("example.com\nblog.example.com");
  await page.getByRole("button", { name: "Start scan" }).click();

  await expect(page).toHaveURL(/\/scans\/1$/);
  await expect(page.getByText("Running")).toBeVisible();
  await expect(page.getByText("Fetched 1 of 3 discovered pages")).toBeVisible();

  await page.reload();
  await expect(page.getByText("Completed").first()).toBeVisible();
  await expect(page.getByRole("tab", { name: /Pages/i })).toBeVisible();

  await page.getByRole("tab", { name: /Pages/i }).click();
  await page.getByLabel("Search pages").fill("pricing");
  await expect(page).toHaveURL(/search=pricing/);
  await expect(page.getByRole("cell", { name: "Pricing", exact: true })).toBeVisible();

  await page.getByText("https://example.com/pricing").click();
  await expect(page.getByText("Page details")).toBeVisible();
  await expect(page.getByText("Redirect chain")).toBeVisible();

  await page.getByRole("tab", { name: "Head" }).click();
  await expect(page.getByText("Basic metadata")).toBeVisible();
  await expect(page.getByText("Open Graph")).toBeVisible();

  await page.getByRole("tab", { name: /Links/i }).click();
  await expect(page.getByRole("table").getByText("External", { exact: true })).toBeVisible();
  await expect(page.getByText("No visible text")).toBeVisible();

  await page.getByRole("tab", { name: "HTML" }).click();
  await expect(page.getByLabel("Escaped HTML source")).toContainText("<script>window.executed = true</script>");
  expect(await page.evaluate(() => (window as unknown as { executed?: boolean }).executed)).toBeUndefined();

  await page.getByRole("link", { name: "Back to page results" }).click();
  await expect(page).toHaveURL(/\/scans\/1\?tab=pages/);
});

async function mockApi(page: Page) {
  let scanStatus: "running" | "completed" = "running";

  await page.route("**/api/scans", async (route) => {
    if (route.request().method() === "POST") {
      await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ ...scan, status: "running" }) });
      return;
    }
    await route.fulfill({ contentType: "application/json", body: JSON.stringify([{ ...scan, status: scanStatus }]) });
  });

  await page.route("**/api/scans/1", async (route) => {
    const body = { ...scan, status: scanStatus };
    scanStatus = "completed";
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
  });

  await page.route("**/api/scans/1/pages**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ items: [pageRow], total: 1, limit: 50, offset: 0 })
    });
  });

  await page.route("**/api/scans/1/errors", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify([]) });
  });

  await page.route("**/api/scans/1/delete-preview", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        scan_id: 1,
        can_delete: true,
        status: "completed",
        snapshots: 1,
        link_occurrences: 1,
        html_blobs_referenced: 1,
        html_blobs_deleted: 1,
        raw_html_bytes_reclaimable: 1200,
        stored_html_bytes_reclaimable: 480,
        reason: null
      })
    });
  });

  await page.route("**/api/snapshots/9", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(snapshot) });
  });

  await page.route("**/api/snapshots/9/links", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(links) });
  });

  await page.route("**/api/snapshots/9/html", async (route) => {
    await route.fulfill({ contentType: "text/plain", body: "<html><body><script>window.executed = true</script><h1>Pricing</h1></body></html>" });
  });
}

const scope = {
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
};

const scan = {
  id: 1,
  starting_url: "https://example.com/",
  status: "running",
  scope_config: scope,
  created_at: "2026-07-30T01:00:00Z",
  started_at: "2026-07-30T01:00:01Z",
  finished_at: null,
  discovered_count: 3,
  fetched_count: 1,
  failed_count: 0,
  skipped_count: 0,
  queued_count: 2,
  stop_reason: null,
  fatal_error_message: null
};

const pageRow = {
  id: 9,
  resource_id: 2,
  requested_url: "https://example.com/pricing",
  final_url: "https://example.com/pricing",
  http_status: 200,
  title: "Pricing",
  depth: 1,
  content_type: "text/html",
  discovery_source: "https://example.com/",
  inbound_occurrence_count: 1,
  inbound_source_page_count: 1,
  response_time_ms: 87,
  fetch_state: "fetched",
  error_type: null
};

const snapshot = {
  id: 9,
  scan_id: 1,
  resource_id: 2,
  requested_url: "https://example.com/pricing-old",
  final_url: "https://example.com/pricing",
  http_status: 200,
  content_type: "text/html",
  encoding: "utf-8",
  crawl_depth: 1,
  fetched_at: "2026-07-30T01:00:02Z",
  response_time_ms: 87,
  response_headers: {},
  redirect_chain: [{ requested_url: "https://example.com/pricing-old", status_code: 301, location: "/pricing", resolved_url: "https://example.com/pricing" }],
  html_raw_byte_size: 1200,
  html_stored_byte_size: 480,
  raw_html_sha256: "rawhash",
  head_sha256: "headhash",
  page_title: "Pricing",
  html_language: "en",
  meta_description: "Pricing page",
  meta_robots: "index,follow",
  canonical_url: "https://example.com/pricing",
  parsed_head_json: {
    encoding: "utf-8",
    viewport: "width=device-width, initial-scale=1",
    open_graph: { "og:title": "Pricing" },
    twitter: { "twitter:card": "summary" },
    meta: [{ name: "description", content: "Pricing page" }],
    links: [{ rel: "canonical", href: "https://example.com/pricing" }],
    json_ld: ['{"@context":"https://schema.org","@type":"WebPage"}']
  },
  fetch_state: "fetched",
  error_type: null,
  error_message: null
};

const links = [
  {
    id: 1,
    raw_href: "https://external.example/download",
    resolved_url: "https://external.example/download",
    normalized_target_url: "https://external.example/download",
    target_resource_id: null,
    anchor_text: null,
    title: null,
    aria_label: "Download",
    rel: "nofollow",
    target: "_blank",
    dom_path: "html > body > a",
    in_scope: false,
    scope_decision: "external",
    exclusion_reason: "External host"
  }
];
