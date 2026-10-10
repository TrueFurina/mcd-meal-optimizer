"""价格计算与下单链路测试。

重点验证: 分→元换算、到店自取的参数规则 (beType=1 不传 beCode、
orderType=1 必传 takeWayCode)、以及**未显式确认绝不提交订单**的安全闸门。
"""

import unittest

from mcd_meal_optimizer.models import MenuItem, Plan, PlanItem, Nutrition
from mcd_meal_optimizer.orders import (
    BE_TYPE_RULES,
    OrderConfirmRequired,
    OrderService,
    render_price,
    to_items,
)

PRICE_RESPONSE = {
    "success": True,
    "data": {
        "productOriginalPrice": 4200,
        "originalPrice": 4200,
        "discount": 0,
        "price": 4200,
        "productList": [
            {"productCode": "9900005456", "productName": "麦辣鸡腿汉堡三件套",
             "quantity": 1, "originalSubtotal": 3350, "subtotal": 3350},
            {"productCode": "521741", "productName": "脆薯饼",
             "quantity": 1, "originalSubtotal": 850, "subtotal": 850},
        ],
        "takeWayList": [
            {"code": "eat-in", "title": "堂食"},
            {"code": "locker-out", "title": "外带"},
        ],
    },
}

ORDER_RESPONSE = {
    "success": True,
    "data": {"orderId": "ORD123456", "price": 4200, "payUrl": "https://pay.example/x"},
}


class FakeClient:
    """记录调用的假客户端。"""

    def __init__(self, responses=None):
        self.calls: list[tuple[str, dict]] = []
        self.responses = responses or {}

    def call_tool(self, name, arguments=None):
        self.calls.append((name, arguments or {}))
        return self.responses.get(name, {"success": True, "data": {}})

    def tool_args(self, name):
        return [a for n, a in self.calls if n == name]


def _item(code="9900005456", name="麦辣鸡腿汉堡三件套", price=33.5):
    return MenuItem(code=code, name=name, price=price)


class TestToItems(unittest.TestCase):
    def test_menu_item(self):
        self.assertEqual(
            to_items([_item()]), [{"productCode": "9900005456", "quantity": 1}]
        )

    def test_plan_item(self):
        """PlanItem 必须被识别 —— 否则求解结果传给算价接口会变成空 items。"""
        plan = Plan(
            items=[PlanItem(item=_item(), quantity=1)],
            subtotal=33.5, discount=0, payable=33.5, nutrition=Nutrition(),
        )
        self.assertEqual(to_items(plan.items), [{"productCode": "9900005456", "quantity": 1}])

    def test_dict_with_coupon(self):
        got = to_items([{"code": "A1", "quantity": 2, "couponId": "C9"}])
        self.assertEqual(got, [{"productCode": "A1", "quantity": 2, "couponId": "C9"}])

    def test_dict_without_code_dropped(self):
        self.assertEqual(to_items([{"quantity": 2}]), [])


class TestPriceParsing(unittest.TestCase):
    def test_cents_to_yuan(self):
        svc = OrderService(FakeClient({"calculate-price": PRICE_RESPONSE}))
        r = svc.price("1450713", [_item(), _item("521741", "脆薯饼", 8.5)])
        self.assertAlmostEqual(r.payable, 42.0)
        self.assertAlmostEqual(r.original_price, 42.0)
        self.assertAlmostEqual(r.lines[0]["payable"], 33.5)
        self.assertEqual(len(r.lines), 2)
        self.assertEqual(r.default_take_way(), "eat-in")

    def test_be_type_1_omits_be_code(self):
        """到店自取 (beType=1) 不传 beCode, 传了会报错。"""
        client = FakeClient({"calculate-price": PRICE_RESPONSE})
        OrderService(client).price("1450713", [_item()], be_type=1, be_code="SHOULD_NOT_APPEAR")
        args = client.tool_args("calculate-price")[0]
        self.assertEqual(args["orderType"], 1)
        self.assertEqual(args["beType"], 1)
        self.assertNotIn("beCode", args)

    def test_be_type_5_includes_be_code(self):
        client = FakeClient({"calculate-price": PRICE_RESPONSE})
        OrderService(client).price("1450713", [_item()], be_type=5, be_code="BEFIVE")
        args = client.tool_args("calculate-price")[0]
        self.assertEqual(args["orderType"], 1)
        self.assertEqual(args["beCode"], "BEFIVE")

    def test_be_type_rules_table(self):
        self.assertEqual(BE_TYPE_RULES[1], (1, False))
        self.assertEqual(BE_TYPE_RULES[5], (1, True))
        self.assertEqual(BE_TYPE_RULES[2], (2, True))
        self.assertEqual(BE_TYPE_RULES[6], (2, True))


class TestOrderGate(unittest.TestCase):
    def test_preview_does_not_create_order(self):
        client = FakeClient({"calculate-price": PRICE_RESPONSE})
        preview = OrderService(client).preview("1450713", [_item()])
        self.assertEqual(client.tool_args("create-order"), [])
        self.assertEqual(preview["take_way_code"], "eat-in")
        self.assertEqual(preview["order_args"]["takeWayCode"], "eat-in")
        self.assertAlmostEqual(preview["payable"], 42.0)

    def test_submit_without_confirm_refuses(self):
        """未显式确认时必须拒绝, 且**不得**发出 create-order 请求。"""
        client = FakeClient({"calculate-price": PRICE_RESPONSE, "create-order": ORDER_RESPONSE})
        with self.assertRaises(OrderConfirmRequired):
            OrderService(client).submit("1450713", [_item()])
        self.assertEqual(client.tool_args("create-order"), [])

    def test_submit_with_confirm(self):
        client = FakeClient({"calculate-price": PRICE_RESPONSE, "create-order": ORDER_RESPONSE})
        result = OrderService(client).submit("1450713", [_item()], confirm=True)
        self.assertEqual(result.order_id, "ORD123456")
        self.assertAlmostEqual(result.payable, 42.0)
        self.assertEqual(result.pay_url, "https://pay.example/x")
        args = client.tool_args("create-order")[0]
        self.assertEqual(args["takeWayCode"], "eat-in")
        self.assertEqual(args["items"], [{"productCode": "9900005456", "quantity": 1}])

    def test_remark_truncated_to_50(self):
        client = FakeClient({"calculate-price": PRICE_RESPONSE, "create-order": ORDER_RESPONSE})
        OrderService(client).submit("1450713", [_item()], confirm=True, remark="x" * 80)
        self.assertEqual(len(client.tool_args("create-order")[0]["remark"]), 50)

    def test_cancel(self):
        client = FakeClient({"cancel-order": {"success": True, "data": {}}})
        OrderService(client).cancel("ORD123456", reason_code=1)
        self.assertEqual(
            client.tool_args("cancel-order")[0],
            {"orderId": "ORD123456", "cancelReasonCode": 1},
        )


class TestRender(unittest.TestCase):
    def test_contains_total_and_take_way(self):
        svc = OrderService(FakeClient({"calculate-price": PRICE_RESPONSE}))
        text = render_price(svc.price("1450713", [_item()]))
        self.assertIn("¥42.00", text)
        self.assertIn("eat-in", text)
        self.assertIn("麦辣鸡腿汉堡三件套", text)


if __name__ == "__main__":
    unittest.main()
