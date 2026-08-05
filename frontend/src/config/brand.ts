export const productName = "Site Ledger";
export const productTagline = "A historical record of your website.";
export const productDescription =
  "Site Ledger is a local-first website intelligence platform that inventories sites, preserves crawl evidence, and tracks page observations over time.";
export const repositoryUrl = "https://github.com/Artsen/site-ledger";
export const repositorySlug = "site-ledger";

export function formatDocumentTitle(title?: string | null) {
  const normalized = title?.trim();
  return normalized ? `${normalized} | ${productName}` : productName;
}
