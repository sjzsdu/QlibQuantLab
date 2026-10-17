"use client";

/**
 * 因子详情（阶段 4 CRUD + 阶段 6 切片⑤ 计算/IC 预览）：
 * - 编辑（名称/描述/表达式 + 静态校验）、发布（二次确认）、删除；
 *   表达式变更保存后后端自动 version+1（版本历史留痕）。
 * - 「计算 IC」：提交 worker 计算任务（qlib D.features / stub 合成），
 *   计算记录展示 覆盖率 + 日度 rank-IC 汇总，选中记录可预览 IC 曲线（≤1500 点）。
 *   结果沿用平台「四标注」口径：区间 / 股票池 / 数据来源授权 / 局限说明。
 */

import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import dynamic from "next/dynamic";
import { useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  DatePicker,
  Descriptions,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
} from "antd";
import type { Dayjs } from "dayjs";
import dayjs from "dayjs";
import { ArrowLeftOutlined, CheckCircleOutlined, ExperimentOutlined } from "@ant-design/icons";
import { AppShell } from "@/components/AppShell";
import { RequireAuth } from "@/components/RequireAuth";
import { ExpressionValidator } from "@/components/ExpressionValidator";
import { useApiMutation, useApiQuery, type ApiMutationInput } from "@/hooks/useApi";
import { useCurrentUser } from "@/hooks/useCurrentUser";
import { buildQuery } from "@/lib/api";
import type {
  Dataset,
  DatasetUniverses,
  Factor,
  FactorComputeRun,
  FactorComputeSubmitInput,
  IcCurve,
  Paged,
  ResultSourceAnnotation,
  Visibility,
} from "@/lib/types";

const IcCurveChart = dynamic(() => import("@/components/IcCurveChart"), {
  ssr: false,
  loading: () => <Spin style={{ display: "block", margin: "24px auto" }} size="small" />,
});

const { Text, Paragraph } = Typography;

const VISIBILITY_META: Record<Visibility, { label: string; color: string }> = {
  private: { label: "私有", color: "default" },
  org: { label: "组织内", color: "blue" },
  public: { label: "已发布", color: "green" },
};

const JOB_STATUS_META: Record<string, { label: string; color: string }> = {
  queued: { label: "排队中", color: "default" },
  running: { label: "运行中", color: "blue" },
  succeeded: { label: "成功", color: "green" },
  failed: { label: "失败", color: "red" },
  canceled: { label: "已取消", color: "orange" },
};

type FactorEditForm = {
  name: string;
  description?: string;
  expression: string;
};

type ComputeFormValues = {
  dataset_id: string;
  universe?: string;
  range?: [Dayjs, Dayjs];
};

const fmtNum = (value: unknown, digits = 4) =>
  typeof value === "number" ? value.toFixed(digits) : "—";
const fmtPct = (value: unknown) =>
  typeof value === "number" ? `${(value * 100).toFixed(1)}%` : "—";

