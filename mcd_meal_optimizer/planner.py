"""编排层: 通过麦当劳 MCP 取数, 调用求解器, 产出可执行方案。

数据流::

    list-nutrition-foods ─┐
    query-my-coupons     ─┼─> 归一化 ─> 求解器 ─> 方案 ─> 渲染 / 下单
    available-coupons    ─┤
    query-nearby-stores  ─┤
    query-meals          ─┘

当账号尚未配置门店(``query-nearby-stores`` 返回空)时, 可传入
``menu_items`` 或使用 ``examples/sample-menu.json`` 走离线示例路径,
保证工具在任何账号状态下都能给出可解释的输出。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .mcp_client import McdMcpClient, McdMcpError
from .models import Constraints, Coupon, MenuItem, Nutrition, Plan
from .optimizer import effective_price, solve
from .parsers import (
    attach_nutrition,
    extract_data,
    normalize_menu,
    parse_available_coupons,
    parse_my_coupons_markdown,
    parse_nutrition_table,
)

DEFAULT_SAMPLE_MENU = Path(__file__).resolve().parent.parent / "examples" / "sample-menu.json"


class McdPlanService:
    """面向「营养×预算」场景的 MCP 编排服务。"""

    def __init__(self, client: McdMcpClient | None = None) -> None:
        self.client = client or McdMcpClient()
        self._nutrition: dict[str, Nutrition] | None = None
        self._coupons: list[Coupon] | None = None

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
        """到店场景门店查询。search_type=2 按位置, =1 查收藏门店。"""
        args: dict[str, Any] = {"beType": be_type, "searchType": search_type}
        if city:
            args["city"] = city
        if keyword:
            args["keyword"] = keyword
        payload = self.client.call_tool("query-nearby-stores", args)
        return _as_list(payload)

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
        args: dict[str, Any] = {
            "storeCode": store_code,
            "orderType": order_type,
            "beType": be_type,
        }
        if be_code:
            args["beCode"] = be_code
        payload = self.client.call_tool("query-meals", args)
        items = normalize_menu(extract_data(payload) or payload)
        if attach_nutrition_data and items:
            attach_nutrition(items, self.nutrition_table())
        return items

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

        meta["nutrition"] = sum(1 for it in items if it.nutrition)
        plans = solve(items, constraints, coupons, objective=objective, top_n=top_n)
        return plans, meta

    # ------------------------------------------------------------- 渲染

    @staticmethod
    def render(plans: Iterable[Plan], constraints: Constraints, meta: dict[str, Any] | None = None) -> str:
        plans = list(plans)
        lines: list[str] = []
        if meta and meta.get("menu_source") == "sample":
            lines.append("> 说明: 未从你的账号取到门店菜单, 以下为**示例菜单**计算结果, 价格仅作演示。")
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
    """加载离线示例菜单 (无门店数据时的兜底)。"""
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
