"""그림자 조종사 v1 — flip 다이얼(H-14) 관측. 판단·그림자 손익을 기록만 한다.

실돈 거래는 절대 바꾸지 않는다. 승격(실권 이양)은 H-14 게이트(분기 30건 또는 4주) 후
사장님 판정으로만 — 설계: docs/superpowers/specs/2026-10-21-regime-adaptive-bot-design.md.

소비자 계약 (두 파일, 모드 데이터 디렉토리):
- shadow_pilot.jsonl (하루 한 줄, 같은 day 재실행은 기존 줄 반환):
  day, dial, n_events, decision — 오늘 다이얼로 내린 판단(ON/OFF/None=보류).
  이 decision은 '다음 진입분부터' 적용되는 판단이다(walk-forward). 사건 채점은
  오늘 판단이 아니라 그 사건의 진입일(KST) 이전 마지막 일일 레코드의 decision
  (= applied)으로 한다 — 미래 몰래보기 금지. 기록이 없으면 applied=None(분기 없음).
  n_new(오늘 평가 완료 수), n_unresolved(봉 결측·예외로 재시도 예정 수),
  divergent/n_div(오늘 새로 확정된 분기), cum_div/cum_actual/cum_shadow.
- pilot_events.jsonl (사건별 1줄, trade_id 키): trade_id, symbol, entry_ts,
  applied, actual, shadow, divergent. 평가 실패는 기록하지 않고 다음 실행에서 재시도.
- cum_*은 매번 pilot_events 합산이라 결측일·역순·수동 재생성에 불변이다. 합산 대상은
  판단(applied)이 있던 사건만 — H-14 게이트의 공정 분모(판단 없던 시절 이력이 절대값을 오염시키지 않게).
- 한계: 일일 레코드에는 ts가 없어 day 단위 walk-forward다 — 레코드가 수 시간 늦게 생성되면
  그날 진입분에 약한 누수 가능(자기 사건 혼입은 아님).
- actual은 체결 포함 실손익, shadow는 분기 시 공용 시뮬(수수료 미반영) — 분기 비교 전용.
  분기가 아니면 shadow = actual.
평가 시점: 청산 완료 AND 진입+49h 경과(봉 48개 보장) AND 아직 평가 안 됨."""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app.regime_engine import (MATURITY_H, _append_jsonl, _load_jsonl,
                               _load_trades, is_dial_event, update_dial)

KST = timezone(timedelta(hours=9))


def decide(dial):
    """다이얼 > 0 → 뒤집기 유지(ON), <= 0 → 중단(OFF), None → 보류(현상 유지)."""
    if dial is None:
        return None
    return "ON" if dial > 0 else "OFF"


def _applied(prev: list, entry_day: str):
    """진입일 이전(day < entry_day) 마지막 일일 레코드의 decision, 없으면 None."""
    cands = [r for r in prev
             if isinstance(r.get("day"), str) and r["day"] < entry_day]
    if not cands:
        return None
    cands.sort(key=lambda r: r["day"])      # 안정 정렬 — 같은 day면 파일상 마지막
    return cands[-1].get("decision")


def run_pilot(root: Path, day: str, demo: bool, now_utc=None,
              cli=None, fetch=None, sim=None) -> dict:
    """성숙한 사건 거래를 진입 당시 판단(applied)과 대조해 평가·기록한다.

    같은 day가 이미 기록돼 있으면 그 줄을 그대로 반환(재생성 중복 방지)."""
    date.fromisoformat(day)                  # 형식 오류는 ValueError
    from vwap_trader.mode_paths import data_dir
    from app.trade_sim import fetch_bars, sim_pct
    fetch = fetch or fetch_bars
    sim = sim or sim_pct
    dd = data_dir(root, demo)
    log_p = dd / "shadow_pilot.jsonl"
    ev_p = dd / "pilot_events.jsonl"
    prev = _load_jsonl(log_p)
    done_rec = next((r for r in reversed(prev) if r.get("day") == day), None)
    if done_rec is not None:
        return done_rec

    now = now_utc or datetime.now(timezone.utc)
    state = update_dial(root, demo, now_utc=now, cli=cli, fetch=fetch, sim=sim)
    decision = decide(state.get("dial"))

    if cli is None and fetch is fetch_bars:
        from pybit.unified_trading import HTTP
        cli = HTTP(testnet=False)

    cache = _load_jsonl(ev_p)
    done = {c.get("trade_id") for c in cache}

    new_div = []
    n_new = n_unresolved = 0
    for t in _load_trades(root, demo):
        tid = t.get("trade_id")
        if not tid or tid in done or not is_dial_event(t):
            continue
        try:
            if not t.get("exit_timestamp_utc"):
                continue                     # 미청산 — 아직 채점 불가
            entered = datetime.fromisoformat(t["timestamp_utc"])
            if entered.tzinfo is None:
                continue                     # tz 없는 기록은 날짜 귀속 불확실 — 제외
            if now - entered < timedelta(hours=MATURITY_H):
                continue                     # 미성숙 — 봉 48개 보장 전
            actual = float(t.get("pnl_usd") or 0.0)
            applied = _applied(prev, entered.astimezone(KST).date().isoformat())
            is_flip_long = t.get("flip_from") == "short"
            # 분기: 실제 flip 롱 & OFF → 가상 숏(-1) / 실제 FLAT 숏 & ON → 가상 롱(+1)
            want = -1 if (is_flip_long and applied == "OFF") else \
                   (1 if (not is_flip_long and applied == "ON") else 0)
            shadow, divergent = actual, False
            if want:
                e, a = t.get("entry_price"), t.get("atr_at_entry")
                size = t.get("position_size_usd") or 0.0
                bs = fetch(cli, t["symbol"], t["timestamp_utc"]) if e and a and size else None
                if not bs or len(bs) < 3:
                    n_unresolved += 1        # 캐시 미기록 = 다음 실행 재시도 (actual도 미집계 — 대칭)
                    continue
                shadow = round(sim(want, e, a, bs) / 100 * size, 2)
                divergent = True
            rec = {"trade_id": tid, "symbol": t.get("symbol"),
                   "entry_ts": t["timestamp_utc"], "applied": applied,
                   "actual": actual, "shadow": shadow, "divergent": divergent}
            _append_jsonl(ev_p, rec)
        except Exception:
            n_unresolved += 1                # 사건 1건의 불량이 조종사 전체를 멈추면 안 된다
            continue
        cache.append(rec)
        done.add(tid)
        n_new += 1
        if divergent:
            new_div.append({"trade_id": tid, "symbol": rec["symbol"],
                            "actual": actual, "shadow": shadow})

    judged = [c for c in cache if c.get("applied") is not None]
    out = {"day": day, "dial": state.get("dial"), "n_events": state.get("n_events"),
           "decision": decision, "n_new": n_new, "n_unresolved": n_unresolved,
           "divergent": new_div, "n_div": len(new_div),
           "cum_div": sum(1 for c in judged if c.get("divergent")),
           "cum_actual": round(sum(c.get("actual") or 0.0 for c in judged), 2),
           "cum_shadow": round(sum(c.get("shadow") or 0.0 for c in judged), 2)}
    _append_jsonl(log_p, out)
    return out
