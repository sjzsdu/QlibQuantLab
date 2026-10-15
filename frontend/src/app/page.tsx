"use client";

/**
 * 首页：平台入口
 * - 展示当前用户 / 组织
 * - 项目卡片入口（跳转项目管理、审计日志、合规文本）
 * - 风险提示与免责声明（常驻）
 * - 系统信息（仅客户端通过 TanStack Query 拉取，构建期不 fetch）
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Card, Col, Row, Space, Tag, Typography } from "antd";
import {
  FileSearchOutlined,
  FolderOpenOutlined,
  SafetyCertificateOutlined,
  SettingOutlined,
} from "@ant-design/icons";
import { AppShell } from "@/components/AppShell";
import { RequireAuth } from "@/components/RequireAuth";
import { useApiQuery } from "@/hooks/useApi";
import { useCurrentUser } from "@/hooks/useCurrentUser";
import type { SystemInfo } from "@/lib/types";

const { Title, Paragraph, Text } = Typography;

interface EntryCard {
  key: string;
  title: string;
  description: string;
  href: string;
  icon: React.ReactNode;
}

const ENTRIES: EntryCard[] = [
  {
    key: "projects",
    title: "项目管理",
    description: "创建与维护研究项目，管理项目成员与可见性。",
    href: "/projects",
    icon: <FolderOpenOutlined />,
  },
  {
    key: "audit",
    title: "审计日志",
    description: "查看登录、提交、变更等关键操作的审计记录。",
    href: "/audit",
    icon: <FileSearchOutlined />,
  },
  {
    key: "legal",
    title: "合规文本",
    description: "用户协议、风险提示书与免责声明（含版本与生效日期）。",
    href: "/legal/risk",
    icon: <SafetyCertificateOutlined />,
  },
];

function HomePageContent() {
  const { user } = useCurrentUser();
  const router = useRouter();

  const systemInfo = useApiQuery<SystemInfo>(
    ["system", "info"],
    "/v1/system/info",
    { retry: false },
  );

  return (
    <Space direction="vertical" size={24} style={{ display: "flex" }}>
      <div>
        <Title level={3} style={{ marginBottom: 4 }}>
          欢迎回来，{user?.display_name || user?.username}
        </Title>
        <Text type="secondary">
          {user?.org_name ? `当前组织：${user.org_name} · ` : ""}
          QlibQuantLab 量化研究平台 —— 数据、因子、模型与回测的一体化研究环境。
        </Text>
      </div>

      <Row gutter={[16, 16]}>
        {ENTRIES.map((entry) => (
          <Col key={entry.key} xs={24} sm={12} lg={8}>
            <Card
              hoverable
              title={
                <Space>
                  {entry.icon}
                  {entry.title}
                </Space>
              }
              onClick={() => router.push(entry.href)}
            >
              <Paragraph type="secondary" style={{ marginBottom: 8 }}>
                {entry.description}
              </Paragraph>
              <Link href={entry.href} onClick={(e) => e.stopPropagation()}>
                进入 {entry.title} →
              </Link>
            </Card>
          </Col>
        ))}
      </Row>

      <Card
        title={
          <Space>
            <SettingOutlined />
            系统信息
          </Space>
        }
        size="small"
      >
        {systemInfo.isLoading ? (
          <Text type="secondary">加载中…</Text>
        ) : systemInfo.isError ? (
          <Text type="secondary">
            暂时无法获取系统信息（后端服务可能未启动）。
          </Text>
        ) : (
          <Space direction="vertical" size={4}>
            {Object.entries(systemInfo.data ?? {})
              .filter(([, value]) =>
                ["string", "number", "boolean"].includes(typeof value),
              )
              .map(([key, value]) => (
                <Text key={key} type="secondary" style={{ fontSize: 13 }}>
                  {key}：<Text strong>{String(value)}</Text>
                </Text>
              ))}
          </Space>
        )}
      </Card>

      <Card
        title={
          <Space>
            <SafetyCertificateOutlined />
            风险提示与免责声明
          </Space>
        }
        style={{ borderColor: "#faad14" }}
      >
        <Space direction="vertical" size={8} style={{ display: "flex" }}>
          <Paragraph style={{ marginBottom: 0 }}>
            <Tag color="warning">风险提示</Tag>
            本平台仅用于量化研究、教学与演示，
            <Text strong>不提供任何投资建议，不保证任何策略收益</Text>
            ；历史回测表现不代表未来收益，市场有风险，投资决策及其后果由用户自行承担。
          </Paragraph>
          <Paragraph style={{ marginBottom: 0 }} type="secondary">
            使用本平台前请阅读：
            <Link href="/legal/terms" style={{ marginInlineStart: 8 }}>
              用户协议
            </Link>
            <Link href="/legal/risk" style={{ marginInlineStart: 12 }}>
              风险提示书
            </Link>
            <Link href="/legal/disclaimer" style={{ marginInlineStart: 12 }}>
              免责声明
            </Link>
          </Paragraph>
        </Space>
      </Card>
    </Space>
  );
}

export default function HomePage() {
  return (
    <RequireAuth>
      <AppShell>
        <HomePageContent />
      </AppShell>
    </RequireAuth>
  );
}
