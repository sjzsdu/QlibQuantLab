import { expect, test } from "@playwright/test";
import { openFirstRowButton } from "./helpers";

/**
 * 旅程 ⑦ 回测分析：回测列表 → 详情（四标注 + 费用透传 + 导出/打印入口）。
 * 首行的策略名称 link 按钮进详情；admin 拥有 backtest.export，导出按钮可见。
 * 登录态由 setup 项目共享。
 */

test("回测详情含四标注与导出/打印入口", async ({ page }) => {
  await page.goto("/backtests");
  await expect(page.getByRole("table")).toBeVisible();
  await openFirstRowButton(page, /\/backtests\/[0-9a-f-]{36}/);
  await expect(page.getByText("四标注：结果说明")).toBeVisible();
  await expect(page.getByText("① 数据区间")).toBeVisible();
  await expect(page.getByText("③ 费用假设（100% 透传）")).toBeVisible();
  await expect(page.getByRole("button", { name: /导出报告 CSV/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /打印版/ })).toBeVisible();
});
