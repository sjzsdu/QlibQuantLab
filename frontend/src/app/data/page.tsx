"use client";

/**
 * 数据管理（阶段 4）：三个 Tab —— 数据源 / 授权台账 / 数据集。
 *
 * 合规链在 UI 上的体现：没有有效授权台账就不能创建数据集（数据集表单只列出
 * status=active 的台账）；台账创建/吊销仅 admin（data.license.manage）。
 */

import { useMemo, useState } from "react";
import {
  App,
  Button,
  DatePicker,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import { PlusOutlined } from "@ant-design/icons";
import { useRouter } from "next/navigation";
import type { Dayjs } from "dayjs";
import dayjs from "dayjs";
import { AppShell } from "@/components/AppShell";
import { RequireAuth } from "@/components/RequireAuth";
import { useApiMutation, useApiQuery, type ApiMutationInput } from "@/hooks/useApi";
import { useCurrentUser } from "@/hooks/useCurrentUser";
import { buildQuery } from "@/lib/api";
import type {
  DataLicense,
  DataSource,
  Dataset,
  Paged,
} from "@/lib/types";

const { Text } = Typography;

/** 列表状态（分页）与查询合体的小 hook */
function usePaged<T>(
  key: string,
  path: string,
  extra?: Record<string, string | number | undefined>,
) {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const query = useApiQuery<Paged<T>>(
    [key, page, pageSize, extra],
    path + buildQuery({ page, page_size: pageSize, ...extra }),
  );
  return { ...query, page, pageSize, setPage, setPageSize };
}

// ------------------------------------------------------------------ 数据源
type SourceFormValues = {
  name: string;
  kind?: string;
  vendor?: string;
  homepage?: string;
  notes?: string;
};

function DataSourcesTab() {
  const { message } = App.useApp();
  const { hasPermission } = useCurrentUser();
  const canWrite = hasPermission("data.write");
  const canDelete = hasPermission("resource.delete");
  const [editing, setEditing] = useState<DataSource | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [form] = Form.useForm<SourceFormValues>();

  const sources = usePaged<DataSource>("data-sources", "/v1/data-sources");
  const saveSource = useApiMutation<unknown, ApiMutationInput>();
  const deleteSource = useApiMutation<unknown, ApiMutationInput>();

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    setModalOpen(true);
  };

  const openEdit = (row: DataSource) => {
    setEditing(row);
    form.setFieldsValue({
      name: row.name,
      kind: row.kind,
      vendor: row.vendor ?? undefined,
      homepage: row.homepage ?? undefined,
      notes: row.notes ?? undefined,
    });
    setModalOpen(true);
  };

  const onSubmit = async (values: SourceFormValues) => {
    try {
      if (editing) {
        await saveSource.mutateAsync({
          path: `/v1/data-sources/${editing.id}`,
          method: "PATCH",
          body: values,
        });
        message.success("数据源已更新");
      } else {
        await saveSource.mutateAsync({ path: "/v1/data-sources", body: values });
        message.success("数据源已登记");
      }
      setModalOpen(false);
      void sources.refetch();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "保存失败");
    }
  };

  const onDelete = async (row: DataSource) => {
    try {
      await deleteSource.mutateAsync({
        path: `/v1/data-sources/${row.id}?confirm=true`,
        method: "DELETE",
      });
      message.success("数据源已删除");
      void sources.refetch();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "删除失败");
    }
  };

  return (
    <>
      <Space style={{ marginBottom: 12 }}>
        {canWrite ? (
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            登记数据源
          </Button>
        ) : null}
      </Space>
      <Table<DataSource>
        rowKey="id"
        size="small"
        loading={sources.isLoading}
        dataSource={sources.data?.items ?? []}
        pagination={{
          current: sources.page,
          pageSize: sources.pageSize,
          total: sources.data?.total ?? 0,
          showSizeChanger: true,
          onChange: (p, ps) => {
            sources.setPage(p);
            sources.setPageSize(ps);
          },
        }}
        columns={[
          { title: "名称", dataIndex: "name" },
          { title: "类型", dataIndex: "kind", width: 120 },
          { title: "供应商", dataIndex: "vendor", render: (v: string | null) => v ?? "—" },
          {
            title: "数据集数",
            dataIndex: "dataset_count",
            width: 90,
            render: (v: number) => <Tag>{v}</Tag>,
          },
          {
            title: "状态",
            dataIndex: "status",
            width: 90,
            render: (v: string) => (
              <Tag color={v === "active" ? "green" : "default"}>
                {v === "active" ? "启用" : "停用"}
              </Tag>
            ),
          },
          { title: "登记人", dataIndex: "created_by", width: 100 },
          {
            title: "操作",
            key: "actions",
            width: 160,
            render: (_: unknown, row: DataSource) => (
              <Space size={4}>
                {canWrite ? (
                  <Button size="small" onClick={() => openEdit(row)}>
                    编辑
                  </Button>
                ) : null}
                {canDelete ? (
                  <Popconfirm
                    title={`确认删除数据源「${row.name}」？`}
                    description="有关联数据集时会被拒绝。"
                    okText="删除"
                    cancelText="取消"
                    onConfirm={() => void onDelete(row)}
                  >
                    <Button size="small" danger>
                      删除
                    </Button>
                  </Popconfirm>
                ) : null}
              </Space>
            ),
          },
        ]}
      />
      <Modal
        title={editing ? "编辑数据源" : "登记数据源"}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => void form.submit()}
        destroyOnClose
      >
        <Form form={form} layout="vertical" onFinish={(v) => void onSubmit(v)}>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: "请输入名称" }]}>
            <Input placeholder="如：Yahoo Finance（经 qlib 官方脚本导入）" maxLength={200} />
          </Form.Item>
          <Form.Item name="kind" label="类型" initialValue="market">
            <Input placeholder="market / index / fundamental …" maxLength={32} />
          </Form.Item>
          <Form.Item name="vendor" label="供应商">
            <Input maxLength={200} />
          </Form.Item>
          <Form.Item name="homepage" label="主页">
            <Input maxLength={500} />
          </Form.Item>
          <Form.Item name="notes" label="备注">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

