"use client";

import { useState } from "react";
import { Alert } from "antd";
import Link from "next/link";

/**
 * 全站风险提示条。
 * 可关闭，但组件状态不持久化 —— 刷新页面后自动复现。
 */
export function RiskBanner() {
  const [visible, setVisible] = useState(true);
  if (!visible) return null;

  return (
    <Alert
      banner
      type="warning"
      showIcon
      closable
      onClose={() => setVisible(false)}
      message={
        <span>
          风险提示：本平台不提供任何投资建议，不保证任何策略收益，投资风险由用户自行承担。
          <Link href="/legal/risk" style={{ marginInlineStart: 8 }}>
            查看风险提示书
          </Link>
          <Link href="/legal/disclaimer" style={{ marginInlineStart: 12 }}>
            免责声明
          </Link>
        </span>
      }
    />
  );
}
