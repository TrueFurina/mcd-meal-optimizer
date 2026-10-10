"""导出真实门店的菜单快照, 供仓库作为**可复现证据**与离线演示数据。

用法::

    # 按城市自动发现门店并导出
    python scripts/snapshot_store.py --city 上海
    # 或直接指定门店编码
    python scripts/snapshot_store.py --store-code 1450713

产物: ``examples/real-menu-<storeCode>.json``, 结构::

    {
      "meta": {门店/抓取时间/数据来源/营养覆盖率},
      "items": [ {code, name, price, original_price, category, tags,
                  nutrition, components, nutrition_missing, complete} ]
    }

快照只含**公开菜单与营养数据**, 不含任何账号信息或凭据。导出后可直接:

    python -m mcd_meal_optimizer plan --menu-file examples/real-menu-1450713.json \\
        --kcal-min 550 --kcal-max 800 --protein 30 --budget 40
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mcd_meal_optimizer.mcp_client import McdMcpClient, McdMcpError  # noqa: E402
from mcd_meal_optimizer.planner import McdPlanService  # noqa: E402

EXAMPLES = ROOT / "examples"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="导出真实门店菜单快照")
    ap.add_argument("--city", help="城市名, 自动发现门店")
    ap.add_argument("--store-code", help="门店编码")
    ap.add_argument("--be-type", type=int, default=1, help="1=到店自取")
    ap.add_argument("--order-type", type=int, default=1)
    ap.add_argument("--out", help="输出路径, 默认 examples/real-menu-<code>.json")
    args = ap.parse_args(argv)

    client = McdMcpClient()
    svc = McdPlanService(client)

    store = None
    if args.city:
        found = svc.discover_stores(args.city, limit=1)
        if found:
            store = found[0]
    store_code = args.store_code or (store or {}).get("code")
    if not store_code:
        print("未找到门店: 请用 --city 或 --store-code 指定。", file=sys.stderr)
        return 2

    print(f"门店: {store_code} {store['name'] if store else ''}".rstrip())
    t0 = time.time()
    items = svc.menu(store_code, be_type=args.be_type, order_type=args.order_type)
    if not items:
        print("未取到菜单。", file=sys.stderr)
        return 1

    cov = svc.nutrition_coverage(items)
    payload = {
        "meta": {
            "store_code": store_code,
            "store_name": (store or {}).get("name", ""),
            "store_address": (store or {}).get("address", ""),
            "city": (store or {}).get("city", ""),
            "be_type": args.be_type,
            "order_type": args.order_type,
            "source": "麦当劳 MCP (query-meals + query-meal-detail + list-nutrition-foods)",
            "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "item_count": len(items),
            "nutrition_coverage": cov,
            "note": (
                "price/original_price 单位为元, 取自 query-meals 的门店陈列价; "
                "真实成交价(含券)需用 calculate-price。nutrition 由套餐组成求和, "
                "nutrition_missing 非空表示部分组成未收录营养, 求解时会被排除。"
            ),
        },
        "items": [
            {
                "code": it.code,
                "name": it.name,
                "price": round(it.price, 2),
                "original_price": round(it.original_price, 2),
                "category": it.category,
                "tags": it.tags,
                "components": it.components,
                "nutrition_missing": it.nutrition_missing,
                "complete": it.nutrition_complete,
                "nutrition": asdict(it.nutrition) if it.nutrition else None,
            }
            for it in items
        ],
    }

    out = Path(args.out) if args.out else EXAMPLES / f"real-menu-{store_code}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"餐品 {len(items)} 项 | 营养完整 {cov['complete']} / 部分 {cov['partial']} / 无 {cov['none']}")
    print(f"耗时 {time.time() - t0:.1f}s -> {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except McdMcpError as exc:
        print(f"[MCP 错误] {exc}", file=sys.stderr)
        raise SystemExit(1)
