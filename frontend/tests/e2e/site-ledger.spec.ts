import { mkdir } from "node:fs/promises";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

if (process.env.README_SCREENSHOT_REVIEW === "1") {
  test("captures deterministic README product screenshots", async ({ page }) => {
    await mockApi(page);
    await mockComparisonApi(page, 5, 6, 4);
    await mockReadmePresentationApi(page);

    const outputDir = path.resolve(process.cwd(), "..", ".tmp", "readme-screenshots");
    await mkdir(outputDir, { recursive: true });
    await page.setViewportSize({ width: 1440, height: 960 });

    await page.goto("/sites/3");
    await expect(page.getByRole("heading", { name: "Example Commerce" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Evidence coverage" })).toBeVisible();
    await captureReadmeScreenshot(page, outputDir, "site-intelligence-overview.png");

    await page.goto("/sites/3/findings");
    await expect(page.getByRole("link", { name: "https://example.test/products/discontinued-lamp" })).toBeVisible();
    await captureReadmeScreenshot(page, outputDir, "findings-workspace.png");

    await page.goto("/sites/3/pages/2?tab=history");
    await expect(page.getByText("Document and metadata changed")).toBeVisible();
    await captureReadmeScreenshot(page, outputDir, "page-history.png");

    await page.goto("/sites/3/comparisons");
    await page.getByRole("button", { name: "Compare" }).click();
    await expect(page.getByText("Comparable", { exact: true })).toBeVisible();
    await page.getByRole("tab", { name: /Pages/ }).click();
    await captureReadmeScreenshot(page, outputDir, "scan-comparison.png");

    await page.goto("/sites/3/graph?scan_id=1&labels=all&link_visibility=all");
    await expect(page.getByRole("img", { name: "Static 2D website topology graph" })).toBeVisible();
    await captureReadmeScreenshot(page, outputDir, "topology-graph.png");
  });
}

test("Site Intelligence refreshes current evidence without replacing history", async ({ page }) => {
  await mockApi(page);
  await mockReadmePresentationApi(page);
  let requestedMode = "";
  await page.route("**/api/sites/3/collection-plans/preview?limit=20", async (route) => {
    const payload = route.request().postDataJSON();
    requestedMode = payload.target_mode;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        evidence_domain: "render", target_mode: "refresh_current", context_identity: "render:desktop", context: {},
        active_page_count: 428, active_page_universe_sha256: "a".repeat(64), eligible: 428,
        covered: 389, in_flight: 0, active_collection: 5, missing: 39, ineligible: 0,
        batch_size: 250, estimated_batch_count: 2, collectable: true, non_collectable_reason: null,
        targets: [], target_total: 423, limit: 20, offset: 0,
      }),
    });
  });
  await page.route("**/api/sites/3/collection-plans", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ id: 54 }) });
  });
  await page.goto("/sites/3");
  const dialogPromise = page.waitForEvent("dialog");
  const clickPromise = page.getByRole("button", { name: "Refresh current" }).click();
  const dialog = await dialogPromise;
  expect(dialog.message()).toContain("Existing observations will be retained");
  expect(dialog.message()).toContain("5 eligible Pages are already being collected");
  await dialog.accept();
  await clickPromise;
  await expect.poll(() => requestedMode).toBe("refresh_current");
});

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

test("Accessibility workspace is responsive and keeps automated evidence explicit", async ({ page }) => {
  await mockApi(page);
  for (const viewport of [
    { width: 375, height: 812 },
    { width: 768, height: 1024 },
    { width: 1024, height: 768 },
    { width: 1440, height: 960 },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto("/sites/3/accessibility");
    await expect(page.getByRole("heading", { name: "Accessibility", exact: true })).toBeVisible();
    await expect(page.getByText("Automated checks are limited.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Run Accessibility Audit" })).toBeEnabled();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  }
  await page.getByRole("tab", { name: "Pages" }).click();
  await expect(page.getByText("No audited Pages match")).toBeVisible();
  await page.getByRole("tab", { name: "Rules" }).click();
  await expect(page.getByText("No current rule evidence")).toBeVisible();
  await page.getByRole("tab", { name: /Runs/ }).click();
  await expect(page.getByText("No Accessibility runs")).toBeVisible();
  await page.getByRole("button", { name: "Run Accessibility Audit" }).click();
  await expect(page.getByRole("dialog", { name: "Run Accessibility Audit" })).toBeVisible();
  await page.keyboard.press("Escape");
  await page.setViewportSize({ width: 375, height: 812 });
  await page.getByRole("button", { name: "Open navigation" }).click();
  await expect(page.getByRole("link", { name: "Accessibility" })).toHaveAttribute("aria-current", "page");
});

