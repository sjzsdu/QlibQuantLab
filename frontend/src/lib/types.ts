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

// ------------------------------------------------------------------ 阶段 4：数据域
export type LicenseStatus = "active" | "revoked";

/** GET /api/v1/data-sources */
export interface DataSource {
  id: string;
  name: string;
  kind: string;
  vendor?: string | null;
  homepage?: string | null;
  notes?: string | null;
  status: string;
  dataset_count: number;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface CreateDataSourceInput {
  name: string;
  kind?: string;
  vendor?: string;
  homepage?: string;
  notes?: string;
}

/** GET /api/v1/data-licenses（授权台账） */
export interface DataLicense {
  id: string;
  data_source_id: string;
  data_source_name?: string | null;
  scope: string;
  license_ref: string;
  allowed_use: string;
  redistribution_allowed: boolean;
  granted_by: string;
  granted_at?: string | null;
  expires_at?: string | null;
  evidence_uri?: string | null;
  status: LicenseStatus;
  created_at: string;
  updated_at: string;
}

export interface CreateDataLicenseInput {
  data_source_id: string;
  license_ref: string;
  allowed_use: string;
  redistribution_allowed?: boolean;
  granted_by: string;
  expires_at?: string;
  scope?: string;
}

export type DatasetStatus = "pending" | "active" | "failed";

/** GET /api/v1/datasets */
export interface Dataset {
  id: string;
  project_id?: string | null;
  project_name?: string | null;
  data_source_id: string;
  data_source_name?: string | null;
  license_id: string;
  license_ref?: string | null;
  name: string;
  qlib_region: string;
  freq: string;
  start_date?: string | null;
  end_date?: string | null;
  instrument_count: number;
  storage_uri: string;
  status: DatasetStatus;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface CreateDatasetInput {
  data_source_id: string;
  license_id: string;
  name: string;
  qlib_region?: string;
  freq?: string;
  project_id?: string;
}

/** POST /api/v1/datasets/{id}/import（进度经 /jobs/{job_id} 每 2s 轮询） */
export interface DatasetImportReceipt {
  dataset_id: string;
  job_id: string;
  status: string;
}

/** GET /api/v1/datasets/{id}/preview */
export interface PreviewRow {
  date: string;
  values: Record<string, number>;
}

export interface DatasetPreview {
  dataset_id: string;
  instrument: string;
  fields: string[];
  items: PreviewRow[];
  total: number;
  page: number;
  page_size: number;
}

export interface DatasetInstruments {
  dataset_id: string;
  items: { instrument: string; display_name: string }[];
  total: number;
  page: number;
  page_size: number;
}

export interface DatasetCalendar {
  dataset_id: string;
  total: number;
  start?: string | null;
  end?: string | null;
}

// ------------------------------------------------------------------ 阶段 4：因子域
export interface Factor {
  id: string;
  project_id: string;
  project_name?: string | null;
  name: string;
  expression: string;
  factor_type: string;
  description?: string | null;
  params: Record<string, unknown>;
  version: number;
  visibility: Visibility;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface CreateFactorInput {
  project_id: string;
  name: string;
  expression: string;
  description?: string;
}

/** POST /api/v1/factors/validate（静态校验，不落库） */
export interface ExpressionCheck {
  valid: boolean;
  errors: string[];
  fields: string[];
  functions: string[];
}

// ------------------------------------------------------------------ 阶段 4：任务（只读子集）
export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "canceled";

/** GET /api/v1/jobs / jobs/{id} */
export interface Job {
  id: string;
  kind: string;
  status: JobStatus;
  progress: number;
  attempts: number;
  max_attempts: number;
  error?: string | null;
  payload: Record<string, unknown>;
  requested_by: string;
  queued_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  created_at: string;
}

// ------------------------------------------------------------------ 阶段 4：项目成员
export interface ProjectMember {
  user_id: string;
  username: string;
  role: string;
  added_at?: string | null;
}

// ------------------------------------------------------------------ 阶段 5：模型 / 训练
/** 因子快照条目（创建模型时固化，后续改因子不影响） */
export interface FactorSnapshotItem {
  factor_id: string;
  name: string;
  expression: string;
  version: number;
  factor_type: string;
}

export interface TrainingRunBrief {
  id: string;
  job_id?: string | null;
  job_status?: string | null;
  created_at: string;
  finished_at?: string | null;
}

export type ModelStatus = "draft" | "training" | "trained" | "failed";

/** GET /api/v1/models */
export interface Model {
  id: string;
  project_id: string;
  project_name?: string | null;
  dataset_id: string;
  dataset_name?: string | null;
  name: string;
  algo: string;
  hyperparams: Record<string, unknown>;
  training_config: Record<string, unknown>;
  factor_snapshot: FactorSnapshotItem[];
  status: ModelStatus;
  last_run?: TrainingRunBrief | null;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface CreateModelInput {
  project_id: string;
  dataset_id: string;
  name: string;
  algo?: string;
  factor_ids: string[];
  hyperparams?: Record<string, unknown>;
  target?: string;
}

/** GET /api/v1/models/catalog（静态目录，偏差登记 docs/stage5/06-risks.md） */
export interface ModelCatalogItem {
  algo: string;
  label: string;
  available: boolean;
  note?: string;
}

/** POST /api/v1/models/{id}/train */
export interface TrainSubmitReceipt {
  job_id: string;
  training_run_id: string;
  split: { train: string[]; valid?: string[] };
  status: string;
}

/** GET /api/v1/training-runs（data_range 内含四标注：切分/引擎/数据来源授权/limitations） */
export interface TrainingRun {
  id: string;
  model_id: string;
  model_name?: string | null;
  dataset_id: string;
  job_id?: string | null;
  job_status?: string | null;
  metrics: Record<string, number | string>;
  data_range: Record<string, unknown>;
  artifact_uri?: string | null;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
}

// ------------------------------------------------------------------ 阶段 5：策略
export type SignalSource = "rule" | "model";

/** GET /api/v1/strategies */
export interface Strategy {
  id: string;
  project_id: string;
  project_name?: string | null;
  model_id?: string | null;
  model_name?: string | null;
  name: string;
  description?: string | null;
  signal_source: SignalSource;
  signal_config: Record<string, unknown>;
  visibility: Visibility;
  is_public: boolean;
  version: number;
  published_at?: string | null;
  published_by?: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface CreateStrategyInput {
  project_id: string;
  name: string;
  description?: string;
  signal_source?: SignalSource;
  model_id?: string;
  lookback?: number;
}

// ------------------------------------------------------------------ 阶段 5：回测
/** 费用三件套必填（后端 422 校验），其余为交易所常规默认 */
export interface CostConfig {
  commission_rate: number;
  slippage_value: number;
  impact_rate_per_million: number;
  slippage_type?: "fixed_bp";
  min_commission?: number;
  settlement_fee_rate?: number;
  stamp_duty_sell?: number;
}

/** 数据来源/授权四标注第 4 项（data_range.source） */
export interface ResultSourceAnnotation {
  dataset_id?: string;
  dataset_name?: string;
  data_source_id?: string;
  vendor?: string | null;
  license_ref?: string | null;
  allowed_use?: string | null;
  redistribution_allowed?: boolean | null;
}

/** GET /api/v1/backtests（metrics/data_range 携带四标注） */
export interface Backtest {
  id: string;
  project_id: string;
  project_name?: string | null;
  strategy_id: string;
  strategy_name?: string | null;
  dataset_id: string;
  dataset_name?: string | null;
  job_id?: string | null;
  job_status?: string | null;
  benchmark: string;
  cost_config: CostConfig;
  params: Record<string, unknown>;
  split_config: Record<string, unknown>;
  metrics: Record<string, number | string>;
  data_range: Record<string, unknown> & {
    source?: ResultSourceAnnotation;
    signal_source?: SignalSource;
  };
  limitations?: string | null;
  curve_uri?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface CreateBacktestInput {
  strategy_id: string;
  dataset_id: string;
  benchmark?: string;
  start_date?: string;
  end_date?: string;
  topk?: number;
  max_instruments?: number;
  cost_config: CostConfig;
}

/** GET /api/v1/backtests/{id}/curve（≤1500 点降采样） */
export interface BacktestCurve {
  points: [string, number][];
  total: number;
  downsampled: boolean;
}

// ------------------------------------------------------------------ 阶段 5：任务中心
export interface JobLog {
  seq: number;
  level: string;
  message: string;
  created_at: string;
}

/** GET /api/v1/jobs/{id}/logs?since_seq=N（2s 增量轮询） */
export interface JobLogs {
  items: JobLog[];
  next_seq: number;
  status: JobStatus;
  progress: number;
}

/** POST /api/v1/jobs/{id}/cancel | retry */
export interface JobAction {
  id: string;
  status: string;
  detail?: string | null;
}
