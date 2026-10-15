"use client";

/**
 * 审计日志：支持按 action / actor 筛选 + 分页。
 * 后端契约：GET /api/v1/audit-logs?action=&actor=&page=&page_size=
 */

import { useState } from "react";
import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import { SearchOutlined, ReloadOutlined } from "@ant-design/icons";
import { AppShell } from "@/components/AppShell";
import { RequireAuth } from "@/components/RequireAuth";
import { EmptyState } from "@/components/EmptyState";
import { useApiQuery } from "@/hooks/useApi";
import { buildQuery } from "@/lib/api";
import type { AuditLog, Paged } from "@/lib/types";
import dayjs from "dayjs";

const { Text } = Typography;

interface Filters {
  action: string;
  actor: string;
}

const OUTCOME_META: Record<string, { label: string; color: string }> = {
  success: { label: "成功", color: "green" },
  succeeded: { label: "成功", color: "green" },
  failure: { label: "失败", color: "red" },
  failed: { label: "失败", color: "red" },
  denied: { label: "拒绝", color: "orange" },
  error: { label: "错误", color: "red" },
};

function AuditPageContent() {
  const [filters, setFilters] = useState<Filters>({ action: "", actor: "" });
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [form] = Form.useForm<Filters>();

  const query = useApiQuery<Paged<AuditLog>>(
    ["audit-logs", filters.action, filters.actor, page, pageSize],
    `/v1/audit-logs${buildQuery({
      action: filters.action,
      actor: filters.actor,
      page,
      page_size: pageSize,
    })}`,
  );

  const handleSearch = (values: Filters) => {
    setPage(1);
    setFilters({
      action: (values.action ?? "").trim(),
      actor: (values.actor ?? "").trim(),
    });
  };

  const handleReset = () => {
    form.resetFields();
    setPage(1);
    setFilters({ action: "", actor: "" });
  };

  const columns = [
    {
      title: "时间",
      dataIndex: "created_at",
      key: "created_at",
      width: 165,
      render: (value: string) =>
        value ? dayjs(value).format("YYYY-MM-DD HH:mm:ss") : "-",
    },
    {
      title: "动作",
      dataIndex: "action",
      key: "action",
      width: 180,
      render: (value: string) => <Tag color="blue">{value}</Tag>,
    },
    {
      title: "结果",
      dataIndex: "outcome",
      key: "outcome",
      width: 90,
      render: (value: string) => {
        const meta = OUTCOME_META[value] ?? { label: value, color: "default" };
        return <Tag color={meta.color}>{meta.label}</Tag>;
      },
    },
    {
      title: "操作人",
      dataIndex: "actor_username",
      key: "actor_username",
      width: 130,
      render: (value: string | null) => value || "-",
    },
    {
      title: "资源",
      key: "resource",
      width: 220,
      render: (_: unknown, record: AuditLog) => (
        <Space direction="vertical" size={0}>
          <Text>{record.resource_type || "-"}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {record.resource_id || "-"}
          </Text>
        </Space>
      ),
    },
    {
      title: "详情",
      dataIndex: "detail",
      key: "detail",
      ellipsis: true,
      render: (value: string | null) =>
        value ? (
          <Text type="secondary" style={{ fontSize: 12 }} title={value}>
            {value}
          </Text>
        ) : (
          "-"
        ),
    },
    {
      title: "IP",
      dataIndex: "ip",
      key: "ip",
      width: 130,
      render: (value: string | null) => value || "-",
    },
    {
      title: "请求 ID",
      dataIndex: "request_id",
      key: "request_id",
      width: 200,
      render: (value: string | null) =>
        value ? (
          <Text copyable={{ text: value }} style={{ fontSize: 12 }}>
            {value}
          </Text>
        ) : (
          "-"
        ),
    },
  ];

  return (
    <Space direction="vertical" size={16} style={{ display: "flex", width: "100%" }}>
      <div>
        <Typography.Title level={4} style={{ marginBottom: 0 }}>
          审计日志
        </Typography.Title>
        <Text type="secondary">
          登录、提交、变更等关键操作的不可变审计记录（仅管理员与审计员可见）。
        </Text>
      </div>

      <Card size="small">
        <Form
          form={form}
          layout="inline"
          onFinish={handleSearch}
          style={{ rowGap: 12, width: "100%" }}
        >
          <Form.Item name="action" label="动作">
            <Input
              placeholder="如 project.create"
              allowClear
              style={{ width: 220 }}
              onPressEnter={() => form.submit()}
            />
          </Form.Item>
          <Form.Item name="actor" label="操作人">
            <Input
              placeholder="用户名"
              allowClear
              style={{ width: 180 }}
              onPressEnter={() => form.submit()}
            />
          </Form.Item>
          <Form.Item>
            <Space>
              <Button type="primary" icon={<SearchOutlined />} htmlType="submit">
                查询
              </Button>
              <Button icon={<ReloadOutlined />} onClick={handleReset}>
                重置
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Card>

      {query.isError ? (
        <Alert
          type="error"
          showIcon
          message="审计日志加载失败"
          description={query.error instanceof Error ? query.error.message : "请稍后重试"}
          action={
            <Button size="small" onClick={() => void query.refetch()}>
              重试
            </Button>
          }
        />
      ) : null}

      <div className="page-card">
        <Table<AuditLog>
          rowKey="id"
          size="middle"
          loading={query.isPending}
          columns={columns}
          dataSource={query.data?.items ?? []}
          scroll={{ x: 1100 }}
          locale={{
            emptyText: (
              <EmptyState
                title="暂无审计记录"
                description="调整筛选条件，或在平台内执行操作后在此查看记录。"
              />
            ),
          }}
          pagination={{
            current: page,
            pageSize,
            total: query.data?.total ?? 0,
            showSizeChanger: true,
            pageSizeOptions: [20, 50, 100],
            showTotal: (total) => `共 ${total} 条记录`,
            onChange: (nextPage, nextPageSize) => {
              setPage(nextPage);
              setPageSize(nextPageSize);
            },
          }}
        />
      </div>
    </Space>
  );
}

export default function AuditPage() {
  return (
    <RequireAuth>
      <AppShell>
        <AuditPageContent />
      </AppShell>
    </RequireAuth>
  );
}
