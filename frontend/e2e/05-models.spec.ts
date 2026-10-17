import { expect, test } from "@playwright/test";
import { openByName } from "./helpers";

/**
 * 旅程 ⑤ 模型训练：模型列表 → 详情 → 训练弹窗（含阶段 6 复用开关）。
 * 只打开弹窗验表单结构，不真正提交训练（避免冒烟依赖 worker 队列时序）。
 * 登录态由 setup 项目共享。
 */

test("模型训练弹窗含切分/股票池/复用开关", async ({ page }) => {
  await page.goto("/models");
  await expect(page.getByRole("table")).toBeVisible();
  await openByName(page, "s6-reuse-lgb", /\/models\/[0-9a-f-]{36}/);
  await page.getByRole("button", { name: /训练中|提交训练/ }).first().click();
  await expect(page.getByText("复用已计算的因子值（与 IC 预览同源）")).toBeVisible();
  await expect(page.getByText("自定义训练/验证切分")).toBeVisible();
  await expect(page.getByText("股票池")).toBeVisible();
});
