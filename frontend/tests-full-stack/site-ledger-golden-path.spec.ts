import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { writeFile } from "node:fs/promises";

const apiUrl = required("GOLDEN_PATH_API_URL");
const fixtureUrl = required("GOLDEN_PATH_FIXTURE_URL");
const resultPath = required("GOLDEN_PATH_RESULT_PATH");
const workspaceId = required("GOLDEN_PATH_WORKSPACE_ID");
const expectedTargetCopy = process.env.GOLDEN_PATH_EXPECTED_TARGET_COPY ?? "Version two product copy.";

type Json = Record<string, unknown> & {
  id: number;
  status: string;
  total: number;
  online_workers: number;
  fetched_count: number;
  resource_id: number;
  requested_url: string;
  normalized_url: string;
  scan_id: number;
  primary_change_class: string;
  raw_html_sha256: string | null;
  content_blob_id: number | null;
  extraction_state: string;
  document_text_sha256: string;
  outline_sha256: string;
  sections: Array<{ direct_text: string }>;
  items: Json[];
  scope_config: { allow_private_networks: boolean };
  comparison: Json;
  current_build: Json | null;
  active_build: Json | null;
  artifact: Json | null;
  diff_text: string | null;
};

type StructuredEvidence = {
  document_text_sha256: string;
  outline_sha256: string;
  sections: Array<{ direct_text: string }>;
};

type Evidence = { item: Json; observation: Json; structured: StructuredEvidence };

