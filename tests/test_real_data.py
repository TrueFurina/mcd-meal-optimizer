"""真实 MCP 返回结构的解析与名称匹配测试。

样本取自真实响应 (``query-meals`` / ``query-meal-detail`` / ``list-nutrition-foods``),
只保留结构与关键字段。重点覆盖**容易出错且会静默失真**的地方:
规格区分 (中/大杯、4块/5块)、包装词、佐料与周边。
"""

import unittest

from mcd_meal_optimizer.models import Constraints, MenuItem, Nutrition
from mcd_meal_optimizer.optimizer import solve
from mcd_meal_optimizer.parsers import (
    is_non_food,
    match_nutrition_name,
    merge_component_nutrition,
    parse_meal_detail,
    parse_meal_detail_components,
    parse_menu_payload,
    parse_nutrition_table,
)
from mcd_meal_optimizer.stores import _match_city, _norm_store

# --------------------------------------------------------------- 真实样本

MENU_PAYLOAD = {
    "success": True,
    "data": {
        "categories": [
            {"name": "人气热卖", "meals": [
                {"code": "9900005456", "tags": ["套餐"]},
                {"code": "521741"},
            ]},
            {"name": "咖啡饮料", "meals": [
                {"code": "3010", "tags": ["饮料"]},
            ]},
        ],
        "meals": {
            "9900005456": {"name": "麦辣鸡腿汉堡三件套", "currentPrice": "33.5",
                           "originalPrice": "46", "canWithOrder": False},
            "521741": {"name": "脆薯饼", "currentPrice": "8.5", "originalPrice": "8.5"},
            "3010": {"name": "雪碧", "currentPrice": "9", "originalPrice": "13.5"},
        },
    },
}

DETAIL_COMBO = {
    "success": True,
    "data": {
        "code": "9900005456",
        "name": "麦辣鸡腿汉堡三件套",
        "rounds": [
            {"id": 1, "name": "麦辣鸡腿汉堡", "choices": [
                {"code": "1440", "name": "麦辣鸡腿汉堡", "quantity": 1, "isDefault": 1},
            ]},
            {"id": 2, "name": "选择套餐内小食", "choices": [
                {"code": "4810", "name": "中薯条", "quantity": 1, "isDefault": 1},
                {"code": "521983", "name": "5块心形薯饼+韩式辣椒黄油风味酱",
                 "quantity": 0, "isDefault": 0},
            ]},
            {"id": 3, "name": "选择饮料", "choices": [
                {"code": "4102", "name": "中杯可口可乐", "quantity": 0, "isDefault": 0},
                {"code": "4103", "name": "可乐中杯", "quantity": 1, "isDefault": 1},
            ]},
        ],
    },
}

# 单品的 detail: rounds 为空, 但 name 是**带规格的精确名**
DETAIL_SINGLE = {"success": True, "data": {"code": "4810", "name": "中薯条", "rounds": []}}

NUTRITION_TEXT = """
[8]{productName,nutritionDescription,energyKj,energyKcal,protein,fat,carbohydrate,sodium,calcium}:
  麦辣鸡腿汉堡,null,2150,514,25,26,41,1020,120
  中薯条,null,1210,289,4,12,38,165,18
  大薯条,null,1512,361,5,15,47,206,22
  可乐中杯,null,628,150,0,0,37,15,2
  冰美式中杯,null,12,3,0,0,1,5,2
  热美式中杯,null,15,4,0,0,1,6,2
  麦乐鸡4块,null,748,179,11,10,11,410,12
  麦乐鸡5块,null,935,223,14,13,14,512,15
  100%苹果汁,null,397,95,0,0,23,10,0
  纯牛奶（盒装）,null,450,107,7,5,8,120,240
  苹果片,null,209,50,0,0,13,0,2
  雪碧小杯,null,461,110,0,0,28,12,2
"""


def _table() -> dict[str, Nutrition]:
    return parse_nutrition_table(NUTRITION_TEXT)


# ------------------------------------------------------------- 菜单解析


