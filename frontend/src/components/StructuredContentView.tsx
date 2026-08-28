import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type {
  StructuredContent,
  StructuredContentDocument,
  StructuredContentNode,
  StructuredContentSection,
  StructuredMarkdown,
} from "../types/scans";
import { formatDate, formatStatus } from "../utils/format";
import { Button } from "./ui/Button";
import { CopyButton } from "./ui/CopyButton";
import { DefinitionList } from "./ui/DefinitionList";
import { EmptyState } from "./ui/EmptyState";
import { ErrorBanner } from "./ui/ErrorBanner";
import { LoadingBlock } from "./ui/Loading";
import { StatusBadge } from "./ui/StatusBadge";
import { Tabs } from "./ui/Tabs";

type StructuredContentViewProps = {
  queryKey: string[];
  load: () => Promise<StructuredContent>;
  prepare: () => Promise<StructuredContent>;
  loadDocument: () => Promise<StructuredContentDocument>;
  loadMarkdown: () => Promise<StructuredMarkdown>;
};

export function StructuredContentView({
  queryKey,
  load,
  prepare,
  loadDocument,
  loadMarkdown,
}: StructuredContentViewProps) {
  const queryClient = useQueryClient();
  const content = useQuery({ queryKey, queryFn: load, retry: false });
  const preparation = useMutation({
    mutationFn: prepare,
    onSuccess: (value) => {
      queryClient.setQueryData(queryKey, value);
      void queryClient.invalidateQueries({ queryKey: [...queryKey, "document"] });
      void queryClient.invalidateQueries({ queryKey: [...queryKey, "markdown"] });
    },
  });
  if (content.isLoading) return <LoadingBlock label="Loading structured content..." />;
  if (content.error)
    return <ErrorBanner error={content.error} title="Could not load structured content" />;
  if (!content.data) return null;
  if (content.data.status === "not_prepared") {
    return (
      <EmptyState
        title="Structured content not prepared"
        message={
          content.data.reason ?? "Prepare the retained HTML to inspect its canonical document."
        }
        action={
          <Button
            type="button"
            loading={preparation.isPending}
            onClick={() => preparation.mutate()}
          >
            Prepare content
          </Button>
        }
      />
    );
  }
  if (content.data.status === "not_applicable") {
    return (
      <EmptyState
        title="Structured content unavailable"
        message={content.data.reason ?? "This Page has no retained HTML."}
      />
    );
  }
  if (preparation.error)
    return <ErrorBanner error={preparation.error} title="Could not prepare structured content" />;
  return (
    <PreparedContent
      content={content.data}
      queryKey={queryKey}
      loadDocument={loadDocument}
      loadMarkdown={loadMarkdown}
    />
  );
}

function PreparedContent({
  content,
  queryKey,
  loadDocument,
  loadMarkdown,
}: {
  content: StructuredContent;
  queryKey: string[];
  loadDocument: () => Promise<StructuredContentDocument>;
  loadMarkdown: () => Promise<StructuredMarkdown>;
}) {
  const [mode, setMode] = useState("outline");
  const artifact = content.artifact;
  if (!artifact)
    return (
      <EmptyState
        title="Structured content unavailable"
        message={content.reason ?? "No compatible artifact is available."}
      />
    );
  return (
    <div className="space-y-5">
      {content.status !== "ready" ? (
        <div className="border-y border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
          {content.reason ?? formatStatus(content.status)}
        </div>
      ) : null}
      <section className="border-y border-stone-200 bg-white py-4">
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <h2 className="text-base font-semibold">Structured Page content</h2>
          <StatusBadge status={content.status} />
          <span className="text-xs text-stone-500">
            {artifact.extractor_version} / {artifact.extractor_config_version}
          </span>
        </div>
        <DefinitionList
          items={[
            {
              label: "Observation",
              value: content.provenance
                ? `Scan ${content.provenance.scan_id}, observation ${content.provenance.snapshot_id}`
                : "Not available",
            },
            {
              label: "Fetched",
              value: content.provenance?.fetched_at
                ? formatDate(content.provenance.fetched_at)
                : "Not available",
            },
            { label: "ContentBlob", value: content.provenance?.content_blob_id ?? "Not available" },
            { label: "Profile", value: formatStatus(artifact.document_profile) },
            { label: "Structural nodes", value: artifact.node_count },
            { label: "Sections", value: artifact.section_count },
            {
              label: "Headings",
              value: `${artifact.heading_count} (${Object.entries(artifact.heading_counts)
                .map(([level, count]) => `${level}: ${count}`)
                .join(", ")})`,
            },
            {
              label: "Document size",
              value: `${artifact.document_word_count.toLocaleString()} words / ${artifact.document_character_count.toLocaleString()} characters`,
            },
            {
              label: "Canonical document SHA-256",
              value: artifact.canonical_document_sha256 ?? "Not available",
              copyValue: artifact.canonical_document_sha256 ?? undefined,
            },
            {
              label: "Outline SHA-256",
              value: artifact.outline_sha256,
              copyValue: artifact.outline_sha256,
            },
            {
              label: "Markdown",
              value: `${artifact.markdown_renderer_version ?? "Not available"} / ${artifact.markdown_character_count?.toLocaleString() ?? 0} characters`,
            },
            {
              label: "Truncation",
              value: artifact.is_truncated
                ? artifact.truncation_reasons.map(formatStatus).join(", ")
                : "None",
            },
          ]}
        />
      </section>
      <Tabs
        tabs={[
          { id: "outline", label: "Outline" },
          { id: "document", label: "Document", count: artifact.node_count },
          { id: "markdown", label: "Markdown" },
        ]}
        active={mode}
        onChange={setMode}
      />
      {mode === "outline" ? <OutlineView content={content} /> : null}
      {mode === "document" ? (
        <DocumentView queryKey={[...queryKey, "document"]} load={loadDocument} />
      ) : null}
      {mode === "markdown" ? (
        <MarkdownView queryKey={[...queryKey, "markdown"]} load={loadMarkdown} />
      ) : null}
    </div>
  );
}

