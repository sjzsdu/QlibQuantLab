"use client";

/**
 * 回测详情（阶段 5）：净值曲线（ECharts ≤1500 点）+ 指标 + **四标注固定展示**：
 * 数据区间 data_range / 费用假设 cost_config / 局限说明 limitations / 数据来源授权 source。
 * 任务进行中每 2s 轮询，终态后拉取曲线。
 */

import { useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import dynamic from "next/dynamic";
import { useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Progress,
  Row,
  Space,
  Spin,
  Statistic,
  Table,
  Tag,
  Typography,
} from "antd";
import { ArrowLeftOutlined } from "@ant-design/icons";
import { AppShell } from "@/components/AppShell";
import { RequireAuth } from "@/components/RequireAuth";
import { useApiQuery } from "@/hooks/useApi";
import type { Backtest, BacktestCurve, Job, ResultSourceAnnotation } from "@/lib/types";
import dayjs from "dayjs";

const NavCurveChart = dynamic(() => import("@/components/NavCurveChart"), {
  ssr: false,
  loading: () => <Spin style={{ display: "block", margin: "48px auto" }} size="large" />,
});

const { Text, Paragraph } = Typography;

const JOB_STATUS_META: Record<string, { label: string; color: string }> = {
  queued: { label: "排队中", color: "default" },
  running: { label: "运行中", color: "blue" },
  succeeded: { label: "成功", color: "green" },
  failed: { label: "失败", color: "red" },
  canceled: { label: "已取消", color: "orange" },
};

const TERMINAL = new Set(["succeeded", "failed", "canceled"]);

function pct(value: number | undefined): string {
  return value === undefined ? "—" : `${(value * 100).toFixed(2)}%`;
}

function BacktestDetailContent({ id }: { id: string }) {
  const router = useRouter();
  const queryClient = useQueryClient();

  const backtest = useApiQuery<Backtest>(["backtest", id], `/v1/backtests/${id}`);

  const { data: job } = useApiQuery<Job>(
    ["backtest-job", backtest.data?.job_id],
    `/v1/jobs/${backtest.data?.job_id ?? ""}`,
    {
      enabled: !!backtest.data?.job_id,
      refetchInterval: (query) => {
        const status = query.state.data?.status;
        return status && TERMINAL.has(status) ? false : 2000;
      },
    },
  );

  const finished = !!backtest.data?.curve_uri || job?.status === "succeeded";

  // 任务终态后刷新回测行（worker 回写 metrics/data_range/limitations）
  useEffect(() => {
    if (job?.status && TERMINAL.has(job.status)) {
      void queryClient.invalidateQueries({ queryKey: ["backtest", id] });
      void queryClient.invalidateQueries({ queryKey: ["backtest-curve", id] });
      void queryClient.invalidateQueries({ queryKey: ["backtests"] });
    }
  }, [job?.status, id, queryClient]);

  const curve = useApiQuery<BacktestCurve>(
    ["backtest-curve", id],
    `/v1/backtests/${id}/curve`,
    { enabled: finished },
  );

  if (backtest.isLoading) {
    return <Spin style={{ display: "block", margin: "48px auto" }} size="large" />;
  }
  if (backtest.isError || !backtest.data) {
    return (
      <Alert type="error" showIcon message={backtest.error?.message ?? "回测加载失败"} />
    );
  }

  const row = backtest.data;
  const metrics = row.metrics ?? {};
  const range = row.data_range ?? {};
  const source = (range.source ?? {}) as ResultSourceAnnotation;
  const cost = row.cost_config ?? ({} as Backtest["cost_config"]);
  const jobActive = !!job && !TERMINAL.has(job.status);

  const costRows: [string, string][] = [
    ["佣金费率", String(cost.commission_rate ?? "—")],
    ["最低佣金", String(cost.min_commission ?? "—")],
    ["滑点类型", String(cost.slippage_type ?? "—")],
    ["滑点（基点）", String(cost.slippage_value ?? "—")],
    ["冲击成本（费率/成交额）", String(cost.impact_rate_per_million ?? "—")],
    ["结算费率", String(cost.settlement_fee_rate ?? "—")],
    ["印花税（卖出）", String(cost.stamp_duty_sell ?? "—")],
  ];

  const rangeColumns = [
    { title: "项", key: "k", render: (_: unknown, item: [string, string]) => item[0] },
    { title: "值", key: "v", render: (_: unknown, item: [string, string]) => item[1] },
  ];
  const rangeRows: [string, string][] = [
    ["数据区间", `${String(range.start ?? "—")} ~ ${String(range.end ?? "—")}`],
    ["频率 / 天数", `${String(range.freq ?? "day")} / ${String(range.n_days ?? "—")}`],
    ["引擎", String(range.engine ?? "—")],
    ["标的数", String(range.instruments ?? "—")],
    ["Top-K", String(range.topk ?? "—")],
    ["信号来源", range.signal_source === "model" ? "模型信号" : "规则信号（动量）"],
    ...(range.training_run_id
      ? ([["训练记录", String(range.training_run_id)]] as [string, string][])
      : []),
    ...(range.synthetic ? ([["数据性质", "合成（stub 对照）"]] as [string, string][]) : []),
  ];

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => router.push("/backtests")}>
        返回回测分析
      </Button>

      <Card
        title={
          <Space wrap>
            {row.strategy_name ?? row.strategy_id}
            <Tag color="geekblue">基准 {row.benchmark}</Tag>
            {row.job_status ? (
              <Tag color={JOB_STATUS_META[row.job_status]?.color}>
                {JOB_STATUS_META[row.job_status]?.label ?? row.job_status}
              </Tag>
            ) : null}
          </Space>
        }
        extra={
          row.job_id ? (
            <Button type="link" onClick={() => router.push(`/jobs/${row.job_id}`)}>
              查看任务日志
            </Button>
          ) : null
        }
      >
        <Descriptions column={{ xs: 1, sm: 2, lg: 4 }} size="small">
          <Descriptions.Item label="数据集">
            {row.dataset_name ?? row.dataset_id}
          </Descriptions.Item>
          <Descriptions.Item label="提交人">{row.created_by}</Descriptions.Item>
          <Descriptions.Item label="提交时间">
            {dayjs(row.created_at).format("YYYY-MM-DD HH:mm:ss")}
          </Descriptions.Item>
          <Descriptions.Item label="回测区间">
            {row.start_date && row.end_date
              ? `${row.start_date} ~ ${row.end_date}`
              : "数据集全区间"}
          </Descriptions.Item>
        </Descriptions>
        {job && jobActive ? (
          <div style={{ marginTop: 12 }}>
            <Space size={12} wrap>
              <Tag color={JOB_STATUS_META[job.status]?.color}>
                {JOB_STATUS_META[job.status]?.label ?? job.status}
              </Tag>
              <Progress
                percent={job.progress}
                size="small"
                style={{ width: 220 }}
                status={job.status === "failed" ? "exception" : undefined}
              />
              <Text type="secondary" style={{ fontSize: 13 }}>
                任务 {job.id.slice(0, 8)}
              </Text>
            </Space>
          </div>
        ) : null}
        {job?.error ? (
          <Alert style={{ marginTop: 8 }} type="error" showIcon message={job.error} />
        ) : null}
      </Card>

      {finished ? (
        <>
          <Row gutter={[12, 12]}>
            <Col xs={12} sm={8} md={4}>
              <Card size="small">
                <Statistic
                  title="总收益"
                  value={pct(metrics.total_return as number | undefined)}
                  valueStyle={{
                    color:
                      typeof metrics.total_return === "number" && metrics.total_return < 0
                        ? "#cf1322"
                        : "#3f8600",
                  }}
                />
              </Card>
            </Col>
            <Col xs={12} sm={8} md={4}>
              <Card size="small">
                <Statistic title="夏普" value={metrics.sharpe ?? "—"} precision={2} />
              </Card>
            </Col>
            <Col xs={12} sm={8} md={4}>
              <Card size="small">
                <Statistic title="最大回撤" value={pct(metrics.max_drawdown as number | undefined)} />
              </Card>
            </Col>
            <Col xs={12} sm={8} md={4}>
              <Card size="small">
                <Statistic title="年化收益" value={pct(metrics.annualized_return as number | undefined)} />
              </Card>
            </Col>
            <Col xs={12} sm={8} md={4}>
              <Card size="small">
                <Statistic title="交易次数" value={metrics.trade_count ?? "—"} />
              </Card>
            </Col>
            <Col xs={12} sm={8} md={4}>
              <Card size="small">
                <Statistic
                  title="信号来源"
                  value={range.signal_source === "model" ? "模型" : "规则"}
                />
              </Card>
            </Col>
          </Row>

          <Card
            title="净值曲线"
            size="small"
            extra={
              curve.data?.downsampled ? (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {curve.data.total} 点降采样展示
                </Text>
              ) : null
            }
          >
            {curve.isLoading ? (
              <Spin />
            ) : curve.isError ? (
              <Alert type="warning" showIcon message={curve.error.message} />
            ) : curve.data && curve.data.points.length > 0 ? (
              <NavCurveChart
                points={curve.data.points.map(([date, nav]) => ({ date, nav }))}
              />
            ) : (
              <Alert type="warning" showIcon message="净值曲线为空" />
            )}
            <Paragraph type="secondary" style={{ fontSize: 12, marginTop: 8, marginBottom: 0 }}>
              历史回测不代表未来收益；曲线基于固定费用模型估算，未含融资融券与涨跌停约束。
            </Paragraph>
          </Card>

          <Card title="四标注：结果说明" size="small">
            <Descriptions column={{ xs: 1, sm: 2 }} size="small" bordered>
              <Descriptions.Item label="① 数据区间">
                {String(range.start ?? "—")} ~ {String(range.end ?? "—")}（{String(range.freq ?? "day")}，{" "}
                {String(range.n_days ?? "—")} 交易日，引擎 {String(range.engine ?? "—")}）
              </Descriptions.Item>
              <Descriptions.Item label="② 数据来源 / 授权">
                {source.vendor ? `${source.vendor} · ` : ""}
                {source.dataset_name ? `${source.dataset_name} · ` : ""}
                {source.license_ref ? <Text code>{source.license_ref}</Text> : "—"}
                {source.allowed_use ? `（${source.allowed_use}）` : ""}
              </Descriptions.Item>
            </Descriptions>

            <Typography.Title level={5} style={{ marginTop: 16 }}>
              ③ 费用假设（100% 透传）
            </Typography.Title>
            <Table
              rowKey={(item) => item[0]}
              size="small"
              pagination={false}
              dataSource={costRows}
              columns={rangeColumns}
            />

            <Typography.Title level={5} style={{ marginTop: 16 }}>
              数据区间明细
            </Typography.Title>
            <Table
              rowKey={(item) => item[0]}
              size="small"
              pagination={false}
              dataSource={rangeRows}
              columns={rangeColumns}
            />

            <Typography.Title level={5} style={{ marginTop: 16 }}>
              ④ 局限说明
            </Typography.Title>
            <Alert
              type="warning"
              showIcon
              message={row.limitations || "（未提供）"}
              style={{ whiteSpace: "pre-wrap" }}
            />
          </Card>
        </>
      ) : row.job_status === "failed" || row.job_status === "canceled" ? (
        <Alert
          type="error"
          showIcon
          message={`回测任务${row.job_status === "failed" ? "失败" : "已取消"}，无结果可展示`}
          description="可在任务中心查看错误日志并重试。"
        />
      ) : (
        <Card size="small">
          <Space direction="vertical" size={8}>
            <Spin />
            <Text type="secondary">回测排队/运行中，完成后自动展示曲线与四标注…</Text>
          </Space>
        </Card>
      )}
    </Space>
  );
}

export default function BacktestDetailPage() {
  const { id } = useParams<{ id: string }>();
  return (
    <AppShell>
      <RequireAuth>
        <BacktestDetailContent id={id} />
      </RequireAuth>
    </AppShell>
  );
}
