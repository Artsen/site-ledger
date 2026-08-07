const terminalStatuses = new Set(["completed", "completed_with_errors", "failed", "cancelled", "interrupted"]);

export function isTerminalStatus(status: string) {
  return terminalStatuses.has(status);
}

export function formatStatus(status: string | null | undefined) {
  if (!status) return "Unknown";
  return status
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export function statusTone(status: string | null | undefined): "neutral" | "success" | "warning" | "danger" | "info" {
  if (!status) return "neutral";
  if (status === "completed") return "success";
  if (status === "completed_with_errors" || status === "interrupted") return "warning";
  if (status === "failed" || status === "cancelled") return "danger";
  if (status === "running" || status === "queued") return "info";
  return "neutral";
}

export type DateFormatOptions = {
  timeZone?: string | null;
  showTimeZone?: boolean;
  locale?: string;
};

function parseInstant(value: string) {
  const unambiguous = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?$/.test(value)
    ? `${value}Z`
    : value;
  return new Date(unambiguous);
}

export function formatDate(value: string | null | undefined, options: DateFormatOptions = {}) {
  if (!value) return "Not available";
  const date = parseInstant(value);
  if (Number.isNaN(date.getTime())) return "Not available";
  return new Intl.DateTimeFormat(options.locale, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    ...(options.timeZone ? { timeZone: options.timeZone } : {}),
    ...(options.showTimeZone ? { timeZoneName: "short" as const } : {})
  }).format(date);
}

export function formatDateTime(value: string | null | undefined, options: DateFormatOptions = {}) {
  return formatDate(value, options);
}

export function formatFullDate(value: string | null | undefined, options: DateFormatOptions = {}) {
  if (!value) return "Not available";
  const date = parseInstant(value);
  if (Number.isNaN(date.getTime())) return "Not available";
  return new Intl.DateTimeFormat(options.locale, {
    year: "numeric", month: "long", day: "numeric", hour: "numeric", minute: "2-digit",
    ...(options.timeZone ? { timeZone: options.timeZone } : {}),
    ...(options.showTimeZone ? { timeZoneName: "short" as const } : {})
  }).format(date);
}

export function formatRelativeDate(value: string | null | undefined) {
  if (!value) return "No date";
  const date = parseInstant(value);
  if (Number.isNaN(date.getTime())) return "No date";
  const seconds = Math.round((date.getTime() - Date.now()) / 1000);
  const abs = Math.abs(seconds);
  const divisions: Array<[Intl.RelativeTimeFormatUnit, number]> = [
    ["year", 31536000],
    ["month", 2592000],
    ["week", 604800],
    ["day", 86400],
    ["hour", 3600],
    ["minute", 60]
  ];
  for (const [unit, amount] of divisions) {
    if (abs >= amount) return new Intl.RelativeTimeFormat(undefined, { numeric: "auto" }).format(Math.round(seconds / amount), unit);
  }
  return "Just now";
}

export function formatDuration(start: string | null | undefined, end: string | null | undefined = new Date().toISOString()) {
  if (!start) return "Not started";
  const startDate = new Date(start);
  const endDate = end ? new Date(end) : new Date();
  if (Number.isNaN(startDate.getTime()) || Number.isNaN(endDate.getTime())) return "Not available";
  const totalSeconds = Math.max(0, Math.round((endDate.getTime() - startDate.getTime()) / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes >= 60) {
    const hours = Math.floor(minutes / 60);
    return `${hours}h ${minutes % 60}m`;
  }
  if (minutes > 0) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}

export function formatBytes(value: number | null | undefined) {
  if (value == null) return "Not available";
  const units = ["B", "KB", "MB", "GB"];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

export function hostnameFromUrl(value: string | null | undefined) {
  if (!value) return "Unknown host";
  try {
    return new URL(value).hostname;
  } catch {
    return value;
  }
}

export function compactUrl(value: string | null | undefined) {
  if (!value) return "";
  try {
    const url = new URL(value);
    return `${url.hostname}${url.pathname}${url.search}`;
  } catch {
    return value;
  }
}

export function formatScopeDecision(value: string | null | undefined) {
  return formatStatus(value ?? "unknown");
}

export function plural(count: number, singular: string, pluralName = `${singular}s`) {
  return `${count} ${count === 1 ? singular : pluralName}`;
}