test("Rendered workspace rerenders, deletes old evidence, and deletes the old Run", async ({ page }) => {
  await mockApi(page);
  let activeRunId = 41;
  let rerenderTargets: number[] = [];
  let evidenceDeleted = false;
  let oldRunDeleted = false;
  const run = (id: number) => renderRunFixture(id, id === 41 ? "site_workspace" : "rerender");
  const observation = (overrides: Record<string, unknown>) => ({
    id: 301,
    snapshot_id: null,
    render_run_target_id: 101,
    resource_id: 2,
    page_title: "Successful",
    static_final_url: "https://example.com/success",
    browser_final_url: "https://example.com/success",
    capture_state: "completed",
    static_http_status: null,
    navigation_http_status: 200,
    error_type: null,
    error_message: null,
    duration_ms: 120,
    warning_count: 0,
    page_error_count: 0,
    blocked_request_count: 0,
    console_message_count: 0,
    has_viewport_screenshot: true,
    has_full_page_screenshot: true,
    has_rendered_dom: true,
    finished_at: "2026-08-26T05:01:00Z",
    ...overrides,
  });
  const mixed = [
    observation({}),
    observation({ id: 302, render_run_target_id: 102, resource_id: 3, page_title: "Rate limited", static_final_url: "https://example.com/limited", browser_final_url: "https://example.com/limited", capture_state: "failed", navigation_http_status: 429, error_type: "navigation_rate_limited", has_viewport_screenshot: false, has_full_page_screenshot: false, has_rendered_dom: false }),
    observation({ id: 303, render_run_target_id: 103, resource_id: 4, page_title: "Not attempted", static_final_url: "https://example.com/skipped", browser_final_url: null, capture_state: "skipped", navigation_http_status: null, error_type: "host_rate_limit_circuit_open", has_viewport_screenshot: false, has_full_page_screenshot: false, has_rendered_dom: false }),
  ];
  const observationList = (items: typeof mixed) => ({ items, total: items.length, limit: 50, offset: 0, summary: { successful_renders: 1, no_content_responses: 0, redirect_responses: 0, http_error_responses: 0, rate_limited: 1, skipped_after_throttling: 1, technical_failures: 0, artifacts_retained: 3 } });
  const target = (item: (typeof mixed)[number], position: number) => ({ target_id: item.render_run_target_id, position, web_resource_id: item.resource_id, requested_url: item.static_final_url, source_snapshot_id: null, created_at: "2026-08-26T05:00:00Z", evidence_deleted_at: evidenceDeleted && item.id === 302 ? "2026-08-26T06:00:00Z" : null, observation_id: evidenceDeleted && item.id === 302 ? null : item.id, capture_state: evidenceDeleted && item.id === 302 ? null : item.capture_state, navigation_http_status: evidenceDeleted && item.id === 302 ? null : item.navigation_http_status, duration_ms: item.duration_ms, warning_count: item.warning_count, page_error_count: item.page_error_count, has_page_artifacts: !evidenceDeleted && item.has_viewport_screenshot, finished_at: evidenceDeleted && item.id === 302 ? null : item.finished_at, presentation_state: evidenceDeleted && item.id === 302 ? "evidence_deleted" : item.error_type === "navigation_rate_limited" ? "rate_limited" : item.error_type === "host_rate_limit_circuit_open" ? "not_attempted_host_throttled" : "successful" });
  const deletionImpact = { can_delete: true, reason: null, targets_requested: 1, observations: 1, targets_already_without_evidence: 0, runs: 1, run_targets: 3, deleted_targets: 0, unattempted_targets: 0, legacy_observations: 0, network_rows: 4, console_rows: 0, page_error_rows: 0, artifact_rows: 0, artifact_blobs_referenced: 0, exclusive_artifact_blobs: 0, shared_artifact_blobs_retained: 0, raw_bytes_reclaimable: 0, stored_bytes_reclaimable: 0, background_jobs: 1, job_events: 2, child_rerender_links_detached: 1 };

  await page.route("**/api/rendering/capabilities", (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify({ defaults: { ...scope, render_mode: "all_eligible" }, limits: { render_viewport_width: { minimum: 320, maximum: 3840 }, render_viewport_height: { minimum: 240, maximum: 2160 }, render_navigation_timeout_seconds: { minimum: 1, maximum: 120 }, render_load_timeout_seconds: { minimum: 0, maximum: 30 } }, supported_modes: [], browser_engine: "chromium", artifact_types: [], allowed_request_methods: ["GET"], service_workers: "blocked" }) }));
  await page.route(/\/api\/sites\/3\/pages(?:\?.*)?$/, (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify({ items: [
    { resource_id: 2, latest_title: "Successful", normalized_url: "https://example.com/success", workspace_state: "active" },
    { resource_id: 3, latest_title: "Rate limited", normalized_url: "https://example.com/limited", workspace_state: "active" },
    { resource_id: 4, latest_title: "Not attempted", normalized_url: "https://example.com/skipped", workspace_state: "active" },
  ], total: 3, limit: 50, offset: 0 }) }));
  await page.route(/\/api\/sites\/3\/render-runs(?:\?.*)?$/, async (route) => {
    if (route.request().method() === "POST") {
      activeRunId = 41;
      await route.fulfill({ status: 202, contentType: "application/json", body: JSON.stringify(run(41)) });
      return;
    }
    const items = oldRunDeleted ? [run(42)] : activeRunId === 42 ? [run(42), run(41)] : [run(41)];
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ items, total: items.length, limit: 25, offset: 0 }) });
  });
  await page.route("**/api/sites/3/render-runs/41/rerender", async (route) => {
    rerenderTargets = (await route.request().postDataJSON()).target_ids;
    activeRunId = 42;
    await route.fulfill({ status: 202, contentType: "application/json", body: JSON.stringify(run(42)) });
  });
  await page.route(/\/api\/sites\/3\/render-runs\/(41|42)\/targets(?:\?.*)?$/, async (route) => {
    const outcome = new URL(route.request().url()).searchParams.get("outcome");
    let items = mixed.map(target);
    if (outcome === "rate_limited") items = items.filter((item) => item.presentation_state === "rate_limited");
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ items, total: items.length, limit: 50, offset: 0 }) });
  });
  await page.route("**/api/sites/3/render-runs/41/evidence-deletion-preview", (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify(deletionImpact) }));
  await page.route("**/api/sites/3/render-runs/41/delete-evidence", async (route) => { evidenceDeleted = true; await route.fulfill({ contentType: "application/json", body: JSON.stringify({ observations_deleted: 1, runs_deleted: 0, warnings: [] }) }); });
  await page.route("**/api/sites/3/render-runs/41/deletion-preview", (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify(deletionImpact) }));
  await page.route(/\/api\/sites\/3\/render-runs\/(41|42)(?:\?.*)?$/, async (route) => {
    const id = Number(new URL(route.request().url()).pathname.split("/").at(-1));
    if (route.request().method() === "DELETE") { oldRunDeleted = true; await route.fulfill({ contentType: "application/json", body: JSON.stringify({ observations_deleted: 0, runs_deleted: 1, warnings: [] }) }); return; }
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ ...run(id), observations: observationList(mixed) }) });
  });

  await page.goto("/sites/3/rendered");
  await page.getByRole("button", { name: "Run renders" }).click();
  await page.getByRole("checkbox", { name: /Successful/ }).click();
  await page.getByRole("checkbox", { name: /Rate limited/ }).click();
  await page.getByRole("checkbox", { name: /Not attempted/ }).click();
  await page.getByRole("button", { name: "Queue 3 Pages" }).click();
  await expect(page).toHaveURL(/\/sites\/3\/rendered\/runs\/41/);
  await expect(page.getByText("HTTP 429")).toBeVisible();
  await page.getByLabel("Target state").selectOption("rate_limited");
  await page.getByRole("checkbox", { name: "Select https://example.com/limited" }).click();
  await page.getByRole("button", { name: "Rerender 1" }).click();
  await expect(page).toHaveURL(/\/sites\/3\/rendered\/runs\/42/);
  expect(rerenderTargets).toEqual([102]);

  await page.goto("/sites/3/rendered/runs/41");
  await page.getByLabel("Target state").selectOption("rate_limited");
  await page.getByRole("checkbox", { name: "Select https://example.com/limited" }).click();
  await page.getByRole("button", { name: "Delete evidence (1)" }).click();
  await page.getByRole("button", { name: "Delete permanently" }).click();
  await page.getByLabel("Target state").selectOption("evidence_deleted");
  await expect(page.getByRole("table").getByText("Evidence deleted", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Delete run" }).click();
  await page.getByRole("textbox", { name: "Type DELETE RENDER RUN 41 to confirm" }).fill("DELETE RENDER RUN 41");
  await page.getByRole("button", { name: "Delete permanently" }).click();
  await expect(page).toHaveURL(/\/sites\/3\/rendered$/);
  await expect(page.getByRole("link", { name: "Run 42" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Run 41" })).toHaveCount(0);
});

test("Page and Inventory Remove, Restore, and Delete remain distinct", async ({ page }) => {
  await mockApi(page);
  let pageState: "active" | "suppressed" = "active";
  let pageExists = true;
  let inventorySuppressed = false;
  let inventoryExists = true;

  await page.route(/\/api\/sites\/3\/pages(?:\?.*)?$/, async (route) => {
    const requested = new URL(route.request().url()).searchParams.get("workspace_state") ?? "active";
    const visible = pageExists && (requested === "all" || requested === pageState);
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ items: visible ? [{ ...persistentPage.page, workspace_state: pageState, suppressed_at: pageState === "suppressed" ? "2026-08-25T00:00:00Z" : null }] : [], total: visible ? 1 : 0, limit: 50, offset: 0 }) });
  });
  await page.route("**/api/sites/3/pages/2/workspace-state", async (route) => {
    pageState = (await route.request().postDataJSON()).workspace_state;
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ ...persistentPage, page: { ...persistentPage.page, workspace_state: pageState, suppressed_at: pageState === "suppressed" ? "2026-08-25T00:00:00Z" : null } }) });
  });
  await page.route("**/api/sites/3/pages/bulk-delete", async (route) => {
    expect((await route.request().postDataJSON()).resource_ids).toEqual([2]);
    pageExists = false;
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ selected: 1, changed: 1, unchanged: 0, rejected: 0 }) });
  });
  await page.route(/\/api\/sites\/3\/inventory(?:\?.*)?$/, async (route) => {
    const requested = new URL(route.request().url()).searchParams.get("visibility") ?? "active";
    const state = inventorySuppressed ? "suppressed" : "active";
    const visible = inventoryExists && (requested === "all" || requested === state);
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ items: visible ? [{ normalized_url: "https://example.com/pricing", resource_id: 2, source_count: 2, source_types: ["manual", "sitemap"], sources: [{ id: 4, name: "Main sitemap", type: "sitemap", entry_id: 6, raw_url: "https://example.com/pricing" }, { id: 7, name: "Manual URLs", type: "manual", entry_id: 8, raw_url: "/pricing" }], scope_decision: "crawlable", validation_state: "valid", sitemap_lastmod: null, latest_scan_status: "completed", latest_fetch_date: "2026-08-25T00:00:00Z", classification: "source_and_crawl", suppression_id: inventorySuppressed ? 15 : null, is_suppressed: inventorySuppressed, suppressed_at: inventorySuppressed ? "2026-08-25T00:00:00Z" : null }] : [], total: visible ? 1 : 0, limit: 50, offset: 0 }) });
  });
  await page.route("**/api/sites/3/inventory/suppressions", async (route) => {
    inventorySuppressed = true;
    await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ id: 15 }) });
  });
  await page.route("**/api/sites/3/inventory/suppressions/15", async (route) => {
    inventorySuppressed = false;
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ deleted_suppression_id: 15 }) });
  });
  await page.route("**/api/sites/3/inventory/suppressions/bulk", async (route) => {
    inventorySuppressed = true;
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ selected: 1, changed: 1, unchanged: 0, rejected: 0 }) });
  });
  await page.route("**/api/sites/3/inventory/suppressions/bulk-restore", async (route) => {
    inventorySuppressed = false;
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ selected: 1, changed: 1, unchanged: 0, rejected: 0 }) });
  });
  await page.route("**/api/sites/3/inventory/bulk-delete", async (route) => {
    expect((await route.request().postDataJSON()).entry_ids).toEqual([6]);
    inventoryExists = false;
    inventorySuppressed = false;
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ selected: 1, changed: 1, unchanged: 0, rejected: 0 }) });
  });

  await page.goto("/sites/3/pages");
  await page.getByRole("button", { name: "Remove", exact: true }).click();
  await page.getByRole("button", { name: "Remove from Site Pages" }).click();
  await expect(page.getByText("https://example.com/pricing")).toHaveCount(0);
  await page.getByLabel("Site Page state").selectOption("suppressed");
  await expect(page.getByText("https://example.com/pricing")).toBeVisible();
  await page.getByRole("button", { name: "Restore", exact: true }).click();
  await page.getByRole("button", { name: "Restore to Site Pages" }).click();
  await expect(page.getByText("https://example.com/pricing")).toHaveCount(0);
  await page.getByLabel("Site Page state").selectOption("active");
  await expect(page.getByText("https://example.com/pricing")).toBeVisible();
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await page.getByRole("button", { name: "Delete Page workspace" }).click();
  await expect(page.getByText("https://example.com/pricing")).toHaveCount(0);
  await page.getByLabel("Site Page state").selectOption("suppressed");
  await expect(page.getByText("https://example.com/pricing")).toHaveCount(0);

  await page.goto("/sites/3/inventory");
  await page.getByRole("button", { name: "Remove", exact: true }).click();
  await page.getByRole("button", { name: "Remove from Inventory" }).click();
  await expect(page.getByText("https://example.com/pricing")).toHaveCount(0);
  await page.getByLabel("Inventory visibility").selectOption("suppressed");
  await expect(page.getByText("https://example.com/pricing")).toBeVisible();
  await page.getByRole("button", { name: "Restore", exact: true }).click();
  await page.getByRole("button", { name: "Restore to Inventory" }).click();
  await expect(page.getByText("https://example.com/pricing")).toHaveCount(0);
  await page.getByLabel("Inventory visibility").selectOption("active");
  await expect(page.getByText("https://example.com/pricing")).toBeVisible();
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await page.getByRole("button", { name: "Delete from current Inventory" }).click();
  await expect(page.getByText("https://example.com/pricing")).toHaveCount(0);
  await page.getByLabel("Inventory visibility").selectOption("suppressed");
  await expect(page.getByText("https://example.com/pricing")).toHaveCount(0);
});

