import { useMutation } from "@tanstack/react-query";
import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";

import { createScan, defaultScope, techSmithScope } from "../api/client";
import type { ScopeConfig } from "../types/scans";

export function NewScanPage() {
  const navigate = useNavigate();
  const [startingUrl, setStartingUrl] = useState("");
  const [preset, setPreset] = useState("default");
  const [scope, setScope] = useState<ScopeConfig>(defaultScope());
  const mutation = useMutation({
    mutationFn: () => createScan(startingUrl, scope),
    onSuccess: (scan) => navigate(`/scans/${scan.id}`)
  });

  function applyPreset(value: string) {
    setPreset(value);
    setScope(value === "techsmith" ? techSmithScope() : defaultScope());
  }

  function updateList(key: keyof ScopeConfig, value: string) {
    setScope((current) => ({ ...current, [key]: value.split("\n").map((item) => item.trim()).filter(Boolean) }));
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    mutation.mutate();
  }

  return (
    <section className="mx-auto max-w-5xl px-8 py-8">
      <h1 className="mb-6 text-2xl font-semibold">New scan</h1>
      <form onSubmit={submit} className="space-y-5">
        <label className="block">
          <span className="mb-1 block text-sm font-medium">Starting URL</span>
          <input
            required
            value={startingUrl}
            onChange={(event) => setStartingUrl(event.target.value)}
            className="w-full rounded-md border border-stone-300 bg-white px-3 py-2"
            placeholder="https://example.com/"
          />
        </label>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <label className="block">
            <span className="mb-1 block text-sm font-medium">Scope preset</span>
            <select value={preset} onChange={(event) => applyPreset(event.target.value)} className="w-full rounded-md border border-stone-300 bg-white px-3 py-2">
              <option value="default">Current host</option>
              <option value="techsmith">TechSmith starter</option>
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium">Maximum pages</span>
            <input type="number" min={1} value={scope.max_pages} onChange={(event) => setScope({ ...scope, max_pages: Number(event.target.value) })} className="w-full rounded-md border border-stone-300 bg-white px-3 py-2" />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium">Maximum depth</span>
            <input type="number" min={0} value={scope.max_depth} onChange={(event) => setScope({ ...scope, max_depth: Number(event.target.value) })} className="w-full rounded-md border border-stone-300 bg-white px-3 py-2" />
          </label>
        </div>
        <details className="border-t border-stone-200 pt-4">
          <summary className="cursor-pointer text-sm font-medium">Advanced scope settings</summary>
          <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
            <TextArea label="Allowed hosts" value={scope.allowed_host_patterns.join("\n")} onChange={(value) => updateList("allowed_host_patterns", value)} />
            <TextArea label="Excluded hosts" value={scope.excluded_host_patterns.join("\n")} onChange={(value) => updateList("excluded_host_patterns", value)} />
            <TextArea label="Included path prefixes" value={scope.included_path_prefixes.join("\n")} onChange={(value) => updateList("included_path_prefixes", value)} />
            <TextArea label="Excluded path prefixes" value={scope.excluded_path_prefixes.join("\n")} onChange={(value) => updateList("excluded_path_prefixes", value)} />
            <TextArea label="Dropped query parameters" value={scope.drop_query_parameters.join("\n")} onChange={(value) => updateList("drop_query_parameters", value)} />
            <label className="block">
              <span className="mb-1 block text-sm font-medium">Request timeout seconds</span>
              <input type="number" min={1} value={scope.request_timeout_seconds} onChange={(event) => setScope({ ...scope, request_timeout_seconds: Number(event.target.value) })} className="w-full rounded-md border border-stone-300 bg-white px-3 py-2" />
            </label>
          </div>
        </details>
        {mutation.error ? <div className="text-sm text-red-700">{mutation.error.message}</div> : null}
        <button className="rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white" disabled={mutation.isPending}>
          Start scan
        </button>
      </form>
    </section>
  );
}

function TextArea(props: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium">{props.label}</span>
      <textarea value={props.value} onChange={(event) => props.onChange(event.target.value)} rows={4} className="w-full rounded-md border border-stone-300 bg-white px-3 py-2 text-sm" />
    </label>
  );
}

