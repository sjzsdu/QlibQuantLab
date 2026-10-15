/**
 * 后端统一响应信封与业务类型定义。
 * 后端契约：{ code: 0, message: "ok", data: <payload>, request_id: "..." }
 */

/** 统一响应体；code != 0 表示业务错误（此时 HTTP 状态码为 4xx/5xx） */
export interface Envelope<T> {
  code: number;
  message: string;
  data: T;
  request_id?: string;
}

/** 分页响应 */
export interface Paged<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export type Role = "admin" | "researcher" | "viewer" | "auditor";

/** 角色中文名映射（全站中文界面） */
export const ROLE_LABELS: Record<Role, string> = {
  admin: "管理员",
  researcher: "研究员",
  viewer: "访客",
  auditor: "审计员",
};

/** GET /api/v1/me */
export interface CurrentUser {
  user_id: string;
  username: string;
  display_name?: string | null;
  email?: string | null;
  org_id: string;
  org_name?: string | null;
  roles: Role[];
  is_authenticated: boolean;
  provider: string;
}

/** GET /api/v1/me/permissions */
export interface PermissionsResponse {
  permissions: string[];
}

/** GET /api/v1/orgs/current */
export interface OrgInfo {
  id: string;
  slug: string;
  name: string;
}

/** GET /api/v1/auth/login */
export interface LoginResponse {
  url: string;
}

/** GET /api/v1/auth/logout（后端可能返回跳转地址，也可能清 cookie 后由前端兜底跳转） */
export interface LogoutResponse {
  url?: string;
  redirect_to?: string | null;
}

export type Visibility = "private" | "org" | "public";

/** 项目（GET/POST/PATCH /api/v1/projects*） */
export interface Project {
  id: string;
  name: string;
  description?: string | null;
  visibility: Visibility;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface CreateProjectInput {
  name: string;
  description?: string;
}

export interface UpdateProjectInput {
  name?: string;
  description?: string;
}

/** DELETE /api/v1/projects/{id}?confirm=true */
export interface DeleteResult {
  deleted: boolean;
}

/** GET /api/v1/audit-logs */
export interface AuditLog {
  id: string;
  action: string;
  resource_type?: string | null;
  resource_id?: string | null;
  outcome: string;
  actor_username?: string | null;
  detail?: string | null;
  ip?: string | null;
  request_id?: string | null;
  created_at: string;
}

export type LegalCode = "terms" | "risk" | "disclaimer";

/** GET /api/v1/legal/{code}，content 为 Markdown 字符串 */
export interface LegalDocument {
  code: string;
  title: string;
  version: string;
  effective_at: string;
  content: string;
}

/** GET /api/v1/legal/meta */
export interface LegalMeta {
  code: string;
  title: string;
  version: string;
  effective_at: string;
}

/** GET /api/v1/health/live|ready */
export interface HealthStatus {
  status?: string;
  [key: string]: unknown;
}

/** GET /api/v1/system/info（字段由后端扩展，前端做防御性渲染） */
export interface SystemInfo {
  version?: string;
  auth_provider?: string;
  [key: string]: unknown;
}
