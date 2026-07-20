# -*- coding: utf-8 -*-
"""Step 2: BE A/B 반사실 계측기 (봇 내장, 기록 전용).
반대 arm(본전잠금 트리거만 다름)의 청산을 같은 봉 데이터로 그림자 추적. 거래소 미접촉.
"""
import json

FEE = 0.00055 * 2  # 왕복 taker


def shadow_init_fields(real_arm, entry_price, sl, be_trigger_a=1.5, be_trigger_b=0.75):
    """새 포지션의 반대 arm(그림자) 초기 상태 dict.
    실제 A(1.5) → 그림자 B(0.75), 실제 B(0.75) → 그림자 A(1.5). 초기 SL은 두 arm 동일."""
    if real_arm == "A":
        s_arm, s_be = "B", be_trigger_b
    else:
        s_arm, s_be = "A", be_trigger_a
    return {"shadow_arm": s_arm, "shadow_be_trigger": s_be,
            "shadow_best_price": entry_price, "shadow_be_triggered": False, "shadow_sl": sl}


def pnl_of(entry, exit_price, direction, size_usd):
    qty = size_usd / entry
    gross = qty * (exit_price - entry) if direction == "long" else qty * (entry - exit_price)
    return gross - size_usd * FEE


def advance_stop(direction, entry, atr, be_trigger, trail_mult, exit_mode,
                 st, bar_high, bar_low, cur):
    """손절선 전진 정책 — 봇 _update_trailing_sl과 그림자가 공유하는 단일 진실(순수함수).
    st={"best","be","sl"} in-place 갱신. 돌파 검사는 하지 않음(봇=거래소가, 그림자=update_shadow가).
    exit_mode: "be_trail"=본전잠금 후에만 추적 / "trailing"=항상 추적 / "fixed"=무동작.
    (결함③ 수리 2026-07-20: 구그림자는 추적선 항상 활성으로 봇 be_trail 정책과 달랐음 — §5.12 A)"""
    if exit_mode == "fixed":
        return
    be_level = be_trigger * atr
    trail_dist = trail_mult * atr
    if direction == "long":
        if bar_high > st["best"]:
            st["best"] = bar_high
        if not st["be"] and st["best"] >= entry + be_level:
            st["be"] = True
            if entry > st["sl"]:
                st["sl"] = entry
        if st["be"] or exit_mode == "trailing":
            nsl = st["best"] - trail_dist
            # spike-retrace 가드(봇과 동일): be 발동 시에만 entry 복귀
            if cur and nsl >= cur:
                nsl = entry if (st["be"] and entry < cur) else st["sl"]
            if nsl > st["sl"]:
                st["sl"] = nsl
    else:
        if bar_low < st["best"]:
            st["best"] = bar_low
        if not st["be"] and st["best"] <= entry - be_level:
            st["be"] = True
            if entry < st["sl"]:
                st["sl"] = entry
        if st["be"] or exit_mode == "trailing":
            nsl = st["best"] + trail_dist
            if cur and nsl <= cur:
                nsl = entry if (st["be"] and entry > cur) else st["sl"]
            if nsl < st["sl"]:
                st["sl"] = nsl


def shadow_exit_reason(direction, entry, sl, be):
    """봇 _classify_exit_reason 미러 (tp=0 전제)."""
    if not be:
        return "SL"
    if direction == "long" and sl > entry:
        return "TrailSL"
    if direction == "short" and sl < entry:
        return "TrailSL"
    return "BE"


def update_shadow(direction, entry, atr, be_trigger, trail_mult, exit_mode,
                  st, bar_high, bar_low, cur):
    """그림자 갱신: 이번 분 시작 sl 기준 돌파 먼저(look-ahead 금지) → advance_stop.
    반환 (exited, exit_price, reason). 봇과 같은 정책 공유(결함③ 수리)."""
    sl = st["sl"]
    if direction == "long":
        if bar_low <= sl:
            return True, sl, shadow_exit_reason(direction, entry, sl, st["be"])
    else:
        if bar_high >= sl:
            return True, sl, shadow_exit_reason(direction, entry, sl, st["be"])
    advance_stop(direction, entry, atr, be_trigger, trail_mult, exit_mode,
                 st, bar_high, bar_low, cur)
    return False, None, None


def build_pair_record(*, trade_id, symbol, direction, entry, atr, size_usd,
                      real_arm, real_be, real_exit, real_reason, real_exchange_pnl, real_exit_ms,
                      shadow_arm, shadow_be, shadow_exit, shadow_reason, shadow_exit_ms):
    return {
        "trade_id": trade_id, "symbol": symbol, "direction": direction,
        "entry_price": entry, "atr_at_entry": atr, "position_size_usd": round(size_usd, 2),
        "real_arm": real_arm, "real_be_trigger": real_be,
        "real_exit_price": real_exit, "real_exit_reason": real_reason,
        "real_pnl": round(pnl_of(entry, real_exit, direction, size_usd), 4),
        "shadow_arm": shadow_arm, "shadow_be_trigger": shadow_be,
        "shadow_exit_price": shadow_exit, "shadow_exit_reason": shadow_reason,
        "shadow_pnl": round(pnl_of(entry, shadow_exit, direction, size_usd), 4),
        "real_exchange_pnl": real_exchange_pnl,
        "real_exit_ms": real_exit_ms, "shadow_exit_ms": shadow_exit_ms,
    }


def append_pair(path, record):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
