"""双目标餐搭求解器。

问题: 在**预算上限**与**营养目标(热量区间 + 蛋白质下限)**双约束下,
从门店真实菜单里选出 1~N 件餐品, 使到手价最低 (或同等预算下蛋白最高)。

采用动态规划: 以 (热量桶, 蛋白桶, 必需项掩码) 为状态, 保留每状态
最低到手价的组合, 再对候选组合做**精确复算**与可行性过滤。桶只用于
剪枝, 最终指标均按真实营养/价格精确计算, 报告值不因分桶而失真。

对菜单规模 <= 10 的小样本, 提供 :func:`brute_force` 作为独立校验。
"""

from __future__ import annotations

import itertools
from typing import Callable, Iterable

from .models import Constraints, Coupon, MenuItem, Nutrition, Plan, PlanItem

KCAL_STEP = 5.0
PROTEIN_STEP = 2.0
KCAL_CAP = 1500.0
PROTEIN_CAP = 80.0


def effective_price(item: MenuItem, coupons: Iterable[Coupon]) -> tuple[float, str | None]:
    """单件餐品在可用券下的最低到手价。"""
    best = item.price
    best_coupon: str | None = None
    for c in coupons:
        if not c.applies_to(item):
            continue
        if c.kind == "fixed_price" and 0 < c.price < best:
            best, best_coupon = c.price, c.title
        elif c.kind == "percent_off" and 0 < c.price < 1:
            cand = round(item.price * c.price, 2)
            if cand < best:
                best, best_coupon = cand, c.title
    return best, best_coupon


def _order_discount(subtotal: float, coupons: Iterable[Coupon]) -> tuple[float, str | None]:
    """整单适用的满减券, 返回 (减免额, 券名)。"""
    best_d, best_t = 0.0, None
    for c in coupons:
        if c.kind == "threshold_off" and subtotal >= c.threshold and c.price > best_d:
            best_d, best_t = c.price, c.title
    return best_d, best_t


def nutrition_constraints_active(cons: Constraints) -> bool:
    """是否启用了任何营养相关约束。"""
    return cons.kcal_min > 0 or cons.protein_min > 0 or cons.kcal_max < 1e9


def _filter_items(items: list[MenuItem], cons: Constraints) -> list[MenuItem]:
    """筛出可参与求解的餐品。

    营养约束生效时, 默认**只保留营养完整**的餐品: 缺营养的餐品会被
    当作 0 kcal / 0 g 蛋白, 从而伪造出"达标"结论。这类餐品要么补齐
    营养(拆解套餐组成), 要么排除出解。
    """
    need_nutrition = nutrition_constraints_active(cons)
    out = []
    for it in items:
        name = it.name
        if any(kw and kw in name for kw in cons.exclude):
            continue
        if it.price <= 0 and not it.nutrition:
            continue
        if need_nutrition and cons.require_complete_nutrition and not it.nutrition_complete:
            continue
        out.append(it)
    # 低价优先, 便于剪枝
    out.sort(key=lambda x: x.price)
    return out


def excluded_by_nutrition(items: list[MenuItem], cons: Constraints) -> list[MenuItem]:
    """返回因「营养不完整」被排除的餐品 (供诚实汇报)。"""
    if not (nutrition_constraints_active(cons) and cons.require_complete_nutrition):
        return []
    return [it for it in items if not it.nutrition_complete]


def _required_mask(item: MenuItem, keywords: list[str]) -> int:
    mask = 0
    for i, kw in enumerate(keywords):
        if kw and kw in item.name:
            mask |= 1 << i
    return mask


