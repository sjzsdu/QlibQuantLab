"use client";

/**
 * 策略管理（阶段 5）：信号配置 CRUD（rule | model 双信号源）+ 绑定模型 + 公开发布（二次确认）。
 */

import { useMemo, useState } from "react";
import {
  App,
  Button,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import { PlusOutlined } from "@ant-design/icons";
import { AppShell } from "@/components/AppShell";
import { RequireAuth } from "@/components/RequireAuth";
import { useApiMutation, useApiQuery, type ApiMutationInput } from "@/hooks/useApi";
import { useCurrentUser } from "@/hooks/useCurrentUser";
import { buildQuery } from "@/lib/api";
import type { Model, Paged, Project, Strategy } from "@/lib/types";
import dayjs from "dayjs";

const { Text } = Typography;

type StrategyFormValues = {
  project_id: string;
  name: string;
  description?: string;
  signal_source: "rule" | "model";
  model_id?: string;
  lookback?: number;
};

function StrategiesPageContent() {
  const { message } = App.useApp();
  const { hasPermission } = useCurrentUser();
  const canWrite = hasPermission("strategy.write");
  const canPublish = hasPermission("strategy.publish");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [keyword, setKeyword] = useState<string | undefined>();
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Strategy | null>(null);
  const [form] = Form.useForm<StrategyFormValues>();

  const strategies = useApiQuery<Paged<Strategy>>(
    ["strategies", page, pageSize, keyword],
    `/v1/strategies${buildQuery({ page, page_size: pageSize, keyword })}`,
  );
  const projects = useApiQuery<Paged<Project>>(
    ["strategy-project-options"],
    `/v1/projects${buildQuery({ page_size: 200 })}`,
  );
  const models = useApiQuery<Paged<Model>>(
    ["strategy-model-options"],
    `/v1/models${buildQuery({ page_size: 200 })}`,
  );
  const saveStrategy = useApiMutation<Strategy, ApiMutationInput>();
  const publishStrategy = useApiMutation<Strategy, ApiMutationInput>();

  const projectOptions = useMemo(
    () => (projects.data?.items ?? []).map((p) => ({ value: p.id, label: p.name })),
    [projects.data],
  );
  const modelOptions = useMemo(
    () =>
      (models.data?.items ?? []).map((m) => ({
        value: m.id,
        label: `${m.name}（${m.status}）`,
      })),
    [models.data],
  );

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({ signal_source: "rule", lookback: 20 });
    setModalOpen(true);
  };

  const openEdit = (row: Strategy) => {
    setEditing(row);
    form.setFieldsValue({
      name: row.name,
      description: row.description ?? undefined,
      signal_source: row.signal_source,
      model_id: row.model_id ?? undefined,
      lookback: (row.signal_config.lookback as number) ?? 20,
    });
    setModalOpen(true);
  };

  const onSubmit = async (values: StrategyFormValues) => {
    try {
      if (editing) {
        await saveStrategy.mutateAsync({
          path: `/v1/strategies/${editing.id}`,
          method: "PATCH",
          body: {
            name: values.name,
            description: values.description ?? null,
            signal_source: values.signal_source,
            model_id: values.signal_source === "model" ? values.model_id : null,
            lookback: values.lookback ?? 20,
          },
        });
        message.success("策略已更新");
      } else {
        await saveStrategy.mutateAsync({
          path: "/v1/strategies",
          body: values,
        });
        message.success("策略已创建");
      }
      setModalOpen(false);
      form.resetFields();
      setEditing(null);
      void strategies.refetch();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "保存失败");
    }
  };

  const onPublish = async (row: Strategy) => {
    try {
      await publishStrategy.mutateAsync({
        path: `/v1/strategies/${row.id}/publish?confirm=true`,
      });
      message.success("策略已公开发布");
      void strategies.refetch();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "发布失败");
    }
  };

  const sourceWatch = Form.useWatch("signal_source", form);

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Space style={{ width: "100%", justifyContent: "space-between" }} wrap>
        <Typography.Title level={4} style={{ margin: 0 }}>
          策略管理
        </Typography.Title>
        <Space>
          <Input.Search
            placeholder="按名称搜索"
            allowClear
            style={{ width: 220 }}
            onSearch={(value) => {
              setKeyword(value || undefined);
              setPage(1);
            }}
          />
          {canWrite ? (
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
              新建策略
            </Button>
          ) : null}
        </Space>
      </Space>

      <Table<Strategy>
        rowKey="id"
        size="small"
        loading={strategies.isLoading}
        dataSource={strategies.data?.items ?? []}
        pagination={{
          current: page,
          pageSize,
          total: strategies.data?.total ?? 0,
          showSizeChanger: true,
          onChange: (p, ps) => {
            setPage(p);
            setPageSize(ps);
          },
        }}
        columns={[
          { title: "名称", dataIndex: "name" },
          { title: "所属项目", dataIndex: "project_name", render: (v: string | null) => v ?? "—" },
          {
            title: "信号源",
            key: "signal_source",
            width: 220,
            render: (_: unknown, row: Strategy) =>
              row.signal_source === "model" ? (
                <Tooltip title={`绑定模型：${row.model_id ?? "—"}`}>
                  <Tag color="purple">模型信号</Tag>
                </Tooltip>
              ) : (
                <Tag color="blue">规则信号（动量 {String(row.signal_config.lookback ?? 20)} 日）</Tag>
              ),
          },
          {
            title: "绑定模型",
            dataIndex: "model_name",
            render: (v: string | null, row: Strategy) => v ?? (row.model_id ? row.model_id : "—"),
          },
          {
            title: "可见性",
            key: "visibility",
            width: 110,
            render: (_: unknown, row: Strategy) =>
              row.is_public ? (
                <Tag color="green">已发布 v{row.version}</Tag>
              ) : (
                <Tag>{row.visibility}</Tag>
              ),
          },
          { title: "创建人", dataIndex: "created_by", width: 100 },
          {
            title: "更新时间",
            dataIndex: "updated_at",
            width: 150,
            render: (v: string) => dayjs(v).format("YYYY-MM-DD HH:mm"),
          },
          {
            title: "操作",
            key: "actions",
            width: 170,
            render: (_: unknown, row: Strategy) => (
              <Space size={4}>
                {canWrite ? (
                  <Button type="link" size="small" onClick={() => openEdit(row)}>
                    编辑
                  </Button>
                ) : null}
                {canPublish && !row.is_public ? (
                  <Popconfirm
                    title="公开该策略？"
                    description="发布后组织外可见（阶段 5 为 public），且需要管理员权限。"
                    okText="确认发布"
                    cancelText="取消"
                    onConfirm={() => void onPublish(row)}
                  >
                    <Button type="link" size="small" disabled={!canPublish}>
                      发布
                    </Button>
                  </Popconfirm>
                ) : null}
              </Space>
            ),
          },
        ]}
      />

      <Modal
        title={editing ? "编辑策略" : "新建策略"}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => void form.submit()}
        okButtonProps={{ loading: saveStrategy.isPending }}
        width={640}
        destroyOnClose
      >
        <Form form={form} layout="vertical" onFinish={(v) => void onSubmit(v)}>
          {!editing ? (
            <Form.Item
              name="project_id"
              label="所属项目"
              rules={[{ required: true, message: "请选择项目" }]}
            >
              <Select
                placeholder="选择项目"
                options={projectOptions}
                loading={projects.isLoading}
                showSearch
                optionFilterProp="label"
              />
            </Form.Item>
          ) : null}
          <Form.Item name="name" label="名称" rules={[{ required: true, message: "请输入名称" }]}>
            <Input maxLength={200} placeholder="如：动量 Top5 / LGB 因子策略" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item
            name="signal_source"
            label="信号源"
            rules={[{ required: true, message: "请选择信号源" }]}
            extra="规则 = 动量回看窗口；模型 = 绑定模型的样本外预测（需该模型已有成功训练）"
          >
            <Select
              options={[
                { value: "rule", label: "规则信号（动量）" },
                { value: "model", label: "模型信号（绑定训练模型）" },
              ]}
            />
          </Form.Item>
          {sourceWatch === "model" ? (
            <Form.Item
              name="model_id"
              label="绑定模型"
              rules={[{ required: true, message: "请选择模型" }]}
              extra="回测时取该模型最近一次产出 artifact 的成功训练做预测"
            >
              <Select
                placeholder="选择模型"
                options={modelOptions}
                loading={models.isLoading}
                showSearch
                optionFilterProp="label"
              />
            </Form.Item>
          ) : (
            <Form.Item
              name="lookback"
              label="动量回看窗口（交易日）"
              rules={[{ required: true, message: "请输入回看窗口" }]}
            >
              <InputNumber min={1} max={250} style={{ width: 200 }} />
            </Form.Item>
          )}
          {!editing ? (
            <Text type="secondary" style={{ fontSize: 12 }}>
              策略创建后可在回测提交时选择；发布为敏感操作（二次确认 + 管理员权限）。
            </Text>
          ) : null}
        </Form>
      </Modal>
    </Space>
  );
}

export default function StrategiesPage() {
  return (
    <AppShell>
      <RequireAuth>
        <StrategiesPageContent />
      </RequireAuth>
    </AppShell>
  );
}
