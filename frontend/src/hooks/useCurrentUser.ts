"use client";

/**
 * 业务组件获取当前用户的唯一 hook。
 * 使用方式：const { user, isLoading, can, logout } = useCurrentUser();
 */

import { useContext } from "react";
import { AuthContext, type AuthContextValue } from "@/contexts/AuthContext";

export function useCurrentUser(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useCurrentUser 必须在 <AuthProvider> 内部使用");
  }
  return context;
}