class TestRealMenuParsing(unittest.TestCase):
    def test_real_shape(self):
        items = parse_menu_payload(MENU_PAYLOAD)
        self.assertEqual(len(items), 3)
        by_code = {i.code: i for i in items}
        combo = by_code["9900005456"]
        self.assertEqual(combo.name, "麦辣鸡腿汉堡三件套")
        self.assertAlmostEqual(combo.price, 33.5)
        self.assertAlmostEqual(combo.original_price, 46.0)
        self.assertEqual(combo.category, "人气热卖")
        self.assertEqual(combo.tags, ["套餐"])
        self.assertEqual(by_code["3010"].category, "咖啡饮料")

    def test_price_is_yuan_not_cents(self):
        """query-meals 的价格是元; 分->元的换算只发生在 calculate-price。"""
        items = {i.code: i for i in parse_menu_payload(MENU_PAYLOAD)}
        self.assertAlmostEqual(items["521741"].price, 8.5)

    def test_unknown_shape_falls_back(self):
        items = parse_menu_payload({"data": [{"code": "A1", "name": "巨无霸", "price": 25.5}]})
        self.assertEqual([i.name for i in items], ["巨无霸"])


class TestMealDetailParsing(unittest.TestCase):
    def test_default_components(self):
        comps = parse_meal_detail_components(DETAIL_COMBO)
        self.assertEqual(comps, ["麦辣鸡腿汉堡", "中薯条", "可乐中杯"])

    def test_precise_name_for_single_item(self):
        info = parse_meal_detail(DETAIL_SINGLE)
        self.assertEqual(info["name"], "中薯条")
        self.assertEqual(info["components"], [])

    def test_empty_payload(self):
        self.assertEqual(parse_meal_detail({"data": {}}), {"name": "", "components": []})
        self.assertEqual(parse_meal_detail(None), {"name": "", "components": []})


# ------------------------------------------------------------- 名称匹配


class TestNameMatching(unittest.TestCase):
    def setUp(self):
        self.table = _table()

    def _key(self, name):
        return match_nutrition_name(name, self.table)[0]

    def test_exact(self):
        self.assertEqual(self._key("中薯条"), "中薯条")

    def test_ignores_spaces_and_brackets(self):
        self.assertEqual(self._key("100% 苹果汁(盒装)"), "100%苹果汁")

    def test_packaging_word_is_ignored(self):
        """「纯牛奶」应能对上营养库的「纯牛奶（盒装）」。"""
        self.assertEqual(self._key("纯牛奶"), "纯牛奶（盒装）")

    def test_weight_and_container_stripped(self):
        self.assertEqual(self._key("苹果片一袋(60g)"), "苹果片")

    def test_word_order_insensitive_for_count(self):
        self.assertEqual(self._key("5块麦乐鸡"), "麦乐鸡5块")

    # --- 以下为**必须拒绝**的近似, 否则营养会被错配 ---

    def test_size_discriminates_drink(self):
        self.assertEqual(self._key("冰美式中杯"), "冰美式中杯")
        self.assertEqual(self._key("热美式中杯"), "热美式中杯")
        self.assertNotEqual(self._key("冰美式中杯"), "热美式中杯")

    def test_size_discriminates_fries(self):
        self.assertEqual(self._key("中薯条"), "中薯条")
        self.assertNotEqual(self._key("中薯条"), "大薯条")

    def test_piece_count_is_not_stripped(self):
        """4块与5块的麦乐鸡热量不同, 绝不能互配。"""
        self.assertEqual(self._key("麦乐鸡4块"), "麦乐鸡4块")
        self.assertEqual(self._key("麦乐鸡5块"), "麦乐鸡5块")
        self.assertNotEqual(self._key("麦乐鸡4块"), "麦乐鸡5块")

    def test_ambiguous_and_unlisted_return_none(self):
        for name in ("薯条", "牛奶", "雪碧", "龙焰鸡腿堡", ""):
            with self.subTest(name=name):
                self.assertIsNone(self._key(name))

    def test_confidence_ordering(self):
        self.assertAlmostEqual(match_nutrition_name("中薯条", self.table)[1], 1.0)
        self.assertLess(match_nutrition_name("100% 苹果汁(盒装)", self.table)[1], 1.0)


