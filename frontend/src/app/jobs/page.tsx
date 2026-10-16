"use client";

/**
 * 任务中心（阶段 5）：全部异步任务列表（kind/status 过滤），行内进度与终态。
 * 控制操作（取消/重试）在详情页。
 */

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Progress, Select, Space, Table, Tag, Tooltip, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import { AppShell } from "@/components/AppShell";
import { RequireAuth } from "@/components/RequireAuth";
import { useApiQuery } from "@/hooks/useApi";
import { buildQuery } from "@/lib/api";
import type { Job, JobStatus, Paged } from "@/lib/types";
import dayjs from "dayjs";

const { Text } = Typography;

const JOB_STATUS_META: Record<JobStatus, { label: string; color: string }> = {
  queued: { label: "排队中", color: "default" },
  running: { label: "运行中", color: "blue" },
  succeeded: { label: "成功", color: "green" },
  failed: { label: "失败", color: "red" },
  canceled: { label: "已取消", color: "orange" },
};

const JOB_KIND_META: Record<string, string> = {
  dataset_import: "数据导入",
  train: "模型训练",
  backtest: "回测",
  factor_compute: "因子计算",
  export: "导出",
};

const TERMINAL = new Set<JobStatus>(["succeeded", "failed", "canceled"]);

function JobsPageContent() {
  const router = useRouter();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [kind, setKind] = useState<string | undefined>();
  const [status, setStatus] = useState<JobStatus | undefined>();

  const jobs = useApiQuery<Paged<Job>>(
    ["jobs", page, pageSize, kind, status],
    `/v1/jobs${buildQuery({ page, page_size: pageSize, kind, status })}`,
    { refetchInterval: 3000 }, // 列表轻轮询：有活跃任务时保持新鲜
  );

  const columns: ColumnsType<Job> = [
    {
      title: "任务",
      key: "id",
      render: (_: unknown, row: Job) => (
        <Tooltip title={row.id}>
          <Text
            style={{ cursor: "pointer", color: "#1677ff" }}
            onClick={() => router.push(`/jobs/${row.id}`)}
          >
            {row.id.slice(0, 8)}
          </Text>
        </Tooltip>
      ),
    },
    {
      title: "类型",
      dataIndex: "kind",
      width: 110,
      render: (v: string) => JOB_KIND_META[v] ?? v,
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 100,
      render: (v: JobStatus) => {
        const meta = JOB_STATUS_META[v];
        return <Tag color={meta?.color ?? "default"}>{meta?.label ?? v}</Tag>;
      },
    },
    {
      title: "进度",
      dataIndex: "progress",
      width: 140,
      render: (v: number, row: Job) => (
        <Progress
          percent={v}
          size="small"
          status={
            row.status === "failed"
              ? "exception"
              : TERMINAL.has(row.status) && row.status !== "succeeded"
                ? "normal"
                : row.status === "succeeded"
                  ? "success"
                  : undefined
          }
        />
      ),
    },
    {
      title: "尝试",
      key: "attempts",
      width: 70,
      render: (_: unknown, row: Job) => `${row.attempts}/${row.max_attempts}`,
    },
    {
      title: "提交人",
      dataIndex: "requested_by",
      width: 110,
      render: (v: string) => v || "—",
    },
    {
      title: "入队时间",
      dataIndex: "queued_at",
      width: 160,
      render: (v: string | null) => (v ? dayjs(v).format("MM-DD HH:mm:ss") : "—"),
    },
    {
      title: "结束时间",
      dataIndex: "finished_at",
      width: 160,
      render: (v: string | null) => (v ? dayjs(v).format("MM-DD HH:mm:ss") : "—"),
    },
    {
      title: "错误",
      dataIndex: "error",
      render: (v: string | null) =>
        v ? (
          <Text type="danger" style={{ maxWidth: 260 }} ellipsis={{ tooltip: v }}>
            {v}
          </Text>
        ) : (
          "—"
        ),
    },
  ];

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Space style={{ width: "100%", justifyContent: "space-between" }} wrap>
        <Typography.Title level={4} style={{ margin: 0 }}>
          任务中心
        </Typography.Title>
        <Space>
          <Select
            allowClear
            placeholder="类型"
            style={{ width: 130 }}
            size="small"
            value={kind}
            onChange={(value) => {
              setKind(value);
              setPage(1);
            }}
            options={Object.entries(JOB_KIND_META).map(([value, label]) => ({ value, label }))}
          />
          <Typography.Text type="secondary" style={{ fontSize: 13 }}>
            状态：
          </Typography.Text>
          <Space size={4} wrap>
            {(["queued", "running", "succeeded", "failed", "canceled"] as JobStatus[]).map(
              (value) => (
                <Tag.CheckableTag
                  key={value}
                  checked={status === value}
                  onChange={(checked) => {
                    setStatus(checked ? value : undefined);
                    setPage(1);
                  }}
                >
                  {JOB_STATUS_META[value].label}
                </Tag.CheckableTag>
              ),
            )}
          </Space>
        </Space>
      </Space>

      <Table<Job>
        rowKey="id"
        size="small"
        loading={jobs.isLoading}
        dataSource={jobs.data?.items ?? []}
        onRow={(row) => ({ onClick: () => router.push(`/jobs/${row.id}`), style: { cursor: "pointer" } })}
        pagination={{
          current: page,
          pageSize,
          total: jobs.data?.total ?? 0,
          showSizeChanger: true,
          onChange: (p, ps) => {
            setPage(p);
            setPageSize(ps);
          },
        }}
        columns={columns}
      />
    </Space>
  );
}

export default function JobsPage() {
  return (
    <AppShell>
      <RequireAuth>
        <JobsPageContent />
      </RequireAuth>
    </AppShell>
  );
}
