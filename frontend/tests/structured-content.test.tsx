import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { StructuredContentView } from "../src/components/StructuredContentView";
import type { StructuredContent } from "../src/types/scans";

const ready: StructuredContent = {
  status: "ready",
  reason: null,
  provenance: {
    snapshot_id: 9,
    scan_id: 4,
    site_id: 2,
    content_blob_id: 7,
    raw_html_sha256: "a".repeat(64),
    requested_url: "https://example.com/",
    final_url: "https://example.com/",
    fetched_at: "2026-08-10T12:00:00Z",
    retrieval_method: "full_fetch",
    reused_from_snapshot_id: null,
  },
  artifact: {
    id: 5,
    extractor_version: "structured-content-v1",
    extractor_config_version: "default-v1",
    extraction_state: "ready",
    document_profile: "headed",
    section_count: 2,
    heading_count: 2,
    heading_counts: { h1: 1, h2: 1, h3: 0, h4: 0, h5: 0, h6: 0 },
    document_word_count: 6,
    document_character_count: 32,
    document_text_sha256: "b".repeat(64),
    outline_sha256: "c".repeat(64),
    is_truncated: false,
    truncation_reasons: [],
    created_at: "2026-08-10T12:00:01Z",
  },
  items: [
    section(10, null, 0, 1, "Page title", "Page introduction"),
    section(11, 10, 1, 2, "Details", "Detailed source text"),
  ],
  total: 2,
  limit: 2000,
  offset: 0,
};

describe("StructuredContentView", () => {
  it("prepares historical content and exposes the outline and direct text", async () => {
    const prepare = vi.fn().mockResolvedValue(ready);
    renderView({
      status: "not_prepared",
      reason: "Not prepared",
      provenance: ready.provenance,
      artifact: null,
      items: [],
      total: 0,
      limit: 2000,
      offset: 0,
    }, prepare);
    fireEvent.click(await screen.findByRole("button", { name: "Prepare content" }));
    await waitFor(() => expect(prepare).toHaveBeenCalledOnce());
    expect((await screen.findAllByText("Page title")).length).toBeGreaterThan(0);
    expect(screen.getByText("Page introduction")).toBeInTheDocument();
  });

  it("selects and collapses nested headings without rendering text as HTML", async () => {
    renderView(ready, vi.fn());
    fireEvent.click(await screen.findByRole("button", { name: /Details/ }));
    expect(screen.getByText("Detailed source text")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Collapse Page title" }));
    expect(screen.queryByRole("button", { name: /Details/ })).not.toBeInTheDocument();
  });
});

function renderView(value: StructuredContent, prepare: () => Promise<StructuredContent>) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <StructuredContentView queryKey={["content"]} load={() => Promise.resolve(value)} prepare={prepare} />
    </QueryClientProvider>,
  );
}

function section(
  id: number,
  parentId: number | null,
  position: number,
  level: number,
  heading: string,
  text: string,
) {
  return {
    id,
    position,
    parent_section_id: parentId,
    kind: "heading" as const,
    heading_level: level,
    heading_text: heading,
    heading_dom_path: `html > body > h${level}`,
    region_key: "main",
    region_dom_path: "html > body > main",
    direct_text: text,
    direct_text_sha256: "d".repeat(64),
    section_sha256: "e".repeat(64),
    subtree_sha256: "f".repeat(64),
    direct_word_count: text.split(" ").length,
    direct_character_count: text.length,
    subtree_word_count: text.split(" ").length,
    subtree_character_count: text.length,
    child_count: id === 10 ? 1 : 0,
    descendant_count: id === 10 ? 1 : 0,
    block_count: 1,
    has_direct_content: true,
  };
}