// ------------------------------------------------------------------ 授权台账
type LicenseFormValues = {
  data_source_id: string;
  license_ref: string;
  allowed_use: string;
  granted_by: string;
  redistribution_allowed?: boolean;
  expires_at?: Dayjs;
};

function LicensesTab() {
  const { message } = App.useApp();
  const { hasPermission } = useCurrentUser();
  const canManage = hasPermission("data.license.manage");
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<DataLicense | null>(null);
  const [form] = Form.useForm<LicenseFormValues>();

  const sources = usePaged<DataSource>("license-source-options", "/v1/data-sources", {
    page_size: 200,
  });
  const licenses = usePaged<DataLicense>("data-licenses", "/v1/data-licenses");
  const saveLicense = useApiMutation<unknown, ApiMutationInput>();

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({ redistribution_allowed: false });
    setModalOpen(true);
  };

  const openEdit = (row: DataLicense) => {
    setEditing(row);
    form.setFieldsValue({
      data_source_id: row.data_source_id,
      license_ref: row.license_ref,
      allowed_use: row.allowed_use,
      granted_by: row.granted_by,
      redistribution_allowed: row.redistribution_allowed,
      expires_at: row.expires_at ? dayjs(row.expires_at) : undefined,
    });
    setModalOpen(true);
  };

  const onSubmit = async (values: LicenseFormValues) => {
    const body = {
      ...values,
      expires_at: values.expires_at ? values.expires_at.toISOString() : undefined,
    };
    try {
      if (editing) {
        await saveLicense.mutateAsync({
          path: `/v1/data-licenses/${editing.id}`,
          method: "PATCH",
          body,
        });
        message.success("授权台账已更新");
      } else {
        await saveLicense.mutateAsync({ path: "/v1/data-licenses", body });
        message.success("授权台账已登记");
      }
      setModalOpen(false);
      void licenses.refetch();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "保存失败");
    }
  };

  const onRevoke = async (row: DataLicense) => {
    try {
      await saveLicense.mutateAsync({
        path: `/v1/data-licenses/${row.id}`,
        method: "PATCH",
        body: { status: "revoked" },
      });
      message.success("台账已吊销");
      void licenses.refetch();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "吊销失败");
    }
  };

  return (
    <>
      <Space style={{ marginBottom: 12 }}>
        {canManage ? (
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            登记授权台账
          </Button>
        ) : (
          <Text type="secondary" style={{ fontSize: 13 }}>
            台账的创建 / 修改 / 吊销仅管理员可操作
          </Text>
        )}
      </Space>
      <Table<DataLicense>
        rowKey="id"
        size="small"
        loading={licenses.isLoading}
        dataSource={licenses.data?.items ?? []}
        pagination={{
          current: licenses.page,
          pageSize: licenses.pageSize,
          total: licenses.data?.total ?? 0,
          showSizeChanger: true,
          onChange: (p, ps) => {
            licenses.setPage(p);
            licenses.setPageSize(ps);
          },
        }}
        columns={[
          {
            title: "数据源",
            dataIndex: "data_source_name",
            render: (v: string | null) => v ?? "—",
          },
          {
            title: "授权依据",
            dataIndex: "license_ref",
            render: (v: string) => (
              <Tooltip title={v}>
                <Text style={{ maxWidth: 220 }} ellipsis>
                  {v}
                </Text>
              </Tooltip>
            ),
          },
          { title: "授权范围", dataIndex: "scope", width: 140 },
          {
            title: "可再分发",
            dataIndex: "redistribution_allowed",
            width: 100,
            render: (v: boolean) =>
              v ? <Tag color="orange">允许</Tag> : <Tag color="green">禁止</Tag>,
          },
          {
            title: "有效期至",
            dataIndex: "expires_at",
            width: 120,
            render: (v: string | null) => (v ? dayjs(v).format("YYYY-MM-DD") : "长期"),
          },
          {
            title: "状态",
            dataIndex: "status",
            width: 90,
            render: (v: string) =>
              v === "active" ? <Tag color="green">有效</Tag> : <Tag color="red">已吊销</Tag>,
          },
          { title: "登记人", dataIndex: "granted_by", width: 110 },
          {
            title: "操作",
            key: "actions",
            width: 160,
            render: (_: unknown, row: DataLicense) =>
              canManage ? (
                <Space size={4}>
                  <Button size="small" onClick={() => openEdit(row)}>
                    编辑
                  </Button>
                  {row.status === "active" ? (
                    <Popconfirm
                      title="确认吊销该台账？"
                      description="吊销后将无法用它创建数据集（已有数据集不受影响）。"
                      okText="吊销"
                      cancelText="取消"
                      onConfirm={() => void onRevoke(row)}
                    >
                      <Button size="small" danger>
                        吊销
                      </Button>
                    </Popconfirm>
                  ) : null}
                </Space>
              ) : null,
          },
        ]}
      />
      <Modal
        title={editing ? "更新授权台账" : "登记授权台账"}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => void form.submit()}
        destroyOnClose
      >
        <Form form={form} layout="vertical" onFinish={(v) => void onSubmit(v)}>
          <Form.Item
            name="data_source_id"
            label="数据源"
            rules={[{ required: true, message: "请选择数据源" }]}
          >
            <Select
              disabled={!!editing}
              placeholder="选择数据源"
              options={(sources.data?.items ?? []).map((s) => ({
                value: s.id,
                label: s.name,
              }))}
            />
          </Form.Item>
          <Form.Item
            name="license_ref"
            label="授权依据（如条款名称 / 链接 / 合同编号）"
            rules={[{ required: true, message: "请输入授权依据" }]}
          >
            <Input maxLength={200} />
          </Form.Item>
          <Form.Item
            name="allowed_use"
            label="允许用途"
            rules={[{ required: true, message: "请输入允许用途" }]}
            initialValue="internal research only（回测 / 因子研究 / 可视化）"
          >
            <Input.TextArea rows={2} maxLength={2000} />
          </Form.Item>
          <Form.Item name="granted_by" label="授权来源 / 经办人" rules={[{ required: true }]}>
            <Input maxLength={200} />
          </Form.Item>
          <Form.Item name="redistribution_allowed" label="允许再分发原始数据" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="expires_at" label="有效期至（留空 = 长期）">
            <DatePicker style={{ width: "100%" }} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

