"use client";

/**
 * 项目详情：基本信息 + 成员管理（添加须为本组织用户）+ 可见性切换（二次确认）。
 * 权限：成员管理 = project.member.manage（staff）；可见性 = project.visibility（admin）。
 */

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  App,
  Button,
  Card,
  Form,
  Input,
  Popconfirm,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
} from "antd";
import { ArrowLeftOutlined, PlusOutlined } from "@ant-design/icons";
import { AppShell } from "@/components/AppShell";
import { RequireAuth } from "@/components/RequireAuth";
import { useApiMutation, useApiQuery, type ApiMutationInput } from "@/hooks/useApi";
import { useCurrentUser } from "@/hooks/useCurrentUser";
import type { Project, ProjectMember, Visibility } from "@/lib/types";
import { ROLE_LABELS, type Role } from "@/lib/types";
import dayjs from "dayjs";

const { Text } = Typography;

const VISIBILITY_META: Record<Visibility, { label: string; color: string; desc: string }> = {
  private: { label: "私有", color: "default", desc: "仅项目成员可见" },
  org: { label: "组织内", color: "blue", desc: "组织内所有成员可见" },
  public: { label: "公开", color: "green", desc: "公开可见（对外发布，会写审计日志）" },
};

/** 项目内可授予的角色 */
const PROJECT_ROLES: { value: string; label: string }[] = [
  { value: "viewer", label: ROLE_LABELS.viewer },
  { value: "researcher", label: ROLE_LABELS.researcher },
  { value: "admin", label: ROLE_LABELS.admin },
];

interface MembersResponse {
  items: ProjectMember[];
  total: number;
}

type MemberFormValues = { username: string; role: string };

