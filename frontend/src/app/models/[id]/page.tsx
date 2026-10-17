"use client";

/**
 * 模型详情（阶段 5）：因子快照 / 超参 + 提交训练（切分默认 70/30，可显式）+
 * 训练记录（指标 + data_range 四标注展开）。任务进度每 2s 轮询，终态刷新。
 */

import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Checkbox,
  DatePicker,
  Descriptions,
  Form,
  InputNumber,
  Modal,
  Progress,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import { ArrowLeftOutlined, PlayCircleOutlined } from "@ant-design/icons";
import type { Dayjs } from "dayjs";
import dayjs from "dayjs";
import { AppShell } from "@/components/AppShell";
import { RequireAuth } from "@/components/RequireAuth";
import { useApiMutation, useApiQuery, type ApiMutationInput } from "@/hooks/useApi";
import { useCurrentUser } from "@/hooks/useCurrentUser";
import { buildQuery } from "@/lib/api";
import type {
  DatasetUniverses,
  Job,
  Model,
  Paged,
  ResultSourceAnnotation,
  TrainSubmitReceipt,
  TrainingRun,
} from "@/lib/types";

const { Text, Paragraph } = Typography;

const JOB_STATUS_META: Record<string, { label: string; color: string }> = {
  queued: { label: "排队中", color: "default" },
  running: { label: "运行中", color: "blue" },
  succeeded: { label: "成功", color: "green" },
  failed: { label: "失败", color: "red" },
  canceled: { label: "已取消", color: "orange" },
};

const TERMINAL = new Set(["succeeded", "failed", "canceled"]);

function formatMetric(value: unknown): string {
  if (value === undefined || value === null || value === "") return "—";
  if (typeof value === "number") return value.toFixed(4);
  return String(value);
}

/** 训练记录 data_range 四标注展开行：切分区间 / 数据来源授权 / 局限说明 */
function RunAnnotations({ run }: { run: TrainingRun }) {
  const range = run.data_range ?? {};
  const source = (range.source ?? {}) as ResultSourceAnnotation;
  const train = Array.isArray(range.train) ? (range.train as string[]) : null;
  const valid = Array.isArray(range.valid) ? (range.valid as string[]) : null;
  const limitations = typeof range.limitations === "string" ? range.limitations : null;

  return (
    <Space direction="vertical" size={8} style={{ width: "100%" }}>
      <Descriptions column={{ xs: 1, sm: 2 }} size="small" bordered style={{ maxWidth: 900 }}>
        <Descriptions.Item label="训练区间">
          {train ? `${train[0]} ~ ${train[1]}` : "—"}
        </Descriptions.Item>
        <Descriptions.Item label="验证区间">
          {valid ? `${valid[0]} ~ ${valid[1]}` : "—"}
        </Descriptions.Item>
        <Descriptions.Item label="引擎">{String(range.engine ?? "—")}</Descriptions.Item>
        <Descriptions.Item label="因子数">
          {range.n_factors !== undefined ? String(range.n_factors) : "—"}
        </Descriptions.Item>
        {range.reuse_factor_values ? (
          <Descriptions.Item label="因子值来源" span={2}>
            复用已计算的因子值（与因子页 IC 预览同源）
            {Array.isArray(range.factor_value_runs) && (range.factor_value_runs as string[]).length > 0
              ? `：${(range.factor_value_runs as string[]).map((r) => r.slice(0, 8)).join("、")}`
              : ""}
          </Descriptions.Item>
        ) : null}
        <Descriptions.Item label="数据源 / 供应商">
          {source.vendor ?? source.dataset_name ?? "—"}
        </Descriptions.Item>
        <Descriptions.Item label="授权依据">
          {source.license_ref ? (
            <Text code>{source.license_ref}</Text>
          ) : (
            "—"
          )}
        </Descriptions.Item>
        {source.allowed_use ? (
          <Descriptions.Item label="允许用途" span={2}>
            {source.allowed_use}
            {source.redistribution_allowed ? "（可再分发）" : "（不可再分发）"}
          </Descriptions.Item>
        ) : null}
      </Descriptions>
      {limitations ? (
        <Alert type="warning" showIcon message="局限说明" description={limitations} />
      ) : null}
    </Space>
  );
}

type TrainFormValues = {
  custom_split: boolean;
  train_range?: [Dayjs, Dayjs];
  valid_range?: [Dayjs, Dayjs];
  max_instruments?: number;
  universe?: string;
  reuse: boolean;
};

