"""
lighter_sync_client.py
同步版 Lighter REST 客户端（带签名 + token 缓存）
依赖: pip install lighter-sdk requests
"""

import time
from dataclasses import dataclass
from typing import Dict, Any, Optional
import requests
import lighter  # from lighter-sdk


# ============================ 配置 ============================

@dataclass
class LighterConfig:
    base_url: str = "https://mainnet.zklighter.elliot.ai"
    api_key_private_key: str = ""    # 你的 API_KEY_PRIVATE_KEY
    account_index: int = 0           # ACCOUNT_INDEX
    api_key_index: int = 0           # API_KEY_INDEX
    auth_ttl_seconds: int = 600      # token 有效期缓存时间（默认 10 分钟）


# ============================ 签名与 token 缓存 ============================

class LighterSignerSync:
    def __init__(self, cfg: LighterConfig):
        self._cfg = cfg
        self._client = lighter.SignerClient(
            url=cfg.base_url,
            private_key=cfg.api_key_private_key,
            account_index=cfg.account_index,
            api_key_index=cfg.api_key_index,
        )
        self._auth: Optional[str] = None
        self._expire = 0.0

    def get_auth_token(self) -> str:
        """获取有效 auth_token（过期才重新生成）"""
        if self._auth and time.time() < self._expire - 5:
            return self._auth

        auth, err = self._client.create_auth_token_with_expiry(
            lighter.SignerClient.DEFAULT_10_MIN_AUTH_EXPIRY
        )
        if err:
            raise RuntimeError(f"Signer error: {err}")

        self._auth = auth
        self._expire = time.time() + self._cfg.auth_ttl_seconds
        return auth


# ============================ 同步 HTTP 客户端 ============================

class LighterClientSync:
    def __init__(self, cfg: LighterConfig):
        self._cfg = cfg
        self._signer = LighterSignerSync(cfg)
        self._session = requests.Session()

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        need_auth: bool = False,
        include_auth_query: bool = False,
    ) -> Dict[str, Any]:
        """内部统一请求封装"""
        url = self._cfg.base_url + path
        headers = {"accept": "application/json"}
        params = params or {}

        # 鉴权
        if need_auth:
            token = self._signer.get_auth_token()
            headers["Authorization"] = token
            if include_auth_query:
                params.setdefault("auth", token)

        resp = self._session.request(
            method.upper(),
            url,
            params=params,
            json=json,
            headers=headers,
            timeout=10,
        )

        if resp.status_code != 200:
            raise RuntimeError(f"Lighter HTTP {resp.status_code}: {resp.text[:300]}")
        try:
            return resp.json()
        except Exception:
            return {"raw": resp.text}

    # ============================ 常用 API ============================

    def get_account(self, by: str, value: str) -> Dict[str, Any]:
        """GET /api/v1/account"""
        return self._request(
            "GET", "/api/v1/account",
            params={"by": by, "value": value},
            need_auth=False,
        )

    def get_accounts_by_l1(self, l1_address: str) -> Dict[str, Any]:
        """GET /api/v1/accountsByL1Address"""
        return self._request(
            "GET", "/api/v1/accountsByL1Address",
            params={"l1_address": l1_address},
            need_auth=False,
        )

    def get_account_limits(self, account_index: int) -> Dict[str, Any]:
        """GET /api/v1/accountLimits（需要签名）"""
        return self._request(
            "GET", "/api/v1/accountLimits",
            params={"account_index": account_index},
            need_auth=True,
        )

    def get_account_pnl(
        self,
        by: str,
        value: str,
        resolution: str,
        start_ts: int,
        end_ts: int,
        count_back: int,
    ) -> Dict[str, Any]:
        """GET /api/v1/pnl（需要签名）"""
        return self._request(
            "GET", "/api/v1/pnl",
            need_auth=True,
            params={
                "by": by,
                "value": value,
                "resolution": resolution,
                "start_timestamp": start_ts,
                "end_timestamp": end_ts,
                "count_back": count_back,
            },
        )


# ============================ 示例 ============================

if __name__ == "__main__":
    cfg = LighterConfig(
        api_key_private_key="0xYOUR_PRIVATE_KEY_HERE",
        account_index=123456,
        api_key_index=0,
    )

    client = LighterClientSync(cfg)

    acc = client.get_account(by="index", value=str(cfg.account_index))
    print("account =", acc)

    limits = client.get_account_limits(account_index=cfg.account_index)
    print("limits =", limits)

    now_ms = int(time.time() * 1000)
    pnl = client.get_account_pnl(
        by="index",
        value=str(cfg.account_index),
        resolution="1h",
        start_ts=now_ms - 3 * 24 * 3600 * 1000,
        end_ts=now_ms,
        count_back=72,
    )
    print("pnl =", pnl)