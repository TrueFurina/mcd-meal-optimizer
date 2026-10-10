"""求解器测试。

核心是**随机差分测试**: 在小规模随机实例上, DP 结果必须与穷举结果一致。
另有可行性、券应用与边界用例。
"""

import random
import unittest

from mcd_meal_optimizer.models import Constraints, Coupon, MenuItem, Nutrition
from mcd_meal_optimizer.optimizer import (
    brute_force,
    effective_price,
    solve,
)


def make_item(i: int, kcal: float, prot: float, price: float) -> MenuItem:
    return MenuItem(
        code=f"I{i}",
        name=f"餐品{i}",
        price=price,
        nutrition=Nutrition(energy_kcal=kcal, protein=prot),
    )


class TestOptimizerCorrectness(unittest.TestCase):
    def test_dp_matches_bruteforce_random(self):
        """随机实例上 DP 与穷举的最优到手价必须一致。"""
        rng = random.Random(20261010)
        mismatches = 0
        for trial in range(120):
            n = rng.randint(3, 9)
            items = [
                make_item(
                    i,
                    kcal=rng.randint(50, 450),
                    prot=rng.randint(0, 35),
                    price=round(rng.uniform(5, 30), 1),
                )
                for i in range(n)
            ]
            cons = Constraints(
                kcal_min=rng.choice([0, 200, 400]),
                kcal_max=rng.choice([600, 800, 1200]),
                protein_min=rng.choice([0, 15, 30]),
                budget_max=rng.choice([30, 50, 80]),
                min_items=1,
                max_items=3,
            )
            dp = solve(items, cons, objective="min_price", top_n=1)
            bf = brute_force(items, cons, top_n=1)
            dp_cost = dp[0].payable if dp else None
            bf_cost = bf[0].payable if bf else None
            if dp_cost != bf_cost:
                mismatches += 1
                if mismatches <= 3:
                    print(f"  MISMATCH trial={trial} dp={dp_cost} bf={bf_cost} "
                          f"n={n} cons={cons}")
        self.assertEqual(mismatches, 0, f"{mismatches}/120 次差分不一致")

    def test_feasibility_respected(self):
        items = [
            make_item(0, 250, 12, 15.0),
            make_item(1, 300, 20, 18.0),
            make_item(2, 120, 3, 8.0),
            make_item(3, 400, 25, 25.0),
        ]
        cons = Constraints(kcal_min=400, kcal_max=600, protein_min=30,
                           budget_max=35, max_items=3)
        plans = solve(items, cons, top_n=5)
        self.assertTrue(plans)
        for p in plans:
            self.assertGreaterEqual(p.kcal, 400)
            self.assertLessEqual(p.kcal, 600)
            self.assertGreaterEqual(p.protein, 30)
            self.assertLessEqual(p.payable, 35 + 1e-6)

    def test_infeasible_returns_empty(self):
        items = [make_item(0, 100, 1, 5.0)]
        cons = Constraints(kcal_min=800, kcal_max=900, protein_min=50, budget_max=100)
        self.assertEqual(solve(items, cons), [])

    def test_kcal_min_enforced(self):
        """热点: 最便宜的「满足上限+蛋白」组合若不满足热量下限, 必须被排除。

        构造上最低价的方案 A(50kcal/¥5) 会违反 kcal_min=400, 因此正确答案
        应是有 400kcal 的 C(¥18)。该用例可捕获「丢掉热量下限」类缺陷。
        """
        items = [
            make_item(0, 50, 20, 5.0),    # A: 最便宜, 但热量远低于下限
            make_item(1, 450, 12, 20.0),  # B
            make_item(2, 400, 10, 18.0),  # C: 最低价合规解
        ]
        cons = Constraints(kcal_min=400, kcal_max=600, protein_min=10,
                           budget_max=100, max_items=2)
        plans = solve(items, cons, top_n=5)
        self.assertTrue(plans)
        for p in plans:
            self.assertGreaterEqual(p.kcal, 400, "违反热量下限的方案被返回")
        self.assertAlmostEqual(plans[0].payable, 18.0)
        # 与穷举交叉验证
        bf = brute_force(items, cons, top_n=1)
        self.assertAlmostEqual(bf[0].payable, plans[0].payable)

    def test_budget_binding(self):
        items = [make_item(i, 200, 15, 10.0 + i) for i in range(5)]
        loose = Constraints(kcal_min=300, kcal_max=500, protein_min=25, budget_max=100)
        tight = Constraints(kcal_min=300, kcal_max=500, protein_min=25, budget_max=21)
        loose_plans = solve(items, loose, top_n=1)
        tight_plans = solve(items, tight, top_n=1)
        self.assertTrue(loose_plans)
        if tight_plans:
            self.assertLessEqual(tight_plans[0].payable, loose_plans[0].payable)

    def test_max_items_respected(self):
        items = [make_item(i, 100, 5, 5.0) for i in range(6)]
        cons = Constraints(kcal_min=0, kcal_max=10000, protein_min=0,
                           budget_max=1000, max_items=2)
        plans = solve(items, cons, top_n=3)
        for p in plans:
            self.assertLessEqual(len(p.items), 2)

    def test_objective_max_protein(self):
        items = [
            make_item(0, 300, 10, 20.0),
            make_item(1, 300, 30, 25.0),
            make_item(2, 300, 5, 5.0),
        ]
        cons = Constraints(kcal_min=300, kcal_max=600, protein_min=0, budget_max=50, max_items=2)
        plans = solve(items, cons, objective="max_protein", top_n=1)
        self.assertTrue(plans)
        self.assertGreaterEqual(plans[0].protein, 30)


