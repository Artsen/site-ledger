import { expect, test, type Page } from "@playwright/test";

test("product workspace shell is stable across desktop, tablet, and mobile", async ({ page }) => {
  await mockApi(page);
  const screenshotDir = process.env.WORKSPACE_SCREENSHOTS_DIR;

  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto("/sites/3/pages?search=pricing");
  await expect(page.getByRole("navigation", { name: "Site workspace" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Pages", exact: true })).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("combobox", { name: "Current Site" })).toHaveValue("3");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  if (screenshotDir) await page.screenshot({ path: `${screenshotDir}/workspace-desktop.png`, fullPage: true });

  await page.getByRole("button", { name: "Collapse sidebar" }).click();
  await expect(page.getByRole("button", { name: "Expand sidebar" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("button", { name: "Expand sidebar" })).toBeVisible();
  await page.getByRole("button", { name: "Expand sidebar" }).click();

  await page.setViewportSize({ width: 768, height: 1024 });
  await expect(page.getByRole("button", { name: "Open navigation" })).toBeVisible();
  await page.getByRole("button", { name: "Open navigation" }).click();
  await expect(page.getByRole("complementary", { name: "Workspace navigation" }).first()).toBeVisible();
  if (screenshotDir) await page.screenshot({ path: `${screenshotDir}/workspace-tablet.png`, fullPage: true });
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "Open navigation" })).toBeFocused();

  await page.setViewportSize({ width: 375, height: 812 });
  await page.getByRole("button", { name: "Open navigation" }).click();
  await expect(page.getByRole("link", { name: "Site Settings" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  if (screenshotDir) await page.screenshot({ path: `${screenshotDir}/workspace-mobile.png`, fullPage: true });
});

test("Performance workspace is responsive and safe without provider configuration", async ({ page }) => {
  await mockApi(page);
  for (const viewport of [
    { width: 375, height: 812 },
    { width: 768, height: 1024 },
    { width: 1024, height: 768 },
    { width: 1440, height: 960 },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto("/sites/3/performance");
    await expect(page.getByRole("heading", { name: "Performance", exact: true })).toBeVisible();
    await expect(page.getByText("Google providers are not configured.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Collect Performance" })).toBeDisabled();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  }
  await page.setViewportSize({ width: 375, height: 812 });
  await page.getByRole("button", { name: "Open navigation" }).click();
  await expect(page.getByRole("link", { name: "Performance" })).toHaveAttribute("aria-current", "page");
});

test("Site Ledger workflow supports creation, filtering, details, inbound links, and deletion", async ({
  page,
}) => {
  test.setTimeout(90_000);
  await mockApi(page);

  await page.goto("/");
  await expect(page).toHaveTitle("New Scan | Site Ledger");
  await expect(page.getByText("Site Ledger", { exact: true }).last()).toBeVisible();
  await expect(
    page.getByText("A historical record of your website."),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Site Ledger Sites" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Sites", exact: true }).click();
  await expect(page).toHaveURL(/\/sites$/);
  await expect(page).toHaveTitle("Sites | Site Ledger");
  await page.getByRole("link", { name: "All Scans", exact: true }).click();
  await expect(page).toHaveURL(/\/scans$/);
  await expect(page).toHaveTitle("All Scans | Site Ledger");
  await page.getByRole("link", { name: "New Scan", exact: true }).click();
  await expect(page).toHaveURL(/\/scans\/new$/);

  await page.goto("/sites");
  await expect(
    page.getByRole("heading", { name: "Saved sites" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Create site" }).click();
  await page.getByLabel("Name").fill("Example Site");
  await page.getByLabel("Base URL").fill("https://example.com/learn/");
  await page.getByLabel("Included path prefixes").fill("/learn/");
  await page.getByRole("button", { name: "Create site" }).click();
  await expect(page).toHaveURL(/\/sites\/3$/);
  await expect(
    page.getByRole("heading", { name: "Example Site" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Site Settings" }).click();
  await expect(page).toHaveURL(/\/sites\/3\/settings$/);
  await page.getByLabel("Maximum pages").fill("150");
  await page.getByRole("button", { name: "Save site" }).click();
  await expect(page).toHaveURL(/\/sites\/3$/);
  await page.getByRole("link", { name: "Run scan" }).click();
  await expect(page).toHaveURL(/\/scans\/new\?site_id=3/);
  await page.getByLabel("Maximum pages").fill("12");
  await page.getByRole("button", { name: "Start scan" }).click();
  await expect(page).toHaveURL(/\/scans\/2$/);
  await expect(page.getByText("Example Site").first()).toBeVisible();

  await page.goto("/scans/new");
  await expect(
    page.getByRole("heading", { name: "Start a new scan" }),
  ).toBeVisible();

  await page.getByLabel("Starting URL").fill("example.com");
  await page.getByLabel("Starting URL").blur();
  await expect(page.getByLabel("Starting URL")).toHaveValue(
    "https://example.com/",
  );
  await expect(page.getByText("Exact hostname: example.com")).toBeVisible();

  await page.getByText("Advanced scope settings").click();
  await page
    .getByRole("textbox", { name: "Allowed hosts" })
    .fill("example.com\nblog.example.com");
  await page.getByRole("button", { name: "Start scan" }).click();

  await expect(page).toHaveURL(/\/scans\/1$/);
  await expect(page.getByText("Running").first()).toBeVisible();
  await expect(page.getByText("Fetched 1 of 3 discovered pages")).toBeVisible();

  await page.reload();
  await expect(page.getByText("Completed").first()).toBeVisible();
  await expect(page.getByRole("tab", { name: /Pages/i })).toBeVisible();

  await page.getByRole("tab", { name: /Errors/i }).click();
  await expect(page.getByText("guide.pdf")).toHaveCount(0);
  await expect(page.getByText("hero.webp")).toHaveCount(0);

  await page.getByRole("tab", { name: /Resources/i }).click();
  await expect(page.getByText("Documents", { exact: true })).toBeVisible();
  await expect(page.getByText("Images", { exact: true })).toBeVisible();
  await expect(page.getByText("Scripts", { exact: true })).toBeVisible();
  await expect(page.getByText("Stylesheets", { exact: true })).toBeVisible();
  await expect(page.getByText("Fonts", { exact: true })).toBeVisible();
  await page.getByLabel("Resource kind").selectOption("document");
  await expect(page).toHaveURL(/resource_kind=document/);
  await page.getByText("https://example.com/guide.pdf").click();
  await expect(page.getByText("application/pdf")).toBeVisible();
  await page.getByRole("tab", { name: /Used by Pages/i }).click();
  await expect(page.getByRole("link", { name: "Pricing" })).toBeVisible();

  await page.goto("/scans/1?tab=rendered");
  await page.getByLabel("Rendered capture state").selectOption("completed_with_warnings");
  await expect(page).toHaveURL(/render_state=completed_with_warnings/);
  await page.getByRole("link", { name: /Open rendered evidence/ }).click();
  await expect(page).toHaveURL(/\/scans\/1\/pages\/9\?tab=rendered/);

  await page.goto("/scans/1");

  await page.getByRole("tab", { name: /Graph/i }).click();
  await expect(page.getByText("Website topology graph")).toBeVisible();
  await expect(page.getByText(/2 of 2 nodes/)).toBeVisible();
  await page.getByLabel("Graph mode").selectOption("2d");
  await page.getByLabel("Search graph nodes").fill("pricing");
  await page
    .getByRole("button", { name: /Pricing/ })
    .first()
    .click();
  await expect(page.getByText("Selected page")).toBeVisible();
  await expect(page.getByRole("link", { name: "Open details" })).toBeVisible();
  await page.getByRole("button", { name: "Neighborhood", exact: true }).click();
  await expect(page).toHaveURL(/focus_snapshot_id=9/);
  await page
    .getByRole("button", { name: /2 links/ })
    .first()
    .click();
  await expect(page.getByText("Selected edge")).toBeVisible();
  await expect(page.getByText("Pricing link")).toBeVisible();
  await page.getByLabel("Graph maximum depth").fill("1");
  await expect(page).toHaveURL(/max_depth=1/);
  await page.getByRole("button", { name: "Presentation" }).click();
  await expect(
    page.getByRole("button", { name: "Exit presentation" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Exit presentation" }).click();

  await page.getByRole("tab", { name: /Pages/i }).click();
  await page.getByLabel("Search pages").fill("pricing");
  await expect(page).toHaveURL(/search=pricing/);
  await expect(
    page.getByRole("cell", { name: "Pricing", exact: true }),
  ).toBeVisible();

  await page.getByText("https://example.com/pricing").click();
  await expect(page.getByRole("heading", { name: "Pricing" })).toBeVisible();
  await expect(page.getByText("Redirect chain")).toBeVisible();

  await page.getByRole("tab", { name: "Head" }).click();
  await expect(page.getByText("Basic metadata")).toBeVisible();
  await expect(page.getByText("Open Graph")).toBeVisible();

  await page.getByRole("tab", { name: /Outgoing links/i }).click();
  await expect(
    page.getByRole("table").getByText("External", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("No visible text")).toBeVisible();

  await page.getByRole("tab", { name: /Inbound links/i }).click();
  await expect(page.getByText("Inbound link summary")).toBeVisible();
  await expect(page.getByRole("link", { name: /Source page/ })).toBeVisible();
  await page.getByLabel("Search inbound links").fill("source");
  await expect(page).toHaveURL(/inbound_search=source/);

  await page.getByRole("tab", { name: "HTML" }).click();
  await expect(page.getByLabel("Escaped HTML source")).toContainText(
    "<script>window.executed = true</script>",
  );
  expect(
    await page.evaluate(
      () => (window as unknown as { executed?: boolean }).executed,
    ),
  ).toBeUndefined();

  await page.getByRole("link", { name: "Back to Scan Pages" }).click();
  await expect(page).toHaveURL(/\/scans\/1\?tab=pages/);

  await page.getByRole("link", { name: "All Scans" }).click();
  await page.getByLabel("Search scans").fill("example");
  await page.getByLabel("Scan status").selectOption("completed");
  await expect(page).toHaveURL(/search=example/);
  await page.getByRole("button", { name: "Delete" }).click();
  await expect(
    page.getByRole("dialog", { name: "Delete this scan?" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Delete scan" }).click();
  await expect(page.getByText("Scan deleted.")).toBeVisible();
});

test("persistent Page workspace supports organization, evidence, links, and notes", async ({
  page,
}) => {
  await mockApi(page);

  await page.goto("/sites/3/pages/2");
  await expect(page.getByRole("heading", { name: "Pricing" })).toBeVisible();
  await expect(
    page.getByText("Needs Review", { exact: true }).first(),
  ).toBeVisible();
  await expect(
    page.getByText("Web team", { exact: true }).first(),
  ).toBeVisible();

  await page.getByRole("button", { name: "Edit organization" }).click();
  await expect(page.getByLabel("Editorial")).toBeChecked();
  await expect(page.getByText("Retired category (Archived)")).toHaveCount(0);
  await page.getByLabel("Owner").fill("Content team");
  await page.getByRole("button", { name: "Save organization" }).click();

  await page.getByRole("tab", { name: /Scans/ }).click();
  await expect(page).toHaveURL(/tab=scans/);
  await expect(
    page.getByRole("link", { name: "Open Observation" }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: /Retry Page/i })).toHaveCount(
    0,
  );

  await page.getByRole("tab", { name: "Links" }).click();
  await expect(page.getByText("Main content", { exact: true })).toBeVisible();
  await expect(page.getByText("Crawlable", { exact: true })).toBeVisible();

  await page.getByRole("tab", { name: /Notes/ }).click();
  await page.getByLabel(/Add note/).fill("Review pricing copy\nwith legal.");
  await page.getByRole("button", { name: "Add note" }).click();
  await expect(
    page.getByText("Review pricing copy\nwith legal."),
  ).toBeVisible();
  await page.getByRole("button", { name: "Pin", exact: true }).click();
  await expect(page.getByText(/Pinned note/)).toBeVisible();
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  await page.getByLabel("Edit note").fill("Pricing copy approved.");
  await page.getByRole("button", { name: "Save note" }).click();
  await expect(page.getByText("Pricing copy approved.")).toBeVisible();
  await page.getByLabel("Search notes").fill("pricing");
  await expect(page).toHaveURL(/notes_search=pricing/);
});

test("structured content is inspectable on exact observations and persistent Pages", async ({
  page,
}) => {
  await mockApi(page);
  const content = structuredContentFixture();
  await page.route("**/api/snapshots/9/structured-content?*", async (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify(content) }),
  );
  await page.route("**/api/sites/3/pages/2/structured-content?*", async (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify(content) }),
  );

  await page.goto("/scans/1/pages/9?tab=content");
  await expect(page.getByRole("heading", { name: "Structured Page content" })).toBeVisible();
  await expect(page.getByText("Page title", { exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: /Details/ }).click();
  await expect(page.getByText(/window\.structuredExecuted/)).toBeVisible();
  expect(
    await page.evaluate(
      () => (window as unknown as { structuredExecuted?: boolean }).structuredExecuted,
    ),
  ).toBeUndefined();
  await page.getByRole("button", { name: "Collapse Page title" }).click();
  await expect(page.getByRole("button", { name: /Details/ })).toHaveCount(0);

  await page.goto("/sites/3/pages/2?tab=content");
  await expect(page.getByText("Scan 1, observation 9")).toBeVisible();
  await expect(page.getByText("structured-content-v1 / default-v1")).toBeVisible();
});

test("numbered pagination stays URL-backed and isolated between Scan tabs", async ({ page }) => {
  await mockApi(page);
  await page.route("**/api/scans/1/pages**", async (route) => {
    const url = new URL(route.request().url());
    const limit = Number(url.searchParams.get("limit") ?? 50);
    const offset = Number(url.searchParams.get("offset") ?? 0);
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ items: [{ ...pageRow, id: offset + 1, requested_url: `https://example.com/page-${offset + 1}` }], total: 125, limit, offset }),
    });
  });
  await page.route("**/api/scans/1/resources**", async (route) => {
    if (new URL(route.request().url()).pathname !== "/api/scans/1/resources") return route.fallback();
    const url = new URL(route.request().url());
    const limit = Number(url.searchParams.get("limit") ?? 50);
    const offset = Number(url.searchParams.get("offset") ?? 0);
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ items: [resourceItem({ resource_id: offset + 21 })], total: 100, limit, offset }) });
  });

  await page.goto("/scans/1?tab=pages&resources_limit=25&resources_offset=25");
  await expect(page.getByRole("navigation", { name: "Pages pagination" })).toHaveCount(2);
  await page.getByRole("button", { name: "Go to Page 3" }).first().click();
  await expect(page).toHaveURL(/pages_offset=100/);
  await expect(page.getByText("Showing 101-125 of 125 Pages").first()).toBeVisible();

  await page.getByLabel("Page rows per page").first().selectOption("100");
  await expect(page).toHaveURL(/pages_limit=100/);
  await expect(page).toHaveURL(/pages_offset=0/);
  await page.getByRole("button", { name: "Last" }).first().click();
  await expect(page).toHaveURL(/pages_offset=100/);
  await page.getByRole("button", { name: "First" }).first().click();
  await expect(page).toHaveURL(/pages_offset=0/);

  await page.getByRole("tab", { name: /Resources/i }).click();
  await expect(page).not.toHaveURL(/resources_limit=/);
  await expect(page).not.toHaveURL(/resources_offset=/);
  await expect(page.getByText("Showing 1-50 of 100 Resources").first()).toBeVisible();
  await page.getByRole("tab", { name: /Rendered/i }).click();
  await expect(page).not.toHaveURL(/rendered_offset=25/);
  await page.goBack();
  await expect(page).toHaveURL(/tab=resources/);
  await page.goForward();
  await expect(page).toHaveURL(/tab=rendered/);
});

test("terminal Scan projections switch from fallback and preserve ready results during rebuild", async ({ page }) => {
  await mockApi(page);
  let state: "missing" | "building" | "ready" | "failed" = "missing";
  let currentBuild: number | null = null;
  let pageRequests = 0;
  await page.route("**/api/scans/1/projection**", async (route) => {
    const method = route.request().method();
    const pathname = new URL(route.request().url()).pathname;
    if (method === "POST") {
      state = "building";
      await route.fulfill({ status: 202, contentType: "application/json", body: JSON.stringify({ id: currentBuild ? 10 : 9, scan_id: 1, status: "queued" }) });
      return;
    }
    if (pathname !== "/api/scans/1/projection") return route.fallback();
    const active = state === "building" ? { id: currentBuild ? 10 : 9, status: "building", error_message: null } : null;
    const failed = state === "failed" ? { id: 10, status: "failed", error_message: "Synthetic rebuild failure" } : null;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        scan_id: 1,
        scan_status: "completed",
        expected_version: "scan-projection-v1",
        projection_source: currentBuild ? "materialized" : "dynamic",
        projection_status: state,
        current_build: currentBuild ? { id: currentBuild, status: "ready" } : null,
        active_build: active,
        latest_build: failed ?? active ?? (currentBuild ? { id: currentBuild, status: "ready" } : null),
        can_build: state === "missing" || (state === "failed" && !currentBuild),
        can_rebuild: Boolean(currentBuild && state !== "building"),
      }),
    });
  });
  await page.route("**/api/scans/1/pages**", async (route) => {
    pageRequests += 1;
    const url = new URL(route.request().url());
    const limit = Number(url.searchParams.get("limit") ?? 50);
    const offset = Number(url.searchParams.get("offset") ?? 0);
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ items: [{ ...pageRow, id: offset + 1 }], total: 125, limit, offset }) });
  });

  await page.goto("/scans/1?tab=pages");
  await expect(page.getByText("Using current evidence while optimized results are prepared")).toBeVisible();
  await expect(page.getByRole("cell", { name: "Pricing", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Prepare results" }).click();
  await expect(page.getByText("Building optimized results")).toBeVisible();

  state = "ready";
  currentBuild = 9;
  await page.reload();
  await expect(page.getByText("Optimized results ready")).toBeVisible();
  await page.getByRole("button", { name: "Go to Page 2" }).first().click();
  await expect(page).toHaveURL(/pages_offset=50/);
  const requestsBeforeFocus = pageRequests;
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await page.waitForTimeout(300);
  expect(pageRequests).toBe(requestsBeforeFocus);

  await page.getByRole("tab", { name: /Resources/i }).click();
  await page.getByLabel("Resource kind").selectOption("document");
  await expect(page).toHaveURL(/resource_kind=document/);
  await page.goto("/scans/1?tab=graph&selected_edge=8-2");
  await expect(page.getByText("Pricing link")).toBeVisible();
  await expect(page.getByText("Selected edge")).toBeVisible();

  await page.getByRole("button", { name: "Rebuild results" }).click();
  await expect(page.getByText("Building optimized results")).toBeVisible();
  await expect(page.getByText("Website topology graph")).toBeVisible();
  state = "failed";
  await page.reload();
  await expect(page.getByText("Optimized results failed; using current evidence")).toBeVisible();
  await expect(page.getByText("Synthetic rebuild failure")).toBeVisible();
  await expect(page.getByText("Website topology graph")).toBeVisible();
});

test("saved-Site observations link to their exact Page workspace while ad hoc observations do not", async ({ page }) => {
  await mockApi(page);
  await page.route("**/api/snapshots/9", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        ...snapshot,
        scan_id: 2,
        website_property_id: 3,
        website_property_name: "Example Site",
        site_page_id: 12,
        has_persistent_page: true,
        is_html_page: true,
      }),
    });
  });
  await page.route("**/api/snapshots/10", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        ...snapshot,
        id: 10,
        scan_id: 1,
        website_property_id: null,
        website_property_name: null,
        site_page_id: null,
        has_persistent_page: false,
        is_html_page: true,
      }),
    });
  });

  await page.goto("/scans/2/pages/9");
  const workspaceAction = page.getByRole("link", { name: "Open Page workspace for Pricing" });
  await expect(workspaceAction).toBeVisible();
  await expect(workspaceAction).toHaveAttribute("href", "/sites/3/pages/2");
  await page.getByRole("tab", { name: "Rendered" }).click();
  await expect(workspaceAction).toBeVisible();
  await workspaceAction.click();
  await expect(page).toHaveURL(/\/sites\/3\/pages\/2$/);
  await expect(page.getByRole("heading", { name: "Pricing" })).toBeVisible();

  await page.goBack();
  await expect(page).toHaveURL(/\/scans\/2\/pages\/9\?tab=rendered/);
  await page.goto("/scans/1/pages/10");
  await expect(page.getByText(/ad hoc Scan and has no Site-scoped Page workspace/)).toBeVisible();
  await expect(page.getByRole("link", { name: /Open Page workspace/ })).toHaveCount(0);
});

