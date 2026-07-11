"""PA Agent 无头分析模式 — 适合 VPS / cron 定时任务 / CI。

直接运行两阶段分析流水线，不需要 PyQt6 GUI。
输出分析报告到 stdout 并持久化到 records/pending/。

用法:
    # 默认使用 settings.json 中的交易所和标的
    python3 run_headless.py

    # 指定交易所和标的
    python3 run_headless.py --exchange okx --symbol BTC/USDT --timeframe 1h

    # 仅数据获取检查（不调用 AI）
    python3 run_headless.py --exchange binance --symbol ETH/USDT --timeframe 15m --no-ai

    # Docker / systemd 定时任务
    python3 run_headless.py --exchange okx --symbol BTC/USDT --timeframe 4h
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

_here = Path(__file__).resolve().parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

# =============================================================================
# PyQt6 依赖消除 — 必须在任何 pa_agent 导入前执行
# pa_agent/util/__init__.py 在模块级别 import event_bus (→ PyQt6.QtCore)
# =============================================================================
_stub_eb = type(sys)("pa_agent.util.event_bus")

class _StubEventBus:
    def emit(self, *_a: object, **_kw: object) -> None:
        pass

    def __getattr__(self, _name: str) -> object:
        return self.emit  # any signal = no-op

_stub_eb.EventBus = _StubEventBus
sys.modules["pa_agent.util.event_bus"] = _stub_eb

_stub_cd = type(sys)("pa_agent.util.crash_diagnostics")
_stub_cd.enable_crash_diagnostics = lambda: None
_stub_cd.log_startup_diagnostics = lambda: None
sys.modules["pa_agent.util.crash_diagnostics"] = _stub_cd

for _mod_name in (
    "pa_agent.gui",
    "pa_agent.gui.theme",
    "pa_agent.gui.widgets",
    "pa_agent.gui.main_window",
    "pa_agent.gui.chart_widget",
    "pa_agent.gui.conversation_widget",
    "pa_agent.gui.decision_panel",
    "pa_agent.gui.ai_sidebar",
    "pa_agent.gui.settings_dialog",
    "pa_agent.gui.feishu_settings_dialog",
    "pa_agent.gui.general_settings_dialog",
    "pa_agent.gui.ai_model_settings_dialog",
    "pa_agent.gui.order_opportunity",
    "pa_agent.notify",
):
    sys.modules[_mod_name] = type(sys)(_mod_name)


class _NoopPendingWriter:
    """PendingWriter 的无操作替身 — TwoStageOrchestrator 需要写入器但可以跳过。"""

    def save_full(self, _record: object) -> None:
        pass

    def save_partial(self, _record: object, _reason: str) -> None:
        pass

    def append_followup(self, *_a: object, **_kw: object) -> None:
        pass


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="PA Agent 无头分析模式（VPS / cron 友好）")
    p.add_argument(
        "--exchange", "-e", default=None,
        help="CCXT 交易所 id（binance / okx / bybit / bitget 等），默认读取 settings.json",
    )
    p.add_argument(
        "--symbol", "-s", default=None,
        help="交易对（如 BTC/USDT），默认读取 settings.json",
    )
    p.add_argument(
        "--timeframe", "-t", default=None,
        help="K 线周期（如 15m / 1h / 4h / 1d），默认读取 settings.json",
    )
    p.add_argument("--no-ai", action="store_true", help="只获取 K 线数据并打印摘要，不调用 AI 分析")
    p.add_argument(
        "--bar-count", "-n", type=int, default=None,
        help="分析用 K 线数量，默认读取 settings.json",
    )
    return p.parse_args()


def _load_settings():
    from pa_agent.config.paths import SETTINGS_JSON_PATH
    from pa_agent.config.settings import load_settings

    return load_settings(SETTINGS_JSON_PATH)


def main() -> int:
    args = _parse_args()
    settings = _load_settings()

    exchange_id = (
        args.exchange
        or getattr(settings.general, "last_ccxt_exchange", "binance")
        or "binance"
    )
    symbol = args.symbol or settings.general.last_symbol or "BTC/USDT"
    timeframe = args.timeframe or settings.general.last_timeframe or "15m"
    bar_count = args.bar_count or getattr(settings.general, "analysis_bar_count", 100)
    bar_count = max(20, min(bar_count, 5000))  # safety clamp

    print(f"交易所: {exchange_id}")
    print(f"交易对: {symbol}")
    print(f"周  期: {timeframe}")
    print(f"K 线数: {bar_count}")
    print()

    # ── 步骤 1：数据获取 ────────────────────────────────────────────────
    print("[1/4] 连接数据源 ...")
    from pa_agent.data.ccxt_source import CcxtSource

    source = CcxtSource(exchange_id=exchange_id)
    try:
        source.connect()
        source.subscribe(symbol, timeframe)
        bars = source.latest_snapshot(bar_count + 50)
    except Exception as exc:
        print(f"错误: 数据获取失败 — {exc}", file=sys.stderr)
        return 1
    finally:
        source.disconnect()

    print(f"    获取到 {len(bars)} 根 K 线")

    # ── 步骤 2：构造 KlineFrame ──────────────────────────────────────────
    print("[2/4] 构造分析帧 ...")
    from pa_agent.data.base import (
        IndicatorBundle, KlineBar, KlineFrame, normalize_kline_bar,
    )
    from pa_agent.data.bar_close_wait import has_forming_bar_at_head
    from pa_agent.indicators.atr import atr_full
    from pa_agent.indicators.ema import ema_full

    forming = has_forming_bar_at_head(bars, timeframe, symbol=symbol)
    closed_bars = bars[1:] if forming else bars[:]
    if len(closed_bars) < bar_count:
        print(
            f"错误: 已收盘 K 线不足 {bar_count} 根（只有 {len(closed_bars)} 根）",
            file=sys.stderr,
        )
        return 1
    closed = closed_bars[:bar_count]

    rebased = [
        normalize_kline_bar(
            KlineBar(
                seq=i + 1, ts_open=b.ts_open, open=b.open, high=b.high,
                low=b.low, close=b.close, volume=b.volume, closed=True,
            )
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
        symbol=symbol,
        timeframe=timeframe,
        bars=tuple(rebased),
        indicators=IndicatorBundle(
            ema20=tuple(reversed(ema20_asc)),
            atr14=tuple(reversed(atr14_asc)),
        ),
        snapshot_ts_local_ms=int(time.time() * 1000),
    )

    latest = frame.bars[0]
    oldest = frame.bars[-1]
    print(
        f"    最新 K: #{latest.seq} O={latest.open:.2f} H={latest.high:.2f} "
        f"L={latest.low:.2f} C={latest.close:.2f}"
    )
    print(f"    最早 K: #{oldest.seq} O={oldest.open:.2f} C={oldest.close:.2f}")
    atr_vals = [x for x in frame.indicators.atr14 if x == x]
    if atr_vals:
        print(f"    ATR14: {atr_vals[0]:.2f}")
    print()

    if args.no_ai:
        _print_data_summary(frame)
        return 0

    # ── 步骤 3：策略引擎 ────────────────────────────────────────────────
    print("[3/4] 运行策略引擎 ...")
    from pa_agent.ai.decision_nodes import (
        check_preflight_data, judge_always_in, judge_direction,
        judge_market_chaos, judge_momentum_strength,
    )

    pf = check_preflight_data(frame)
    if not pf.ok:
        print(f"    数据闸门未通过: {pf.reason}")
        return 0

    direction, f23 = judge_direction(frame)
    f24 = judge_always_in(frame)
    f25 = judge_momentum_strength(frame, direction)
    f13 = judge_market_chaos(frame)

    print(f"    方向判断 : {direction}  (§2.3 = {f23.answer} {f23.branch or ''})")
    print(f"    AlwaysIn : {f24.answer}  ({f24.branch or '无'})")
    print(f"    动量强度 : {f25.answer}  ({f25.branch or '无'})")
    print(f"    市场混沌 : {f13.answer}  (极度混乱={f13.answer == '是'})")
    print()

    # ── 步骤 4：AI 分析 ─────────────────────────────────────────────────
    print("[4/4] 调用 AI 分析 ...")
    if not (settings.provider.api_key or "").strip():
        print(
            "警告: 未配置 API Key。请编辑 config/settings.json 添加 "
            "provider.api_key，或在程序中设置。"
        )
        print("策略引擎结果已输出，跳过 AI 调用。")
        return 0

    from pa_agent.ai.client_factory import create_ai_client
    from pa_agent.ai.json_validator import JsonValidator
    from pa_agent.ai.prompt_assembler import PromptAssembler
    from pa_agent.ai.router import route_strategy_files
    from pa_agent.config.paths import EXPERIENCE_DIR, PROMPT_DIR
    from pa_agent.orchestrator.two_stage import TwoStageOrchestrator
    from pa_agent.records.experience_reader import ExperienceReader
    from pa_agent.util.threading import CancelToken

    exp_reader = ExperienceReader(experience_dir=EXPERIENCE_DIR)  # type: ignore[arg-type]
    assembler = PromptAssembler(
        prompt_dir=PROMPT_DIR,
        experience_reader=exp_reader,
        prompt_settings=settings.prompt,
    )
    client = create_ai_client(settings.provider)
    validator = JsonValidator(settings)

    orch = TwoStageOrchestrator(
        client=client,
        assembler=assembler,
        router=route_strategy_files,
        validator=validator,
        pending_writer=_NoopPendingWriter(),
        exp_reader=exp_reader,
        settings=settings,
    )

    def _on_event(_evt: object) -> None:
        pass

    record = orch.submit(frame, CancelToken(), _on_event)

    print(f"    Stage 1: {'成功' if record.stage1_diagnosis else '失败'}")
    print(f"    Stage 2: {'成功' if record.stage2_decision else '失败'}")
    if record.stage1_diagnosis:
        d = record.stage1_diagnosis
        print(f"    gate_result: {d.get('gate_result', '?')}")
        print(f"    cycle_position: {d.get('cycle_position', '?')}")
        print(f"    direction: {d.get('direction', '?')}")
    if record.stage2_decision:
        d2 = record.stage2_decision
        dec = d2.get("decision", {})
        if isinstance(dec, dict):
            print(f"    order_type: {dec.get('order_type', '?')}")
            print(f"    trade_confidence: {dec.get('trade_confidence', '?')}")
    if record.usage_total:
        u = record.usage_total
        print(
            f"    tokens: prompt={u.get('prompt_tokens', 0)} "
            f"completion={u.get('completion_tokens', 0)} "
            f"total={u.get('total_tokens', 0)}"
        )
    print()

    # ── 持久化 ──────────────────────────────────────────────────────────
    from pa_agent.config.paths import RECORDS_PENDING_DIR

    RECORDS_PENDING_DIR.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    fname = f"headless_{ts}_{symbol.replace('/', '_')}_{timeframe}.json"
    fpath = RECORDS_PENDING_DIR / fname
    try:
        fpath.write_text(
            record.model_dump_json(indent=2, exclude_none=False),
            encoding="utf-8",
        )
        print(f"报告已保存: {fpath}")
    except Exception as exc:
        print(f"警告: 保存报告失败 — {exc}", file=sys.stderr)

    return 0


def _print_data_summary(frame: "KlineFrame") -> None:
    bars = frame.bars
    closes = [b.close for b in bars]
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    volumes = [b.volume for b in bars]

    print("── K 线摘要 ──")
    print(f"  K 线数  : {len(bars)}")
    print(f"  开盘    : {bars[0].open:.2f}")
    print(f"  最新收盘: {closes[0]:.2f}")
    print(f"  最高    : {max(highs):.2f}")
    print(f"  最低    : {min(lows):.2f}")
    if closes[-1] != 0:
        print(f"  涨跌幅  : {(closes[0] / closes[-1] - 1) * 100:+.2f}%")
    print(f"  平均成交量: {sum(volumes) / max(len(volumes), 1):.0f}")
    ema = [e for e in frame.indicators.ema20 if e == e]
    if ema:
        loc = "上方" if closes[0] > ema[0] else "下方"
        print(f"  价格 vs EMA20: {loc} ({closes[0]:.2f} vs {ema[0]:.2f})")


if __name__ == "__main__":
    raise SystemExit(main())
