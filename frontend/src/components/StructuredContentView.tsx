import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { StructuredContent, StructuredContentSection } from "../types/scans";
import { formatDate, formatStatus } from "../utils/format";
import { Button } from "./ui/Button";
import { DefinitionList } from "./ui/DefinitionList";
import { EmptyState } from "./ui/EmptyState";
import { ErrorBanner } from "./ui/ErrorBanner";
import { LoadingBlock } from "./ui/Loading";
import { StatusBadge } from "./ui/StatusBadge";

export function StructuredContentView({
  queryKey,
  load,
  prepare,
}: {
  queryKey: string[];
  load: () => Promise<StructuredContent>;
  prepare: () => Promise<StructuredContent>;
}) {
  const queryClient = useQueryClient();
  const content = useQuery({ queryKey, queryFn: load, retry: false });
  const preparation = useMutation({
    mutationFn: prepare,
    onSuccess: (value) => queryClient.setQueryData(queryKey, value),
  });
  if (content.isLoading) return <LoadingBlock label="Loading structured content..." />;
  if (content.error) return <ErrorBanner error={content.error} title="Could not load structured content" />;
  if (!content.data) return null;
  if (content.data.status === "not_prepared") {
    return (
      <EmptyState
        title="Structured content not prepared"
        message={content.data.reason ?? "Prepare the retained HTML to inspect its outline and sections."}
        action={<Button type="button" loading={preparation.isPending} onClick={() => preparation.mutate()}>Prepare content</Button>}
      />
    );
  }
  if (content.data.status === "not_applicable") {
    return <EmptyState title="Structured content unavailable" message={content.data.reason ?? "This Page has no retained HTML."} />;
  }
  if (preparation.error) return <ErrorBanner error={preparation.error} title="Could not prepare structured content" />;
  return <PreparedContent content={content.data} />;
}