test("AI Document Sources preserve nested evidence, provenance, history, and safe deletion", async ({ page }) => {
  test.setTimeout(90_000);
  await mockApi(page);
  let sourceAdded = false;
  const aiSource = { id: 7, website_property_id: 3, site_name: "Example Site", name: "llms.txt", entry_url: "https://example.com/llms.txt", discovery_mode: "bounded_discovery", is_active: true, settings: { request_timeout_seconds: 10, max_attempts: 2, max_nesting_depth: 5, max_index_documents: 100, max_total_documents: 1000, max_references_per_document: 10000, max_individual_document_bytes: 5000000, max_total_retained_bytes: 100000000, max_total_network_bytes: 250000000, follow_external_documents: false, save_declared_documents: true }, last_refresh_status: "completed_with_errors", last_successful_refresh_at: "2026-08-06T12:00:00Z", current_entry_count: 1, latest_refresh_id: 11, latest_source_refresh_id: 20, document_count: 3, reference_count: 5, warning_count: 1, retained_bytes: 2048 };
  const savedDocument = { id: 21, source_id: 7, refresh_id: 11, resource_id: 40, requested_url: "https://example.com/llms.txt", final_url: "https://example.com/llms.txt", parent_depth_min: 0, document_role: "root_index", document_kind: "llms_index", classification_rule: "filename_llms_txt", fetch_state: "saved", http_status: 200, normalized_mime_type: "text/plain", encoding: "utf-8", response_headers: {}, redirect_chain: [], fetched_at: "2026-08-06T12:00:00Z", response_time_ms: 20, network_bytes_transferred: 2048, raw_sha256: "a".repeat(64), parsed_title: "Example docs", parsed_summary: "Summary", parse_state: "parsed", parse_version: "ai-document-parser-v1", parse_warnings_json: [], warning_count: 0, change_state: "changed", error_type: null, error_message: null, raw_byte_size: 2048, stored_byte_size: 700, parent_count: 2 };
  const markdownDocument = { ...savedDocument, id: 23, resource_id: 43, requested_url: "https://example.com/guide.md", final_url: "https://example.com/guide.md", parent_depth_min: 1, document_role: "declared_document", document_kind: "markdown_document", classification_rule: "mime_markdown", parsed_title: "Guide" };

  await page.route("**/api/sites/3/sources?*", async (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify({ items: sourceAdded ? [{ id: 7, website_property_id: 3, parent_source_id: null, root_source_id: null, source_type: "ai_document", name: "llms.txt", source_url: "https://example.com/llms.txt", normalized_source_url: "https://example.com/llms.txt", is_active: true, discovery_mode: "bounded_discovery", settings_json: aiSource.settings, last_refresh_status: "completed", last_refresh_started_at: null, last_refresh_finished_at: null, last_successful_refresh_at: null, last_http_status: 200, last_error_type: null, last_error_message: null, created_at: "2026-08-06T12:00:00Z", updated_at: "2026-08-06T12:00:00Z", current_entry_count: 1 }] : [], total: sourceAdded ? 1 : 0, limit: 100, offset: 0 }) }));
  await page.route("**/api/sites/3/ai-document-sources/discover", async (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify({ candidates: [{ url: "https://example.com/llms.txt", discovery_method: "conventional_root", relation: "llms-txt", status: "found", http_status: 200, message: null, already_configured: false }, { url: "https://example.com/docs/llms.txt", discovery_method: "http_link_header", relation: "llms-txt", status: "found", http_status: 200, message: null, already_configured: false }] }) }));
  await page.route("**/api/sites/3/ai-document-sources", async (route) => { sourceAdded = true; await route.fulfill({ contentType: "application/json", body: JSON.stringify(aiSource) }); });
  await page.route("**/api/sites/3/sources/7/refresh", async (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify({ id: 20, status: "queued" }) }));
  await page.route("**/api/ai-document-sources/7", async (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify(aiSource) }));
  await page.route("**/api/ai-document-sources/7/refreshes/11/tree", async (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify({ items: [{ snapshot: savedDocument, parent_count: 2, cycle: false }, { snapshot: { ...savedDocument, id: 22, requested_url: "https://example.com/docs/llms.txt", final_url: "https://example.com/docs/llms.txt", parent_depth_min: 1, document_kind: "llms_index", document_role: "nested_index", parent_count: 1 }, parent_count: 1, cycle: true }] }) }));
  await page.route("**/api/ai-document-sources/7/refreshes/11/documents?*", async (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify({ items: [markdownDocument], total: 1, limit: 50, offset: 0 }) }));
  await page.route("**/api/ai-document-sources/7/refreshes/11/references?*", async (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify({ items: [{ id: 1, parent_snapshot_id: 21, target_resource_id: 41, child_snapshot_id: null, position: 0, section_title: "Optional", label: "Guide", description: "Read it", raw_url: "/guide", resolved_url: "https://example.com/guide", normalized_target_url: "https://example.com/guide", optional: true, inferred_role: "declared_document", inferred_kind: "html_page_reference", classification_rule: "parent_reference", in_scope: true, scope_decision: "crawlable", exclusion_reason: null, discovery_depth: 1, forms_cycle: false, inventory_entry_id: 8 }, { id: 2, parent_snapshot_id: 21, target_resource_id: 42, child_snapshot_id: null, position: 1, section_title: "External", label: "Outside", description: null, raw_url: "https://outside.example/doc", resolved_url: "https://outside.example/doc", normalized_target_url: "https://outside.example/doc", optional: false, inferred_role: "declared_document", inferred_kind: "external_reference", classification_rule: "parent_reference", in_scope: false, scope_decision: "external", exclusion_reason: "outside scope", discovery_depth: 1, forms_cycle: false, inventory_entry_id: null }], total: 2, limit: 50, offset: 0 }) }));
  await page.route("**/api/ai-document-sources/7/refreshes/11/validation", async (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify([{ id: 1, snapshot_id: 22, reference_id: 2, severity: "warning", code: "circular_index_reference", message: "Circular index reference", data_json: {} }]) }));
  await page.route("**/api/ai-document-sources/7/refreshes?*", async (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify({ items: [0, 1].map((index) => ({ id: 11 - index, source_refresh_id: 20 - index, status: "completed", configuration_json: aiSource.settings, root_candidate_count: 1, document_discovered_count: 3, document_fetched_count: 3, document_saved_count: 3, document_unchanged_count: index ? 0 : 2, document_changed_count: index ? 3 : 1, document_failed_count: 0, document_skipped_count: 0, reference_count: 5, cycle_count: 1, total_network_bytes: 3000, total_retained_bytes: 2048, stop_reason: null, fatal_error_message: null, created_at: `2026-08-0${6 - index}T12:00:00Z` })), total: 2, limit: 50, offset: 0 }) }));
  await page.route("**/api/ai-document-snapshots/23", async (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify(markdownDocument) }));
  await page.route("**/api/ai-document-snapshots/23/content", async (route) => route.fulfill({ contentType: "text/plain", body: "# Guide\n\nExact retained content." }));
  await page.route("**/api/ai-document-sources/7/deletion-preview", async (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify({ refresh_count: 2, snapshot_count: 6, reference_count: 10, current_inventory_origin_count: 1, unique_blob_count: 3, shared_blob_count: 1, exclusive_blob_count: 2, reclaimable_storage_bytes: 1400 }) }));
  await page.route("**/api/ai-document-sources/7", async (route) => { if (route.request().method() === "DELETE") { sourceAdded = false; await route.fulfill({ contentType: "application/json", body: JSON.stringify({ deleted_source_id: 7 }) }); } else await route.fallback(); });

  await page.goto("/sites/3/ai-documents");
  await page.getByRole("button", { name: "Discover AI Document Sources" }).click();
  await expect(page.getByText("https://example.com/llms.txt")).toBeVisible();
  await expect(page.getByText("https://example.com/docs/llms.txt")).toBeVisible();
  await page.getByText("https://example.com/docs/llms.txt").locator("xpath=ancestor::label").getByRole("checkbox").uncheck();
  await page.getByRole("button", { name: "Add selected Sources" }).click();
  await page.getByRole("link", { name: "Open Source" }).click();
  await expect(page.getByRole("heading", { name: "llms.txt" })).toBeVisible();
  await page.getByRole("button", { name: "Refresh" }).click();
  await page.getByRole("tab", { name: "Tree" }).click();
  await expect(page.getByText("https://example.com/docs/llms.txt")).toBeVisible();
  await expect(page.getByText("2 parents")).toBeVisible();
  await expect(page.getByText("Cycle")).toBeVisible();
  await page.getByRole("tab", { name: "Files" }).click();
  await page.getByLabel("Document kind").selectOption("markdown_document");
  await page.getByRole("link", { name: "Open", exact: true }).click();
  await page.getByRole("button", { name: "Load saved content" }).click();
  await expect(page.getByText(/Exact retained content/)).toBeVisible();
  await page.getByRole("button", { name: "Copy content" }).click();
  await page.goto("/sites/3/ai-documents/7?tab=declared");
  await expect(page.getByText("Current origin")).toBeVisible();
  await expect(page.getByText("Reference only")).toBeVisible();
  await page.getByRole("tab", { name: "Validation" }).click();
  await expect(page.getByText(/llms-full.txt is optional/)).toBeVisible();
  await page.getByRole("tab", { name: "History" }).click();
  await expect(page.getByText("Showing 1-2 of 2 refreshes").first()).toBeVisible();
  await expect(page.getByText("2").first()).toBeVisible();
  await page.getByRole("tab", { name: "Settings" }).click();
  const acceptedDeletion = new Promise<void>((resolve) => page.once("dialog", async (dialog) => { await dialog.accept(); resolve(); }));
  await page.getByRole("button", { name: "Preview and delete" }).click();
  await acceptedDeletion;
  await expect(page).toHaveURL(/\/sites\/3\/ai-documents/);
  await page.goto("/scans/1");
  await expect(page.getByRole("tab", { name: /Pages/i })).toBeVisible();
});

