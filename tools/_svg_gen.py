"""生成 README 用 SVG: assets/hero.svg + assets/architecture.svg

一次性脚本, 不进仓库。坐标全部显式计算, 避免手写出错。
"""
from __future__ import annotations

import html
import pathlib

OUT = pathlib.Path(r"E:/Program/mcd/mcd-meal-optimizer/assets")
OUT.mkdir(parents=True, exist_ok=True)

FONT = "&apos;Segoe UI&apos;,&apos;PingFang SC&apos;,&apos;Microsoft YaHei&apos;,&apos;Hiragino Sans GB&apos;,sans-serif"
MONO = "&apos;Cascadia Code&apos;,&apos;SFMono-Regular&apos;,Consolas,&apos;Courier New&apos;,monospace"

C_BG0, C_BG1 = "#0a1120", "#13243f"
C_CARD, C_CARD_R = "#152239", "#1b2c4a"
C_STROKE = "#263a5c"
C_ACCENT = "#38bdf8"
C_AMBER = "#fbbf24"
C_TX = "#e8eefc"
C_SUB = "#93a7c6"
C_MUTED = "#5f7291"

DEFS = f"""  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{C_BG0}"/>
      <stop offset="1" stop-color="{C_BG1}"/>
    </linearGradient>
    <linearGradient id="accent" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#38bdf8"/>
      <stop offset="1" stop-color="#818cf8"/>
    </linearGradient>
  </defs>"""


def esc(s: str) -> str:
    return html.escape(s, quote=True).replace("'", "&apos;")


def txt(x, y, s, size, fill, weight="400", anchor="start", font=FONT, opacity=None, spacing=None):
    extra = ""
    if opacity is not None:
        extra += f' opacity="{opacity}"'
    if spacing is not None:
        extra += f' letter-spacing="{spacing}"'
    return (
        f'  <text x="{x}" y="{y}" font-size="{size}" fill="{fill}" font-weight="{weight}"'
        f' text-anchor="{anchor}" font-family="{font}"{extra}>{esc(s)}</text>'
    )


def card(x, y, w, h, fill=C_CARD, stroke=C_STROKE, rx=12, sw=1):
    return (
        f'  <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" '
        f'stroke="{stroke}" stroke-width="{sw}"/>'
    )


def arrow(x1, y1, x2, y2, color=C_STROKE, sw=2.2):
    return (
        f'  <line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" '
        f'stroke-width="{sw}" marker-end="url(#ah)"/>'
    )


# ============================================================ hero.svg

