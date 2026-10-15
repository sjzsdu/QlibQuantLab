"use client";

/**
 * 因子库（阶段 4）：表达式 CRUD + 静态校验 + 发布。
 * 本阶段因子只做「定义与校验」，真实计算与 IC 分析属阶段 5。
 */

import { useMemo, useState } from "react";
import {
  App,
  Button,
  Form,
  Input,
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
import { ExpressionValidator } from "@/components/ExpressionValidator";
import { useApiMutation, useApiQuery, type ApiMutationInput } from "@/hooks/useApi";
import { useCurrentUser } from "@/hooks/useCurrentUser";
import { buildQuery } from "@/lib/api";
import type { Factor, Paged, Project, Visibility } from "@/lib/types";
import dayjs from "dayjs";

const { Text, Paragraph } = Typography;

const VISIBILITY_META: Record<Visibility, { label: string; color: string }> = {
  private: { label: "私有", color: "default" },
  org: { label: "组织内", color: "blue" },
  public: { label: "已发布", color: "green" },
};

type FactorFormValues = {
  project_id: string;
  name: string;
  description?: string;
  expression: string;
};

function FactorsPageContent() {
  const { message } = App.useApp();
  const router = useRouter();
  const { hasPermission } = useCurrentUser();
  const canWrite = hasPermission("factor.write");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [keyword, setKeyword] = useState<string | undefined>();
  const [modalOpen, setModalOpen] = useState(false);
  const [expression, setExpression] = useState("");
  const [form] = Form.useForm<FactorFormValues>();

  const factors = useApiQuery<Paged<Factor>>(
    ["factors", page, pageSize, keyword],
    `/v1/factors${buildQuery({ page, page_size: pageSize, keyword })}`,
  );
  const projects = useApiQuery<Paged<Project>>(
    ["factor-project-options"],
    `/v1/projects${buildQuery({ page_size: 200 })}`,
  );
  const createFactor = useApiMutation<unknown, ApiMutationInput>();

  const projectOptions = useMemo(
    () => (projects.data?.items ?? []).map((p) => ({ value: p.id, label: p.name })),
    [projects.data],
  );

  const onSubmit = async (values: FactorFormValues) => {
    try {
      await createFactor.mutateAsync({ path: "/v1/factors", body: values });
      message.success("因子已创建");
      setModalOpen(false);
      form.resetFields();
      setExpression("");
      void factors.refetch();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "创建失败");
    }
  };

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Space style={{ width: "100%", justifyContent: "space-between" }} wrap>
        <Typography.Title level={4} style={{ margin: 0 }}>
          因子库
        </Typography.Title>
        <Space>
          <Input.Search
            placeholder="按名称 / 表达式搜索"
            allowClear
            style={{ width: 260 }}
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
                setExpression("");
                setModalOpen(true);
              }}
            >
              新建因子
            </Button>
          ) : null}
        </Space>
      </Space>

      <Table<Factor>
        rowKey="id"
        size="small"
        loading={factors.isLoading}
        dataSource={factors.data?.items ?? []}
        pagination={{
          current: page,
          pageSize,
          total: factors.data?.total ?? 0,
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
            render: (name: string, row: Factor) => (
              <Button type="link" size="small" onClick={() => router.push(`/factors/${row.id}`)}>
                {name}
              </Button>
            ),
          },
          { title: "所属项目", dataIndex: "project_name", render: (v: string | null) => v ?? "—" },
          {
            title: "表达式",
            dataIndex: "expression",
            render: (value: string) => (
              <Tooltip title={value}>
                <Text code style={{ maxWidth: 280 }} ellipsis={{ tooltip: value }}>
                  {value}
                </Text>
              </Tooltip>
            ),
          },
          {
            title: "版本",
            dataIndex: "version",
            width: 70,
            render: (v: number) => <Tag>v{v}</Tag>,
          },
          {
            title: "状态",
            dataIndex: "visibility",
            width: 90,
            render: (v: Visibility) => {
              const meta = VISIBILITY_META[v] ?? VISIBILITY_META.private;
              return <Tag color={meta.color}>{meta.label}</Tag>;
            },
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
        title="新建因子"
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => void form.submit()}
        okButtonProps={{ loading: createFactor.isPending }}
        width={640}
        destroyOnClose
      >
        <Form form={form} layout="vertical" onFinish={(v) => void onSubmit(v)}>
          <Form.Item
            name="project_id"
            label="所属项目"
            rules={[{ required: true, message: "请选择项目" }]}
          >
            <Select placeholder="选择项目" options={projectOptions} loading={projects.isLoading} />
          </Form.Item>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: "请输入名称" }]}>
            <Input maxLength={200} placeholder="如：5 日反转" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item
            name="expression"
            label="Qlib 表达式"
            rules={[{ required: true, message: "请输入表达式" }]}
            extra="支持 $open/$high/$low/$close/$volume/$factor 字段与 Ref/Mean/Std/Rank/If 等白名单函数"
          >
            <Input.TextArea
              rows={3}
              maxLength={500}
              placeholder="如：Ref($close, 5) / $close - 1"
              onChange={(event) => setExpression(event.target.value)}
              style={{ fontFamily: "monospace" }}
            />
          </Form.Item>
          <ExpressionValidator expression={expression} />
          <Paragraph type="secondary" style={{ fontSize: 12, marginTop: 12, marginBottom: 0 }}>
            阶段 4 只做静态校验（词法/语法/白名单），不执行计算；真实求值在阶段 5。
          </Paragraph>
        </Form>
      </Modal>
    </Space>
  );
}

export default function FactorsPage() {
  return (
    <AppShell>
      <RequireAuth>
        <FactorsPageContent />
      </RequireAuth>
    </AppShell>
  );
}