test("Site timezone and automatic Category Rule workflow", async ({ page }) => {
  await mockApi(page);
  await page.route("**/api/sites/3/category-rules", async (route) => {
    if (route.request().method() === "POST") {
      const payload = await route.request().postDataJSON();
      await route.fulfill({ contentType: "application/json", status: 201, body: JSON.stringify({ id: 31, website_property_id: 3, category_name: "Editorial", current_revision_number: 1, current_match_count: 2, current_excluded_count: 0, last_evaluated_at: null, created_at: "2026-08-07T02:23:00Z", updated_at: "2026-08-07T02:23:00Z", ...payload, is_active: true }) });
      return;
    }
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ items: [], total: 0, limit: 25, offset: 0 }) });
  });
  await page.route("**/api/sites/3/category-rules/preview", async (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify({ total_pages_evaluated: 3, matching_pages: 2, currently_assigned: 0, would_gain_automatic_support: 2, would_lose_automatic_support: 0, excluded_matches: 0, sample_matching_pages: [{ resource_id: 2, normalized_url: "https://example.com/blog/a" }], sample_non_matching_pages: [], invalid_conditions: [], evaluation_duration_ms: 2 }) }));

  await page.goto("/sites/3/settings");
  await page.getByLabel("Time zone").fill("America/New_York");
  await page.getByRole("button", { name: "Save site" }).click();
  await expect(page).toHaveURL(/\/sites\/3$/);
  await page.goto("/sites/3/category-rules");
  await page.getByRole("button", { name: "Create Rule" }).click();
  await page.getByLabel("Rule name").fill("Blog paths");
  await page.getByLabel("Rule Category").selectOption("7");
  await page.getByLabel("Condition 1 value").fill("/blog/");
  await page.getByRole("button", { name: "Preview" }).click();
  await expect(page.getByText("Preview: 2 matching Pages")).toBeVisible();
  await page.getByRole("button", { name: "Save & Apply" }).click();
  await expect(page.getByRole("button", { name: "Create Rule" })).toBeVisible();
});

