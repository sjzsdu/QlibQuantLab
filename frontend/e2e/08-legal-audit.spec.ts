import { expect, test } from "@playwright/test";

/**
 * 旅程 ⑧ 合规与审计：/legal 索引（meta 驱动）→ 文档详情 → 404 兜底；
 * 审计日志列表 + 导出入口（admin 有 audit.export）。
 * 登录态由 setup 项目共享。
 */

test("合规索引 → 文档详情 → 未知文档 404", async ({ page }) => {
  await page.goto("/legal");
  // meta 驱动的三张文档卡（用户协议/风险提示/免责声明）
  await expect(page.locator(".ant-card").filter({ hasText: "用户协议" }).first()).toBeVisible();
  await expect(page.locator(".ant-card").filter({ hasText: "免责声明" }).first()).toBeVisible();
  // 点第一张卡的「查看全文」进详情
  await page.getByRole("button", { name: "查看全文" }).first().click();
  await page.waitForURL(/\/legal\/.+/, { timeout: 40_000 });
  await expect(page.getByRole("button", { name: /打印/ })).toBeVisible();

  await page.goto("/legal/unknown-doc");
  await expect(page.getByText("文档不存在")).toBeVisible();
  await expect(page.getByText("当前可用文档")).toBeVisible();
});

test("审计日志列表与导出入口", async ({ page }) => {
  await page.goto("/audit");
  await expect(page.getByRole("table").first()).toBeVisible();
  await expect(page.getByRole("button", { name: /导出 CSV/ })).toBeVisible();
});