def solve(
    items: list[MenuItem],
    constraints: Constraints,
    coupons: list[Coupon] | None = None,
    objective: str = "min_price",
    top_n: int = 3,
) -> list[Plan]:
    """求解最优餐搭方案, 返回按目标排序的若干方案。

    objective: ``min_price`` (默认, 到手价最低) | ``max_protein``
    (同预算下蛋白最高) | ``best_value`` (每元蛋白最高)。
    """
    constraints.validate()
    coupons = coupons or []
    pool = _filter_items(items, constraints)
    if not pool:
        return []

    keywords = list(constraints.must_include)
    full_mask = (1 << len(keywords)) - 1 if keywords else 0

    eff = [effective_price(it, coupons) for it in pool]
    masks = [_required_mask(it, keywords) for it in pool]

    kcal_cap = min(constraints.kcal_max, KCAL_CAP)
    p_cap = min(max(constraints.protein_min, 40.0), PROTEIN_CAP)

    def kb(k: float) -> int:
        return min(int(k // KCAL_STEP), int(kcal_cap // KCAL_STEP))

    def pb(p: float) -> int:
        return min(int(p // PROTEIN_STEP), int(p_cap // PROTEIN_STEP))

    n_k = int(kcal_cap // KCAL_STEP) + 1
    n_p = int(p_cap // PROTEIN_STEP) + 1
    n_m = max(1, full_mask + 1)

    # state -> (payable, tuple_of_indices)
    states: dict[tuple[int, int, int], tuple[float, tuple[int, ...]]] = {
        (0, 0, 0): (0.0, ())
    }

    for idx, item in enumerate(pool):
        price, _ = eff[idx]
        kcal = item.kcal
        prot = item.protein
        mk = masks[idx]
        additions: dict[tuple[int, int, int], tuple[float, tuple[int, ...]]] = {}
        for (k, p, m), (cost, combo) in states.items():
            if len(combo) >= constraints.max_items:
                continue
            nk, np_, nm = kb(k * KCAL_STEP + kcal), pb(p * PROTEIN_STEP + prot), m | mk
            ncost = cost + price
            key = (nk, np_, nm)
            cur = states.get(key) or additions.get(key)
            if cur is None or ncost < cur[0]:
                additions[key] = (ncost, combo + (idx,))
        for key, val in additions.items():
            cur = states.get(key)
            if cur is None or val[0] < cur[0]:
                states[key] = val

    # 精确复算 + 可行性过滤
    plans: list[Plan] = []
    for (k, p, m), _ in states.items():
        if m != full_mask:
            continue
        combo = states[(k, p, m)][1]
        if not combo:
            continue
        plan = _build_plan(pool, combo, coupons, constraints)
        if plan is not None:
            plans.append(plan)

    plans = _dedupe(plans)
    plans.sort(key=_ranker(objective))
    return plans[:top_n]


def _build_plan(
    pool: list[MenuItem],
    combo: tuple[int, ...],
    coupons: list[Coupon],
    cons: Constraints,
) -> Plan | None:
    if len(combo) < cons.min_items:
        return None

    plan_items: list[PlanItem] = []
    subtotal = 0.0
    nutrition: Nutrition | None = None
    for i in combo:
        item = pool[i]
        price, coupon_title = effective_price(item, coupons)
        plan_items.append(PlanItem(item=item, quantity=1, applied_coupon=coupon_title, payable=price))
        subtotal += price
        if item.nutrition:
            nutrition = item.nutrition if nutrition is None else nutrition + item.nutrition

    if nutrition is None:
        return None
    if not (cons.kcal_min <= nutrition.energy_kcal <= cons.kcal_max):
        return None
    if nutrition.protein < cons.protein_min:
        return None
    if cons.must_include and not any(
        kw and kw in pi.item.name for kw in cons.must_include for pi in plan_items
    ):
        return None

    order_disc, order_coupon = _order_discount(subtotal, coupons)
    if order_coupon:
        # 整单券记到第一件上, 仅用于展示
        plan_items[0].applied_coupon = plan_items[0].applied_coupon or order_coupon

    payable = round(subtotal - order_disc, 2)
    if payable > cons.budget_max + 1e-6:
        return None

    return Plan(
        items=plan_items,
        subtotal=round(subtotal, 2),
        discount=round(order_disc, 2),
        payable=payable,
        nutrition=nutrition,
    )


def _dedupe(plans: list[Plan]) -> list[Plan]:
    seen: set[tuple[str, ...]] = set()
    out: list[Plan] = []
    for p in plans:
        sig = tuple(sorted(pi.item.code for pi in p.items))
        if sig in seen:
            continue
        seen.add(sig)
        out.append(p)
    return out


def _ranker(objective: str) -> Callable[[Plan], tuple]:
    if objective == "max_protein":
        return lambda p: (-p.protein, p.payable, -p.kcal)
    if objective == "best_value":
        return lambda p: (-(p.protein / p.payable if p.payable else 0), p.payable)
    return lambda p: (p.payable, -p.protein, p.kcal)


def brute_force(
    items: list[MenuItem],
    constraints: Constraints,
    coupons: list[Coupon] | None = None,
    top_n: int = 3,
) -> list[Plan]:
    """小样本穷举, 用于校验 DP 结果 (仅建议 len(items) <= 12)。"""
    constraints.validate()
    coupons = coupons or []
    pool = _filter_items(items, constraints)
    plans: list[Plan] = []
    for r in range(constraints.min_items, constraints.max_items + 1):
        for combo in itertools.combinations(range(len(pool)), r):
            plan = _build_plan(pool, combo, coupons, constraints)
            if plan is not None:
                plans.append(plan)
    plans = _dedupe(plans)
    plans.sort(key=_ranker("min_price"))
    return plans[:top_n]


def cheapest_per_yuan_protein(
    items: list[MenuItem], protein_min: float = 0.0
) -> list[tuple[MenuItem, float]]:
    """单件性价比排行 (每元蛋白质), 作为辅助决策信息。"""
    rows: list[tuple[MenuItem, float]] = []
    for it in items:
        if it.protein < protein_min or it.price <= 0:
            continue
        rows.append((it, round(it.protein / it.price, 2)))
    rows.sort(key=lambda r: -r[1])
    return rows
