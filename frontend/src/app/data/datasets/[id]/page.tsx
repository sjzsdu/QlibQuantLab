"use client";

/**
 * 数据集详情（阶段 4）：导入（入队 → 每 2s 轮询任务）+ 预览（标的 / 日历 / OHLCV）。
 *
 * 预览数据由 API 容器只读挂载 qlib_data 卷、纯标准库解析 float32 bin 得到
 * （API 进程不 import qlib）；未导入（storage_uri 为空）时后端返回 400，前端展示原因。
 */

import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  AutoComplete,
  Button,
  Card,
  DatePicker,
  Descriptions,
  Progress,
  Space,
  Spin,
  Table,
  Tabs,
  Tag,
  Typography,
} from "antd";
import { ArrowLeftOutlined, ImportOutlined } from "@ant-design/icons";
import type { Dayjs } from "dayjs";
import { AppShell } from "@/components/AppShell";
import { RequireAuth } from "@/components/RequireAuth";
import { useApiMutation, useApiQuery, type ApiMutationInput } from "@/hooks/useApi";
import { useCurrentUser } from "@/hooks/useCurrentUser";
import { buildQuery } from "@/lib/api";
import type {
  Dataset,
  DatasetCalendar,
  DatasetImportReceipt,
  DatasetInstruments,
  DatasetPreview,
  Job,
} from "@/lib/types";

const { Text } = Typography;

const JOB_STATUS_META: Record<string, { label: string; color: string }> = {
  queued: { label: "排队中", color: "default" },
  running: { label: "运行中", color: "blue" },
  succeeded: { label: "成功", color: "green" },
  failed: { label: "失败", color: "red" },
  canceled: { label: "已取消", color: "orange" },
};

const TERMINAL = new Set(["succeeded", "failed", "canceled"]);

function DatasetDetailContent({ id }: { id: string }) {
  const { message } = App.useApp();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { hasPermission } = useCurrentUser();
  const canImport = hasPermission("data.write");
  const [activeJobId, setActiveJobId] = useState<string | null>(null);

  const { data: dataset, isLoading } = useApiQuery<Dataset>(["dataset", id], `/v1/datasets/${id}`);

  // 导入任务轮询：每 2s，终态停
  const { data: job } = useApiQuery<Job>(
    ["dataset-import-job", activeJobId],
    `/v1/jobs/${activeJobId ?? ""}`,
    {
      enabled: !!activeJobId,
      refetchInterval: (query) => {
        const status = query.state.data?.status;
        return status && TERMINAL.has(status) ? false : 2000;
      },
    },
  );

  // 任务成功后刷新数据集信息与预览
  useEffect(() => {
    if (job?.status === "succeeded") {
      void queryClient.invalidateQueries({ queryKey: ["dataset", id] });
      void queryClient.invalidateQueries({ queryKey: ["dataset-page", id] });
    }
  }, [job?.status, id, queryClient]);

  const importDataset = useApiMutation<DatasetImportReceipt, ApiMutationInput>();
  const onImport = async () => {
    try {
      const receipt = await importDataset.mutateAsync({
        path: `/v1/datasets/${id}/import`,
      });
      setActiveJobId(receipt.job_id);
      message.success("导入任务已入队");
    } catch (error) {
      message.error(error instanceof Error ? error.message : "入队失败");
    }
  };

  const jobActive = !!job && !TERMINAL.has(job.status);
  const statusMeta = dataset ? JOB_STATUS_META[dataset.status] : undefined;

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => router.push("/data")}>
        返回数据管理
      </Button>

      {isLoading || !dataset ? (
        <Spin style={{ display: "block", margin: "48px auto" }} size="large" />
      ) : (
        <>
          <Card
            title={
              <Space>
                {dataset.name}
                {statusMeta ? <Tag color={statusMeta.color}>{statusMeta.label}</Tag> : null}
              </Space>
            }
            extra={
              canImport ? (
                <Button
                  type="primary"
                  icon={<ImportOutlined />}
                  loading={importDataset.isPending || jobActive}
                  onClick={() => void onImport()}
                >
                  {jobActive ? "导入进行中…" : dataset.status === "active" ? "重新导入" : "导入数据"}
                </Button>
              ) : null
            }
          >
            <Descriptions column={{ xs: 1, sm: 2, lg: 3 }} size="small">
              <Descriptions.Item label="数据源">
                {dataset.data_source_name ?? dataset.data_source_id}
              </Descriptions.Item>
              <Descriptions.Item label="授权依据">
                {dataset.license_ref ?? dataset.license_id}
              </Descriptions.Item>
              <Descriptions.Item label="区域/频率">
                {dataset.qlib_region} / {dataset.freq}
              </Descriptions.Item>
              <Descriptions.Item label="数据区间">
                {dataset.start_date && dataset.end_date
                  ? `${dataset.start_date} ~ ${dataset.end_date}`
                  : "—"}
              </Descriptions.Item>
              <Descriptions.Item label="标的数">
                {dataset.instrument_count || "—"}
              </Descriptions.Item>
              <Descriptions.Item label="登记人">{dataset.created_by}</Descriptions.Item>
            </Descriptions>
            {job ? (
              <div style={{ marginTop: 12 }}>
                <Space size={12}>
                  <Tag color={JOB_STATUS_META[job.status]?.color}>
                    {JOB_STATUS_META[job.status]?.label ?? job.status}
                  </Tag>
                  <Progress
                    percent={job.progress}
                    size="small"
                    style={{ width: 200 }}
                    status={job.status === "failed" ? "exception" : undefined}
                  />
                  <Text type="secondary" style={{ fontSize: 13 }}>
                    任务 {job.id.slice(0, 8)} · 尝试 {job.attempts}/{job.max_attempts}
                  </Text>
                </Space>
                {job.error ? (
                  <Alert style={{ marginTop: 8 }} type="error" showIcon message={job.error} />
                ) : null}
              </div>
            ) : null}
          </Card>

          <Tabs
            items={[
              { key: "instruments", label: "标的", children: <InstrumentsTab datasetId={id} /> },
              { key: "calendar", label: "交易日历", children: <CalendarTab datasetId={id} /> },
              { key: "preview", label: "行情预览", children: <PreviewTab datasetId={id} /> },
            ]}
          />
        </>
      )}
    </Space>
  );
}

