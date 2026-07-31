import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { createScan, createSiteScan, defaultScope, listSites } from "../api/client";
import { Button } from "../components/ui/Button";
import { ErrorBanner } from "../components/ui/ErrorBanner";
import { Field } from "../components/ui/Field";
import { LoadingBlock } from "../components/ui/Loading";
import { inputClass } from "../components/ui/styles";
import type { ScopeConfig, SiteListItem } from "../types/scans";
import { plural } from "../utils/format";
import { normalizeStartingUrlInput, parseLineList } from "../utils/url";

const preferenceKey = "artsen.scan.preferences";

type ListFields = Pick<
  ScopeConfig,
  "allowed_host_patterns" | "excluded_host_patterns" | "included_path_prefixes" | "excluded_path_prefixes" | "drop_query_parameters"
>;

type ListFieldText = Record<keyof ListFields, string>;

type Preferences = {
  max_pages?: number;
  max_depth?: number;
  advanced_open?: boolean;
};

export function NewScanPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [searchParams] = useSearchParams();
  const initialSiteId = searchParams.get("site_id") ?? "";
  const sites = useQuery({ queryKey: ["sites", "active-selector"], queryFn: () => listSites("?active_state=active&limit=100&sort=name") });
  const [mode, setMode] = useState<"site" | "ad_hoc">(initialSiteId ? "site" : "ad_hoc");
  const [selectedSiteId, setSelectedSiteId] = useState(initialSiteId);
  const initialScope = useMemo(() => scopeFromQuery(searchParams), [searchParams]);
  const preferences = useMemo(() => readPreferences(), []);
  const [startingUrl, setStartingUrl] = useState(searchParams.get("starting_url") ?? "");
  const [advancedOpen, setAdvancedOpen] = useState(preferences.advanced_open ?? false);
  const [scope, setScope] = useState<ScopeConfig>({
    ...initialScope,
    max_pages: preferences.max_pages ?? initialScope.max_pages,
    max_depth: preferences.max_depth ?? initialScope.max_depth
  });
  const [listFields, setListFields] = useState<ListFieldText>(() => listsFromScope(initialScope));
  const submittingRef = useRef(false);
  const urlValidation = useMemo(() => normalizeStartingUrlInput(startingUrl), [startingUrl]);
  const effectiveScope = useMemo(() => scopeFromForm(scope, listFields), [scope, listFields]);
  const validation = useMemo(() => validateForm(startingUrl, urlValidation, scope), [startingUrl, urlValidation, scope]);
  const selectedSite = sites.data?.items.find((site) => String(site.id) === selectedSiteId);
  const mutation = useMutation({
    mutationFn: () => mode === "site" && selectedSite ? createSiteScan(String(selectedSite.id), effectiveScope) : createScan(urlValidation.normalizedUrl, effectiveScope),
    onSuccess: async (scan) => {
      await queryClient.invalidateQueries({ queryKey: ["scans"] });
      navigate(`/scans/${scan.id}`);
    },
    onSettled: () => {
      submittingRef.current = false;
    }
  });
  const canStart = mode === "site" ? Boolean(selectedSite) && !validation.hasErrors && !mutation.isPending : !validation.hasErrors && !mutation.isPending;

  useEffect(() => {
    if (!selectedSite || mode !== "site") return;
    setStartingUrl(selectedSite.base_url);
    setScope(selectedSite.scope_config);
    setListFields(listsFromScope(selectedSite.scope_config));
  }, [selectedSite, mode]);

  useEffect(() => {
    writePreferences({
      max_pages: scope.max_pages,
      max_depth: scope.max_depth,
      advanced_open: advancedOpen
    });
  }, [advancedOpen, scope.max_depth, scope.max_pages]);

  function updateList(key: keyof ListFieldText, value: string) {
    setListFields((current) => ({ ...current, [key]: value }));
  }

  function updateNumber(key: keyof Pick<ScopeConfig, "max_pages" | "max_depth" | "request_timeout_seconds" | "max_html_response_bytes" | "delay_between_requests_ms" | "max_redirects">, value: string) {
    setScope((current) => ({ ...current, [key]: value === "" ? Number.NaN : Number(value) }));
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (submittingRef.current) return;
    if (!canStart) return;
    submittingRef.current = true;
    mutation.mutate();
  }

  return (
    <section className="mx-auto max-w-4xl px-4 py-6 sm:px-6 lg:px-8">
      <div className="mb-6">
        <div className="text-sm text-stone-500">Scans</div>
        <h1 className="mt-1 text-2xl font-semibold tracking-normal text-stone-950">Start a new scan</h1>
      </div>

      <form onSubmit={submit} className="space-y-6">
        <div className="rounded-md border border-stone-200 bg-white p-4 shadow-sm sm:p-5">
          <div className="mb-4 text-sm font-medium text-stone-900">Mode</div>
          <div className="flex flex-wrap gap-3">
            <label className="flex items-center gap-2 text-sm"><input type="radio" checked={mode === "site"} onChange={() => setMode("site")} className="size-4" />Saved site</label>
            <label className="flex items-center gap-2 text-sm"><input type="radio" checked={mode === "ad_hoc"} onChange={() => setMode("ad_hoc")} className="size-4" />Ad hoc URL</label>
          </div>
          {mode === "site" ? (
            <div className="mt-4">
              {sites.isLoading ? <LoadingBlock label="Loading active sites..." /> : null}
              {sites.data?.items.length ? (
                <Field id="saved-site" label="Site" helper="Scan-specific settings below are copied from the saved site and do not update it.">
                  <select id="saved-site" value={selectedSiteId} onChange={(event) => setSelectedSiteId(event.target.value)} className={inputClass()}>
                    <option value="">Select a site</option>
                    {sites.data.items.map((site: SiteListItem) => <option key={site.id} value={site.id}>{site.name} · {site.base_url}</option>)}
                  </select>
                </Field>
              ) : !sites.isLoading ? (
                <div className="text-sm text-stone-600">No active sites yet. <a className="underline" href="/sites/new">Create site</a></div>
              ) : null}
              {selectedSite ? (
                <div className="mt-3 rounded-md border border-stone-200 bg-stone-50 p-3 text-sm">
                  <div className="font-medium">{selectedSite.name}</div>
                  <div className="mt-1 font-mono text-xs text-stone-600">{selectedSite.base_url}</div>
                  <Button type="button" className="mt-3" onClick={() => {
                    setScope(selectedSite.scope_config);
                    setListFields(listsFromScope(selectedSite.scope_config));
                  }}>Reset to saved site configuration</Button>
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
        <div className="rounded-md border border-stone-200 bg-white p-4 shadow-sm sm:p-5">
          {mode === "site" ? <h2 className="mb-4 text-base font-semibold">Scan-specific settings</h2> : null}
          {mode === "ad_hoc" ? <Field
            id="starting-url"
            label="Starting URL"
            error={validation.startingUrl}
            helper={
              urlValidation.hostname && !validation.startingUrl ? (
                <>
                  By default, this scan is limited to <code className="rounded bg-stone-100 px-1 py-0.5">{urlValidation.hostname}</code>.
                </>
              ) : (
                "Enter a public HTTP or HTTPS page. Bare hostnames are converted to HTTPS."
              )
            }
          >
            <input
              id="starting-url"
              aria-describedby="starting-url-helper starting-url-error"
              value={startingUrl}
              onBlur={() => {
                if (!urlValidation.error && startingUrl.trim() !== urlValidation.normalizedUrl) setStartingUrl(urlValidation.normalizedUrl);
              }}
              onChange={(event) => setStartingUrl(event.target.value)}
              className={`${inputClass(Boolean(validation.startingUrl))} text-base`}
              placeholder="https://www.example.com/"
            />
          </Field> : null}

          <div className="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field id="max-pages" label="Maximum pages" error={validation.maxPages} helper="Stop after this many pages have been fetched or skipped.">
              <input id="max-pages" type="number" min={1} max={10000} value={numberInputValue(scope.max_pages)} onChange={(event) => updateNumber("max_pages", event.target.value)} className={inputClass(Boolean(validation.maxPages))} />
            </Field>
            <Field id="max-depth" label="Maximum depth" error={validation.maxDepth} helper="Depth 0 scans only the starting URL.">
              <input id="max-depth" type="number" min={0} max={50} value={numberInputValue(scope.max_depth)} onChange={(event) => updateNumber("max_depth", event.target.value)} className={inputClass(Boolean(validation.maxDepth))} />
            </Field>
          </div>
        </div>

        <details open={advancedOpen} onToggle={(event) => setAdvancedOpen(event.currentTarget.open)} className="rounded-md border border-stone-200 bg-white p-4 shadow-sm sm:p-5">
          <summary className="cursor-pointer text-sm font-medium text-stone-900 focus:outline-none focus:ring-2 focus:ring-neutral-900 focus:ring-offset-2">
            Advanced scope settings
          </summary>
          <div className="mt-5 grid grid-cols-1 gap-5 lg:grid-cols-2">
            <TextArea
              id="allowed-hosts"
              label="Allowed hosts"
              value={listFields.allowed_host_patterns}
              onChange={(value) => updateList("allowed_host_patterns", value)}
              helper={"One hostname or wildcard pattern per line. Blank lines are ignored.\nexample.com\nblog.example.com\n*.example.org"}
            />
            <TextArea
              id="excluded-hosts"
              label="Excluded hosts"
              value={listFields.excluded_host_patterns}
              onChange={(value) => updateList("excluded_host_patterns", value)}
              helper={"One hostname or wildcard pattern per line. Blank lines are ignored.\nsupport.*\nold.example.com"}
            />
            <TextArea
              id="included-paths"
              label="Included path prefixes"
              value={listFields.included_path_prefixes}
              onChange={(value) => updateList("included_path_prefixes", value)}
              helper={"One path prefix per line. Use / to include all paths.\n/\n/docs/"}
            />
            <TextArea
              id="excluded-paths"
              label="Excluded path prefixes"
              value={listFields.excluded_path_prefixes}
              onChange={(value) => updateList("excluded_path_prefixes", value)}
              helper={"One path prefix per line. Blank lines are ignored.\n/wp-admin/\n/private/"}
            />
            <TextArea
              id="dropped-query-parameters"
              label="Dropped query parameters"
              value={listFields.drop_query_parameters}
              onChange={(value) => updateList("drop_query_parameters", value)}
              helper={"One parameter name or wildcard per line. Blank lines are ignored.\nutm_*\ngclid\nfbclid"}
            />
            <div className="space-y-4">
              <label className="flex items-start gap-3 rounded-md border border-stone-200 p-3 text-sm" htmlFor="follow-subdomains">
                <input id="follow-subdomains" type="checkbox" checked={scope.follow_subdomains} onChange={(event) => setScope({ ...scope, follow_subdomains: event.target.checked })} className="mt-0.5 size-4 rounded border-stone-300 focus:ring-neutral-900" />
                <span>
                  <span className="block font-medium text-stone-900">Follow subdomains for explicit allowed hosts</span>
                  <span className="mt-1 block text-xs leading-5 text-stone-600">This only applies when allowed hosts include base hostnames.</span>
                </span>
              </label>
              <Field id="request-timeout" label="Request timeout" error={validation.requestTimeout} helper="Seconds before a request is recorded as timed out.">
                <input id="request-timeout" type="number" min={1} value={numberInputValue(scope.request_timeout_seconds)} onChange={(event) => updateNumber("request_timeout_seconds", event.target.value)} className={inputClass(Boolean(validation.requestTimeout))} />
              </Field>
              <Field id="max-html-bytes" label="Maximum HTML response size" error={validation.maxHtmlBytes} helper="Bytes read before a page is stopped as too large.">
                <input id="max-html-bytes" type="number" min={1} value={numberInputValue(scope.max_html_response_bytes)} onChange={(event) => updateNumber("max_html_response_bytes", event.target.value)} className={inputClass(Boolean(validation.maxHtmlBytes))} />
              </Field>
              <Field id="request-delay" label="Delay between requests" error={validation.requestDelay} helper="Milliseconds to wait between sequential requests.">
                <input id="request-delay" type="number" min={0} value={numberInputValue(scope.delay_between_requests_ms)} onChange={(event) => updateNumber("delay_between_requests_ms", event.target.value)} className={inputClass(Boolean(validation.requestDelay))} />
              </Field>
              <Field id="max-redirects" label="Maximum redirects" error={validation.maxRedirects} helper="Redirect hops allowed before stopping a request.">
                <input id="max-redirects" type="number" min={0} value={numberInputValue(scope.max_redirects)} onChange={(event) => updateNumber("max_redirects", event.target.value)} className={inputClass(Boolean(validation.maxRedirects))} />
              </Field>
              <Field id="user-agent" label="Custom user agent" helper="Sent with crawler requests. Do not include credentials.">
                <input id="user-agent" value={scope.user_agent} onChange={(event) => setScope({ ...scope, user_agent: event.target.value })} className={inputClass()} />
              </Field>
            </div>
          </div>
        </details>

        <ScopeSummary hostname={urlValidation.hostname} scope={effectiveScope} />

        {mutation.error ? <ErrorBanner error={mutation.error} title="Could not start scan" /> : null}

        <div className="flex justify-end">
          <Button type="submit" variant="primary" disabled={!canStart} loading={mutation.isPending}>
            {mutation.isPending ? "Starting scan..." : "Start scan"}
          </Button>
        </div>
      </form>
    </section>
  );
}

function TextArea({ id, label, value, helper, onChange }: { id: string; label: string; value: string; helper: string; onChange: (value: string) => void }) {
  return (
    <Field id={id} label={label} helper={<span className="whitespace-pre-line">{helper}</span>}>
      <textarea id={id} value={value} onChange={(event) => onChange(event.target.value)} rows={5} className={`${inputClass()} font-mono text-xs leading-5`} />
    </Field>
  );
}

function ScopeSummary({ hostname, scope }: { hostname: string; scope: ScopeConfig }) {
  const allowedHosts = scope.allowed_host_patterns.length;
  const includedPaths = scope.included_path_prefixes.filter((path) => path !== "/").length;
  return (
    <section aria-label="Scope summary" className="rounded-md border border-stone-200 bg-stone-50 p-4 text-sm">
      <div className="font-medium text-stone-900">Scope summary</div>
      <div className="mt-3 flex flex-wrap gap-2">
        <SummaryPill>{allowedHosts ? plural(allowedHosts, "allowed host") : hostname ? `Exact hostname: ${hostname}` : "Exact hostname will be derived"}</SummaryPill>
        <SummaryPill>{scope.follow_subdomains ? "Subdomains included for allowed hosts" : "Subdomains excluded"}</SummaryPill>
        <SummaryPill>{includedPaths ? plural(includedPaths, "included path") : "All paths included"}</SummaryPill>
        <SummaryPill>{scope.excluded_path_prefixes.length ? plural(scope.excluded_path_prefixes.length, "path exclusion") : "No path exclusions"}</SummaryPill>
        <SummaryPill>{scope.drop_query_parameters.length ? `${scope.drop_query_parameters.length} tracking parameters removed` : "No query parameters removed"}</SummaryPill>
        <SummaryPill>Maximum {scope.max_pages || 0} pages</SummaryPill>
        <SummaryPill>Maximum depth {scope.max_depth || 0}</SummaryPill>
      </div>
    </section>
  );
}

function SummaryPill({ children }: { children: React.ReactNode }) {
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

function validateForm(_startingUrl: string, urlValidation: ReturnType<typeof normalizeStartingUrlInput>, scope: ScopeConfig) {
  const validation = {
    startingUrl: urlValidation.error,
    maxPages: validateInteger(scope.max_pages, 1, 10000, "Maximum pages must be between 1 and 10,000."),
    maxDepth: validateInteger(scope.max_depth, 0, 50, "Maximum depth must be between 0 and 50."),
    requestTimeout: validateNumber(scope.request_timeout_seconds, 1, 300, "Request timeout must be between 1 and 300 seconds."),
    maxHtmlBytes: validateInteger(scope.max_html_response_bytes, 1, 100000000, "Maximum HTML response size must be at least 1 byte."),
    requestDelay: validateInteger(scope.delay_between_requests_ms, 0, 60000, "Delay must be between 0 and 60,000 milliseconds."),
    maxRedirects: validateInteger(scope.max_redirects, 0, 50, "Maximum redirects must be between 0 and 50.")
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

function numberInputValue(value: number) {
  return Number.isNaN(value) ? "" : value;
}

function readPreferences(): Preferences {
  try {
    const value = window.localStorage.getItem(preferenceKey);
    return value ? (JSON.parse(value) as Preferences) : {};
  } catch {
    return {};
  }
}

function writePreferences(preferences: Preferences) {
  window.localStorage.setItem(preferenceKey, JSON.stringify(preferences));
}

function scopeFromQuery(searchParams: URLSearchParams) {
  const raw = searchParams.get("scope");
  if (!raw) return defaultScope();
  try {
    return { ...defaultScope(), ...(JSON.parse(raw) as Partial<ScopeConfig>) };
  } catch {
    return defaultScope();
  }
}
