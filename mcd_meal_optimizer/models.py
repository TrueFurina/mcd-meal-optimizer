"""领域模型: 餐品、营养、优惠券、约束与方案。"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Iterable


# --------------------------------------------------------------------- 营养


@dataclass(frozen=True)
class Nutrition:
    """单份餐品的营养成分 (每份含量)。"""

    energy_kj: float = 0.0
    energy_kcal: float = 0.0
    protein: float = 0.0   # 克
    fat: float = 0.0       # 克
    carbohydrate: float = 0.0  # 克
    sodium: float = 0.0    # 毫克
    calcium: float = 0.0   # 毫克

    def __add__(self, other: "Nutrition") -> "Nutrition":
        return Nutrition(
            self.energy_kj + other.energy_kj,
            self.energy_kcal + other.energy_kcal,
            self.protein + other.protein,
            self.fat + other.fat,
            self.carbohydrate + other.carbohydrate,
            self.sodium + other.sodium,
            self.calcium + other.calcium,
        )


ZERO_NUTRITION = Nutrition()


# --------------------------------------------------------------------- 餐品


@dataclass
class MenuItem:
    """门店在售餐品。

    code 为门店内唯一餐品编码; price 为原价 (元)。nutrition 可能缺失
    (菜单接口不含营养, 需按名称与营养库匹配)。
    """

    code: str
    name: str
    price: float
    category: str = ""
    nutrition: Nutrition | None = None
    tags: list[str] = field(default_factory=list)
    # 门店原价 (元), 无优惠时的牌价; 为 0 表示接口未提供
    original_price: float = 0.0
    # 套餐的默认组成 (来自 query-meal-detail 的 rounds[].choices[].name)
    components: list[str] = field(default_factory=list)
    # 组成里未能匹配到营养数据的部分 (营养不完整时非空, 用于诚实标注)
    nutrition_missing: list[str] = field(default_factory=list)

    @property
    def nutrition_complete(self) -> bool:
        """营养是否完整可信 (组成全部命中营养库)。"""
        return self.nutrition is not None and not self.nutrition_missing

    @property
    def kcal(self) -> float:
        return self.nutrition.energy_kcal if self.nutrition else 0.0

    @property
    def protein(self) -> float:
        return self.nutrition.protein if self.nutrition else 0.0


# --------------------------------------------------------------------- 优惠券


@dataclass
class Coupon:
    """优惠券。

    kind:
      - ``fixed_price``   指定餐品用券价 (price 为该到手价)
      - ``percent_off``   指定餐品折扣 (price 为折扣率, 如 0.7)
      - ``threshold_off`` 满 threshold 减 price
      - ``unknown``       无法解析, 仅展示不计价
    scope: 券适用的餐品名或关键词; 为空表示全场。
    """

    title: str
    kind: str = "unknown"
    price: float = 0.0
    threshold: float = 0.0
    scope: str = ""
    tags: list[str] = field(default_factory=list)
    raw: str = ""

    def applies_to(self, item: MenuItem) -> bool:
        if not self.scope:
            return True
        return self.scope in item.name or item.name in self.scope


# --------------------------------------------------------------------- 约束


@dataclass
class Constraints:
    """双目标约束。"""

    kcal_min: float = 0.0
    kcal_max: float = 1e9
    protein_min: float = 0.0
    budget_max: float = 1e9
    min_items: int = 1
    max_items: int = 4
    # 必须包含的餐品名关键词 (如 "汉堡"), 任一命中即可
    must_include: list[str] = field(default_factory=list)
    # 排除的餐品名关键词
    exclude: list[str] = field(default_factory=list)
    # 是否允许同一餐品重复
    allow_duplicates: bool = False
    # 营养约束生效时, 是否只接受营养**完整**的餐品。
    # True (默认) 时, 营养缺失/不完整的餐品不会进入解 —— 否则它们的
    # 热量与蛋白会被低估, 让"达标"结论失真。
    require_complete_nutrition: bool = True

    def validate(self) -> None:
        if self.kcal_min > self.kcal_max:
            raise ValueError("kcal_min 不能大于 kcal_max")
        if self.min_items < 1:
            raise ValueError("min_items 至少为 1")
        if self.max_items < self.min_items:
            raise ValueError("max_items 不能小于 min_items")


# --------------------------------------------------------------------- 方案


@dataclass
class PlanItem:
    item: MenuItem
    quantity: int = 1
    applied_coupon: str | None = None
    payable: float = 0.0


@dataclass
class Plan:
    """一个餐搭方案。"""

    items: list[PlanItem]
    subtotal: float
    discount: float
    payable: float
    nutrition: Nutrition

    @property
    def kcal(self) -> float:
        return self.nutrition.energy_kcal

    @property
    def protein(self) -> float:
        return self.nutrition.protein

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": [
                {
                    "code": pi.item.code,
                    "name": pi.item.name,
                    "quantity": pi.quantity,
                    "price": round(pi.item.price, 2),
                    "payable": round(pi.payable, 2),
                    "coupon": pi.applied_coupon,
                }
                for pi in self.items
            ],
            "subtotal": round(self.subtotal, 2),
            "discount": round(self.discount, 2),
            "payable": round(self.payable, 2),
            "nutrition": {k: round(v, 2) for k, v in asdict(self.nutrition).items()},
        }


def total_nutrition(items: Iterable[MenuItem]) -> Nutrition:
    acc = ZERO_NUTRITION
    for it in items:
        if it.nutrition:
            acc = acc + it.nutrition
    return acc
