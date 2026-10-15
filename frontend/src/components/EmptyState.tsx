"use client";

import type { ReactNode } from "react";
import { Button, Empty, Space, Typography } from "antd";

interface EmptyStateProps {
  title?: string;
  description?: string;
  /** 操作区（如「新建」按钮） */
  action?: ReactNode;
}

/** 统一的友好空态 */
export function EmptyState({
  title = "暂无数据",
  description,
  action,
}: EmptyStateProps) {
  return (
    <Space direction="vertical" align="center" size={8} style={{ padding: "32px 0" }}>
      <Empty description={false} image={Empty.PRESENTED_IMAGE_SIMPLE} />
      <Typography.Text strong>{title}</Typography.Text>
      {description ? (
        <Typography.Text type="secondary" style={{ fontSize: 13 }}>
          {description}
        </Typography.Text>
      ) : null}
      {action}
    </Space>
  );
}

/** 便捷的「空列表 + 新建入口」组合 */
export function EmptyAction({
  label,
  onClick,
}: {
  label: string;
  onClick: () => void;
}) {
  return (
    <Button type="primary" onClick={onClick}>
      {label}
    </Button>
  );
}