// ------------------------------------------------------------------ 数据集
type DatasetFormValues = {
  data_source_id: string;
  license_id: string;
  name: string;
  qlib_region?: string;
  freq?: string;
};

function DatasetsTab() {
  const { message } = App.useApp();
  const router = useRouter();
  const { hasPermission } = useCurrentUser();
  const canWrite = hasPermission("data.write");
  const [modalOpen, setModalOpen] = useState(false);
  const [form] = Form.useForm<DatasetFormValues>();
  const [sourceId, setSourceId] = useState<string | undefined>();

  const datasets = usePaged<Dataset>("datasets", "/v1/datasets");
  const sources = usePaged<DataSource>("dataset-source-options", "/v1/data-sources", {
    page_size: 200,
  });
  const licenses = useApiQuery<Paged<DataLicense>>(
    ["active-licenses", sourceId],
    `/v1/data-licenses${buildQuery({ data_source_id: sourceId, status: "active", page_size: 200 })}`,
    { enabled: !!sourceId },
  );
  const createDataset = useApiMutation<unknown, ApiMutationInput>();

  const onSubmit = async (values: DatasetFormValues) => {
    try {
      await createDataset.mutateAsync({ path: "/v1/datasets", body: values });
      message.success("数据集已创建（待导入）");
      setModalOpen(false);
      void datasets.refetch();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "创建失败");
    }
  };

  const sourceOptions = useMemo(
    () => (sources.data?.items ?? []).map((s) => ({ value: s.id, label: s.name })),
    [sources.data],
  );
  const licenseOptions = useMemo(
    () =>
      (licenses.data?.items ?? []).map((l) => ({
        value: l.id,
        label: `${l.license_ref}（${l.scope}）`,
      })),
    [licenses.data],
  );

  return (
    <>
      <Space style={{ marginBottom: 12 }}>
        {canWrite ? (
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => {
              form.resetFields();
              setSourceId(undefined);
              setModalOpen(true);
            }}
          >
            创建数据集
          </Button>
        ) : null}
        <Text type="secondary" style={{ fontSize: 13 }}>
          平台不内置未授权数据：创建数据集必须挂接有效授权台账
        </Text>
      </Space>
      <Table<Dataset>
        rowKey="id"
        size="small"
        loading={datasets.isLoading}
        dataSource={datasets.data?.items ?? []}
        pagination={{
          current: datasets.page,
          pageSize: datasets.pageSize,
          total: datasets.data?.total ?? 0,
          showSizeChanger: true,
          onChange: (p, ps) => {
            datasets.setPage(p);
            datasets.setPageSize(ps);
          },
        }}
        columns={[
          {
            title: "名称",
            dataIndex: "name",
            render: (name: string, row: Dataset) => (
              <Button
                type="link"
                size="small"
                onClick={() => router.push(`/data/datasets/${row.id}`)}
              >
                {name}
              </Button>
            ),
          },
          {
            title: "数据源",
            dataIndex: "data_source_name",
            render: (v: string | null) => v ?? "—",
          },
          {
            title: "授权依据",
            dataIndex: "license_ref",
            render: (v: string | null) => (v ? (
              <Tooltip title={v}>
                <Text style={{ maxWidth: 180 }} ellipsis>
                  {v}
                </Text>
              </Tooltip>
            ) : "—"),
          },
          {
            title: "区域/频率",
            key: "region",
            width: 110,
            render: (_: unknown, row: Dataset) => `${row.qlib_region} / ${row.freq}`,
          },
          {
            title: "区间",
            key: "range",
            render: (_: unknown, row: Dataset) =>
              row.start_date && row.end_date ? `${row.start_date} ~ ${row.end_date}` : "—",
          },
          {
            title: "标的数",
            dataIndex: "instrument_count",
            width: 80,
            render: (v: number) => v || "—",
          },
          {
            title: "状态",
            dataIndex: "status",
            width: 90,
            render: (v: Dataset["status"]) =>
              v === "active" ? (
                <Tag color="green">就绪</Tag>
              ) : v === "pending" ? (
                <Tag color="orange">待导入</Tag>
              ) : (
                <Tag color="red">失败</Tag>
              ),
          },
        ]}
      />
      <Modal
        title="创建数据集"
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => void form.submit()}
        destroyOnClose
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={(v) => void onSubmit(v)}
          onValuesChange={(changed) => {
            if ("data_source_id" in changed) {
              setSourceId(changed.data_source_id as string | undefined);
              form.setFieldValue("license_id", undefined);
            }
          }}
        >
          <Form.Item
            name="data_source_id"
            label="数据源"
            rules={[{ required: true, message: "请选择数据源" }]}
          >
            <Select placeholder="选择数据源" options={sourceOptions} />
          </Form.Item>
          <Form.Item
            name="license_id"
            label="授权台账（仅列出有效台账）"
            rules={[{ required: true, message: "请选择授权台账" }]}
            extra={!sourceId ? "先选择数据源" : undefined}
          >
            <Select
              placeholder="选择授权台账"
              options={licenseOptions}
              loading={licenses.isLoading}
              notFoundContent={sourceId ? "该数据源下没有有效台账" : undefined}
            />
          </Form.Item>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: "请输入名称" }]}>
            <Input maxLength={200} placeholder="如：cn 日线（Yahoo 公开数据）" />
          </Form.Item>
          <Form.Item name="qlib_region" label="qlib 区域" initialValue="cn">
            <Input maxLength={32} />
          </Form.Item>
          <Form.Item name="freq" label="频率" initialValue="day">
            <Input maxLength={8} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

// ------------------------------------------------------------------ 页面
function DataPageContent() {
  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Typography.Title level={4} style={{ margin: 0 }}>
        数据管理
      </Typography.Title>
      <Tabs
        items={[
          { key: "sources", label: "数据源", children: <DataSourcesTab /> },
          { key: "licenses", label: "授权台账", children: <LicensesTab /> },
          { key: "datasets", label: "数据集", children: <DatasetsTab /> },
        ]}
      />
    </Space>
  );
}

export default function DataPage() {
  return (
    <AppShell>
      <RequireAuth>
        <DataPageContent />
      </RequireAuth>
    </AppShell>
  );
}
