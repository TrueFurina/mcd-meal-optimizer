"""麦当劳 MCP 返回内容的解析器。

MCP 工具返回的并不是结构化 JSON, 而是若干种「文本套 JSON / 文本套表格 /
文本套 Markdown」的形态。本模块把这些形态统一解析成领域模型。

已支持的形态 (均以真实响应为准):

1. ``list-nutrition-foods`` 的紧凑表格::

       [160]{productName,nutritionDescription,energyKj,energyKcal,...}:
         猪柳麦满分,null,1288,308,16,16,24,781,213
         ...

2. ``query-my-coupons`` 的 Markdown 券列表::

       ## 新人专享-中杯美式7折
       - **优惠**: ¥13.3 (用券价格)

3. ``available-coupons`` 的 ``- 优惠券标题：xxx`` 块列表。

4. ``query-meals`` 的菜单 (字段名不固定, 采用宽容归一化)。
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from .models import Coupon, MenuItem, Nutrition

# --------------------------------------------------------------- 紧凑表格

_TABLE_HEADER = re.compile(r"\[(\d+)\]\{([^}]*)\}\s*:\s*$")


def parse_compact_table(text: str) -> list[dict[str, str]]:
    """解析 ``[N]{col1,col2}:`` + 缩进行的紧凑表格。"""
    if not isinstance(text, str) or "{" not in text:
        return []

    rows: list[dict[str, str]] = []
    columns: list[str] = []
    for line in text.splitlines():
        m = _TABLE_HEADER.search(line.strip())
        if m:
            columns = [c.strip() for c in m.group(2).split(",") if c.strip()]
            continue
        if not columns or not line.strip():
            continue
        if line.startswith(" ") or line.startswith("\t"):
            cells = [c.strip() for c in line.strip().split(",")]
            if len(cells) < len(columns):
                cells += [""] * (len(columns) - len(cells))
            rows.append(dict(zip(columns, cells)))

    return rows


def _num(value: str) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return 0.0


def parse_nutrition_table(text: str) -> dict[str, Nutrition]:
    """解析营养表, 返回 ``{餐品名: Nutrition}``。"""
    result: dict[str, Nutrition] = {}
    for row in parse_compact_table(text):
        name = (row.get("productName") or "").strip()
        if not name:
            continue
        result[name] = Nutrition(
            energy_kj=_num(row.get("energyKj", "0")),
            energy_kcal=_num(row.get("energyKcal", "0")),
            protein=_num(row.get("protein", "0")),
            fat=_num(row.get("fat", "0")),
            carbohydrate=_num(row.get("carbohydrate", "0")),
            sodium=_num(row.get("sodium", "0")),
            calcium=_num(row.get("calcium", "0")),
        )
    return result


# ----------------------------------------------------------------- 优惠券

_PRICE_RE = re.compile(r"[¥￥]\s*(\d+(?:\.\d+)?)")
_PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*折")
_THRESHOLD_OFF_RE = re.compile(
    r"满\s*(\d+(?:\.\d+)?)\s*元?\s*减\s*(\d+(?:\.\d+)?)\s*元?"
)


def parse_my_coupons_markdown(text: str) -> list[Coupon]:
    """解析 ``query-my-coupons`` 返回的 Markdown 券列表。"""
    coupons: list[Coupon] = []
    if not isinstance(text, str):
        return coupons

    blocks = re.split(r"^##\s+", text, flags=re.MULTILINE)
    for block in blocks[1:]:
        lines = block.strip().splitlines()
        if not lines:
            continue
        title = lines[0].strip()
        if not title:
            continue
        body = "\n".join(lines[1:])

        tags: list[str] = []
        m = re.search(r"\*\*标签\*\*\s*[:：]\s*(.+)", body)
        if m:
            tags = [t.strip() for t in m.group(1).split(",") if t.strip()]

        coupon = _classify_coupon(title, body, tags)
        coupon.raw = block.strip()
        coupons.append(coupon)
    return coupons


def parse_available_coupons(text: str) -> list[Coupon]:
    """解析 ``available-coupons`` 返回的 ``- 优惠券标题：`` 块列表。"""
    coupons: list[Coupon] = []
    if not isinstance(text, str):
        return coupons

    chunks = re.split(r"\n\s*-\s*优惠券标题\s*[:：]\s*", text)
    for chunk in chunks[1:]:
        title = chunk.splitlines()[0].strip().rstrip("\\").strip()
        if not title:
            continue
        body = chunk
        status = ""
        m = re.search(r"状态\s*[:：]\s*([^\n\\]+)", body)
        if m:
            status = m.group(1).strip()
        coupon = _classify_coupon(title, body, [status] if status else [])
        coupon.raw = chunk.strip()[:400]
        coupons.append(coupon)
    return coupons


def _classify_coupon(title: str, body: str, tags: list[str]) -> Coupon:
    """从券标题与正文推断券的类型与参数。

    识别顺序: 满减 > 买一送一 > 免费 > N元固定价 > 折扣 > 券后价 > 未知。
    """
    scope = _guess_scope(title)

    m = _THRESHOLD_OFF_RE.search(title) or _THRESHOLD_OFF_RE.search(body)
    if m:
        return Coupon(
            title=title,
            kind="threshold_off",
            threshold=float(m.group(1)),
            price=float(m.group(2)),
            scope=scope,
            tags=tags,
        )

    if "买一送一" in title:
        return Coupon(title=title, kind="bogo", scope=scope, tags=tags)

    if title.startswith("免费") or "免费" in title:
        return Coupon(title=title, kind="free_item", scope=scope, tags=tags)

    # "9.9元中杯冰美式" -> 固定到手价
    m = re.search(r"(\d+(?:\.\d+)?)\s*元", title)
    if m and "满" not in title:
        return Coupon(
            title=title,
            kind="fixed_price",
            price=float(m.group(1)),
            scope=scope,
            tags=tags,
        )

    m = _PERCENT_RE.search(title)
    if m:
        return Coupon(
            title=title,
            kind="percent_off",
            price=float(m.group(1)) / 10.0,
            scope=scope,
            tags=tags,
        )

    m = _PRICE_RE.search(body) or _PRICE_RE.search(title)
    if m and ("用券价格" in body or "到手价" in body or "券后" in body):
        return Coupon(
            title=title,
            kind="fixed_price",
            price=float(m.group(1)),
            scope=scope,
            tags=tags,
        )

    return Coupon(title=title, kind="unknown", scope=scope, tags=tags)


# 券标题里可用于匹配餐品的常见关键词
_SCOPE_KEYWORDS = [
    "麦辣鸡腿堡", "板烧鸡腿堡", "巨无霸", "麦香鸡", "麦香鱼", "吉士汉堡",
    "原味板烧鸡腿麦满分", "猪柳蛋麦满分", "猪柳麦满分", "大脆鸡扒麦满分",
    "烟肉蛋麦满分", "火腿扒麦满分", "双层吉士汉堡", "培根蔬萃双层牛堡",
    "麦乐鸡", "麦辣鸡翅", "薯条", "玉米杯", "新地", "麦旋风", "圆筒冰淇淋",
    "香芋派", "菠萝派", "可乐", "美式", "奶铁", "拿铁", "鲜萃咖啡", "怡泉",
    "叠叠卷", "脆汁鸡", "奥利奥",
]


def _guess_scope(title: str) -> str:
    for kw in _SCOPE_KEYWORDS:
        if kw in title:
            return kw
    return ""


# ------------------------------------------------------------------- 菜单

_CODE_KEYS = ("code", "mealCode", "productCode", "skuCode", "itemCode", "id")
_NAME_KEYS = ("name", "mealName", "productName", "spuName", "title")
_PRICE_KEYS = (
    "price", "currentPrice", "salePrice", "showPrice", "originalPrice",
    "priceValue", "amount",
)
_CAT_KEYS = ("category", "catName", "categoryName", "groupName", "typeName")


def _first(d: dict[str, Any], keys: Iterable[str], default: Any = None) -> Any:
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return default


def _to_float(v: Any) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"(\d+(?:\.\d+)?)", str(v or ""))
    return float(m.group(1)) if m else 0.0


def normalize_menu(payload: Any) -> list[MenuItem]:
    """把 ``query-meals`` 的任意结构归一化成 :class:`MenuItem` 列表。"""
    items: list[MenuItem] = []
    seen: set[str] = set()

    def walk(node: Any, category: str = "") -> None:
        if isinstance(node, dict):
            name = _first(node, _NAME_KEYS)
            price = _first(node, _PRICE_KEYS)
            if name and price is not None:
                code = str(_first(node, _CODE_KEYS, name))
                cat = str(_first(node, _CAT_KEYS, category) or category)
                if code not in seen:
                    seen.add(code)
                    items.append(
                        MenuItem(
                            code=code,
                            name=str(name),
                            price=_to_float(price),
                            category=cat,
                        )
                    )
                return
            # 分类字典: {类别名: [餐品...]}
            for key, value in node.items():
                walk(value, category=str(key))
        elif isinstance(node, list):
            for child in node:
                walk(child, category)

    walk(payload)
    return items


def attach_nutrition(
    items: list[MenuItem], nutrition: dict[str, Nutrition]
) -> int:
    """按名称把营养数据挂到菜单餐品上, 返回命中数量。"""
    hit = 0
    for it in items:
        if it.nutrition:
            continue
        n = nutrition.get(it.name)
        if n is None:
            # 宽松匹配: 菜单名包含营养表名, 或反之
            for key, value in nutrition.items():
                if key and (key in it.name or it.name in key) and abs(len(key) - len(it.name)) <= 4:
                    n = value
                    break
        if n is not None:
            it.nutrition = n
            hit += 1
    return hit


def extract_data(payload: Any) -> Any:
    """若返回是 ``{"data": ...}`` 信封, 取出 data。"""
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload
