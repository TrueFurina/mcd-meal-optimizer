"""麦麦算盘 · 麦当劳营养×预算双目标餐搭管家。

在预算上限与营养目标(热量/蛋白质)双约束下, 基于**真实门店菜单**、
**真实优惠券**与 **calculate-price 真实算价**, 求最优餐搭方案, 并可
一键创建真实订单(需显式确认)。

门店发现不依赖账号收藏: 走
``mall-points-products -> query-party-city -> query-party-store`` 链路
按城市拿到真实 storeCode。
"""

__version__ = "1.1.0"
__all__ = ["__version__"]
