"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Spin } from "antd";
import { useCurrentUser } from "@/hooks/useCurrentUser";

interface RequireAuthProps {
  children: React.ReactNode;
}

/**
 * 未登录（或会话失效）时跳转 /login，并带上 return-to 参数。
 * 加载中显示全屏 Spin。
 */
export function RequireAuth({ children }: RequireAuthProps) {
  const { user, isLoading } = useCurrentUser();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (!isLoading && !user) {
      const next = encodeURIComponent(pathname || "/");
      router.replace(`/login?next=${next}`);
    }
  }, [isLoading, user, pathname, router]);

  if (isLoading) {
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          minHeight: "40vh",
        }}
      >
        <Spin size="large" tip="正在加载会话…" />
      </div>
    );
  }

  if (!user) return null;

  return <>{children}</>;
}
