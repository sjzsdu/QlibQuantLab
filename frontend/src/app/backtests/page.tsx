"use client";

/**
 * 回测分析（阶段 5）：提交回测（费用三件套必填，100% 透传）+ 列表。
 * 模型信号策略提交前需已有成功训练（后端 409 前置拦截，前端透传错误）。
 */

import { useMemo, useState } from "react";
import {
  App,
  Button,
  DatePicker,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import { PlusOutlined } from "@ant-design/icons";
import { useRouter } from "next/navigation";
import type { Dayjs } from "dayjs";
import dayjs from "dayjs";
import { AppShell } from "@/components/AppShell";
import { RequireAuth } from "@/components/RequireAuth";
import { useApiMutation, useApiQuery, type ApiMutationInput } from "@/hooks/useApi";
import { useCurrentUser } from "@/hooks/useCurrentUser";
import { buildQuery } from "@/lib/api";
import type { Backtest, Dataset, Paged, Strategy } from "@/lib/types";

const { Paragraph } = Typography;

const JOB_STATUS_META: Record<string, { label: string; color: string }> = {
  queued: { label: "排队中", color: "default" },
  running: { label: "运行中", color: "blue" },
  succeeded: { label: "成功", color: "green" },
  failed: { label: "失败", color: "red" },
  canceled: { label: "已取消", color: "orange" },
};

type BacktestFormValues = {
  strategy_id: string;
  dataset_id: string;
  benchmark?: string;
  range?: [Dayjs, Dayjs];
  topk?: number;
  commission_rate: number;
  slippage_value: number;
  impact_rate_per_million: number;
};

function BacktestsPageContent() {
  const { message } = App.useApp();
  const router = useRouter();
  const { hasPermission } = useCurrentUser();
  const canSubmit = hasPermission("backtest.submit");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [modalOpen, setModalOpen] = useState(false);
  const [form] = Form.useForm<BacktestFormValues>();

  const backtests = useApiQuery<Paged<Backtest>>(
    ["backtests", page, pageSize],
    `/v1/backtests${buildQuery({ page, page_size: pageSize })}`,
  );
  const strategies = useApiQuery<Paged<Strategy>>(
    ["backtest-strategy-options"],
    `/v1/strategies${buildQuery({ page_size: 200 })}`,
  );
  const datasets = useApiQuery<Paged<Dataset>>(
    ["backtest-dataset-options"],
    `/v1/datasets${buildQuery({ page_size: 200 })}`,
  );
  const submitBacktest = useApiMutation<Backtest, ApiMutationInput>();

  const strategyOptions = useMemo(
    () =>
      (strategies.data?.items ?? []).map((s) => ({
        value: s.id,
        label: `${s.name}（${s.signal_source === "model" ? `模型 ${s.model_name ?? s.model_id}` : "规则"}）`,
      })),
    [strategies.data],
  );
  const datasetOptions = useMemo(
    () =>
      (datasets.data?.items ?? [])
        .filter((d) => d.start_date)
        .map((d) => ({
          value: d.id,
          label: `${d.name}（${d.start_date} ~ ${d.end_date}）`,
        })),
    [datasets.data],
  );

  const onSubmit = async (values: BacktestFormValues) => {
    try {
      const row = await submitBacktest.mutateAsync({
        path: "/v1/backtests",
        body: {
          strategy_id: values.strategy_id,
          dataset_id: values.dataset_id,
          benchmark: values.benchmark || "SH000300",
          start_date: values.range?.[0]?.format("YYYY-MM-DD"),
          end_date: values.range?.[1]?.format("YYYY-MM-DD"),
          topk: values.topk ?? 50,
          cost_config: {
            commission_rate: values.commission_rate,
            slippage_value: values.slippage_value,
            impact_rate_per_million: values.impact_rate_per_million,
          },
        },
      });
      message.success("回测任务已入队");
      setModalOpen(false);
      form.resetFields();
      router.push(`/backtests/${row.id}`);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "提交失败");
    }
  };

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Space style={{ width: "100%", justifyContent: "space-between" }} wrap>
        <Typography.Title level={4} style={{ margin: 0 }}>
          回测分析
        </Typography.Title>
        {canSubmit ? (
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => {
              form.resetFields();
              form.setFieldsValue({ benchmark: "SH000300", topk: 50 });
              setModalOpen(true);
            }}
          >
            提交回测
          </Button>
        ) : null}
      </Space>

      <Table<Backtest>
        rowKey="id"
        size="small"
        loading={backtests.isLoading}
        dataSource={backtests.data?.items ?? []}
        pagination={{
          current: page,
          pageSize,
          total: backtests.data?.total ?? 0,
          showSizeChanger: true,
          onChange: (p, ps) => {
            setPage(p);
            setPageSize(ps);
          },
        }}
        columns={[
          {
            title: "策略",
            dataIndex: "strategy_name",
            render: (v: string | null, row: Backtest) => (
              <Button type="link" size="small" onClick={() => router.push(`/backtests/${row.id}`)}>
                {v ?? row.strategy_id}
              </Button>
            ),
          },
          { title: "数据集", dataIndex: "dataset_name", render: (v: string | null) => v ?? "—" },
          {
            title: "信号源",
            key: "signal_source",
            width: 100,
            render: (_: unknown, row: Backtest) => {
              const source = row.data_range.signal_source ?? (row.params.signal_source as string);
              return source === "model" ? (
                <Tag color="purple">模型</Tag>
              ) : (
                <Tag color="blue">规则</Tag>
              );
            },
          },
          {
            title: "任务状态",
            dataIndex: "job_status",
            width: 100,
            render: (v: string | null) => {
              const meta = v ? JOB_STATUS_META[v] : undefined;
              return <Tag color={meta?.color ?? "default"}>{meta?.label ?? v ?? "—"}</Tag>;
            },
          },
          {
            title: "总收益",
            key: "total_return",
            width: 100,
            render: (_: unknown, row: Backtest) =>
              typeof row.metrics.total_return === "number"
                ? `${(row.metrics.total_return * 100).toFixed(2)}%`
                : "—",
          },
          {
            title: "夏普",
            key: "sharpe",
            width: 80,
            render: (_: unknown, row: Backtest) =>
              typeof row.metrics.sharpe === "number" ? row.metrics.sharpe.toFixed(2) : "—",
          },
          {
            title: "最大回撤",
            key: "max_drawdown",
            width: 100,
            render: (_: unknown, row: Backtest) =>
              typeof row.metrics.max_drawdown === "number"
                ? `${(row.metrics.max_drawdown * 100).toFixed(2)}%`
                : "—",
          },
          { title: "创建人", dataIndex: "created_by", width: 100 },
          {
            title: "提交时间",
            dataIndex: "created_at",
            width: 150,
            render: (v: string) => dayjs(v).format("YYYY-MM-DD HH:mm"),
          },
        ]}
      />

      <Modal
        title="提交回测"
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => void form.submit()}
        okButtonProps={{ loading: submitBacktest.isPending }}
        width={680}
        destroyOnClose
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={{ benchmark: "SH000300", topk: 50 }}
          onFinish={(v) => void onSubmit(v)}
        >
          <Form.Item
            name="strategy_id"
            label="策略"
            rules={[{ required: true, message: "请选择策略" }]}
          >
            <Select
              placeholder="选择策略"
              options={strategyOptions}
              loading={strategies.isLoading}
              showSearch
              optionFilterProp="label"
            />
          </Form.Item>
          <Form.Item
            name="dataset_id"
            label="数据集"
            rules={[{ required: true, message: "请选择数据集" }]}
          >
            <Select
              placeholder="选择已导入的数据集"
              options={datasetOptions}
              loading={datasets.isLoading}
              showSearch
              optionFilterProp="label"
            />
          </Form.Item>
          <Space size={16} wrap>
            <Form.Item name="benchmark" label="基准">
              <Input style={{ width: 160 }} maxLength={32} />
            </Form.Item>
            <Form.Item name="range" label="回测区间（可空 = 数据集全区间）">
              <DatePicker.RangePicker />
            </Form.Item>
            <Form.Item name="topk" label="持仓数 Top-K">
              <InputNumber min={1} max={500} style={{ width: 140 }} />
            </Form.Item>
          </Space>
          <Typography.Text strong>费用假设（三件套必填，100% 透传进模拟器）</Typography.Text>
          <Space size={16} wrap style={{ marginTop: 8 }}>
            <Form.Item
              name="commission_rate"
              label="佣金费率"
              rules={[{ required: true, message: "必填" }]}
              extra="如 0.0003 = 万三"
            >
              <InputNumber min={0} max={0.5} step={0.0001} style={{ width: 160 }} />
            </Form.Item>
            <Form.Item
              name="slippage_value"
              label="滑点（基点 bp）"
              rules={[{ required: true, message: "必填" }]}
            >
              <InputNumber min={0} max={1000} style={{ width: 160 }} />
            </Form.Item>
            <Form.Item
              name="impact_rate_per_million"
              label="冲击成本（费率/成交额）"
              rules={[{ required: true, message: "必填" }]}
              extra="如 0.0001 = 万一分之一"
            >
              <InputNumber min={0} max={1} step={0.0001} style={{ width: 200 }} />
            </Form.Item>
          </Space>
          <Paragraph type="secondary" style={{ fontSize: 12, marginTop: 8, marginBottom: 0 }}>
            历史回测不代表未来收益；结果页固定展示数据区间 / 费用口径 / 局限说明与数据来源授权。
          </Paragraph>
        </Form>
      </Modal>
    </Space>
  );
}

export default function BacktestsPage() {
  return (
    <AppShell>
      <RequireAuth>
        <BacktestsPageContent />
      </RequireAuth>
    </AppShell>
  );
}
