"use client";

/**
 * 合规文本页：用户协议 / 风险提示 / 免责声明。
 * 后端返回 Markdown 字符串，由自研轻量渲染器（lib/markdown.ts）转义后渲染，
 * 不引入任何重型 markdown 依赖。
 */

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { Alert, Button, Card, Result, Space, Spin, Tabs, Typography } from "antd";
import { AppShell } from "@/components/AppShell";
import { useApiQuery } from "@/hooks/useApi";
import { renderMarkdown } from "@/lib/markdown";
import type { LegalCode, LegalDocument } from "@/lib/types";

const { Text } = Typography;

const VALID_CODES: LegalCode[] = ["terms", "risk", "disclaimer"];

const TAB_ITEMS = [
  { key: "terms", label: "用户协议" },
  { key: "risk", label: "风险提示" },
  { key: "disclaimer", label: "免责声明" },
];

export default function LegalPage() {
  const params = useParams<{ code: string }>();
  const router = useRouter();
  const code = params?.code ?? "";
  const valid = VALID_CODES.includes(code as LegalCode);

  const docQuery = useApiQuery<LegalDocument>(
    ["legal", code],
    `/v1/legal/${code}`,
    { enabled: valid, retry: false },
  );

  if (!valid) {
    return (
      <AppShell>
        <Result
          status="404"
          title="文档不存在"
          subTitle="仅支持用户协议（terms）、风险提示（risk）、免责声明（disclaimer）。"
          extra={
            <Link href="/">
              <Button type="primary">返回首页</Button>
            </Link>
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
          items={TAB_ITEMS}
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
          </Card>
        )}
      </Space>
    </AppShell>
  );
}