test("deterministic Scan comparison selects direction, filters, and sorts neutral results", async ({
  page,
}) => {
  await mockApi(page);
  await mockComparisonApi(page);

  await page.goto("/sites/3/comparisons");
  await expect(page.getByLabel("Baseline Scan")).toHaveValue("1");
  await expect(page.getByLabel("Target Scan")).toHaveValue("2");
  await page.getByRole("button", { name: "Compare" }).click();
  await expect(page.getByText("Comparable", { exact: true })).toBeVisible();
  await expect(page.getByText("scan-comparison-v2")).toBeVisible();

  await page.getByRole("tab", { name: /Pages/ }).click();
  await expect(page.getByLabel("Show all Pages")).not.toBeChecked();
  await expect(page.getByText("Not Observed In Target", { exact: true })).toBeVisible();
  await expect(page.getByText(/removed from website/i)).toHaveCount(0);
  await page.getByRole("button", { name: "Sort URL ascending" }).click();
  await expect(page).toHaveURL(/comparison_sort=url/);
  await page.getByLabel("Presence filter").selectOption("not_observed_in_target");
  await expect(page).toHaveURL(/comparison_presence=not_observed_in_target/);
  await page.getByLabel("Show all Pages").check();
  await expect(page).toHaveURL(/comparison_show_all=true/);
});

