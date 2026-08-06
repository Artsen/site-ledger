import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { createSite, defaultScope, getRenderCapabilities, getSite, updateSite } from "../api/client";
import { Button } from "../components/ui/Button";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorBanner } from "../components/ui/ErrorBanner";
import { Field } from "../components/ui/Field";
import { LoadingBlock } from "../components/ui/Loading";
import { inputClass } from "../components/ui/styles";
import type { ScopeConfig, SitePayload } from "../types/scans";
import { plural } from "../utils/format";
import { normalizeStartingUrlInput, parseLineList } from "../utils/url";
import { useDocumentTitle } from "../utils/useDocumentTitle";

type ListFields = Pick<ScopeConfig, "allowed_host_patterns" | "excluded_host_patterns" | "included_path_prefixes" | "excluded_path_prefixes" | "drop_query_parameters">;
type ListFieldText = Record<keyof ListFields, string>;

export function SiteFormPage({ mode }: { mode: "create" | "edit" }) {
  const { siteId = "" } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const existing = useQuery({ queryKey: ["site", siteId], queryFn: () => getSite(siteId), enabled: mode === "edit" });
  const renderCapabilities = useQuery({ queryKey: ["render-capabilities"], queryFn: getRenderCapabilities });
  useDocumentTitle(mode === "edit" ? (existing.data?.name ? `Edit ${existing.data.name}` : "Edit Site") : "Create Site");
  const [touchedIncludedPaths, setTouchedIncludedPaths] = useState(false);
  const [form, setForm] = useState<SitePayload>({
    name: "",
    base_url: "",
    description: "",
    group_key: "Other",
    locale: "",
    platform_key: "Other",
    ownership_key: "Unknown",
    scope_config: defaultScope(),
    is_active: true
  });
  const [listFields, setListFields] = useState<ListFieldText>(() => listsFromScope(defaultScope()));
  const baseValidation = useMemo(() => normalizeStartingUrlInput(form.base_url), [form.base_url]);
  const effectiveScope = useMemo(() => scopeFromForm(form.scope_config, listFields), [form.scope_config, listFields]);
  const validation = validate(form, baseValidation, effectiveScope);
  const save = useMutation({
    mutationFn: () => {
      const payload = { ...form, base_url: baseValidation.normalizedUrl, description: form.description || null, locale: form.locale || null, scope_config: effectiveScope };
      return mode === "edit" ? updateSite(siteId, payload) : createSite(payload);
    },
    onSuccess: async (site) => {
      await queryClient.invalidateQueries({ queryKey: ["sites"] });
      await queryClient.invalidateQueries({ queryKey: ["site", String(site.id)] });
      navigate(`/sites/${site.id}`);
    }
  });

  useEffect(() => {
    if (!existing.data) return;
    setForm({
      name: existing.data.name,
      base_url: existing.data.base_url,
      description: existing.data.description ?? "",
      group_key: existing.data.group_key,
      locale: existing.data.locale ?? "",
      platform_key: existing.data.platform_key,
      ownership_key: existing.data.ownership_key,
      scope_config: { ...defaultScope(), ...existing.data.scope_config },
      is_active: existing.data.is_active
    });
    setListFields(listsFromScope(existing.data.scope_config));
    setTouchedIncludedPaths(true);
  }, [existing.data]);

  useEffect(() => {
    if (mode !== "create" || touchedIncludedPaths || !baseValidation.normalizedUrl) return;
    try {
      const path = new URL(baseValidation.normalizedUrl).pathname;
      if (path && path !== "/") setListFields((current) => ({ ...current, included_path_prefixes: path.endsWith("/") ? path : `${path}/` }));
    } catch {
      return;
    }
  }, [baseValidation.normalizedUrl, mode, touchedIncludedPaths]);

  if (existing.isLoading) return <PageFrame><LoadingBlock label="Loading site..." /></PageFrame>;
  if (existing.error) return <PageFrame><ErrorBanner error={existing.error} title="Could not load site" /></PageFrame>;
  if (mode === "edit" && !existing.data) return <PageFrame><EmptyState title="Site not found" message="The saved site may have been deleted." /></PageFrame>;

  function updateList(key: keyof ListFieldText, value: string) {
    if (key === "included_path_prefixes") setTouchedIncludedPaths(true);
    setListFields((current) => ({ ...current, [key]: value }));
  }

  function updateScopeNumber(key: keyof Pick<ScopeConfig, "max_pages" | "max_depth" | "request_timeout_seconds" | "max_html_response_bytes" | "delay_between_requests_ms" | "max_redirects">, value: string) {
    setForm((current) => ({ ...current, scope_config: { ...current.scope_config, [key]: value === "" ? Number.NaN : Number(value) } }));
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (validation.hasErrors) return;
    save.mutate();
  }

  return (
    <PageFrame>
      <div className="mb-6">
        <div className="mb-2 text-sm text-stone-500"><Link to="/sites" className="underline">Sites</Link> / {mode === "edit" ? "Edit" : "Create"}</div>
        <h1 className="text-2xl font-semibold">{mode === "edit" ? "Edit site" : "Create site"}</h1>
      </div>
      <form onSubmit={submit} className="space-y-5">
        <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <Field id="site-name" label="Name" error={validation.name}><input id="site-name" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} className={inputClass(Boolean(validation.name))} /></Field>
            <Field id="site-base-url" label="Base URL" error={validation.baseUrl} helper="Use the primary URL or path that represents this website property."><input id="site-base-url" value={form.base_url} onChange={(event) => setForm({ ...form, base_url: event.target.value })} className={inputClass(Boolean(validation.baseUrl))} placeholder="https://www.example.com/learn/" /></Field>
            <Field id="site-description" label="Description"><textarea id="site-description" value={form.description ?? ""} onChange={(event) => setForm({ ...form, description: event.target.value })} className={inputClass()} rows={3} /></Field>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Field id="site-group" label="Group" helper="Optional. Create your own grouping label."><input id="site-group" value={form.group_key} onChange={(event) => setForm({ ...form, group_key: event.target.value })} className={inputClass()} placeholder="Marketing" /></Field>
              <Field id="site-locale" label="Locale" error={validation.locale} helper="Optional. Example: en-US"><input id="site-locale" value={form.locale ?? ""} onChange={(event) => setForm({ ...form, locale: event.target.value })} className={inputClass(Boolean(validation.locale))} /></Field>
              <Field id="site-platform" label="Platform" helper="Optional. Example: WordPress Learn"><input id="site-platform" value={form.platform_key} onChange={(event) => setForm({ ...form, platform_key: event.target.value })} className={inputClass()} placeholder="WordPress" /></Field>
              <Field id="site-ownership" label="Ownership" helper="Optional. Team or owner name."><input id="site-ownership" value={form.ownership_key} onChange={(event) => setForm({ ...form, ownership_key: event.target.value })} className={inputClass()} placeholder="Web Team" /></Field>
            </div>
            {mode === "edit" ? <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.is_active} onChange={(event) => setForm({ ...form, is_active: event.target.checked })} className="size-4 rounded border-stone-300" />Active site</label> : null}
          </div>
        </section>
        <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
          <h2 className="text-base font-semibold">Saved scope settings</h2>
          <p className="mt-1 text-sm text-stone-600">These settings are copied into each new scan. Scan-specific changes do not alter the saved site.</p>
          <div className="mt-4 grid grid-cols-1 gap-5 lg:grid-cols-2">
            <TextArea id="allowed-hosts" label="Allowed hosts" value={listFields.allowed_host_patterns} onChange={(value) => updateList("allowed_host_patterns", value)} />
            <TextArea id="excluded-hosts" label="Excluded hosts" value={listFields.excluded_host_patterns} onChange={(value) => updateList("excluded_host_patterns", value)} />
            <TextArea id="included-paths" label="Included path prefixes" value={listFields.included_path_prefixes} onChange={(value) => updateList("included_path_prefixes", value)} />
            <TextArea id="excluded-paths" label="Excluded path prefixes" value={listFields.excluded_path_prefixes} onChange={(value) => updateList("excluded_path_prefixes", value)} />
            <TextArea id="dropped-query-parameters" label="Dropped query parameters" value={listFields.drop_query_parameters} onChange={(value) => updateList("drop_query_parameters", value)} />
            <div className="space-y-4">
              <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.scope_config.follow_subdomains} onChange={(event) => setForm({ ...form, scope_config: { ...form.scope_config, follow_subdomains: event.target.checked } })} className="size-4 rounded border-stone-300" />Follow subdomains</label>
              <NumberField id="max-pages" label="Maximum pages" value={form.scope_config.max_pages} error={validation.maxPages} onChange={(value) => updateScopeNumber("max_pages", value)} />
              <NumberField id="max-depth" label="Maximum depth" value={form.scope_config.max_depth} error={validation.maxDepth} onChange={(value) => updateScopeNumber("max_depth", value)} />
              <NumberField id="request-timeout" label="Request timeout" value={form.scope_config.request_timeout_seconds} error={validation.requestTimeout} onChange={(value) => updateScopeNumber("request_timeout_seconds", value)} />
              <NumberField id="max-html-bytes" label="Maximum HTML response size" value={form.scope_config.max_html_response_bytes} error={validation.maxHtmlBytes} onChange={(value) => updateScopeNumber("max_html_response_bytes", value)} />
              <NumberField id="request-delay" label="Delay between requests" value={form.scope_config.delay_between_requests_ms} error={validation.requestDelay} onChange={(value) => updateScopeNumber("delay_between_requests_ms", value)} />
              <NumberField id="max-redirects" label="Maximum redirects" value={form.scope_config.max_redirects} error={validation.maxRedirects} onChange={(value) => updateScopeNumber("max_redirects", value)} />
              <Field id="user-agent" label="User agent"><input id="user-agent" value={form.scope_config.user_agent} onChange={(event) => setForm({ ...form, scope_config: { ...form.scope_config, user_agent: event.target.value } })} className={inputClass()} /></Field>
              <Field id="saved-render-mode" label="Default render mode" helper="Copied into new scans; existing scans are unchanged."><select id="saved-render-mode" value={form.scope_config.render_mode} onChange={(event) => setForm({ ...form, scope_config: { ...form.scope_config, render_mode: event.target.value as ScopeConfig["render_mode"] } })} className={inputClass()}><option value="none">Static only</option><option value="starting_page">Starting page</option><option value="all_eligible">All eligible pages</option></select></Field>
              {form.scope_config.render_mode !== "none" ? <NumberField id="saved-render-max" label="Maximum rendered pages" value={form.scope_config.render_max_pages} error={validation.renderMaxPages} onChange={(value) => setForm((current) => ({ ...current, scope_config: { ...current.scope_config, render_max_pages: Number(value) } }))} /> : null}
              {renderCapabilities.error ? <div className="text-xs text-red-700">Rendering limits are currently unavailable.</div> : null}
            </div>
          </div>
          <ScopeSummary scope={effectiveScope} baseUrl={baseValidation.normalizedUrl} />
        </section>
        {save.error ? <ErrorBanner error={save.error} title="Could not save site" /> : null}
        <div className="flex justify-end gap-2">
          <Link to={mode === "edit" ? `/sites/${siteId}` : "/sites"} className="rounded-md border border-stone-300 bg-white px-3 py-2 text-sm font-medium">Cancel</Link>
          <Button type="submit" variant="primary" loading={save.isPending} disabled={validation.hasErrors}>{mode === "edit" ? "Save site" : "Create site"}</Button>
        </div>
      </form>
    </PageFrame>
  );
}

