import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';

/**
 * 用户文档的导航结构（P0 范围）。
 *
 * 与 `docs/`（内部阶段交付文档）刻意隔离：那边是交付报告，这边是给使用者的操作手册，
 * 两套并存、互不引用（内部文档可以链到官网，官网不链回内部文档）。
 */
const sidebars: SidebarsConfig = {
  docs: [
    {
      type: 'doc',
      id: 'quickstart',
      label: '5 分钟跑起来',
    },
    {
      type: 'doc',
      id: 'concepts',
      label: '核心概念',
    },
    {
      type: 'category',
      label: '模块指南',
      collapsed: false,
      items: ['guides/projects', 'guides/factors', 'guides/backtests'],
    },
    {
      type: 'doc',
      id: 'deployment',
      label: '部署（模式 A / B）',
    },
  ],
};

export default sidebars;
