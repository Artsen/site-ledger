export const scanInputLimits = {
  maxPages: { minimum: 1, maximum: 50_000 },
  maxDepth: { minimum: 0, maximum: 100 },
  requestTimeoutSeconds: { minimum: 0.1, maximum: 120 },
  maxHtmlResponseBytes: { minimum: 1, maximum: 20_000_000 },
  delayBetweenRequestsMs: { minimum: 0, maximum: 60_000 },
  maxRedirects: { minimum: 0, maximum: 20 },
  userAgentMaxLength: 512,
  startingUrlMaxLength: 2_048,
  renderLocaleMaxLength: 64,
  renderTimezoneMaxLength: 255
} as const;