def build_hero() -> str:
    W, H = 1280, 380
    p = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="麦麦算盘 —— 麦当劳营养×预算双目标餐搭求解器">',
        DEFS,
        f'  <rect width="{W}" height="{H}" rx="18" fill="url(#bg)"/>',
    ]
    # 装饰网格
    p.append('  <g opacity="0.05" stroke="#ffffff" stroke-width="1">')
    for gx in range(80, W, 80):
        p.append(f'    <line x1="{gx}" y1="0" x2="{gx}" y2="{H}"/>')
    for gy in range(40, H, 40):
        p.append(f'    <line x1="0" y1="{gy}" x2="{W}" y2="{gy}"/>')
    p.append("  </g>")
    # 左侧金色竖条
    p.append(f'  <rect x="0" y="0" width="7" height="{H}" rx="3.5" fill="url(#accent)"/>')

    LX = 62
    # 顶部标签
    p.append(card(LX, 52, 372, 38, fill="#12203a", stroke="#2b4470", rx=19))
    p.append(txt(LX + 20, 77, "麦当劳程序员创意开发大赛 · 参赛作品", 17, C_ACCENT, weight="600"))

    # 主标题
    p.append(txt(LX, 178, "麦麦算盘", 84, C_TX, weight="800", spacing="2"))
    p.append(txt(LX + 4, 226, "麦当劳营养 × 预算双目标餐搭求解器", 26, C_SUB, weight="500"))
    p.append(txt(LX + 4, 268, "在预算内吃够营养，在营养达标时花得最少", 21, "#7dd3fc"))

    # 命令行小样
    p.append(card(LX, 292, 578, 62, fill="#0d1729", stroke="#22375a", rx=9))
    p.append(txt(LX + 16, 316, "$ python -m mcd_meal_optimizer plan --city 上海", 14.5, "#9ad8ff", font=MONO))
    p.append(txt(LX + 16, 340, "      --kcal-min 550 --kcal-max 800 --protein 30 --price-check", 13, "#7fb8e8", font=MONO))

    # 右侧四张数据卡 2x2
    facts = [
        ("158", "营养库餐品", "热量 / 蛋白 / 脂肪 / 碳水"),
        ("64", "单元测试全绿", "随机差分 + 变异验证"),
        ("¥23.80", "预测价 = 真实成交价", "calculate-price 逐分吻合"),
        ("82/121", "营养完整候选", "缺数据一律排除出解"),
    ]
    cw, ch = 292, 116
    xs = [LX + 592 + 0, LX + 592 + cw + 20]
    ys = [52, 52 + ch + 20]
    for i, (big, label, sub) in enumerate(facts):
        cx = xs[i % 2]
        cy = ys[i // 2]
        p.append(card(cx, cy, cw, ch))
        p.append(f'  <rect x="{cx}" y="{cy}" width="4" height="{ch}" rx="2" fill="url(#accent)"/>')
        size = 40 if len(big) <= 4 else 32
        p.append(txt(cx + 24, cy + 56, big, size, C_TX if i != 3 else C_AMBER, weight="800"))
        p.append(txt(cx + 24, cy + 84, label, 17, C_SUB, weight="600"))
        p.append(txt(cx + 24, cy + 105, sub, 13.5, C_MUTED))

    p.append("</svg>")
    return "\n".join(p)


# ============================================================ architecture.svg

def build_arch() -> str:
    W, H = 1280, 830
    p = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="麦麦算盘架构总览">',
        DEFS,
        '  <marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        f'    <path d="M 0 0 L 10 5 L 0 10 z" fill="{C_STROKE}"/>'
        "  </marker>",
        f'  <rect width="{W}" height="{H}" rx="18" fill="url(#bg)"/>',
    ]

    # 标题
    p.append(txt(60, 52, "麦麦算盘 · 架构总览", 32, C_TX, weight="800"))
    p.append(txt(1220, 52, "零第三方依赖 · Python 3.10+ · 求解器与取数解耦", 15, C_MUTED, anchor="end"))
    p.append(f'  <line x1="60" y1="70" x2="1220" y2="70" stroke="{C_STROKE}" stroke-width="1"/>')

    def band(label, y, h):
        p.append(txt(60, y - 14, label, 19, C_ACCENT, weight="700"))
        p.append(card(40, y, 1200, h, fill="#0e1a2e", stroke="#203353", rx=14))

    def box(x, y, w, h, titles, descs, accent=C_ACCENT, tsize=14.5, dsize=13):
        p.append(card(x, y, w, h, fill=C_CARD, stroke=C_CARD_R))
        p.append(f'  <rect x="{x}" y="{y}" width="3.5" height="{h}" rx="1.75" fill="{accent}"/>')
        ty = y + 26
        for t in titles:
            p.append(txt(x + 16, ty, t, tsize, C_TX, weight="600", font=MONO))
            ty += 19
        ty += 6
        for d in descs:
            p.append(txt(x + 16, ty, d, dsize, C_SUB))
            ty += 17

    def vgap(y0, y1, label):
        p.append(arrow(640, y0, 640, y1))
        p.append(card(556, (y0 + y1) / 2 - 15, 168, 30, fill="#0d1729", stroke="#24395c", rx=15))
        p.append(txt(640, (y0 + y1) / 2 + 5, label, 14, "#9ad8ff", anchor="middle", weight="600"))

    # ---------- ① 数据层
    band("①  数据层 · 麦当劳 MCP（Streamable HTTP · Bearer 鉴权 · 35 个工具）", 118, 124)
    bw, gap = 248, 56
    bx = [60 + i * (bw + gap) for i in range(4)]
    box(bx[0], 130, bw, 100,
        ["list-nutrition-foods"],
        ["158 款餐品营养数据", "热量/蛋白/脂肪/碳水/钠/钙"])
    box(bx[1], 130, bw, 100,
        ["query-meals", "query-meal-detail"],
        ["121 项真实门店菜单", "套餐默认组成 → 拆成单品"])
    box(bx[2], 130, bw, 100,
        ["mall-points-products", "query-party-store"],
        ["门店发现（不依赖账号配置）", "城市 → 真实 storeCode"])
    box(bx[3], 130, bw, 100,
        ["query-my-coupons", "available-coupons"],
        ["券池：满减/固定价/折扣", "→ 计入到手价"])

    vgap(242, 292, "解析 / 归一化")

    # ---------- ② 解析层
    band("②  解析层 · parsers.py（把非结构化返回变成结构化对象）", 292, 108)
    bw5, gap5 = 224, 10
    bx5 = [60 + i * (bw5 + gap5) for i in range(5)]
    for i, (t, d) in enumerate([
        ("紧凑表格解析", "缩进 CSV → 营养字典"),
        ("Markdown 券解析", "5 类券规则自动识别"),
        ("分类菜单归一", "categories 反查 meals"),
        ("套餐轮次拆解", "rounds.isDefault=1"),
        ("名称多重集匹配", "保留区分字，拒绝近似"),
    ]):
        p.append(card(bx5[i], 304, bw5, 84, fill=C_CARD, stroke=C_CARD_R))
        p.append(f'  <rect x="{bx5[i]}" y="304" width="3.5" height="84" rx="1.75" fill="#818cf8"/>')
        p.append(txt(bx5[i] + 16, 334, t, 15.5, C_TX, weight="600"))
        p.append(txt(bx5[i] + 16, 358, d, 13, C_SUB))
        p.append(txt(bx5[i] + 16, 378, "", 13, C_SUB))

    vgap(400, 450, "约束建模")

    # ---------- ③ 求解层
    band("③  求解层 · optimizer.py（纯函数，不依赖网络）", 450, 152)
    p.append(card(60, 462, 748, 128, fill=C_CARD, stroke=C_CARD_R))
    p.append(f'  <rect x="60" y="462" width="3.5" height="128" rx="1.75" fill="url(#accent)"/>')
    p.append(txt(78, 492, "双约束动态规划求解器", 18, C_TX, weight="700"))
    for i, line in enumerate([
        "state = (热量桶, 蛋白桶, 必需掩码)",
        "value = 最低到手价（已计入券后价）",
        "objective = min_price / max_protein / best_value",
    ]):
        p.append(txt(78, 518 + i * 21, line, 14, "#9ad8ff", font=MONO))
    p.append(txt(78, 580, "DP vs 穷举 120 组随机差分：结果必须完全一致", 13, C_MUTED))

    p.append(card(832, 462, 388, 128, fill="#1e1a0e", stroke="#6b5518"))
    p.append(f'  <rect x="832" y="462" width="3.5" height="128" rx="1.75" fill="{C_AMBER}"/>')
    p.append(txt(850, 492, "营养门禁（诚实边界）", 18, C_AMBER, weight="700"))
    p.append(txt(850, 520, "partial / none  →  排除出解", 14, C_TX, font=MONO))
    p.append(txt(850, 544, "绝不按 0 kcal / 0 g 参与计算", 13.5, C_SUB))
    p.append(txt(850, 566, "否则会伪造出「营养达标」结论", 13.5, C_SUB))

    vgap(602, 652, "输出 / 复核")

    # ---------- ④ 输出层
    band("④  输出层 · planner.py / cli.py", 652, 144)
    bw4, gap4 = 248, 56
    bx4 = [60 + i * (bw4 + gap4) for i in range(4)]
    outs = [
        ("方案 Top-N", ["营养 / 价格 / 组成", "逐条可解释"], C_ACCENT),
        ("calculate-price", ["下单前强制复算", "预测价 = 真实成交价"], C_ACCENT),
        ("--confirm 闸门", ["未确认直接抛异常", "且不发出任何请求"], C_AMBER),
        ("create-order", ["→ cancel-order 撤单", "端到端已实测闭合"], C_ACCENT),
    ]
    for i, (t, ds, ac) in enumerate(outs):
        p.append(card(bx4[i], 666, bw4, 112, fill=C_CARD, stroke=C_CARD_R))
        p.append(f'  <rect x="{bx4[i]}" y="666" width="3.5" height="112" rx="1.75" fill="{ac}"/>')
        p.append(txt(bx4[i] + 16, 700, t, 16, C_TX, weight="700", font=MONO))
        for j, d in enumerate(ds):
            p.append(txt(bx4[i] + 16, 726 + j * 19, d, 13.5, C_SUB))
    for gx in (308, 612, 916):
        p.append(arrow(gx + 8, 722, gx + 50, 722, sw=2.5))

    # 底部说明
    p.append(f'  <line x1="60" y1="806" x2="1220" y2="806" stroke="{C_STROKE}" stroke-width="1"/>')
    p.append(txt(60, 826, "仓库内 examples/real-menu-1450713.json 为真实门店快照（121 项），不联网可离线复现同一结果", 14, C_MUTED))

    p.append("</svg>")
    return "\n".join(p)


hero = build_hero()
arch = build_arch()
(OUT / "hero.svg").write_text(hero + "\n", encoding="utf-8")
(OUT / "architecture.svg").write_text(arch + "\n", encoding="utf-8")
print("hero.svg      ", len(hero), "chars")
print("architecture.svg", len(arch), "chars")

# XML 合法性校验
import xml.etree.ElementTree as ET

for f in ("hero.svg", "architecture.svg"):
    try:
        ET.parse(OUT / f)
        print("XML OK  :", f)
    except ET.ParseError as e:
        print("XML FAIL:", f, e)
        raise SystemExit(1)
