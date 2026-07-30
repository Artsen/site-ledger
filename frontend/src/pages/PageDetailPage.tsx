import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { getHtml, getLinks, getSnapshot } from "../api/client";

export function PageDetailPage() {
  const { scanId = "", snapshotId = "" } = useParams();
  const [tab, setTab] = useState("overview");
  const snapshot = useQuery({ queryKey: ["snapshot", snapshotId], queryFn: () => getSnapshot(snapshotId) });
  const links = useQuery({ queryKey: ["links", snapshotId], queryFn: () => getLinks(snapshotId), enabled: tab === "links" });
  const html = useQuery({ queryKey: ["html", snapshotId], queryFn: () => getHtml(snapshotId), enabled: tab === "html" });

  if (snapshot.isLoading) return <div className="p-8">Loading page...</div>;
  if (!snapshot.data) return <div className="p-8">Page not found.</div>;

  return (
    <section className="px-8 py-7">
      <Link to={`/scans/${scanId}`} className="mb-4 inline-block text-sm text-stone-600 underline">Back to scan</Link>
      <h1 className="mb-1 truncate text-xl font-semibold">{snapshot.data.page_title ?? snapshot.data.requested_url}</h1>
      <div className="mb-5 truncate text-sm text-stone-600">{snapshot.data.final_url ?? snapshot.data.requested_url}</div>
      <div className="mb-4 flex gap-2 border-b border-stone-200">
        {["overview", "head", "links", "html"].map((item) => (
          <button key={item} onClick={() => setTab(item)} className={`px-3 py-2 text-sm ${tab === item ? "border-b-2 border-neutral-900 font-medium" : "text-stone-600"}`}>
            {item[0].toUpperCase() + item.slice(1)}
          </button>
        ))}
      </div>
      {tab === "overview" ? (
        <dl className="grid grid-cols-1 gap-3 text-sm md:grid-cols-2">
          <Field label="Requested URL" value={snapshot.data.requested_url} />
          <Field label="Final URL" value={snapshot.data.final_url} />
          <Field label="HTTP status" value={snapshot.data.http_status} />
          <Field label="Content type" value={snapshot.data.content_type} />
          <Field label="Depth" value={snapshot.data.crawl_depth} />
          <Field label="Fetch duration" value={snapshot.data.response_time_ms ? `${snapshot.data.response_time_ms} ms` : null} />
          <Field label="HTML SHA-256" value={snapshot.data.raw_html_sha256} />
          <Field label="Error" value={snapshot.data.error_type} />
        </dl>
      ) : null}
      {tab === "head" ? (
        <pre className="overflow-auto rounded-md border border-stone-200 bg-white p-4 text-xs">{JSON.stringify(snapshot.data.parsed_head_json, null, 2)}</pre>
      ) : null}
      {tab === "links" ? (
        <div className="overflow-auto rounded-md border border-stone-200 bg-white">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-stone-100 text-xs uppercase text-stone-500">
              <tr><th className="px-3 py-2">Href</th><th className="px-3 py-2">Decision</th><th className="px-3 py-2">Text</th><th className="px-3 py-2">DOM path</th></tr>
            </thead>
            <tbody>
              {links.data?.map((link) => (
                <tr key={link.id} className="border-t border-stone-100">
                  <td className="max-w-md truncate px-3 py-2">{link.raw_href}</td>
                  <td className="px-3 py-2">{link.scope_decision}</td>
                  <td className="max-w-xs truncate px-3 py-2">{link.anchor_text}</td>
                  <td className="max-w-sm truncate px-3 py-2">{link.dom_path}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {tab === "html" ? (
        <pre className="max-h-[70vh] overflow-auto rounded-md border border-stone-200 bg-white p-4 text-xs">{html.data}</pre>
      ) : null}
    </section>
  );
}

function Field({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="rounded-md border border-stone-200 bg-white px-3 py-2">
      <dt className="text-xs uppercase tracking-wide text-stone-500">{label}</dt>
      <dd className="mt-1 break-words">{value == null ? "" : String(value)}</dd>
    </div>
  );
}

