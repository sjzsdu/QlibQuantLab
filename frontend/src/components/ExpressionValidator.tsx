"use client";

/**
 * 因子表达式静态校验器（阶段 4）：调用 POST /v1/factors/validate，展示通过/失败反馈。
 * 只做词法/语法/白名单静态校验，不执行计算（真实求值属阶段 5）。
 */

import { useState } from "react";
import { Alert, App, Button, Space, Tag, Typography } from "antd";
import { CheckCircleOutlined, CloseCircleOutlined } from "@ant-design/icons";
import { useApiMutation, type ApiMutationInput } from "@/hooks/useApi";
import type { ExpressionCheck } from "@/lib/types";

const { Text } = Typography;

export function ExpressionValidator({ expression }: { expression: string }) {
  const { message } = App.useApp();
  const [result, setResult] = useState<ExpressionCheck | null>(null);
  const check = useApiMutation<ExpressionCheck, ApiMutationInput>();

  const run = async () => {
    try {
      const data = await check.mutateAsync({
        path: "/v1/factors/validate",
        body: { expression },
      });
      setResult(data);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "校验失败");
    }
  };

  return (
    <Space direction="vertical" size={6} style={{ width: "100%" }}>
      <Button size="small" onClick={() => void run()} loading={check.isPending}>
        校验表达式
      </Button>
      {result ? (
        result.valid ? (
          <Space size={4} wrap>
            <Tag icon={<CheckCircleOutlined />} color="success">
              校验通过
            </Tag>
            {result.fields.length ? (
              <Text type="secondary" style={{ fontSize: 12 }}>
                字段：{result.fields.join(", ")}
              </Text>
            ) : null}
            {result.functions.length ? (
              <Text type="secondary" style={{ fontSize: 12 }}>
                函数：{result.functions.join(", ")}
              </Text>
            ) : null}
          </Space>
        ) : (
          <Alert
            type="error"
            showIcon
            icon={<CloseCircleOutlined />}
            message="表达式校验未通过"
            description={
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {result.errors.map((error) => (
                  <li key={error}>{error}</li>
                ))}
              </ul>
            }
          />
        )
      ) : null}
    </Space>
  );
}
