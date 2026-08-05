import { expect, test, type Page } from "@playwright/test";

test("Site Ledger workflow supports creation, filtering, details, inbound links, and deletion", async ({
  page,
}) => {
  test.setTimeout(90_000);
  await mockApi(page);

  await page.goto("/");
  await expect(page).toHaveTitle("New Scan | Site Ledger");
  await expect(page.getByText("Site Ledger", { exact: true })).toBeVisible();
  await expect(
    page.getByText("A historical record of your website."),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Site Ledger home" }),
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
  await page.getByRole("link", { name: "Edit site" }).click();
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
  await expect(page.getByText("Page details")).toBeVisible();
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

  await page.getByRole("link", { name: "Back to page results" }).click();
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

async function mockApi(page: Page) {
  let scanStatus: "running" | "completed" = "running";
  let siteActive = true;
  let pageNote: Record<string, unknown> | null = null;

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
