"""麦当劳 MCP (Model Context Protocol) 轻量客户端。

- 协议: Streamable HTTP, 服务地址 https://mcp.mcd.cn
- 鉴权: 请求头 Authorization: Bearer <MCD_MCP_TOKEN>
- 零第三方依赖: 仅使用 Python 标准库 (urllib)

MCP 工具返回的 result.content[0].text 里同时包含「字段说明」和一段
载有真实数据的 JSON, 本模块负责提取其中的 JSON 并统一抛出异常。
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

DEFAULT_URL = "https://mcp.mcd.cn"
TOKEN_ENV = "MCD_MCP_TOKEN"

# 服务端返回文本中的真实数据段落标记
_RESPONSE_MARKERS = ("## Original Response", "## Complete API Response")


class McdMcpError(RuntimeError):
    """麦当劳 MCP 调用失败。"""


class McdMcpClient:
    """最小可用的麦当劳 MCP 客户端。"""

    def __init__(
        self,
        token: str | None = None,
        url: str = DEFAULT_URL,
        timeout: float = 30.0,
    ) -> None:
        token = token or os.environ.get(TOKEN_ENV, "").strip()
        if not token:
            raise McdMcpError(
                f"未找到 MCP Token。请设置环境变量 {TOKEN_ENV}, "
                f"或通过 token 参数传入。"
            )
        self.url = url
        self.timeout = timeout
        self.token = token
        self._session_id: str | None = None
        self._seq = 0

    # ---------------------------------------------------------------- 底层

    def _rpc(self, method: str, params: dict[str, Any] | None = None) -> Any:
        self._seq += 1
        payload = {"jsonrpc": "2.0", "id": self._seq, "method": method}
        if params is not None:
            payload["params"] = params

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        req = urllib.request.Request(
            self.url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                sid = resp.headers.get("Mcp-Session-Id")
                if sid:
                    self._session_id = sid
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:  # 4xx / 5xx
            detail = exc.read().decode("utf-8", "replace")[:500]
            if exc.code == 401:
                raise McdMcpError(
                    "401: MCP Token 无效、已过期或未提供, 请检查 "
                    f"{TOKEN_ENV}。"
                ) from exc
            if exc.code == 429:
                raise McdMcpError(
                    "429: 触发限流 (600 次/分钟), 请降低请求频率。"
                ) from exc
            raise McdMcpError(f"HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise McdMcpError(f"网络错误: {exc.reason}") from exc

        return self._decode(raw)

    @staticmethod
    def _decode(raw: str) -> Any:
        """兼容 JSON 与 SSE (text/event-stream) 两种响应。"""
        raw = raw.strip()
        if not raw:
            raise McdMcpError("服务端返回空响应")

        if raw.startswith("event:") or raw.startswith("data:"):
            chunks = [
                line[len("data:"):].strip()
                for line in raw.splitlines()
                if line.startswith("data:")
            ]
            raw = "\n".join(c for c in chunks if c)

        try:
            body = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise McdMcpError(f"响应不是合法 JSON: {raw[:200]}") from exc

        if isinstance(body, dict) and body.get("error"):
            err = body["error"]
            raise McdMcpError(
                f"JSON-RPC 错误 {err.get('code')}: {err.get('message')}"
            )
        return body.get("result", body)

    # ---------------------------------------------------------------- 上层

    def initialize(self) -> dict[str, Any]:
        """完成 MCP 握手, 返回 serverInfo。"""
        res = self._rpc(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "mcd-meal-optimizer", "version": "1.0.0"},
            },
        )
        return res or {}

    def list_tools(self) -> list[dict[str, Any]]:
        res = self._rpc("tools/list", {})
        return (res or {}).get("tools", [])

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        """调用 MCP 工具并返回其中的业务数据 (已解析为 Python 对象)。"""
        res = self._rpc(
            "tools/call", {"name": name, "arguments": arguments or {}}
        )
        return self._extract_payload(res, name)

    @staticmethod
    def _extract_payload(res: Any, tool: str) -> Any:
        if not isinstance(res, dict):
            return res
        content = res.get("content")
        if not isinstance(content, list) or not content:
            if res.get("isError"):
                raise McdMcpError(f"工具 {tool} 返回错误: {res}")
            return res

        text = "\n".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        ).strip()

        payload = _parse_payload_text(text)
        if isinstance(payload, dict) and payload.get("success") is False:
            raise McdMcpError(
                f"工具 {tool} 业务失败 [{payload.get('code')}]: "
                f"{payload.get('message')}"
            )
        return payload


def _parse_payload_text(text: str) -> Any:
    """从工具返回文本中抽取真实 JSON。"""
    if not text:
        return {}

    for marker in _RESPONSE_MARKERS:
        idx = text.find(marker)
        if idx != -1:
            tail = text[idx + len(marker):].strip()
            cand = _first_json(tail)
            if cand is not None:
                return cand

    cand = _first_json(text)
    return cand if cand is not None else {"text": text}


def _first_json(text: str) -> Any:
    """返回文本中第一个可解析的 JSON 值 (对象/数组)。"""
    text = text.strip()
    # 去掉 markdown 代码围栏
    text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text).strip()
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch in "{[":
            try:
                obj, _ = decoder.raw_decode(text[i:])
                return obj
            except json.JSONDecodeError:
                continue
    return None
