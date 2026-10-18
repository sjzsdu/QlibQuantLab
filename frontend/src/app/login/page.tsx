"use client";

/**
 * 登录页：按后端 auth_provider 自适应（阶段 7 · D7-10）。
 * - mock（阶段 1-6 默认）：开发环境一键进入 + 身份选择器（UI 与阶段 6 逐像素一致）；
 * - casdoor：中性「统一身份认证」文案 + 「登录」按钮 —— 生产环境不露开发入口。
 * 流程不变：GET /api/v1/auth/login → 拿到 { url } → window.location.href 跳转完成登录。
 * 页面常驻风险提示。
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Alert,
  Button,
  Card,
  Divider,
  Flex,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
} from "antd";
import { LoginOutlined, HomeOutlined, SafetyCertificateOutlined } from "@ant-design/icons";
import { apiFetch } from "@/lib/api";
import { useCurrentUser } from "@/hooks/useCurrentUser";
import {
  ROLE_LABELS,
  type LoginResponse,
  type Role,
  type SystemInfo,
} from "@/lib/types";

const { Title, Paragraph, Text } = Typography;

/** Mock 身份选项（与后端 MockAuthProvider 的 profile 参数对应） */
const PROFILE_OPTIONS = [
  { value: "admin", label: "admin · 管理员（全部权限）" },
  { value: "researcher", label: "researcher · 研究员（读写，不能删除/改配置）" },
  { value: "viewer", label: "viewer · 访客（只读）" },
  { value: "auditor", label: "auditor · 审计员（只读 + 审计日志）" },
];

export default function LoginPage() {
  const { user, isLoading, logout } = useCurrentUser();
  const [profile, setProfile] = useState("admin");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 默认 mock：dev 下零闪变（与阶段 6 逐像素一致）；取到非 mock 再切中性登录。
  // 拿不到 /system/info 时维持现状 —— 后端不可达时登录链路本身也不可用。
  const [authProvider, setAuthProvider] = useState("mock");

  useEffect(() => {
    let alive = true;
    apiFetch<SystemInfo>("/v1/system/info")
      .then((info) => {
        if (alive && info?.auth_provider) {
          setAuthProvider(info.auth_provider);
        }
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, []);

  const isMock = authProvider === "mock";

  const handleLogin = async () => {
    setSubmitting(true);
    setError(null);
    try {
      // 记住来路，登录后由后端 redirect_to 参数带回
      const params = new URLSearchParams(
        typeof window !== "undefined" ? window.location.search : "",
      );
      const next = params.get("next") ?? "/";
      const suffix =
        next && next !== "/" ? `?redirect_to=${encodeURIComponent(next)}` : "";

      const data = await apiFetch<LoginResponse>(`/v1/auth/login${suffix}`);
      if (!data?.url) {
        throw new Error("登录接口未返回跳转地址");
      }

      let target = data.url;
      // 仅 Mock 登录地址支持切换 profile；OIDC 登录地址不做任何篡改
      if (profile !== "admin" && target.startsWith("/api/v1/auth/mock/enter")) {
        const url = new URL(target, window.location.origin);
        url.searchParams.set("profile", profile);
        target = `${url.pathname}${url.search}`;
      }
      window.location.href = target;
    } catch (e) {
      setError(e instanceof Error ? e.message : "登录失败，请稍后重试");
      setSubmitting(false);
    }
  };

  return (
    <Flex
      align="center"
      justify="center"
      style={{ minHeight: "calc(100vh - 40px)", padding: "32px 16px" }}
    >
      <Card style={{ width: "100%", maxWidth: 560 }}>
        <Space direction="vertical" size={16} style={{ display: "flex", width: "100%" }}>
          <div>
            <Title level={3} style={{ marginBottom: 4 }}>
              登录 QlibQuantLab
            </Title>
            <Text type="secondary">量化研究平台 · 数据 / 因子 / 模型 / 回测</Text>
          </div>

          <Alert
            type="warning"
            showIcon
            icon={<SafetyCertificateOutlined />}
            message="风险提示"
            description={
              <span>
                本平台不提供任何投资建议，不保证任何策略收益，投资风险由用户自行承担。
                详见 <Link href="/legal/disclaimer">免责声明</Link> 与{" "}
                <Link href="/legal/risk">风险提示书</Link>。
              </span>
            }
          />

          {isLoading ? (
            <Flex justify="center" style={{ padding: "24px 0" }}>
              <Spin size="large" />
            </Flex>
          ) : user ? (
            <Card size="small" title="当前已登录">
              <Space direction="vertical" size={8} style={{ display: "flex" }}>
                <Text>
                  用户：
                  <Text strong>{user.display_name || user.username}</Text>
                </Text>
                {user.org_name ? <Text>组织：{user.org_name}</Text> : null}
                <Space size={4}>
                  角色：
                  {(user.roles ?? []).map((role: Role) => (
                    <Tag key={role}>{ROLE_LABELS[role] ?? role}</Tag>
                  ))}
                </Space>
                <Space>
                  <Link href="/">
                    <Button icon={<HomeOutlined />}>返回首页</Button>
                  </Link>
                  <Button danger onClick={() => void logout()}>
                    退出登录
                  </Button>
                </Space>
              </Space>
            </Card>
          ) : (
            <>
              {isMock ? (
                <div>
                  <Paragraph style={{ marginBottom: 8 }}>
                    <Text strong>开发环境一键进入：</Text>
                    <Text type="secondary">
                      当前使用 MockAuthProvider，无需账号密码，选择身份后直接进入平台。
                    </Text>
                  </Paragraph>
                  <Select
                    aria-label="选择 Mock 身份"
                    style={{ width: "100%" }}
                    value={profile}
                    onChange={setProfile}
                    options={PROFILE_OPTIONS}
                  />
                </div>
              ) : (
                <div>
                  <Paragraph style={{ marginBottom: 0 }}>
                    <Text strong>统一身份认证登录：</Text>
                    <Text type="secondary">
                      将跳转至组织身份认证页面，完成登录后自动返回平台。
                    </Text>
                  </Paragraph>
                </div>
              )}

              {error ? (
                <Alert type="error" showIcon message={error} />
              ) : null}

              <Button
                type="primary"
                size="large"
                block
                icon={<LoginOutlined />}
                loading={submitting}
                onClick={() => void handleLogin()}
              >
                {isMock ? "一键进入平台" : "登录"}
              </Button>

              <Divider plain style={{ margin: "8px 0" }}>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  说明
                </Text>
              </Divider>
              <Paragraph type="secondary" style={{ fontSize: 13, marginBottom: 0 }}>
                会话由后端签发的 HttpOnly Cookie（qqlab_session）维护，
                浏览器脚本不可读取；写操作通过双提交 Cookie（qqlab_csrf）进行 CSRF 校验。
                {isMock
                  ? "正式环境将切换为 Casdoor OIDC 登录，前端无需改动。"
                  : "由 Casdoor OIDC 完成身份认证，平台会话由后端独立签发。"}
              </Paragraph>
              <Paragraph style={{ fontSize: 13, marginBottom: 0 }}>
                <Link href="/legal/terms">用户协议</Link>
                <span style={{ marginInline: 8 }}>·</span>
                <Link href="/legal/risk">风险提示</Link>
                <span style={{ marginInline: 8 }}>·</span>
                <Link href="/legal/disclaimer">免责声明</Link>
              </Paragraph>
            </>
          )}
        </Space>
      </Card>
    </Flex>
  );
}
