"use client";

import { useMemo, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import {
  App,
  Avatar,
  Button,
  Layout,
  Menu,
  Popconfirm,
  Space,
  Tag,
  Typography,
} from "antd";
import {
  AimOutlined,
  DashboardOutlined,
  DatabaseOutlined,
  ExperimentOutlined,
  FileSearchOutlined,
  FolderOpenOutlined,
  LineChartOutlined,
  LogoutOutlined,
  OrderedListOutlined,
  RobotOutlined,
  SafetyCertificateOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { useCurrentUser } from "@/hooks/useCurrentUser";
import { ROLE_LABELS, type Role } from "@/lib/types";

const { Header, Sider, Content } = Layout;

interface AppShellProps {
  children: React.ReactNode;
}

/** 角色中文标签颜色 */
const ROLE_COLORS: Record<string, string> = {
  admin: "volcano",
  researcher: "blue",
  viewer: "default",
  auditor: "purple",
};

const LEGAL_KEYS = ["/legal", "/legal/terms", "/legal/risk", "/legal/disclaimer"];

/** 全站布局：侧边栏菜单 + 顶栏（当前用户 / 组织 / 角色 / 登出） */
export function AppShell({ children }: AppShellProps) {
  const { user, logout } = useCurrentUser();
  const router = useRouter();
  const pathname = usePathname();
  const { message } = App.useApp();
  const [openKeys, setOpenKeys] = useState<string[]>(
    LEGAL_KEYS.includes(pathname) ? ["legal-group"] : [],
  );

  const menuItems = useMemo(
    () => [
      { key: "/", icon: <DashboardOutlined />, label: "首页" },
      { key: "/projects", icon: <FolderOpenOutlined />, label: "项目管理" },
      { key: "/data", icon: <DatabaseOutlined />, label: "数据管理" },
      { key: "/factors", icon: <ExperimentOutlined />, label: "因子库" },
      { key: "/models", icon: <RobotOutlined />, label: "模型训练" },
      { key: "/strategies", icon: <AimOutlined />, label: "策略管理" },
      { key: "/backtests", icon: <LineChartOutlined />, label: "回测分析" },
      { key: "/jobs", icon: <OrderedListOutlined />, label: "任务中心" },
      { key: "/audit", icon: <FileSearchOutlined />, label: "审计日志" },
      {
        key: "legal-group",
        icon: <SafetyCertificateOutlined />,
        label: "合规文本",
        type: "group" as const,
        children: [
          { key: "/legal", label: "全部文件" },
          { key: "/legal/terms", label: "用户协议" },
          { key: "/legal/risk", label: "风险提示" },
          { key: "/legal/disclaimer", label: "免责声明" },
        ],
      },
    ],
    [],
  );

  /** 选中高亮：子路由（/data/datasets/{id}）回退到父菜单项 */
  const selectedKeys = useMemo(() => {
    if (pathname === "/") return ["/"];
    const parents = ["/projects", "/data", "/factors", "/models", "/strategies", "/backtests", "/jobs", "/audit"];
    const hit = parents.find((k) => pathname === k || pathname.startsWith(`${k}/`));
    return [hit ?? pathname];
  }, [pathname]);

  const handleLogout = async () => {
    try {
      await logout();
    } catch {
      message.error("登出失败，请重试");
    }
  };

  const roles = (user?.roles ?? []) as Role[];

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Sider
        breakpoint="lg"
        collapsedWidth={0}
        theme="light"
        width={220}
        className="app-sider"
        style={{ borderRight: "1px solid #f0f0f0" }}
      >
        <div
          style={{
            height: 56,
            display: "flex",
            alignItems: "center",
            paddingInline: 20,
            borderBottom: "1px solid #f0f0f0",
            fontWeight: 600,
            whiteSpace: "nowrap",
          }}
        >
          QlibQuantLab
        </div>
        <Menu
          mode="inline"
          items={menuItems}
          selectedKeys={selectedKeys}
          openKeys={openKeys}
          onOpenChange={setOpenKeys}
          onClick={({ key }) => {
            if (key !== pathname) router.push(key);
          }}
          style={{ borderInlineEnd: "none" }}
        />
      </Sider>

      <Layout>
        <Header
          className="app-header"
          style={{
            background: "#fff",
            paddingInline: 24,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            flexWrap: "wrap",
            borderBottom: "1px solid #f0f0f0",
            height: "auto",
            minHeight: 56,
            lineHeight: "56px",
          }}
        >
          <Typography.Title level={5} style={{ margin: 0 }}>
            量化研究平台
          </Typography.Title>

          <Space size={8} wrap>
            {user?.org_name ? <Tag color="geekblue">{user.org_name}</Tag> : null}
            {roles.map((role) => (
              <Tag key={role} color={ROLE_COLORS[role] ?? "default"}>
                {ROLE_LABELS[role] ?? role}
              </Tag>
            ))}
            <Avatar size="small" icon={<UserOutlined />} />
            <Typography.Text>
              {user?.display_name || user?.username}
              {user ? (
                <Typography.Text type="secondary" style={{ marginLeft: 8 }}>
                  {user.user_id} @ {user.org_id}
                </Typography.Text>
              ) : null}
            </Typography.Text>
            <Popconfirm
              title="确认退出登录？"
              okText="退出"
              cancelText="取消"
              onConfirm={() => void handleLogout()}
            >
              <Button danger size="small" icon={<LogoutOutlined />}>
                登出
              </Button>
            </Popconfirm>
          </Space>
        </Header>

        <Content
          style={{ padding: 24, maxWidth: 1280, width: "100%", margin: "0 auto" }}
        >
          {children}
        </Content>
      </Layout>
    </Layout>
  );
}
