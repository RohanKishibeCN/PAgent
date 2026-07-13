"""PA Agent Web Dashboard — FastAPI 服务，通过浏览器访问 VPS IP 即可使用。

用法:
    # 开发运行
    python3 web_server.py

    # 生产运行（推荐）
    python3 web_server.py --port 8080 --host 0.0.0.0

    # 浏览器访问
    http://VPS_IP:8080
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

_here = Path(__file__).resolve().parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

# =============================================================================
# PyQt6 依赖消除（与 run_headless.py 相同策略）
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

app = FastAPI(title="PA Agent Web Dashboard", version="1.0.0")
STATIC_DIR = _here / "web" / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ── 模板渲染（绕过 Jinja2>=3.1.2 缓存 bug）─────────────────────────────────
from jinja2 import Environment, FileSystemLoader as _FSL
_from_jinja_env = Environment(loader=_FSL(str(_here / "web" / "templates")), auto_reload=False)


def _render(name: str, context: dict) -> str:
    """Render an HTML template with Jinja2, bypassing broken TemplateResponse cache."""
    return _from_jinja_env.get_template(name).render(**context)


class _Templates:
    """Drop-in replacement for starlette.templating.Jinja2Templates."""

    def TemplateResponse(self, name: str, context: dict) -> HTMLResponse:
        from starlette.responses import HTMLResponse

        html = _render(name, context)
        return HTMLResponse(content=html, media_type="text/html")


templates = _Templates()


# ── API: 服务状态 ────────────────────────────────────────────────────────────

@app.get("/api/status")
def api_status():
    return {"status": "ok", "version": "1.0.0"}


# ── API: 交易对列表 ──────────────────────────────────────────────────────────

_KNOWN_SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT", "XRP/USDT",
    "BNB/USDT", "ADA/USDT", "AVAX/USDT", "DOT/USDT", "LINK/USDT",
    "SUI/USDT", "ARB/USDT", "OP/USDT", "MATIC/USDT", "ATOM/USDT",
    "LTC/USDT", "BCH/USDT", "FIL/USDT", "APT/USDT", "NEAR/USDT",
    "PEPE/USDT", "WIF/USDT", "INJ/USDT", "TIA/USDT",
]


@app.get("/api/markets")
def api_markets(exchange: str = "okx"):
    """Return known trading pairs for the symbol dropdown."""
    return {
        "symbols": _KNOWN_SYMBOLS,
        "timeframes": ["15m", "30m", "1h", "2h", "4h", "8h", "12h", "1d"],
    }


# ── API: 持久化分析记录 ──────────────────────────────────────────────────────

from datetime import datetime


def _save_web_record(result: dict) -> None:
    """Write a lightweight record to records/pending/ so it appears in history."""
    from pa_agent.config.paths import RECORDS_PENDING_DIR
    RECORDS_PENDING_DIR.mkdir(parents=True, exist_ok=True)

    ts_iso = datetime.now().isoformat()
    ts_ms = int(time.time() * 1000)
    symbol = result.get("symbol", "UNKNOWN")
    timeframe = result.get("timeframe", "?")
    fname = f"web_{ts_ms}_{symbol.replace('/','_')}_{timeframe}.json"
    path = RECORDS_PENDING_DIR / fname

    diagnosis = result.get("diagnosis") or {}
    decision_data = result.get("decision") or {}
    dec = decision_data.get("decision") if isinstance(decision_data.get("decision"), dict) else {}

    record = {
        "meta": {
            "timestamp_local_iso": ts_iso,
            "timestamp_local_ms": ts_ms,
            "symbol": symbol,
            "timeframe": timeframe,
            "bar_count": result.get("bar_count", 0),
            "ai_provider": {},
            "decision_stance": "balanced",
        },
        "kline_data": [],
        "htf_text": "",
        "stage1_messages": [],
        "stage1_response": None,
        "stage1_diagnosis": diagnosis,
        "stage2_messages": [],
        "stage2_response": None,
        "stage2_decision": decision_data,
        "strategy_files_used": [],
        "experience_loaded": [],
        "exception": {"category": "info", "debug_hint": "web_dashboard"} if result["status"] != "error" else {"category": "error", "debug_hint": result.get("error", "")},
        "usage_total": result.get("usage", {}),
        "web_status": result.get("status"),
        "order_type": dec.get("order_type"),
        "order_direction": dec.get("order_direction"),
        "entry_price": dec.get("entry_price"),
        "trade_confidence": dec.get("trade_confidence"),
    }
    try:
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


# ── API: 触发分析 ────────────────────────────────────────────────────────────

@app.post("/api/analyze")
async def api_analyze(
    exchange: str = Form("okx"),
    symbol: str = Form("BTC/USDT"),
    timeframe: str = Form("1h"),
    bar_count: int = Form(80),
    no_ai: bool = Form(False),
):
    """触发一次分析，异步执行，返回分析结果"""
    from pa_agent.data.base import (
        IndicatorBundle, KlineBar, KlineFrame, normalize_kline_bar,
    )
    from pa_agent.data.bar_close_wait import has_forming_bar_at_head
    from pa_agent.data.ccxt_source import CcxtSource
    from pa_agent.indicators.atr import atr_full
    from pa_agent.indicators.ema import ema_full

    # 统一用 `/` 格式
    symbol = symbol.strip().upper()
    if "/" not in symbol:
        symbol = symbol.replace("-", "/")
    bar_count = max(20, min(bar_count, 500))

    result: dict[str, Any] = {
        "exchange": exchange,
        "symbol": symbol,
        "timeframe": timeframe,
        "bar_count": bar_count,
        "status": "running",
        "error": None,
        "diagnosis": None,
        "decision": None,
        "kline_summary": None,
        "timestamp": int(time.time()),
    }

    try:
        source = CcxtSource(exchange_id=exchange)
        await asyncio.get_event_loop().run_in_executor(None, source.connect)
        await asyncio.get_event_loop().run_in_executor(
            None, source.subscribe, symbol, timeframe
        )
        bars = await asyncio.get_event_loop().run_in_executor(
            None, source.latest_snapshot, bar_count + 50
        )
        await asyncio.get_event_loop().run_in_executor(None, source.disconnect)
    except Exception as exc:
        result["status"] = "error"
        result["error"] = f"数据获取失败: {exc}"
        _save_web_record(result)
        return result

    # 构造 KlineFrame
    forming = has_forming_bar_at_head(bars, timeframe, symbol=symbol)
    closed_bars = bars[1:] if forming else bars[:]
    closed = closed_bars[:min(bar_count, len(closed_bars))]

    rebased = [
        normalize_kline_bar(
            KlineBar(seq=i + 1, ts_open=b.ts_open, open=b.open, high=b.high,
                     low=b.low, close=b.close, volume=b.volume, closed=True)
        )
        for i, b in enumerate(closed)
    ]
    bars_asc = list(reversed(rebased))
    ema20_asc = ema_full([b.close for b in bars_asc], 20)
    atr14_asc = atr_full(
        [b.high for b in bars_asc], [b.low for b in bars_asc],
        [b.close for b in bars_asc], 14,
    )
    frame = KlineFrame(
        symbol=symbol, timeframe=timeframe, bars=tuple(rebased),
        indicators=IndicatorBundle(
            ema20=tuple(reversed(ema20_asc)), atr14=tuple(reversed(atr14_asc)),
        ),
        snapshot_ts_local_ms=int(time.time() * 1000),
    )

    closes = [b.close for b in frame.bars]
    result["kline_summary"] = {
        "bar_count": len(rebased),
        "current_price": closes[0],
        "high_24h": max(closes),
        "low_24h": min(closes),
    }
    atr_vals = [x for x in frame.indicators.atr14 if x == x]
    if atr_vals:
        result["kline_summary"]["atr"] = round(atr_vals[0], 2)

    if no_ai:
        result["status"] = "data_only"
        _save_web_record(result)
        return result

    # ── 策略引擎 ────────────────────────────────────────────────────────
    from pa_agent.ai.decision_nodes import (
        check_preflight_data, judge_always_in, judge_direction,
        judge_market_chaos, judge_momentum_strength,
    )

    pf = check_preflight_data(frame)
    if not pf.ok:
        result["status"] = "preflight_failed"
        result["error"] = pf.reason
        _save_web_record(result)
        return result

    direction, f23 = judge_direction(frame)
    f24 = judge_always_in(frame)
    f25 = judge_momentum_strength(frame, direction)
    f13 = judge_market_chaos(frame)

    result["diagnosis"] = {
        "direction": direction,
        "gate_23": {"answer": f23.answer, "branch": f23.branch},
        "gate_24": {"answer": f24.answer, "branch": f24.branch},
        "gate_25": {"answer": f25.answer, "branch": f25.branch},
        "chaos": f13.answer == "是",
    }

    # ── AI 分析（如果配置了 API Key）──
    from pa_agent.config.paths import SETTINGS_JSON_PATH
    from pa_agent.config.settings import load_settings

    settings = load_settings(SETTINGS_JSON_PATH)
    if not (settings.provider.api_key or "").strip():
        result["status"] = "no_ai_key"
        _save_web_record(result)
        return result

    from pa_agent.ai.client_factory import create_ai_client
    from pa_agent.ai.json_validator import JsonValidator
    from pa_agent.ai.prompt_assembler import PromptAssembler
    from pa_agent.ai.router import route_strategy_files
    from pa_agent.config.paths import EXPERIENCE_DIR, PROMPT_DIR, RECORDS_PENDING_DIR
    from pa_agent.orchestrator.two_stage import TwoStageOrchestrator
    from pa_agent.records.experience_reader import ExperienceReader
    from pa_agent.util.threading import CancelToken

    RECORDS_PENDING_DIR.mkdir(parents=True, exist_ok=True)

    exp_reader = ExperienceReader(experience_dir=EXPERIENCE_DIR)
    assembler = PromptAssembler(
        prompt_dir=PROMPT_DIR, experience_reader=exp_reader,
        prompt_settings=settings.prompt,
    )
    client = create_ai_client(settings.provider)
    validator = JsonValidator(settings)
    pending_writer = __import__("pa_agent.records.pending_writer", fromlist=["PendingWriter"]).PendingWriter(
        pending_dir=RECORDS_PENDING_DIR, event_bus=None, api_key=settings.provider.api_key,
    )

    orch = TwoStageOrchestrator(
        client=client, assembler=assembler, router=route_strategy_files,
        validator=validator, pending_writer=pending_writer,
        exp_reader=exp_reader, settings=settings,
    )

    record = await asyncio.get_event_loop().run_in_executor(
        None, lambda: orch.submit(frame, CancelToken(), lambda _: None)
    )

    result["diagnosis"] = record.stage1_diagnosis
    result["decision"] = record.stage2_decision
    result["usage"] = record.usage_total
    result["status"] = "success"

    _save_web_record(result)
    return result


# ── API: 历史结果列表 ──────────────────────────────────────────────────────

@app.get("/api/results")
def api_results():
    from pa_agent.config.paths import RECORDS_PENDING_DIR

    RECORDS_PENDING_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(RECORDS_PENDING_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    items = []
    for f in files[:50]:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            meta = data.get("meta", {})
            s1 = data.get("stage1_diagnosis") or {}
            s2 = data.get("stage2_decision") or {}
            items.append({
                "filename": f.name,
                "time": meta.get("timestamp_local_iso", ""),
                "symbol": meta.get("symbol", ""),
                "timeframe": meta.get("timeframe", ""),
                "direction": s1.get("direction", "?"),
                "order_type": s2.get("decision", {}).get("order_type", "?") if isinstance(s2.get("decision"), dict) else "?",
                "confidence": s2.get("decision", {}).get("trade_confidence", "?") if isinstance(s2.get("decision"), dict) else "?",
                "error": data.get("exception"),
            })
        except Exception:
            pass
    return {"items": items, "total": len(files)}


# ── API: 统计汇总 ────────────────────────────────────────────────────────────

@app.get("/api/stats")
def api_stats():
    """Return summary statistics across all analysis records."""
    from pa_agent.config.paths import RECORDS_PENDING_DIR
    RECORDS_PENDING_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(RECORDS_PENDING_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)

    total = 0
    with_ai = 0
    with_order = 0
    no_order = 0
    errors = 0
    confidences: list[int] = []
    directions: dict[str, int] = {}
    order_types: dict[str, int] = {}
    symbols: dict[str, int] = {}
    last_10_directions: list[str] = []

    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            total += 1
            meta = data.get("meta", {})
            s1 = data.get("stage1_diagnosis") or {}
            s2 = data.get("stage2_decision") or {}
            dec = s2.get("decision") if isinstance(s2.get("decision"), dict) else {}

            sym = meta.get("symbol", "?")
            symbols[sym] = symbols.get(sym, 0) + 1

            dir_val = s1.get("direction", "?")
            directions[dir_val] = directions.get(dir_val, 0) + 1

            if data.get("exception") and data["exception"].get("category") == "error":
                errors += 1

            ot = dec.get("order_type", "")
            if ot and ot != "不下单":
                with_order += 1
                order_types[ot] = order_types.get(ot, 0) + 1
            else:
                no_order += 1

            conf = dec.get("trade_confidence")
            if isinstance(conf, (int, float)) and conf > 0:
                confidences.append(int(conf))

            if data.get("usage_total", {}).get("total_tokens", 0) > 0:
                with_ai += 1

            if len(last_10_directions) < 10:
                last_10_directions.append(dir_val)
        except Exception:
            total += 1
            errors += 1

    avg_confidence = round(sum(confidences) / len(confidences), 1) if confidences else 0
    return {
        "total": total,
        "with_ai": with_ai,
        "with_order": with_order,
        "no_order": no_order,
        "errors": errors,
        "avg_confidence": avg_confidence,
        "max_confidence": max(confidences) if confidences else 0,
        "direction_distribution": dict(sorted(directions.items(), key=lambda x: -x[1])),
        "order_type_distribution": dict(sorted(order_types.items(), key=lambda x: -x[1])),
        "symbols": dict(sorted(symbols.items(), key=lambda x: -x[1])),
        "last_10_directions": last_10_directions,
    }


@app.get("/api/results/{filename}")
def api_result_detail(filename: str):
    from pa_agent.config.paths import RECORDS_PENDING_DIR

    fpath = RECORDS_PENDING_DIR / filename
    if not fpath.exists():
        return JSONResponse({"error": "not found"}, status_code=404)
    data = json.loads(fpath.read_text(encoding="utf-8"))
    return data


# ── API: 配置 ────────────────────────────────────────────────────────────────

def _mask_secret(val: str) -> str:
    """Mask all but last 4 chars of a secret, or return empty if blank."""
    if not val or len(val) < 4:
        return "****" if val else ""
    return "*" * (len(val) - 4) + val[-4:]


@app.get("/api/settings")
def api_settings():
    from pa_agent.config.paths import SETTINGS_JSON_PATH
    from pa_agent.config.settings import load_settings

    s = load_settings(SETTINGS_JSON_PATH)
    return {
        "provider": {
            "model": s.provider.model,
            "base_url": s.provider.base_url,
            "api_key_configured": bool(s.provider.api_key),
            "api_key_masked": _mask_secret(s.provider.api_key) if s.provider.api_key else "",
            "thinking": s.provider.thinking,
            "reasoning_effort": s.provider.reasoning_effort,
            "context_window": s.provider.context_window,
        },
        "general": {
            "last_data_source": s.general.last_data_source,
            "last_ccxt_exchange": s.general.last_ccxt_exchange,
            "last_symbol": s.general.last_symbol,
            "last_timeframe": s.general.last_timeframe,
            "analysis_bar_count": s.general.analysis_bar_count,
            "decision_stance": s.general.decision_stance,
            "decision_confidence_threshold": s.general.decision_confidence_threshold,
            "keep_analysis": s.general.keep_analysis,
            "enable_next_bar_prediction": s.general.enable_next_bar_prediction,
        },
        "validation": {
            "normalization_mode": s.validation.normalization_mode,
            "retry_enabled": s.validation.retry_enabled,
            "retry_max": s.validation.retry_max,
        },
        "feishu": {
            "enabled": s.feishu.enabled,
            "webhook_url": s.feishu.webhook_url,
            "notify_on_order_only": s.feishu.notify_on_order_only,
            "app_id_masked": _mask_secret(s.feishu.app_id) if s.feishu.app_id else "",
            "chat_id": s.feishu.chat_id,
            "app_mode": bool(s.feishu.app_id and s.feishu.app_secret and s.feishu.chat_id),
        },
        "exchange_api": {
            "api_key_masked": _mask_secret(s.exchange_api.api_key),
            "secret_masked": _mask_secret(s.exchange_api.secret),
            "password_masked": _mask_secret(s.exchange_api.password),
            "configured": bool(s.exchange_api.api_key and s.exchange_api.secret),
        },
        "trading": {
            "auto_trade_enabled": s.trading.auto_trade_enabled,
            "trade_amount": s.trading.trade_amount,
            "max_risk_per_trade_pct": s.trading.max_risk_per_trade_pct,
            "min_confidence": s.trading.min_confidence,
            "quote_currency": s.trading.quote_currency,
        },
    }


@app.post("/api/settings")
def api_update_settings(body: dict):
    """Update arbitrary settings fields. Only sends non-None values.

    Example:
      {"general": {"last_ccxt_exchange": "okx", "last_symbol": "ETH/USDT"}, ...}
    """
    from pa_agent.config.paths import SETTINGS_JSON_PATH
    from pa_agent.config.settings import load_settings, save_settings, Settings

    s = load_settings(SETTINGS_JSON_PATH)

    def _merge(target: object, updates: dict) -> None:
        for key, val in updates.items():
            if val is not None and hasattr(target, key):
                setattr(target, key, val)

    for section, fields in body.items():
        if not isinstance(fields, dict):
            continue
        section_obj = getattr(s, section, None)
        if section_obj is not None:
            _merge(section_obj, fields)

    save_settings(s, SETTINGS_JSON_PATH)
    return {"ok": True}


@app.post("/api/settings/exchange")
def api_set_exchange(exchange: str = Form(...)):
    from pa_agent.config.paths import SETTINGS_JSON_PATH
    from pa_agent.config.settings import load_settings, save_settings

    s = load_settings(SETTINGS_JSON_PATH)
    s.general.last_ccxt_exchange = exchange
    s.general.last_data_source = "ccxt"
    save_settings(s, SETTINGS_JSON_PATH)
    return {"ok": True, "exchange": exchange}


@app.post("/api/settings/test-exchange")
async def api_test_exchange(body: dict):
    """Test exchange API connection with given credentials.

    If credentials are omitted, uses saved settings.
    Returns True/False + message.
    """
    from pa_agent.config.paths import SETTINGS_JSON_PATH
    from pa_agent.config.settings import load_settings

    s = load_settings(SETTINGS_JSON_PATH)
    ex_id = body.get("exchange") or s.general.last_ccxt_exchange or "okx"

    try:
        import ccxt
    except ImportError:
        return {"ok": False, "message": "CCXT 未安装"}

    try:
        ex_class = getattr(ccxt, ex_id)
        ex = ex_class()
        markets = await asyncio.get_event_loop().run_in_executor(None, ex.load_markets)
        return {
            "ok": True,
            "message": f"✅ {ex_id} 连接成功, {len(markets)} 个交易对可用",
            "market_count": len(markets),
        }
    except Exception as e:
        return {"ok": False, "message": f"❌ {ex_id} 连接失败: {e}"}


@app.post("/api/settings/test-exchange-auth")
async def api_test_exchange_auth(body: dict):
    """Test exchange API with authentication (real money connection test).

    ⚠️ 不会下单，只做连接和余额查询。
    """
    api_key = body.get("api_key", "")
    secret = body.get("secret", "")
    password = body.get("password", "")
    exchange_id = body.get("exchange", "")

    if not api_key or not secret:
        return {"ok": False, "message": "API Key 和 Secret 不能为空"}

    try:
        import ccxt
    except ImportError:
        return {"ok": False, "message": "CCXT 未安装"}

    try:
        ex_class = getattr(ccxt, exchange_id)
        kwargs = {"apiKey": api_key, "secret": secret}
        if password:
            kwargs["password"] = password
        ex = ex_class(kwargs)

        balance = await asyncio.get_event_loop().run_in_executor(
            None, ex.fetch_balance
        )
        total_usdt = balance.get("USDT", {}).get("total", 0)
        total_btc = balance.get("BTC", {}).get("total", 0)

        return {
            "ok": True,
            "message": f"✅ {exchange_id} 认证成功",
            "balance": {
                "USDT": round(total_usdt, 2) if total_usdt else 0,
                "BTC": round(total_btc, 6) if total_btc else 0,
            },
        }
    except Exception as e:
        return {"ok": False, "message": f"❌ 认证失败: {e}"}


# ── API: 飞书推送测试 ─────────────────────────────────────────────────────────

@app.post("/api/feishu/test")
async def api_feishu_test():
    """发送测试消息到飞书群，配置从已保存的 settings.json 读取."""
    try:
        from pa_agent.config.paths import SETTINGS_JSON_PATH
        from pa_agent.config.settings import load_settings

        s = load_settings(SETTINGS_JSON_PATH)
        from pa_agent.notify.feishu_notifier import send_text_to_group

        text = (
            f"🧪 PA Agent 飞书推送测试\n"
            f"时间: {datetime.now().isoformat()}\n"
            f"状态: 连接测试成功 ✅\n"
            f"这是来自 VPS 的测试消息，后续分析结果将通过此通道推送。"
        )
        ok = send_text_to_group(text, s)
        return {"ok": ok, "message": "发送成功 ✅" if ok else "发送失败，请检查 App ID/Secret/群 ID 配置"}
    except Exception as exc:
        return {"ok": False, "message": f"服务器错误: {exc}"}


# ── Web 页面 ────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/results", response_class=HTMLResponse)
def results_page(request: Request):
    return templates.TemplateResponse("results.html", {"request": request})


@app.get("/stats", response_class=HTMLResponse)
def stats_page(request: Request):
    return templates.TemplateResponse("stats.html", {"request": request})


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    return templates.TemplateResponse("settings.html", {"request": request})


# ── 启动 ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="PA Agent Web Dashboard")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址 (默认 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="监听端口 (默认 8080)")
    args = parser.parse_args()

    print(f"\n  PA Agent Web Dashboard")
    print(f"  {'='*40}")
    print(f"  本地:   http://127.0.0.1:{args.port}")
    print(f"  网络:   http://{args.host}:{args.port}")
    print(f"  按 Ctrl+C 停止\n")

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