function ModelDetailContent({ id }: { id: string }) {
  const { message } = App.useApp();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { hasPermission } = useCurrentUser();
  const canTrain = hasPermission("train.submit");
  const [trainModalOpen, setTrainModalOpen] = useState(false);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [form] = Form.useForm<TrainFormValues>();

  const model = useApiQuery<Model>(["model", id], `/v1/models/${id}`);
  const runs = useApiQuery<Paged<TrainingRun>>(
    ["model-runs", id],
    `/v1/training-runs${buildQuery({ model_id: id, page_size: 50 })}`,
  );

  // 训练任务轮询：每 2s，终态停
  const { data: job } = useApiQuery<Job>(
    ["model-train-job", activeJobId],
    `/v1/jobs/${activeJobId ?? ""}`,
    {
      enabled: !!activeJobId,
      refetchInterval: (query) => {
        const status = query.state.data?.status;
        return status && TERMINAL.has(status) ? false : 2000;
      },
    },
  );

  useEffect(() => {
    if (job?.status && TERMINAL.has(job.status)) {
      void queryClient.invalidateQueries({ queryKey: ["model", id] });
      void queryClient.invalidateQueries({ queryKey: ["model-runs", id] });
      void queryClient.invalidateQueries({ queryKey: ["models"] });
    }
  }, [job?.status, id, queryClient]);

  const submitTrain = useApiMutation<TrainSubmitReceipt, ApiMutationInput>();

  // 股票池（阶段 6 D6）：训练绑定模型的数据集，拉其 instruments/*.txt 清单
  const trainDatasetId = model.data?.dataset_id ?? "";
  const universes = useApiQuery<DatasetUniverses>(
    ["model-train-universes", trainDatasetId],
    `/v1/datasets/${trainDatasetId}/universes`,
    { enabled: Boolean(trainDatasetId) },
  );
  const universeOptions = useMemo(() => {
    const items = universes.data?.items ?? [];
    if (!items.length) return [{ value: "all", label: "all（全市场，含指数）" }];
    return items.map((u) => ({
      value: u.name,
      label:
        u.name === "all"
          ? `all（全市场，含指数，${u.instruments} 只）`
          : `${u.name}（${u.instruments} 只）`,
    }));
  }, [universes.data]);

  useEffect(() => {
    if (!trainModalOpen || !universeOptions.length) return;
    const current = form.getFieldValue("universe");
    if (current && universeOptions.some((o) => o.value === current)) return;
    const preferred = universeOptions.some((o) => o.value === "csi300")
      ? "csi300"
      : universeOptions[0].value;
    form.setFieldsValue({ universe: preferred });
  }, [universeOptions, form, trainModalOpen]);

  const onTrain = async (values: TrainFormValues) => {
    const body: Record<string, unknown> = {
      max_instruments: values.max_instruments ?? 0,
      universe: values.universe || "csi300",
      reuse_factor_values: values.reuse === true,
    };
    if (values.custom_split && values.train_range) {
      body.split = {
        train: [
          values.train_range[0].format("YYYY-MM-DD"),
          values.train_range[1].format("YYYY-MM-DD"),
        ],
        ...(values.valid_range
          ? {
              valid: [
                values.valid_range[0].format("YYYY-MM-DD"),
                values.valid_range[1].format("YYYY-MM-DD"),
              ],
            }
          : {}),
      };
    }
    try {
      const receipt = await submitTrain.mutateAsync({
        path: `/v1/models/${id}/train`,
        body,
      });
      setTrainModalOpen(false);
      form.resetFields();
      setActiveJobId(receipt.job_id);
      message.success("训练任务已入队");
      void queryClient.invalidateQueries({ queryKey: ["model", id] });
      void queryClient.invalidateQueries({ queryKey: ["model-runs", id] });
    } catch (error) {
      message.error(error instanceof Error ? error.message : "入队失败");
    }
  };

  const jobActive = !!job && !TERMINAL.has(job.status);
  const statusTag = (status: string) => {
    const map: Record<string, string> = {
      draft: "default",
      training: "blue",
      trained: "green",
      failed: "red",
    };
    return <Tag color={map[status] ?? "default"}>{status}</Tag>;
  };
  const snapshotColumns = useMemo(
    () => [
      { title: "因子", dataIndex: "name" },
      {
        title: "表达式",
        dataIndex: "expression",
        render: (v: string) => (
          <Text code style={{ maxWidth: 420 }} ellipsis={{ tooltip: v }}>
            {v}
          </Text>
        ),
      },
      { title: "版本", dataIndex: "version", width: 70, render: (v: number) => <Tag>v{v}</Tag> },
    ],
    [],
  );

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => router.push("/models")}>
        返回模型训练
      </Button>

      {model.isLoading ? (
        <Spin style={{ display: "block", margin: "48px auto" }} size="large" />
      ) : model.isError || !model.data ? (
        <Alert type="error" showIcon message={model.error?.message ?? "模型加载失败"} />
      ) : (
        <>
          <Card
            title={
              <Space>
                {model.data.name}
                {statusTag(model.data.status)}
              </Space>
            }
            extra={
              canTrain ? (
                <Button
                  type="primary"
                  icon={<PlayCircleOutlined />}
                  loading={submitTrain.isPending || jobActive}
                  onClick={() => setTrainModalOpen(true)}
                >
                  {jobActive ? "训练进行中…" : "提交训练"}
                </Button>
              ) : null
            }
          >
            <Descriptions column={{ xs: 1, sm: 2, lg: 3 }} size="small">
              <Descriptions.Item label="所属项目">
                {model.data.project_name ?? model.data.project_id}
              </Descriptions.Item>
              <Descriptions.Item label="数据集">
                {model.data.dataset_name ?? model.data.dataset_id}
              </Descriptions.Item>
              <Descriptions.Item label="算法">{model.data.algo}</Descriptions.Item>
              <Descriptions.Item label="目标表达式">
                <Tooltip title={String(model.data.training_config.target ?? "")}>
                  <Text
                    code
                    style={{ maxWidth: 260 }}
                    ellipsis={{ tooltip: String(model.data.training_config.target ?? "") }}
                  >
                    {String(model.data.training_config.target ?? "—")}
                  </Text>
                </Tooltip>
              </Descriptions.Item>
              <Descriptions.Item label="超参">
                {Object.entries(model.data.hyperparams)
                  .map(([k, v]) => `${k}=${String(v)}`)
                  .join(", ") || "—"}
              </Descriptions.Item>
              <Descriptions.Item label="登记人">{model.data.created_by}</Descriptions.Item>
            </Descriptions>

            {job ? (
              <div style={{ marginTop: 12 }}>
                <Space size={12} wrap>
                  <Tag color={JOB_STATUS_META[job.status]?.color}>
                    {JOB_STATUS_META[job.status]?.label ?? job.status}
                  </Tag>
                  <Progress
                    percent={job.progress}
                    size="small"
                    style={{ width: 200 }}
                    status={job.status === "failed" ? "exception" : undefined}
                  />
                  <Text type="secondary" style={{ fontSize: 13 }}>
                    任务 {job.id.slice(0, 8)} · 尝试 {job.attempts}/{job.max_attempts}
                  </Text>
                </Space>
                {job.error ? (
                  <Alert style={{ marginTop: 8 }} type="error" showIcon message={job.error} />
                ) : null}
                <div style={{ marginTop: 8 }}>
                  <Button
                    size="small"
                    type="link"
                    onClick={() => router.push(`/jobs/${job.id}`)}
                  >
                    查看任务日志
                  </Button>
                </div>
              </div>
            ) : null}
          </Card>

          <Card title="特征因子（创建时快照）" size="small">
            <Table
              rowKey="factor_id"
              size="small"
              pagination={false}
              dataSource={model.data.factor_snapshot}
              columns={snapshotColumns}
            />
            <Paragraph type="secondary" style={{ fontSize: 12, marginTop: 12, marginBottom: 0 }}>
              快照固化于创建时刻：后续修改因子库不影响本模型，训练任务 payload 同样携带该快照。
            </Paragraph>
          </Card>

          <Card title="训练记录" size="small">
            <Table<TrainingRun>
              rowKey="id"
              size="small"
              loading={runs.isLoading}
              dataSource={runs.data?.items ?? []}
              pagination={{ pageSize: 10, hideOnSinglePage: true }}
              expandable={{
                rowExpandable: (row) => Object.keys(row.data_range ?? {}).length > 0,
                expandedRowRender: (row) => <RunAnnotations run={row} />,
              }}
              columns={[
                {
                  title: "提交时间",
                  dataIndex: "created_at",
                  width: 160,
                  render: (v: string) => dayjs(v).format("YYYY-MM-DD HH:mm:ss"),
                },
                {
                  title: "状态",
                  dataIndex: "job_status",
                  width: 95,
                  render: (v: string | null) => {
                    const meta = v ? JOB_STATUS_META[v] : undefined;
                    return <Tag color={meta?.color ?? "default"}>{meta?.label ?? v ?? "—"}</Tag>;
                  },
                },
                {
                  title: "train_ic",
                  key: "train_ic",
                  width: 95,
                  render: (_: unknown, row: TrainingRun) => formatMetric(row.metrics.train_ic),
                },
                {
                  title: "valid_ic",
                  key: "valid_ic",
                  width: 95,
                  render: (_: unknown, row: TrainingRun) => formatMetric(row.metrics.valid_ic),
                },
                {
                  title: "valid_ir",
                  key: "valid_ir",
                  width: 95,
                  render: (_: unknown, row: TrainingRun) => formatMetric(row.metrics.valid_ir),
                },
                {
                  title: "artifact",
                  dataIndex: "artifact_uri",
                  render: (v: string | null) =>
                    v ? (
                      <Text code style={{ maxWidth: 220 }} ellipsis={{ tooltip: v }}>
                        {v}
                      </Text>
                    ) : (
                      <Text type="secondary">—</Text>
                    ),
                },
                {
                  title: "完成时间",
                  dataIndex: "finished_at",
                  width: 160,
                  render: (v: string | null) =>
                    v ? dayjs(v).format("YYYY-MM-DD HH:mm:ss") : "—",
                },
              ]}
            />
          </Card>

          <Modal
            title="提交训练"
            open={trainModalOpen}
            onCancel={() => setTrainModalOpen(false)}
            onOk={() => void form.submit()}
            okButtonProps={{ loading: submitTrain.isPending }}
            destroyOnClose
          >
            <Form
              form={form}
              layout="vertical"
              initialValues={{ custom_split: false, max_instruments: 0, reuse: false }}
              onFinish={(v) => void onTrain(v)}
            >
              <Form.Item
                name="custom_split"
                valuePropName="checked"
                extra="不勾选时按数据集区间自动 70/30 切分（train 前段 / valid 后段，不重叠）"
              >
                <Checkbox>自定义训练/验证切分</Checkbox>
              </Form.Item>
              <Form.Item
                noStyle
                shouldUpdate={(prev, next) => prev.custom_split !== next.custom_split}
              >
                {({ getFieldValue }) =>
                  getFieldValue("custom_split") ? (
                    <Space direction="vertical" style={{ width: "100%" }}>
                      <Form.Item
                        name="train_range"
                        label="训练区间"
                        rules={[{ required: true, message: "请选择训练区间" }]}
                      >
                        <DatePicker.RangePicker style={{ width: "100%" }} />
                      </Form.Item>
                      <Form.Item name="valid_range" label="验证区间（可留空）">
                        <DatePicker.RangePicker style={{ width: "100%" }} />
                      </Form.Item>
                    </Space>
                  ) : null
                }
              </Form.Item>
              <Form.Item
                name="max_instruments"
                label="训练标的数上限"
                extra="0 = 全量；小样本冒烟/调参时可截断（如 50）"
              >
                <InputNumber min={0} max={20000} style={{ width: "100%" }} />
              </Form.Item>
              <Form.Item
                name="universe"
                label="股票池"
                extra="all 含指数代码（SH000300 等）；成分池为数据集 instruments 文件静态快照"
              >
                <Select options={universeOptions} loading={universes.isLoading} />
              </Form.Item>
              <Form.Item
                name="reuse"
                valuePropName="checked"
                extra="开启后读取因子页「计算 IC」落库的因子值（同版本，values.csv.gz）而非训练时重算表达式；任一因子无同版本的已完成计算记录时提交会被拒绝（不静默回退）"
              >
                <Checkbox>复用已计算的因子值（与 IC 预览同源）</Checkbox>
              </Form.Item>
            </Form>
          </Modal>
        </>
      )}
    </Space>
  );
}

export default function ModelDetailPage() {
  const { id } = useParams<{ id: string }>();
  return (
    <AppShell>
      <RequireAuth>
        <ModelDetailContent id={id} />
      </RequireAuth>
    </AppShell>
  );
}
