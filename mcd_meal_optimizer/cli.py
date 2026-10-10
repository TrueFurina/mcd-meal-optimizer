"""命令行入口: python -m mcd_meal_optimizer <command>

命令:
    check        连通性与账号状态自检
    tools        列出麦当劳 MCP 当前支持的工具
    nutrition    查询餐品营养数据
    coupons      查看可用 / 可领取优惠券
    stores       查询门店 (需账号已配置位置或收藏门店)
    plan         双目标餐搭求解 (核心命令)
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from . import __version__
from .mcp_client import McdMcpClient, McdMcpError
from .models import Constraints, MenuItem
from .planner import McdPlanService, load_sample_menu, summarize_prices

BANNER = f"麦麦算盘 · 麦当劳营养×预算餐搭管家 v{__version__}"


def _client() -> McdMcpClient:
    try:
        c = McdMcpClient()
        c.initialize()
        return c
    except McdMcpError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        print("提示: 请先申请 MCP Token 并设置环境变量 MCD_MCP_TOKEN。", file=sys.stderr)
        raise SystemExit(2)


def cmd_check(args: argparse.Namespace) -> int:
    client = _client()
    svc = McdPlanService(client)
    print(BANNER)
    print(f"- MCP 服务: {client.url}")
    print("- 连接: OK")

    try:
        acc = client.call_tool("query-my-account", {})
        points = (acc.get("data") or {}).get("availablePoint", "?")
        print(f"- 积分: {points}")
    except McdMcpError as exc:
        print(f"- 积分: 查询失败 ({exc})")

    n = len(svc.nutrition_table())
    print(f"- 营养库: {n} 款餐品")

    coupons = svc.coupons()
    print(f"- 券: 共 {len(coupons)} 张 (卡包 + 麦麦省)")

    try:
        addr = svc.addresses()
        print(f"- 配送地址: {len(addr)} 个")
    except McdMcpError:
        print("- 配送地址: 查询失败")

    stores = svc.find_stores(search_type=1)
    print(f"- 收藏门店: {len(stores)} 家")
    if not stores:
        print(
            "  ! 未取到门店。门店/菜单/下单类工具需要账号侧配置:\n"
            "    在麦当劳 App 收藏一家门店, 或指定 --store-code 手动传入门店编码。"
        )
    return 0


def cmd_tools(args: argparse.Namespace) -> int:
    client = _client()
    tools = client.list_tools()
    print(f"麦当劳 MCP 共 {len(tools)} 个工具:\n")
    for t in sorted(tools, key=lambda x: x["name"]):
        desc = (t.get("description") or "").splitlines()[0][:70]
        print(f"- {t['name']:<24} {desc}")
    return 0


def cmd_nutrition(args: argparse.Namespace) -> int:
    svc = McdPlanService(_client())
    table = svc.nutrition_table()
    rows = [
        (name, n.energy_kcal, n.protein, n.fat, n.carbohydrate)
        for name, n in table.items()
    ]
    if args.query:
        rows = [r for r in rows if args.query in r[0]]
    if args.sort == "protein":
        rows.sort(key=lambda r: -r[2])
    elif args.sort == "kcal":
        rows.sort(key=lambda r: r[1])
    else:
        rows.sort(key=lambda r: -r[1])
    rows = rows[: args.top]

    print(f"营养库命中 {len(rows)} 条 (共 {len(table)} 款)\n")
    print(f"{'餐品':<28}{'热量kcal':>9}{'蛋白g':>7}{'脂肪g':>7}{'碳水g':>7}")
    for name, kcal, prot, fat, carb in rows:
        print(f"{name:<28}{kcal:>9.0f}{prot:>7.1f}{fat:>7.1f}{carb:>7.1f}")
    return 0


def cmd_coupons(args: argparse.Namespace) -> int:
    svc = McdPlanService(_client())
    print("== 我的卡包 ==")
    for c in svc.my_coupons():
        print(f"- {c.title}  [{c.kind}" + (f" ¥{c.price:.2f}" if c.price else "") + f"] {','.join(c.tags)}")
    print("\n== 麦麦省可领取 ==")
    for c in svc.available_coupons():
        print(f"- {c.title}  [{c.kind}] {','.join(c.tags)}")
    return 0


def cmd_stores(args: argparse.Namespace) -> int:
    svc = McdPlanService(_client())
    stores = svc.find_stores(
        city=args.city, keyword=args.keyword, be_type=args.be_type, search_type=args.search_type
    )
    if not stores:
        print("未查询到门店。")
        print("原因通常是账号未配置位置: 请在麦当劳 App 收藏门店后重试, 或直接使用 --store-code。")
        return 1
    for s in stores:
        code = s.get("storeCode") or s.get("code")
        name = s.get("storeName") or s.get("name")
        print(f"- {code}  {name}  {s.get('address', '')}")
    return 0


def cmd_menu(args: argparse.Namespace) -> int:
    svc = McdPlanService(_client())
    items = svc.menu(args.store_code, be_type=args.be_type, order_type=args.order_type)
    if not items:
        print("未取到菜单。请确认 storeCode 有效。")
        return 1
    info = summarize_prices(items)
    print(json.dumps(info, ensure_ascii=False, indent=2))
    for it in items[: args.top]:
        print(f"- {it.code:<12} {it.name:<24} ¥{it.price:.2f}"
              + (f"  {it.kcal:.0f}kcal/{it.protein:.1f}g蛋白" if it.nutrition else ""))
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    svc = McdPlanService(_client())
    cons = Constraints(
        kcal_min=args.kcal_min,
        kcal_max=args.kcal_max,
        protein_min=args.protein,
        budget_max=args.budget,
        min_items=args.min_items,
        max_items=args.max_items,
        must_include=args.include or [],
        exclude=args.exclude or [],
    )
    menu_items: list[MenuItem] | None = None
    if args.menu_file:
        menu_items = load_sample_menu(args.menu_file)

    plans, meta = svc.plan(
        cons,
        menu_items=menu_items,
        store_code=args.store_code,
        be_type=args.be_type,
        order_type=args.order_type,
        objective=args.objective,
        top_n=args.top,
    )

    if args.json:
        print(json.dumps(
            {"meta": meta, "plans": [p.to_dict() for p in plans]},
            ensure_ascii=False, indent=2,
        ))
        return 0 if plans else 1

    print(BANNER)
    print(f"约束: {cons.kcal_min:.0f}-{cons.kcal_max:.0f} kcal | 蛋白≥{cons.protein_min:.0f}g | "
          f"预算≤¥{cons.budget_max:.0f} | 件数 {cons.min_items}-{cons.max_items}")
    print(f"数据来源: 菜单={meta.get('menu_source')} 券={meta.get('coupons')} "
          f"营养匹配={meta.get('nutrition')}\n")
    print(svc.render(plans, cons, meta))
    return 0 if plans else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mcd_meal_optimizer", description=BANNER)
    p.add_argument("-v", "--version", action="version", version=BANNER)
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="连通性与账号状态自检").set_defaults(func=cmd_check)
    sub.add_parser("tools", help="列出 MCP 工具").set_defaults(func=cmd_tools)

    n = sub.add_parser("nutrition", help="查询营养数据")
    n.add_argument("--query", help="餐品名关键词")
    n.add_argument("--sort", choices=["kcal", "protein"], default="kcal")
    n.add_argument("--top", type=int, default=20)
    n.set_defaults(func=cmd_nutrition)

    sub.add_parser("coupons", help="查看优惠券").set_defaults(func=cmd_coupons)

    s = sub.add_parser("stores", help="查询门店")
    s.add_argument("--city")
    s.add_argument("--keyword")
    s.add_argument("--be-type", type=int, default=1)
    s.add_argument("--search-type", type=int, default=2)
    s.set_defaults(func=cmd_stores)

    m = sub.add_parser("menu", help="查询门店菜单")
    m.add_argument("--store-code", required=True)
    m.add_argument("--be-type", type=int, default=1)
    m.add_argument("--order-type", type=int, default=1)
    m.add_argument("--top", type=int, default=20)
    m.set_defaults(func=cmd_menu)

    pl = sub.add_parser("plan", help="双目标餐搭求解 (核心)")
    pl.add_argument("--kcal-min", type=float, default=500)
    pl.add_argument("--kcal-max", type=float, default=800)
    pl.add_argument("--protein", type=float, default=30, help="蛋白质下限 (g)")
    pl.add_argument("--budget", type=float, default=40, help="预算上限 (元)")
    pl.add_argument("--min-items", type=int, default=1)
    pl.add_argument("--max-items", type=int, default=4)
    pl.add_argument("--store-code", help="门店编码; 不传则用示例菜单")
    pl.add_argument("--be-type", type=int, default=1)
    pl.add_argument("--order-type", type=int, default=1)
    pl.add_argument("--menu-file", help="离线菜单 JSON 路径")
    pl.add_argument("--include", action="append", help="必须包含的餐品关键词 (可重复)")
    pl.add_argument("--exclude", action="append", help="排除的餐品关键词 (可重复)")
    pl.add_argument("--objective", choices=["min_price", "max_protein", "best_value"], default="min_price")
    pl.add_argument("--top", type=int, default=3)
    pl.add_argument("--json", action="store_true")
    pl.set_defaults(func=cmd_plan)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except McdMcpError as exc:
        print(f"[MCP 错误] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
