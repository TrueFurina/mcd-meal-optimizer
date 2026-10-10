"""真实价格计算与下单链路。

到店自取 (``beType=1 / orderType=1``) 是**唯一不依赖账号侧配置**的下单
路径: 不需要收藏门店、不需要配送地址。本模块围绕它实现:

- :meth:`OrderService.price`   调用 ``calculate-price`` 拿**真实成交价**
  (接口返回单位为「分」, 此处统一换算成「元」)
- :meth:`OrderService.preview` 只做算价与参数校验, **绝不提交订单**
- :meth:`OrderService.submit`  调用 ``create-order`` 真实建单
- :meth:`OrderService.cancel`  调用 ``cancel-order`` 撤销

安全设计: ``submit`` 默认拒绝执行, 必须显式传 ``confirm=True``。这避免
「顺手跑一下」就把真实订单挂到用户账号上。``create-order`` 只创建未支付
订单并返回支付入口, 但仍是真实订单, 因此闸门放在这一层。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from .mcp_client import McdMcpClient, McdMcpError
from .models import MenuItem
from .parsers import extract_data

CENTS_PER_YUAN = 100.0

# beType -> (orderType, 是否需要 beCode)
BE_TYPE_RULES: dict[int, tuple[int, bool]] = {
    1: (1, False),   # 到店自取
    5: (1, True),    # 得来速
    2: (2, True),    # 麦乐送
    6: (2, True),    # 企业团餐
}


class OrderConfirmRequired(RuntimeError):
    """未显式确认就尝试提交真实订单。"""


def to_items(items: Sequence[MenuItem | dict[str, Any]]) -> list[dict[str, Any]]:
    """把菜单项 / 方案项 / ``{code, quantity}`` 统一成接口要求的 items 结构。

    必须同时接受 :class:`MenuItem` 与 :class:`~.models.PlanItem` ——
    求解结果给的是 PlanItem, 直接传 MenuItem 的判断会把它静默丢掉,
    导致 items 为空、接口报「检查必填参数」。
    """
    out: list[dict[str, Any]] = []
    for it in items:
        if isinstance(it, MenuItem):
            out.append({"productCode": str(it.code), "quantity": 1})
            continue
        inner = getattr(it, "item", None)  # PlanItem
        if isinstance(inner, MenuItem):
            qty = int(getattr(it, "quantity", 1) or 1)
            out.append({"productCode": str(inner.code), "quantity": qty})
            continue
        if isinstance(it, dict):
            code = it.get("productCode") or it.get("code")
            if not code:
                continue
            row = {"productCode": str(code), "quantity": int(it.get("quantity") or 1)}
            for k in ("couponId", "couponCode"):
                if it.get(k):
                    row[k] = it[k]
            out.append(row)
    return out


def _yuan(cents: Any) -> float:
    try:
        return round(float(cents) / CENTS_PER_YUAN, 2)
    except (TypeError, ValueError):
        return 0.0


@dataclass
class PriceResult:
    """``calculate-price`` 的解析结果 (金额单位已转为元)。"""

    product_price: float = 0.0
    original_price: float = 0.0
    discount: float = 0.0
    payable: float = 0.0
    lines: list[dict[str, Any]] = field(default_factory=list)
    take_way_options: list[dict[str, str]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    def default_take_way(self) -> str | None:
        for opt in self.take_way_options:
            if opt.get("code"):
                return opt["code"]
        return None


@dataclass
class OrderResult:
    """``create-order`` 的结果。"""

    order_id: str = ""
    payable: float = 0.0
    pay_url: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class OrderService:
    """价格计算 / 下单 / 撤单。"""

    def __init__(self, client: McdMcpClient) -> None:
        self.client = client

    # ------------------------------------------------------------ 价格

    def price(
        self,
        store_code: str,
        items: Sequence[MenuItem | dict[str, Any]],
        be_type: int = 1,
        be_code: str | None = None,
    ) -> PriceResult:
        """调用 ``calculate-price`` 计算真实成交价。"""
        order_type, need_be_code = BE_TYPE_RULES.get(be_type, (1, False))
        args: dict[str, Any] = {
            "storeCode": store_code,
            "orderType": order_type,
            "beType": be_type,
            "items": to_items(items),
        }
        if need_be_code and be_code:
            args["beCode"] = be_code
        payload = extract_data(self.client.call_tool("calculate-price", args))
        data = payload if isinstance(payload, dict) else {}

        lines: list[dict[str, Any]] = []
        for row in data.get("productList") or []:
            if not isinstance(row, dict):
                continue
            lines.append(
                {
                    "code": str(row.get("productCode") or ""),
                    "name": str(row.get("productName") or ""),
                    "quantity": int(row.get("quantity") or 1),
                    "payable": _yuan(row.get("subtotal")),
                    "original": _yuan(row.get("originalSubtotal")),
                }
            )

        options = []
        for opt in data.get("takeWayList") or []:
            if isinstance(opt, dict) and opt.get("code"):
                options.append(
                    {"code": str(opt["code"]), "title": str(opt.get("title") or "")}
                )

        return PriceResult(
            product_price=_yuan(data.get("productPrice")),
            original_price=_yuan(data.get("originalPrice")),
            discount=_yuan(data.get("discount")),
            payable=_yuan(data.get("price", data.get("productPrice"))),
            lines=lines,
            take_way_options=options,
            raw=data,
        )

    # ------------------------------------------------------------ 下单

    def preview(
        self,
        store_code: str,
        items: Sequence[MenuItem | dict[str, Any]],
        take_way_code: str | None = None,
        be_type: int = 1,
        be_code: str | None = None,
    ) -> dict[str, Any]:
        """组装下单参数并算价, 但**不提交**。用于下单前确认。"""
        order_type, need_be_code = BE_TYPE_RULES.get(be_type, (1, False))
        priced = self.price(store_code, items, be_type=be_type, be_code=be_code)
        chosen = take_way_code or priced.default_take_way()
        args: dict[str, Any] = {
            "storeCode": store_code,
            "orderType": order_type,
            "beType": be_type,
            "items": to_items(items),
        }
        if order_type == 1:
            args["takeWayCode"] = chosen
        if need_be_code and be_code:
            args["beCode"] = be_code
        return {
            "store_code": store_code,
            "be_type": be_type,
            "order_type": order_type,
            "take_way_code": chosen,
            "take_way_options": priced.take_way_options,
            "payable": priced.payable,
            "discount": priced.discount,
            "lines": priced.lines,
            "order_args": args,
        }

    def submit(
        self,
        store_code: str,
        items: Sequence[MenuItem | dict[str, Any]],
        take_way_code: str | None = None,
        be_type: int = 1,
        be_code: str | None = None,
        confirm: bool = False,
        remark: str | None = None,
    ) -> OrderResult:
        """真实调用 ``create-order`` 建单。

        必须显式 ``confirm=True`` —— 否则抛 :class:`OrderConfirmRequired`。
        """
        if not confirm:
            raise OrderConfirmRequired(
                "拒绝下单: 未显式确认。真实订单会挂到你的麦当劳账号上, "
                "请先用 preview() 查看, 确认后传 confirm=True 再提交。"
            )

        preview = self.preview(
            store_code, items, take_way_code=take_way_code, be_type=be_type, be_code=be_code
        )
        args = dict(preview["order_args"])
        if remark:
            args["remark"] = remark[:50]

        payload = extract_data(self.client.call_tool("create-order", args))
        data = payload if isinstance(payload, dict) else {}

        order_id = ""
        for key in ("orderId", "orderNo", "orderCode", "orderNumber"):
            if data.get(key):
                order_id = str(data[key])
                break
        pay_url = ""
        for key in ("payUrl", "paymentUrl", "url", "qrCode", "qrCodeUrl"):
            if data.get(key):
                pay_url = str(data[key])
                break
        payable = _yuan(data.get("price", data.get("payable", 0))) or preview["payable"]

        return OrderResult(order_id=order_id, payable=payable, pay_url=pay_url, raw=data)

    # ------------------------------------------------------------ 撤单

    def cancel(self, order_id: str, reason_code: int = 1) -> dict[str, Any]:
        """取消订单。``reason_code``: 1=改主意 2=重复下单 3=点错 4=地址错 5=时间错 -1=其它。"""
        payload = extract_data(
            self.client.call_tool(
                "cancel-order", {"orderId": order_id, "cancelReasonCode": reason_code}
            )
        )
        return payload if isinstance(payload, dict) else {}


def render_price(result: PriceResult, title: str = "真实算价") -> str:
    """把算价结果渲染成可读文本。"""
    lines = [f"## {title}"]
    for row in result.lines:
        lines.append(
            f"- {row['name']} ×{row['quantity']}  ¥{row['payable']:.2f}"
            + (f"（原价 ¥{row['original']:.2f}）" if row["original"] > row["payable"] else "")
        )
    if result.discount:
        lines.append(f"- 优惠: -¥{result.discount:.2f}")
    lines.append(f"- **合计 ¥{result.payable:.2f}**")
    if result.take_way_options:
        opts = " / ".join(f"{o['title']}({o['code']})" for o in result.take_way_options)
        lines.append(f"- 取餐方式: {opts}")
    return "\n".join(lines)


def ensure_items_available(items: Iterable[MenuItem]) -> list[str]:
    """返回菜单里**缺营养数据**的餐品名, 供下单前提示 (不阻断)。"""
    return [it.name for it in items if not it.nutrition_complete]


__all__ = [
    "OrderService",
    "PriceResult",
    "OrderResult",
    "OrderConfirmRequired",
    "render_price",
    "to_items",
]
