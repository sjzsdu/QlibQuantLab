#!/usr/bin/env python3
"""生成 QlibQuantLab 官网品牌素材（SVG）。

设计说明：
- 图标 = 字母 Q（Quant）的环 + 上升折线内嵌（量化曲线）+ 圆头尾巴。
- 圆角方形底板承载渐变（indigo -> cyan），强调色 amber 只用于内部折线。
- 所有几何量写在 64x64 网格上，缩放到任意尺寸都不失真。
"""
from __future__ import annotations

import pathlib

OUT = pathlib.Path(__file__).parent

INDIGO = "#4F46E5"
CYAN = "#06B6D4"          # 深底装饰（曲线、光斑）用，深底上对比度高
PLATE_TO = "#0891B2"      # 图标底板渐变末端：保证白色笔画 ≥3:1（WCAG 非文本对比）
AMBER = "#FBBF24"
INK = "#0F172A"
MUTED = "#64748B"

# ---------------------------------------------------------------- 基础构件

def defs(prefix: str = "") -> str:
    return f"""
  <defs>
    <linearGradient id="{prefix}bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{INDIGO}"/>
      <stop offset="1" stop-color="{PLATE_TO}"/>
    </linearGradient>
    <linearGradient id="{prefix}sheen" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#FFFFFF" stop-opacity="0.28"/>
      <stop offset="1" stop-color="#FFFFFF" stop-opacity="0"/>
    </linearGradient>
  </defs>"""


def q_glyph(stroke: str = "#FFFFFF", accent: str = AMBER, w: float = 6.5) -> str:
    """Q 标记：环 + 尾巴 + 内部上升折线。坐标基于 64x64 网格。"""
    return f"""
    <circle cx="30.5" cy="32" r="15.5" fill="none" stroke="{stroke}" stroke-width="{w}"/>
    <path d="M 39.5 41 L 50.5 52" fill="none" stroke="{stroke}" stroke-width="{w}" stroke-linecap="round"/>
    <path d="M 23 36 L 27.5 30.5 L 32 33.5 L 37.5 25.5" fill="none" stroke="{accent}"
          stroke-width="{w * 0.46:.2f}" stroke-linecap="round" stroke-linejoin="round"/>"""


# ---------------------------------------------------------------- 1. 图标

def logo_mark() -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64" role="img" aria-label="QlibQuantLab">
  <title>QlibQuantLab</title>{defs()}
  <rect width="64" height="64" rx="15" fill="url(#bg)"/>
  <rect width="64" height="32" rx="15" fill="url(#sheen)"/>
  {q_glyph()}
</svg>
"""


def logo_mark_transparent() -> str:
    """无底板版：放在图片、浅色卡片、GitHub avatar 边缘用。"""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64" role="img" aria-label="QlibQuantLab">
  <title>QlibQuantLab</title>{defs()}
  {q_glyph(stroke=INDIGO, accent=PLATE_TO)}
</svg>
"""


def logo_mono(color: str) -> str:
    """单色版：印刷、单色场景。"""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64" role="img" aria-label="QlibQuantLab">
  <title>QlibQuantLab</title>
  {q_glyph(stroke=color, accent=color)}
</svg>
"""


# ---------------------------------------------------------------- 2. 横向组合标

def logo_horizontal(text_color: str, accent: str = AMBER, plate: bool = True) -> str:
    """图标 + 字标。字标用系统无衬线字体栈（见 brand.md 的转曲说明）。"""
    W, H = 268, 64
    plate_svg = f'<rect width="64" height="64" rx="15" fill="url(#bg)"/><rect width="64" height="32" rx="15" fill="url(#sheen)"/>' if plate else ""
    glyph = q_glyph() if plate else q_glyph(stroke=text_color, accent=accent)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="QlibQuantLab">
  <title>QlibQuantLab</title>{defs()}
  {plate_svg}
  {glyph}
  <text x="80" y="41" font-family="Helvetica Neue, Helvetica, Arial, sans-serif"
        font-size="30" font-weight="700" letter-spacing="-0.6" fill="{text_color}">Qlib<tspan font-weight="400" fill="{accent if not plate else text_color}">Quant</tspan>Lab</text>
</svg>
"""


