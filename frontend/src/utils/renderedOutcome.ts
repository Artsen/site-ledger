import type { RenderedObservationIndexItem } from "../types/scans";

export function renderOutcomeLabel(item: Pick<RenderedObservationIndexItem, "capture_state" | "navigation_http_status" | "error_type">) {
  if (item.error_type === "host_rate_limit_circuit_open") return "Not attempted - host throttled";
  if (item.navigation_http_status === 429 || item.error_type === "navigation_rate_limited") return "Rate limited";
  if (item.navigation_http_status === 204 || item.navigation_http_status === 205 || item.error_type === "navigation_no_content") return "No Page content";
  if (item.error_type === "navigation_http_redirect") return "HTTP redirect";
  if (item.navigation_http_status != null && item.navigation_http_status >= 500) return "Server error";
  if (item.navigation_http_status != null && item.navigation_http_status >= 400) return "HTTP error";
  return item.capture_state.replace(/_/g, " ");
}