function PageFrame({ children }: { children: React.ReactNode }) {
  return <section className="mx-auto max-w-5xl px-4 py-6 sm:px-6 lg:px-8">{children}</section>;
}

function TextArea({ id, label, value, onChange }: { id: string; label: string; value: string; onChange: (value: string) => void }) {
  return <Field id={id} label={label} helper="One value per line. Blank lines are ignored."><textarea id={id} value={value} onChange={(event) => onChange(event.target.value)} rows={5} className={`${inputClass()} font-mono text-xs leading-5`} /></Field>;
}

function NumberField({ id, label, value, error, onChange }: { id: string; label: string; value: number; error: string | null; onChange: (value: string) => void }) {
  return <Field id={id} label={label} error={error}><input id={id} type="number" value={Number.isNaN(value) ? "" : value} onChange={(event) => onChange(event.target.value)} className={inputClass(Boolean(error))} /></Field>;
}

function ScopeSummary({ scope, baseUrl }: { scope: ScopeConfig; baseUrl: string }) {
  const host = hostname(baseUrl);
  return (
    <section aria-label="Scope summary" className="mt-4 rounded-md border border-stone-200 bg-stone-50 p-4 text-sm">
      <div className="font-medium">Scope summary</div>
      <div className="mt-3 flex flex-wrap gap-2">
        <Pill>{scope.allowed_host_patterns.length ? plural(scope.allowed_host_patterns.length, "allowed host") : host ? `Exact hostname: ${host}` : "Exact hostname will be derived"}</Pill>
        <Pill>{scope.follow_subdomains ? "Subdomains included" : "Subdomains excluded"}</Pill>
        <Pill>{scope.included_path_prefixes.filter((path) => path !== "/").length ? plural(scope.included_path_prefixes.length, "included path") : "All paths included"}</Pill>
        <Pill>Maximum {scope.max_pages || 0} pages</Pill>
        <Pill>Maximum depth {scope.max_depth || 0}</Pill>
      </div>
    </section>
  );
}