function PreparedContent({ content }: { content: StructuredContent }) {
  const [selectedId, setSelectedId] = useState<number | null>(content.items[0]?.id ?? null);
  const [collapsed, setCollapsed] = useState<Set<number>>(() => new Set());
  useEffect(() => {
    if (selectedId == null && content.items[0]) setSelectedId(content.items[0].id);
  }, [content.items, selectedId]);
  const byId = useMemo(() => new Map(content.items.map((section) => [section.id, section])), [content.items]);
  const visible = content.items.filter((section) => !hasCollapsedAncestor(section, byId, collapsed));
  const selected = byId.get(selectedId ?? -1) ?? content.items[0];
  const artifact = content.artifact;
  if (!artifact) return <EmptyState title="Structured content unavailable" message={content.reason ?? "No compatible artifact is available."} />;
  return (
    <div className="space-y-5">
      {content.status !== "ready" ? <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">{content.reason ?? formatStatus(content.status)}</div> : null}
      <section className="border-y border-stone-200 bg-white py-4">
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <h2 className="text-base font-semibold">Structured Page content</h2>
          <StatusBadge status={content.status} />
          <span className="text-xs text-stone-500">{artifact.extractor_version} / {artifact.extractor_config_version}</span>
        </div>
        <DefinitionList items={[
          { label: "Observation", value: content.provenance ? `Scan ${content.provenance.scan_id}, observation ${content.provenance.snapshot_id}` : "Not available" },
          { label: "Fetched", value: content.provenance?.fetched_at ? formatDate(content.provenance.fetched_at) : "Not available" },
          { label: "ContentBlob", value: content.provenance?.content_blob_id ?? "Not available" },
          { label: "Profile", value: formatStatus(artifact.document_profile) },
          { label: "Sections", value: artifact.section_count },
          { label: "Headings", value: `${artifact.heading_count} (${Object.entries(artifact.heading_counts).map(([level, count]) => `${level}: ${count}`).join(", ")})` },
          { label: "Document size", value: `${artifact.document_word_count.toLocaleString()} words / ${artifact.document_character_count.toLocaleString()} characters` },
          { label: "Document text SHA-256", value: artifact.document_text_sha256, copyValue: artifact.document_text_sha256 },
          { label: "Outline SHA-256", value: artifact.outline_sha256, copyValue: artifact.outline_sha256 },
          { label: "Truncation", value: artifact.is_truncated ? artifact.truncation_reasons.map(formatStatus).join(", ") : "None" },
        ]} />
      </section>
      {content.total > content.items.length ? <p className="text-sm text-amber-800">Showing the first {content.items.length.toLocaleString()} of {content.total.toLocaleString()} sections.</p> : null}
      {!content.items.length ? <EmptyState title="No extracted sections" message="The retained document contains no source-derived readable text or headings." /> : (
        <div className="grid min-h-[28rem] grid-cols-1 border-y border-stone-200 lg:grid-cols-[minmax(18rem,32%)_minmax(0,1fr)]">
          <div className="max-h-[42rem] overflow-auto border-b border-stone-200 bg-stone-50 p-2 lg:border-b-0 lg:border-r">
            <h3 className="px-2 py-2 text-sm font-semibold">Outline</h3>
            {visible.map((section) => {
              const depth = sectionDepth(section, byId);
              const isCollapsed = collapsed.has(section.id);
              return (
                <div key={section.id} className="flex items-start" style={{ paddingLeft: `${Math.min(depth, 12) * 16}px` }}>
                  {section.child_count ? <button type="button" className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center" aria-label={`${isCollapsed ? "Expand" : "Collapse"} ${sectionLabel(section)}`} onClick={() => setCollapsed((current) => toggleSet(current, section.id))}>{isCollapsed ? <ChevronRight size={15} /> : <ChevronDown size={15} />}</button> : <span className="h-7 w-7 shrink-0" />}
                  <button type="button" onClick={() => setSelectedId(section.id)} className={`min-w-0 flex-1 px-2 py-1.5 text-left text-sm ${selected?.id === section.id ? "bg-neutral-900 font-semibold text-white" : "hover:bg-stone-200"}`}>
                    <span className="mr-2 font-mono text-xs opacity-70">{section.heading_level ? `H${section.heading_level}` : section.kind === "preamble" ? "PRE" : "DOC"}</span>
                    <span className="break-words">{sectionLabel(section)}</span>
                  </button>
                </div>
              );
            })}
          </div>
          {selected ? <SectionDetail section={selected} /> : null}
        </div>
      )}
    </div>
  );
}

function SectionDetail({ section }: { section: StructuredContentSection }) {
  return (
    <section className="min-w-0 p-4">
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <h3 className="text-base font-semibold">{sectionLabel(section)}</h3>
        <span className="rounded bg-stone-100 px-2 py-1 text-xs">{section.heading_level ? `H${section.heading_level}` : formatStatus(section.kind)}</span>
        <span className="rounded bg-stone-100 px-2 py-1 text-xs">{formatStatus(section.region_key)}</span>
      </div>
      <DefinitionList items={[
        { label: "Position", value: section.position },
        { label: "Direct content", value: `${section.direct_word_count.toLocaleString()} words / ${section.direct_character_count.toLocaleString()} characters` },
        { label: "Subtree content", value: `${section.subtree_word_count.toLocaleString()} words / ${section.subtree_character_count.toLocaleString()} characters` },
        { label: "Children / descendants", value: `${section.child_count} / ${section.descendant_count}` },
        { label: "Heading DOM path", value: section.heading_dom_path ?? "Not applicable", copyValue: section.heading_dom_path },
        { label: "Region DOM path", value: section.region_dom_path ?? "Not available", copyValue: section.region_dom_path },
        { label: "Section SHA-256", value: section.section_sha256, copyValue: section.section_sha256 },
        { label: "Subtree SHA-256", value: section.subtree_sha256, copyValue: section.subtree_sha256 },
      ]} />
      <div className="mt-5 border-t border-stone-200 pt-4">
        <h4 className="mb-2 text-sm font-semibold">Direct source text</h4>
        {section.direct_text ? <pre className="max-h-[30rem] overflow-auto whitespace-pre-wrap break-words bg-stone-50 p-3 font-sans text-sm leading-6 text-stone-900">{section.direct_text}</pre> : <p className="text-sm text-stone-500">No direct text in this section.</p>}
      </div>
    </section>
  );
}

function sectionLabel(section: StructuredContentSection) {
  if (section.kind === "preamble") return "Preamble";
  if (section.kind === "unheaded") return "Unheaded document";
  return section.heading_text || "Empty heading";
}

function sectionDepth(section: StructuredContentSection, byId: Map<number, StructuredContentSection>) {
  let depth = 0;
  let parentId = section.parent_section_id;
  const visited = new Set<number>();
  while (parentId != null && !visited.has(parentId)) {
    visited.add(parentId);
    depth += 1;
    parentId = byId.get(parentId)?.parent_section_id ?? null;
  }
  return depth;
}

function hasCollapsedAncestor(section: StructuredContentSection, byId: Map<number, StructuredContentSection>, collapsed: Set<number>) {
  let parentId = section.parent_section_id;
  while (parentId != null) {
    if (collapsed.has(parentId)) return true;
    parentId = byId.get(parentId)?.parent_section_id ?? null;
  }
  return false;
}

function toggleSet(current: Set<number>, id: number) {
  const next = new Set(current);
  if (next.has(id)) next.delete(id); else next.add(id);
  return next;
}
