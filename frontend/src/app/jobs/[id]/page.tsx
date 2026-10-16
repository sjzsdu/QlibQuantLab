"use client";

/**
 * 任务详情（阶段 5）：2s 增量日志轮询（GET /jobs/{id}/logs?since_seq=N）+
 * 取消（queued 直接取消 / running 协作式）+ 重试（复制 payload 重新入队）。
 *
 * 轮询约定：next_seq 单调推进，客户端累积日志；终态（响应内 status）自动停止。
 */

import { useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Descriptions,
  Popconfirm,
  Progress,
  Space,
  Spin,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import { ArrowLeftOutlined, ReloadOutlined, StopOutlined, RedoOutlined } from "@ant-design/icons";
import { AppShell } from "@/components/AppShell";
import { RequireAuth } from "@/components/RequireAuth";
import { useApiMutation, useApiQuery, type ApiMutationInput } from "@/hooks/useApi";
import { useCurrentUser } from "@/hooks/useCurrentUser";
import { buildQuery } from "@/lib/api";
import type { Job, JobAction, JobLog, JobLogs, JobStatus } from "@/lib/types";
import dayjs from "dayjs";

const { Text, Paragraph } = Typography;

const JOB_STATUS_META: Record<JobStatus, { label: string; color: string }> = {
  queued: { label: "排队中", color: "default" },
  running: { label: "运行中", color: "blue" },
  succeeded: { label: "成功", color: "green" },
  failed: { label: "失败", color: "red" },
  canceled: { label: "已取消", color: "orange" },
};

const TERMINAL = new Set<JobStatus>(["succeeded", "failed", "canceled"]);

function JobDetailContent({ id }: { id: string }) {
  const { message } = App.useApp();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { hasPermission } = useCurrentUser();
  const canControl = hasPermission("job.control");

  const [logs, setLogs] = useState<JobLog[]>([]);
  const [nextSeq, setNextSeq] = useState(0);
  const logsBoxRef = useRef<HTMLDivElement | null>(null);

  const job = useApiQuery<Job>(["job", id], `/v1/jobs/${id}`, {
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && TERMINAL.has(status) ? false : 2000;
    },
  });

  // 增量日志：since_seq 推进式拉取（2s；响应内 status 终态即停）
  const logsQuery = useApiQuery<JobLogs>(
    ["job-logs", id, nextSeq],
    `/v1/jobs/${id}/logs${buildQuery({ since_seq: nextSeq, limit: 200 })}`,
    {
      refetchInterval: (query) => {
        const status = query.state.data?.status;
        return status && TERMINAL.has(status) ? false : 2000;
      },
    },
  );

  useEffect(() => {
    const data = logsQuery.data;
    if (data && data.items.length > 0 && data.next_seq > nextSeq) {
      setLogs((prev) => [...prev, ...data.items]);
      setNextSeq(data.next_seq);
    }
  }, [logsQuery.data, nextSeq]);

  // 新日志滚动到底
  useEffect(() => {
    const el = logsBoxRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [logs.length]);

  const cancelJob = useApiMutation<JobAction, ApiMutationInput>();
  const retryJob = useApiMutation<JobAction, ApiMutationInput>();

  const onCancel = async () => {
    try {
      const result = await cancelJob.mutateAsync({ path: `/v1/jobs/${id}/cancel` });
      if (result.status === "canceled") {
        message.success("任务已取消");
      } else {
        message.info("已置取消标记：任务将在下一个进度检查点停止");
      }
      void queryClient.invalidateQueries({ queryKey: ["job", id] });
      void queryClient.invalidateQueries({ queryKey: ["job-logs", id] });
      void queryClient.invalidateQueries({ queryKey: ["jobs"] });
    } catch (error) {
      message.error(error instanceof Error ? error.message : "取消失败");
    }
  };

  const onRetry = async () => {
    try {
      const result = await retryJob.mutateAsync({ path: `/v1/jobs/${id}/retry` });
      message.success("已复制 payload 重新入队");
      router.push(`/jobs/${result.id}`);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "重试失败");
    }
  };

  if (job.isLoading) {
    return <Spin style={{ display: "block", margin: "48px auto" }} size="large" />;
  }
  if (job.isError || !job.data) {
    return <Alert type="error" showIcon message={job.error?.message ?? "任务加载失败"} />;
  }

  const row = job.data;
  const status = row.status;
  const meta = JOB_STATUS_META[status];
  const canCancel = !TERMINAL.has(status);
  const canRetry = status === "failed" || status === "canceled";

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Space style={{ width: "100%", justifyContent: "space-between" }} wrap>
        <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => router.push("/jobs")}>
          返回任务中心
        </Button>
        <Space>
          <Tooltip title="重新拉取状态与日志">
            <Button
              icon={<ReloadOutlined />}
              onClick={() => {
                void job.refetch();
                void logsQuery.refetch();
              }}
            />
          </Tooltip>
          {canControl && canCancel ? (
            <Popconfirm
              title="取消该任务？"
              description="排队中任务立即取消；运行中任务将在下一个进度检查点停止。"
              okText="确认取消"
              cancelText="再想想"
              onConfirm={() => void onCancel()}
            >
              <Button danger icon={<StopOutlined />} loading={cancelJob.isPending}>
                取消任务
              </Button>
            </Popconfirm>
          ) : null}
          {canControl && canRetry ? (
            <Button
              type="primary"
              icon={<RedoOutlined />}
              loading={retryJob.isPending}
              onClick={() => void onRetry()}
            >
              重试任务
            </Button>
          ) : null}
        </Space>
      </Space>

      <Card
        title={
          <Space wrap>
            任务 {row.id.slice(0, 8)}
            <Tag color={meta?.color ?? "default"}>{meta?.label ?? status}</Tag>
          </Space>
        }
      >
        <Descriptions column={{ xs: 1, sm: 2, lg: 3 }} size="small">
          <Descriptions.Item label="类型">{row.kind}</Descriptions.Item>
          <Descriptions.Item label="提交人">{row.requested_by || "—"}</Descriptions.Item>
          <Descriptions.Item label="尝试">
            {row.attempts}/{row.max_attempts}
          </Descriptions.Item>
          <Descriptions.Item label="入队时间">
            {row.queued_at ? dayjs(row.queued_at).format("YYYY-MM-DD HH:mm:ss") : "—"}
          </Descriptions.Item>
          <Descriptions.Item label="开始时间">
            {row.started_at ? dayjs(row.started_at).format("YYYY-MM-DD HH:mm:ss") : "—"}
          </Descriptions.Item>
          <Descriptions.Item label="结束时间">
            {row.finished_at ? dayjs(row.finished_at).format("YYYY-MM-DD HH:mm:ss") : "—"}
          </Descriptions.Item>
        </Descriptions>
        <div style={{ marginTop: 12 }}>
          <Space size={12} wrap>
            <Progress
              percent={row.progress}
              size="small"
              style={{ width: 260 }}
              status={status === "failed" ? "exception" : undefined}
            />
            <Text type="secondary" style={{ fontSize: 13 }}>
              每 2 秒增量拉取日志（since_seq={nextSeq}）
            </Text>
          </Space>
        </div>
        {row.error ? (
          <Alert style={{ marginTop: 12 }} type="error" showIcon message={row.error} />
        ) : null}
        <Paragraph style={{ marginTop: 12, marginBottom: 0 }}>
          <Text strong>任务 payload：</Text>
          <pre
            style={{
              marginTop: 6,
              padding: 12,
              background: "#fafafa",
              border: "1px solid #f0f0f0",
              borderRadius: 6,
              fontSize: 12,
              maxHeight: 220,
              overflow: "auto",
            }}
          >
            {JSON.stringify(row.payload, null, 2)}
          </pre>
        </Paragraph>
      </Card>

      <Card
        title={`执行日志（${logs.length} 条）`}
        size="small"
        extra={
          logsQuery.isFetching ? (
            <Text type="secondary" style={{ fontSize: 12 }}>
              轮询中…
            </Text>
          ) : (
            <Text type="secondary" style={{ fontSize: 12 }}>
              {TERMINAL.has(status) ? "任务已结束" : "等待新日志"}
            </Text>
          )
        }
      >
        {logsQuery.isError ? (
          <Alert
            type="error"
            showIcon
            message={logsQuery.error.message}
            style={{ marginBottom: 8 }}
          />
        ) : null}
        <div
          ref={logsBoxRef}
          style={{
            maxHeight: 480,
            overflowY: "auto",
            fontFamily: "monospace",
            fontSize: 12,
            lineHeight: 1.7,
            background: "#0f172a",
            color: "#e2e8f0",
            padding: 12,
            borderRadius: 6,
          }}
        >
          {logs.length === 0 ? (
            <Text style={{ color: "#94a3b8" }}>
              {logsQuery.isLoading ? "加载中…" : "暂无日志（任务排队中或尚未产生输出）"}
            </Text>
          ) : (
            logs.map((log) => (
              <div key={log.seq} style={{ display: "flex", gap: 12 }}>
                <span style={{ color: "#64748b", flexShrink: 0 }}>
                  [{String(log.seq).padStart(3, "0")}]{" "}
                  {dayjs(log.created_at).format("HH:mm:ss")}
                </span>
                <span
                  style={{
                    color:
                      log.level === "error"
                        ? "#f87171"
                        : log.level === "warn"
                          ? "#fbbf24"
                          : "#e2e8f0",
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-all",
                  }}
                >
                  {log.message}
                </span>
              </div>
            ))
          )}
        </div>
      </Card>
    </Space>
  );
}

export default function JobDetailPage() {
  const { id } = useParams<{ id: string }>();
  return (
    <AppShell>
      <RequireAuth>
        <JobDetailContent id={id} />
      </RequireAuth>
    </AppShell>
  );
}
