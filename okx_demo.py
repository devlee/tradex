"""OKX 模拟盘私有接口。所有请求都带 x-simulated-trading: 1，不会打到实盘。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

HOST = "https://openapi.okx.com"
SIMULATED = "1"
USER_AGENT = "tradex-demo/0.1"


class OkxError(RuntimeError):
    pass


class DemoClient:
    def __init__(self, api_key: str, secret: str, passphrase: str) -> None:
        self.api_key = api_key
        self.secret = secret
        self.passphrase = passphrase

    def _request(self, method: str, path: str, params: dict | None = None, body: dict | None = None) -> dict:
        query = urllib.parse.urlencode(params or {})
        request_path = f"{path}?{query}" if query else path
        payload = json.dumps(body, separators=(",", ":")) if body is not None else ""
        stamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        message = f"{stamp}{method}{request_path}{payload}"
        sign = base64.b64encode(
            hmac.new(self.secret.encode(), message.encode(), hashlib.sha256).digest()
        ).decode()
        request = urllib.request.Request(HOST + request_path, data=payload.encode() if payload else None, method=method)
        request.add_header("OK-ACCESS-KEY", self.api_key)
        request.add_header("OK-ACCESS-SIGN", sign)
        request.add_header("OK-ACCESS-TIMESTAMP", stamp)
        request.add_header("OK-ACCESS-PASSPHRASE", self.passphrase)
        request.add_header("x-simulated-trading", SIMULATED)
        request.add_header("Content-Type", "application/json")
        request.add_header("User-Agent", USER_AGENT)
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=20) as response:
                    data = json.loads(response.read().decode())
                break
            except urllib.error.HTTPError as error:
                detail = error.read().decode(errors="replace")[:300]
                raise OkxError(f"HTTP {error.code} {detail}") from None
            except urllib.error.URLError as error:
                last_error = error
                if attempt == 2:
                    raise OkxError(f"网络错误 {error.reason}") from None
                time.sleep(0.4 * (attempt + 1))
        else:
            raise OkxError(f"网络错误 {last_error}")
        if data.get("code") != "0":
            detail = data.get("data")
            extra = ""
            if isinstance(detail, list) and detail and isinstance(detail[0], dict):
                extra = detail[0].get("sMsg") or ""
            raise OkxError(extra or data.get("msg") or "OKX 返回失败")
        return data

    def balance(self) -> dict:
        return self._request("GET", "/api/v5/account/balance", {"ccy": "USDT"})

    def config(self) -> dict:
        rows = self._request("GET", "/api/v5/account/config").get("data") or []
        return rows[0] if rows else {}

    def set_leverage(self, inst_id: str, lever: str = "1", pos_side: str | None = None) -> None:
        body = {"instId": inst_id, "lever": lever, "mgnMode": "cross"}
        if pos_side:
            body["posSide"] = pos_side
        self._request("POST", "/api/v5/account/set-leverage", body=body)

    def positions(self, inst_id: str) -> list[dict]:
        return self._request("GET", "/api/v5/account/positions", {"instId": inst_id}).get("data") or []

    def pending_orders(self, inst_id: str) -> list[dict]:
        return self._request("GET", "/api/v5/trade/orders-pending", {"instId": inst_id}).get("data") or []

    def order(self, inst_id: str, cl_ord_id: str) -> dict | None:
        rows = self._request(
            "GET", "/api/v5/trade/order", {"instId": inst_id, "clOrdId": cl_ord_id}
        ).get("data") or []
        return rows[0] if rows else None

    def fills_history(self, inst_id: str) -> list[dict]:
        return self._request(
            "GET",
            "/api/v5/trade/orders-history",
            {"instType": "SWAP", "instId": inst_id, "limit": "20"},
        ).get("data") or []

    def funding_bills(self, inst_id: str) -> list[dict]:
        return self._request(
            "GET",
            "/api/v5/account/bills",
            {"instType": "SWAP", "instId": inst_id, "type": "8", "limit": "100"},
        ).get("data") or []

    def place(self, body: dict) -> dict:
        rows = self._request("POST", "/api/v5/trade/order", body=body).get("data") or []
        row = rows[0] if rows else {}
        if row.get("sCode") not in (None, "0"):
            raise OkxError(row.get("sMsg") or "下单失败")
        return row

    def cancel(self, inst_id: str, cl_ord_id: str) -> None:
        rows = self._request(
            "POST", "/api/v5/trade/cancel-order", body={"instId": inst_id, "clOrdId": cl_ord_id}
        ).get("data") or []
        row = rows[0] if rows else {}
        if row.get("sCode") not in (None, "0"):
            raise OkxError(row.get("sMsg") or "撤单失败")

    def amend(self, inst_id: str, cl_ord_id: str, price: str) -> None:
        rows = self._request(
            "POST",
            "/api/v5/trade/amend-order",
            body={"instId": inst_id, "clOrdId": cl_ord_id, "newPx": price},
        ).get("data") or []
        row = rows[0] if rows else {}
        if row.get("sCode") not in (None, "0"):
            raise OkxError(row.get("sMsg") or "改单失败")


def public_get(path: str, params: dict[str, str]) -> dict:
    query = urllib.parse.urlencode(params)
    url = f"{HOST}{path}?{query}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last_error: Exception | None = None
    data: dict = {}
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                data = json.loads(response.read().decode())
            break
        except urllib.error.URLError as error:
            last_error = error
            if attempt == 2:
                raise OkxError(f"网络错误 {error.reason}") from None
            time.sleep(0.4 * (attempt + 1))
    else:
        raise OkxError(f"网络错误 {last_error}")
    if data.get("code") != "0":
        raise OkxError(data.get("msg") or "行情请求失败")
    return data
