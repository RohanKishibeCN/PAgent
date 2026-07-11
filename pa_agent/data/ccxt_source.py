"""CCXT crypto exchange data source for BTC/ETH spot and futures.

Supports 100+ exchanges via the unified CCXT interface.
Default: Binance spot (BTC/USDT, ETH/USDT).

Proxy support: set ``https_proxy`` / ``http_proxy`` environment variable,
or pass ``proxies`` dict to constructor.

Usage:
    source = CcxtSource(exchange_id="binance")
    source.connect()
    source.subscribe("BTC/USDT", "15m")
    bars = source.latest_snapshot(200)
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

from pa_agent.data.base import (
    DataSource,
    DataSourceTransientError,
    KlineBar,
    normalize_kline_bar,
)

logger = logging.getLogger(__name__)

_CCXT_TF_MAP: dict[str, str] = {
    "1m":  "1m",
    "3m":  "3m",
    "5m":  "5m",
    "15m": "15m",
    "30m": "30m",
    "1h":  "1h",
    "2h":  "2h",
    "4h":  "4h",
    "6h":  "6h",
    "8h":  "8h",
    "12h": "12h",
    "1d":  "1d",
    "3d":  "3d",
    "1w":  "1w",
    "1M":  "1M",
}

_CRYPTO_DEFAULT_SYMBOLS = [
    "BTC/USDT",
    "ETH/USDT",
    "BTC/USDC",
    "ETH/USDC",
    "SOL/USDT",
    "BNB/USDT",
    "XRP/USDT",
    "DOGE/USDT",
    "BTC/USD:USDT",
    "ETH/USD:USDT",
]


def _detect_proxy() -> dict[str, str] | None:
    for var in ("https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY", "all_proxy", "ALL_PROXY"):
        val = os.environ.get(var, "").strip()
        if val:
            return {"https": val, "http": val}
    return None


class CcxtSource(DataSource):
    def __init__(
        self,
        exchange_id: str = "binance",
        proxies: dict[str, str] | None = None,
    ) -> None:
        self._exchange_id = exchange_id
        self._proxies = proxies
        self._exchange: Any = None
        self._symbol: str = ""
        self._timeframe: str = ""
        self._connected: bool = False

    @property
    def exchange_id(self) -> str:
        return self._exchange_id

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def connect(self) -> None:
        try:
            import ccxt
        except ImportError as exc:
            raise DataSourceTransientError(
                "CCXT 未安装，请执行 pip install ccxt"
            ) from exc

        exchange_config: dict[str, Any] = {
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        }

        proxies = self._proxies or _detect_proxy()
        if proxies:
            exchange_config["proxies"] = proxies
            logger.info("CcxtSource using proxy: %s", proxies)

        try:
            exchange_class = getattr(ccxt, self._exchange_id)
            self._exchange = exchange_class(exchange_config)
            self._exchange.load_markets()
            self._connected = True
            logger.info(
                "CcxtSource connected: exchange=%s markets=%d proxy=%s",
                self._exchange_id,
                len(self._exchange.markets),
                bool(proxies),
            )
        except Exception as exc:
            self._connected = False
            msg = str(exc)
            if "timeout" in msg.lower() or "timed out" in msg.lower():
                hint = (
                    "。可在终端中设置代理后重试，例如:\n"
                    "  export https_proxy=http://127.0.0.1:7890\n"
                    "  export http_proxy=http://127.0.0.1:7890"
                )
                msg += hint
            raise DataSourceTransientError(
                f"CCXT 连接 {self._exchange_id} 失败：{msg}"
            ) from exc

    def disconnect(self) -> None:
        self._exchange = None
        self._connected = False
        logger.info("CcxtSource disconnected")

    # ── Discovery ─────────────────────────────────────────────────────────

    def list_symbols(self) -> list[str]:
        if self._exchange is None:
            return list(_CRYPTO_DEFAULT_SYMBOLS)
        try:
            markets = self._exchange.load_markets()
            return sorted([
                sym for sym, m in markets.items()
                if m.get("active") and m.get("spot")
                and sym.endswith("/USDT")
            ])
        except Exception as exc:
            logger.warning("CcxtSource list_symbols failed: %s", exc)
            return list(_CRYPTO_DEFAULT_SYMBOLS)

    def supported_timeframes(self) -> list[str]:
        if self._exchange is not None:
            try:
                return list(self._exchange.timeframes.keys())
            except Exception:
                pass
        return list(_CCXT_TF_MAP.keys())

    # ── Subscription ──────────────────────────────────────────────────────

    def subscribe(self, symbol: str, timeframe: str) -> None:
        if timeframe not in _CCXT_TF_MAP:
            raise ValueError(
                f"CCXT 不支持的周期: {timeframe!r}。"
                f"可用: {list(_CCXT_TF_MAP)}"
            )
        self._symbol = symbol.strip()
        self._timeframe = timeframe
        logger.info(
            "CcxtSource subscribed: %s %s exchange=%s",
            self._symbol,
            timeframe,
            self._exchange_id,
        )

    def unsubscribe(self) -> None:
        self._symbol = ""
        self._timeframe = ""
        logger.info("CcxtSource unsubscribed")

    # ── Data fetch ────────────────────────────────────────────────────────

    def latest_snapshot(self, n: int) -> list[KlineBar]:
        if self._exchange is None:
            raise DataSourceTransientError("CCXT 未连接，请先选择数据来源 CCXT")
        if not self._symbol or not self._timeframe:
            raise DataSourceTransientError("CCXT 未订阅品种/周期")

        try:
            ohlcv = self._exchange.fetch_ohlcv(
                self._symbol,
                _CCXT_TF_MAP[self._timeframe],
                limit=n + 1,
            )
        except Exception as exc:
            msg = str(exc)
            if "rate limit" in msg.lower() or "ddos" in msg.lower():
                raise DataSourceTransientError(
                    f"交易所频率限制 ({self._exchange_id})，请稍候几秒后重试"
                ) from exc
            raise DataSourceTransientError(
                f"CCXT {self._exchange_id} 获取 {self._symbol} "
                f"{self._timeframe} 数据失败：{exc}"
            ) from exc

        if not ohlcv:
            raise DataSourceTransientError(
                f"CCXT {self._exchange_id}:{self._symbol} "
                f"{self._timeframe} 返回空数据"
            )

        ohlcv_newest_first = list(reversed(ohlcv))

        bars: list[KlineBar] = []
        for i, candle in enumerate(ohlcv_newest_first):
            ts_ms, o, h, l, c, v = (
                int(candle[0]),
                float(candle[1]),
                float(candle[2]),
                float(candle[3]),
                float(candle[4]),
                float(candle[5]),
            )
            bar = KlineBar(
                seq=i + 1,
                ts_open=ts_ms,
                open=o,
                high=h,
                low=l,
                close=c,
                volume=v,
                closed=True,
            )
            if i == 0:
                from pa_agent.data.bar_close_wait import seconds_until_bar_closes

                secs_left = seconds_until_bar_closes(
                    ts_ms, self._timeframe, now_ms=None
                )
                still_forming = secs_left is not None and secs_left > 0
                bar = KlineBar(
                    seq=bar.seq,
                    ts_open=bar.ts_open,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=bar.volume,
                    closed=not still_forming,
                )
            bars.append(normalize_kline_bar(bar))
            if len(bars) >= n:
                break

        return bars

    def server_time_ms(self) -> int:
        if self._exchange is None:
            return 0
        try:
            ts = self._exchange.milliseconds()
            if ts is not None:
                return int(ts)
        except Exception:
            pass
        return 0