function OutlineView({ content }: { content: StructuredContent }) {
  const [selectedId, setSelectedId] = useState<number | null>(content.items[0]?.id ?? null);
  const [collapsed, setCollapsed] = useState<Set<number>>(() => new Set());
  useEffect(() => {
    if (selectedId == null && content.items[0]) setSelectedId(content.items[0].id);
  }, [content.items, selectedId]);
  const byId = useMemo(
    () => new Map(content.items.map((section) => [section.id, section])),
    [content.items],
  );
  const visible = content.items.filter(
    (section) => !hasCollapsedAncestor(section, byId, collapsed),
  );
  const selected = byId.get(selectedId ?? -1) ?? content.items[0];
  if (!content.items.length)
    return (
      <EmptyState
        title="No extracted sections"
        message="The retained document contains no source-derived readable text or headings."
      />
    );
  return (
    <div className="grid min-h-[28rem] grid-cols-1 border-y border-stone-200 lg:grid-cols-[minmax(18rem,32%)_minmax(0,1fr)]">
      <div className="max-h-[42rem] overflow-auto border-b border-stone-200 bg-stone-50 p-2 lg:border-b-0 lg:border-r">
        {visible.map((section) => {
          const depth = sectionDepth(section, byId);
          const isCollapsed = collapsed.has(section.id);
          return (
            <div
              key={section.id}
              className="flex items-start"
              style={{ paddingLeft: `${Math.min(depth, 12) * 16}px` }}
            >
              {section.child_count ? (
                <button
                  type="button"
                  className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center"
                  aria-label={`${isCollapsed ? "Expand" : "Collapse"} ${sectionLabel(section)}`}
                  onClick={() => setCollapsed((current) => toggleSet(current, section.id))}
                >
                  {isCollapsed ? <ChevronRight size={15} /> : <ChevronDown size={15} />}
                </button>
              ) : (
                <span className="h-7 w-7 shrink-0" />
              )}
              <button
                type="button"
                onClick={() => setSelectedId(section.id)}
                className={`min-w-0 flex-1 px-2 py-1.5 text-left text-sm ${selected?.id === section.id ? "bg-neutral-900 font-semibold text-white" : "hover:bg-stone-200"}`}
              >
                <span className="mr-2 font-mono text-xs opacity-70">
                  {section.heading_level
                    ? `H${section.heading_level}`
                    : section.kind === "preamble"
                      ? "PRE"
                      : "DOC"}
                </span>
                <span className="break-words">{sectionLabel(section)}</span>
              </button>
            </div>
          );
        })}
      </div>
      {selected ? <SectionDetail section={selected} /> : null}
    </div>
  );
}

function DocumentView({ queryKey, load }: { queryKey: string[]; load: () => Promise<StructuredContentDocument> }) {
  const query = useQuery({ queryKey, queryFn: load, retry: false });
  if (query.isLoading) return <LoadingBlock label="Loading canonical document..." />;
  if (query.error) return <ErrorBanner error={query.error} title="Could not load canonical document" />;
  if (!query.data?.items.length)
    return <EmptyState title="Empty canonical document" message="No structural nodes were retained." />;
  return (
    <section className="border-y border-stone-200">
      {query.data.total > query.data.items.length ? (
        <p className="border-b border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          Showing {query.data.items.length.toLocaleString()} of {query.data.total.toLocaleString()} nodes.
        </p>
      ) : null}
      <div className="max-h-[48rem] overflow-auto divide-y divide-stone-200">
        {query.data.items.map((node) => <DocumentNode key={node.id} node={node} />)}
      </div>
    </section>
  );
}

