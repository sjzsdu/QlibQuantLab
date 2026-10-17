/**
 * 全站唯一的 HTTP 客户端。
 *
 * 硬性约束：
 * 1. 所有请求一律使用相对路径（baseURL = "/api"），禁止出现任何主机名；
 * 2. 携带 cookie（credentials: "include"），由 Next.js rewrites 转发到后端；
 * 3. 非安全方法（非 GET/HEAD/OPTIONS）自动附加 CSRF 双提交 token（X-CSRF-Token ← cookie qqlab_csrf）；
 * 4. 收到 401 统一跳转 /login（登录页自身除外，避免重定向死循环）；
 * 5. 统一解开后端响应信封 { code, message, data, request_id }。
 */

import { getCsrfToken } from "@/lib/cookies";
import type { Envelope } from "@/lib/types";

/** 相对路径前缀，服务端 rewrite 会把它转发到后端 */
const BASE_URL = "/api";

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

export type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

/** 业务/网络错误，携带后端业务码与 HTTP 状态码 */
export class ApiError extends Error {
  readonly code: number;
  readonly status: number;
  readonly requestId?: string;

  constructor(message: string, code = -1, status = 0, requestId?: string) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.requestId = requestId;
  }

  /** 会话失效 */
  get isUnauthenticated(): boolean {
    return this.status === 401;
  }
}

function inBrowser(): boolean {
  return typeof window !== "undefined";
}

/** 401 统一跳转登录页（登录页自身不跳，防止死循环） */
function redirectToLogin(): void {
  if (!inBrowser()) return;
  const { pathname, search } = window.location;
  if (pathname === "/login" || pathname.startsWith("/login/")) return;
  const next = encodeURIComponent(`${pathname}${search}`);
  window.location.replace(`/login?next=${next}`);
}

function isJsonResponse(res: Response): boolean {
  const contentType = res.headers.get("content-type") ?? "";
  return contentType.includes("application/json");
}

/**
 * 发起请求并返回完整响应信封。
 * 失败时抛出 ApiError。
 */
export async function apiRequest<T>(
  path: string,
  init: RequestInit & { method?: HttpMethod } = {},
): Promise<Envelope<T>> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");

  if (!SAFE_METHODS.has(method)) {
    const token = getCsrfToken();
    if (token) {
      headers.set("X-CSRF-Token", token);
    }
    if (
      init.body &&
      !(init.body instanceof FormData) &&
      !headers.has("Content-Type")
    ) {
      headers.set("Content-Type", "application/json");
    }
  }

  let res: Response;
  try {
    res = await fetch(`${BASE_URL}${path}`, {
      ...init,
      method,
      headers,
      credentials: "include",
      cache: "no-store",
    });
  } catch {
    throw new ApiError("网络异常：无法连接后端服务，请稍后重试", -1, 0);
  }

  if (res.status === 401) {
    redirectToLogin();
  }

  if (!isJsonResponse(res)) {
    throw new ApiError(
      `请求失败（HTTP ${res.status}）：后端未返回 JSON 响应（服务未启动或代理转发异常）`,
      -1,
      res.status,
    );
  }

  let envelope: Envelope<T>;
  try {
    envelope = (await res.json()) as Envelope<T>;
  } catch {
    throw new ApiError("响应解析失败：返回的 JSON 格式无效", -1, res.status);
  }

  if (typeof envelope?.code !== "number") {
    throw new ApiError("响应结构异常：缺少统一响应信封 code 字段", -1, res.status);
  }

  if (envelope.code !== 0 || !res.ok) {
    throw new ApiError(
      envelope.message || `请求失败（HTTP ${res.status}）`,
      envelope.code,
      res.status,
      envelope.request_id,
    );
  }

  return envelope;
}

/**
 * 发起请求并直接返回信封中的 data。
 * 失败时抛出 ApiError。
 */
export async function apiFetch<T>(
  path: string,
  init: RequestInit & { method?: HttpMethod } = {},
): Promise<T> {
  const envelope = await apiRequest<T>(path, init);
  return envelope.data;
}

/** 拼接查询参数，自动跳过 undefined/null/空字符串 */
export function buildQuery(
  params: Record<string, string | number | undefined | null>,
): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, String(value));
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

/**
 * 下载类请求（CSV 导出等）：响应可能是文件流，也可能是错误信封。
 *
 * - 2xx + 文件流 → 解析 Content-Disposition 文件名，触发浏览器保存；
 * - 其它状态 → 按统一信封解出 ApiError（400 confirm / 403 权限 与其它接口一致）。
 */
export async function apiDownload(
  path: string,
  fallbackFilename: string,
): Promise<string> {
  let res: Response;
  try {
    res = await fetch(`${BASE_URL}${path}`, {
      method: "GET",
      headers: { Accept: "text/csv,application/json" },
      credentials: "include",
      cache: "no-store",
    });
  } catch {
    throw new ApiError("网络异常：无法连接后端服务，请稍后重试", -1, 0);
  }

  if (res.status === 401) {
    redirectToLogin();
  }

  const contentType = res.headers.get("content-type") ?? "";
  if (res.ok && (contentType.includes("text/csv") || contentType.includes("application/octet-stream"))) {
    const blob = await res.blob();
    const filename = filenameFromDisposition(
      res.headers.get("content-disposition"),
      fallbackFilename,
    );
    saveBlob(blob, filename);
    return filename;
  }

  // 失败分支：后端返回统一 JSON 信封
  let message = `下载失败（HTTP ${res.status}）`;
  let code = -1;
  let requestId: string | undefined;
  try {
    const envelope = (await res.json()) as Partial<Envelope<unknown>>;
    if (typeof envelope.code === "number") {
      code = envelope.code;
      message = envelope.message || message;
      requestId = envelope.request_id;
    }
  } catch {
    /* 保留默认信息 */
  }
  throw new ApiError(message, code, res.status, requestId);
}

/** 从 Content-Disposition 提取 filename（无则用兜底名） */
function filenameFromDisposition(header: string | null, fallback: string): string {
  if (!header) return fallback;
  const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(header);
  if (!match) return fallback;
  try {
    return decodeURIComponent(match[1]);
  } catch {
    return match[1];
  }
}

/** 临时 object URL 触发浏览器保存，随后立即释放 */
function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
