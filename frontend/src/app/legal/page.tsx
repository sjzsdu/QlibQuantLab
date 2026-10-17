"use client";

/**
 * 合规文件索引（阶段 6 切片⑦）：由 `GET /v1/legal/meta` 驱动的文档列表。
 *
 * 后端 meta 是唯一事实源（标题/版本/生效日期）——前端不硬编码文档清单，
 * 新增文档时索引自动出现；页面同时给出风险提示摘要与打印页脚声明。
 */

import Link from "next/link";
import { Alert, Button, Card, Descriptions, Result, Space, Spin, Typography } from "antd";
import { SafetyCertificateOutlined } from "@ant-design/icons";
import { AppShell } from "@/components/AppShell";
import { useApiQuery } from "@/hooks/useApi";
import type { LegalMeta } from "@/lib/types";

const { Paragraph, Text } = Typography;

export default function LegalIndexPage() {
  const metaQuery = useApiQuery<LegalMeta[]>(["legal", "meta"], "/v1/legal/meta", {
    retry: false,
  });

  if (metaQuery.isPending) {
    return (
      <AppShell>
        <Card>
          <Spin tip="加载合规文件清单…" />
        </Card>
      </AppShell>
    );
  }

  if (metaQuery.isError || !Array.isArray(metaQuery.data)) {
    return (
      <AppShell>
        <Result
          status="error"
          title="合规文件清单加载失败"
          subTitle="请确认后端服务可用后重试。"
          extra={
            <Button type="primary" onClick={() => void metaQuery.refetch()}>
              重试
            </Button>
          }
        />
      </AppShell>
    );
  }

  return (
    <AppShell>
      <Space direction="vertical" size={16} style={{ display: "flex", width: "100%" }}>
        <Alert
          type="warning"
          showIcon
          icon={<SafetyCertificateOutlined />}
          message="风险提示"
          description={
            <Space direction="vertical" size={4}>
              <Text>
                本平台仅提供量化研究与回测工具，不构成任何投资建议；
                <Text strong>历史回测结果不代表未来收益</Text>
                ，策略在实盘前请充分评估风险并自行承担责任。
              </Text>
              <Text type="secondary">
                平台内所有结果页均携带数据范围、参数快照、成本假设与局限性四类标注；
                使用未获授权的数据源不被允许（数据授权台账强制）。
              </Text>
            </Space>
          }
        />
        {metaQuery.data.map((doc) => (
          <Card
            key={doc.code}
            title={
              <Space>
                <SafetyCertificateOutlined />
                {doc.title}
              </Space>
            }
            extra={
              <Link href={`/legal/${doc.code}`}>
                <Button>查看全文</Button>
              </Link>
            }
          >
            <Descriptions size="small" column={3}>
              <Descriptions.Item label="标识">{doc.code}</Descriptions.Item>
              <Descriptions.Item label="版本">{doc.version}</Descriptions.Item>
              <Descriptions.Item label="生效日期">{doc.effective_at}</Descriptions.Item>
            </Descriptions>
          </Card>
        ))}
        {/* 打印页脚（屏幕不显示）：出处 + 风险声明，与回测报告打印版同一套 print CSS */}
        <div className="print-only" style={{ marginTop: 24, borderTop: "1px solid #ccc", paddingTop: 8 }}>
          <Paragraph style={{ fontSize: 12, margin: 0 }}>
            QlibQuantLab 合规文件索引 · 打印件仅供存档，电子版以平台内最新版本为准。
          </Paragraph>
          <Paragraph style={{ fontSize: 12, margin: 0 }}>
            风险声明：历史回测不代表未来收益；本文件不构成投资建议。
          </Paragraph>
        </div>
      </Space>
    </AppShell>
  );
}
