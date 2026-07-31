import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { createSite, defaultScope, getSite, updateSite } from "../api/client";
import { Button } from "../components/ui/Button";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorBanner } from "../components/ui/ErrorBanner";
import { Field } from "../components/ui/Field";
import { LoadingBlock } from "../components/ui/Loading";
import { inputClass } from "../components/ui/styles";
import { groupOptions, ownershipOptions, platformOptions } from "../types/siteClassifications";
import type { ScopeConfig, SitePayload } from "../types/scans";
import { plural } from "../utils/format";
import { normalizeStartingUrlInput, parseLineList } from "../utils/url";

type ListFields = Pick<ScopeConfig, "allowed_host_patterns" | "excluded_host_patterns" | "included_path_prefixes" | "excluded_path_prefixes" | "drop_query_parameters">;
type ListFieldText = Record<keyof ListFields, string>;

export function SiteFormPage({ mode }: { mode: "create" | "edit" }) {
  const { siteId = "" } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const existing = useQuery({ queryKey: ["site", siteId], queryFn: () => getSite(siteId), enabled: mode === "edit" });
  const [touchedIncludedPaths, setTouchedIncludedPaths] = useState(false);
  const [form, setForm] = useState<SitePayload>({
    name: "",
    base_url: "",
    description: "",
    group_key: "other",
    locale: "",
    platform_key: "other",
    ownership_key: "unknown",
    scope_config: defaultScope(),
    is_active: true
  });
  const [listFields, setListFields] = useState<ListFieldText>(() => listsFromScope(defaultScope()));
  const baseValidation = useMemo(() => normalizeStartingUrlInput(form.base_url), [form.base_url]);
  const effectiveScope = useMemo(() => scopeFromForm(form.scope_config, listFields), [form.scope_config, listFields]);
  const validation = validate(form, baseValidation);
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
      scope_config: existing.data.scope_config,
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
              <SelectField id="site-group" label="Group" value={form.group_key} options={groupOptions} onChange={(value) => setForm({ ...form, group_key: value })} />
              <Field id="site-locale" label="Locale" error={validation.locale} helper="Optional. Example: en-US"><input id="site-locale" value={form.locale ?? ""} onChange={(event) => setForm({ ...form, locale: event.target.value })} className={inputClass(Boolean(validation.locale))} /></Field>
              <SelectField id="site-platform" label="Platform" value={form.platform_key} options={platformOptions} onChange={(value) => setForm({ ...form, platform_key: value })} />
              <SelectField id="site-ownership" label="Ownership" value={form.ownership_key} options={ownershipOptions} onChange={(value) => setForm({ ...form, ownership_key: value })} />
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
              <NumberField id="max-pages" label="Maximum pages" value={form.scope_config.max_pages} onChange={(value) => updateScopeNumber("max_pages", value)} />
              <NumberField id="max-depth" label="Maximum depth" value={form.scope_config.max_depth} onChange={(value) => updateScopeNumber("max_depth", value)} />
              <NumberField id="request-timeout" label="Request timeout" value={form.scope_config.request_timeout_seconds} onChange={(value) => updateScopeNumber("request_timeout_seconds", value)} />
              <NumberField id="max-html-bytes" label="Maximum HTML response size" value={form.scope_config.max_html_response_bytes} onChange={(value) => updateScopeNumber("max_html_response_bytes", value)} />
              <NumberField id="request-delay" label="Delay between requests" value={form.scope_config.delay_between_requests_ms} onChange={(value) => updateScopeNumber("delay_between_requests_ms", value)} />
              <NumberField id="max-redirects" label="Maximum redirects" value={form.scope_config.max_redirects} onChange={(value) => updateScopeNumber("max_redirects", value)} />
              <Field id="user-agent" label="User agent"><input id="user-agent" value={form.scope_config.user_agent} onChange={(event) => setForm({ ...form, scope_config: { ...form.scope_config, user_agent: event.target.value } })} className={inputClass()} /></Field>
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

function SelectField({ id, label, value, options, onChange }: { id: string; label: string; value: string; options: Array<{ value: string; label: string }>; onChange: (value: string) => void }) {
  return <Field id={id} label={label}><select id={id} value={value} onChange={(event) => onChange(event.target.value)} className={inputClass()}>{options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></Field>;
}

function TextArea({ id, label, value, onChange }: { id: string; label: string; value: string; onChange: (value: string) => void }) {
  return <Field id={id} label={label} helper="One value per line. Blank lines are ignored."><textarea id={id} value={value} onChange={(event) => onChange(event.target.value)} rows={5} className={`${inputClass()} font-mono text-xs leading-5`} /></Field>;
}

function NumberField({ id, label, value, onChange }: { id: string; label: string; value: number; onChange: (value: string) => void }) {
  return <Field id={id} label={label}><input id={id} type="number" value={Number.isNaN(value) ? "" : value} onChange={(event) => onChange(event.target.value)} className={inputClass()} /></Field>;
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

function validate(form: SitePayload, baseValidation: ReturnType<typeof normalizeStartingUrlInput>) {
  const locale = form.locale && !/^[a-z]{2}-[A-Z]{2}$/.test(form.locale) ? "Locale must look like en-US." : null;
  return {
    name: form.name.trim() ? null : "Name is required.",
    baseUrl: baseValidation.error,
    locale,
    hasErrors: !form.name.trim() || Boolean(baseValidation.error) || Boolean(locale)
  };
}