class TestCouponApplication(unittest.TestCase):
    def test_fixed_price_lowers_cost(self):
        item = make_item(0, 200, 10, 20.0)
        item.name = "中杯美式"
        coupon = Coupon(title="美式券", kind="fixed_price", price=13.3, scope="美式")
        price, title = effective_price(item, [coupon])
        self.assertAlmostEqual(price, 13.3)
        self.assertEqual(title, "美式券")

    def test_percent_off(self):
        item = make_item(0, 200, 10, 20.0)
        item.name = "中杯美式"
        coupon = Coupon(title="7折", kind="percent_off", price=0.7, scope="美式")
        price, _ = effective_price(item, [coupon])
        self.assertAlmostEqual(price, 14.0)

    def test_threshold_order_discount(self):
        items = [make_item(0, 200, 10, 20.0), make_item(1, 200, 10, 15.0)]
        coupon = Coupon(title="满30减5", kind="threshold_off", threshold=30, price=5)
        cons = Constraints(kcal_min=300, kcal_max=500, protein_min=15,
                           budget_max=100, max_items=2)
        plans = solve(items, cons, [coupon], top_n=1)
        self.assertTrue(plans)
        self.assertAlmostEqual(plans[0].subtotal, 35.0)
        self.assertAlmostEqual(plans[0].discount, 5.0)
        self.assertAlmostEqual(plans[0].payable, 30.0)


class TestPerformance(unittest.TestCase):
    def test_large_menu_solves_fast(self):
        """~120 款菜单应在秒级内求解 (验证 DP 剪枝有效)。"""
        import time
        rng = random.Random(7)
        items = [
            make_item(i, rng.randint(30, 500), rng.randint(0, 30), round(rng.uniform(4, 28), 1))
            for i in range(120)
        ]
        cons = Constraints(kcal_min=500, kcal_max=800, protein_min=30, budget_max=45, max_items=4)
        t0 = time.time()
        plans = solve(items, cons, top_n=3)
        dt = time.time() - t0
        self.assertLess(dt, 20.0, f"求解耗时 {dt:.1f}s 过慢")
        self.assertTrue(plans)


if __name__ == "__main__":
    unittest.main()
