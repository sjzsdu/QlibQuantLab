import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

// 域名未定稿：构建时用 SITE_URL 覆盖，默认值是显式占位（绝不要带着 example.com 上线）。
const SITE_URL = process.env.SITE_URL ?? 'https://qqlab.example.com';
const GITHUB_URL = 'https://github.com/sjzsdu/QlibQuantLab';

const config: Config = {
  title: 'QlibQuantLab',
  tagline: '基于 Qlib 的多用户量化研究平台',
  favicon: 'img/favicon.ico',

  url: SITE_URL,
  baseUrl: '/',

  // 链接写错就让构建失败（P0 验收项：零 broken link），而不是留个 404 到线上。
  onBrokenLinks: 'throw',
  onBrokenAnchors: 'throw',

  markdown: {
    hooks: {
      onBrokenMarkdownLinks: 'throw',
    },
  },

  i18n: {
    // P0 只做中文；目录与配置按 i18n 结构就位，en 是 P2 的事。
    defaultLocale: 'zh-Hans',
    locales: ['zh-Hans'],
  },

  plugins: [
    [
      '@docusaurus/plugin-content-docs',
      {
        // 法务中心是独立的文档实例：路径挂在 /legal，导航与文档站分开，
        // 正文由 scripts/sync-legal.mjs 从后端 qqlab/legal 与根 LICENSE 生成。
        id: 'legal',
        path: 'legal',
        routeBasePath: 'legal',
        sidebarPath: './sidebarsLegal.ts',
        breadcrumbs: false,
        editUrl: `${GITHUB_URL}/tree/main/backend/src/qqlab/legal/`,
      },
    ],
  ],

  presets: [
    [
      'classic',
      {
        docs: {
          sidebarPath: './sidebars.ts',
          editUrl: `${GITHUB_URL}/tree/main/website/`,
          showLastUpdateAuthor: false,
          // 法务页是构建期生成物（不进 git），显示「最后更新」会持续产出
          // “Cannot infer the update date” 警告；0.1.0 阶段这项信息价值有限。
          showLastUpdateTime: false,
        },
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
        sitemap: {
          changefreq: 'weekly',
          priority: 0.5,
          // 404 不是可索引页面
          ignorePatterns: ['/404'],
        },
      } satisfies Preset.Options,
    ],
  ],

  themeConfig: {
    image: 'img/og-image.png',
    metadata: [
      {
        name: 'description',
        content:
          'QlibQuantLab 是基于 Qlib 的开源多用户量化研究平台：多组织数据与策略隔离、可插拔认证、审计留痕，训练与回测在独立 worker 容器执行。仅供研究、教学与技术验证使用。',
      },
      {property: 'og:type', content: 'website'},
      {property: 'og:site_name', content: 'QlibQuantLab'},
      {name: 'twitter:card', content: 'summary_large_image'},
    ],
    colorMode: {
      defaultMode: 'light',
      disableSwitch: false,
      respectPrefersColorScheme: true,
    },
    navbar: {
      title: 'QlibQuantLab',
      logo: {
        alt: 'QlibQuantLab',
        src: 'img/logo.svg',
        width: 32,
        height: 32,
      },
      items: [
        {to: '/features', label: '能力', position: 'left'},
        {to: '/architecture', label: '架构', position: 'left'},
        {to: '/docs/quickstart', label: '文档', position: 'left'},
        {
          label: '法务',
          position: 'left',
          items: [
            {to: '/legal/disclaimer', label: '免责声明'},
            {to: '/legal/risk', label: '风险提示'},
            {to: '/legal/terms', label: '用户协议'},
            {to: '/legal/license', label: 'License'},
          ],
        },
        {
          href: GITHUB_URL,
          label: 'GitHub',
          position: 'right',
        },
      ],
    },
    footer: {
      style: 'dark',
      links: [
        {
          title: '产品',
          items: [
            {label: '能力', to: '/features'},
            {label: '架构与边界', to: '/architecture'},
            {label: '文档', to: '/docs/quickstart'},
          ],
        },
        {
          title: '文档',
          items: [
            {label: '5 分钟跑起来', to: '/docs/quickstart'},
            {label: '核心概念', to: '/docs/concepts'},
            {label: '部署（模式 A / B）', to: '/docs/deployment'},
          ],
        },
        {
          title: '法务',
          items: [
            {label: '免责声明', to: '/legal/disclaimer'},
            {label: '风险提示', to: '/legal/risk'},
            {label: '用户协议', to: '/legal/terms'},
            {label: 'License', to: '/legal/license'},
          ],
        },
        {
          title: '源码',
          items: [{label: 'GitHub', href: GITHUB_URL}],
        },
      ],
      copyright: [
        '<div class="footer-legal">',
        '<strong>免责声明</strong>：本平台仅供研究、教学与技术验证使用，<b>不构成任何投资建议</b>；所有回测结果与指标均为历史数据的统计呈现，不代表未来收益。',
        '</div>',
        `<div class="footer-copy">© ${new Date().getFullYear()} QlibQuantLab 贡献者 · MIT License</div>`,
      ].join(''),
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
      additionalLanguages: ['bash', 'json', 'python', 'sql', 'yaml', 'diff'],
    },
    tableOfContents: {
      minHeadingLevel: 2,
      maxHeadingLevel: 4,
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
