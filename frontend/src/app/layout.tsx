"use client";

/**
 * 根布局（客户端组件）：
 * - ConfigProvider(中文语言包) → AntD App → QueryClientProvider → AuthProvider
 * - 全站风险提示条（可关闭，刷新后复现）
 *
 * 注意：所有页面数据获取均为客户端 TanStack Query，构建期不做任何 fetch，
 * 因此 `pnpm build` 在没有后端的环境下同样可以通过。
 */

import { useEffect, useState, type ReactNode } from "react";
import { App as AntApp, ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "@/contexts/AuthContext";
import { RiskBanner } from "@/components/RiskBanner";
import "./globals.css";

export default function RootLayout({ children }: { children: ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            refetchOnWindowFocus: false,
            retry: 1,
            staleTime: 15_000,
          },
        },
      }),
  );

  useEffect(() => {
    if (!document.title) {
      document.title = "QlibQuantLab 量化研究平台";
    }
  }, []);

  return (
    <html lang="zh-CN">
      <body>
        <ConfigProvider
          locale={zhCN}
          theme={{ token: { colorPrimary: "#1677ff", borderRadius: 6 } }}
        >
          <AntApp>
            <QueryClientProvider client={queryClient}>
              <AuthProvider>
                <RiskBanner />
                {children}
              </AuthProvider>
            </QueryClientProvider>
          </AntApp>
        </ConfigProvider>
      </body>
    </html>
  );
}