class TestNonFoodDetect(unittest.TestCase):
    def test_non_food(self):
        for name in ("韩式烟熏芝士风味酱", "北美招牌牧场酱", "海绵宝宝×航海王系列玩具",
                     "旋旋水手帽", "麦当劳联名复古棒球帽", "餐具"):
            with self.subTest(name=name):
                self.assertTrue(is_non_food(name))

    def test_food_is_not_non_food(self):
        for name in ("苹果片一袋(60g)", "麦辣鸡腿汉堡", "中薯条", "可乐中杯"):
            with self.subTest(name=name):
                self.assertFalse(is_non_food(name))


class TestComponentNutrition(unittest.TestCase):
    def test_sum_and_skip_non_food(self):
        table = _table()
        n, missing = merge_component_nutrition(
            ["麦辣鸡腿汉堡", "中薯条", "可乐中杯", "韩式烟熏芝士风味酱"], table
        )
        self.assertEqual(missing, [])
        self.assertAlmostEqual(n.energy_kcal, 514 + 289 + 150)
        self.assertAlmostEqual(n.protein, 25 + 4 + 0)

    def test_missing_reported_not_zeroed(self):
        table = _table()
        n, missing = merge_component_nutrition(["中薯条", "龙焰鸡腿堡"], table)
        self.assertEqual(missing, ["龙焰鸡腿堡"])
        self.assertAlmostEqual(n.energy_kcal, 289)  # 只算命中的部分

    def test_all_missing_returns_none(self):
        n, missing = merge_component_nutrition(["不存在A", "不存在B"], _table())
        self.assertIsNone(n)
        self.assertEqual(len(missing), 2)

    def test_only_non_food_returns_none_without_missing(self):
        n, missing = merge_component_nutrition(["韩式烟熏芝士风味酱"], _table())
        self.assertIsNone(n)
        self.assertEqual(missing, [])


# ------------------------------------------------- 营养不完整不得入解


class TestNutritionGating(unittest.TestCase):
    def _items(self):
        return [
            MenuItem(code="A", name="好汉堡", price=20.0,
                     nutrition=Nutrition(energy_kcal=600, protein=30)),
            MenuItem(code="B", name="缺营养新品", price=1.0, nutrition=None),
            MenuItem(code="C", name="部分命中套餐", price=1.0,
                     nutrition=Nutrition(energy_kcal=50, protein=1),
                     nutrition_missing=["龙焰鸡腿堡"]),
        ]

    def test_incomplete_items_excluded(self):
        """缺营养/部分命中的餐品不能进入解 —— 否则会用被低估的数值伪装达标。"""
        cons = Constraints(kcal_min=500, kcal_max=700, protein_min=25, budget_max=50)
        plans = solve(self._items(), cons)
        self.assertTrue(plans)
        for p in plans:
            for pi in p.items:
                self.assertTrue(pi.item.nutrition_complete)
        self.assertEqual(
            {pi.item.code for p in plans for pi in p.items}, {"A"}
        )

    def test_opt_out_allows_partial(self):
        cons = Constraints(
            kcal_min=0, kcal_max=1e9, protein_min=0, budget_max=50,
            require_complete_nutrition=False,
        )
        plans = solve(self._items(), cons)
        self.assertTrue(plans)


# ------------------------------------------------------------- 门店归一


class TestStoreNormalization(unittest.TestCase):
    def test_norm_store(self):
        s = _norm_store({"code": "1450713", "name": "麦当劳上海黄浦华旭国际大厦餐厅",
                         "address": "西藏中路336号", "cityName": "上海市",
                         "latitude": 31.233774, "longitude": 121.475816,
                         "distance": 415}, "party-city")
        self.assertEqual(s["code"], "1450713")
        self.assertEqual(s["city"], "上海市")
        self.assertAlmostEqual(s["latitude"], 31.233774)
        self.assertEqual(s["source"], "party-city")

    def test_norm_store_rejects_incomplete(self):
        self.assertIsNone(_norm_store({"name": "无编码"}, "x"))
        self.assertIsNone(_norm_store({"code": "1"}, "x"))

    def test_city_match(self):
        cities = [{"name": "上海市", "code": 310100}, {"name": "北京市", "code": 110100}]
        self.assertEqual(_match_city(cities, "上海")["code"], 310100)
        self.assertEqual(_match_city(cities, "上海市")["code"], 310100)
        self.assertEqual(_match_city(cities, "北京市")["code"], 110100)
        self.assertIsNone(_match_city(cities, "不存在的市"))


if __name__ == "__main__":
    unittest.main()
