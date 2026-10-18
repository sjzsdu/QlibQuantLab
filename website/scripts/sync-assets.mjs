#!/usr/bin/env node
/**
 * 把品牌源（website/brand/）同步到站点实际引用的位置（website/static/img/）。
 *
 * 为什么需要：`brand/` 是 source of truth（所有位图由 make_assets.py 从 SVG 生成），
 * `static/img/` 是 Docusaurus 的静态目录。手复制会让两边漂移，所以用脚本对齐。
 *
 * 用法：
 *   node scripts/sync-assets.mjs           # 同步
 *   node scripts/sync-assets.mjs --check   # 只校验是否一致（不一致退出码 1，供 CI 用）
 */
import {copyFileSync, readFileSync, existsSync, mkdirSync} from 'node:fs';
import {dirname, join, resolve, basename} from 'node:path';
import {fileURLToPath} from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const siteRoot = resolve(here, '..');
const brandDir = join(siteRoot, 'brand');
const imgDir = join(siteRoot, 'static', 'img');

const checkOnly = process.argv.includes('--check');

/** brand 源文件 → static/img 落地名 */
const MAP = {
  'logo-mark.svg': 'logo.svg',
  'logo-horizontal-dark.svg': 'logo-horizontal-dark.svg',
  'logo-horizontal-light.svg': 'logo-horizontal-light.svg',
  'logo-mark-transparent.svg': 'logo-mark-transparent.svg',
  'favicon.svg': 'favicon.svg',
  'favicon.ico': 'favicon.ico',
  'apple-touch-icon.png': 'apple-touch-icon.png',
  'icon-192.png': 'icon-192.png',
  'icon-512.png': 'icon-512.png',
  'og-image.png': 'og-image.png',
  'og-image.svg': 'og-image.svg',
};

mkdirSync(imgDir, {recursive: true});

const problems = [];

for (const [src, dest] of Object.entries(MAP)) {
  const from = join(brandDir, src);
  const to = join(imgDir, dest);
  if (!existsSync(from)) {
    problems.push(`缺少品牌源文件：brand/${src}（先跑 brand/make_assets.py）`);
    continue;
  }
  if (checkOnly) {
    if (!existsSync(to)) {
      problems.push(`static/img/${dest} 不存在（跑 node scripts/sync-assets.mjs）`);
    } else if (readFileSync(from).compare(readFileSync(to)) !== 0) {
      problems.push(`static/img/${dest} 与 brand/${src} 不一致（跑 node scripts/sync-assets.mjs）`);
    }
    continue;
  }
  copyFileSync(from, to);
}

if (checkOnly) {
  if (problems.length) {
    console.error('[sync-assets] 未通过：');
    for (const p of problems) console.error(`  - ${p}`);
    process.exit(1);
  }
  console.log(`[sync-assets] ${Object.keys(MAP).length} 个文件一致`);
} else {
  console.log(`[sync-assets] 已同步 ${Object.keys(MAP).length} 个文件 → static/img/`);
  for (const p of problems) console.error(`  ! ${p}`);
  if (problems.length) process.exit(1);
}

// 截图不入 brand/：它们是实拍产物，直接放 static/img/screens（见 brand/README.md §8）
const screens = join(imgDir, 'screens');
if (!existsSync(screens)) {
  console.warn(`[sync-assets] 提示：${basename(screens)} 不存在，站点截图会 404`);
}
