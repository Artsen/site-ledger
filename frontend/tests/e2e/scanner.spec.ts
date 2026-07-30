import { expect, test } from "@playwright/test";

test("new scan screen is available", async ({ page }) => {
  await page.route("**/api/scans", async (route) => {
    await route.fulfill({ json: [] });
  });
  await page.goto("/scans/new");
  await expect(page.getByRole("heading", { name: "New scan" })).toBeVisible();
  await expect(page.getByLabel("Starting URL")).toBeVisible();
});