async function mockComparisonApi(page: Page) {
  let created = false;
  const scanSide = (id: number, createdAt: string) => ({
    id,
    status: "completed",
    starting_url: "https://example.com/learn/",
    created_at: createdAt,
    started_at: createdAt,
    finished_at: createdAt,
    stop_reason: "queue_empty",
    failed_count: 0,
  });
  const build = {
    id: 9,
    scan_comparison_id: 7,
    comparison_version: "scan-comparison-v2",
    algorithm_identity: "scan-comparison-v2|source-signals-v1|document-content-v2|incapsula-cb-v1|page-v2|resource-v1|link-v1|scan-projection-v1",
    status: "ready",
    baseline_projection_build_id: 4,
    target_projection_build_id: 5,
    baseline_projection_version: "scan-projection-v1",
    target_projection_version: "scan-projection-v1",
    baseline_projection_algorithm_identity: "projection",
    target_projection_algorithm_identity: "projection",
    baseline_projection_checksum: "baseline",
    target_projection_checksum: "target",
    baseline_scope_fingerprint: "same",
    target_scope_fingerprint: "same",
    baseline_seed_fingerprint: "same",
    target_seed_fingerprint: "same",
    coverage_state: "comparable",
    warnings_json: [],
    validation_json: {},
    comparison_checksum_sha256: "deterministic-checksum",
    started_at: "2026-08-07T12:00:00Z",
    finished_at: "2026-08-07T12:00:01Z",
    failed_at: null,
    build_duration_ms: 1000,
    error_type: null,
    error_message: null,
    page_result_count: 1,
    resource_result_count: 0,
    link_result_count: 0,
    created_at: "2026-08-07T12:00:00Z",
  };
  const comparison = {
    id: 7,
    website_property_id: 3,
    baseline_scan_id: 1,
    target_scan_id: 2,
    current_build_id: 9,
    created_at: "2026-08-07T12:00:00Z",
    updated_at: "2026-08-07T12:00:01Z",
    baseline_scan: scanSide(1, "2026-08-06T12:00:00Z"),
    target_scan: scanSide(2, "2026-08-07T12:00:00Z"),
    current_build: build,
    active_build: null,
  };
  const overview = {
    comparison,
    summary: {
      pages: { total: 1, not_observed_in_target: 1 },
      resources: { total: 0 },
      links: { total: 0 },
      scan: {},
    },
  };
  await page.route("**/api/sites/3/scans**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          scanSide(2, "2026-08-07T12:00:00Z"),
          scanSide(1, "2026-08-06T12:00:00Z"),
        ],
        total: 2,
        limit: 250,
        offset: 0,
      }),
    });
  });
  await page.route(/\/api\/sites\/3\/comparisons(?:\?.*)?$/, async (route) => {
    if (route.request().method() === "POST") {
      created = true;
      await route.fulfill({ status: 202, contentType: "application/json", body: JSON.stringify(overview) });
      return;
    }
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ items: created ? [comparison] : [], total: created ? 1 : 0, limit: 100, offset: 0 }),
    });
  });
  await page.route("**/api/sites/3/comparisons/7/status", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(overview) });
  });
  await page.route(/\/api\/sites\/3\/comparisons\/7$/, async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(overview) });
  });
  await page.route("**/api/sites/3/comparisons/7/pages**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        items: [{
          id: 1,
          resource_id: 2,
          normalized_url: "https://example.com/learn/old",
          host: "example.com",
          path: "/learn/old",
          presence_state: "not_observed_in_target",
          change_state: "not_applicable",
          primary_change_class: "not_applicable",
          content_state: "not_applicable",
          document_content_state: "not_applicable",
          metadata_state: "not_applicable",
          technical_state: "not_applicable",
          exact_source_state: "not_applicable",
          head_state: "not_applicable",
          changed_field_count: 0,
          baseline_http_status: 200,
          target_http_status: null,
          response_time_ms_delta: null,
          network_bytes_delta: null,
        }],
        total: 1,
        limit: 50,
        offset: 0,
        comparison_build_id: 9,
        comparison_version: "scan-comparison-v2",
      }),
    });
  });
}