function FactorDetailContent({ id }: { id: string }) {
  const { message, modal } = App.useApp();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { hasPermission } = useCurrentUser();
  const canWrite = hasPermission("factor.write");
  const canPublish = hasPermission("factor.publish");

  const factorQuery = useApiQuery<Factor>(["factor", id], `/v1/factors/${id}`);
  const [form] = Form.useForm<FactorEditForm>();
  const [expression, setExpression] = useState<string | undefined>(undefined);

  const updateFactor = useApiMutation<unknown, ApiMutationInput>();
  const publishFactor = useApiMutation<unknown, ApiMutationInput>();
  const deleteFactor = useApiMutation<unknown, ApiMutationInput>();
  const computeFactor = useApiMutation<{ job_id: string; run_id: string }, ApiMutationInput>();

  const canCompute = hasPermission("factor.compute");

  // 计算记录（阶段 6 切片⑤）：有活跃任务时 3s 轮询，终态停
  const runsQuery = useApiQuery<Paged<FactorComputeRun>>(
    ["factor-compute-runs", id],
    `/v1/factors/${id}/compute-runs${buildQuery({ page_size: 10 })}`,
    {
      refetchInterval: (query) => {
        const items = query.state.data?.items ?? [];
        return items.some((r) => r.job_status === "queued" || r.job_status === "running")
          ? 3000
          : false;
      },
    },
  );
  const runs = useMemo(() => runsQuery.data?.items ?? [], [runsQuery.data]);

  // 计算提交表单：数据集 + 股票池（默认 csi300）+ 可选区间
  const [computeOpen, setComputeOpen] = useState(false);
  const [computeForm] = Form.useForm<ComputeFormValues>();
  const datasets = useApiQuery<Paged<Dataset>>(
    ["factor-compute-datasets"],
    `/v1/datasets${buildQuery({ page_size: 200 })}`,
  );
  const datasetOptions = useMemo(
    () =>
      (datasets.data?.items ?? []).map((d) => ({
        value: d.id,
        label: `${d.name}（${d.status ?? "—"}）`,
      })),
    [datasets.data],
  );
  const watchedDatasetId = Form.useWatch("dataset_id", computeForm);
  const universes = useApiQuery<DatasetUniverses>(
    ["factor-compute-universes", watchedDatasetId ?? ""],
    `/v1/datasets/${watchedDatasetId}/universes`,
    { enabled: Boolean(watchedDatasetId) },
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
  // 股票池默认 csi300（提示：已排除指数）；数据集无该池则退回第一个可用池
  useEffect(() => {
    if (!computeOpen || !universeOptions.length) return;
    const current = computeForm.getFieldValue("universe");
    if (current && universeOptions.some((o) => o.value === current)) return;
    const preferred = universeOptions.some((o) => o.value === "csi300")
      ? "csi300"
      : universeOptions[0].value;
    computeForm.setFieldsValue({ universe: preferred });
  }, [universeOptions, computeForm, computeOpen]);

  // 选中记录的 IC 曲线（≤1500 点降采样）
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const icCurve = useApiQuery<IcCurve>(
    ["factor-ic-curve", id, selectedRunId ?? ""],
    `/v1/factors/${id}/compute-runs/${selectedRunId}/ic-curve`,
    { enabled: Boolean(selectedRunId) },
  );
  const selectedRun = runs.find((r) => r.id === selectedRunId) ?? null;

  const onSubmitCompute = async (values: ComputeFormValues) => {
    const body: FactorComputeSubmitInput = {
      dataset_id: values.dataset_id,
      universe: values.universe,
      ...(values.range
        ? {
            start_date: values.range[0].format("YYYY-MM-DD"),
            end_date: values.range[1].format("YYYY-MM-DD"),
          }
        : {}),
    };
    try {
      await computeFactor.mutateAsync({ path: `/v1/factors/${id}/compute`, method: "POST", body });
      message.success("计算任务已入队，完成后可在下方预览 IC 曲线");
      setComputeOpen(false);
      computeForm.resetFields();
      void queryClient.invalidateQueries({ queryKey: ["factor-compute-runs", id] });
    } catch (error) {
      message.error(error instanceof Error ? error.message : "提交失败");
    }
  };

  const factor = factorQuery.data;

  const onSave = async (values: FactorEditForm) => {
    try {
      await updateFactor.mutateAsync({
        path: `/v1/factors/${id}`,
        method: "PATCH",
        body: values,
      });
      message.success("因子已保存");
      void queryClient.invalidateQueries({ queryKey: ["factor", id] });
      void queryClient.invalidateQueries({ queryKey: ["factors"] });
    } catch (error) {
      message.error(error instanceof Error ? error.message : "保存失败");
    }
  };

  const onPublish = () => {
    modal.confirm({
      title: "确认发布该因子？",
      content:
        "发布后该因子对全组织可见，且作为「已发布定义」被后续研究引用（不可静默修改语义，修改会生成新版本）。",
      okText: "发布",
      cancelText: "取消",
      onOk: async () => {
        try {
          await publishFactor.mutateAsync({
            path: `/v1/factors/${id}/publish?confirm=true`,
          });
          message.success("因子已发布");
          void queryClient.invalidateQueries({ queryKey: ["factor", id] });
          void queryClient.invalidateQueries({ queryKey: ["factors"] });
        } catch (error) {
          message.error(error instanceof Error ? error.message : "发布失败");
        }
      },
    });
  };

  const onDelete = async () => {
    try {
      await deleteFactor.mutateAsync({
        path: `/v1/factors/${id}?confirm=true`,
        method: "DELETE",
      });
      message.success("因子已删除");
      void queryClient.invalidateQueries({ queryKey: ["factors"] });
      router.push("/factors");
    } catch (error) {
      message.error(error instanceof Error ? error.message : "删除失败");
    }
  };

  if (factorQuery.isLoading || !factor) {
    return (
      <Spin style={{ display: "block", margin: "48px auto" }} size="large" />
    );
  }

  const meta = VISIBILITY_META[factor.visibility] ?? VISIBILITY_META.private;

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => router.push("/factors")}>
        返回因子库
      </Button>

      <Card
        title={
          <Space>
            {factor.name}
            <Tag color={meta.color}>{meta.label}</Tag>
            <Tag>v{factor.version}</Tag>
          </Space>
        }
        extra={
          canWrite ? (
            <Space>
              {canPublish && factor.visibility !== "public" ? (
                <Button
                  type="primary"
                  icon={<CheckCircleOutlined />}
                  loading={publishFactor.isPending}
                  onClick={onPublish}
                >
                  发布
                </Button>
              ) : null}
              <Popconfirm
                title="确认删除该因子？"
                description="删除后无法恢复。"
                okText="删除"
                cancelText="取消"
                onConfirm={() => void onDelete()}
              >
                <Button danger>删除</Button>
              </Popconfirm>
            </Space>
          ) : null
        }
      >
        <Descriptions column={{ xs: 1, sm: 2 }} size="small">
          <Descriptions.Item label="所属项目">
            <Button
              type="link"
              size="small"
              style={{ padding: 0 }}
              onClick={() => router.push(`/projects/${factor.project_id}`)}
            >
              {factor.project_name ?? factor.project_id}
            </Button>
          </Descriptions.Item>
          <Descriptions.Item label="创建人">{factor.created_by}</Descriptions.Item>
          <Descriptions.Item label="创建时间">
            {dayjs(factor.created_at).format("YYYY-MM-DD HH:mm")}
          </Descriptions.Item>
          <Descriptions.Item label="更新时间">
            {dayjs(factor.updated_at).format("YYYY-MM-DD HH:mm")}
          </Descriptions.Item>
        </Descriptions>
        {factor.visibility === "public" ? (
          <Alert
            style={{ marginTop: 12 }}
            type="info"
            showIcon
            message="已发布：表达式变更会生成新版本（version+1），历史版本可追溯。"
          />
        ) : null}
      </Card>

      <Card title="定义">
        <Form<FactorEditForm>
          form={form}
          layout="vertical"
          initialValues={{
            name: factor.name,
            description: factor.description ?? "",
            expression: factor.expression,
          }}
          onFinish={(values) => void onSave(values)}
        >
          <Form.Item
            name="name"
            label="名称"
            rules={[{ required: true, message: "请输入名称" }]}
          >
            <Input maxLength={200} disabled={!canWrite} />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} disabled={!canWrite} />
          </Form.Item>
          <Form.Item
            name="expression"
            label="Qlib 表达式"
            rules={[{ required: true, message: "请输入表达式" }]}
            extra="字段：$open/$high/$low/$close/$volume/$factor/$vwap；函数：Ref/Mean/Std/Rank/If 等白名单。表达式变更保存后 version+1。"
          >
            <Input.TextArea
              rows={4}
              maxLength={500}
              disabled={!canWrite}
              style={{ fontFamily: "monospace" }}
              onChange={(event) => setExpression(event.target.value)}
            />
          </Form.Item>
          <ExpressionValidator expression={expression ?? factor.expression} />
          {canWrite ? (
            <Paragraph style={{ marginTop: 16, marginBottom: 0 }}>
              <Button type="primary" htmlType="submit" loading={updateFactor.isPending}>
                保存
              </Button>
              <Text type="secondary" style={{ marginLeft: 12, fontSize: 12 }}>
                静态校验即时生效；表达式真实求值走「计算 IC」任务（qlib / stub 引擎），
                结果含覆盖率与日度 rank-IC 预览。
              </Text>
            </Paragraph>
          ) : (
            <Alert style={{ marginTop: 12 }} type="info" showIcon message="你当前的角色为只读，无法编辑因子。" />
          )}
        </Form>
      </Card>

      {/* 计算与 IC 预览（阶段 6 切片⑤） */}
      <Card
        title="计算与 IC 预览"
        extra={
          canCompute ? (
            <Button
              type="primary"
              icon={<ExperimentOutlined />}
              onClick={() => setComputeOpen(true)}
            >
              计算 IC
            </Button>
          ) : null
        }
      >
        {runs.length === 0 ? (
          <Alert
            type="info"
            showIcon
            message="尚未计算过：点击右上角「计算 IC」提交任务。IC 为历史区间样本内统计（对次期收益的秩相关），非未来收益承诺。"
          />
        ) : (
          <Table<FactorComputeRun>
            rowKey="id"
            size="small"
            loading={runsQuery.isLoading}
            dataSource={runs}
            pagination={false}
            onRow={(record) => ({
              onClick: () => {
                if (record.ic_uri) setSelectedRunId(record.id);
              },
              style: { cursor: record.ic_uri ? "pointer" : "default" },
            })}
            columns={[
              {
                title: "计算时间",
                dataIndex: "created_at",
                render: (value: string) => dayjs(value).format("YYYY-MM-DD HH:mm"),
              },
              {
                title: "状态",
                dataIndex: "job_status",
                render: (value: string | null) => {
                  const meta = JOB_STATUS_META[value ?? ""];
                  return meta ? <Tag color={meta.color}>{meta.label}</Tag> : "—";
                },
              },
              {
                title: "股票池",
                render: (_: unknown, row: FactorComputeRun) =>
                  String(row.data_range.universe ?? "all"),
              },
              {
                title: "区间",
                render: (_: unknown, row: FactorComputeRun) =>
                  `${String(row.data_range.start ?? "—")} ~ ${String(row.data_range.end ?? "—")}`,
              },
              {
                title: "覆盖率",
                render: (_: unknown, row: FactorComputeRun) => fmtPct(row.metrics.coverage),
              },
              {
                title: "IC 均值",
                render: (_: unknown, row: FactorComputeRun) => fmtNum(row.metrics.ic_mean),
              },
              {
                title: "ICIR",
                render: (_: unknown, row: FactorComputeRun) => fmtNum(row.metrics.ic_ir),
              },
              {
                title: "正IC占比",
                render: (_: unknown, row: FactorComputeRun) => fmtPct(row.metrics.ic_positive_ratio),
              },
              {
                title: "有效天数",
                render: (_: unknown, row: FactorComputeRun) => String(row.metrics.n_days ?? "—"),
              },
              {
                title: "操作",
                render: (_: unknown, row: FactorComputeRun) => (
                  <Space size={4}>
                    {row.ic_uri ? (
                      <Button
                        size="small"
                        type={selectedRunId === row.id ? "primary" : "default"}
                        onClick={(event) => {
                          event.stopPropagation();
                          setSelectedRunId(row.id);
                        }}
                      >
                        IC 曲线
                      </Button>
                    ) : null}
                    {row.job_id ? (
                      <Button
                        size="small"
                        type="link"
                        onClick={(event) => {
                          event.stopPropagation();
                          router.push(`/jobs/${row.job_id}`);
                        }}
                      >
                        任务
                      </Button>
                    ) : null}
                  </Space>
                ),
              },
            ]}
          />
        )}

        {selectedRun && selectedRun.ic_uri ? (
          <Card
            size="small"
            style={{ marginTop: 16 }}
            title={`日度 rank-IC 曲线（${dayjs(selectedRun.created_at).format("YYYY-MM-DD HH:mm")} 计算）`}
          >
            {icCurve.data ? (
              <IcCurveChart points={icCurve.data.points} />
            ) : icCurve.isError ? (
              <Alert
                type="warning"
                showIcon
                message={icCurve.error instanceof Error ? icCurve.error.message : "IC 曲线加载失败"}
              />
            ) : (
              <Spin style={{ display: "block", margin: "24px auto" }} size="small" />
            )}
            <Paragraph style={{ marginTop: 8, marginBottom: 4, fontSize: 12 }} type="secondary">
              表达式快照：{String(selectedRun.data_range.expression ?? factor.expression)}（v
              {String(selectedRun.data_range.version ?? "—")}） ｜ 股票池：
              {String(selectedRun.data_range.universe ?? "all")} ｜ 区间：
              {String(selectedRun.data_range.start ?? "—")} ~{" "}
              {String(selectedRun.data_range.end ?? "—")} ｜ 引擎：
              {String(selectedRun.data_range.engine ?? "—")}
              {icCurve.data?.downsampled ? " ｜ 已降采样展示" : ""}
            </Paragraph>
            {typeof selectedRun.data_range.limitations === "string" &&
            selectedRun.data_range.limitations ? (
              <Alert
                type="warning"
                showIcon
                message={selectedRun.data_range.limitations}
                style={{ whiteSpace: "pre-wrap", fontSize: 12 }}
              />
            ) : null}
            {selectedRun.data_range.source ? (
              <Paragraph style={{ marginTop: 8, marginBottom: 0, fontSize: 12 }} type="secondary">
                数据来源授权：
                {(() => {
                  const source = selectedRun.data_range.source as ResultSourceAnnotation;
                  return (
                    <>
                      {source.vendor ? `${source.vendor} · ` : ""}
                      {source.dataset_name ? `${source.dataset_name} · ` : ""}
                      {source.license_ref ? <Text code>{source.license_ref}</Text> : "—"}
                      {source.allowed_use ? `（${source.allowed_use}）` : ""}
                    </>
                  );
                })()}
              </Paragraph>
            ) : null}
          </Card>
        ) : null}
      </Card>

      <Modal
        title="计算因子 IC"
        open={computeOpen}
        onCancel={() => setComputeOpen(false)}
        onOk={() => void computeForm.submit()}
        okText="提交计算"
        confirmLoading={computeFactor.isPending}
        destroyOnClose
      >
        <Paragraph type="secondary" style={{ fontSize: 12 }}>
          提交后由 worker 计算：因子值对次期收益的「日度横截面 rank-IC」（每日样本 &lt; 5 跳过）+
          覆盖率。表达式按当前版本快照，入队后修改因子不影响本次运行。
        </Paragraph>
        <Form<ComputeFormValues>
          form={computeForm}
          layout="vertical"
          onFinish={(values) => void onSubmitCompute(values)}
        >
          <Form.Item
            name="dataset_id"
            label="数据集"
            rules={[{ required: true, message: "请选择数据集" }]}
          >
            <Select
              options={datasetOptions}
              placeholder="选择已导入（active）的数据集"
              showSearch
              optionFilterProp="label"
              loading={datasets.isLoading}
            />
          </Form.Item>
          <Form.Item
            name="universe"
            label="股票池"
            extra="默认 csi300（已排除指数代码）；all = 全市场（含指数，IC 会被指数稀释）"
          >
            <Select options={universeOptions} />
          </Form.Item>
          <Form.Item name="range" label="计算区间（可选）" extra="默认数据集全区间">
            <DatePicker.RangePicker style={{ width: "100%" }} />
          </Form.Item>
        </Form>
      </Modal>
    </Space>
  );
}

export default function FactorDetailPage() {
  const { id } = useParams<{ id: string }>();
  return (
    <AppShell>
      <RequireAuth>
        <FactorDetailContent id={id} />
      </RequireAuth>
    </AppShell>
  );
}