// ------------------------------------------------------------------ 标的
function InstrumentsTab({ datasetId }: { datasetId: string }) {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const query = useApiQuery<DatasetInstruments>(
    ["dataset-instruments", datasetId, page, pageSize],
    `/v1/datasets/${datasetId}/instruments${buildQuery({ page, page_size: pageSize })}`,
    { enabled: datasetId !== "" },
  );

  return (
    <>
      {query.isError ? (
        <Alert type="error" showIcon message={query.error.message} style={{ marginBottom: 12 }} />
      ) : null}
      <Table
        rowKey={(row) => row.instrument}
        size="small"
        loading={query.isLoading}
        dataSource={query.data?.items ?? []}
        pagination={{
          current: page,
          pageSize,
          total: query.data?.total ?? 0,
          showSizeChanger: true,
          onChange: (p, ps) => {
            setPage(p);
            setPageSize(ps);
          },
        }}
        columns={[
          { title: "标的代码", dataIndex: "instrument" },
          { title: "名称", dataIndex: "display_name" },
        ]}
      />
    </>
  );
}

// ------------------------------------------------------------------ 交易日历
function CalendarTab({ datasetId }: { datasetId: string }) {
  const [range, setRange] = useState<[Dayjs, Dayjs] | null>(null);
  const query = useApiQuery<DatasetCalendar>(
    ["dataset-calendar", datasetId, range?.[0]?.toISOString(), range?.[1]?.toISOString()],
    `/v1/datasets/${datasetId}/calendar${buildQuery({
      start: range?.[0]?.format("YYYY-MM-DD"),
      end: range?.[1]?.format("YYYY-MM-DD"),
    })}`,
  );

  return (
    <Space direction="vertical" size={12} style={{ width: "100%" }}>
      <DatePicker.RangePicker
        value={range}
        onChange={(value) => setRange(value as [Dayjs, Dayjs] | null)}
      />
      {query.isError ? (
        <Alert type="error" showIcon message={query.error.message} />
      ) : query.data ? (
        <Descriptions column={3} size="small" bordered style={{ maxWidth: 640 }}>
          <Descriptions.Item label="交易日数">{query.data.total}</Descriptions.Item>
          <Descriptions.Item label="起始">{query.data.start ?? "—"}</Descriptions.Item>
          <Descriptions.Item label="结束">{query.data.end ?? "—"}</Descriptions.Item>
        </Descriptions>
      ) : (
        <Spin />
      )}
    </Space>
  );
}

