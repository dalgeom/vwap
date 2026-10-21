"""그림자 조종사 v1 — flip 다이얼(H-14) 관측. 결정·그림자 손익을 기록만 한다.

실돈 거래는 절대 바꾸지 않는다. 승격(실권 이양)은 H-14 게이트(분기 30건 또는 4주) 후
사장님 판정으로만 — 설계: docs/superpowers/specs/2026-10-21-regime-adaptive-bot-design.md.
기록: <모드 데이터>/shadow_pilot.jsonl, 하루 한 줄(같은 day 재실행은 기존 줄 반환).
그림자 손익 규약: 판단이 실제와 같으면 그림자=실제(체결 포함 실손익), 다르면 공용
시뮬 엔진으로 가상 반대방향을 계산(수수료 미반영 — 분기 비교 전용)."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.regime_engine import (_append_jsonl, _load_jsonl, _load_trades,
                               is_dial_event, update_dial)

KST = timezone(timedelta(hours=9))


def decide(dial):
    """다이얼 > 0 → 뒤집기 유지(ON), <= 0 → 중단(OFF), None → 보류(현상 유지)."""
    if dial is None:
        return None
    return "ON" if dial > 0 else "OFF"


def _closed_on(trades: list, day: str) -> list:
    out = []
    for t in trades:
        ts = t.get("exit_timestamp_utc")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                continue        # tz 없는 기록은 날짜 귀속이 불확실 — 제외
            if dt.astimezone(KST).date().isoformat() == day:
                out.append(t)
        except (ValueError, TypeError):
            continue
    return out


def run_pilot(root: Path, day: str, demo: bool, now_utc=None,
              cli=None, fetch=None, sim=None) -> dict:
    """day(KST)에 청산된 사건 거래를 그림자 판단과 대조해 기록한다.

    같은 day가 이미 기록돼 있으면 그 줄을 그대로 반환(재생성 중복 방지)."""
    from vwap_trader.mode_paths import data_dir
    from app.trade_sim import fetch_bars, sim_pct
    fetch = fetch or fetch_bars
    sim = sim or sim_pct
    dd = data_dir(root, demo)
    log_p = dd / "shadow_pilot.jsonl"
    prev = _load_jsonl(log_p)
    done = next((r for r in reversed(prev) if r.get("day") == day), None)
    if done is not None:
        return done

    state = update_dial(root, demo, now_utc=now_utc, cli=cli, fetch=fetch, sim=sim)
    decision = decide(state.get("dial"))

    if cli is None and fetch is fetch_bars:
        from pybit.unified_trading import HTTP
        cli = HTTP(testnet=False)

    divergent = []
    day_actual = day_shadow = 0.0
    for t in _closed_on(_load_trades(root, demo), day):
        if not is_dial_event(t):
            continue
        try:
            actual = float(t.get("pnl_usd") or 0.0)
            day_actual += actual
            shadow = actual                    # 기본: 그림자도 같은 행동(실손익 그대로)
            is_flip_long = t.get("flip_from") == "short"
            # 분기 방향: 실제 flip 롱 & OFF → 가상 숏(-1) / 실제 FLAT 숏 & ON → 가상 롱(+1)
            want = -1 if (is_flip_long and decision == "OFF") else \
                   (1 if (not is_flip_long and decision == "ON") else 0)
            if want:
                e, a = t.get("entry_price"), t.get("atr_at_entry")
                size = t.get("position_size_usd") or 0.0
                bs = fetch(cli, t["symbol"], t["timestamp_utc"]) if e and a and size else None
                if bs and len(bs) >= 3:
                    shadow = round(sim(want, e, a, bs) / 100 * size, 2)
                    divergent.append({"trade_id": t.get("trade_id"),
                                      "symbol": t.get("symbol"),
                                      "actual": actual, "shadow": shadow})
                # 봉을 못 받으면 분기로 세지 않고 그림자=실제 유지(보수적)
            day_shadow += shadow
        except Exception:
            continue    # 사건 1건의 불량이 조종사 전체를 멈추면 안 된다

    last = prev[-1] if prev else {}
    rec = {"day": day, "dial": state.get("dial"), "n_events": state.get("n_events"),
           "decision": decision, "n_div": len(divergent), "divergent": divergent,
           "day_actual": round(day_actual, 2), "day_shadow": round(day_shadow, 2),
           "cum_div": (last.get("cum_div") or 0) + len(divergent),
           "cum_actual": round((last.get("cum_actual") or 0.0) + day_actual, 2),
           "cum_shadow": round((last.get("cum_shadow") or 0.0) + day_shadow, 2)}
    _append_jsonl(log_p, rec)
    return rec
