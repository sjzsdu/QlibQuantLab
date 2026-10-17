import { defineConfig } from "@playwright/test";

/**
 * Playwright e2e 冒烟（阶段 6 切片⑧）。
 *
 * - `channel: "chrome"` 使用系统 Chrome（不下载浏览器内核，离线可跑）；
 * - 不配置 webServer —— 冒烟对象是**已在运行的部署栈**（frontend :3000 +
 *   backend :8000），登录走 /login 的 mock「一键进入」，不注入任何测试后门；
 * - **projects 三段式（登录限流 5 次/分钟/IP 的约束）**：
 *   1. setup —— 只登录一次并保存 storageState；
 *   2. app   —— 复用共享 cookie 跑其余旅程（不再逐测登录）；
 *   3. auth  —— 01-auth 登录门旅程，用全新 context 独立登录（被测路径本身）；
 *   依赖顺序把 auth 的 2 次登录推到与 setup 不同的限流窗口内。
 * - 数据依赖开发栈种子数据（smoke 项目 / dev 数据集 / 示例因子与模型），
 *   断言以「结构性存在」为主（卡片 / 按钮 / 标注），避免对具体指标值的脆弱断言；
 * - 跑法：`pnpm e2e`（栈未起时会失败——这本身也是部署可用性信号）。
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  expect: { timeout: 10_000 },
  fullyParallel: true,
  workers: 2,
  // dev 服务器按需编译是唯一 flaky 源（改共享模块后路由首访需重编译），
  // 冒烟是「结构性存在」断言 —— 一次重试兜底工具链时序，不掩盖真实失败
  retries: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    channel: "chrome",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "setup", testMatch: /setup\.spec\.ts/ },
    {
      name: "app",
      dependencies: ["setup"],
      use: { storageState: "e2e/.auth/state.json" },
      testIgnore: /(01-auth|setup)\.spec\.ts/,
    },
    { name: "auth", testMatch: /01-auth\.spec\.ts/, dependencies: ["app"] },
  ],
});