// ------------------------------------------------------------------ 行情预览
const FIELD_LABELS: Record<string, string> = {
  open: "开盘",
  high: "最高",
  low: "最低",
  close: "收盘",
  volume: "成交量",
  factor: "复权因子",
};

function PreviewTab({ datasetId }: { datasetId: string }) {
  const [instrument, setInstrument] = useState<string>("");
  const [range, setRange] = useState<[Dayjs, Dayjs] | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  // 标的下拉（前 500 个，支持自由输入代码）
  const instruments = useApiQuery<DatasetInstruments>(
    ["dataset-page", datasetId, "preview-instruments"],
    `/v1/datasets/${datasetId}/instruments${buildQuery({ page_size: 500 })}`,
  );

  const preview = useApiQuery<DatasetPreview>(
    ["dataset-preview", datasetId, instrument, range?.[0]?.toISOString(), range?.[1]?.toISOString(), page, pageSize],
    `/v1/datasets/${datasetId}/preview${buildQuery({
      instrument,
      start: range?.[0]?.format("YYYY-MM-DD"),
      end: range?.[1]?.format("YYYY-MM-DD"),
      page,
      page_size: pageSize,
    })}`,
    { enabled: instrument !== "" },
  );

  const columns = useMemo(() => {
    const fields = preview.data?.fields ?? ["open", "high", "low", "close", "volume", "factor"];
    return [
      { title: "日期", dataIndex: "date", fixed: "left" as const, width: 110 },
      ...fields.map((field) => ({
        title: `${FIELD_LABELS[field] ?? field}`,
        key: field,
        align: "right" as const,
        render: (_: unknown, row: DatasetPreview["items"][number]) =>
          row.values[field]?.toFixed(4) ?? "—",
      })),
    ];
  }, [preview.data]);

  return (
    <Space direction="vertical" size={12} style={{ width: "100%" }}>
      <Space wrap>
        <AutoComplete
          style={{ width: 260 }}
          placeholder="输入或选择标的代码（如 SH600000）"
          value={instrument}
          onChange={(value) => {
            setInstrument(String(value));
            setPage(1);
          }}
          options={(instruments.data?.items ?? []).map((item) => ({
            value: item.instrument,
            label: `${item.instrument} ${item.display_name}`,
          }))}
          showSearch
          filterOption={(input, option) =>
            String(option?.value ?? "").toLowerCase().includes(input.toLowerCase()) ||
            String(option?.label ?? "").toLowerCase().includes(input.toLowerCase())
          }
        />
        <DatePicker.RangePicker
          value={range}
          onChange={(value) => {
            setRange(value as [Dayjs, Dayjs] | null);
            setPage(1);
          }}
        />
      </Space>

      {preview.isError ? (
        <Alert type="warning" showIcon message={preview.error.message} />
      ) : (
        <Table
          rowKey="date"
          size="small"
          loading={preview.isLoading}
          dataSource={preview.data?.items ?? []}
          columns={columns}
          scroll={{ x: true }}
          pagination={{
            current: page,
            pageSize,
            total: preview.data?.total ?? 0,
            showSizeChanger: true,
            onChange: (p, ps) => {
              setPage(p);
              setPageSize(ps);
            },
          }}
        />
      )}
    </Space>
  );
}

export default function DatasetDetailPage() {
  const { id } = useParams<{ id: string }>();
  return (
    <AppShell>
      <RequireAuth>
        <DatasetDetailContent id={id} />
      </RequireAuth>
    </AppShell>
  );
}
