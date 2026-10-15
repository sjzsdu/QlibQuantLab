import type { NextConfig } from "next";

/**
 * 后端地址只允许出现在这里（服务端 rewrite 转发，浏览器永远看不到该地址）。
 * 前端业务代码一律使用相对路径 `/api/v1/...`。
 */
const backendInternalUrl =
  process.env.BACKEND_INTERNAL_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  output: "standalone",
  typescript: {
    // 构建期保留类型检查（pnpm build 会跑 tsc）
    ignoreBuildErrors: false,
  },
  eslint: {
    // lint 由 `pnpm lint` 单独执行，避免构建被 lint 规则阻塞
    ignoreDuringBuilds: true,
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backendInternalUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