# ---------------------------------------------------------------- 3. favicon

def favicon() -> str:
    """32px 优化：去掉内折线（16px 会糊），加粗环与尾巴。"""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="32" height="32" role="img" aria-label="QlibQuantLab">
  <title>QlibQuantLab</title>{defs()}
  <rect width="64" height="64" rx="16" fill="url(#bg)"/>
  <circle cx="30.5" cy="31" r="16" fill="none" stroke="#FFFFFF" stroke-width="8"/>
  <path d="M 40 40.5 L 52 52.5" fill="none" stroke="#FFFFFF" stroke-width="8" stroke-linecap="round"/>
  <path d="M 24 34 L 29 28.5 L 33 31.5 L 38 24" fill="none" stroke="{AMBER}"
        stroke-width="4.4" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
"""


# ---------------------------------------------------------------- 4. OG 图

def og_image() -> str:
    """1200x630 社交分享卡。深色底 + 网格 + 图标 + 定位语 + 免责小字。"""
    title = "QlibQuantLab"
    subtitle = "基于 Qlib 的开源多用户量化研究平台"
    bullets = "多租户隔离   ·   可插拔认证   ·   Qlib 物理隔离"
    disclaimer = "仅供研究、教学与技术验证使用，不构成任何投资建议。"
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 630" width="1200" height="630" role="img" aria-label="QlibQuantLab">
  <title>QlibQuantLab</title>
  <defs>
    <linearGradient id="ogbg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#0A0F1E"/>
      <stop offset="0.55" stop-color="#101B33"/>
      <stop offset="1" stop-color="#0A0F1E"/>
    </linearGradient>
    <linearGradient id="ogaccent" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{INDIGO}"/>
      <stop offset="1" stop-color="{PLATE_TO}"/>
    </linearGradient>
    <radialGradient id="ogglow" cx="0.5" cy="0.5" r="0.5">
      <stop offset="0" stop-color="{CYAN}" stop-opacity="0.20"/>
      <stop offset="1" stop-color="{CYAN}" stop-opacity="0"/>
    </radialGradient>
    <pattern id="oggrid" width="40" height="40" patternUnits="userSpaceOnUse">
      <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#FFFFFF" stroke-opacity="0.045" stroke-width="1"/>
    </pattern>
  </defs>

  <rect width="1200" height="630" fill="url(#ogbg)"/>
  <rect width="1200" height="630" fill="url(#oggrid)"/>
  <circle cx="1010" cy="120" r="330" fill="url(#ogglow)"/>

  <!-- 左上品牌条 -->
  <g transform="translate(80, 74)">
    <rect width="56" height="56" rx="13" fill="url(#ogaccent)"/>
    <g transform="translate(-2,-2) scale(0.9375)">
      <circle cx="30.5" cy="32" r="15.5" fill="none" stroke="#FFFFFF" stroke-width="6.5"/>
      <path d="M 39.5 41 L 50.5 52" fill="none" stroke="#FFFFFF" stroke-width="6.5" stroke-linecap="round"/>
      <path d="M 23 36 L 27.5 30.5 L 32 33.5 L 37.5 25.5" fill="none" stroke="{AMBER}"
            stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
    </g>
    <text x="74" y="38" font-family="Helvetica Neue, Helvetica, Arial, sans-serif" font-size="27"
          font-weight="600" letter-spacing="0.2" fill="#FFFFFF" fill-opacity="0.82">QlibQuantLab</text>
  </g>

  <!-- 主标题 -->
  <text x="80" y="316" font-family="Helvetica Neue, Helvetica, Arial, sans-serif" font-size="82"
        font-weight="700" letter-spacing="-2.5" fill="#FFFFFF">{title}</text>

  <!-- 定位语 -->
  <text x="80" y="392" font-family="PingFang SC, Hiragino Sans GB, Microsoft YaHei, sans-serif"
        font-size="34" font-weight="400" fill="#C7D2E5">{subtitle}</text>

  <!-- 关键特征 -->
  <g font-family="PingFang SC, Hiragino Sans GB, Microsoft YaHei, sans-serif" font-size="23" fill="#8FA3C4">
    <rect x="80" y="436" width="4" height="26" rx="2" fill="url(#ogaccent)"/>
    <text x="100" y="457">{bullets}</text>
  </g>

  <!-- 免责声明 -->
  <line x1="80" y1="536" x2="1120" y2="536" stroke="#FFFFFF" stroke-opacity="0.10" stroke-width="1"/>
  <text x="80" y="574" font-family="PingFang SC, Hiragino Sans GB, Microsoft YaHei, sans-serif"
        font-size="19" fill="#6B7A96">{disclaimer}</text>

  <!-- 右侧装饰：上升折线 + 节点（纯抽象，不含任何收益率数字） -->
  <g opacity="0.95">
    <path d="M 712 470 L 796 415 L 860 440 L 940 350 L 1020 375 L 1110 268"
          fill="none" stroke="url(#ogaccent)" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>
    <g fill="#0A0F1E" stroke="{CYAN}" stroke-width="3">
      <circle cx="712" cy="470" r="7"/><circle cx="790" cy="415" r="7"/><circle cx="860" cy="440" r="7"/>
      <circle cx="940" cy="350" r="7"/><circle cx="1020" cy="375" r="7"/>
    </g>
    <circle cx="1110" cy="268" r="9" fill="{AMBER}"/>
    <circle cx="1110" cy="268" r="20" fill="none" stroke="{AMBER}" stroke-opacity="0.35" stroke-width="2"/>
  </g>
</svg>
"""