function hostname(value: string) {
  try {
    return value ? new URL(value).hostname : "";
  } catch {
    return "";
  }
}

function Pill({ children }: { children: React.ReactNode }) {
  return <span className="rounded-md border border-stone-200 bg-white px-2 py-1 text-xs text-stone-700">{children}</span>;
}

function scopeFromForm(scope: ScopeConfig, listFields: ListFieldText): ScopeConfig {
  return {
    ...scope,
    allowed_host_patterns: parseLineList(listFields.allowed_host_patterns),
    excluded_host_patterns: parseLineList(listFields.excluded_host_patterns),
    included_path_prefixes: parseLineList(listFields.included_path_prefixes),
    excluded_path_prefixes: parseLineList(listFields.excluded_path_prefixes),
    drop_query_parameters: parseLineList(listFields.drop_query_parameters)
  };
}

function listsFromScope(scope: ScopeConfig): ListFieldText {
  return {
    allowed_host_patterns: scope.allowed_host_patterns.join("\n"),
    excluded_host_patterns: scope.excluded_host_patterns.join("\n"),
    included_path_prefixes: scope.included_path_prefixes.join("\n"),
    excluded_path_prefixes: scope.excluded_path_prefixes.join("\n"),
    drop_query_parameters: scope.drop_query_parameters.join("\n")
  };
}

