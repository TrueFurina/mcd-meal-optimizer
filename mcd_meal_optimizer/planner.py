"""编排层: 通过麦当劳 MCP 取数, 调用求解器, 产出可执行方案。

真实数据流 (到店自取 ``beType=1 / orderType=1``)::

    mall-points-products ─> query-party-city ─> query-party-store
                                                    │ storeCode
                                                    v
    list-nutrition-foods ─┐                  query-meals  (真实名称+价格)
    query-my-coupons     ─┼─> 归一化 ─> query-meal-detail (套餐拆成单品)
    available-coupons    ─┘                        │
                                                   v
                                    求解器 ─> 方案 ─> calculate-price (真实算价)
                                                   └─> create-order  (需显式确认)

``query-nearby-stores`` 依赖账号侧定位/收藏门店, 全新账号会返回空, 因此
门店发现默认走不依赖账号的派对门店链路 (见 :mod:`.stores`)。

当完全取不到菜单时, 可传 ``menu_items`` 或使用 ``examples/sample-menu.json``
走离线示例路径, 输出会明确标注"价格为示例"。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .mcp_client import McdMcpClient, McdMcpError
from .models import Constraints, Coupon, MenuItem, Nutrition, Plan
from .optimizer import effective_price, excluded_by_nutrition, solve
from .orders import OrderService
from .parsers import (
    attach_nutrition,
    extract_data,
    match_nutrition_name,
    merge_component_nutrition,
    normalize_menu,
    parse_available_coupons,
    parse_meal_detail,
    parse_meal_detail_components,
    parse_menu_payload,
    parse_my_coupons_markdown,
    parse_nutrition_table,
)
from .stores import StoreFinder

DEFAULT_SAMPLE_MENU = Path(__file__).resolve().parent.parent / "examples" / "sample-menu.json"
DEFAULT_CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"


class McdPlanService:
    """面向「营养×预算」场景的 MCP 编排服务。"""

    def __init__(self, client: McdMcpClient | None = None) -> None:
        self.client = client or McdMcpClient()
        self.stores = StoreFinder(self.client)
        self.orders = OrderService(self.client)
        self._nutrition: dict[str, Nutrition] | None = None
        self._coupons: list[Coupon] | None = None
        self._detail_cache: dict[str, dict[str, Any]] | None = None

    # ------------------------------------------------------------- 营养库

    def nutrition_table(self, refresh: bool = False) -> dict[str, Nutrition]:
        if self._nutrition is None or refresh:
            payload = self.client.call_tool("list-nutrition-foods", {})
            self._nutrition = parse_nutrition_table(extract_data(payload) or payload)
        return self._nutrition

    # -------------------------------------------------------------- 券

    def my_coupons(self) -> list[Coupon]:
        payload = self.client.call_tool("query-my-coupons", {"page": "1", "pageSize": "200"})
        text = _as_text(payload)
        return parse_my_coupons_markdown(text)

    def available_coupons(self) -> list[Coupon]:
        payload = self.client.call_tool("available-coupons", {})
        return parse_available_coupons(_as_text(payload))

    def coupons(self, refresh: bool = False) -> list[Coupon]:
        if self._coupons is None or refresh:
            merged: list[Coupon] = []
            try:
                merged.extend(self.my_coupons())
            except McdMcpError:
                pass
            try:
                merged.extend(self.available_coupons())
            except McdMcpError:
                pass
            self._coupons = merged
        return self._coupons

    # ------------------------------------------------------------- 门店

    def find_stores(
        self,
        city: str | None = None,
        keyword: str | None = None,
        be_type: int = 1,
        search_type: int = 2,
    ) -> list[dict[str, Any]]:
        """账号侧门店查询 (search_type=2 按位置, =1 查收藏门店)。

        依赖账号已配置定位或收藏门店; 全新账号通常返回空。
        不依赖账号配置的按城市发现请用 :meth:`discover_stores`。
        """
        return self.stores.nearby(
            city=city, keyword=keyword, be_type=be_type, search_type=search_type
        )

    def discover_stores(self, city: str, limit: int = 20) -> list[dict[str, Any]]:
        """按城市名发现**真实门店** (不依赖账号收藏/定位)。"""
        return self.stores.discover(city, limit=limit)

    def delivery_stores(self, address_id: str, be_type: int = 2) -> list[dict[str, Any]]:
        payload = self.client.call_tool(
            "delivery-query-stores", {"beType": be_type, "addressId": address_id}
        )
        return _as_list(payload)

    def addresses(self) -> list[dict[str, Any]]:
        return _as_list(self.client.call_tool("delivery-query-addresses", {}))

    # ------------------------------------------------------------- 菜单

    def menu(
        self,
        store_code: str,
        be_type: int = 1,
        order_type: int = 1,
        be_code: str | None = None,
        attach_nutrition_data: bool = True,
    ) -> list[MenuItem]:
        """拉取门店**真实菜单** (含真实名称与价格)。"""
        args: dict[str, Any] = {
            "storeCode": store_code,
            "orderType": order_type,
            "beType": be_type,
        }
        if be_code:
            args["beCode"] = be_code
        payload = self.client.call_tool("query-meals", args)
        data = extract_data(payload)
        items = parse_menu_payload(data if data is not None else payload)
        if attach_nutrition_data and items:
            self.enrich_nutrition(items, store_code, be_type=be_type, order_type=order_type)
        return items

    # ------------------------------------------------------- 营养对齐

    def _detail_cache_file(self, store_code: str, be_type: int, order_type: int) -> Path:
        return DEFAULT_CACHE_DIR / f"compose-{store_code}-{be_type}-{order_type}.json"

    def _load_detail_cache(self, store_code: str, be_type: int, order_type: int) -> dict[str, dict[str, Any]]:
        if self._detail_cache is not None:
            return self._detail_cache
        path = self._detail_cache_file(store_code, be_type, order_type)
        cache: dict[str, dict[str, Any]] = {}
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                for k, v in raw.items():
                    # 兼容旧缓存格式 (值为组成列表)
                    if isinstance(v, dict):
                        cache[str(k)] = {
                            "name": str(v.get("name") or ""),
                            "components": list(v.get("components") or []),
                        }
                    elif isinstance(v, list):
                        cache[str(k)] = {"name": "", "components": list(v)}
            except (json.JSONDecodeError, OSError, TypeError):
                cache = {}
        self._detail_cache = cache
        return cache

    def _save_detail_cache(self, store_code: str, be_type: int, order_type: int) -> None:
        if self._detail_cache is None:
            return
        try:
            DEFAULT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            path = self._detail_cache_file(store_code, be_type, order_type)
            path.write_text(
                json.dumps(self._detail_cache, ensure_ascii=False, indent=1),
                encoding="utf-8",
            )
        except OSError:
            pass

    def detail_of(
        self,
        code: str,
        store_code: str,
        be_type: int = 1,
        order_type: int = 1,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        """取餐品详情 ``{name: 精确名, components: [...]}``, 带磁盘缓存。"""
        cache = self._load_detail_cache(store_code, be_type, order_type) if use_cache else {}
        if code in cache:
            return cache[code]
        args: dict[str, Any] = {
            "storeCode": store_code,
            "orderType": order_type,
            "beType": be_type,
            "code": str(code),
        }
        try:
            payload = self.client.call_tool("query-meal-detail", args)
        except McdMcpError:
            info = {"name": "", "components": []}
        else:
            info = parse_meal_detail(payload)
        if use_cache:
            cache[code] = info
        return info

    def components_of(
        self,
        code: str,
        store_code: str,
        be_type: int = 1,
        order_type: int = 1,
        use_cache: bool = True,
    ) -> list[str]:
        """取某餐品的默认组成 (套餐会拆成单品), 带磁盘缓存。"""
        return self.detail_of(
            code, store_code, be_type=be_type, order_type=order_type, use_cache=use_cache
        ).get("components") or []

    def enrich_nutrition(
        self,
        items: list[MenuItem],
        store_code: str,
        be_type: int = 1,
        order_type: int = 1,
        use_cache: bool = True,
        max_detail: int | None = None,
    ) -> dict[str, int]:
        """给菜单餐品挂营养: 直接匹配 -> 套餐拆解 -> 单品精确名匹配。

        返回统计 ``{direct, decomposed, partial, missing}``, 便于诚实汇报
        覆盖率 —— 新品(如当季限定)可能不在营养库里, 这些会被标为 partial
        并记入 ``nutrition_missing``, **不会**按 0 计算。
        """
        table = self.nutrition_table()
        stats = {"direct": 0, "decomposed": 0, "partial": 0, "missing": 0}

        pending: list[MenuItem] = []
        for it in items:
            if it.nutrition:
                stats["direct"] += 1
                continue
            key, _ = match_nutrition_name(it.name, table)
            if key is not None:
                it.nutrition = table[key]
                stats["direct"] += 1
            else:
                pending.append(it)

        budget = max_detail if max_detail is not None else len(pending)
        changed = False
        for offset, it in enumerate(pending):
            if offset >= budget:
                # 未在本次预算内拆解, 标记为待定 (不计入营养)
                it.nutrition_missing = ["<未拆解>"]
                stats["missing"] += 1
                continue
            info = self.detail_of(
                it.code, store_code, be_type=be_type, order_type=order_type, use_cache=use_cache
            )
            changed = True
            comps = list(info.get("components") or [])
            if not comps:
                # 单品没有可选轮次: 用 detail 的**精确名** (带规格) 匹配,
                # 例如菜单叫「薯条」而 detail 是「中薯条」。
                comps = [str(info.get("name") or "") or it.name]
            it.components = comps
            nutrition, missing = merge_component_nutrition(comps, table)
            it.nutrition = nutrition
            it.nutrition_missing = missing
            if nutrition is None:
                stats["missing"] += 1
            elif missing:
                stats["partial"] += 1
            else:
                stats["decomposed"] += 1

        if changed and use_cache:
            self._save_detail_cache(store_code, be_type, order_type)
        return stats

    def nutrition_coverage(self, items: list[MenuItem]) -> dict[str, int]:
        """统计一份菜单的营养完整度 (用于输出诚实标注)。"""
        complete = sum(1 for it in items if it.nutrition_complete)
        partial = sum(
            1 for it in items if it.nutrition is not None and it.nutrition_missing
        )
        none = sum(1 for it in items if it.nutrition is None)
        return {"total": len(items), "complete": complete, "partial": partial, "none": none}

    # ------------------------------------------------------------- 求解

    def plan(
        self,
        constraints: Constraints,
        coupons: list[Coupon] | None = None,
        menu_items: list[MenuItem] | None = None,
        store_code: str | None = None,
        be_type: int = 1,
        order_type: int = 1,
        objective: str = "min_price",
        top_n: int = 3,
        allow_sample_fallback: bool = True,
    ) -> tuple[list[Plan], dict[str, Any]]:
        """产出方案, 并返回数据来源信息 (用于诚实标注)。"""
        meta: dict[str, Any] = {"menu_source": None, "coupons": 0, "nutrition": 0}

        if coupons is None:
            coupons = self.coupons()
        meta["coupons"] = len(coupons)

        items = menu_items
        if items is None and store_code:
            try:
                items = self.menu(store_code, be_type=be_type, order_type=order_type)
                meta["menu_source"] = f"live:{store_code}"
            except McdMcpError as exc:
                meta["menu_error"] = str(exc)

        if not items and allow_sample_fallback:
            items = load_sample_menu()
            meta["menu_source"] = "sample"

        if not items:
            return [], meta

        cov = self.nutrition_coverage(items)
        meta["coverage"] = cov
        meta["nutrition"] = cov["complete"]
        meta["excluded_no_nutrition"] = [
            it.name for it in excluded_by_nutrition(items, constraints)
        ]
        plans = solve(items, constraints, coupons, objective=objective, top_n=top_n)
        return plans, meta

    # ------------------------------------------------------------- 渲染

    @staticmethod
    def render(plans: Iterable[Plan], constraints: Constraints, meta: dict[str, Any] | None = None) -> str:
        plans = list(plans)
        lines: list[str] = []
        if meta and meta.get("menu_source") == "sample":
            lines.append("> 说明: 未从你的账号取到门店菜单, 以下为**示例菜单**计算结果, 价格仅作演示。")
        cov = (meta or {}).get("coverage")
        if cov and (cov.get("partial") or cov.get("none")):
            lines.append(
                f"> 营养覆盖: {cov['complete']}/{cov['total']} 项完整; "
                f"{cov['partial']} 项组成部分未收录, {cov['none']} 项无营养数据。"
                "这些餐品已被排除出解 —— 不会按 0 热量计算, 以免伪造「达标」。"
            )
        if not plans:
            lines.append("没有找到同时满足营养与预算约束的方案。建议放宽预算或热量区间。")
            return "\n".join(lines)

        for i, p in enumerate(plans, 1):
            lines.append(
                f"## 方案 {i} — 到手 ¥{p.payable:.2f}"
                f"（原价 ¥{p.subtotal:.2f}"
                + (f"，省 ¥{p.discount:.2f}" if p.discount else "")
                + "）"
            )
            lines.append(
                f"- 营养: {p.kcal:.0f} kcal / 蛋白 {p.protein:.1f} g"
                f"（目标 {constraints.kcal_min:.0f}-{constraints.kcal_max:.0f} kcal,"
                f" 蛋白 ≥ {constraints.protein_min:.0f} g）"
            )
            for pi in p.items:
                tag = f"  ← 用券「{pi.applied_coupon}」" if pi.applied_coupon else ""
                lines.append(f"- {pi.item.name} ¥{pi.payable:.2f}{tag}")
            lines.append("")
        return "\n".join(lines).strip()


# ----------------------------------------------------------------- 工具函数


def _as_text(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        if isinstance(payload.get("text"), str):
            return payload["text"]
        data = payload.get("data")
        if isinstance(data, str):
            return data
        return json.dumps(payload, ensure_ascii=False)
    return str(payload)


def _as_list(payload: Any) -> list[dict[str, Any]]:
    data = extract_data(payload)
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("list", "stores", "records", "items", "addresses"):
            if isinstance(data.get(key), list):
                return [x for x in data[key] if isinstance(x, dict)]
    return []


def load_sample_menu(path: Path | str | None = None) -> list[MenuItem]:
    """加载离线菜单 JSON (示例菜单或真实门店快照)。

    兼容两种结构: 精简的 ``examples/sample-menu.json``, 以及
    ``scripts/snapshot_store.py`` 导出的 ``examples/real-menu-*.json``
    (含 original_price / components / nutrition_missing)。
    """
    p = Path(path) if path else DEFAULT_SAMPLE_MENU
    if not p.exists():
        return []
    raw = json.loads(p.read_text(encoding="utf-8"))
    items = []
    for row in raw.get("items", []):
        n = row.get("nutrition") or {}
        items.append(
            MenuItem(
                code=str(row.get("code") or row.get("name")),
                name=row["name"],
                price=float(row.get("price", 0)),
                category=row.get("category", ""),
                nutrition=Nutrition(**n) if n else None,
                tags=list(row.get("tags") or []),
                original_price=float(row.get("original_price") or 0),
                components=list(row.get("components") or []),
                nutrition_missing=list(row.get("nutrition_missing") or []),
            )
        )
    return items


def summarize_prices(items: list[MenuItem]) -> dict[str, float]:
    """菜单价格概览, 便于在 README / 输出里说明数据规模。"""
    if not items:
        return {"count": 0}
    prices = [i.price for i in items if i.price > 0]
    return {
        "count": len(items),
        "with_nutrition": sum(1 for i in items if i.nutrition),
        "min_price": min(prices) if prices else 0.0,
        "max_price": max(prices) if prices else 0.0,
    }
