"""门店发现: 在账号**未配置收藏门店/配送地址**时也能拿到真实门店。

麦当劳 MCP 的 ``query-nearby-stores`` 依赖账号侧的定位/收藏, 全新账号会
返回空列表。本模块给出一条不依赖账号配置的替代链路::

    mall-points-products                # 取派对商品 spuId (公开数据)
      └─> query-party-city   {spuId}    # 取城市 code + 经纬度
            └─> query-party-store {code, latitude, longitude, spuId}
                                        # 取该城市门店列表 (含 storeCode)

拿到 ``storeCode`` 后即可调用 ``query-meals`` / ``calculate-price`` /
``create-order`` —— 这三个接口只认门店编码, 与账号收藏无关。

链路失败时自动回退到 ``query-nearby-stores``, 因此对已配置账号同样可用。
"""

from __future__ import annotations

from typing import Any

from .mcp_client import McdMcpClient, McdMcpError
from .parsers import extract_data

# 任意一个 ``shopId=5`` 的派对类商品都可以, 这里用「麦当劳亲子读书会」兜底。
DEFAULT_PARTY_SPU_ID = 1830


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _norm_store(raw: dict[str, Any], source: str) -> dict[str, Any] | None:
    """把不同接口的门店对象归一化成统一字段。"""
    if not isinstance(raw, dict):
        return None
    code = str(raw.get("code") or raw.get("storeCode") or "").strip()
    name = str(raw.get("name") or raw.get("storeName") or "").strip()
    if not code or not name:
        return None
    return {
        "code": code,
        "name": name,
        "address": str(raw.get("address") or "").strip(),
        "city": str(raw.get("cityName") or raw.get("city") or "").strip(),
        "latitude": _num(raw.get("latitude")),
        "longitude": _num(raw.get("longitude")),
        "distance": _num(raw.get("distance"), -1),
        "be_code": str(raw.get("beCode") or "").strip(),
        "source": source,
    }


def _match_city(cities: list[dict[str, Any]], wanted: str) -> dict[str, Any] | None:
    """城市名对齐: 先精确, 再前缀 (上海 -> 上海市), 最后包含。"""
    if not wanted:
        return None
    w = wanted.strip()
    for c in cities:
        if c.get("name") == w:
            return c
    for c in cities:
        if str(c.get("name") or "").startswith(w):
            return c
    for c in cities:
        if w in str(c.get("name") or ""):
            return c
    return None


class StoreFinder:
    """真实门店发现器。"""

    def __init__(self, client: McdMcpClient) -> None:
        self.client = client

    # ------------------------------------------------------- 派对链路

    def party_spu_id(self) -> int:
        """从积分商城取一个可用派对的 spuId。"""
        try:
            payload = self.client.call_tool("mall-points-products", {})
        except McdMcpError:
            return DEFAULT_PARTY_SPU_ID
        data = extract_data(payload)
        if isinstance(data, list):
            for row in data:
                if isinstance(row, dict) and row.get("spuId"):
                    return int(row["spuId"])
        return DEFAULT_PARTY_SPU_ID

    def party_cities(self, spu_id: int | None = None) -> list[dict[str, Any]]:
        spu = spu_id or self.party_spu_id()
        payload = self.client.call_tool("query-party-city", {"spuId": spu})
        data = extract_data(payload)
        return [c for c in data if isinstance(c, dict)] if isinstance(data, list) else []

    def party_stores(
        self, city: str, spu_id: int | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        """按城市名查询门店 (不依赖账号收藏)。"""
        spu = spu_id or self.party_spu_id()
        city_rec = _match_city(self.party_cities(spu), city)
        if city_rec is None:
            return []
        payload = self.client.call_tool(
            "query-party-store",
            {
                "code": str(city_rec.get("code")),
                "latitude": city_rec.get("latitude"),
                "longitude": city_rec.get("longitude"),
                "spuId": spu,
            },
        )
        data = extract_data(payload)
        rows = data if isinstance(data, list) else []
        out = [_norm_store(r, "party-city") for r in rows]
        return [s for s in out if s][:limit]

    # ------------------------------------------------------- 账号链路

    def nearby(
        self,
        city: str | None = None,
        keyword: str | None = None,
        be_type: int = 1,
        search_type: int = 2,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """``query-nearby-stores`` (依赖账号定位/收藏门店)。"""
        args: dict[str, Any] = {"beType": be_type, "searchType": search_type}
        if city:
            args["city"] = city
        if keyword:
            args["keyword"] = keyword
        payload = self.client.call_tool("query-nearby-stores", args)
        data = extract_data(payload)
        rows = data if isinstance(data, list) else []
        out = [_norm_store(r, "nearby-stores") for r in rows]
        return [s for s in out if s][:limit]

    # ----------------------------------------------------------- 组合

    def discover(self, city: str, limit: int = 20) -> list[dict[str, Any]]:
        """按城市发现门店: 先走不依赖账号的派对链路, 空则回退账号链路。"""
        try:
            stores = self.party_stores(city, limit=limit)
            if stores:
                return stores
        except McdMcpError:
            pass
        try:
            return self.nearby(city=city, limit=limit)
        except McdMcpError:
            return []
