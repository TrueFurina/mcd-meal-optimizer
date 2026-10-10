"""命令行入口: python -m mcd_meal_optimizer <command>

命令:
    check        连通性与账号状态自检
    tools        列出麦当劳 MCP 当前支持的工具
    nutrition    查询餐品营养数据
    coupons      查看可用 / 可领取优惠券
    stores       门店查询 / 按城市发现真实门店
    menu         查看门店真实菜单 (含营养覆盖统计)
    plan         双目标餐搭求解 (核心命令)
    price        对指定餐品组合做真实算价 (calculate-price)
    order        真实下单 (create-order, 必须显式 --confirm)
    cancel       取消订单
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from . import __version__
from .mcp_client import McdMcpClient, McdMcpError
from .models import Constraints, MenuItem
from .orders import OrderConfirmRequired, render_price
from .planner import McdPlanService, load_sample_menu, summarize_prices

BANNER = f"麦麦算盘 · 麦当劳营养×预算餐搭管家 v{__version__}"

BE_TYPE_HELP = "1=到店自取 5=得来速 2=麦乐送 6=团餐"


def _client() -> McdMcpClient:
    try:
        c = McdMcpClient()
        c.initialize()
        return c
    except McdMcpError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        print("提示: 请先申请 MCP Token 并设置环境变量 MCD_MCP_TOKEN。", file=sys.stderr)
        raise SystemExit(2)


def _parse_items(specs: list[str] | None) -> list[dict[str, Any]]:
    """``--item 9900005456`` 或 ``--item 9900005456:2`` -> items 结构。"""
    out: list[dict[str, Any]] = []
    for spec in specs or []:
        spec = spec.strip()
        if not spec:
            continue
        code, _, qty = spec.partition(":")
        out.append({"productCode": code.strip(), "quantity": int(qty or 1)})
    return out


# ------------------------------------------------------------------ 自检


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

    print(f"- 营养库: {len(svc.nutrition_table())} 款餐品")

    coupons = svc.coupons()
    print(f"- 券: 共 {len(coupons)} 张 (卡包 + 麦麦省)")

    try:
        print(f"- 配送地址: {len(svc.addresses())} 个")
    except McdMcpError:
        print("- 配送地址: 查询失败")

    owned = svc.find_stores(search_type=1)
    print(f"- 收藏门店: {len(owned)} 家")

    city = args.city
    if city:
        found = svc.discover_stores(city, limit=3)
        print(f"- 「{city}」门店发现: {len(found)} 家")
        for s in found:
            print(f"    {s['code']}  {s['name']}")
        if found:
            print("- 到店自取下单链路: 可用 (无需账号配置门店)")
            return 0

    if not owned and not city:
        print(
            "  ℹ 未取到收藏门店 —— 这不影响使用。\n"
            "    门店发现可走城市链路:  mcd_meal_optimizer stores --city 上海\n"
            "    或直接指定门店编码:    --store-code 1450713"
        )
    return 0


def cmd_tools(args: argparse.Namespace) -> int:
    tools = _client().list_tools()
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
    stores: list[dict[str, Any]] = []
    label = ""
    if args.city:
        stores = svc.discover_stores(args.city, limit=args.top)
        label = f"城市发现「{args.city}」"
    if not stores:
        stores = svc.find_stores(
            city=args.city, keyword=args.keyword,
            be_type=args.be_type, search_type=args.search_type,
        )[: args.top]
        label = "账号门店查询"

    if not stores:
        print("未查询到门店。")
        print("  - 账号侧未配置定位/收藏门店时, query-nearby-stores 会返回空。")
        print("  - 请用 --city 走城市发现链路:  stores --city 上海")
        return 1

    print(f"{label}: 共 {len(stores)} 家\n")
    for s in stores:
        dist = f"  {s['distance']:.0f}m" if s.get("distance", -1) >= 0 else ""
        print(f"- {s['code']:<10} {s['name']}{dist}")
        if s.get("address"):
            print(f"  {'':<10} {s['address']}")
    return 0


def cmd_menu(args: argparse.Namespace) -> int:
    svc = McdPlanService(_client())
    store_code = args.store_code
    if not store_code and args.city:
        found = svc.discover_stores(args.city, limit=1)
        if found:
            store_code = found[0]["code"]
            print(f"# 自动选中门店: {store_code} {found[0]['name']}\n")
    if not store_code:
        print("需要 --store-code, 或用 --city 自动发现门店。")
        return 1

    items = svc.menu(
        store_code,
        be_type=args.be_type,
        order_type=args.order_type,
        attach_nutrition_data=not args.no_enrich,
    )
    if not items:
        print("未取到菜单。请确认 storeCode 有效。")
        return 1

    cov = svc.nutrition_coverage(items)
    info = summarize_prices(items)
    info["nutrition_coverage"] = cov
    print(json.dumps(info, ensure_ascii=False, indent=2))
    print()
    print(f"{'编码':<12}{'餐品':<26}{'现价':>8}{'原价':>8}{'热量':>8}{'蛋白':>7}")
    for it in items[: args.top]:
        if it.nutrition_complete:
            kcal, prot, mark = f"{it.kcal:.0f}", f"{it.protein:.1f}", ""
        elif it.nutrition is not None:
            # 只匹配到部分组成 —— 显示"部分", 不把残值当总热量展示
            kcal, prot, mark = "部分", "部分", "*"
        else:
            kcal, prot, mark = "—", "—", ""
        print(f"{it.code:<12}{it.name:<26}{it.price:>8.2f}{it.original_price:>8.2f}{kcal:>8}{prot:>7} {mark}")
    if args.top < len(items):
        print(f"... 共 {len(items)} 项")
    print("\n* = 套餐的组成部分未全部收录营养, 求解时会被排除 (不按 0 计算)")
    return 0


def _resolve_store(svc: McdPlanService, args: argparse.Namespace) -> str | None:
    if args.store_code:
        return args.store_code
    if getattr(args, "city", None):
        found = svc.discover_stores(args.city, limit=1)
        if found:
            print(f"# 自动选中门店: {found[0]['code']} {found[0]['name']}\n")
            return found[0]["code"]
    return None


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

    store_code = None
    if not menu_items:
        store_code = _resolve_store(svc, args)

    plans, meta = svc.plan(
        cons,
        menu_items=menu_items,
        store_code=store_code,
        be_type=args.be_type,
        order_type=args.order_type,
        objective=args.objective,
        top_n=args.top,
        allow_sample_fallback=not args.no_fallback,
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
    cov = meta.get("coverage") or {}
    print(f"数据来源: 菜单={meta.get('menu_source')} | 券={meta.get('coupons')} | "
          f"营养完整={cov.get('complete', meta.get('nutrition'))}/{cov.get('total', '?')}\n")
    print(svc.render(plans, cons, meta))

    if plans and store_code and args.price_check:
        print("\n--- 真实算价 (calculate-price) ---")
        priced = svc.orders.price(store_code, plans[0].items, be_type=args.be_type)
        print(render_price(priced, f"方案 1 · 门店 {store_code}"))
        print("\n下单: 在 plan 结果上确认后执行")
        codes = " ".join(f"--item {pi.item.code}" for pi in plans[0].items)
        print(f"  python -m mcd_meal_optimizer order --store-code {store_code} {codes} --confirm")
    return 0 if plans else 1


def cmd_price(args: argparse.Namespace) -> int:
    svc = McdPlanService(_client())
    store_code = _resolve_store(svc, args)
    if not store_code:
        print("需要 --store-code, 或用 --city 自动发现门店。")
        return 1
    items = _parse_items(args.item)
    if not items:
        print("需要至少一个 --item <餐品编码>[:数量]。")
        return 1
    result = svc.orders.price(store_code, items, be_type=args.be_type, be_code=args.be_code)
    print(render_price(result, f"门店 {store_code} · 真实算价"))
    if args.json:
        print(json.dumps(result.raw, ensure_ascii=False, indent=2))
    return 0


def cmd_order(args: argparse.Namespace) -> int:
    svc = McdPlanService(_client())
    store_code = _resolve_store(svc, args)
    if not store_code:
        print("需要 --store-code, 或用 --city 自动发现门店。")
        return 1
    items = _parse_items(args.item)
    if not items:
        print("需要至少一个 --item <餐品编码>[:数量]。")
        return 1

    preview = svc.orders.preview(
        store_code, items, take_way_code=args.take_way,
        be_type=args.be_type, be_code=args.be_code,
    )

    print("## 下单预览 (尚未提交)")
    print(f"- 门店: {store_code}")
    print(f"- 类型: beType={preview['be_type']} orderType={preview['order_type']}")
    print(f"- 取餐: {preview['take_way_code']}"
          + (f"  可选项: " + " / ".join(f"{o['title']}({o['code']})" for o in preview['take_way_options'])
             if preview["take_way_options"] else ""))
    for row in preview["lines"]:
        print(f"  · {row['name']} ×{row['quantity']}  ¥{row['payable']:.2f}")
    print(f"- **合计 ¥{preview['payable']:.2f}**")

    if not args.confirm:
        print("\n! 未提交: 真实下单会挂到你的麦当劳账号上。")
        print("  确认无误后, 追加 --confirm 重新执行即可建单。")
        if args.json:
            print(json.dumps(preview, ensure_ascii=False, indent=2, default=str))
        return 0

    try:
        result = svc.orders.submit(
            store_code, items, take_way_code=preview["take_way_code"],
            be_type=args.be_type, be_code=args.be_code, confirm=True, remark=args.remark,
        )
    except OrderConfirmRequired as exc:
        print(f"[拒单] {exc}", file=sys.stderr)
        return 1

    print("\n## 订单已创建")
    print(f"- 订单号: {result.order_id or '(接口未返回)'}")
    print(f"- 应付: ¥{result.payable:.2f}")
    if result.pay_url:
        print(f"- 支付入口: {result.pay_url}")
    print("请在麦当劳 App 或支付链接完成支付。")
    if args.json:
        print(json.dumps(result.raw, ensure_ascii=False, indent=2))
    return 0


def cmd_cancel(args: argparse.Namespace) -> int:
    svc = McdPlanService(_client())
    data = svc.orders.cancel(args.order_id, reason_code=args.reason)
    print(f"订单 {args.order_id}: " + ("已取消" if data else "(接口无返回内容)"))
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


# ------------------------------------------------------------------ 解析器


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mcd_meal_optimizer", description=BANNER)
    p.add_argument("-v", "--version", action="version", version=BANNER)
    sub = p.add_subparsers(dest="command", required=True)

    ck = sub.add_parser("check", help="连通性与账号状态自检")
    ck.add_argument("--city", help="顺带验证该城市的门店发现链路")
    ck.set_defaults(func=cmd_check)

    sub.add_parser("tools", help="列出 MCP 工具").set_defaults(func=cmd_tools)

    n = sub.add_parser("nutrition", help="查询营养数据")
    n.add_argument("--query", help="餐品名关键词")
    n.add_argument("--sort", choices=["kcal", "protein"], default="kcal")
    n.add_argument("--top", type=int, default=20)
    n.set_defaults(func=cmd_nutrition)

    sub.add_parser("coupons", help="查看优惠券").set_defaults(func=cmd_coupons)

    s = sub.add_parser("stores", help="门店查询 / 按城市发现真实门店")
    s.add_argument("--city", help="城市名, 如 上海 —— 走不依赖账号的门店发现链路")
    s.add_argument("--keyword")
    s.add_argument("--be-type", type=int, default=1, help=BE_TYPE_HELP)
    s.add_argument("--search-type", type=int, default=2)
    s.add_argument("--top", type=int, default=15)
    s.set_defaults(func=cmd_stores)

    m = sub.add_parser("menu", help="查看门店真实菜单")
    m.add_argument("--store-code")
    m.add_argument("--city", help="不传 store-code 时, 按城市自动发现门店")
    m.add_argument("--be-type", type=int, default=1, help=BE_TYPE_HELP)
    m.add_argument("--order-type", type=int, default=1)
    m.add_argument("--top", type=int, default=25)
    m.add_argument("--no-enrich", action="store_true",
                   help="跳过套餐拆解, 只做直接名称匹配")
    m.set_defaults(func=cmd_menu)

    pl = sub.add_parser("plan", help="双目标餐搭求解 (核心)")
    pl.add_argument("--kcal-min", type=float, default=500)
    pl.add_argument("--kcal-max", type=float, default=800)
    pl.add_argument("--protein", type=float, default=30, help="蛋白质下限 (g)")
    pl.add_argument("--budget", type=float, default=40, help="预算上限 (元)")
    pl.add_argument("--min-items", type=int, default=1)
    pl.add_argument("--max-items", type=int, default=4)
    pl.add_argument("--store-code")
    pl.add_argument("--city", help="按城市自动发现门店")
    pl.add_argument("--be-type", type=int, default=1, help=BE_TYPE_HELP)
    pl.add_argument("--order-type", type=int, default=1)
    pl.add_argument("--menu-file", help="离线菜单 JSON 路径")
    pl.add_argument("--include", action="append", help="必须包含的餐品关键词 (可重复)")
    pl.add_argument("--exclude", action="append", help="排除的餐品关键词 (可重复)")
    pl.add_argument("--objective", choices=["min_price", "max_protein", "best_value"], default="min_price")
    pl.add_argument("--top", type=int, default=3)
    pl.add_argument("--price-check", action="store_true", help="对最优方案调用 calculate-price 真实算价")
    pl.add_argument("--no-fallback", action="store_true", help="无门店菜单时不回退示例菜单")
    pl.add_argument("--json", action="store_true")
    pl.set_defaults(func=cmd_plan)

    pr = sub.add_parser("price", help="对指定餐品组合真实算价")
    pr.add_argument("--store-code")
    pr.add_argument("--city")
    pr.add_argument("--be-type", type=int, default=1, help=BE_TYPE_HELP)
    pr.add_argument("--be-code")
    pr.add_argument("--item", action="append", help="餐品编码, 可 CODE:数量 (可重复)")
    pr.add_argument("--json", action="store_true")
    pr.set_defaults(func=cmd_price)

    od = sub.add_parser("order", help="真实下单 (默认只预览, 需 --confirm)")
    od.add_argument("--store-code")
    od.add_argument("--city")
    od.add_argument("--be-type", type=int, default=1, help=BE_TYPE_HELP)
    od.add_argument("--be-code")
    od.add_argument("--item", action="append", help="餐品编码, 可 CODE:数量 (可重复)")
    od.add_argument("--take-way", help="取餐方式, 取 calculate-price 的 takeWayList code, 如 eat-in")
    od.add_argument("--remark", help="备注 (仅外送)")
    od.add_argument("--confirm", action="store_true", help="确认提交真实订单")
    od.add_argument("--json", action="store_true")
    od.set_defaults(func=cmd_order)

    cn = sub.add_parser("cancel", help="取消订单")
    cn.add_argument("--order-id", required=True)
    cn.add_argument("--reason", type=int, default=1,
                    help="1=改主意 2=重复下单 3=点错 4=地址错 5=时间错 -1=其它")
    cn.add_argument("--json", action="store_true")
    cn.set_defaults(func=cmd_cancel)

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
