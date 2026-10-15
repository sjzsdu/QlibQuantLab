"use client";

/**
 * 前端唯一认证入口（Provider）。
 *
 * 业务组件禁止直接读 cookie / 调第三方 SDK，只能通过 useCurrentUser() 拿用户。
 * 数据来源：GET /api/v1/me 与 GET /api/v1/me/permissions（TanStack Query 客户端拉取）。
 */

import {
  createContext,
  useCallback,
  useMemo,
  type ReactNode,
} from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch, ApiError } from "@/lib/api";
import type {
  CurrentUser,
  LoginResponse,
  LogoutResponse,
  PermissionsResponse,
  Role,
} from "@/lib/types";

export interface AuthContextValue {
  /** 当前用户；未登录 / 会话失效为 null */
  user: CurrentUser | null;
  /** 正在拉取会话 */
  isLoading: boolean;
  /** 当前用户在当前组织的权限点（如 project.read） */
  permissions: string[];
  /** 角色判断：can("admin", "researcher")，任一命中即 true */
  can: (...roles: string[]) => boolean;
  /** 权限点判断：hasPermission("project.read") */
  hasPermission: (permission: string) => boolean;
  /** 登录：GET /api/v1/auth/login → 拿 url 后整页跳转 */
  login: (next?: string) => Promise<void>;
  /** 登出：GET /api/v1/auth/logout（后端清 cookie）→ 跳转登录页 */
  logout: () => Promise<void>;
  /** 刷新会话与权限缓存 */
  refresh: () => Promise<void>;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

const ME_KEY = ["auth", "me"] as const;
const PERMISSIONS_KEY = ["auth", "permissions"] as const;

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();

  const meQuery = useQuery<CurrentUser | null>({
    queryKey: ME_KEY,
    queryFn: async () => {
      try {
        return await apiFetch<CurrentUser>("/v1/me");
      } catch (error) {
        // 401 = 未登录，不视为错误；其余错误上抛（由调用方按未登录兜底）
        if (error instanceof ApiError && error.isUnauthenticated) {
          return null;
        }
        throw error;
      }
    },
    retry: (failureCount, error) => {
      // 4xx 不重试；网络类错误最多重试 2 次
      if (error instanceof ApiError && error.status >= 400) return false;
      return failureCount < 2;
    },
    staleTime: 30_000,
    refetchOnWindowFocus: true,
  });

  const permissionsQuery = useQuery<string[]>({
    queryKey: PERMISSIONS_KEY,
    queryFn: async () => {
      const data = await apiFetch<PermissionsResponse>("/v1/me/permissions");
      return data?.permissions ?? [];
    },
    enabled: Boolean(meQuery.data),
    retry: false,
    staleTime: 60_000,
  });

  const user = meQuery.data ?? null;
  const isLoading = meQuery.isPending;

  const can = useCallback(
    (...roles: string[]) => {
      if (!user) return false;
      if (roles.length === 0) return true;
      const userRoles = user.roles ?? [];
      return roles.some((role) => userRoles.includes(role as Role));
    },
    [user],
  );

  const hasPermission = useCallback(
    (permission: string) =>
      (permissionsQuery.data ?? []).includes(permission),
    [permissionsQuery.data],
  );

  const login = useCallback(async (next?: string) => {
    const suffix =
      next && next !== "/" ? `?redirect_to=${encodeURIComponent(next)}` : "";
    const data = await apiFetch<LoginResponse>(`/v1/auth/login${suffix}`);
    if (!data?.url) {
      throw new ApiError("登录接口未返回跳转地址", -1, 0);
    }
    window.location.href = data.url;
  }, []);

  const logout = useCallback(async () => {
    try {
      const data = await apiFetch<LogoutResponse | null>("/v1/auth/logout");
      const target = data?.url ?? data?.redirect_to ?? "/login";
      window.location.href = target;
    } catch {
      // 即便登出接口异常，也至少回到登录页，避免用户停在假登录状态
      window.location.href = "/login";
    }
  }, []);

  const refresh = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: ["auth"] });
  }, [queryClient]);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      isLoading,
      permissions: permissionsQuery.data ?? [],
      can,
      hasPermission,
      login,
      logout,
      refresh,
    }),
    [
      user,
      isLoading,
      permissionsQuery.data,
      can,
      hasPermission,
      login,
      logout,
      refresh,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
