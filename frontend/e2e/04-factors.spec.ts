import { expect, test } from "@playwright/test";
import { openByName } from "./helpers";

/**
 * 旅程 ④ 因子库：因子列表 → 因子详情（表达式快照 + 「计算 IC」入口）。
 * 依赖开发栈已建因子 s6-ma20-ic（stage6_smoke 产物；缺数据时此冒烟失败即为信号）。
 * 登录态由 setup 项目共享。
 */

test("因子详情展示表达式与计算 IC 入口", async ({ page }) => {
  await page.goto("/factors");
  await expect(page.getByRole("table")).toBeVisible();
  await openByName(page, "s6-ma20-ic", /\/factors\/[0-9a-f-]{36}/);
  await expect(page.getByRole("button", { name: "计算 IC" })).toBeVisible();
  await expect(page.getByText("$close").first()).toBeVisible();
});
