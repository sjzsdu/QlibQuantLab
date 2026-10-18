## 这个 PR 做了什么

<!-- 一两句话。评审者先看这里再看 diff。 -->

## 影响范围

- [ ] backend
- [ ] frontend
- [ ] website（官网 / 文档）
- [ ] qlib 链路 / worker
- [ ] 部署 / compose / CI

## 怎么验证的

<!-- 贴命令与结果，不要只写「测试通过」。 -->

```bash
# backend
cd backend && uv run ruff check . && uv run pytest -q

# frontend
cd frontend && pnpm lint && pnpm typecheck && pnpm build

# website（链接写错 / 法务不同源都会在这里红）
cd website && npm ci && npm run build
```

## 合规检查（涉及策略、回测、对外文案时勾选）

- [ ] 没有新增收益率 / 胜率 / 跑赢基准等效果承诺类表述
- [ ] 示例数据是演示数据，不含真实策略、真实资金或真实研究内容
- [ ] 法务文案没有在代码里另写一份（站点与 `GET /api/v1/legal/*` 同源）

## 关联 issue

<!-- Closes #123 -->
