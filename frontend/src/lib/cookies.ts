/**
 * Cookie 读取工具。
 *
 * 只允许读取非 HttpOnly 的 CSRF cookie（双提交 cookie）。
 * 会话 cookie `qqlab_session` 为 HttpOnly，浏览器脚本读不到，也不需要处理。
 */

export const CSRF_COOKIE_NAME = "qqlab_csrf";
export const SESSION_COOKIE_NAME = "qqlab_session";

/** 读取普通（非 HttpOnly）cookie，SSR 环境返回 null */
export function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const prefix = `${name}=`;
  const parts = document.cookie ? document.cookie.split("; ") : [];
  for (const part of parts) {
    if (part.startsWith(prefix)) {
      try {
        return decodeURIComponent(part.slice(prefix.length));
      } catch {
        return part.slice(prefix.length);
      }
    }
  }
  return null;
}

/** 取 CSRF 双提交 token（非 GET/HEAD/OPTIONS 请求必须携带 X-CSRF-Token） */
export function getCsrfToken(): string | null {
  return readCookie(CSRF_COOKIE_NAME);
}
