import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { createScan, createSiteScan, defaultScope, getRenderCapabilities, listSites, listSources } from "../api/client";
import { Button } from "../components/ui/Button";
import { ErrorBanner } from "../components/ui/ErrorBanner";
import { Field } from "../components/ui/Field";
import { LoadingBlock } from "../components/ui/Loading";
import { inputClass } from "../components/ui/styles";
import type { RenderCapabilities, ScopeConfig, SiteListItem } from "../types/scans";
import { plural } from "../utils/format";
import { normalizeStartingUrlInput, parseLineList } from "../utils/url";
import { useDocumentTitle } from "../utils/useDocumentTitle";

const preferenceKey = "website-scanner.scan.preferences";

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
  useDocumentTitle("New Scan");
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [searchParams] = useSearchParams();
  const initialSiteId = searchParams.get("site_id") ?? "";
  const sites = useQuery({ queryKey: ["sites", "active-selector"], queryFn: () => listSites("?active_state=active&limit=100&sort=name") });
  const renderCapabilities = useQuery({ queryKey: ["render-capabilities"], queryFn: getRenderCapabilities });
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
  const [includeInventory, setIncludeInventory] = useState(false);
  const [selectedSourceIds, setSelectedSourceIds] = useState<number[]>([]);
  const [sourceSelectionTouched, setSourceSelectionTouched] = useState(false);
  const submittingRef = useRef(false);
  const urlValidation = useMemo(() => normalizeStartingUrlInput(startingUrl), [startingUrl]);
  const effectiveScope = useMemo(() => scopeFromForm(scope, listFields), [scope, listFields]);
  const validation = useMemo(() => validateForm(startingUrl, urlValidation, scope, renderCapabilities.data), [startingUrl, urlValidation, scope, renderCapabilities.data]);
  const selectedSite = sites.data?.items.find((site) => String(site.id) === selectedSiteId);
  const sources = useQuery({
    queryKey: ["sources", selectedSiteId, "scan-selector"],
    queryFn: () => listSources(selectedSiteId, "?active_state=active&limit=100"),
    enabled: mode === "site" && Boolean(selectedSiteId)
  });
  const sourceItems = useMemo(() => sources.data?.items ?? [], [sources.data?.items]);
  const sourceIds = useMemo(() => sourceItems.map((source) => source.id), [sourceItems]);
  const allSourcesSelected = sourceIds.length > 0 && sourceIds.every((id) => selectedSourceIds.includes(id));
  const sourceSelectionError = includeInventory && sourceIds.length > 0 && selectedSourceIds.length === 0 ? "Select at least one source, or turn off inventory." : null;
  const mutation = useMutation({
    mutationFn: () => mode === "site" && selectedSite ? createSiteScan(String(selectedSite.id), effectiveScope, includeInventory, selectedSourceIds) : createScan(urlValidation.normalizedUrl, effectiveScope),
    onSuccess: async (scan) => {
      await queryClient.invalidateQueries({ queryKey: ["scans"] });
      navigate(`/scans/${scan.id}`);
    },
    onSettled: () => {
      submittingRef.current = false;
    }
  });
  const canStart = mode === "site" ? Boolean(selectedSite) && !validation.hasErrors && !sourceSelectionError && !mutation.isPending : !validation.hasErrors && !mutation.isPending;

  useEffect(() => {
    if (!selectedSite || mode !== "site") return;
    setStartingUrl(selectedSite.base_url);
    setScope(hydrateScope(selectedSite.scope_config));
    setListFields(listsFromScope(hydrateScope(selectedSite.scope_config)));
    setSelectedSourceIds([]);
    setSourceSelectionTouched(false);
  }, [selectedSite, mode]);

  useEffect(() => {
    if (!includeInventory || sourceSelectionTouched || sourceIds.length === 0) return;
    setSelectedSourceIds(sourceIds);
  }, [includeInventory, sourceIds, sourceSelectionTouched]);

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

  function updateNumber(key: keyof Pick<ScopeConfig, "max_pages" | "max_depth" | "request_timeout_seconds" | "static_max_attempts" | "static_retry_initial_delay_ms" | "static_retry_max_delay_ms" | "max_html_response_bytes" | "delay_between_requests_ms" | "max_redirects">, value: string) {
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
                  <label className="mt-3 flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={includeInventory}
                      onChange={(event) => {
                        setIncludeInventory(event.target.checked);
                        if (!event.target.checked) {
                          setSelectedSourceIds([]);
                          setSourceSelectionTouched(false);
                        }
                      }}
                      className="size-4 rounded border-stone-300"
                    />
                    Include current URL inventory
                  </label>
                  {includeInventory ? (
                    <div className="mt-3 rounded-md border border-stone-200 bg-white p-3">
                      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                        <div className="text-xs font-medium text-stone-600">Sources</div>
                        {sourceIds.length ? (
                          <label className="flex items-center gap-2 text-xs font-medium text-stone-700">
                            <input
                              type="checkbox"
                              checked={allSourcesSelected}
                              onChange={(event) => {
                                setSourceSelectionTouched(true);
                                setSelectedSourceIds(event.target.checked ? sourceIds : []);
                              }}
                              className="size-4 rounded border-stone-300"
                            />
                            Select all sources
                          </label>
                        ) : null}
                      </div>
                      {sources.isLoading ? <LoadingBlock label="Loading sources..." /> : null}
                      {sourceItems.length ? sourceItems.map((source) => (
                        <label key={source.id} className="flex items-center gap-2 py-1 text-xs">
                          <input
                            type="checkbox"
                            checked={selectedSourceIds.includes(source.id)}
                            onChange={(event) => {
                              setSourceSelectionTouched(true);
                              setSelectedSourceIds((current) => event.target.checked ? [...new Set([...current, source.id])] : current.filter((id) => id !== source.id));
                            }}
                            className="size-4 rounded border-stone-300"
                          />
                          <span>{source.name} · {source.current_entry_count} URLs</span>
                        </label>
                      )) : !sources.isLoading ? <div className="text-xs text-stone-500">No active sources yet. All current active sources will be used when available.</div> : null}
                      {sourceSelectionError ? <div className="mt-2 text-xs text-red-700">{sourceSelectionError}</div> : null}
                    </div>
                  ) : null}
                  <Button type="button" className="mt-3" onClick={() => {
                    setScope(hydrateScope(selectedSite.scope_config));
                    setListFields(listsFromScope(hydrateScope(selectedSite.scope_config)));
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
          <div className="mt-5 rounded-md border border-stone-200 bg-stone-50 p-3">
            <div className="text-sm font-medium text-stone-900">Repeat-scan optimization</div>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <label className="flex items-start gap-3 text-sm">
                <input
                  type="checkbox"
                  checked={scope.enable_http_revalidation}
                  onChange={(event) => setScope({ ...scope, enable_http_revalidation: event.target.checked })}
                  className="mt-0.5 size-4 rounded border-stone-300"
                />
                <span>
                  <span className="block font-medium text-stone-900">Use HTTP revalidation</span>
                  <span className="block text-xs leading-5 text-stone-600">Send ETag and Last-Modified validators when a compatible prior observation exists. Turn off to force full content downloads.</span>
                </span>
              </label>
              <label className="flex items-start gap-3 text-sm">
                <input
                  type="checkbox"
                  checked={scope.enable_parse_reuse}
                  onChange={(event) => setScope({ ...scope, enable_parse_reuse: event.target.checked })}
                  className="mt-0.5 size-4 rounded border-stone-300"
                />
                <span>
                  <span className="block font-medium text-stone-900">Reuse parsed results</span>
                  <span className="block text-xs leading-5 text-stone-600">Reuse deterministic metadata and links for identical HTML. Turn off to force a full parse.</span>
                </span>
              </label>
            </div>
          </div>
        </div>

        <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm sm:p-5">
          <h2 className="text-base font-semibold">Browser-rendered observations</h2>
          <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field id="render-mode" label="Render mode" helper="Static HTTP evidence remains authoritative. Browser evidence is attached to eligible snapshots.">
              <select id="render-mode" value={scope.render_mode} onChange={(event) => setScope({ ...scope, render_mode: event.target.value as ScopeConfig["render_mode"] })} className={inputClass()}>
                <option value="none">Static only</option><option value="starting_page">Starting page</option><option value="all_eligible">All eligible pages</option>
              </select>
            </Field>
            {scope.render_mode !== "none" ? <Field id="render-max-pages" label="Maximum rendered pages" error={validation.renderMaxPages}>
              <input id="render-max-pages" type="number" min={renderCapabilities.data?.limits.render_max_pages.minimum ?? 1} max={Math.min(scope.max_pages, renderCapabilities.data?.limits.render_max_pages.maximum ?? scope.max_pages)} value={numberInputValue(scope.render_max_pages)} onChange={(event) => setScope({ ...scope, render_max_pages: Number(event.target.value) })} className={inputClass(Boolean(validation.renderMaxPages))} />
            </Field> : null}
            {scope.render_mode !== "none" ? <Field id="render-color" label="Color scheme"><select id="render-color" value={scope.render_color_scheme} onChange={(event) => setScope({ ...scope, render_color_scheme: event.target.value as ScopeConfig["render_color_scheme"] })} className={inputClass()}><option value="light">Light</option><option value="dark">Dark</option><option value="no-preference">No preference</option></select></Field> : null}
            {scope.render_mode !== "none" ? <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={scope.render_capture_full_page} onChange={(event) => setScope({ ...scope, render_capture_full_page: event.target.checked })} className="size-4 rounded border-stone-300" />Capture full-page screenshot</label> : null}
          </div>
          {scope.render_mode !== "none" ? <details className="mt-4 border-t border-stone-200 pt-4"><summary className="cursor-pointer text-sm font-medium">Advanced browser settings</summary><div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <RenderNumberField label="Viewport width" field="render_viewport_width" scope={scope} capabilities={renderCapabilities.data} onChange={setScope} />
            <RenderNumberField label="Viewport height" field="render_viewport_height" scope={scope} capabilities={renderCapabilities.data} onChange={setScope} />
            <RenderNumberField label="Device scale factor" field="render_device_scale_factor" scope={scope} capabilities={renderCapabilities.data} onChange={setScope} />
            <Field id="render-locale" label="Locale"><input id="render-locale" value={scope.render_locale} onChange={(event) => setScope({ ...scope, render_locale: event.target.value })} className={inputClass()} /></Field>
            <Field id="render-timezone" label="Timezone"><input id="render-timezone" value={scope.render_timezone} onChange={(event) => setScope({ ...scope, render_timezone: event.target.value })} className={inputClass()} /></Field>
            <Field id="render-motion" label="Motion"><select id="render-motion" value={scope.render_reduced_motion} onChange={(event) => setScope({ ...scope, render_reduced_motion: event.target.value as ScopeConfig["render_reduced_motion"] })} className={inputClass()}><option value="reduce">Reduce</option><option value="no-preference">No preference</option></select></Field>
            <RenderNumberField label="Navigation timeout (seconds)" field="render_navigation_timeout_seconds" scope={scope} capabilities={renderCapabilities.data} onChange={setScope} />
            <RenderNumberField label="Load timeout (seconds)" field="render_load_timeout_seconds" scope={scope} capabilities={renderCapabilities.data} onChange={setScope} />
            <RenderNumberField label="Page duration limit (seconds)" field="render_max_page_duration_seconds" scope={scope} capabilities={renderCapabilities.data} onChange={setScope} />
            <RenderNumberField label="Full-page height limit" field="render_max_full_page_height" scope={scope} capabilities={renderCapabilities.data} onChange={setScope} />
            <RenderNumberField label="DOM byte limit" field="render_max_dom_bytes" scope={scope} capabilities={renderCapabilities.data} onChange={setScope} />
            <RenderNumberField label="Screenshot byte limit" field="render_max_screenshot_bytes" scope={scope} capabilities={renderCapabilities.data} onChange={setScope} />
            <RenderNumberField label="Network entry limit" field="render_max_network_entries" scope={scope} capabilities={renderCapabilities.data} onChange={setScope} />
            <RenderNumberField label="Console entry limit" field="render_max_console_entries" scope={scope} capabilities={renderCapabilities.data} onChange={setScope} />
            <RenderNumberField label="Page error limit" field="render_max_page_errors" scope={scope} capabilities={renderCapabilities.data} onChange={setScope} />
            <RenderNumberField label="Total network byte limit" field="render_max_total_network_bytes" scope={scope} capabilities={renderCapabilities.data} onChange={setScope} />
            <RenderNumberField label="Resource byte limit" field="render_max_resource_bytes" scope={scope} capabilities={renderCapabilities.data} onChange={setScope} />
          </div></details> : null}
          {renderCapabilities.error ? <div className="mt-3 text-sm text-red-700">Rendering limits could not be loaded. Static-only scans remain available.</div> : null}
          {validation.renderLimits ? <div className="mt-3 text-sm text-red-700">{validation.renderLimits}</div> : null}
        </section>

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
              <Field id="static-max-attempts" label="Maximum static attempts" error={validation.staticMaxAttempts} helper="Total requests allowed per page, including the first attempt.">
                <input id="static-max-attempts" type="number" min={1} max={5} value={numberInputValue(scope.static_max_attempts)} onChange={(event) => updateNumber("static_max_attempts", event.target.value)} className={inputClass(Boolean(validation.staticMaxAttempts))} />
              </Field>
              <Field id="static-retry-initial-delay" label="Initial retry delay" error={validation.staticRetryInitialDelay} helper="Milliseconds before the first eligible retry.">
                <input id="static-retry-initial-delay" type="number" min={0} max={60000} value={numberInputValue(scope.static_retry_initial_delay_ms)} onChange={(event) => updateNumber("static_retry_initial_delay_ms", event.target.value)} className={inputClass(Boolean(validation.staticRetryInitialDelay))} />
              </Field>
              <Field id="static-retry-max-delay" label="Maximum retry delay" error={validation.staticRetryMaxDelay} helper="Caps backoff, jitter, and Retry-After delays in milliseconds.">
                <input id="static-retry-max-delay" type="number" min={0} max={60000} value={numberInputValue(scope.static_retry_max_delay_ms)} onChange={(event) => updateNumber("static_retry_max_delay_ms", event.target.value)} className={inputClass(Boolean(validation.staticRetryMaxDelay))} />
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

type RenderNumberKey = keyof Pick<ScopeConfig, "render_viewport_width" | "render_viewport_height" | "render_device_scale_factor" | "render_navigation_timeout_seconds" | "render_load_timeout_seconds" | "render_max_page_duration_seconds" | "render_max_full_page_height" | "render_max_dom_bytes" | "render_max_screenshot_bytes" | "render_max_network_entries" | "render_max_console_entries" | "render_max_page_errors" | "render_max_total_network_bytes" | "render_max_resource_bytes">;

function RenderNumberField({ label, field, scope, capabilities, onChange }: { label: string; field: RenderNumberKey; scope: ScopeConfig; capabilities?: RenderCapabilities; onChange: (scope: ScopeConfig) => void }) {
  const limits = capabilities?.limits[field];
  const id = field.replace(/_/g, "-");
  return <Field id={id} label={label}><input id={id} type="number" min={limits?.minimum} max={limits?.maximum} step={field === "render_device_scale_factor" ? 0.1 : 1} value={numberInputValue(scope[field])} onChange={(event) => onChange({ ...scope, [field]: Number(event.target.value) })} className={inputClass()} /></Field>;
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

function validateForm(_startingUrl: string, urlValidation: ReturnType<typeof normalizeStartingUrlInput>, scope: ScopeConfig, capabilities?: RenderCapabilities) {
  const renderLimits = scope.render_mode === "none" || !capabilities ? null : Object.entries(capabilities.limits).some(([field, limits]) => {
    const value = scope[field as RenderNumberKey];
    return typeof value === "number" && (!Number.isFinite(value) || value < limits.minimum || value > limits.maximum);
  }) || !scope.render_locale.trim() || !scope.render_timezone.trim() ? "One or more browser settings are outside the server-supported limits." : null;
  const validation = {
    startingUrl: urlValidation.error,
    maxPages: validateInteger(scope.max_pages, 1, 10000, "Maximum pages must be between 1 and 10,000."),
    maxDepth: validateInteger(scope.max_depth, 0, 50, "Maximum depth must be between 0 and 50."),
    requestTimeout: validateNumber(scope.request_timeout_seconds, 1, 300, "Request timeout must be between 1 and 300 seconds."),
    staticMaxAttempts: validateInteger(scope.static_max_attempts, 1, 5, "Maximum static attempts must be between 1 and 5."),
    staticRetryInitialDelay: validateInteger(scope.static_retry_initial_delay_ms, 0, 60000, "Initial retry delay must be between 0 and 60,000 milliseconds."),
    staticRetryMaxDelay: scope.static_retry_initial_delay_ms > scope.static_retry_max_delay_ms ? "Maximum retry delay must be at least the initial delay." : validateInteger(scope.static_retry_max_delay_ms, 0, 60000, "Maximum retry delay must be between 0 and 60,000 milliseconds."),
    maxHtmlBytes: validateInteger(scope.max_html_response_bytes, 1, 100000000, "Maximum HTML response size must be at least 1 byte."),
    requestDelay: validateInteger(scope.delay_between_requests_ms, 0, 60000, "Delay must be between 0 and 60,000 milliseconds."),
    maxRedirects: validateInteger(scope.max_redirects, 0, 50, "Maximum redirects must be between 0 and 50."),
    renderMaxPages: scope.render_mode === "none" ? null : validateInteger(scope.render_max_pages, 1, Math.min(1000, scope.max_pages), "Rendered pages must be between 1 and the scan page limit."),
    renderLimits
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
    return hydrateScope(JSON.parse(raw) as Partial<ScopeConfig>);
  } catch {
    return defaultScope();
  }
}

function hydrateScope(scope: Partial<ScopeConfig>): ScopeConfig {
  return { ...defaultScope(), ...scope };
}
