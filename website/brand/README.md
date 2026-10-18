# QlibQuantLab 品牌与素材规范 v1

> 本目录是官网（`website/`）的素材来源。所有位图都由 `make_assets.py` 从 SVG 生成，改样式只改脚本，不要手改产物。

## 1. 名称与写法

| 项 | 规范 |
|---|---|
| 正式名 | `QlibQuantLab`（驼峰，中间不加空格、不加连字符） |
| 缩写 | `QQL`（仅用于内部沟通，不对外替代正式名） |
| 代码前缀 | `qqlab`（包名 `qqlab`、镜像名 `qqlab-*`、环境变量与仓库一致） |
| 中文称呼 | 「QlibQuantLab 量化研究平台」，不译作品牌名 |
| 禁止写法 | `Qlib Quant Lab`、`QlibQuantlab`、`Qlib-Quant-Lab` |

## 2. 一句话（slogan 候选）

推荐 **A**：只陈述事实、不含任何效果暗示，可直接放首页与 OG 图，合规风险为零。

| # | 一句话 | 适用 | 备注 |
|---|---|---|---|
| **A** ✅ | 基于 Qlib 的多用户量化研究平台 | 首页主标题下方、OG 图、GitHub About | 与 README 首段一致，最稳 |
| B | 开源的量化研究基础设施：多租户、可审计、Qlib 原生 | `/features` 首屏 | 信息密度高，偏工程师语气 |
| C | 让量化研究像写代码一样可复现 | 技术文章标题 | 有主张，但接近"效果承诺"，**不用于首页** |

**长版定位语**（用于 `/features` 首屏段落）：
> 为团队提供多组织数据与策略隔离、可插拔认证与审计留痕；训练与回测跑在独立 worker 容器中，Web 进程永不 `import qlib`，让研究过程可复现、可追溯。

## 3. 配色（可直接粘进 `website/src/css/custom.css`）

```css
:root {
  --qql-indigo:      #4F46E5;  /* 主色：链接、按钮、选中态 */
  --qql-indigo-deep: #3F37C9;  /* 主色深：hover / 白字安全底（8.07:1） */
  --qql-cyan:        #06B6D4;  /* 辅色：仅用于深色底上的曲线、光斑 */
  --qql-cyan-deep:   #0891B2;  /* 底板渐变末端：白笔画仍 ≥3:1 */
  --qql-amber:       #FBBF24;  /* 强调色：只做点缀（折线、高亮点），不做大面积 */
  --qql-ink:         #0F172A;  /* 正文（浅色主题） */
  --qql-slate:       #64748B;  /* 次要文字 */
  --qql-mist:        #C7D2E5;  /* 深色底上的次要文字 */
  --qql-bg-dark:     #0A0F1E;  /* 深色主题背景 */
}
```

**对比度实测**（WCAG：正文 4.5:1，图形/大字 3:1）

| 组合 | 比值 | 判定 |
|---|---|---|
| 白字 / `#4F46E5` | 6.29:1 | AA ✅ |
| 白字 / `#3F37C9` | 8.07:1 | AAA ✅ |
| 白笔画 / `#0891B2`（图标渐变最亮端） | 3.68:1 | 图形 ✅ |
| `#FBBF24` / `#0F172A` | 10.69:1 | AAA ✅ |
| `#C7D2E5` / `#0A0F1E` | 12.53:1 | AAA ✅ |
| `#64748B` / 白 | 4.76:1 | AA ✅ |
| **白字 / `#06B6D4`** | **2.43:1** | **❌ 禁止** |

> 最后一行是硬约束：**`#06B6D4` 上不要放白字/白笔画**。它只用于深色底（`#0A0F1E` 上对比度高）。图标底板之所以用 `#0891B2` 而非 `#06B6D4`，就是为了让白色 Q 笔画站得住。

## 4. 字体

| 用途 | 字体栈 |
|---|---|
| 中文正文 | `PingFang SC, Hiragino Sans GB, Microsoft YaHei, system-ui, sans-serif` |
| 英文/数字 | `Inter, -apple-system, "Helvetica Neue", Arial, sans-serif` |
| 代码与指标 | `JetBrains Mono, SFMono-Regular, Menlo, Consolas, monospace` |

> 字标当前用 SVG `<text>` + 系统字体栈渲染。正式对外发布前建议由设计师**转曲**（outline 成 path），否则不同机器上字宽会略有差异。

## 5. Logo 用法

**最小尺寸**：图标 `24px`；横向组合标 `120px` 宽。小于此值只用 `favicon.svg`（已为 16px 优化，去掉了内部折线）。

**安全留白**：四周留白 ≥ 图标宽度的 `1/4`（Q 环半径的一半），任何元素不得进入该区域。