test("Sources support loaded-page selection and one bulk refresh request", async ({ page }) => {
  await mockApi(page);
  let selectedSourceIds: number[] = [];
  const source = (id: number, name: string, url: string) => ({
    id,
    website_property_id: 3,
    parent_source_id: null,
    root_source_id: null,
    source_type: "sitemap",
    name,
    source_url: url,
    normalized_source_url: url,
    is_active: true,
    discovery_mode: "configured",
    settings_json: {},
    last_refresh_status: "completed",
    last_refresh_started_at: "2026-08-25T00:00:00Z",
    last_refresh_finished_at: "2026-08-25T00:00:01Z",
    last_successful_refresh_at: "2026-08-25T00:00:01Z",
    last_http_status: 200,
    last_error_type: null,
    last_error_message: null,
    created_at: "2026-08-25T00:00:00Z",
    updated_at: "2026-08-25T00:00:01Z",
    current_entry_count: 10,
  });
  await page.route("**/api/sites/3/sources?*", async (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          source(4, "Main sitemap", "https://example.com/sitemap.xml"),
          source(7, "Secondary sitemap", "https://example.com/secondary.xml"),
        ],
        total: 2,
        limit: 100,
        offset: 0,
      }),
    }),
  );
  await page.route("**/api/sites/3/sources/bulk-refresh", async (route) => {
    selectedSourceIds = (await route.request().postDataJSON()).source_ids;
    await route.fulfill({ status: 202, contentType: "application/json", body: "[]" });
  });
  await page.route("**/api/jobs?*job_type=source_refresh*", async (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ items: [], total: 0, limit: 100, offset: 0 }),
    }),
  );

  await page.goto("/sites/3/sources");
  await page
    .getByLabel("Select all refreshable Sources on this loaded page")
    .check();
  await expect(page.getByText("2 Sources selected")).toBeVisible();
  await page.getByRole("button", { name: "Refresh selected" }).click();
  await expect.poll(() => selectedSourceIds).toEqual([4, 7]);
});

