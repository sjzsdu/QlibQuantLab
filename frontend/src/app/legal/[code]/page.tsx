"use client";

/**
 * 合规文本页：用户协议 / 风险提示 / 免责声明（阶段 6 切片⑦）。
 * 后端返回 Markdown 字符串，由自研轻量渲染器（lib/markdown.ts）转义后渲染，
 * 不引入任何重型 markdown 依赖。
 *
 * 文档清单由 `GET /v1/legal/meta` 驱动（tab 项 / 合法性校验都来自 meta，
 * 不在前端硬编码）；「打印」为纯客户端 window.print()（无服务端 PDF），
 * 打印件由 print CSS 隐藏操作按钮并补上风险声明页脚（.print-only）。
 */

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { Alert, Button, Card, Result, Space, Spin, Tabs, Typography } from "antd";
import { PrinterOutlined } from "@ant-design/icons";
import { AppShell } from "@/components/AppShell";
import { useApiQuery } from "@/hooks/useApi";
import { renderMarkdown } from "@/lib/markdown";
import type { LegalDocument, LegalMeta } from "@/lib/types";

const { Paragraph, Text } = Typography;

export default function LegalPage() {
  const params = useParams<{ code: string }>();
  const router = useRouter();
  const code = params?.code ?? "";

  const metaQuery = useApiQuery<LegalMeta[]>(["legal", "meta"], "/v1/legal/meta", {
    retry: false,
  });
  const docs = Array.isArray(metaQuery.data) ? metaQuery.data : [];
  const valid = metaQuery.isSuccess && docs.some((m) => m.code === code);

  const docQuery = useApiQuery<LegalDocument>(
    ["legal", code],
    `/v1/legal/${code}`,
    { enabled: valid, retry: false },
  );

  if (metaQuery.isPending) {
    return (
      <AppShell>
        <Card>
          <Spin tip="加载合规文件清单…" />
        </Card>
      </AppShell>
    );
  }

  if (metaQuery.isError) {
    return (
      <AppShell>
        <Alert
          type="error"
          showIcon
          message="合规文件清单加载失败"
          description="请确认后端服务可用后重试。"
          action={
            <Button size="small" onClick={() => void metaQuery.refetch()}>
              重试
            </Button>
          }
        />
      </AppShell>
    );
  }

  if (!valid) {
    return (
      <AppShell>
        <Result
          status="404"
          title="文档不存在"
          subTitle={
            docs.length > 0
              ? `当前可用文档：${docs.map((m) => `${m.title}（${m.code}）`).join("、")}。`
              : "当前后端未提供任何合规文档。"
          }
          extra={
            <Space>
              <Link href="/legal">
                <Button>合规文件索引</Button>
              </Link>
              <Link href="/">
                <Button type="primary">返回首页</Button>
              </Link>
            </Space>
          }
        />
      </AppShell>
    );
  }

  return (
    <AppShell>
      <Space direction="vertical" size={16} style={{ display: "flex", width: "100%" }}>
        <Tabs
          activeKey={code}
          onChange={(key) => router.push(`/legal/${key}`)}
          items={docs.map((m) => ({ key: m.code, label: m.title }))}
        />

        {docQuery.isPending ? (
          <Card>
            <Spin />
          </Card>
        ) : docQuery.isError ? (
          <Alert
            type="error"
            showIcon
            message="文档加载失败"
            description={
              docQuery.error instanceof Error ? docQuery.error.message : "请稍后重试"
            }
            action={
              <Button size="small" onClick={() => void docQuery.refetch()}>
                重试
              </Button>
            }
          />
        ) : (
          <Card
            title={docQuery.data?.title ?? "文档"}
            extra={
              <Space size={12} wrap>
                <Text type="secondary">版本 {docQuery.data?.version ?? "-"}</Text>
                <Text type="secondary">
                  生效日期 {docQuery.data?.effective_at ?? "-"}
                </Text>
                <Button
                  className="no-print"
                  icon={<PrinterOutlined />}
                  onClick={() => window.print()}
                >
                  打印
                </Button>
              </Space>
            }
          >
            <div
              className="markdown-body"
              // 内容来自后端 Markdown，先经 renderMarkdown 整体转义再做有限替换，无 XSS 风险
              dangerouslySetInnerHTML={{
                __html: renderMarkdown(docQuery.data?.content ?? ""),
              }}
            />
            <Alert
              type="warning"
              showIcon
              style={{ marginTop: 24 }}
              message="风险提示"
              description="本平台不提供任何投资建议，不保证任何策略收益，投资风险由用户自行承担。"
            />
            {/* 打印页脚（屏幕不显示）：文档出处 + 风险声明 */}
            <div
              className="print-only"
              style={{ marginTop: 24, borderTop: "1px solid #ccc", paddingTop: 8 }}
            >
              <Paragraph style={{ fontSize: 12, margin: 0 }}>
                {docQuery.data?.title ?? "合规文档"}（{docQuery.data?.code ?? code}）·
                版本 {docQuery.data?.version ?? "-"} · 生效日期{" "}
                {docQuery.data?.effective_at ?? "-"} · QlibQuantLab 平台内电子版为准。
              </Paragraph>
              <Paragraph style={{ fontSize: 12, margin: 0 }}>
                风险声明：历史回测不代表未来收益；本文件不构成投资建议。
              </Paragraph>
            </div>
          </Card>
        )}
      </Space>
    </AppShell>
  );
}