**禁例**（评审直接打回）：
- 拉伸变形 / 改变宽高比
- 更换渐变方向或替换颜色
- 叠加阴影、描边、外发光
- 旋转、倾斜
- 放在与渐变同明度的底上（如中灰、紫底）
- 在图标上再压文字

**底色搭配**：深底用 `logo-horizontal-dark.svg`；浅底用 `logo-horizontal-light.svg`；单色印刷用 `logo-mark-mono-*.svg`。

## 6. 文件清单

| 文件 | 尺寸 | 用途 → 落地位置 |
|---|---|---|
| `logo-mark.svg` | 64×64 矢量 | 站点 Logo → `website/static/img/logo.svg` |
| `logo-mark-transparent.svg` | 64×64 | 浅色卡片、文档内嵌、邮件签名 |
| `logo-mark-mono-dark.svg` / `-white.svg` | 64×64 | 单色印刷、水印 |
| `logo-horizontal-dark.svg` | 268×64 | 深色导航栏、README 顶部横幅 |
| `logo-horizontal-light.svg` | 268×64 | 浅色导航栏、打印文档 |
| `favicon.svg` | 32×32 优化 | 浏览器标签页矢量源 |
| `favicon.ico` | 16/32/48 | 站点根目录（老浏览器兜底） |
| `favicon-{16,32,48}.png` | 位图 | PWA manifest、平台抓取 |
| `apple-touch-icon.png` | 180×180 | iOS 添加到主屏 → `website/static/img/apple-touch-icon.png` |
| `icon-192.png` / `icon-512.png` | 位图 | PWA manifest（maskable） |
| `icon-maskable.svg` | 矢量源 | 上面两张位图的源文件 |
| `og-image.svg` / `og-image.png` | 1200×630 | 社交分享卡（GitHub / 微信 / X） |
| `logo-mark-512.png` | 512×512 | GitHub 组织头像、文档站卡片 |
| `../screenshots/*.webp` | 2880×1800 | 首页截图位（体积约为 PNG 的 35–40%） |
| `../screenshots/*@2x.png` | 2880×1800 | 需要无损时用 |

## 7. OG 图规范

- 尺寸 `1200×630`；安全区四周 `40px`（部分平台会裁切边缘）
- 左侧固定结构：品牌条（y=74）→ 主标题（y=316）→ 定位语（y=392）→ 特征行（y=457）→ 分隔线（y=536）→ 免责声明（y=574）
- 右侧装饰是**纯抽象的上升折线与节点，不含任何数值、收益率、日期**——这是合规要求，不是审美选择
- 每页独立 OG 时只替换「定位语」与「特征行」，其余结构与配色不动

## 8. 截图清单与再生成方法

| 文件 | 页面 | 状态 |
|---|---|---|
| `login.webp` | `/login` | ✅ 已拍 |
| `home.webp` | `/`（入口卡片 + 风险提示 + 免责声明） | ✅ 已拍 |
| `projects.webp` | `/projects`（2 个演示项目） | ✅ 已拍 |
| `factors.webp` | `/factors`（6 个演示因子） | ✅ 已拍 |
| `legal.webp` | `/legal/disclaimer` | ✅ 已拍 |
| 待补 | `/backtests/[id]`（回测曲线 + 指标卡）、`/factors/[id]`（IC 曲线） | ⏳ 需先导入 qlib 数据并跑一次回测 |

再生成命令（`chrome-headless-shell` + 持久化 profile，cookie 跨端口共享）：

```bash
CHROME="$HOME/Library/Caches/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-mac-arm64/chrome-headless-shell"
# 1) 建立登录态（cookie 写入 profile，后续页面复用）
"$CHROME" --headless --no-sandbox --user-data-dir=/tmp/p1 --screenshot=/tmp/_s.png \
  "http://localhost:8000/api/v1/auth/mock/enter?profile=admin&redirect_to=/"
# 2) 拍页面（1440×900 @2x）
"$CHROME" --headless --no-sandbox --hide-scrollbars --user-data-dir=/tmp/p1 \
  --window-size=1440,900 --force-device-scale-factor=2 --virtual-time-budget=15000 \
  --screenshot=./home.png "http://localhost:3000/"
```

## 9. 合规红线（每次加素材都过一遍）

- 不出现收益率、胜率、跑赢基准、"提升 XX%" 等效果表述
- 不出现真实券商/策略名称或真实资金规模
- 截图里的数据必须是演示数据（`dev-user @ dev-org`），不得含真实研究内容
- 每张对外发布的图，若含页面截图，页面底部应能看到免责声明或应在文案中附免责声明
- 免责声明文案与 `GET /api/v1/legal/disclaimer` **同源**，站点不要另写一份
