import { expect, test } from "@playwright/test";

test("overview renders key cockpit sections", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Operator Cockpit")).toBeVisible({ timeout: 15000 });
  await expect(page.getByText("Executive Overview")).toBeVisible({ timeout: 15000 });
  await expect(page.getByText("Best Leads Right Now")).toBeVisible({ timeout: 15000 });
  await expect(page.getByText("Coverage Gaps")).toBeVisible({ timeout: 15000 });
});
