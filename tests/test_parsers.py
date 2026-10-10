"""解析器测试。样本取自真实 MCP 响应。"""

import unittest

from mcd_meal_optimizer.parsers import (
    attach_nutrition,
    normalize_menu,
    parse_available_coupons,
    parse_compact_table,
    parse_my_coupons_markdown,
    parse_nutrition_table,
)
from mcd_meal_optimizer.models import MenuItem

NUTRITION_SAMPLE = """
[160]{productName,nutritionDescription,energyKj,energyKcal,protein,fat,carbohydrate,sodium,calcium}:
  猪柳麦满分,null,1288,308,16,16,24,781,213
  猪柳蛋麦满分,null,1618,387,23,21,25,846,243
  中薯条,null,1210,289,4,12,38,165,18
  巨无霸,null,2146,513,27,26,42,961,171
"""

COUPONS_SAMPLE = """# 您的优惠券列表

共 2 张可用优惠券 | 第 1/1 页 | 每页 200 条

## 新人专享-中杯美式7折
- **优惠**: ¥13.3 (用券价格)
- **有效期**: 2026-10-10 00:00-2026-11-08 23:59 05:00-23:59
- **领取时间**: 今日收到
- **标签**: 到店专用

<img src="https://example.com/a.png">

## 新人专享-中杯奶铁7折
- **优惠**: ¥14.7 (用券价格)
- **标签**: 到店专用,限时
"""

AVAILABLE_SAMPLE = """### 麦麦省优惠券列表：
- 优惠券标题：巧克力味厚松饼猪柳蛋套餐 \\
  状态：可领取 \\
  优惠券图片：\\
    <img src="https://example.com/b.png">
- 优惠券标题：满30减5 \\
  状态：可领取 \\
"""


class TestCompactTable(unittest.TestCase):
    def test_rows_and_types(self):
        rows = parse_compact_table(NUTRITION_SAMPLE)
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]["productName"], "猪柳麦满分")
        self.assertEqual(rows[0]["energyKcal"], "308")

    def test_garbage_returns_empty(self):
        self.assertEqual(parse_compact_table("not a table"), [])
        self.assertEqual(parse_compact_table(""), [])

    def test_nutrition_dict(self):
        table = parse_nutrition_table(NUTRITION_SAMPLE)
        self.assertEqual(len(table), 4)
        n = table["巨无霸"]
        self.assertAlmostEqual(n.energy_kcal, 513)
        self.assertAlmostEqual(n.protein, 27)
        self.assertAlmostEqual(n.sodium, 961)


class TestCouponParsing(unittest.TestCase):
    def test_my_coupons_prices(self):
        coupons = parse_my_coupons_markdown(COUPONS_SAMPLE)
        self.assertEqual(len(coupons), 2)
        self.assertEqual(coupons[0].title, "新人专享-中杯美式7折")
        # 标题带"7折", 应识别为折扣券
        self.assertEqual(coupons[0].kind, "percent_off")
        self.assertAlmostEqual(coupons[0].price, 0.7)
        self.assertIn("到店专用", coupons[0].tags)
        self.assertIn("限时", coupons[1].tags)

    def test_threshold_coupon(self):
        coupons = parse_available_coupons(AVAILABLE_SAMPLE)
        self.assertEqual(len(coupons), 2)
        t = coupons[1]
        self.assertEqual(t.kind, "threshold_off")
        self.assertAlmostEqual(t.threshold, 30)
        self.assertAlmostEqual(t.price, 5)

    def test_fixed_price_from_title(self):
        """'9.9元中杯冰美式' 应识别为固定价券且绑定美式。"""
        text = "### 麦麦省优惠券列表：\n- 优惠券标题：9.9元中杯冰美式 \\\n  状态：可领取 \\\n"
        coupons = parse_available_coupons(text)
        self.assertEqual(len(coupons), 1)
        self.assertEqual(coupons[0].kind, "fixed_price")
        self.assertAlmostEqual(coupons[0].price, 9.9)
        self.assertEqual(coupons[0].scope, "美式")

    def test_bogo_and_free(self):
        text = (
            "### 麦麦省优惠券列表：\n"
            "- 优惠券标题：人气麦旋风买一送一 \\\n  状态：可领取 \\\n"
            "- 优惠券标题：免费脆薯饼 \\\n  状态：可领取 \\\n"
        )
        coupons = parse_available_coupons(text)
        self.assertEqual(coupons[0].kind, "bogo")
        self.assertEqual(coupons[0].scope, "麦旋风")
        self.assertEqual(coupons[1].kind, "free_item")

    def test_threshold_not_misread_as_fixed_price(self):
        """'满30减5' 不应被 'N元' 规则误判为固定价券。"""
        text = "### 麦麦省优惠券列表：\n- 优惠券标题：满30元减5元 \\\n  状态：可领取 \\\n"
        coupons = parse_available_coupons(text)
        self.assertEqual(coupons[0].kind, "threshold_off")


class TestMenuNormalization(unittest.TestCase):
    def test_flat_list(self):
        payload = {"data": [
            {"code": "A1", "name": "巨无霸", "price": "25.5"},
            {"code": "A2", "mealName": "中薯条", "salePrice": 12.5},
        ]}
        items = normalize_menu(payload)
        self.assertEqual({i.name for i in items}, {"巨无霸", "中薯条"})
        self.assertAlmostEqual(items[0].price, 25.5)

    def test_categorized_dict(self):
        payload = {"汉堡": [{"code": "A1", "name": "巨无霸", "price": 25.5}],
                   "小食": [{"code": "B1", "name": "中薯条", "price": 12.5}]}
        items = normalize_menu(payload)
        self.assertEqual(len(items), 2)
        self.assertEqual({i.category for i in items}, {"汉堡", "小食"})

    def test_dedupe_by_code(self):
        payload = [{"code": "A1", "name": "巨无霸", "price": 25.5}] * 3
        self.assertEqual(len(normalize_menu(payload)), 1)

    def test_attach_nutrition(self):
        items = [MenuItem(code="A1", name="巨无霸", price=25.5),
                 MenuItem(code="A2", name="不存在的餐品", price=9.9)]
        table = parse_nutrition_table(NUTRITION_SAMPLE)
        hit = attach_nutrition(items, table)
        self.assertEqual(hit, 1)
        self.assertAlmostEqual(items[0].protein, 27)


if __name__ == "__main__":
    unittest.main()