function DocumentNode({ node }: { node: StructuredContentNode }) {
  const headingLevel = Number(node.semantic.level ?? 0);
  const label = node.kind === "heading" && headingLevel ? `heading H${headingLevel}` : formatStatus(node.kind);
  return (
    <div className="px-3 py-2" style={{ paddingLeft: `${12 + Math.min(node.depth, 12) * 16}px` }}>
      <div className="flex flex-wrap items-center gap-2 text-xs text-stone-500">
        <span className="font-mono">{node.position}</span>
        <strong className="text-stone-800">{label}</strong>
        <span>{formatStatus(node.region_key)}</span>
        {node.source_tag ? <span className="font-mono">&lt;{node.source_tag}&gt;</span> : null}
      </div>
      {node.text !== null ? (
        <p className="mt-1 whitespace-pre-wrap break-words text-sm text-stone-900">
          {node.text || "Empty heading"}
        </p>
      ) : null}
    </div>
  );
}

function MarkdownView({ queryKey, load }: { queryKey: string[]; load: () => Promise<StructuredMarkdown> }) {
  const query = useQuery({ queryKey, queryFn: load, retry: false });
  if (query.isLoading) return <LoadingBlock label="Loading deterministic Markdown..." />;
  if (query.error) return <ErrorBanner error={query.error} title="Could not load Markdown" />;
  if (!query.data) return null;
  return (
    <section className="border-y border-stone-200 py-3">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2 px-3">
        <div className="text-xs text-stone-500">
          {query.data.rendererVersion} / {query.data.totalCharacters.toLocaleString()} characters
          {query.data.partial ? " / partial response" : ""}
        </div>
        <CopyButton value={query.data.text} label="Copy Markdown" />
      </div>
      <pre className="max-h-[48rem] overflow-auto whitespace-pre-wrap break-words bg-stone-50 p-4 text-sm leading-6 text-stone-900">
        {query.data.text}
      </pre>
    </section>
  );
}

function SectionDetail({ section }: { section: StructuredContentSection }) {
  return (
    <section className="min-w-0 p-4">
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <h3 className="text-base font-semibold">{sectionLabel(section)}</h3>
        <span className="rounded bg-stone-100 px-2 py-1 text-xs">
          {section.heading_level ? `H${section.heading_level}` : formatStatus(section.kind)}
        </span>
        <span className="rounded bg-stone-100 px-2 py-1 text-xs">
          {formatStatus(section.region_key)}
        </span>
      </div>
      <DefinitionList
        items={[
          { label: "Position", value: section.position },
          {
            label: "Direct content",
            value: `${section.direct_word_count.toLocaleString()} words / ${section.direct_character_count.toLocaleString()} characters`,
          },
          {
            label: "Subtree content",
            value: `${section.subtree_word_count.toLocaleString()} words / ${section.subtree_character_count.toLocaleString()} characters`,
          },
          {
            label: "Children / descendants",
            value: `${section.child_count} / ${section.descendant_count}`,
          },
          {
            label: "Heading DOM path",
            value: section.heading_dom_path ?? "Not applicable",
            copyValue: section.heading_dom_path,
          },
          {
            label: "Region DOM path",
            value: section.region_dom_path ?? "Not available",
            copyValue: section.region_dom_path,
          },
          {
            label: "Section SHA-256",
            value: section.section_sha256,
            copyValue: section.section_sha256,
          },
          {
            label: "Subtree SHA-256",
            value: section.subtree_sha256,
            copyValue: section.subtree_sha256,
          },
        ]}
      />
      <div className="mt-5 border-t border-stone-200 pt-4">
        <h4 className="mb-2 text-sm font-semibold">Direct source text</h4>
        {section.direct_text ? (
          <pre className="max-h-[30rem] overflow-auto whitespace-pre-wrap break-words bg-stone-50 p-3 font-sans text-sm leading-6 text-stone-900">
            {section.direct_text}
          </pre>
        ) : (
          <p className="text-sm text-stone-500">No direct text in this section.</p>
        )}
      </div>
    </section>
  );
}

function sectionLabel(section: StructuredContentSection) {
  if (section.kind === "preamble") return "Preamble";
  if (section.kind === "unheaded") return "Unheaded document";
  return section.heading_text || "Empty heading";
}

function sectionDepth(
  section: StructuredContentSection,
  byId: Map<number, StructuredContentSection>,
) {
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

function hasCollapsedAncestor(
  section: StructuredContentSection,
  byId: Map<number, StructuredContentSection>,
  collapsed: Set<number>,
) {
  let parentId = section.parent_section_id;
  while (parentId != null) {
    if (collapsed.has(parentId)) return true;
    parentId = byId.get(parentId)?.parent_section_id ?? null;
  }
  return false;
}

function toggleSet(current: Set<number>, id: number) {
  const next = new Set(current);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  return next;
}
