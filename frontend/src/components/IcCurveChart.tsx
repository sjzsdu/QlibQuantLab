"use client";

/**
 * 日度 rank-IC 曲线图（阶段 6 切片⑤）：echarts/core 按需引入（tree-shaking）。
 * 与净值曲线图（NavCurveChart）同构：SSR 关闭场景使用（调用方以 next/dynamic
 * ssr:false 引入），ResizeObserver 自适应容器宽度，卸载时 dispose。
 * 附加 0 轴虚线参考 —— IC 的正负号有含义，0 轴是判读基准。
 */

import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TooltipComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([
  LineChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
  MarkLineComponent,
  CanvasRenderer,
]);

interface IcCurveChartProps {
  /** ``[date, ic]`` 点列（后端 IcCurveOut.points，已 ≤1500 点降采样） */
  points: [string, number][];
  /** 图高（px） */
  height?: number;
  /** 系列名称（图例） */
  name?: string;
}

export default function IcCurveChart({ points, height = 280, name = "日度 rank-IC" }: IcCurveChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const chart = echarts.init(el);
    chartRef.current = chart;
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(el);
    return () => {
      observer.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    chart.setOption({
      animation: false,
      grid: { left: 56, right: 24, top: 32, bottom: 48 },
      tooltip: { trigger: "axis", valueFormatter: (value: unknown) => Number(value).toFixed(4) },
      legend: { show: points.length > 0, data: [name], top: 0 },
      dataZoom: [{ type: "inside" }, { type: "slider", height: 18, bottom: 8 }],
      xAxis: { type: "category", data: points.map((p) => p[0]), boundaryGap: false },
      yAxis: {
        type: "value",
        scale: true,
        axisLabel: { formatter: (value: number) => value.toFixed(2) },
      },
      series: [
        {
          name,
          type: "line",
          showSymbol: false,
          data: points.map((p) => p[1]),
          lineStyle: { width: 1.5 },
          markLine: {
            silent: true,
            symbol: "none",
            lineStyle: { type: "dashed", color: "#bfbfbf" },
            label: { formatter: "0", position: "insideEndTop", color: "#999" },
            data: [{ yAxis: 0 }],
          },
        },
      ],
    });
  }, [points, name]);

  return <div ref={containerRef} style={{ width: "100%", height }} />;
}