test("observability details are human-readable before raw evidence", async ({ page }) => {
  await mockApi(page);
  for (const viewport of [{ width: 375, height: 812 }, { width: 768, height: 1024 }, { width: 1024, height: 768 }, { width: 1440, height: 960 }]) {
    await page.setViewportSize(viewport);
    await page.goto("/sites/3/performance/observations/12");
    await expect(page.getByRole("heading", { name: "Real-user experience" })).toBeVisible();
    await expect(page.getByText("URL-level field data unavailable")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Site-origin context" })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  }
  await page.getByRole("link", { name: /View exact raw JSON/ }).click();
  await expect(page).toHaveURL(/\/performance\/evidence\/12$/);
  await expect(page.getByRole("heading", { name: "Raw provider evidence" })).toBeVisible();
  await page.goto("/sites/3/accessibility/observations/12");
  await expect(page.getByRole("heading", { name: "Accessibility observation" })).toBeVisible();
  await page.getByRole("button", { name: /Buttons must have discernible text/ }).click();
  await expect(page.getByText("Fix the missing accessible name.")).toBeVisible();
  await page.getByRole("link", { name: /View exact raw detector JSON/ }).click();
  await expect(page).toHaveURL(/\/accessibility\/evidence\/12$/);
  await expect(page.getByRole("heading", { name: "Raw Accessibility evidence" })).toBeVisible();
});

test("Performance observation deletion removes evidence while retaining its Run", async ({ page }) => {
  await mockApi(page);
  let retained = true;
  const run = performanceRun();
  await page.route("**/api/sites/3/performance-runs/4**", async (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify({ ...run, id: 4, observations: { items: retained ? [performanceObservation()] : [], total: retained ? 1 : 0, limit: 500, offset: 0 } }) }));
  await page.route("**/api/sites/3/performance-observations/12/deletion-preview", async (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify({ can_delete: true, reason: null, observation_id: 12, run_id: 4, provider: "crux", dimension: "PHONE", outcome: "ready", observed_at: "2026-08-20T00:00:00Z", target_kind: "url", requested_target: "https://example.com/pricing", payload_present: true, payload_shared: false, payload_reference_count: 1, payload_raw_bytes: 1000, payload_stored_bytes: 500, raw_bytes_reclaimable: 1000, stored_bytes_reclaimable: 500 }) }));
  await page.route("**/api/sites/3/performance-observations/12", async (route) => {
    if (route.request().method() === "DELETE") { retained = false; await route.fulfill({ contentType: "application/json", body: JSON.stringify({ deleted_observation_id: 12, runs_deleted: 0, observations_deleted: 1, warnings: [] }) }); return; }
    await route.fallback();
  });
  await page.goto("/sites/3/performance/runs/4");
  await page.getByRole("link", { name: "Inspect result" }).click();
  await page.getByRole("button", { name: "Delete observation" }).click();
  await expect(page.getByRole("dialog", { name: "Delete Performance observation" })).toBeVisible();
  await page.getByRole("button", { name: "Delete permanently" }).click();
  await expect(page).toHaveURL(/\/performance\/runs\/4$/);
  await expect(page.getByRole("heading", { name: "Run 4" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Inspect result" })).toHaveCount(0);
});

test("Accessibility Run deletion requires its exact phrase and refreshes the workspace", async ({ page }) => {
  await mockApi(page);
  let retained = true;
  const run = accessibilityRun();
  await page.route("**/api/sites/3/accessibility-runs/51/deletion-preview", async (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify({ can_delete: true, reason: null, run_id: 51, status: "completed", created_at: "2026-08-20T00:00:00Z", finished_at: "2026-08-20T00:01:00Z", completed_count: 1, ready_count: 1, failed_count: 0, retained_observation_count: 1, deleted_observation_count: 0, rule_rows_removed: 1, node_rows_removed: 1, payload_blobs_referenced: 1, exclusive_payload_blobs: 1, shared_payload_blobs: 0, raw_bytes_reclaimable: 1000, stored_bytes_reclaimable: 500, background_jobs_removed: 1, job_events_removed: 2 }) }));
  await page.route("**/api/sites/3/accessibility-runs/51**", async (route) => {
    if (new URL(route.request().url()).pathname.endsWith("/deletion-preview")) { await route.fallback(); return; }
    if (route.request().method() === "DELETE") { retained = false; await route.fulfill({ contentType: "application/json", body: JSON.stringify({ deleted_run_id: 51, runs_deleted: 1, observations_deleted: 1, warnings: [] }) }); return; }
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ ...run, observations: { items: [accessibilityObservation()], total: 1, limit: 500, offset: 0 } }) });
  });
  await page.route("**/api/sites/3/accessibility-runs**", async (route) => {
    if (new URL(route.request().url()).pathname !== "/api/sites/3/accessibility-runs") { await route.fallback(); return; }
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ items: retained ? [run] : [], total: retained ? 1 : 0, limit: 25, offset: 0 }) });
  });
  await page.goto("/sites/3/accessibility/runs/51");
  await page.getByRole("button", { name: "Delete run" }).click();
  const confirmation = page.getByRole("textbox");
  await confirmation.fill("DELETE ACCESSIBILITY RUN 51");
  await page.getByRole("button", { name: "Delete permanently" }).click();
  await expect(page).toHaveURL(/\/accessibility\?view=runs$/);
  await expect(page.getByText("No Accessibility runs")).toBeVisible();
});

test("destructive evidence dialog remains accessible at supported widths", async ({ page }) => {
  await mockApi(page);
  await page.route("**/api/sites/3/performance-observations/12/deletion-preview", async (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify({ can_delete: true, reason: null, observation_id: 12, run_id: 4, provider: "crux", dimension: "PHONE", outcome: "ready", observed_at: "2026-08-20T00:00:00Z", target_kind: "url", requested_target: "https://example.com/pricing", payload_present: true, payload_shared: false, payload_reference_count: 1, payload_raw_bytes: 1000, payload_stored_bytes: 500, raw_bytes_reclaimable: 1000, stored_bytes_reclaimable: 500 }) }));
  for (const width of [375, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: width === 375 ? 812 : 900 });
    await page.goto("/sites/3/performance/observations/12");
    const trigger = page.getByRole("button", { name: "Delete observation" });
    await trigger.click();
    const dialog = page.getByRole("dialog", { name: "Delete Performance observation" });
    await expect(dialog).toBeVisible();
    await expect(page.getByRole("button", { name: "Close deletion dialog" })).toBeFocused();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    await page.keyboard.press("Tab");
    expect(await page.evaluate(() => document.querySelector('[role="dialog"]')?.contains(document.activeElement))).toBe(true);
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(trigger).toBeFocused();
  }
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
  await expect(page.getByRole("alert")).toContainText("Browser rendering was rate limited");
  const renderedTable = page.getByRole("table");
  await expect(renderedTable.getByText("HTTP error", { exact: true })).toBeVisible();
  await expect(renderedTable.getByText("Rate limited", { exact: true })).toBeVisible();
  await expect(renderedTable.getByText("Not attempted - host throttled", { exact: true })).toBeVisible();
  await page.getByLabel("Rendered capture state").selectOption("completed_with_warnings");
  await expect(page).toHaveURL(/render_state=completed_with_warnings/);
  await page.getByRole("link", { name: /Open rendered evidence/ }).first().click();
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
  await expect(page.getByText("structured-content-v2 / canonical-document-v1")).toBeVisible();
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
        expected_version: "scan-projection-v2",
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

