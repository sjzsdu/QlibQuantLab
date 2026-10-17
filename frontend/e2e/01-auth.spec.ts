import { expect, test } from "@playwright/test";
import { expectMenuItems, login } from "./helpers";

/**
 * 旅程 ① 登录与全站导航：未登录重定向 / 一键进入 / 侧边栏全量入口。
 */

test("未登录访问受保护页会重定向到登录页", async ({ page }) => {
  await page.goto("/projects");
  await page.waitForURL(/\/login/, { timeout: 20_000 });
  await expect(page.getByRole("button", { name: "一键进入平台" })).toBeVisible();
});

test("一键进入后首页与全站导航可见", async ({ page }) => {
  await login(page);
  await expectMenuItems(page, [
    "项目管理",
    "数据管理",
    "因子库",
    "模型训练",
    "策略管理",
    "回测分析",
    "任务中心",
    "审计日志",
    "全部文件",
  ]);
});
