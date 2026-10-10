"""生成 examples/sample-menu.json。

营养数据来自麦当劳 MCP ``list-nutrition-foods`` (真实);
价格为**示例价格**, 仅用于在没有门店数据时演示求解器, 会随地区/门店浮动。
真实下单前务必用 ``calculate-price`` 校验。

用法: MCD_MCP_TOKEN=xxx python scripts/gen_sample_menu.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mcd_meal_optimizer.mcp_client import McdMcpClient  # noqa: E402
from mcd_meal_optimizer.parsers import extract_data, parse_nutrition_table  # noqa: E402

# 餐品名 -> (示例价格元, 分类)
PRICE_MAP: dict[str, tuple[float, str]] = {
    "巨无霸": (25.5, "汉堡"),
    "双层吉士汉堡": (23.5, "汉堡"),
    "吉士汉堡包": (15.5, "汉堡"),
    "麦香鸡": (15.5, "汉堡"),
    "麦香鱼": (16.5, "汉堡"),
    "麦辣鸡腿汉堡": (22.5, "汉堡"),
    "板烧鸡腿堡": (20.5, "汉堡"),
    "培根蔬萃双层牛堡": (24.5, "汉堡"),
    "原味板烧鸡腿麦满分": (19.5, "早餐"),
    "猪柳蛋麦满分": (21.5, "早餐"),
    "猪柳麦满分": (18.5, "早餐"),
    "大脆鸡扒麦满分": (20.5, "早餐"),
    "烟肉蛋麦满分": (19.5, "早餐"),
    "火腿扒麦满分": (18.5, "早餐"),
    "中薯条": (12.5, "小食"),
    "大薯条": (15.5, "小食"),
    "小薯条": (10.5, "小食"),
    "麦乐鸡5块": (13.5, "小食"),
    "麦辣鸡翅-2块": (12.5, "小食"),
    "大杯玉米杯": (11.5, "小食"),
    "小杯玉米杯": (9.5, "小食"),
    "圆筒冰淇淋": (5.5, "甜品"),
    "朱古力新地": (11.5, "甜品"),
    "草莓新地": (10.5, "甜品"),
    "奥利奥麦旋风": (12.5, "甜品"),
    "草莓麦旋风": (12.5, "甜品"),
    "香芋派": (8.5, "甜品"),
    "菠萝派": (8.5, "甜品"),
    "可乐中杯": (10.5, "饮料"),
    "可乐大杯": (12.5, "饮料"),
    "可乐小杯": (8.5, "饮料"),
    "中杯怡泉+C": (10.5, "饮料"),
    "大杯怡泉+C": (12.5, "饮料"),
    "冰美式中杯": (17.0, "饮料"),
    "热美式中杯": (17.0, "饮料"),
    "冰奶铁中杯": (20.0, "饮料"),
    "热奶铁中杯": (20.0, "饮料"),
    "大杯鲜萃咖啡": (18.0, "饮料"),
    "小杯鲜萃咖啡": (14.0, "饮料"),
    "鲜蔬蛋沙拉叠叠卷": (16.5, "卷类"),
    "鸡肉蛋沙拉叠叠卷": (18.5, "卷类"),
}


def main() -> int:
    client = McdMcpClient()
    payload = client.call_tool("list-nutrition-foods", {})
    table = parse_nutrition_table(extract_data(payload) or payload)
    print(f"营养库: {len(table)} 款")

    items = []
    for name, (price, category) in PRICE_MAP.items():
        n = table.get(name)
        if n is None:
            print(f"  ! 营养库缺失, 跳过: {name}")
            continue
        items.append({
            "code": f"SAMPLE-{len(items) + 1:03d}",
            "name": name,
            "price": price,
            "category": category,
            "nutrition": {
                "energy_kj": n.energy_kj,
                "energy_kcal": n.energy_kcal,
                "protein": n.protein,
                "fat": n.fat,
                "carbohydrate": n.carbohydrate,
                "sodium": n.sodium,
                "calcium": n.calcium,
            },
        })

    out = {
        "name": "麦当劳示例菜单 (营养数据来自 MCP, 价格为示例)",
        "note": "价格仅为演示用示例值, 真实价格以 query-meals / calculate-price 返回为准。",
        "count": len(items),
        "items": items,
    }
    dest = ROOT / "examples" / "sample-menu.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写入 {dest} ({len(items)} 款)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