test("modern Scan Render authority shows queued targets before attempts", async ({ page }) => {
  await mockApi(page);
  await page.route("**/api/scans/1", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        ...scan,
        status: "completed",
        website_property_id: 3,
        website_property_name: "Example Site",
        rendered_attempted_count: 99,
        rendered_completed_count: 99,
        render_run_id: 77,
        render_run_status: "queued",
        render: scanRenderSummary({ authority: "render_run", render_run_id: 77, status: "queued", selected_count: 2, target_count: 2, unattempted_target_count: 2 }),
        scope_config: { ...scope, render_mode: "all_eligible" },
      }),
    });
  });

  await page.goto("/scans/1");

  const summary = page.getByRole("region", { name: "Scan render execution summary" });
  await expect(summary).toContainText("Browser Render Run #77");
  await expect(summary).toContainText("Queued");
  await expect(summary).toContainText("Targets2");
  await expect(summary).toContainText("Attempted0");
  await expect(summary.getByRole("link", { name: "Open Render Run" })).toHaveAttribute("href", "/sites/3/rendered/runs/77");
  await expect(page.getByRole("tab", { name: /Rendered 2/ })).toBeVisible();
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
  await expect(page.getByText("scan-comparison-v3")).toBeVisible();

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

async function captureReadmeScreenshot(page: Page, outputDir: string, filename: string) {
  await expect(page.locator("text=Loading")).toHaveCount(0);
  await page.screenshot({ path: path.join(outputDir, filename), fullPage: false });
}

