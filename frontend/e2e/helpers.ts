import { expect, type Page } from "@playwright/test";

/**
 * e2e 冒烟共用步骤（阶段 6 切片⑧）。
 * 登录只走公开的 mock 进入口（/login「一键进入平台」），与真实用户路径一致。
 *
 * 两个实测坑（dev 环境）：
 * 1. 一键进入的导航链是 `/login` → `GET /api/v1/auth/mock/enter`（302）→ `/`，
 *    中途 URL 已不是 /login —— 只排除 /login 会在**cookie 落地前**误判登录完成，
 *    后续 goto 会取消在途导航导致会话丢失（RequireAuth 弹回 /login?next=…）。
 *    因此必须等到**落在应用页**（非 /api、非 /login）为止。
 * 2. dev 服务器按需编译 + React 水合完成前，点击可能落在未挂监听的元素上丢失，
 *    所有「点按钮进详情」都带一次重试。
 */

/** Mock auth：/login 一键进入（默认 admin profile），落进应用页才算成功。 */
export async function login(page: Page): Promise<void> {
  await page.goto("/login");
  const button = page.getByRole("button", { name: "一键进入平台" });
  const already = page.getByText("当前已登录");
  // 二者之一出现才算登录页水合完成；已持会话时直接放行
  await Promise.race([
    button.waitFor({ state: "visible", timeout: 15_000 }),
    already.waitFor({ state: "visible", timeout: 15_000 }),
  ]).catch(() => undefined);
  if (await already.isVisible().catch(() => false)) return;
  await button.click();
  await page.waitForURL(
    (url) => !url.pathname.startsWith("/login") && !url.pathname.startsWith("/api"),
    { timeout: 20_000 },
  );
  // 落点页会拉 /v1/me —— 等它成功，确保会话真正生效后再导航
  await page
    .waitForResponse((r) => r.url().includes("/v1/me") && r.ok(), { timeout: 10_000 })
    .catch(() => undefined);
}

/** AppShell 侧边栏菜单项可见（布局渲染完成的最低证据）。 */
export async function expectMenuItems(page: Page, labels: string[]): Promise<void> {
  for (const label of labels) {
    await expect(page.getByRole("menuitem", { name: label })).toBeVisible();
  }
}

/** 点击首行的第一个按钮（名称列 link 按钮）并等待跳转。
 *  dev 下新路由首次导航可能触发按需编译（改共享模块后整图失效）——超时放宽到 40s，
 *  仍失败则由测试级 retries=1 兜底（第二次通常已热）。 */
export async function openFirstRowButton(page: Page, urlPattern: RegExp): Promise<void> {
  await page.getByRole("row").nth(1).getByRole("button").first().click();
  await page.waitForURL(urlPattern, { timeout: 40_000 });
}

/** 按资源名点击名称列 link 按钮并等待跳转（同上，40s 宽限）。 */
export async function openByName(page: Page, name: string, urlPattern: RegExp): Promise<void> {
  await page.getByRole("button", { name }).first().click();
  await page.waitForURL(urlPattern, { timeout: 40_000 });
}
