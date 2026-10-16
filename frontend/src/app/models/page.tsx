"use client";

/**
 * 模型训练（阶段 5）：模型列表 + 创建（factor_ids 引用即快照）。
 * 训练提交在详情页；算法目录来自 GET /models/catalog（静态，D5-0a 仅 lgb）。
 */

import { useMemo, useState } from "react";
import {
  App,
  Button,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import { PlusOutlined } from "@ant-design/icons";
import { useRouter } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { RequireAuth } from "@/components/RequireAuth";
import { useApiMutation, useApiQuery, type ApiMutationInput } from "@/hooks/useApi";
import { useCurrentUser } from "@/hooks/useCurrentUser";
import { buildQuery } from "@/lib/api";
import type {
  Dataset,
  Factor,
  Model,
  ModelCatalogItem,
  ModelStatus,
  Paged,
  Project,
} from "@/lib/types";
import dayjs from "dayjs";

const { Text, Paragraph } = Typography;

const MODEL_STATUS_META: Record<ModelStatus, { label: string; color: string }> = {
  draft: { label: "未训练", color: "default" },
  training: { label: "训练中", color: "blue" },
  trained: { label: "已训练", color: "green" },
  failed: { label: "失败", color: "red" },
};

type ModelFormValues = {
  project_id: string;
  dataset_id: string;
  name: string;
  algo: string;
  factor_ids: string[];
  n_estimators?: number;
  learning_rate?: number;
};

function ModelsPageContent() {
  const { message } = App.useApp();
  const router = useRouter();
  const { hasPermission } = useCurrentUser();
  const canWrite = hasPermission("model.write");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [keyword, setKeyword] = useState<string | undefined>();
  const [modalOpen, setModalOpen] = useState(false);
  const [projectId, setProjectId] = useState<string | undefined>();
  const [form] = Form.useForm<ModelFormValues>();

  const models = useApiQuery<Paged<Model>>(
    ["models", page, pageSize, keyword],
    `/v1/models${buildQuery({ page, page_size: pageSize, keyword })}`,
  );
  const projects = useApiQuery<Paged<Project>>(
    ["model-project-options"],
    `/v1/projects${buildQuery({ page_size: 200 })}`,
  );
  const datasets = useApiQuery<Paged<Dataset>>(
    ["model-dataset-options"],
    `/v1/datasets${buildQuery({ page_size: 200 })}`,
  );
  const catalog = useApiQuery<ModelCatalogItem[]>(["model-catalog"], "/v1/models/catalog");
  const factors = useApiQuery<Paged<Factor>>(
    ["model-factor-options", projectId],
    `/v1/factors${buildQuery({ page_size: 200, project_id: projectId })}`,
    { enabled: !!projectId },
  );
  const createModel = useApiMutation<Model, ApiMutationInput>();

  const projectOptions = useMemo(
    () => (projects.data?.items ?? []).map((p) => ({ value: p.id, label: p.name })),
    [projects.data],
  );
  const datasetOptions = useMemo(
    () =>
      (datasets.data?.items ?? []).map((d) => ({
        value: d.id,
        label: d.start_date
          ? `${d.name}（${d.start_date} ~ ${d.end_date}）`
          : `${d.name}（未导入）`,
        disabled: !d.start_date,
      })),
    [datasets.data],
  );
  const factorOptions = useMemo(
    () =>
      (factors.data?.items ?? []).map((f) => ({
        value: f.id,
        label: `${f.name} — ${f.expression}`,
      })),
    [factors.data],
  );
  const algoOptions = useMemo(
    () =>
      (catalog.data ?? [])
        .filter((item) => item.available)
        .map((item) => ({ value: item.algo, label: item.label })),
    [catalog.data],
  );

  const onSubmit = async (values: ModelFormValues) => {
    try {
      const hyperparams: Record<string, unknown> = {};
      if (values.n_estimators) hyperparams.n_estimators = values.n_estimators;
      if (values.learning_rate) hyperparams.learning_rate = values.learning_rate;
      await createModel.mutateAsync({
        path: "/v1/models",
        body: {
          project_id: values.project_id,
          dataset_id: values.dataset_id,
          name: values.name,
          algo: values.algo,
          factor_ids: values.factor_ids,
          hyperparams,
        },
      });
      message.success("模型已创建（因子表达式已快照）");
      setModalOpen(false);
      form.resetFields();
      setProjectId(undefined);
      void models.refetch();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "创建失败");
    }
  };

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Space style={{ width: "100%", justifyContent: "space-between" }} wrap>
        <Typography.Title level={4} style={{ margin: 0 }}>
          模型训练
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
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => {
                form.resetFields();
                setProjectId(undefined);
                setModalOpen(true);
              }}
            >
              新建模型
            </Button>
          ) : null}
        </Space>
      </Space>

      <Table<Model>
        rowKey="id"
        size="small"
        loading={models.isLoading}
        dataSource={models.data?.items ?? []}
        pagination={{
          current: page,
          pageSize,
          total: models.data?.total ?? 0,
          showSizeChanger: true,
          onChange: (p, ps) => {
            setPage(p);
            setPageSize(ps);
          },
        }}
        columns={[
          {
            title: "名称",
            dataIndex: "name",
            render: (name: string, row: Model) => (
              <Button type="link" size="small" onClick={() => router.push(`/models/${row.id}`)}>
                {name}
              </Button>
            ),
          },
          { title: "所属项目", dataIndex: "project_name", render: (v: string | null) => v ?? "—" },
          { title: "数据集", dataIndex: "dataset_name", render: (v: string | null) => v ?? "—" },
          { title: "算法", dataIndex: "algo", width: 90, render: (v: string) => <Tag>{v}</Tag> },
          {
            title: "状态",
            dataIndex: "status",
            width: 90,
            render: (v: ModelStatus) => {
              const meta = MODEL_STATUS_META[v] ?? MODEL_STATUS_META.draft;
              return <Tag color={meta.color}>{meta.label}</Tag>;
            },
          },
          {
            title: "因子数",
            key: "n_factors",
            width: 80,
            render: (_: unknown, row: Model) => row.factor_snapshot.length,
          },
          {
            title: "最近训练",
            key: "last_run",
            width: 110,
            render: (_: unknown, row: Model) =>
              row.last_run ? (
                <Tooltip
                  title={`创建于 ${dayjs(row.last_run.created_at).format("YYYY-MM-DD HH:mm")}`}
                >
                  <Tag
                    color={
                      MODEL_STATUS_META[(row.last_run.job_status ?? "draft") as ModelStatus]?.color ??
                      "default"
                    }
                  >
                    {row.last_run.job_status ?? "—"}
                  </Tag>
                </Tooltip>
              ) : (
                <Text type="secondary">—</Text>
              ),
          },
          { title: "创建人", dataIndex: "created_by", width: 100 },
          {
            title: "更新时间",
            dataIndex: "updated_at",
            width: 150,
            render: (v: string) => dayjs(v).format("YYYY-MM-DD HH:mm"),
          },
        ]}
      />

      <Modal
        title="新建模型"
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => void form.submit()}
        okButtonProps={{ loading: createModel.isPending }}
        width={680}
        destroyOnClose
      >
        <Form form={form} layout="vertical" onFinish={(v) => void onSubmit(v)}>
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
              onChange={(value) => {
                setProjectId(value as string);
                form.setFieldValue("factor_ids", []);
              }}
            />
          </Form.Item>
          <Form.Item
            name="dataset_id"
            label="绑定数据集"
            rules={[{ required: true, message: "请选择数据集" }]}
            extra="训练默认在该数据集区间上做 70/30 切分（提交训练时可显式覆盖）"
          >
            <Select
              placeholder="选择已导入的数据集"
              options={datasetOptions}
              loading={datasets.isLoading}
              showSearch
              optionFilterProp="label"
            />
          </Form.Item>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: "请输入名称" }]}>
            <Input maxLength={200} placeholder="如：LGB 动量增强 v1" />
          </Form.Item>
          <Form.Item
            name="algo"
            label="算法"
            initialValue="lgb"
            rules={[{ required: true, message: "请选择算法" }]}
          >
            <Select options={algoOptions} loading={catalog.isLoading} />
          </Form.Item>
          <Form.Item
            name="factor_ids"
            label="特征因子"
            rules={[
              { required: true, message: "请至少选择一个因子" },
              {
                validator: (_, values: string[]) =>
                  (values ?? []).length > 0
                    ? Promise.resolve()
                    : Promise.reject(new Error("请至少选择一个因子")),
              },
            ]}
            extra="创建时固化因子表达式快照：之后修改因子库不影响本模型（可复现性）"
          >
            <Select
              mode="multiple"
              placeholder={projectId ? "选择因子（展示项目内因子）" : "先选择项目"}
              options={factorOptions}
              loading={factors.isLoading}
              disabled={!projectId}
              optionFilterProp="label"
            />
          </Form.Item>
          <Space size={16} wrap>
            <Form.Item name="n_estimators" label="树数量（n_estimators）">
              <InputNumber min={10} max={10000} placeholder="默认 100" style={{ width: 180 }} />
            </Form.Item>
            <Form.Item name="learning_rate" label="学习率（learning_rate）">
              <InputNumber
                min={0.001}
                max={1}
                step={0.01}
                placeholder="默认 0.1"
                style={{ width: 180 }}
              />
            </Form.Item>
          </Space>
          <Paragraph type="secondary" style={{ fontSize: 12, marginTop: 8, marginBottom: 0 }}>
            阶段 5 仅支持 LightGBM（D5-0a）；目标函数默认「次期收益」，训练快照随任务固化。
          </Paragraph>
        </Form>
      </Modal>
    </Space>
  );
}

export default function ModelsPage() {
  return (
    <AppShell>
      <RequireAuth>
        <ModelsPageContent />
      </RequireAuth>
    </AppShell>
  );
}