async function mockReadmePresentationApi(page: Page) {
  const exampleSite = {
    ...site,
    name: "Example Commerce",
    base_url: "https://example.test/",
    normalized_base_url: "https://example.test/",
    description: "A fictional commerce catalog used for deterministic documentation captures.",
    platform_key: "Commerce CMS",
    display_timezone: "UTC",
    total_scan_count: 6,
  };
  const clock = (value: string | null, sourceScanId: number | null = null) => ({
    latest_observed_at: value,
    latest_completed_at: value,
    oldest_current_observation_at: value,
    newest_current_observation_at: value,
    source_run_id: null,
    source_scan_id: sourceScanId,
    source_comparison_id: null,
    source_status: value ? "completed" : null,
  });
  const coverage = (observed: number, eligible: number) => ({
    observed,
    eligible,
    ratio: eligible ? observed / eligible : null,
  });

  await page.route("**/api/sites/3/intelligence", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        site_id: 3,
        page_population: { active_page_total: 428, suppressed_page_total: 9, workspace_page_total: 437, workflow_counts: { approved: 312, needs_review: 41, unreviewed: 75 } },
        scan: { present: true, id: 6, status: "completed", created_at: "2026-09-02T02:00:00Z", started_at: "2026-09-02T02:00:03Z", finished_at: "2026-09-02T02:12:18Z", discovered_count: 441, fetched_count: 425, failed_count: 3, skipped_count: 13, stop_reason: "queue_empty", fatal_error_message: null, active_page_observed: coverage(425, 428), active_page_fetched: coverage(422, 428), clock: clock("2026-09-02T02:12:18Z", 6) },
        comparison: { present: true, comparison_id: 7, build_id: 9, baseline_scan_id: 5, target_scan_id: 6, comparison_version: "scan-comparison-v3", algorithm_identity: "scan-comparison-v3", page_counts: { substantive_change: 8, metadata_change: 3, technical_change: 27, normalization_only: 11, no_tracked_change: 376, not_applicable: 3 }, resource_counts: { changed: 18 }, link_counts: { changed: 34 }, clock: { ...clock("2026-09-02T02:13:01Z"), source_comparison_id: 7 } },
        structured_content: { extractor_version: "structured-content-v2", extractor_config_version: "canonical-document-v1", markdown_renderer_version: "structured-markdown-v1", active_pages: 428, eligible_retained_html: 422, ready: 415, partial: 2, unavailable: 0, not_prepared: 5, ineligible: 6, coverage: coverage(417, 422), clock: clock("2026-09-02T02:12:18Z", 6) },
        render: { latest_run: { present: true, id: 14, status: "completed", target_count: 120, created_at: "2026-09-02T03:00:00Z", started_at: "2026-09-02T03:00:01Z", finished_at: "2026-09-02T03:09:42Z" }, retained_coverage: coverage(389, 428), successful: 116, no_content: 0, redirect: 1, http_error: 1, rate_limited: 0, not_attempted_host_throttled: 0, technical_failure: 2, clock: clock("2026-09-02T03:09:42Z") },
        performance: { contexts: [{ provider: "pagespeed", dimension: "mobile", target_kind: "url", provider_adapter_version: "pagespeed-provider-v2", normalization_version: "performance-normalization-v1", ready: 86, unavailable: 4, failed: 0, coverage: coverage(90, 428), clock: clock("2026-09-02T04:18:00Z") }], latest_run_id: 18, latest_run_status: "completed", clock: clock("2026-09-02T04:18:00Z") },
        accessibility: { coverage: coverage(176, 856), ready_pages: 171, failed_pages: 5, pages_with_violations: 23, violation_rules: 14, affected_nodes: 67, needs_review_rules: 6, clock: clock("2026-09-02T05:21:00Z") },
        sources: { active_source_count: 3, inactive_source_count: 0, current_inventory_count: 436, suppressed_inventory_count: 7, latest_refresh_status: "completed", latest_refresh_finished_at: "2026-09-02T01:48:00Z" },
        findings: { detected: 17, unknown: 4, acknowledged_detected: 5, unresolved_total: 16, latest_evaluation_id: 22, latest_evidence_horizon_at: "2026-09-02T05:21:00Z", latest_evaluation_completed_at: "2026-09-02T05:22:12Z" },
        activity: { active_job_count: 0, queued_count: 0, running_count: 0, jobs: [] },
        collection_coverage: [{ evidence_domain: "render", target_mode: "missing_current", context_identity: "render:desktop", context: {}, active_page_count: 428, active_page_universe_sha256: "a".repeat(64), eligible: 428, covered: 389, in_flight: 0, active_collection: 0, missing: 39, ineligible: 0, batch_size: 250, estimated_batch_count: 1, collectable: true, non_collectable_reason: null }],
      }),
    });
  });

  await page.route(/\/api\/sites\/3\/findings(?:\?.*)?$/, async (route) => {
    const rows = [
      [41, 101, "https://example.test/products/discontinued-lamp", "page_http_error", "Page HTTP error", "high", { http_status: 404 }],
      [42, 102, "https://example.test/guides/lighting", "page_broken_internal_links", "Broken internal links", "high", { broken_target_count: 4, occurrence_count: 7 }],
      [43, 103, "https://example.test/products/desk-lamp", "page_noindex", "Page is noindexed", "medium", { robots_directives: ["noindex"] }],
      [44, 104, "https://example.test/categories/lighting", "sitemap_page_http_error", "Sitemap Page HTTP error", "medium", { http_status: 500 }],
      [45, 105, "https://example.test/products/floor-lamp", "page_internal_links_to_redirects", "Internal links to redirects", "low", { redirect_target_count: 2, occurrence_count: 5 }],
    ].map(([id, resourceId, pageUrl, findingType, label, severity, summary], index) => ({
      id, web_resource_id: resourceId, page_url: pageUrl, finding_type: findingType,
      finding_label: label, logical_key_version: `${findingType}-key-v1`, fingerprint_sha256: String(index + 1).repeat(64),
      condition_state: "detected", current_severity: severity,
      first_detected_at: "2026-09-02T05:22:12Z", last_detected_at: "2026-09-02T05:22:12Z",
      last_evaluated_evidence_at: "2026-09-02T05:21:00Z", resolved_at: null, reopened_at: null,
      acknowledged_at: index === 4 ? "2026-09-02T06:00:00Z" : null, current_assessment_id: 200 + index,
      page_workspace_state: "active", current_evidence_summary: summary,
    }));
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ items: rows, total: rows.length, limit: 50, offset: 0 }) });
  });

  await page.route("**/api/sites/3/pages/2/change-history**", async (route) => {
    const history = [
      { snapshot_id: 109, scan_id: 6, scan_status: "completed", observed_at: "2026-09-02T02:05:10Z", http_status: 200, fetch_state: "fetched", change_label: "Document and metadata changed", changed_flags: ["document_content", "title", "description"], intervening_scan_count: 0, intervening_unsuccessful_observation_count: 0 },
      { snapshot_id: 92, scan_id: 5, scan_status: "completed", observed_at: "2026-08-26T02:04:51Z", http_status: 200, fetch_state: "fetched", change_label: "Technical change", changed_flags: ["dependency", "raw_source"], intervening_scan_count: 0, intervening_unsuccessful_observation_count: 0 },
      { snapshot_id: 73, scan_id: 4, scan_status: "completed_with_errors", observed_at: "2026-08-19T02:06:22Z", http_status: 200, fetch_state: "fetched", change_label: "No tracked change", changed_flags: [], intervening_scan_count: 1, intervening_unsuccessful_observation_count: 1 },
      { snapshot_id: 51, scan_id: 2, scan_status: "completed", observed_at: "2026-08-05T02:03:18Z", http_status: 200, fetch_state: "fetched", change_label: "First successful observation", changed_flags: [], intervening_scan_count: 0, intervening_unsuccessful_observation_count: 0 },
    ];
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ items: history, total: history.length, limit: 50, offset: 0 }) });
  });

  await page.route("**/api/sites/3/pages/2", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ ...persistentPage, site_name: "Example Commerce", page: { ...persistentPage.page, normalized_url: "https://example.test/products/desk-lamp", latest_title: "Adjustable Desk Lamp", owner_label: "Merchandising", workflow_status: "approved", observation_count: 6, first_observed_at: "2026-08-05T02:03:18Z", latest_observed_at: "2026-09-02T02:05:10Z", latest_snapshot_id: 109, latest_scan_id: 6 } }),
    });
  });

  await page.route("**/api/sites/3/scans**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          { ...scan, id: 6, status: "completed", website_property_id: 3, website_property_name: "Example Commerce", website_property_base_url: "https://example.test/", starting_url: "https://example.test/", created_at: "2026-09-02T02:00:00Z", finished_at: "2026-09-02T02:12:18Z", discovered_count: 441, fetched_count: 425, failed_count: 3 },
          { ...scan, id: 5, status: "completed", website_property_id: 3, website_property_name: "Example Commerce", website_property_base_url: "https://example.test/", starting_url: "https://example.test/", created_at: "2026-08-26T02:00:00Z", finished_at: "2026-08-26T02:11:44Z", discovered_count: 432, fetched_count: 427, failed_count: 2 },
          { ...scan, id: 1, status: "completed", website_property_id: 3, website_property_name: "Example Commerce", website_property_base_url: "https://example.test/", starting_url: "https://example.test/", finished_at: "2026-07-30T01:01:00Z" },
        ], total: 3, limit: 100, offset: 0,
      }),
    });
  });

  await page.route("**/api/sites/3/comparisons/7/pages**", async (route) => {
    const rows = [
      [31, "https://example.test/products/desk-lamp", "present_in_both", "substantive_change", "different", "different", "same", "different", 4],
      [32, "https://example.test/products/discontinued-lamp", "not_observed_in_target", "not_applicable", "not_applicable", "not_applicable", "not_applicable", "not_applicable", 0],
      [33, "https://example.test/guides/lighting", "present_in_both", "technical_change", "same", "same", "different", "different", 2],
      [34, "https://example.test/categories/new-arrivals", "present_in_both", "metadata_change", "same", "different", "same", "same", 1],
    ].map(([resourceId, normalizedUrl, presenceState, primaryClass, contentState, metadataState, technicalState, sourceState, changedFields], index) => ({
      id: index + 1, resource_id: resourceId, normalized_url: normalizedUrl, host: "example.test", path: new URL(String(normalizedUrl)).pathname,
      presence_state: presenceState, change_state: primaryClass, primary_change_class: primaryClass, content_state: contentState,
      document_content_state: contentState, metadata_state: metadataState, technical_state: technicalState, exact_source_state: sourceState,
      head_state: metadataState, changed_field_count: changedFields, baseline_http_status: 200,
      target_http_status: presenceState === "not_observed_in_target" ? null : 200, response_time_ms_delta: null, network_bytes_delta: null,
    }));
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ items: rows, total: rows.length, limit: 50, offset: 0, comparison_build_id: 9, comparison_version: "scan-comparison-v3" }) });
  });

  await page.route(/\/api\/scans\/1\/graph(?:\?.*)?$/, async (route) => {
    const paths = ["/", "/products/", "/products/desk-lamp", "/products/floor-lamp", "/products/pendant-light", "/categories/", "/categories/lighting", "/guides/", "/guides/lighting", "/about/", "/support/", "/support/shipping"];
    const nodes = paths.map((urlPath, index) => ({
      ...graph.nodes[index === 0 ? 0 : 1], id: `snapshot:${index + 1}`, snapshot_id: index + 1, resource_id: index + 1,
      requested_url: `https://example.test${urlPath}`, final_url: `https://example.test${urlPath}`,
      page_title: index === 0 ? "Example Commerce" : urlPath.split("/").filter(Boolean).at(-1)?.replace(/-/g, " "),
      host: "example.test", path: urlPath, crawl_depth: urlPath.split("/").filter(Boolean).length,
      inbound_occurrence_count: index === 0 ? 0 : 2 + (index % 4), inbound_source_page_count: index === 0 ? 0 : 1 + (index % 3),
      outbound_occurrence_count: index < 8 ? 3 : 1, outbound_target_page_count: index < 8 ? 3 : 1,
      is_scan_seed: index === 0, is_starting_url: index === 0,
    }));
    const edges = nodes.slice(1).map((node, index) => ({
      ...graph.edges[0], id: `1-${node.snapshot_id}`, source: "snapshot:1", target: node.id,
      source_snapshot_id: 1, target_snapshot_id: node.snapshot_id, target_resource_id: node.resource_id,
      occurrence_count: 1 + (index % 3), sample_anchor_texts: [node.page_title], dom_regions: index % 4 === 0 ? { navigation: 1 } : { main: 1 },
    }));
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ ...graph, scan: { ...graph.scan, starting_url: "https://example.test/", website_property_id: 3, website_property_name: "Example Commerce" }, summary: { ...graph.summary, total_available_nodes: nodes.length, total_available_edges: edges.length, returned_nodes: nodes.length, returned_edges: edges.length, fetched_nodes: nodes.length, total_occurrences: edges.reduce((total, edge) => total + edge.occurrence_count, 0) }, nodes, edges }) });
  });

  await page.route("**/api/sites/3", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(exampleSite) });
  });
  await page.route(/\/api\/sites(?:\?.*)?$/, async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ items: [{ ...exampleSite, latest_scan_id: 6, latest_scan_status: "completed", latest_scan_date: "2026-09-02T02:00:00Z", latest_scan_discovered_count: 441, latest_scan_failed_count: 3 }], total: 1, limit: 25, offset: 0 }) });
  });
}

