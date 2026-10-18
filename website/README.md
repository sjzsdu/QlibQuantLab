# QlibQuantLab 官网（`website/`）

一个 Docusaurus 3 站点，同时承载三件事：**项目主页**（`/`、`/features`、`/architecture`）、**用户文档**（`/docs/*`）、**法务中心**（`/legal/*`）。

它刻意与 `frontend/`（产品前端，Next.js 15）**互不共享依赖**：产品升级 Next/React 不会把文档站一起拖下水，反之亦然。

## 本地开发

```bash
cd website
npm ci          # 首次
npm start       # http://localhost:3000
npm run build   # 生产构建（含链接校验）
npm run serve   # 预览构建产物
```

`npm start` / `npm run build` 都会先跑 `scripts/sync-legal.mjs`（见下）。

## 内容来源与治理

三条规则，违反任何一条都会在评审或 CI 里被发现：

1. **单一事实来源**：命令只从 `Makefile` / `docker-compose*.yml` / `.env.example` 抄，端口只从 `HOST_PORT_*` 抄，测试数字只从实际运行结果抄。不凭记忆写。
2. **能力清单从代码派生**：`/features` 与 `guides/*` 的条目对应 `frontend/src/app/**/page.tsx` 与 `backend/src/qqlab/api/v1/*.py`；新增模块时在同一 PR 里更新站点。
3. **法务文案同源**：`/legal/*` 的正文**不在本站手写**，由 `scripts/sync-legal.mjs` 从
   - `backend/src/qqlab/legal/{disclaimer,risk,terms}.md`（后端 `GET /api/v1/legal/{code}` 的同一份源文件）
   - 仓库根 `LICENSE`

   生成到 `website/legal/`（已 gitignore）。**不要手改生成物** —— 后端改文案，站点下次构建自动跟上。

构建期兜底：`onBrokenLinks` / `onBrokenAnchors` / `onBrokenMarkdownLinks` 全为 `throw`，任何死链都会让 `npm run build` 失败，因此 PR 里链接写错是红的。

## 目录结构

```text
website/
├── docusaurus.config.ts      # url（SITE_URL 可覆盖）/ i18n / navbar / footer 常驻免责声明
├── sidebars.ts               # 用户文档导航
├── sidebarsLegal.ts          # 法务中心导航
├── docs/                     # 用户文档（面向外部读者，与根 docs/ 的内部交付文档隔离）
│   ├── quickstart.md
│   ├── concepts.md
│   ├── deployment.md
│   └── guides/{projects,factors,backtests}.md
├── legal/                    # ⚙️ 生成物（sync-legal.mjs），不入库
├── src/
│   ├── css/custom.css        # 品牌 token（与 brand/README.md 的对比度表同源）
│   ├── pages/{index,features,architecture,404}.tsx
│   └── ...
├── static/img/               # 站点实际引用的素材（brand/ 的落地副本 + screens/*.webp）
├── brand/                    # 品牌源：make_assets.py（生成位图）、verify_assets.py（验收）、README.md（规范）
└── scripts/sync-legal.mjs
```

## 素材

`brand/` 是**源**，`static/img/` 是**站点引用**。改 logo 或配色时：

```bash
cd website/brand && python3 make_assets.py      # 重生成 SVG + 位图
cd .. && python3 brand/verify_assets.py         # 20 项验收：尺寸、ICO、WCAG 对比度、截图非空白
python3 scripts/sync-assets.mjs                 # 把品牌产物同步到 static/img
```

`verify_assets.py` 需要 `pillow`（`pip install pillow`）。它校验的其中一条是**硬约束**：白字压 `#06B6D4` 只有 2.43:1，不达标 —— 该颜色只允许出现在深色底上。

截图（`static/img/screens/*.webp`）是从真实部署栈上拍的，用演示数据（`dev-org` / `dev-user`）。**不要用真实策略或真实资金截图。**

## 部署

- `SITE_URL` 环境变量指定站点域名（默认占位 `https://qqlab.example.com` —— **不要带着它上线**）。
- 构建产物是纯静态文件，`website/build/` 可直接托管到 GitHub Pages / Cloudflare Pages / Netlify / 任意 CDN。
- CI 见 `.github/workflows/website.yml`：PR 只构建（含链接校验与 typecheck），`main` 构建后部署 Pages。

## 还没做的（P1 及以后）

- `/docs/api`（从 OpenAPI 派生）、`/docs/operations`、`/docs/testing`、`/docs/faq`、`/docs/glossary`
- `/roadmap`、`/changelog`、`/community/{contributing,security}`
- 站内搜索（P0 未接第三方搜索，`npm run build` 也不依赖它）
- 剩余 4 篇模块指南（data / models / jobs / audit）
- `en` 语言（i18n 配置已就位，但不启用第二个 locale）
- 回测详情与因子 IC 曲线两张截图（需要先导入 qlib 数据并跑一次回测）