async function mockApi(page: Page) {
  let scanStatus: "running" | "completed" = "running";
  let siteActive = true;
  let pageNote: Record<string, unknown> | null = null;

  await page.route("**/api/sites/3/performance/providers", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ pagespeed: { configured: false, adapter_version: "pagespeed-provider-v1" }, crux: { configured: false, adapter_version: "crux-provider-v1" }, normalization_version: "performance-normalization-v1", default_page_limit: 10, hard_page_limit: 25 }) });
  });
  await page.route("**/api/sites/3/performance/latest**", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ items: [], total: 0, limit: 100, offset: 0, measured_page_count: 0, field_available_page_count: 0 }) });
  });
  await page.route("**/api/sites/3/performance-runs**", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ items: [], total: 0, limit: 25, offset: 0 }) });
  });

  await page.route("**/api/scans/1/projection**", async (route) => {
    if (route.request().method() === "POST") {
      await route.fulfill({ status: 202, contentType: "application/json", body: JSON.stringify({ id: 10, scan_id: 1, status: "queued" }) });
      return;
    }
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ scan_id: 1, scan_status: "completed", expected_version: "scan-projection-v1", projection_source: "materialized", projection_status: "ready", current_build: { id: 9, status: "ready" }, active_build: null, latest_build: { id: 9, status: "ready" }, can_build: false, can_rebuild: true }) });
  });

  await page.route("**/api/scans/1/resources/summary", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ unique_resources: 2, observed_resources: 1, discovered_only_resources: 1, total_occurrences: 3, kind_counts: { image: 1, document: 1, script: 1, stylesheet: 1, font: 1 } }) });
  });
  await page.route("**/api/scans/1/resources/21/occurrences**", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ items: [{ occurrence_id: 1, occurrence_source: "anchor", source_snapshot_id: 9, source_resource_id: 2, source_url: "https://example.com/pricing", source_title: "Pricing", relation_type: "page_link", element_tag: "a", attribute_name: "href", raw_url: "/guide.pdf", resolved_url: "https://example.com/guide.pdf", anchor_text: "Guide", alt_text: null, srcset_descriptor: null, rel: null, media: null, type_hint: null, as_hint: null, scope_decision: "crawlable", in_scope: true, dom_path: "/html/body/a", discovered_at: "2026-08-06T01:00:00Z" }], total: 1, limit: 50, offset: 0 }) });
  });
  await page.route("**/api/scans/1/resources/21", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ resource: resourceItem({ resource_id: 21, normalized_url: "https://example.com/guide.pdf", path: "/guide.pdf", file_extension: "pdf", effective_kind: "document", effective_kind_label: "Document", observed: true, discovered_only: false, snapshot_id: 10, final_url: "https://example.com/guide.pdf", http_status: 200, normalized_mime_type: "application/pdf", declared_content_length: 5000 }), requested_url: "https://example.com/guide.pdf", response_body_state: "metadata_only", inspected_prefix_byte_count: 0 }) });
  });
  await page.route("**/api/scans/1/resources**", async (route) => {
    if (new URL(route.request().url()).pathname !== "/api/scans/1/resources") {
      await route.fallback();
      return;
    }
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ items: [resourceItem({ resource_id: 21, normalized_url: "https://example.com/guide.pdf", path: "/guide.pdf", file_extension: "pdf", effective_kind: "document", effective_kind_label: "Document", observed: true, discovered_only: false, snapshot_id: 10, final_url: "https://example.com/guide.pdf", http_status: 200, normalized_mime_type: "application/pdf" }), resourceItem({ resource_id: 22, normalized_url: "https://example.com/hero.webp", path: "/hero.webp", file_extension: "webp", effective_kind: "image", effective_kind_label: "Image" })], total: 2, limit: 50, offset: 0 }) });
  });
  await page.route("**/api/scans/1/rendered-observations**", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ items: [{ id: 31, snapshot_id: 9, capture_state: "completed_with_warnings", static_final_url: "https://example.com/pricing", page_title: "Pricing", navigation_http_status: 200, duration_ms: 450, warning_count: 1, page_error_count: 0, blocked_request_count: 0, console_message_count: 0, has_viewport_screenshot: true, has_full_page_screenshot: false, has_rendered_dom: true, started_at: "2026-08-06T01:00:00Z", finished_at: "2026-08-06T01:00:01Z" }], total: 1, limit: 50, offset: 0 }) });
  });

  await page.route("**/api/notes/41", async (route) => {
    if (route.request().method() === "PATCH" && pageNote) {
      pageNote = { ...pageNote, ...(await route.request().postDataJSON()) };
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify(pageNote),
      });
      return;
    }
    await route.fulfill({ status: 404 });
  });

  await page.route("**/api/sites/3/pages/2/notes**", async (route) => {
    if (route.request().method() === "POST") {
      const body = await route.request().postDataJSON();
      pageNote = {
        id: 41,
        website_property_id: null,
        scan_id: null,
        site_page_id: 12,
        body: body.body,
        is_pinned: body.is_pinned,
        created_at: "2026-08-05T12:00:00Z",
        updated_at: "2026-08-05T12:00:00Z",
      };
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify(pageNote),
      });
      return;
    }
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        items: pageNote ? [pageNote] : [],
        total: pageNote ? 1 : 0,
        limit: 50,
        offset: 0,
      }),
    });
  });

  await page.route("**/api/sites/3/pages/2/observations**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        items: [pageObservation],
        total: 1,
        limit: 50,
        offset: 0,
      }),
    });
  });

  await page.route("**/api/sites/3/page-categories**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        items: pageCategories,
        total: pageCategories.length,
        limit: 200,
        offset: 0,
      }),
    });
  });

  await page.route("**/api/sites/3/pages/2/metadata", async (route) => {
    const body = await route.request().postDataJSON();
    persistentPage.page.owner_label =
      body.owner_label ?? persistentPage.page.owner_label;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(persistentPage),
    });
  });

  await page.route("**/api/sites/3/pages/2", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(persistentPage),
    });
  });

  await page.route("**/api/sites/3/pages/2/categories/details", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        items: [{ category_id: 7, category_name: "Editorial", manually_assigned: true, matching_rules: [], automatic_exclusion: false, effective: true, effective_reason: "Manual" }],
      }),
    });
  });

  await page.route("**/api/snapshots/9/outgoing-links**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        items: [roleLink],
        total: 1,
        limit: 50,
        offset: 0,
        summary: {
          total_occurrences: 1,
          nofollow_occurrences: 0,
          in_scope_occurrences: 1,
          role_counts: { main_content: 1 },
        },
      }),
    });
  });

  await page.route("**/api/scans", async (route) => {
    if (route.request().method() === "POST") {
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({ ...scan, status: "running" }),
      });
      return;
    }
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify([{ ...scan, status: scanStatus }]),
    });
  });

  await page.route("**/api/scans/history**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          { ...scan, status: "completed", finished_at: "2026-07-30T01:00:03Z" },
        ],
        total: 1,
        limit: 25,
        offset: 0,
      }),
    });
  });

  await page.route("**/api/scans/1", async (route) => {
    if (route.request().method() === "DELETE") {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          deleted_scan_id: 1,
          snapshots_deleted: 1,
          link_occurrences_deleted: 1,
          resources_deleted: 1,
          html_blob_records_deleted: 1,
          html_blob_files_deleted: 1,
          html_blobs_deleted: 1,
          raw_html_bytes_reclaimed: 1200,
          stored_html_bytes_reclaimed: 480,
          warnings: [],
        }),
      });
      return;
    }
    const body = { ...scan, status: scanStatus };
    scanStatus = "completed";
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  });

  await page.route("**/api/scans/2", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        ...scan,
        id: 2,
        status: "completed",
        website_property_id: 3,
        website_property_name: "Example Site",
        website_property_base_url: "https://example.com/learn/",
        starting_url: "https://example.com/learn/",
        scope_config: { ...scope, max_pages: 12 },
      }),
    });
  });

  await page.route("**/api/sites/3/scans", async (route) => {
    if (route.request().method() === "POST") {
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          ...scan,
          id: 2,
          status: "running",
          website_property_id: 3,
          website_property_name: "Example Site",
          website_property_base_url: "https://example.com/learn/",
          starting_url: "https://example.com/learn/",
        }),
      });
      return;
    }
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          {
            ...scan,
            website_property_id: 3,
            website_property_name: "Example Site",
            website_property_base_url: "https://example.com/learn/",
          },
        ],
        total: 1,
        limit: 25,
        offset: 0,
      }),
    });
  });

  await page.route("**/api/sites/3", async (route) => {
    if (route.request().method() === "PATCH") {
      const body = await route.request().postDataJSON();
      if (typeof body.is_active === "boolean") siteActive = body.is_active;
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          ...site,
          is_active: siteActive,
          display_timezone: body.display_timezone ?? site.display_timezone,
          scope_config: body.scope_config ?? site.scope_config,
        }),
      });
      return;
    }
    if (route.request().method() === "DELETE") {
      await route.fulfill({
        status: 409,
        contentType: "application/json",
        body: JSON.stringify({
          detail:
            "Delete or detach this site's scans before deleting the site.",
        }),
      });
      return;
    }
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ ...site, is_active: siteActive }),
    });
  });

  await page.route(/\/api\/sites(?:\?.*)?$/, async (route) => {
    if (route.request().method() === "POST") {
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify(site),
      });
      return;
    }
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          {
            ...site,
            latest_scan: undefined,
            recent_scans: undefined,
            latest_scan_id: 1,
            latest_scan_status: "completed",
            latest_scan_date: "2026-07-30T01:00:00Z",
            latest_scan_discovered_count: 3,
            latest_scan_failed_count: 0,
          },
        ],
        total: 1,
        limit: 25,
        offset: 0,
      }),
    });
  });

  await page.route("**/api/scans/1/pages**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        items: [pageRow],
        total: 1,
        limit: 50,
        offset: 0,
      }),
    });
  });

  await page.route("**/api/scans/1/errors", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify([]),
    });
  });

  await page.route("**/api/scans/1/delete-preview", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        scan_id: 1,
        starting_url: "https://example.com/",
        can_delete: true,
        status: "completed",
        snapshots: 1,
        link_occurrences: 1,
        unique_resources: 1,
        html_blobs_referenced: 1,
        exclusive_html_blobs: 1,
        shared_html_blobs: 0,
        html_blobs_deleted: 1,
        raw_html_bytes_reclaimable: 1200,
        stored_html_bytes_reclaimable: 480,
        reason: null,
        warnings: [],
      }),
    });
  });

  await page.route(
    "**/api/scans/1/graph/edges/8-2/occurrences**",
    async (route) => {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          items: [
            {
              ...links[0],
              id: 20,
              source_snapshot_id: 8,
              target_snapshot_id: 9,
              anchor_text: "Pricing link",
              raw_href: "/pricing",
              is_self_link: false,
            },
          ],
          total: 2,
          limit: 50,
          offset: 0,
          edge: graph.edges[0],
        }),
      });
    },
  );

  await page.route("**/api/graph/capabilities", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(graphCapabilities),
    });
  });

  await page.route(/\/api\/scans\/1\/graph(?:\?.*)?$/, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(graph),
    });
  });

  await page.route("**/api/snapshots/9", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(snapshot),
    });
  });

  await page.route("**/api/snapshots/9/rendered", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(renderedObservation),
    });
  });

  await page.route("**/api/snapshots/9/links", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(links),
    });
  });

  await page.route("**/api/snapshots/9/inbound-links**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          {
            ...links[0],
            source_snapshot_id: 9,
            source_resource_id: 2,
            source_requested_url: "https://example.com/pricing",
            source_final_url: "https://example.com/pricing",
            source_page_title: "Source page",
            source_http_status: 200,
            source_fetch_state: "fetched",
            source_crawl_depth: 1,
            is_self_link: true,
          },
        ],
        total: 1,
        limit: 50,
        offset: 0,
        summary: {
          total_occurrences: 1,
          unique_source_pages: 1,
          unique_anchor_texts: 0,
          nofollow_occurrences: 1,
          self_link_occurrences: 1,
        },
      }),
    });
  });

  await page.route("**/api/snapshots/9/html", async (route) => {
    await route.fulfill({
      contentType: "text/plain",
      body: "<html><body><script>window.executed = true</script><h1>Pricing</h1></body></html>",
    });
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
  static_max_attempts: 2,
  static_retry_initial_delay_ms: 500,
  static_retry_max_delay_ms: 5000,
  max_html_response_bytes: 2000000,
  concurrent_requests_per_host: 2,
  delay_between_requests_ms: 0,
  user_agent: "WebsiteScanner/0.1",
  drop_query_parameters: ["utm_*", "gclid", "fbclid", "msclkid"],
  allow_private_networks: false,
  max_redirects: 10,
};

const scan = {
  id: 1,
  website_property_id: null,
  website_property_name: null,
  website_property_base_url: null,
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
  fatal_error_message: null,
};

const site = {
  id: 3,
  name: "Example Site",
  base_url: "https://example.com/learn/",
  normalized_base_url: "https://example.com/learn/",
  description: "Example site",
  group_key: "Marketing",
  locale: "en-US",
  platform_key: "WordPress Learn",
  ownership_key: "Web Team",
  display_timezone: null,
  scope_config: { ...scope, included_path_prefixes: ["/learn/"] },
  is_active: true,
  created_at: "2026-07-30T01:00:00Z",
  updated_at: "2026-07-30T01:00:00Z",
  total_scan_count: 1,
  latest_scan: {
    ...scan,
    website_property_id: 3,
    website_property_name: "Example Site",
    website_property_base_url: "https://example.com/learn/",
  },
  recent_scans: [
    {
      ...scan,
      website_property_id: 3,
      website_property_name: "Example Site",
      website_property_base_url: "https://example.com/learn/",
    },
  ],
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
  error_type: null,
};

const pageCategories = [
  {
    id: 7,
    website_property_id: 3,
    name: "Editorial",
    description: null,
    color_key: "blue",
    sort_order: 0,
    is_active: true,
    assignment_count: 1,
    manual_assignment_count: 1,
    automatic_assignment_count: 0,
    exclusion_count: 0,
    rule_count: 0,
    created_at: "2026-08-05T10:00:00Z",
    updated_at: "2026-08-05T10:00:00Z",
  },
  {
    id: 8,
    website_property_id: 3,
    name: "Retired category",
    description: null,
    color_key: "gray",
    sort_order: 1,
    is_active: false,
    assignment_count: 0,
    manual_assignment_count: 0,
    automatic_assignment_count: 0,
    exclusion_count: 0,
    rule_count: 0,
    created_at: "2026-08-05T10:00:00Z",
    updated_at: "2026-08-05T10:00:00Z",
  },
];

const persistentPage = {
  site_id: 3,
  site_name: "Example Site",
  page: {
    site_page_id: 12,
    resource_id: 2,
    normalized_url: "https://example.com/pricing",
    host: "example.com",
    path: "/pricing",
    query: "",
    owner_label: "Web team",
    workflow_status: "needs_review",
    categories: [pageCategories[0]],
    category_count: 1,
    note_count: 0,
    associated_at: "2026-07-30T01:00:02Z",
    observation_count: 1,
    first_observed_at: "2026-07-30T01:00:02Z",
    latest_observed_at: "2026-07-30T01:00:02Z",
    latest_snapshot_id: 9,
    latest_scan_id: 1,
    latest_http_status: 200,
    latest_title: "Pricing",
    latest_retrieval_method: "full_fetch",
    latest_parse_method: "parsed",
    latest_reused_from_snapshot_id: null,
    latest_fetch_state: "fetched",
    latest_error_type: null,
    latest_error_message: null,
  },
};

const pageObservation = {
  snapshot_id: 9,
  scan_id: 1,
  site_id: 3,
  site_name: "Example Site",
  scan_created_at: "2026-07-30T01:00:00Z",
  scan_status: "completed",
  scan_started_at: "2026-07-30T01:00:01Z",
  scan_finished_at: "2026-07-30T01:01:00Z",
  observed_at: "2026-07-30T01:00:02Z",
  requested_url: "https://example.com/pricing",
  final_url: "https://example.com/pricing",
  http_status: 200,
  retrieval_http_status: 200,
  fetch_state: "fetched",
  error_type: null,
  crawl_depth: 1,
  response_time_ms: 87,
  content_type: "text/html",
  raw_html_sha256: "rawhash",
  head_sha256: "headhash",
  page_title: "Pricing",
  canonical_url: "https://example.com/pricing",
  retrieval_method: "full_fetch",
  parse_method: "parsed",
  content_blob_id: 4,
  parse_artifact_id: 5,
  reused_from_snapshot_id: null,
  network_bytes_transferred: 1200,
  parser_version: "html-parser-v2-link-roles",
};

const roleLink = {
  id: 33,
  raw_href: "/learn",
  resolved_url: "https://example.com/learn",
  normalized_target_url: "https://example.com/learn",
  target_resource_id: 4,
  anchor_text: "Learn",
  title: null,
  aria_label: null,
  rel: null,
  target: null,
  dom_path: "html > body > main > a",
  in_scope: true,
  scope_decision: "crawlable",
  exclusion_reason: null,
  link_role: "main_content",
  link_role_label: "Main content",
  link_role_rule: "ancestor_main",
  link_context_json: { landmark_tag: "main" },
  discovered_at: "2026-07-30T01:00:02Z",
};

const graph = {
  scan: {
    id: 1,
    starting_url: "https://example.com/",
    status: "completed",
    website_property_id: null,
    website_property_name: null,
    created_at: "2026-07-30T01:00:00Z",
    finished_at: "2026-07-30T01:01:00Z",
  },
  summary: {
    total_available_nodes: 2,
    total_available_edges: 1,
    returned_nodes: 2,
    returned_edges: 1,
    fetched_nodes: 2,
    unfetched_nodes: 0,
    error_nodes: 0,
    self_link_edges: 0,
    total_occurrences: 2,
    truncated: false,
    truncation_reasons: [],
    focused: false,
    focus_snapshot_id: null,
    focus_hops: null,
  },
  nodes: [
    {
      id: "snapshot:8",
      kind: "page",
      snapshot_id: 8,
      resource_id: 1,
      requested_url: "https://example.com/",
      final_url: "https://example.com/",
      page_title: "Home",
      host: "example.com",
      path: "/",
      http_status: 200,
      fetch_state: "fetched",
      error_type: null,
      crawl_depth: 0,
      content_type: "text/html",
      response_time_ms: 80,
      inbound_occurrence_count: 0,
      inbound_source_page_count: 0,
      outbound_occurrence_count: 2,
      outbound_target_page_count: 1,
      is_scan_seed: true,
      seed_origin_count: 1,
      is_starting_url: true,
      redirects: false,
      canonical_url: null,
      category: "2xx",
    },
    {
      id: "snapshot:9",
      kind: "page",
      snapshot_id: 9,
      resource_id: 2,
      requested_url: "https://example.com/pricing",
      final_url: "https://example.com/pricing",
      page_title: "Pricing",
      host: "example.com",
      path: "/pricing",
      http_status: 200,
      fetch_state: "fetched",
      error_type: null,
      crawl_depth: 1,
      content_type: "text/html",
      response_time_ms: 87,
      inbound_occurrence_count: 2,
      inbound_source_page_count: 1,
      outbound_occurrence_count: 0,
      outbound_target_page_count: 0,
      is_scan_seed: false,
      seed_origin_count: 0,
      is_starting_url: false,
      redirects: false,
      canonical_url: null,
      category: "2xx",
    },
  ],
  edges: [
    {
      id: "8-2",
      source: "snapshot:8",
      target: "snapshot:9",
      source_snapshot_id: 8,
      target_snapshot_id: 9,
      target_resource_id: 2,
      occurrence_count: 2,
      unique_anchor_text_count: 1,
      nofollow_occurrence_count: 0,
      follow_occurrence_count: 2,
      empty_anchor_occurrence_count: 0,
      is_self_link: false,
      sample_anchor_texts: ["Pricing"],
      first_discovered_at: "2026-07-30T01:00:01Z",
      last_discovered_at: "2026-07-30T01:00:02Z",
      scope_decisions: { crawlable: 2 },
      dom_regions: { main: 2 },
    },
  ],
  effective_filters: {},
};

const graphCapabilities = {
  default_node_limit: 100,
  maximum_node_limit: 3000,
  default_edge_limit: 250,
  maximum_edge_limit: 10000,
  default_focus_hops: 1,
  maximum_focus_hops: 3,
  sample_anchor_limit: 5,
  occurrence_page_default: 50,
  occurrence_page_maximum: 200,
  supported_status_filters: ["any", "2xx", "3xx", "4xx", "5xx", "none"],
  supported_error_filters: ["any", "with_errors", "without_errors"],
  supported_node_size_modes: [
    "uniform",
    "inbound_sources",
    "inbound_occurrences",
    "outbound_targets",
    "outbound_occurrences",
    "response_time",
    "depth_inverse",
  ],
  supported_node_category_modes: [
    "status",
    "fetch_state",
    "depth",
    "host",
    "path",
    "error",
    "seed",
  ],
};

const snapshot = {
  id: 9,
  scan_id: 1,
  resource_id: 2,
  website_property_id: null,
  website_property_name: null,
  site_page_id: null,
  has_persistent_page: false,
  is_html_page: true,
  requested_url: "https://example.com/pricing-old",
  final_url: "https://example.com/pricing",
  http_status: 200,
  content_type: "text/html",
  encoding: "utf-8",
  crawl_depth: 1,
  fetched_at: "2026-07-30T01:00:02Z",
  response_time_ms: 87,
  response_headers: {},
  redirect_chain: [
    {
      requested_url: "https://example.com/pricing-old",
      status_code: 301,
      location: "/pricing",
      resolved_url: "https://example.com/pricing",
    },
  ],
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
    json_ld: ['{"@context":"https://schema.org","@type":"WebPage"}'],
  },
  fetch_state: "fetched",
  error_type: null,
  error_message: null,
};