test("real Site Ledger stack preserves and compares deterministic crawl evidence", async ({ page, request }) => {
  const started = Date.now();
  const health = await getJson(request, `${apiUrl}/api/health`);
  expect(health.status).toBe("ok");
  const worker = await getJson(request, `${apiUrl}/api/jobs/worker-health`);
  expect(worker.online_workers).toBeGreaterThan(0);
  expect((await getJson(request, `${apiUrl}/api/sites?limit=10`)).total).toBe(0);

  const site = await postJson(request, `${apiUrl}/api/sites`, {
    name: "Golden Path Fixture",
    base_url: fixtureUrl,
    scope_config: {
      included_path_prefixes: ["/"],
      max_pages: 10,
      max_depth: 2,
      request_timeout_seconds: 5,
      static_max_attempts: 1,
      concurrent_requests_per_host: 1,
      user_agent: "SiteLedgerGoldenPath/1.0",
      allow_private_networks: true,
      enable_http_revalidation: false,
      enable_parse_reuse: true,
      render_mode: "none"
    }
  });
  expect(site.scope_config.allow_private_networks).toBe(true);

  const scan1Start = Date.now();
  const scan1Id = await startScanInUi(page, site.id);
  const scan1 = await waitForScan(request, scan1Id);
  const scan1Completed = Date.now();
  expect(scan1.status).toBe("completed");
  expect(scan1.fetched_count).toBe(4);
  await waitForProjection(request, scan1Id);
  const scan1Ready = Date.now();
  const pages1 = await getJson(request, `${apiUrl}/api/scans/${scan1Id}/pages?limit=50`);
  expect(pages1.total).toBe(4);
  const evidence1 = await collectEvidence(request, site.id, scan1Id);
  expect(evidence1["/"].structured.sections.some((section) => section.direct_text.includes("Version one product copy."))).toBe(true);

  const switchResponse = await request.post(`${fixtureUrl}/__fixture__/version/2`);
  expect(switchResponse.ok()).toBe(true);
  expect(await (await request.get(`${fixtureUrl}/`)).text()).toContain(expectedTargetCopy);

  const scan2Start = Date.now();
  const scan2Id = await startScanInUi(page, site.id);
  const scan2 = await waitForScan(request, scan2Id);
  const scan2Completed = Date.now();
  expect(scan2.status).toBe("completed");
  expect(scan2.fetched_count).toBe(5);
  await waitForProjection(request, scan2Id);
  const scan2Ready = Date.now();
  const evidence2 = await collectEvidence(request, site.id, scan2Id);
  expect(evidence2["/"].structured.sections.some((section) => section.direct_text.includes(expectedTargetCopy))).toBe(true);

  const comparison = await waitForAutomaticComparison(request, site.id, scan1Id, scan2Id);
  const comparisonId = comparison.comparison.id as number;
  const comparisonReady = Date.now();
  const pageResults = await getJson(request, `${apiUrl}/api/sites/${site.id}/comparisons/${comparisonId}/pages?changed_only=false&limit=50`);
  expect(pageResults.total).toBe(5);
  const byPath = Object.fromEntries(pageResults.items.map((item) => [new URL(item.normalized_url).pathname, item]));
  expect(byPath["/"].primary_change_class).toBe("substantive_change");
  expect(byPath["/pricing/"].primary_change_class).toBe("metadata_change");
  expect(byPath["/technical/"].primary_change_class).toBe("technical_change");
  expect(byPath["/unchanged/"].primary_change_class).toBe("no_tracked_change");
  expect(byPath["/new/"].primary_change_class).toBe("not_applicable");
  const technicalDiff = await getJson(request, `${apiUrl}/api/sites/${site.id}/comparisons/${comparisonId}/pages/${byPath["/technical/"].resource_id}/source-diff?mode=exact`);
  expect(technicalDiff.diff_text).toContain("build=1");
  expect(technicalDiff.diff_text).toContain("build=2");
  expect(evidence1["/unchanged/"].observation.content_blob_id).toBe(evidence2["/unchanged/"].observation.content_blob_id);
  expect(evidence1["/technical/"].observation.raw_html_sha256).not.toBe(evidence2["/technical/"].observation.raw_html_sha256);
  expect(evidence1["/technical/"].structured.document_text_sha256).toBe(evidence2["/technical/"].structured.document_text_sha256);
  expect(evidence1["/technical/"].structured.outline_sha256).toBe(evidence2["/technical/"].structured.outline_sha256);

  await page.goto(`/sites/${site.id}?tab=comparisons&comparison_id=${comparisonId}`);
  await expect(page.getByRole("heading", { name: `Scan ${scan1Id} to Scan ${scan2Id}` })).toBeVisible();
  await expect(page.getByText("scan-comparison-v2", { exact: true })).toBeVisible();
  await page.getByRole("tab", { name: /^Pages/ }).click();
  await page.getByLabel("Show all Pages").check();
  await page.getByRole("link", { name: `${fixtureUrl}/`, exact: true }).click();
  await expect(page.getByText("Substantive Change", { exact: true })).toBeVisible();
  await expect(page.getByText("Changed", { exact: true }).first()).toBeVisible();
  const observationLinks = page.getByRole("link", { name: /^Observation / });
  expect(await observationLinks.count()).toBe(2);
  const baselineHref = await observationLinks.nth(0).getAttribute("href");
  const targetHref = await observationLinks.nth(1).getAttribute("href");
  expect(baselineHref).toBeTruthy();
  expect(targetHref).toBeTruthy();
  await inspectObservationContent(page, baselineHref!, "Version one product copy.");
  await inspectObservationContent(page, targetHref!, expectedTargetCopy);

  await writeFile(resultPath, JSON.stringify({
    workspace_id: workspaceId,
    site_id: site.id,
    scan_1_id: scan1Id,
    scan_2_id: scan2Id,
    comparison_id: comparisonId,
    timings_ms: {
      total: comparisonReady - started,
      scan_1: scan1Completed - scan1Start,
      projection_1: scan1Ready - scan1Completed,
      scan_1_and_projection: scan1Ready - scan1Start,
      scan_2: scan2Completed - scan2Start,
      projection_2: scan2Ready - scan2Completed,
      scan_2_and_projection: scan2Ready - scan2Start,
      comparison: comparisonReady - scan2Ready
    }
  }, null, 2) + "\n", "utf-8");
});

async function startScanInUi(page: Page, siteId: number): Promise<number> {
  await page.goto(`/scans/new?site_id=${siteId}`);
  const start = page.getByRole("button", { name: "Start scan" });
  await expect(start).toBeEnabled();
  await start.click();
  await page.waitForURL(/\/scans\/\d+$/);
  return Number(new URL(page.url()).pathname.split("/").pop());
}

