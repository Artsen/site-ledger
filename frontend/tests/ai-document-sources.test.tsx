import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AiDocumentEvidencePage } from "../src/pages/AiDocumentEvidencePage";
import { AiDocumentSourcePage } from "../src/pages/AiDocumentSourcePage";

const source = {
  id: 7,
  website_property_id: 2,
  site_name: "Docs Site",
  name: "Root AI docs",
  entry_url: "https://example.com/llms.txt",
  discovery_mode: "bounded_discovery",
  is_active: true,
  settings: {
    request_timeout_seconds: 10,
    max_attempts: 2,
    max_nesting_depth: 5,
    max_index_documents: 100,
    max_total_documents: 1000,
    max_references_per_document: 10000,
    max_individual_document_bytes: 5000000,
    max_total_retained_bytes: 100000000,
    max_total_network_bytes: 250000000,
    follow_external_documents: false,
    save_declared_documents: true,
  },
  last_refresh_status: "completed_with_errors",
  last_successful_refresh_at: "2026-08-06T12:00:00Z",
  current_entry_count: 1,
  latest_refresh_id: 11,
  latest_source_refresh_id: 12,
  document_count: 3,
  reference_count: 5,
  warning_count: 1,
  retained_bytes: 2048,
};

const document = {
  id: 21,
  source_id: 7,
  refresh_id: 11,
  resource_id: 40,
  requested_url: "https://example.com/llms.txt",
  final_url: "https://example.com/llms.txt",
  parent_depth_min: 0,
  document_role: "root_index",
  document_kind: "llms_index",
  classification_rule: "filename_llms_txt",
  fetch_state: "saved",
  http_status: 200,
  normalized_mime_type: "text/plain",
  encoding: "utf-8",
  response_headers: {},
  redirect_chain: [],
  fetched_at: "2026-08-06T12:00:00Z",
  response_time_ms: 20,
  network_bytes_transferred: 2048,
  raw_sha256: "a".repeat(64),
  parsed_title: "Docs",
  parsed_summary: "Summary",
  parse_state: "parsed",
  parse_version: "ai-document-parser-v1",
  parse_warnings_json: [],
  warning_count: 0,
  change_state: "changed",
  error_type: null,
  error_message: null,
  raw_byte_size: 2048,
  stored_byte_size: 700,
  parent_count: 2,
};

afterEach(() => vi.restoreAllMocks());

describe("AI Document Source workspace", () => {
  it("shows tree provenance, files, validation, history, and safe settings", async () => {
    mockApi();
    renderRoute(<AiDocumentSourcePage />, "/ai-document-sources/7?tab=tree", "/ai-document-sources/:sourceId");

    expect(await screen.findByRole("heading", { name: "Root AI docs" })).toBeInTheDocument();
    expect(await screen.findByText("2 parents")).toBeInTheDocument();
    expect(screen.getByText("Cycle")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Files" }));
    expect(await screen.findByRole("link", { name: "Open" })).toHaveAttribute("href", "/ai-document-snapshots/21");
    expect(screen.getAllByRole("option", { name: "25" }).length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("tab", { name: "Declared URLs" }));
    expect(await screen.findByText("Current origin")).toBeInTheDocument();
    expect(screen.getAllByText("Optional").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("tab", { name: "Validation" }));
    expect(await screen.findByText(/llms-full.txt is optional/i)).toBeInTheDocument();
    expect(screen.getByText("Circular index reference")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "History" }));
    expect(await screen.findByText("Unchanged")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Settings" }));
    expect(await screen.findByLabelText("Follow external documents")).not.toBeChecked();
    expect(screen.getByLabelText("Request timeout seconds")).toHaveValue(10);
    expect(screen.getByLabelText("Maximum attempts")).toHaveValue(2);
    expect(screen.getByText(/preserving unrelated Sites, Pages, Scans/i)).toBeInTheDocument();
  });

  it("loads exact evidence as escaped text only after an explicit action", async () => {
    mockApi();
    renderRoute(<AiDocumentEvidencePage />, "/ai-document-snapshots/21", "/ai-document-snapshots/:snapshotId");

    expect(await screen.findByRole("heading", { name: "Docs" })).toBeInTheDocument();
    expect(screen.queryByText("<script>window.bad=true</script>")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Load saved content" }));
    expect(await screen.findByText(/window.bad=true/)).toBeInTheDocument();
    expect(globalThis.document.querySelector("script")).toBeNull();
    expect(screen.getByRole("link", { name: "Download saved version" })).toHaveAttribute("href", "/api/ai-document-snapshots/21/download");
  });
});

function renderRoute(element: React.ReactElement, initial: string, path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[initial]}><Routes><Route path={path} element={element} /></Routes></MemoryRouter></QueryClientProvider>);
}

function mockApi() {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    let payload: unknown = {};
    if (url.endsWith("/api/ai-document-sources/7")) payload = source;
    else if (url.includes("/tree")) payload = { items: [{ snapshot: document, parent_count: 2, cycle: true }] };
    else if (url.includes("/documents")) payload = { items: [document], total: 1, limit: 50, offset: 0 };
    else if (url.includes("/references")) payload = { items: [{ id: 1, parent_snapshot_id: 21, target_resource_id: 41, child_snapshot_id: null, position: 0, section_title: "Optional", label: "Guide", description: "Read it", raw_url: "/guide", resolved_url: "https://example.com/guide", normalized_target_url: "https://example.com/guide", optional: true, inferred_role: "declared_document", inferred_kind: "html_page_reference", classification_rule: "parent_reference", in_scope: true, scope_decision: "crawlable", exclusion_reason: null, discovery_depth: 1, forms_cycle: false, inventory_entry_id: 8 }], total: 1, limit: 50, offset: 0 };
    else if (url.includes("/validation")) payload = [{ id: 1, snapshot_id: 21, reference_id: 1, severity: "warning", code: "circular_index_reference", message: "Circular index reference", data_json: {} }];
    else if (url.includes("/refreshes?")) payload = { items: [{ id: 11, source_refresh_id: 12, status: "completed", configuration_json: source.settings, root_candidate_count: 1, document_discovered_count: 3, document_fetched_count: 3, document_saved_count: 3, document_unchanged_count: 2, document_changed_count: 1, document_failed_count: 0, document_skipped_count: 0, reference_count: 5, cycle_count: 1, total_network_bytes: 3000, total_retained_bytes: 2048, stop_reason: null, fatal_error_message: null, created_at: "2026-08-06T12:00:00Z" }], total: 1, limit: 50, offset: 0 };
    else if (url.endsWith("/api/ai-document-snapshots/21")) payload = document;
    else if (url.endsWith("/content")) return new Response("# Docs\n<script>window.bad=true</script>", { status: 200, headers: { "content-type": "text/plain" } });
    return new Response(JSON.stringify(payload), { status: 200, headers: { "content-type": "application/json" } });
  });
}