async function mockComparisonApi(
  page: Page,
  baselineScanId = 1,
  targetScanId = 2,
  pageResultCount = 1,
) {
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
    comparison_version: "scan-comparison-v3",
    algorithm_identity: "scan-comparison-v3|source-signals-v1|document-content-v2|incapsula-cb-v1|page-v2|resource-v1|link-v1|scan-projection-v2",
    status: "ready",
    baseline_projection_build_id: 4,
    target_projection_build_id: 5,
    baseline_projection_version: "scan-projection-v2",
    target_projection_version: "scan-projection-v2",
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
    page_result_count: pageResultCount,
    resource_result_count: 0,
    link_result_count: 0,
    created_at: "2026-08-07T12:00:00Z",
  };
  const comparison = {
    id: 7,
    website_property_id: 3,
    baseline_scan_id: baselineScanId,
    target_scan_id: targetScanId,
    current_build_id: 9,
    created_at: "2026-08-07T12:00:00Z",
    updated_at: "2026-08-07T12:00:01Z",
    baseline_scan: scanSide(baselineScanId, "2026-08-06T12:00:00Z"),
    target_scan: scanSide(targetScanId, "2026-08-07T12:00:00Z"),
    current_build: build,
    active_build: null,
  };
  const overview = {
    comparison,
    summary: {
      pages: { total: pageResultCount, not_observed_in_target: 1 },
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
          scanSide(targetScanId, "2026-08-07T12:00:00Z"),
          scanSide(baselineScanId, "2026-08-06T12:00:00Z"),
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
        comparison_version: "scan-comparison-v3",
      }),
    });
  });
}

async function mockApi(page: Page) {
  let scanStatus: "running" | "completed" = "running";
  let siteActive = true;
  let pageNote: Record<string, unknown> | null = null;

  await page.route("**/api/sites/3/performance-observations/12/presentation", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ observation: performanceObservation({ outcome: "unavailable", error_type: "no_field_data", error_message: "No qualifying dataset." }), metrics: [], opportunities: [], diagnostics: [], origin_context: performanceObservation({ id: 13, target_kind: "origin", requested_target: "https://example.com", provider_target: "https://example.com", outcome: "ready" }), origin_metrics: [{ key: "lcp", label: "Largest Contentful Paint", value: 2200, unit: "ms", formatted_value: "2.20 s", assessment: "good", histogram: [{ density: 0.8 }, { density: 0.15 }, { density: 0.05 }] }], presentation_error: null }) });
  });
  await page.route("**/api/sites/3/performance-observations/12", async (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify(performanceObservation()) }));
  await page.route("**/api/performance-observations/12/payload", async (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify({ exact: true }) }));
  await page.route("**/api/sites/3/accessibility-observations/12/rules/31/nodes**", async (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify({ items: [{ id: 51, position: 0, impact: "critical", target_json: ["#submit"], html_snippet: "<button id=\"submit\"></button>", html_original_length: 29, html_truncated: false, failure_summary: "Fix the missing accessible name.", node_evidence_sha256: "f".repeat(64) }], total: 1, limit: 25, offset: 0 }) }));
  await page.route("**/api/sites/3/accessibility-observations/12/rules**", async (route) => {
    if (new URL(route.request().url()).pathname !== "/api/sites/3/accessibility-observations/12/rules") { await route.fallback(); return; }
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ items: [{ id: 31, accessibility_observation_id: 12, position: 0, rule_id: "button-name", result_type: "violation", impact: "critical", description: "Buttons must have discernible text", help: "Buttons must have discernible text", help_url: "https://dequeuniversity.com/rules/axe/4.12/button-name", tags_json: ["wcag2a", "wcag412"], node_count: 1, rule_evidence_sha256: "e".repeat(64) }], total: 1, limit: 200, offset: 0 }) });
  });
  await page.route("**/api/sites/3/accessibility-observations/12", async (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify(accessibilityObservation()) }));
  await page.route("**/api/accessibility-observations/12/raw", async (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify({ exact: true }) }));

  await page.route("**/api/accessibility/capabilities", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ axe_core_version: "4.12.1", detector_bundle_sha256: "a".repeat(64), integration_version: "accessibility-engine-v1", normalization_version: "accessibility-normalization-v1", ruleset_profile: "wcag22-aa-v1", ruleset_rule_count: 62, ruleset_sha256: "b".repeat(64), default_page_limit: 50, hard_page_limit: 250, absolute_page_limit: 250, max_audit_count: 500, profiles: {} }) });
  });
  await page.route("**/api/sites/3/accessibility/summary", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ pages_audited: 0, profiles_audited: 0, pages_with_violations: 0, violation_rules: 0, affected_nodes: 0, needs_review_rules: 0, impact_counts: {}, failed_latest: 0, latest_observed_at: null }) });
  });
  await page.route("**/api/sites/3/accessibility-runs**", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ items: [], total: 0, limit: 25, offset: 0 }) });
  });
  await page.route("**/api/sites/3/accessibility/pages**", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ items: [], total: 0, limit: 100, offset: 0 }) });
  });
  await page.route("**/api/sites/3/accessibility/rules**", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ items: [], total: 0, limit: 50, offset: 0 }) });
  });

  await page.route("**/api/sites/3/performance/providers", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ pagespeed: { configured: false, adapter_version: "pagespeed-provider-v2" }, crux: { configured: false, adapter_version: "crux-provider-v1" }, normalization_version: "performance-normalization-v1", default_page_limit: 50, hard_page_limit: 250, absolute_page_limit: 250, max_provider_requests: 1002, crux_queries_per_minute: 120 }) });
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
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ scan_id: 1, scan_status: "completed", expected_version: "scan-projection-v2", projection_source: "materialized", projection_status: "ready", current_build: { id: 9, status: "ready" }, active_build: null, latest_build: { id: 9, status: "ready" }, can_build: false, can_rebuild: true }) });
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
    const rendered = (overrides: Record<string, unknown>) => ({ id: 31, snapshot_id: 9, resource_id: 2, capture_state: "completed_with_warnings", static_final_url: "https://example.com/pricing", browser_final_url: "https://example.com/pricing", page_title: "Pricing", static_http_status: 200, navigation_http_status: 200, error_type: null, error_message: null, duration_ms: 450, warning_count: 1, page_error_count: 0, blocked_request_count: 0, console_message_count: 0, has_viewport_screenshot: true, has_full_page_screenshot: false, has_rendered_dom: true, finished_at: "2026-08-06T01:00:01Z", ...overrides });
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ items: [
      rendered({}),
      rendered({ id: 32, snapshot_id: 10, navigation_http_status: 404, capture_state: "failed", error_type: "navigation_http_client_error", error_message: "Main-document navigation returned HTTP 404.", has_viewport_screenshot: false, has_rendered_dom: false }),
      rendered({ id: 33, snapshot_id: 11, navigation_http_status: 429, capture_state: "failed", error_type: "navigation_rate_limited", error_message: "Main-document navigation was rate limited (HTTP 429).", has_viewport_screenshot: false, has_rendered_dom: false }),
      rendered({ id: 34, snapshot_id: 12, navigation_http_status: null, capture_state: "skipped", error_type: "host_rate_limit_circuit_open", error_message: "Browser capture was not attempted because repeated rate-limit responses opened the host render circuit.", has_viewport_screenshot: false, has_rendered_dom: false })
    ], total: 4, limit: 50, offset: 0, summary: { successful_renders: 1, no_content_responses: 0, redirect_responses: 0, http_error_responses: 1, rate_limited: 1, skipped_after_throttling: 1, technical_failures: 0, artifacts_retained: 2 } }) });
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

