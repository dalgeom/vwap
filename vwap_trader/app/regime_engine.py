"""관측소 v1 — 연속성 다이얼 (설계: docs/superpowers/specs/2026-10-21-regime-adaptive-bot-design.md).

사건 = FLAT 레짐에서 잡힌 숏 신호 거래. flip 이전 시절은 실제 숏으로, flip 이후는
flip_from='short' 롱으로 남아 있다 — 양쪽 다 같은 모집단이므로 함께 센다.
사건마다 공용 시뮬 엔진으로 양방향을 재고, 우위 = 롱% − 숏%(노셔널 대비 %p).
다이얼 = 최근 K=20 사건의 우위 평균. 사건 5건 미만 → None(판단 보류 = 현상 유지).

K=20 고정 근거(2026-10-20 walk-forward 반사실): 5~7월 57건 전부 OFF(참사 -$9,476 회피),
8월부터 ON 전환, 9/02 이후 이득 +$212 보존. K=10은 6월 whipsaw -$739 — 민감한 다이얼은 독.
진입 +49h(48봉 만기 +1h) 성숙 사건만 확정 — 미완결 거래가 다이얼을 흔들지 않게.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

K_EVENTS = 20
MIN_EVENTS = 5
MATURITY_H = 49
# 데모 수동청산 오라벨 3건(2026-10-20 규약) — 모든 사건 집계에서 제외
MAN_EXCLUDE = {"4720d21e", "24257e28", "050d5faf"}


def is_dial_event(t: dict) -> bool:
    if t.get("trade_id") in MAN_EXCLUDE:
        return False
    if t.get("flip_from") == "short":
        return True
    return (t.get("side") == "short"
            and str(t.get("regime", "")).startswith("FLAT"))


def compute_dial(advs: list, k: int = K_EVENTS, min_events: int = MIN_EVENTS):
    recent = advs[-k:]
    if len(recent) < min_events:
        return None
    return round(sum(recent) / len(recent), 4)


def _load_jsonl(p: Path) -> list:
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _append_jsonl(p: Path, rec: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _load_trades(root: Path, demo: bool) -> list:
    from vwap_trader.mode_paths import data_dir
    from build_canonical import load_canonical
    from corrections import read_corrections
    dd = data_dir(root, demo)
    if not (dd / "trades_momentum.jsonl").exists():
        return []                          # 신규 PC — 거래 기록 아직 없음
    return load_canonical(
        raw_path=dd / "trades_momentum.jsonl",
        corrected_path=dd / "trades_momentum_corrected.jsonl",
        corrections=read_corrections(dd / "pnl_corrections.jsonl"))


def update_dial(root: Path, demo: bool, now_utc: datetime | None = None,
                cli=None, fetch=None, sim=None) -> dict:
    """신규 성숙 사건을 양방향 시뮬해 캐시(dial_events.jsonl)에 쌓고,
    오늘 상태판 레코드를 regime_state.jsonl에 적재한 뒤 반환한다."""
    from vwap_trader.mode_paths import data_dir
    from app.trade_sim import fetch_bars, sim_pct
    fetch = fetch or fetch_bars
    sim = sim or sim_pct
    now = now_utc or datetime.now(timezone.utc)
    dd = data_dir(root, demo)

    cache_p = dd / "dial_events.jsonl"
    cache = _load_jsonl(cache_p)
    seen = {c.get("trade_id") for c in cache}

    if cli is None and fetch is fetch_bars:
        from pybit.unified_trading import HTTP
        cli = HTTP(testnet=False)

    new = 0
    for t in _load_trades(root, demo):
        tid = t.get("trade_id")
        if not tid or tid in seen or not is_dial_event(t):
            continue
        try:
            entered = datetime.fromisoformat(t["timestamp_utc"])
        except (KeyError, ValueError, TypeError):
            continue
        if entered.tzinfo is None:
            # tz 없는 기록은 제외 — 성숙 판정(UTC)과 봉 조회(로컬 해석)가
            # 9시간 어긋나 조용히 틀린다(2026-10-21 trade_sim 품질 검수 지적).
            # 실데이터 timestamp_utc는 전부 +00:00이라 실제 영향 0.
            continue
        if now - entered < timedelta(hours=MATURITY_H):
            continue                       # 미성숙 — 다음 날 재시도
        e, a = t.get("entry_price"), t.get("atr_at_entry")
        bs = fetch(cli, t["symbol"], t["timestamp_utc"])
        if not bs or len(bs) < 3 or not e or not a:
            continue                       # 봉 결측 — 다음 날 재시도(상폐 심볼은 매일 1콜 낭비 허용)
        adv = round(sim(1, e, a, bs) - sim(-1, e, a, bs), 4)
        rec = {"trade_id": tid, "ts": t["timestamp_utc"], "symbol": t["symbol"],
               "adv_pct": adv}
        _append_jsonl(cache_p, rec)
        cache.append(rec)
        seen.add(tid)
        new += 1

    cache.sort(key=lambda c: c.get("ts") or "")
    dial = compute_dial([c["adv_pct"] for c in cache if c.get("adv_pct") is not None])
    state = {"day": now.astimezone(timezone(timedelta(hours=9))).date().isoformat(),
             "ts": now.isoformat(), "dial": dial,
             "n_events": len(cache), "new_events": new}
    _append_jsonl(dd / "regime_state.jsonl", state)
    return state