function ProjectDetailPageContent() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { message, modal } = App.useApp();
  const { hasPermission } = useCurrentUser();
  const [memberForm] = Form.useForm<MemberFormValues>();
  const [pendingVisibility, setPendingVisibility] = useState<Visibility | null>(null);

  const { data: project, isLoading } = useApiQuery<Project>(
    ["project", id],
    `/v1/projects/${id}`,
  );
  const { data: members, refetch: refetchMembers } = useApiQuery<MembersResponse>(
    ["project-members", id],
    `/v1/projects/${id}/members`,
  );

  const addMember = useApiMutation<unknown, ApiMutationInput>();
  const removeMember = useApiMutation<unknown, ApiMutationInput>();
  const changeVisibility = useApiMutation<unknown, ApiMutationInput>();

  const onAddMember = async (values: MemberFormValues) => {
    try {
      await addMember.mutateAsync({
        path: `/v1/projects/${id}/members`,
        body: values,
      });
      message.success("成员已添加");
      memberForm.resetFields();
      void refetchMembers();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "添加失败");
    }
  };

  const onRemoveMember = async (userId: string) => {
    try {
      await removeMember.mutateAsync({
        path: `/v1/projects/${id}/members/${userId}?confirm=true`,
        method: "DELETE",
      });
      message.success("成员已移除");
      void refetchMembers();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "移除失败");
    }
  };

  const onApplyVisibility = async () => {
    if (!pendingVisibility) return;
    try {
      await changeVisibility.mutateAsync({
        path: `/v1/projects/${id}/visibility?confirm=true`,
        method: "POST",
        body: { visibility: pendingVisibility },
      });
      message.success("可见性已更新");
      router.refresh();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "更新失败");
    } finally {
      setPendingVisibility(null);
    }
  };

  const confirmVisibility = (next: Visibility) => {
    if (next === project?.visibility) return;
    setPendingVisibility(next);
    modal.confirm({
      title: "确认切换项目可见性？",
      content: (
        <Space direction="vertical" size={4}>
          <Text>
            {VISIBILITY_META[project?.visibility ?? "private"].label} →{" "}
            <Text strong>{VISIBILITY_META[next].label}</Text>
          </Text>
          <Text type="secondary">{VISIBILITY_META[next].desc}</Text>
          <Text type="secondary">该操作会写入审计日志。</Text>
        </Space>
      ),
      okText: "确认切换",
      cancelText: "取消",
      onOk: () => void onApplyVisibility(),
      onCancel: () => setPendingVisibility(null),
    });
  };

  const columns = [
    {
      title: "用户名",
      dataIndex: "username",
      render: (name: string, row: ProjectMember) => (
        <Space>
          <Text strong>{name}</Text>
          {row.role === "owner" ? <Tag color="gold">创建者</Tag> : null}
        </Space>
      ),
    },
    {
      title: "项目角色",
      dataIndex: "role",
      render: (role: string) => (
        <Tag color={role === "admin" ? "volcano" : role === "researcher" ? "blue" : "default"}>
          {ROLE_LABELS[role as Role] ?? role}
        </Tag>
      ),
    },
    {
      title: "加入时间",
      dataIndex: "added_at",
      render: (value: string | null) =>
        value ? dayjs(value).format("YYYY-MM-DD HH:mm") : "—",
    },
    {
      title: "操作",
      key: "actions",
      render: (_: unknown, row: ProjectMember) =>
        hasPermission("project.member.manage") && row.role !== "owner" ? (
          <Popconfirm
            title={`确认移除成员 ${row.username}？`}
            okText="移除"
            cancelText="取消"
            onConfirm={() => void onRemoveMember(row.user_id)}
          >
            <Button danger size="small">
              移除
            </Button>
          </Popconfirm>
        ) : null,
    },
  ];

  return (
    <AppShell>
      <RequireAuth>
        <Space direction="vertical" size={16} style={{ width: "100%" }}>
          <Button
            type="text"
            icon={<ArrowLeftOutlined />}
            onClick={() => router.push("/projects")}
          >
            返回项目列表
          </Button>

          {isLoading || !project ? (
            <Spin style={{ display: "block", margin: "48px auto" }} size="large" />
          ) : (
            <>
              <Card title="项目信息">
                <Space direction="vertical" size={4}>
                  <Typography.Title level={4} style={{ margin: 0 }}>
                    {project.name}
                  </Typography.Title>
                  <Text type="secondary">{project.description || "（无描述）"}</Text>
                  <Text type="secondary" style={{ fontSize: 13 }}>
                    创建者 {project.created_by} ·{" "}
                    {dayjs(project.created_at).format("YYYY-MM-DD HH:mm")}
                  </Text>
                </Space>
              </Card>

              <Card
                title="可见性"
                extra={
                  hasPermission("project.visibility") ? (
                    <Text type="secondary" style={{ fontSize: 13 }}>
                      切换需二次确认并写审计日志
                    </Text>
                  ) : null
                }
              >
                <Space size={8} wrap>
                  {(Object.keys(VISIBILITY_META) as Visibility[]).map((value) => {
                    const meta = VISIBILITY_META[value];
                    const active = project.visibility === value;
                    return (
                      <Button
                        key={value}
                        disabled={!hasPermission("project.visibility")}
                        type={active ? "primary" : "default"}
                        onClick={() => confirmVisibility(value)}
                      >
                        {meta.label}
                        {active ? "（当前）" : ""}
                      </Button>
                    );
                  })}
                </Space>
                <div style={{ marginTop: 8 }}>
                  <Text type="secondary" style={{ fontSize: 13 }}>
                    {VISIBILITY_META[project.visibility].desc}
                  </Text>
                </div>
              </Card>

              <Card
                title="项目成员"
                extra={
                  <Text type="secondary" style={{ fontSize: 13 }}>
                    {members?.total ?? 0} 人
                  </Text>
                }
              >
                {hasPermission("project.member.manage") ? (
                  <Form
                    form={memberForm}
                    layout="inline"
                    onFinish={(values) => void onAddMember(values)}
                    style={{ marginBottom: 16 }}
                  >
                    <Form.Item
                      name="username"
                      rules={[{ required: true, message: "输入组织内用户名" }]}
                    >
                      <Input placeholder="用户名（须为本组织成员）" style={{ width: 240 }} />
                    </Form.Item>
                    <Form.Item name="role" initialValue="viewer">
                      <Select options={PROJECT_ROLES} style={{ width: 120 }} />
                    </Form.Item>
                    <Form.Item>
                      <Button type="primary" htmlType="submit" icon={<PlusOutlined />}>
                        添加成员
                      </Button>
                    </Form.Item>
                  </Form>
                ) : null}
                <Table<ProjectMember>
                  rowKey="user_id"
                  size="small"
                  pagination={false}
                  dataSource={members?.items ?? []}
                  columns={columns}
                />
              </Card>
            </>
          )}
        </Space>
      </RequireAuth>
    </AppShell>
  );
}

export default function ProjectDetailPage() {
  return <ProjectDetailPageContent />;
}
