import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { aiDocumentDownloadUrl, getAiDocumentContent, getAiDocumentSnapshot } from "../api/client";
import { CopyButton } from "../components/ui/CopyButton";
import { DefinitionList } from "../components/ui/DefinitionList";
import { ErrorBanner } from "../components/ui/ErrorBanner";
import { LoadingBlock } from "../components/ui/Loading";
import { formatBytes, formatDate, formatStatus } from "../utils/format";
import { useDocumentTitle } from "../utils/useDocumentTitle";

export function AiDocumentEvidencePage() {
  const { snapshotId = "" } = useParams();
  const [loadContent, setLoadContent] = useState(false);
  const snapshot = useQuery({ queryKey: ["ai-document", snapshotId], queryFn: () => getAiDocumentSnapshot(snapshotId) });
  const content = useQuery({ queryKey: ["ai-document-content", snapshotId], queryFn: () => getAiDocumentContent(snapshotId), enabled: loadContent });
  useDocumentTitle(snapshot.data?.parsed_title ?? "Saved AI document");
  if (snapshot.isLoading) return <PageFrame><LoadingBlock label="Loading saved document evidence..." /></PageFrame>;
  if (snapshot.error || !snapshot.data) return <PageFrame><ErrorBanner error={snapshot.error ?? new Error("Saved evidence not found")} title="Could not load saved evidence" /></PageFrame>;
  const item = snapshot.data;
  return <PageFrame>
    <div className="mb-5"><div className="mb-2 text-sm text-stone-500">{item.source_id ? <Link className="underline" to={`/ai-document-sources/${item.source_id}`}>AI Document Source</Link> : "AI Document Source"} / Saved evidence</div><h1 className="text-2xl font-semibold">{item.parsed_title ?? formatStatus(item.document_kind)}</h1><p className="mt-2 break-all font-mono text-xs text-stone-600">{item.final_url ?? item.requested_url}</p><div className="mt-3 flex flex-wrap gap-2"><a href={item.final_url ?? item.requested_url} target="_blank" rel="noreferrer" className="rounded-md border border-stone-300 bg-white px-3 py-2 text-sm font-medium">Open live document</a><a href={aiDocumentDownloadUrl(snapshotId)} className="rounded-md border border-stone-300 bg-white px-3 py-2 text-sm font-medium">Download saved version</a>{content.data ? <CopyButton value={content.data} label="Copy content" /> : null}</div></div>
    <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm"><DefinitionList items={[
      { label: "Requested URL", value: item.requested_url, copyValue: item.requested_url },
      { label: "Final URL", value: item.final_url, copyValue: item.final_url },
      { label: "Role", value: formatStatus(item.document_role) },
      { label: "Kind", value: formatStatus(item.document_kind) },
      { label: "Classification", value: formatStatus(item.classification_rule) },
      { label: "MIME", value: item.normalized_mime_type },
      { label: "Encoding", value: item.encoding },
      { label: "HTTP status", value: item.http_status },
      { label: "Fetched", value: formatDate(item.fetched_at) },
      { label: "Response time", value: item.response_time_ms == null ? null : `${item.response_time_ms} ms` },
      { label: "SHA-256", value: item.raw_sha256, copyValue: item.raw_sha256 },
      { label: "Raw size", value: formatBytes(item.raw_byte_size) },
      { label: "Stored size", value: formatBytes(item.stored_byte_size) },
      { label: "Parent references", value: item.parent_count },
      { label: "Parse warnings", value: item.warning_count },
    ]} /></section>
    <section className="mt-5 rounded-md border border-stone-200 bg-white p-4 shadow-sm"><div className="mb-3 flex items-center justify-between"><h2 className="font-semibold">Exact retained text</h2>{!loadContent ? <button type="button" className="text-sm underline" onClick={() => setLoadContent(true)}>Load saved content</button> : null}</div>{content.isLoading ? <LoadingBlock label="Loading bounded saved content..." /> : null}{content.error ? <ErrorBanner error={content.error} title="Could not load retained text" /> : null}{content.data != null ? <pre className="max-h-[65vh] overflow-auto whitespace-pre-wrap break-words rounded border border-stone-200 bg-stone-50 p-4 font-mono text-xs">{content.data}</pre> : <p className="text-sm text-stone-600">Content is loaded only on request to avoid placing large documents into the page automatically.</p>}</section>
  </PageFrame>;
}

function PageFrame({ children }: { children: React.ReactNode }) { return <div className="mx-auto max-w-[1300px] px-4 py-6 sm:px-6">{children}</div>; }