async function waitForScan(request: APIRequestContext, scanId: number): Promise<Json> {
  return poll(async () => {
    const scan = await getJson(request, `${apiUrl}/api/scans/${scanId}`);
    return ["completed", "completed_with_errors", "failed", "cancelled", "interrupted"].includes(scan.status) ? scan : null;
  }, `Scan ${scanId}`);
}

async function waitForProjection(request: APIRequestContext, scanId: number): Promise<Json> {
  return poll(async () => {
    const value = await getJson(request, `${apiUrl}/api/scans/${scanId}/projection`);
    if (value.current_build?.status === "ready") return value;
    if (value.active_build?.status === "failed") throw new Error(`Projection ${scanId} failed: ${JSON.stringify(value)}`);
    return null;
  }, `projection for Scan ${scanId}`);
}

async function waitForAutomaticComparison(request: APIRequestContext, siteId: number, baseline: number, target: number): Promise<Json> {
  return poll(async () => {
    const list = await getJson(request, `${apiUrl}/api/sites/${siteId}/comparisons?limit=100`);
    const item = list.items.find((candidate) => candidate.baseline_scan_id === baseline && candidate.target_scan_id === target);
    if (!item) return null;
    const value = await getJson(request, `${apiUrl}/api/sites/${siteId}/comparisons/${item.id}/status`);
    if (value.comparison.current_build?.status === "ready") return value;
    if (value.comparison.active_build?.status === "failed") throw new Error(`Comparison failed: ${JSON.stringify(value)}`);
    return null;
  }, "automatic adjacent comparison");
}

async function collectEvidence(request: APIRequestContext, siteId: number, scanId: number): Promise<Record<string, Evidence>> {
  const pages = await getJson(request, `${apiUrl}/api/scans/${scanId}/pages?limit=50`);
  const result: Record<string, Evidence> = {};
  for (const item of pages.items) {
    const path = new URL(item.requested_url).pathname;
    const structured = await getJson(request, `${apiUrl}/api/snapshots/${item.id}/structured-content?limit=2000`);
    const observations = await getJson(request, `${apiUrl}/api/sites/${siteId}/pages/${item.resource_id}/observations?limit=100&direction=asc`);
    const observation = observations.items.find((candidate) => candidate.scan_id === scanId);
    if (!observation) throw new Error(`Observation for Scan ${scanId} and ${item.requested_url} was not found`);
    expect(structured.status).toBe("ready");
    if (!structured.artifact) throw new Error(`Structured artifact for ${item.requested_url} was not ready`);
    result[path] = {
      item,
      observation,
      structured: {
        document_text_sha256: structured.artifact.document_text_sha256,
        outline_sha256: structured.artifact.outline_sha256,
        sections: structured.items.map((section) => ({ direct_text: String(section.direct_text) }))
      }
    };
  }
  return result;
}

async function inspectObservationContent(page: Page, href: string, expectedCopy: string): Promise<void> {
  await page.goto(href);
  await page.getByRole("tab", { name: /^Content/ }).click();
  await page.getByRole("button", { name: /Overview/ }).click();
  await expect(page.getByText(expectedCopy)).toBeVisible();
}

async function poll<T>(operation: () => Promise<T | null>, label: string): Promise<T> {
  const deadline = Date.now() + 90_000;
  while (Date.now() < deadline) {
    const value = await operation();
    if (value !== null) return value;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`Timed out waiting for ${label}`);
}

async function getJson(request: APIRequestContext, url: string): Promise<Json> {
  const response = await request.get(url);
  const body = await response.text();
  expect(response.ok(), `${response.status()} GET ${url}: ${body}`).toBe(true);
  return JSON.parse(body);
}

async function postJson(request: APIRequestContext, url: string, data?: Record<string, unknown>): Promise<Json> {
  const response = await request.post(url, data ? { data } : undefined);
  const body = await response.text();
  expect(response.ok(), `${response.status()} POST ${url}: ${body}`).toBe(true);
  return JSON.parse(body) as Json;
}

function required(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is required`);
  return value;
}