const renderedObservation = {
  id: 31,
  snapshot_id: 9,
  capture_state: "completed_with_warnings",
  started_at: "2026-08-06T01:00:00Z",
  finished_at: "2026-08-06T01:00:01Z",
  requested_url: "https://example.com/pricing",
  final_url: "https://example.com/pricing",
  navigation_http_status: 200,
  document_title: "Pricing",
  browser_engine: "chromium",
  browser_version: "151",
  playwright_version: "1.62",
  renderer_version: "1",
  browser_policy_version: "1",
  capture_schema_version: "1",
  user_agent: "Chromium",
  viewport_width: 1440,
  viewport_height: 900,
  device_scale_factor: 1,
  locale: "en-US",
  timezone_id: "UTC",
  color_scheme: "light",
  reduced_motion: "reduce",
  readiness_state: "load",
  load_event_reached: true,
  fonts_ready_reached: true,
  duration_ms: 450,
  configuration_fingerprint: "a".repeat(64),
  network_entry_count: 0,
  blocked_request_count: 0,
  console_message_count: 0,
  page_error_count: 0,
  warning_count: 1,
  network_truncated: false,
  console_truncated: false,
  page_errors_truncated: false,
  total_encoded_network_bytes: 0,
  error_type: null,
  error_message: null,
  warnings_json: [],
  artifacts: [],
};