function scanRenderSummary(overrides: Record<string, unknown> = {}) {
  return {
    authority: "none",
    selected_count: 0,
    render_run_id: null,
    status: null,
    target_count: 0,
    attempted_count: 0,
    completed_count: 0,
    failed_count: 0,
    skipped_count: 0,
    blocked_request_count: 0,
    artifact_count: 0,
    retained_observation_count: 0,
    deleted_observation_count: 0,
    unattempted_target_count: 0,
    retained_artifact_count: 0,
    started_at: null,
    finished_at: null,
    legacy: false,
    ...overrides,
  };
}

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
  render: scanRenderSummary(),
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
    workspace_state: "active" as const,
    suppressed_at: null,
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

function performanceObservation(overrides: Record<string, unknown> = {}) {
  return { id: 12, performance_run_id: 4, website_property_id: 3, web_resource_id: 8, provider: "crux", provider_adapter_version: "crux-provider-v1", normalization_version: "performance-normalization-v1", target_kind: "url", requested_target: "https://example.com/pricing", provider_target: "https://example.com/pricing", dimension: "PHONE", outcome: "ready", metrics_json: { lcp: { value: 2200, unit: "ms" } }, normalized_sha256: "b".repeat(64), provider_analysis_at: null, provider_period_json: null, provider_product_version: null, observed_at: "2026-08-13T12:00:00Z", error_type: null, error_message: null, page_url: "https://example.com/pricing", payload_sha256: "a".repeat(64), payload_raw_byte_size: 100, payload_stored_byte_size: 80, ...overrides };
}

function performanceRun() {
  return { id: 41, website_property_id: 3, status: "completed", presentation_status: "completed", trigger: "site_workspace", configuration_json: { resource_ids: [8], providers: ["crux"], pagespeed_strategies: [], crux_form_factors: ["PHONE"], include_origin_crux: false }, target_count: 1, request_count: 1, completed_count: 1, ready_count: 1, unavailable_count: 0, failed_count: 0, retained_observation_count: 1, deleted_observation_count: 0, retained_ready_count: 1, retained_unavailable_count: 0, retained_failed_count: 0, deleted_ready_count: 0, deleted_unavailable_count: 0, deleted_failed_count: 0, created_at: "2026-08-20T00:00:00Z", started_at: "2026-08-20T00:00:00Z", finished_at: "2026-08-20T00:01:00Z", error_summary: null, job_id: 71 };
}

function accessibilityObservation() {
  return { id: 12, accessibility_run_id: 4, website_property_id: 3, web_resource_id: 8, requested_url: "https://example.com/pricing", final_url: "https://example.com/pricing", profile: "desktop", outcome: "ready", observed_at: "2026-08-13T12:00:00Z", axe_core_version: "4.12.1", detector_bundle_sha256: "a".repeat(64), integration_version: "accessibility-engine-v1", normalization_version: "accessibility-normalization-v1", ruleset_profile: "wcag22-aa-v1", ruleset_sha256: "b".repeat(64), browser_engine: "chromium", browser_version: "151", playwright_version: "1.55", profile_json: {}, violation_rule_count: 1, violation_node_count: 1, incomplete_rule_count: 0, incomplete_node_count: 0, pass_rule_count: 20, inapplicable_rule_count: 40, normalized_sha256: "c".repeat(64), error_type: null, error_message: null, page_url: "https://example.com/pricing", payload_sha256: "d".repeat(64), payload_raw_byte_size: 100, payload_stored_byte_size: 80 };
}

function accessibilityRun() {
  return { id: 51, website_property_id: 3, status: "completed", presentation_status: "completed", trigger: "site_workspace", configuration_json: { resource_ids: [8], profiles: ["desktop"] }, target_count: 1, observation_count: 1, completed_count: 1, ready_count: 1, failed_count: 0, retained_observation_count: 1, deleted_observation_count: 0, retained_ready_count: 1, retained_failed_count: 0, deleted_ready_count: 0, deleted_failed_count: 0, axe_core_version: "4.12.1", detector_bundle_sha256: "a".repeat(64), integration_version: "accessibility-engine-v1", normalization_version: "accessibility-normalization-v1", ruleset_profile: "wcag22-aa-v1", ruleset_rule_count: 62, ruleset_sha256: "b".repeat(64), created_at: "2026-08-20T00:00:00Z", started_at: "2026-08-20T00:00:00Z", finished_at: "2026-08-20T00:01:00Z", error_summary: null, job_id: 81 };
}

function renderRunFixture(id: number, trigger: string) {
  return {
    id,
    website_property_id: 3,
    source_scan_id: null,
    source_render_run_id: trigger === "rerender" ? 41 : null,
    status: "completed_with_errors",
    presentation_status: "completed_with_errors",
    trigger,
    configuration_json: { ...scope, render_mode: "all_eligible", render_max_pages: 3 },
    target_count: 3,
    attempted_count: 2,
    completed_count: 1,
    failed_count: 1,
    skipped_count: 1,
    blocked_request_count: 0,
    artifact_count: 3,
    retained_observation_count: 3,
    deleted_observation_count: 0,
    unattempted_target_count: 0,
    retained_artifact_count: 3,
    created_at: "2026-08-26T05:00:00Z",
    started_at: "2026-08-26T05:00:01Z",
    finished_at: "2026-08-26T05:01:00Z",
    error_summary: null,
    job_id: 90 + id,
    summary: { successful_renders: 1, no_content_responses: 0, redirect_responses: 0, http_error_responses: 0, rate_limited: 1, skipped_after_throttling: 1, technical_failures: 0, artifacts_retained: 3 },
  };
}

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
    artifact: { id: 5, extractor_version: "structured-content-v2", extractor_config_version: "canonical-document-v1", extraction_state: "ready", document_profile: "headed", section_count: 2, heading_count: 2, heading_counts: { h1: 1, h2: 1, h3: 0, h4: 0, h5: 0, h6: 0 }, document_word_count: 8, document_character_count: 80, document_text_sha256: "b".repeat(64), outline_sha256: "c".repeat(64), is_truncated: false, truncation_reasons: [], node_count: 5, canonical_document_sha256: "g".repeat(64), markdown_renderer_version: "structured-markdown-v1", markdown_sha256: "h".repeat(64), markdown_character_count: 80, created_at: "2026-08-06T01:00:01Z" },
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