function validate(form: SitePayload, baseValidation: ReturnType<typeof normalizeStartingUrlInput>, scope: ScopeConfig) {
  const locale = form.locale && !/^[a-z]{2}-[A-Z]{2}$/.test(form.locale) ? "Locale must look like en-US." : null;
  const validation = {
    name: form.name.trim() ? null : "Name is required.",
    baseUrl: baseValidation.error,
    locale,
    maxPages: validateInteger(scope.max_pages, 1, 10000, "Maximum pages must be between 1 and 10,000."),
    maxDepth: validateInteger(scope.max_depth, 0, 50, "Maximum depth must be between 0 and 50."),
    requestTimeout: validateNumber(scope.request_timeout_seconds, 1, 300, "Request timeout must be between 1 and 300 seconds."),
    maxHtmlBytes: validateInteger(scope.max_html_response_bytes, 1, 100000000, "Maximum HTML response size must be at least 1 byte."),
    requestDelay: validateInteger(scope.delay_between_requests_ms, 0, 60000, "Delay must be between 0 and 60,000 milliseconds."),
    maxRedirects: validateInteger(scope.max_redirects, 0, 50, "Maximum redirects must be between 0 and 50."),
    renderMaxPages: scope.render_mode === "none" ? null : validateInteger(scope.render_max_pages, 1, Math.min(scope.max_pages, 1000), "Rendered pages must be between 1 and the maximum page count.")
  };
  return { ...validation, hasErrors: Object.values(validation).some(Boolean) };
}

function validateInteger(value: number, min: number, max: number, message: string) {
  if (!Number.isInteger(value) || value < min || value > max) return message;
  return null;
}

function validateNumber(value: number, min: number, max: number, message: string) {
  if (!Number.isFinite(value) || value < min || value > max) return message;
  return null;
}
