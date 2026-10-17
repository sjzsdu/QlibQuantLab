import { expect, test } from "@playwright/test";

/**
 * 旅程 ③ 数据管理：数据集 tab → 数据集详情（数据源 / 授权依据 / 数据区间标注）。
 * 登录态由 setup 项目共享（storageState），不再逐测登录（登录限流 5 次/分钟）。
 * /data 默认 tab 是「数据源」—— 必须先切到「数据集」再点行（AntD 切换过的
 * tab pane 会保留在 DOM 里，选择器要限定在 active pane 内）。
 */

test("数据集列表 → 详情含来源授权与数据区间", async ({ page }) => {
  await page.goto("/data");
  await page.getByRole("tab", { name: "数据集" }).click();
  const pane = page.locator(".ant-tabs-tabpane-active");
  const firstRow = pane.getByRole("table").getByRole("row").nth(1);
  await expect(firstRow).toBeVisible();
  // 名称列是 link 按钮（数据集行内唯一的按钮）
  await firstRow.getByRole("button").first().click();
  await page.waitForURL(/\/data\/datasets\/[0-9a-f-]{36}/, { timeout: 20_000 });
  await expect(page.getByText("数据源")).toBeVisible();
  await expect(page.getByText("授权依据")).toBeVisible();
  await expect(page.getByText("数据区间")).toBeVisible();
});