function resourceItem(overrides: Record<string, unknown>) {
  return {
    resource_id: 1, normalized_url: "https://example.com/resource", host: "example.com", path: "/resource", file_extension: null,
    effective_kind: "other", effective_kind_label: "Other", classification_source: "extension", observed: false, discovered_only: true,
    snapshot_id: null, final_url: null, http_status: null, normalized_mime_type: null, content_disposition_filename: null,
    declared_content_length: null, network_bytes_transferred: null, fetched_at: null, response_time_ms: null,
    occurrence_count: 1, source_page_count: 1, anchor_occurrence_count: 0, embedded_occurrence_count: 1,
    in_scope_occurrence_count: 1, out_of_scope_occurrence_count: 0, first_discovered_at: "2026-08-06T01:00:00Z",
    latest_discovered_at: "2026-08-06T01:00:00Z", observation_count: 0, scan_count: 1, ...overrides
  };
}

function structuredContentFixture() {
  const section = (id: number, parentId: number | null, position: number, level: number, heading: string, directText: string) => ({
    id, position, parent_section_id: parentId, kind: "heading", heading_level: level,
    heading_text: heading, heading_dom_path: `html > body > main > h${level}`,
    region_key: "main", region_dom_path: "html > body > main", direct_text: directText,
    direct_text_sha256: "d".repeat(64), section_sha256: "e".repeat(64), subtree_sha256: "f".repeat(64),
    direct_word_count: directText.split(" ").length, direct_character_count: directText.length,
    subtree_word_count: directText.split(" ").length, subtree_character_count: directText.length,
    child_count: id === 10 ? 1 : 0, descendant_count: id === 10 ? 1 : 0,
    block_count: 1, has_direct_content: true,
  });
  return {
    status: "ready", reason: null,
    provenance: { snapshot_id: 9, scan_id: 1, site_id: 3, content_blob_id: 7, raw_html_sha256: "a".repeat(64), requested_url: "https://example.com/pricing", final_url: "https://example.com/pricing", fetched_at: "2026-08-06T01:00:00Z", retrieval_method: "full_fetch", reused_from_snapshot_id: null },
    artifact: { id: 5, extractor_version: "structured-content-v1", extractor_config_version: "default-v1", extraction_state: "ready", document_profile: "headed", section_count: 2, heading_count: 2, heading_counts: { h1: 1, h2: 1, h3: 0, h4: 0, h5: 0, h6: 0 }, document_word_count: 8, document_character_count: 80, document_text_sha256: "b".repeat(64), outline_sha256: "c".repeat(64), is_truncated: false, truncation_reasons: [], created_at: "2026-08-06T01:00:01Z" },
    items: [
      section(10, null, 0, 1, "Page title", "Page introduction"),
      section(11, 10, 1, 2, "Details", "<script>window.structuredExecuted = true</script> Visible text"),
    ],
    total: 2, limit: 2000, offset: 0,
  };
}

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
    exclusion_reason: "External host",
    discovered_at: "2026-07-30T01:00:02Z",
  },
];
