"use client";

/**
 * 因子详情（阶段 4）：编辑（名称/描述/表达式 + 静态校验）、发布（二次确认）、删除。
 * 表达式变更保存后后端会自动 version+1（版本历史留痕）。
 */

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Descriptions,
  Form,
  Input,
  Popconfirm,
  Space,
  Spin,
  Tag,
  Typography,
} from "antd";
import { ArrowLeftOutlined, CheckCircleOutlined } from "@ant-design/icons";
import { AppShell } from "@/components/AppShell";
import { RequireAuth } from "@/components/RequireAuth";
import { ExpressionValidator } from "@/components/ExpressionValidator";
import { useApiMutation, useApiQuery, type ApiMutationInput } from "@/hooks/useApi";
import { useCurrentUser } from "@/hooks/useCurrentUser";
import type { Factor, Visibility } from "@/lib/types";
import dayjs from "dayjs";

const { Text, Paragraph } = Typography;

const VISIBILITY_META: Record<Visibility, { label: string; color: string }> = {
  private: { label: "私有", color: "default" },
  org: { label: "组织内", color: "blue" },
  public: { label: "已发布", color: "green" },
};

type FactorEditForm = {
  name: string;
  description?: string;
  expression: string;
};

function FactorDetailContent({ id }: { id: string }) {
  const { message, modal } = App.useApp();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { hasPermission } = useCurrentUser();
  const canWrite = hasPermission("factor.write");
  const canPublish = hasPermission("factor.publish");

  const factorQuery = useApiQuery<Factor>(["factor", id], `/v1/factors/${id}`);
  const [form] = Form.useForm<FactorEditForm>();
  const [expression, setExpression] = useState<string | undefined>(undefined);

  const updateFactor = useApiMutation<unknown, ApiMutationInput>();
  const publishFactor = useApiMutation<unknown, ApiMutationInput>();
  const deleteFactor = useApiMutation<unknown, ApiMutationInput>();

  const factor = factorQuery.data;

  const onSave = async (values: FactorEditForm) => {
    try {
      await updateFactor.mutateAsync({
        path: `/v1/factors/${id}`,
        method: "PATCH",
        body: values,
      });
      message.success("因子已保存");
      void queryClient.invalidateQueries({ queryKey: ["factor", id] });
      void queryClient.invalidateQueries({ queryKey: ["factors"] });
    } catch (error) {
      message.error(error instanceof Error ? error.message : "保存失败");
    }
  };

  const onPublish = () => {
    modal.confirm({
      title: "确认发布该因子？",
      content:
        "发布后该因子对全组织可见，且作为「已发布定义」被后续研究引用（不可静默修改语义，修改会生成新版本）。",
      okText: "发布",
      cancelText: "取消",
      onOk: async () => {
        try {
          await publishFactor.mutateAsync({
            path: `/v1/factors/${id}/publish?confirm=true`,
          });
          message.success("因子已发布");
          void queryClient.invalidateQueries({ queryKey: ["factor", id] });
          void queryClient.invalidateQueries({ queryKey: ["factors"] });
        } catch (error) {
          message.error(error instanceof Error ? error.message : "发布失败");
        }
      },
    });
  };

  const onDelete = async () => {
    try {
      await deleteFactor.mutateAsync({
        path: `/v1/factors/${id}?confirm=true`,
        method: "DELETE",
      });
      message.success("因子已删除");
      void queryClient.invalidateQueries({ queryKey: ["factors"] });
      router.push("/factors");
    } catch (error) {
      message.error(error instanceof Error ? error.message : "删除失败");
    }
  };

  if (factorQuery.isLoading || !factor) {
    return (
      <Spin style={{ display: "block", margin: "48px auto" }} size="large" />
    );
  }

  const meta = VISIBILITY_META[factor.visibility] ?? VISIBILITY_META.private;

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => router.push("/factors")}>
        返回因子库
      </Button>

      <Card
        title={
          <Space>
            {factor.name}
            <Tag color={meta.color}>{meta.label}</Tag>
            <Tag>v{factor.version}</Tag>
          </Space>
        }
        extra={
          canWrite ? (
            <Space>
              {canPublish && factor.visibility !== "public" ? (
                <Button
                  type="primary"
                  icon={<CheckCircleOutlined />}
                  loading={publishFactor.isPending}
                  onClick={onPublish}
                >
                  发布
                </Button>
              ) : null}
              <Popconfirm
                title="确认删除该因子？"
                description="删除后无法恢复。"
                okText="删除"
                cancelText="取消"
                onConfirm={() => void onDelete()}
              >
                <Button danger>删除</Button>
              </Popconfirm>
            </Space>
          ) : null
        }
      >
        <Descriptions column={{ xs: 1, sm: 2 }} size="small">
          <Descriptions.Item label="所属项目">
            <Button
              type="link"
              size="small"
              style={{ padding: 0 }}
              onClick={() => router.push(`/projects/${factor.project_id}`)}
            >
              {factor.project_name ?? factor.project_id}
            </Button>
          </Descriptions.Item>
          <Descriptions.Item label="创建人">{factor.created_by}</Descriptions.Item>
          <Descriptions.Item label="创建时间">
            {dayjs(factor.created_at).format("YYYY-MM-DD HH:mm")}
          </Descriptions.Item>
          <Descriptions.Item label="更新时间">
            {dayjs(factor.updated_at).format("YYYY-MM-DD HH:mm")}
          </Descriptions.Item>
        </Descriptions>
        {factor.visibility === "public" ? (
          <Alert
            style={{ marginTop: 12 }}
            type="info"
            showIcon
            message="已发布：表达式变更会生成新版本（version+1），历史版本可追溯。"
          />
        ) : null}
      </Card>

      <Card title="定义">
        <Form<FactorEditForm>
          form={form}
          layout="vertical"
          initialValues={{
            name: factor.name,
            description: factor.description ?? "",
            expression: factor.expression,
          }}
          onFinish={(values) => void onSave(values)}
        >
          <Form.Item
            name="name"
            label="名称"
            rules={[{ required: true, message: "请输入名称" }]}
          >
            <Input maxLength={200} disabled={!canWrite} />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} disabled={!canWrite} />
          </Form.Item>
          <Form.Item
            name="expression"
            label="Qlib 表达式"
            rules={[{ required: true, message: "请输入表达式" }]}
            extra="字段：$open/$high/$low/$close/$volume/$factor/$vwap；函数：Ref/Mean/Std/Rank/If 等白名单。表达式变更保存后 version+1。"
          >
            <Input.TextArea
              rows={4}
              maxLength={500}
              disabled={!canWrite}
              style={{ fontFamily: "monospace" }}
              onChange={(event) => setExpression(event.target.value)}
            />
          </Form.Item>
          <ExpressionValidator expression={expression ?? factor.expression} />
          {canWrite ? (
            <Paragraph style={{ marginTop: 16, marginBottom: 0 }}>
              <Button type="primary" htmlType="submit" loading={updateFactor.isPending}>
                保存
              </Button>
              <Text type="secondary" style={{ marginLeft: 12, fontSize: 12 }}>
                阶段 4 只做静态校验；表达式真实求值与 IC 分析在阶段 5 上线。
              </Text>
            </Paragraph>
          ) : (
            <Alert style={{ marginTop: 12 }} type="info" showIcon message="你当前的角色为只读，无法编辑因子。" />
          )}
        </Form>
      </Card>
    </Space>
  );
}

export default function FactorDetailPage() {
  const { id } = useParams<{ id: string }>();
  return (
    <AppShell>
      <RequireAuth>
        <FactorDetailContent id={id} />
      </RequireAuth>
    </AppShell>
  );
}
