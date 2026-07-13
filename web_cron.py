"""PA Agent Web Cron — 通过 HTTP API 触发分析，适合 crontab / systemd timer。

通过 POST 请求本地 web_server 的 /api/analyze 接口触发完整分析流水线，
分析结果会自动触发飞书通知（如果配置了飞书）。

用法:
    # 默认参数
    python3 web_cron.py

    # 指定交易对和周期
    python3 web_cron.py --exchange okx --symbol BTC/USDT --timeframe 1h

    # 指定 K 线数量
    python3 web_cron.py --exchange okx --symbol ETH/USDT --timeframe 15m --bar-count 150

    # 自定义服务地址
    python3 web_cron.py --host 127.0.0.1 --port 8080

    # 仅获取数据（不调用 AI）
    python3 web_cron.py --no-ai

    # crontab 示例（每小时运行一次）
    # 0 * * * * cd /path/to/PAgent && /usr/bin/python3 web_cron.py --exchange okx --symbol BTC/USDT --timeframe 1h >> /var/log/pa-cron.log 2>&1
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import requests

_here = Path(__file__).resolve().parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

# =============================================================================
# PyQt6 依赖消除（与 web_server.py / run_headless.py 相同策略）
# =============================================================================
_stub_eb = type(sys)("pa_agent.util.event_bus")


class _StubEventBus:
    def emit(self, *_a: object, **_kw: object) -> None:
        pass

    def __getattr__(self, _name: str) -> object:
        return self.emit


_stub_eb.EventBus = _StubEventBus
sys.modules["pa_agent.util.event_bus"] = _stub_eb

_stub_cd = type(sys)("pa_agent.util.crash_diagnostics")
_stub_cd.enable_crash_diagnostics = lambda: None
_stub_cd.log_startup_diagnostics = lambda: None
sys.modules["pa_agent.util.crash_diagnostics"] = _stub_cd

for _mod_name in (
    "pa_agent.gui", "pa_agent.gui.theme", "pa_agent.gui.widgets",
    "pa_agent.gui.main_window", "pa_agent.gui.chart_widget",
    "pa_agent.gui.conversation_widget", "pa_agent.gui.decision_panel",
    "pa_agent.gui.ai_sidebar", "pa_agent.gui.settings_dialog",
    "pa_agent.gui.feishu_settings_dialog", "pa_agent.gui.general_settings_dialog",
    "pa_agent.gui.ai_model_settings_dialog", "pa_agent.gui.order_opportunity",
):
    sys.modules[_mod_name] = type(sys)(_mod_name)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="PA Agent Web Cron — 通过 HTTP API 触发分析（适合 crontab）",
    )
    p.add_argument("--host", default="127.0.0.1", help="web_server 地址 (默认 127.0.0.1)")
    p.add_argument("--port", type=int, default=8080, help="web_server 端口 (默认 8080)")
    p.add_argument(
        "--exchange", "-e", default="okx",
        help="CCXT 交易所 id（binance / okx / bybit 等）",
    )
    p.add_argument(
        "--symbol", "-s", default="BTC/USDT",
        help="交易对（如 BTC/USDT）",
    )
    p.add_argument(
        "--timeframe", "-t", default="1h",
        help="K 线周期（如 15m / 1h / 4h / 1d）",
    )
    p.add_argument(
        "--bar-count", "-n", type=int, default=80,
        help="分析用 K 线数量（20-500）",
    )
    p.add_argument(
        "--no-ai", action="store_true",
        help="只获取 K 线数据并打印摘要，不调用 AI 分析",
    )
    return p.parse_args()


def _print_result(result: dict) -> None:
    status = result.get("status", "?")
    symbol = result.get("symbol", "?")
    timeframe = result.get("timeframe", "?")
    error = result.get("error")

    print(f"状态  : {status}")
    print(f"交易对 : {symbol}")
    print(f"周期  : {timeframe}")

    if error:
        print(f"错误  : {error}")
        return

    ks = result.get("kline_summary") or {}
    if ks:
        print(f"价格  : {ks.get('current_price', '?')}")
        print(f"K 线数: {ks.get('bar_count', '?')}")
        if ks.get("atr"):
            print(f"ATR14 : {ks['atr']}")

    diagnosis = result.get("diagnosis") or {}
    if diagnosis:
        direction = diagnosis.get("direction", "?")
        print(f"方向  : {direction}")
        chaos = diagnosis.get("chaos")
        if chaos is not None:
            print(f"混沌  : {'是' if chaos else '否'}")

    decision_data = result.get("decision") or {}
    if decision_data:
        dec = decision_data.get("decision")
        if isinstance(dec, dict):
            ot = dec.get("order_type", "—")
            print(f"下单  : {ot}")
            if ot not in ("—", "不下单", ""):
                conf = dec.get("trade_confidence")
                if conf is not None:
                    print(f"置信度: {conf}%")

    usage = result.get("usage") or {}
    if usage.get("total_tokens"):
        print(f"Token : {usage['total_tokens']}")


def main() -> int:
    args = _parse_args()

    url = f"http://{args.host}:{args.port}/api/analyze"
    data = {
        "exchange": args.exchange,
        "symbol": args.symbol,
        "timeframe": args.timeframe,
        "bar_count": args.bar_count,
        "no_ai": args.no_ai,
    }

    print(f"请求 URL : {url}")
    print(f"参数     : exchange={args.exchange} symbol={args.symbol} "
          f"timeframe={args.timeframe} bar_count={args.bar_count} "
          f"no_ai={args.no_ai}")
    print()

    t0 = time.time()
    try:
        resp = requests.post(url, data=data, timeout=300)
    except requests.ConnectionError:
        print(f"错误: 无法连接到 {url}，请确保 web_server 已启动", file=sys.stderr)
        return 1
    except requests.Timeout:
        print("错误: 请求超时（300s）", file=sys.stderr)
        return 1
    except requests.RequestException as exc:
        print(f"错误: 请求失败 — {exc}", file=sys.stderr)
        return 1

    elapsed = time.time() - t0
    print(f"耗时: {elapsed:.1f}s")
    print()

    if resp.status_code != 200:
        print(f"错误: HTTP {resp.status_code}", file=sys.stderr)
        try:
            print(resp.text, file=sys.stderr)
        except Exception:
            pass
        return 1

    try:
        result = resp.json()
    except json.JSONDecodeError as exc:
        print(f"错误: 响应解析失败 — {exc}", file=sys.stderr)
        return 1

    print("── 分析结果 ──")
    _print_result(result)

    print()
    if result.get("status") == "success":
        print("✅ 分析完成，飞书通知已发送（如果已配置）")
    elif result.get("status") == "data_only":
        print("ℹ️  数据获取完成（--no-ai 模式，未调用 AI）")
    elif result.get("status") == "preflight_failed":
        print(f"⚠️  数据闸门未通过: {result.get('error', '未知')}")
    elif result.get("status") == "no_ai_key":
        print("⚠️  未配置 API Key，仅输出策略引擎结果")
    elif result.get("status") == "error":
        print(f"❌ 分析失败: {result.get('error', '未知')}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
