export type UrlValidation = {
  input: string;
  normalizedUrl: string;
  hostname: string;
  error: string | null;
};

export function normalizeStartingUrlInput(input: string): UrlValidation {
  const trimmed = input.trim();
  if (!trimmed) {
    return { input, normalizedUrl: "", hostname: "", error: "Enter a starting URL." };
  }

  const candidate = /^[a-z][a-z0-9+.-]*:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;

  try {
    const url = new URL(candidate);
    if (url.protocol !== "http:" && url.protocol !== "https:") {
      return { input, normalizedUrl: candidate, hostname: "", error: "Only HTTP and HTTPS URLs can be scanned." };
    }
    if (!url.hostname) {
      return { input, normalizedUrl: candidate, hostname: "", error: "Enter a URL with a hostname." };
    }
    return { input, normalizedUrl: url.toString(), hostname: url.hostname, error: null };
  } catch {
    return { input, normalizedUrl: candidate, hostname: "", error: "The starting URL is not valid. Enter a complete HTTP or HTTPS address." };
  }
}

export function parseLineList(value: string) {
  return value
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean);
}
