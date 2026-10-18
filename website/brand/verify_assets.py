#!/usr/bin/env python3
"""品牌与站点素材验收：文件完整性、位图尺寸、ICO 内容、WCAG 对比度、截图非空白。

依赖：pillow（``pip install pillow``）；在 ``website/brand/`` 下运行：``python3 verify_assets.py``。
"""
from __future__ import annotations

import pathlib
import sys
import zipfile

from PIL import Image

BASE = pathlib.Path(__file__).parent
BRAND = BASE
SHOTS = BASE.parent / "static" / "img" / "screens"

EXPECT = {
    "logo-mark.svg": 0,
    "logo-mark-transparent.svg": 0,
    "logo-mark-mono-dark.svg": 0,
    "logo-mark-mono-white.svg": 0,
    "logo-horizontal-dark.svg": 0,
    "logo-horizontal-light.svg": 0,
    "favicon.svg": 0,
    "icon-maskable.svg": 0,
    "og-image.svg": 0,
    "og-image.png": (1200, 630),
    "logo-mark-512.png": (512, 512),
    "apple-touch-icon.png": (180, 180),
    "icon-192.png": (192, 192),
    "icon-512.png": (512, 512),
    "favicon-16.png": (16, 16),
    "favicon-32.png": (32, 32),
    "favicon-48.png": (48, 48),
    "favicon.ico": (48, 48),
    "README.md": 0,
    "make_assets.py": 0,
}

failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {msg}")
    if not cond:
        failures.append(msg)


print("== 品牌素材文件 ==")
for name, size in EXPECT.items():
    p = BRAND / name
    ok = p.is_file() and p.stat().st_size > 0
    check(ok, f"{name} 存在且非空 ({p.stat().st_size if p.is_file() else 0}B)")
    if ok and size:
        im = Image.open(p)
        check(im.size == size, f"{name} 尺寸 {im.size} == {size}")

print("== favicon.ico 内嵌尺寸 ==")
ico = BRAND / "favicon.ico"
with Image.open(ico) as im:
    sizes = sorted(im.ico.sizes()) if hasattr(im, "ico") else []
check(len(sizes) >= 3, f"ico 含 {len(sizes)} 个尺寸: {sizes}")

print("== WCAG 对比度 ==")


def _lin(c: int) -> float:
    c = c / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _lum(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contrast(a: str, b: str) -> float:
    la, lb = _lum(a), _lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


check(contrast("#FFFFFF", "#4F46E5") >= 4.5, f"白字/主色 {contrast('#FFFFFF', '#4F46E5'):.2f}:1 >= 4.5")
check(contrast("#FFFFFF", "#0891B2") >= 3.0, f"白笔画/渐变末端 {contrast('#FFFFFF', '#0891B2'):.2f}:1 >= 3.0 (图形)")
check(contrast("#FBBF24", "#0F172A") >= 4.5, f"强调/墨 {contrast('#FBBF24', '#0F172A'):.2f}:1 >= 4.5")
check(
    contrast("#FFFFFF", "#06B6D4") < 3.0,
    f"白/辅色 {contrast('#FFFFFF', '#06B6D4'):.2f}:1 仍不达标 —— 文档已列为禁用组合",
)

print("== SVG 中禁止出现旧配色末端 ==")
for svg in ("logo-mark.svg", "favicon.svg", "icon-maskable.svg"):
    txt = (BRAND / svg).read_text(encoding="utf-8")
    check("#0891B2" in txt, f"{svg} 底板渐变使用 #0891B2")
    check(not txt.count("#06B6D4"), f"{svg} 未残留 #06B6D4")

print("== 截图（站点实际引用 static/img/screens/*.webp）==")
SHOT_NAMES = ["login", "home", "projects", "factors", "legal"]
for n in SHOT_NAMES:
    p = SHOTS / f"{n}.webp"
    ok = p.is_file() and p.stat().st_size > 0
    check(ok, f"{n}.webp 非空 ({p.stat().st_size if p.is_file() else 0}B)")
    if ok:
        im = Image.open(p).convert("RGB")
        check(im.size == (2880, 1800), f"{n} 尺寸 {im.size} == (2880, 1800)")
        colours = im.getcolors(maxcolors=100000) or []
        check(len(colours) >= 200, f"{n} 颜色数 {len(colours)} >= 200（非空白）")

print()
if failures:
    print(f"❌ {len(failures)} 项未通过：")
    for f in failures:
        print("   -", f)
    sys.exit(1)
print(f"✅ 全部通过（{len(EXPECT)} 个品牌文件 + {len(SHOT_NAMES)} 张截图）")