# ---------------------------------------------------------------- 写盘



def icon_maskable() -> str:
    """PWA maskable / apple-touch-icon：满版渐变、无内圆角，圆角交给平台裁切。"""
    src = logo_mark()
    src = src.replace('rx="15" fill="url(#bg)"', 'rx="0" fill="url(#bg)"')
    src = src.replace('<rect width="64" height="32" rx="15" fill="url(#sheen)"/>',
                      '<rect width="64" height="32" rx="0" fill="url(#sheen)"/>')
    return src.replace('width="64" height="64"', 'width="512" height="512"', 1)


def rasterize(scale_to: dict[str, tuple[str, int, int]]) -> None:
    """用 rsvg-convert 出位图，再合成 .ico（需要 external rsvg + Pillow）。"""
    import subprocess

    from PIL import Image

    for src, out, w, h in [(v[0], k, v[1], v[2]) for k, v in scale_to.items()]:
        subprocess.run(["rsvg-convert", "-w", str(w), "-h", str(h), src, "-o", out], check=True)
    sizes = (16, 32, 48)
    for sz in sizes:
        subprocess.run(["rsvg-convert", "-w", str(sz), "-h", str(sz), "favicon.svg",
                        "-o", f"favicon-{sz}.png"], check=True)
    imgs = [Image.open(f"favicon-{sz}.png").convert("RGBA") for sz in sizes]
    imgs[-1].save("favicon.ico", format="ICO", sizes=[(s, s) for s in sizes], append_images=imgs[:-1])


if __name__ == "__main__" and "--raster" in __import__("sys").argv:
    rasterize({
        "logo-mark-512.png": ("logo-mark.svg", 512, 512),
        "og-image.png": ("og-image.svg", 1200, 630),
        "icon-512.png": ("icon-maskable.svg", 512, 512),
        "icon-192.png": ("icon-maskable.svg", 192, 192),
        "apple-touch-icon.png": ("icon-maskable.svg", 180, 180),
    })
    print("rasterized: png + favicon.ico")


# ---------------------------------------------------------------- 写盘

FILES = {
    "logo-mark.svg": logo_mark,
    "logo-mark-transparent.svg": logo_mark_transparent,
    "logo-mark-mono-dark.svg": lambda: logo_mono(INK),
    "logo-mark-mono-white.svg": lambda: logo_mono("#FFFFFF"),
    "logo-horizontal-dark.svg": lambda: logo_horizontal("#FFFFFF"),
    "logo-horizontal-light.svg": lambda: logo_horizontal(INK),
    "favicon.svg": favicon,
    "og-image.svg": og_image,
}

FILES["icon-maskable.svg"] = icon_maskable

for name, fn in FILES.items():
    (OUT / name).write_text(fn(), encoding="utf-8")
    print(f"wrote {name:34s} {len(fn()):6d} bytes")
