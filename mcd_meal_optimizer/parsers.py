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

4. ``query-meals`` 的 ``{"categories": [...], "meals": {code: {...}}}`` 结构
   (:func:`parse_menu_payload`), 以及任意嵌套形态的宽容回退。

5. ``query-meal-detail`` 的 ``data.rounds[].choices[]``, 用于还原套餐的
   默认组成 (:func:`parse_meal_detail_components`), 从而让套餐也能拿到
   营养数据 (组成单品求和)。
"""

from __future__ import annotations

import re
from collections import Counter
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


def parse_menu_payload(payload: Any) -> list[MenuItem]:
    """解析 ``query-meals`` 的**真实**返回结构。

    真实结构形如::

        data = {
          "categories": [{"name": "人气热卖", "meals": [{"code": "...", "tags": [...]}]}, ...],
          "meals": {"9900005456": {"name": "麦辣鸡腿汉堡三件套",
                                   "currentPrice": "33.5",
                                   "originalPrice": "46"}, ...},
        }

    价格字段是可变的 ``currentPrice`` (元), 与 ``query-meal-detail`` 无关;
    分类名需要从 ``categories`` 反查, 因为 ``meals`` 里不带分类。

    当结构不是上述形态时, 回退到宽容的 :func:`normalize_menu`。
    """
    data = extract_data(payload)
    if not isinstance(data, dict):
        return normalize_menu(payload)

    meals = data.get("meals")
    if not isinstance(meals, dict) or not meals:
        return normalize_menu(payload)

    # -- 从 categories 反查每个 code 的分类名与标签
    category_of: dict[str, str] = {}
    tags_of: dict[str, list[str]] = {}
    for cat in data.get("categories") or []:
        if not isinstance(cat, dict):
            continue
        cname = str(cat.get("name") or "").strip()
        for m in cat.get("meals") or []:
            if not isinstance(m, dict):
                continue
            c = str(m.get("code") or "")
            if not c:
                continue
            category_of.setdefault(c, cname)
            tg = [str(t) for t in (m.get("tags") or []) if t]
            if tg:
                tags_of.setdefault(c, tg)

    items: list[MenuItem] = []
    for code, m in meals.items():
        if not isinstance(m, dict):
            continue
        name = str(m.get("name") or "").strip()
        if not name:
            continue
        price = _to_float(_first(m, ("currentPrice", "price", "salePrice"), 0))
        original = _to_float(_first(m, ("originalPrice",), 0))
        items.append(
            MenuItem(
                code=str(code),
                name=name,
                price=price,
                category=category_of.get(str(code), ""),
                tags=tags_of.get(str(code), []),
                original_price=original,
            )
        )
    return items


def parse_meal_detail(payload: Any) -> dict[str, Any]:
    """解析 ``query-meal-detail``: 返回 ``{"name": 精确名, "components": [...]}``。

    关键点: ``query-meals`` 里的餐品名是**通用展示名** (如「薯条」「雪碧」
    「牛奶」), 而 ``query-meal-detail`` 返回的是**带规格的精确 SKU 名**
    (「中薯条」「雪碧（小杯）」「热牛奶中杯」)。营养库是按精确名建的,
    所以单品的营养必须用 detail 的名字去匹配, 否则会因规格歧义全部落空。
    """
    data = extract_data(payload)
    if not isinstance(data, dict):
        return {"name": "", "components": []}
    return {
        "name": str(data.get("name") or "").strip(),
        "components": parse_meal_detail_components(payload),
    }


def parse_meal_detail_components(payload: Any) -> list[str]:
    """从 ``query-meal-detail`` 里取出套餐的**默认组成** (餐品名列表)。

    返回结构形如::

        data.rounds = [
          {"name": "麦辣鸡腿汉堡", "choices": [{"name": "麦辣鸡腿汉堡",
                                                "isDefault": 1, "quantity": 1}]},
          {"name": "选择套餐内小食", "choices": [{"name": "中薯条", "isDefault": 1}, ...]},
        ]

    每个 round 取「默认项」: 优先 ``isDefault == 1``, 其次 ``quantity > 0``,
    都没有则取第一项。饮品/小食选择轮次即由此还原成具体单品。
    """
    data = extract_data(payload)
    if not isinstance(data, dict):
        return []
    out: list[str] = []
    for rnd in data.get("rounds") or []:
        if not isinstance(rnd, dict):
            continue
        choices = [c for c in (rnd.get("choices") or []) if isinstance(c, dict)]
        if not choices:
            continue
        pick = None
        for c in choices:
            if c.get("isDefault") in (1, True, "1"):
                pick = c
                break
        if pick is None:
            for c in choices:
                if (c.get("quantity") or 0) > 0:
                    pick = c
                    break
        if pick is None:
            pick = choices[0]
        nm = str(pick.get("name") or "").strip()
        if nm and nm not in out:
            out.append(nm)
    return out


# ------------------------------------------------------------- 名称归一化

_NAME_NOISE = re.compile(r"[\s\-—–_·、,，.。;；!！?？'\"“”‘’()（）\[\]【】{}<>《》/\\|]+")

# 包装词: 不影响营养成分, 比对时剔除 ("100%苹果汁(盒装)" == "100%苹果汁")。
_PACKAGING_WORDS = ("纸盒装", "盒装", "瓶装", "杯装", "袋装", "罐装", "听装")
# 重量规格 "(60g)" / "500ml"
_WEIGHT_RE = re.compile(r"\d+(?:\.\d+)?(?:kg|g|ml|毫升|克)")
# 数量+容器 (一袋/2杯/3瓶...)。**故意不含「块」「个」「片」** ——
# 快餐里块数是装量差异 (麦乐鸡4块 vs 5块), 剔除会造成误配。
_COUNT_UNIT_RE = re.compile(r"[一二三四五六七八九十两\d]+(?:袋|盒|瓶|杯|罐|份|包|支)")

# 佐料/周边: 不提供营养, 缺它们不算"营养不完整"。
_NON_FOOD_RE = re.compile(
    r"(?:酱|蘸料|调料|餐具|纸巾|吸管|优惠券|兑换券|优惠卡"
    r"|帽|玩具|玩偶|公仔|贴纸|徽章|抱枕|卡套|挂件|徽章|手办)"
)


def normalize_food_name(name: Any) -> str:
    """去掉空白/标点/连字符等噪声, 便于跨接口名称对齐。"""
    return _NAME_NOISE.sub("", str(name or "")).lower()


def _base_chars(name: Any) -> Counter:
    """名称的**字符多重集**, 已剔除包装词与重量/数量规格。

    用字符多重集而不是分词: 中文连写没有空格, ``可乐中杯`` 若按
    ``[\\u4e00-\\u9fff]+`` 分词会得到整串, 无法处理词序差异; 字符
    多重集天然忽略词序, 同时保留「大/小/中/冰/热」这类真正改变
    营养的区分字。
    """
    s = normalize_food_name(name)
    for w in _PACKAGING_WORDS:
        s = s.replace(w, "")
    s = _WEIGHT_RE.sub("", s)
    s = _COUNT_UNIT_RE.sub("", s)
    return Counter(s)


def food_name_tokens(name: Any) -> tuple[str, ...]:
    """名称的字符多重集 (排序后的字符元组), 供比较与调试。"""
    return tuple(sorted(_base_chars(name).elements()))


def is_non_food(name: Any) -> bool:
    """是否为佐料 / 周边 / 餐具等**不提供营养**的条目。"""
    return bool(_NON_FOOD_RE.search(str(name or "")))


def match_nutrition_name(
    name: str, table: dict[str, Nutrition]
) -> tuple[str | None, float]:
    """把菜单餐品名对齐到营养库键名, 返回 ``(键名, 置信度)``。

    只接受**高置信**匹配 (字面相同 / 归一化相同 / 剔除包装与规格后字符
    多重集相同), 不做模糊近似 —— 宁可标为「未收录」, 也不把
    「冰牛奶中杯」错配成「热牛奶大杯」这类容量/口味不同的餐品。
    """
    if not name:
        return None, 0.0
    if name in table:
        return name, 1.0

    target_norm = normalize_food_name(name)
    for key in table:
        if key and normalize_food_name(key) == target_norm:
            return key, 0.99

    target_base = _base_chars(name)
    if target_base:
        for key in table:
            if key and _base_chars(key) == target_base:
                return key, 0.95
    return None, 0.0


def merge_component_nutrition(
    components: list[str], table: dict[str, Nutrition]
) -> tuple[Nutrition | None, list[str]]:
    """把套餐组成逐个对齐营养库并求和。

    返回 ``(营养合计, 未命中的组成名)``。佐料/周边 (酱、玩具、帽子)
    不计入营养也不算缺失; 其余任何一个组成未命中都会出现在第二个
    返回值里 —— 调用方据此把该餐品标为「营养不完整」, 而不是静默按
    0 计算导致低估热量。
    """
    if not components:
        return None, []
    acc: Nutrition | None = None
    missing: list[str] = []
    for comp in components:
        if is_non_food(comp):
            continue
        key, _ = match_nutrition_name(comp, table)
        if key is None:
            missing.append(comp)
            continue
        acc = table[key] if acc is None else acc + table[key]
    return acc, missing


def normalize_menu(payload: Any) -> list[MenuItem]:
    """宽容归一化: 任何含 name/price 的嵌套结构都尝试抽出餐品。"""
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
    """按名称把营养数据挂到菜单餐品上, 返回命中数量。

    只做高置信匹配 (见 :func:`match_nutrition_name`); 命中不了就留空,
    由调用方决定是否走「套餐拆解」或标注为未收录。
    """
    hit = 0
    for it in items:
        if it.nutrition:
            continue
        key, _ = match_nutrition_name(it.name, nutrition)
        if key is not None:
            it.nutrition = nutrition[key]
            hit += 1
    return hit


def extract_data(payload: Any) -> Any:
    """若返回是 ``{"data": ...}`` 信封, 取出 data。"""
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload
