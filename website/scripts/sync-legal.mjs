#!/usr/bin/env node
/**
 * 法务文案同源生成器。
 *
 * 站点 `/legal/*` 的正文**不手写**：用户协议 / 风险提示 / 免责声明来自
 * `backend/src/qqlab/legal/*.md`（后端 `GET /api/v1/legal/{code}` 的同一份源文件），
 * License 页来自仓库根 `LICENSE`。后端改了文案，站点下次构建自动跟上。
 *
 * 治理规则见 website/README.md「内容来源」一节：禁止在网站里抄第二份法务文案。
 */
import {readFileSync, writeFileSync, mkdirSync, existsSync} from 'node:fs';
import {dirname, join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const siteRoot = resolve(here, '..');
const repoRoot = resolve(siteRoot, '..');
const legalSrc = join(repoRoot, 'backend', 'src', 'qqlab', 'legal');
const outDir = join(siteRoot, 'legal');

const DOCS = [
  {code: 'disclaimer', file: 'disclaimer.md', label: '免责声明', order: 1},
  {code: 'risk', file: 'risk.md', label: '风险提示', order: 2},
  {code: 'terms', file: 'terms.md', label: '用户协议', order: 3},
];

const DESCRIPTION = {
  disclaimer: 'QlibQuantLab 免责声明：平台仅供研究与教育目的使用，不构成投资建议，不代客理财。',
  risk: 'QlibQuantLab 风险提示：历史回测不等于未来收益、过拟合、数据质量、费用与流动性风险。',
  terms: 'QlibQuantLab 用户协议：服务性质、账户与组织、用户内容、合规使用与责任限制。',
  license: 'QlibQuantLab 采用 MIT License 开源。',
};

function fail(msg) {
  console.error(`[sync-legal] ${msg}`);
  process.exit(1);
}

function stripTitleAndStamp(body) {
  const lines = body.split('\n');
  // 后端文档以 `# 标题` 开头；站点侧标题由 front-matter 提供，避免出现两个 H1。
  if (lines[0]?.startsWith('# ')) {
    lines.shift();
  }
  while (lines.length && lines[0].trim() === '') {
    lines.shift();
  }
  // `版本：v1 ｜ 生效日期：2026-10-14` → 保留为页面顶部的元信息行
  let stamp = '';
  if (lines[0]?.startsWith('版本：')) {
    stamp = lines.shift().trim();
    while (lines.length && lines[0].trim() === '') {
      lines.shift();
    }
  }
  return {stamp, body: lines.join('\n').trimEnd()};
}

function checkMdxSafe(code, text) {
  // Docusaurus 3 把 .md 也按 MDX 解析，裸的 { } 与 <Tag> 会炸构建。
  const risky = [];
  if (/\{/.test(text)) risky.push('{');
  if (/<[A-Za-z/]/.test(text)) risky.push('<');
  if (risky.length) {
    fail(
      `${code}.md 含 MDX 敏感字符 ${risky.join(' ')}：请在后端源文件里用代码块或转义，` +
        '或在 sync-legal.mjs 里显式处理（不要手改生成物）。',
    );
  }
}

if (!existsSync(legalSrc)) {
  fail(`找不到后端法务源目录：${legalSrc}`);
}
mkdirSync(outDir, {recursive: true});

const written = [];

for (const doc of DOCS) {
  const srcPath = join(legalSrc, doc.file);
  if (!existsSync(srcPath)) fail(`缺少后端法务源文件：${srcPath}`);
  const raw = readFileSync(srcPath, 'utf8');
  const {stamp, body} = stripTitleAndStamp(raw);
  checkMdxSafe(doc.code, body);

  const front = [
    '---',
    `title: ${doc.label}`,
    `description: ${DESCRIPTION[doc.code] ?? doc.label}`,
    `sidebar_position: ${doc.order}`,
    'hide_table_of_contents: true',
    '---',
    '',
    '<!-- 本文件由 website/scripts/sync-legal.mjs 生成，不要手改。源文件：' +
      'backend/src/qqlab/legal/' +
      doc.file +
      ' -->',
    '',
  ].join('\n');

  const head = stamp ? `:::info ${stamp}\n:::\n\n` : '';
  const footer =
    '\n\n---\n\n> 本文与后端 `GET /api/v1/legal/' +
    doc.code +
    '` 返回的内容同源；若两者不一致，以后端为准并重新构建站点。\n';

  writeFileSync(join(outDir, `${doc.code}.md`), front + '\n' + head + body + footer, 'utf8');
  written.push(`${doc.code}.md`);
}

// ------------------------------------------------------------------ License
const licensePath = join(repoRoot, 'LICENSE');
if (!existsSync(licensePath)) {
  fail(`找不到 ${licensePath}（站点 License 页需要它）`);
}
const licenseText = readFileSync(licensePath, 'utf8').trimEnd();
const licenseMd = [
  '---',
  'title: License',
  `description: ${DESCRIPTION.license}`,
  'sidebar_position: 4',
  'hide_table_of_contents: true',
  '---',
  '',
  '<!-- 本文件由 website/scripts/sync-legal.mjs 生成，不要手改。源文件：仓库根 LICENSE -->',
  '',
  'QlibQuantLab 以 **MIT License** 发布。完整许可证文本如下（与仓库根 `LICENSE` 同源）：',
  '',
  '```text',
  licenseText,
  '```',
  '',
  '---',
  '',
  '> 使用、修改、分发本项目时请保留版权声明与许可声明。若你在自己的产品里使用本项目，' +
    'MIT 不提供任何形式的担保 —— 这与平台首页的免责声明一致。',
  '',
].join('\n');

writeFileSync(join(outDir, 'license.md'), licenseMd, 'utf8');
written.push('license.md');

console.log(`[sync-legal] 生成 ${written.length} 篇：${written.join(', ')} → website/legal/`);
