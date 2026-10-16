"use client";

/**
 * 净值曲线图（阶段 5）：echarts/core 按需引入（tree-shaking）。
 * SSR 关闭场景使用（调用方以 next/dynamic ssr:false 引入），
 * ResizeObserver 自适应容器宽度，卸载时 dispose。
 */

import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([
  LineChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
  CanvasRenderer,
]);

export interface NavPoint {
  date: string;
  nav: number;
}

interface NavCurveChartProps {
  points: NavPoint[];
  /** 图高（px） */
  height?: number;
  /** 单系列名称（图例） */
  name?: string;
}

export default function NavCurveChart({ points, height = 360, name = "策略净值" }: NavCurveChartProps) {
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
      xAxis: { type: "category", data: points.map((p) => p.date), boundaryGap: false },
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
          data: points.map((p) => p.nav),
          lineStyle: { width: 2 },
          areaStyle: { opacity: 0.08 },
        },
      ],
    });
  }, [points, name]);

  return <div ref={containerRef} style={{ width: "100%", height }} />;
}
