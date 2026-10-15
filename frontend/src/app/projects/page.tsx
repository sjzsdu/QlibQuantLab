"use client";

/**
 * 项目管理：列表（服务端分页）+ 新建 / 编辑 / 删除（删除需二次确认 confirm=true）。
 * 权限：创建/编辑 = admin|researcher；删除 = admin。
 */

import { useState } from "react";
import {
  Alert,
  App,
  Button,
  Form,
  Input,
  Modal,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import { PlusOutlined, EditOutlined, DeleteOutlined } from "@ant-design/icons";
import { AppShell } from "@/components/AppShell";
import { RequireAuth } from "@/components/RequireAuth";
import { EmptyState } from "@/components/EmptyState";
import { useApiMutation, useApiQuery } from "@/hooks/useApi";
import { useCurrentUser } from "@/hooks/useCurrentUser";
import { buildQuery } from "@/lib/api";
import type {
  CreateProjectInput,
  DeleteResult,
  Paged,
  Project,
  UpdateProjectInput,
  Visibility,
} from "@/lib/types";
import dayjs from "dayjs";

const { Text } = Typography;

const VISIBILITY_META: Record<Visibility, { label: string; color: string }> = {
  private: { label: "私有", color: "default" },
  org: { label: "组织内", color: "blue" },
  public: { label: "公开", color: "green" },
};

type FormValues = { name: string; description?: string };

function ProjectsPageContent() {
  const { can } = useCurrentUser();
  const { message, modal } = App.useApp();

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Project | null>(null);
  const [form] = Form.useForm<FormValues>();

  const canWrite = can("admin", "researcher");
  const canDelete = can("admin");

  const listQuery = useApiQuery<Paged<Project>>(
    ["projects", page, pageSize],
    `/v1/projects${buildQuery({ page, page_size: pageSize })}`,
  );

  const createMutation = useApiMutation<Project, { path: string; body: CreateProjectInput }>();
  const updateMutation = useApiMutation<
    Project,
    { path: string; method: "PATCH"; body: UpdateProjectInput }
  >();
  const deleteMutation = useApiMutation<DeleteResult, { path: string; method: "DELETE" }>();

  const refresh = () => {
    void listQuery.refetch();
  };

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    setModalOpen(true);
  };

  const openEdit = (record: Project) => {
    setEditing(record);
    form.setFieldsValue({
      name: record.name,
      description: record.description ?? "",
    });
    setModalOpen(true);
  };

  const handleSubmit = async () => {
    const values = await form.validateFields();
    try {
      if (editing) {
        await updateMutation.mutateAsync({
          path: `/v1/projects/${editing.id}`,
          method: "PATCH",
          body: {
            name: values.name,
            description: values.description ?? "",
          },
        });
        message.success("项目已更新");
      } else {
        await createMutation.mutateAsync({
          path: "/v1/projects",
          body: {
            name: values.name,
            description: values.description || undefined,
          },
        });
        message.success("项目已创建");
      }
      setModalOpen(false);
      form.resetFields();
      refresh();
    } catch (e) {
      message.error(e instanceof Error ? e.message : "保存失败");
    }
  };

  const handleDelete = (record: Project) => {
    modal.confirm({
      title: `删除项目「${record.name}」？`,
      content: "删除后不可恢复，相关数据将不可访问。此操作会被记入审计日志。",
      okText: "确认删除",
      okButtonProps: { danger: true },
      cancelText: "取消",
      onOk: async () => {
        try {
          await deleteMutation.mutateAsync({
            path: `/v1/projects/${record.id}${buildQuery({ confirm: "true" })}`,
            method: "DELETE",
          });
          message.success("项目已删除");
          refresh();
        } catch (e) {
          message.error(e instanceof Error ? e.message : "删除失败");
        }
      },
    });
  };

  const columns = [
    {
      title: "项目名称",
      dataIndex: "name",
      key: "name",
      width: 220,
      render: (name: string, record: Project) => (
        <Space direction="vertical" size={0}>
          <Text strong>{name}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {record.description || "暂无描述"}
          </Text>
        </Space>
      ),
    },
    {
      title: "可见性",
      dataIndex: "visibility",
      key: "visibility",
      width: 100,
      render: (visibility: Visibility) => {
        const meta = VISIBILITY_META[visibility] ?? { label: visibility, color: "default" };
        return <Tag color={meta.color}>{meta.label}</Tag>;
      },
    },
    {
      title: "创建者",
      dataIndex: "created_by",
      key: "created_by",
      width: 160,
      render: (value: string) => <Text>{value || "-"}</Text>,
    },
    {
      title: "创建时间",
      dataIndex: "created_at",
      key: "created_at",
      width: 160,
      render: (value: string) =>
        value ? dayjs(value).format("YYYY-MM-DD HH:mm") : "-",
    },
    {
      title: "更新时间",
      dataIndex: "updated_at",
      key: "updated_at",
      width: 160,
      render: (value: string) =>
        value ? dayjs(value).format("YYYY-MM-DD HH:mm") : "-",
    },
    {
      title: "操作",
      key: "actions",
      width: 160,
      render: (_: unknown, record: Project) => (
        <Space size={4}>
          {canWrite ? (
            <Button
              type="link"
              size="small"
              icon={<EditOutlined />}
              onClick={() => openEdit(record)}
            >
              编辑
            </Button>
          ) : null}
          {canDelete ? (
            <Button
              type="link"
              size="small"
              danger
              icon={<DeleteOutlined />}
              onClick={() => handleDelete(record)}
            >
              删除
            </Button>
          ) : null}
          {!canWrite && !canDelete ? <Text type="secondary">-</Text> : null}
        </Space>
      ),
    },
  ];

  const totalPages = listQuery.data?.total ?? 0;
  const mutating =
    createMutation.isPending || updateMutation.isPending || deleteMutation.isPending;

  return (
    <Space direction="vertical" size={16} style={{ display: "flex", width: "100%" }}>
      <Space style={{ justifyContent: "space-between", width: "100%" }}>
        <div>
          <Typography.Title level={4} style={{ marginBottom: 0 }}>
            项目管理
          </Typography.Title>
          <Text type="secondary">按组织隔离的项目容器，承载数据集、因子、模型与回测。</Text>
        </div>
        {canWrite ? (
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            新建项目
          </Button>
        ) : null}
      </Space>

      {listQuery.isError ? (
        <Alert
          type="error"
          showIcon
          message="项目列表加载失败"
          description={
            listQuery.error instanceof Error
              ? listQuery.error.message
              : "请稍后重试"
          }
          action={
            <Button size="small" onClick={refresh}>
              重试
            </Button>
          }
        />
      ) : null}

      <div className="page-card">
        <Table<Project>
          rowKey="id"
          size="middle"
          loading={listQuery.isPending}
          columns={columns}
          dataSource={listQuery.data?.items ?? []}
          scroll={{ x: 900 }}
          locale={{
            emptyText: (
              <EmptyState
                title="还没有项目"
                description={
                  canWrite
                    ? "点击右上角「新建项目」创建你的第一个研究项目。"
                    : "当前组织下暂无项目，或你没有创建权限。"
                }
                action={
                  canWrite ? (
                    <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
                      新建项目
                    </Button>
                  ) : undefined
                }
              />
            ),
          }}
          pagination={{
            current: page,
            pageSize,
            total: totalPages,
            showSizeChanger: true,
            pageSizeOptions: [10, 20, 50, 100],
            showTotal: (total) => `共 ${total} 个项目`,
            onChange: (nextPage, nextPageSize) => {
              setPage(nextPage);
              setPageSize(nextPageSize);
            },
          }}
        />
      </div>

      <Modal
        open={modalOpen}
        title={editing ? "编辑项目" : "新建项目"}
        okText="保存"
        cancelText="取消"
        confirmLoading={mutating}
        onOk={() => void handleSubmit()}
        onCancel={() => {
          setModalOpen(false);
          form.resetFields();
        }}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item
            name="name"
            label="项目名称"
            rules={[
              { required: true, message: "请输入项目名称" },
              { max: 100, message: "项目名称不能超过 100 个字符" },
            ]}
          >
            <Input placeholder="例如：沪深 300 多因子研究" maxLength={100} />
          </Form.Item>
          <Form.Item name="description" label="项目描述">
            <Input.TextArea
              placeholder="选填：说明研究目标、数据范围等"
              rows={3}
              maxLength={500}
              showCount
            />
          </Form.Item>
        </Form>
      </Modal>
    </Space>
  );
}

export default function ProjectsPage() {
  return (
    <RequireAuth>
      <AppShell>
        <ProjectsPageContent />
      </AppShell>
    </RequireAuth>
  );
}
