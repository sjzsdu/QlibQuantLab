import { expect, test } from "@playwright/test";
import { login } from "./helpers";

/**
 * 共享登录态（阶段 6 切片⑧）：**只登录一次**并保存 storageState，其余 spec 复用
 * cookie。动机是后端登录限流（RATE_LIMIT_LOGIN_PER_MIN=5，按 IP 固定窗口）——
 * 逐测登录（每次 /auth/login + /auth/mock/enter 共 2 次命中）必然打满 429。
 * 01-auth 登录门旅程保留独立登录（它本身就是被测路径，跑在独立的限流窗口）。
 */
test("准备共享登录态", async ({ context, page }) => {
  await login(page);
  await expect(page.getByRole("menuitem", { name: "项目管理" })).toBeVisible();
  await context.storageState({ path: "e2e/.auth/state.json" });
});
