import { expect, test } from "@playwright/test";

/**
 * 旅程 ⑥ 策略管理：列表加载 → 新建弹窗字段（项目/名称/信号源）。
 * 登录态由 setup 项目共享。
 */

test("策略列表与新建弹窗字段完整", async ({ page }) => {
  await page.goto("/strategies");
  await expect(page.getByRole("table")).toBeVisible();
  await page.getByRole("button", { name: /新建策略/ }).click();
  const modal = page.locator(".ant-modal-content");
  await expect(modal).toBeVisible();
  await expect(modal.getByText("名称")).toBeVisible();
  await expect(modal.getByText("信号源")).toBeVisible();
});
