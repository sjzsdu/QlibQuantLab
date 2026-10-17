import { expect, test } from "@playwright/test";

/**
 * 旅程 ② 项目管理：列表加载（列结构 + 种子项目可见）→ 新建弹窗字段。
 * 注：项目详情页（/projects/{id}）暂无列表内导航入口（直链访问），
 * 冒烟只覆盖列表与新建路径。登录态由 setup 项目共享。
 */

test("项目列表结构与新建弹窗", async ({ page }) => {
  await page.goto("/projects");
  await expect(page.getByRole("table").first()).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "项目名称" })).toBeVisible();
  await expect(page.getByText("smoke").first()).toBeVisible();

  await page.getByRole("button", { name: /新建项目/ }).first().click();
  const modal = page.locator(".ant-modal-content");
  await expect(modal.getByText("名称")).toBeVisible();
});
