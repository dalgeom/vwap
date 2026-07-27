# -*- coding: utf-8 -*-
"""B-2: 지연/확인 진입 백테스트 (backtest_delayed_entry.py).
신호 후 N분 초동 방향이 신호 방향과 일치할 때만 진입 시, 즉시역행 손실을
잭팟 훼손 없이 줄이는지 판정. backtest_be replay 계승, 읽기전용 측정 도구.
"""
import os, json, time
from pathlib import Path
from datetime import datetime, timezone

# ★ 앱(frozen exe)이 xcrowd_snapshot → build_client() 경로로 이 모듈의 .env를 읽는다.
#   __file__ 기준이면 번들 내부를 가리켜 키를 못 찾으므로 env 오버라이드를 존중한다
#   (app/paths.py 주석의 경고 사례 — 2026-07-28 xcrowd 스냅샷 누락).
_ENV_ROOT = os.environ.get("VWAP_PROJECT_ROOT")
ROOT = Path(_ENV_ROOT).resolve() if _ENV_ROOT else Path(__file__).resolve().parent
CACHE = ROOT / "data" / "_bt_delayed_klines_cache.json"

SL_MULT = 1.5
TRAIL_MULT = 2.0
BE_TRIGGER = 1.5
MAX_HOLD_MS = 48 * 3600 * 1000
FEE = 0.00055 * 2  # 왕복 taker
DELAYS = (1, 2, 3, 4, 5)


def iso_ms(s: str) -> int:
    return int(datetime.fromisoformat(s).timestamp() * 1000)


def pnl_of(entry: float, exit_price: float, side: str, size_usd: float) -> float:
    qty = size_usd / entry
    gross = qty * (exit_price - entry) if side == "long" else qty * (entry - exit_price)
    return gross - size_usd * FEE


def confirm(bars, e_ms, entry_price, side, n):
    """N번째 1분봉 종가로 방향 확인.
    반환: (status, conf_price, start_ms, replay_bars)
      - "enter":  conf_price에 진입, start_ms부터 replay_bars 재생
      - "skip":   반대 방향 → 진입 안 함 (start_ms, replay_bars=None)
      - "nodata": 창에 N번째 봉 없음
    """
    e_floor = (e_ms // 60000) * 60000
    after = [b for b in bars if b[0] >= e_floor]
    if len(after) < n:
        return ("nodata", None, None, None)
    conf = after[n - 1]
    cp = conf[3]  # 종가
    favorable = cp > entry_price if side == "long" else cp < entry_price
    if not favorable:
        return ("skip", cp, None, None)
    return ("enter", cp, conf[0] + 60000, after[n:])


def replay(entry, atr, side, bars, start_ms, be_trigger=BE_TRIGGER):
    """진입가 entry(시각 start_ms)부터 봇 스탑로직 1분봉 재생.
    bars = (ts, high, low, close) 오름차순, start_ms 이후만. 반환 (exit_price, reason).
    로직: 초기 SL 1.5ATR → 본전잠금(이익 be_trigger*ATR) → 추적 2ATR + spike guard
          → 48h Timeout → 소진 시 EndWindow.
    """
    if not bars:
        return None, "nodata"
    be_level = be_trigger * atr
    trail_dist = TRAIL_MULT * atr
    best = entry
    be = False
    if side == "long":
        sl = entry - SL_MULT * atr
        for ts, hi, lo, cl in bars:
            if lo <= sl:
                return sl, ("TrailSL" if be else "SL")
            if ts - start_ms >= MAX_HOLD_MS:
                return cl, "Timeout"
            if hi > best:
                best = hi
            if not be and best >= entry + be_level:
                be = True
                sl = max(sl, entry)
            if be:
                nsl = best - trail_dist
                if nsl >= cl:  # spike-retrace guard
                    nsl = entry if entry < cl else sl
                if nsl > sl:
                    sl = nsl
        return bars[-1][3], "EndWindow"
    else:
        sl = entry + SL_MULT * atr
        for ts, hi, lo, cl in bars:
            if hi >= sl:
                return sl, ("TrailSL" if be else "SL")
            if ts - start_ms >= MAX_HOLD_MS:
                return cl, "Timeout"
            if lo < best:
                best = lo
            if not be and best <= entry - be_level:
                be = True
                sl = min(sl, entry)
            if be:
                nsl = best + trail_dist
                if nsl <= cl:  # spike-retrace guard (mirror)
                    nsl = entry if entry > cl else sl
                if nsl < sl:
                    sl = nsl
        return bars[-1][3], "EndWindow"


def simulate(trades, klines, n, top_ids):
    """N분 지연 진입 시뮬. n=0이면 즉시 진입(기준선). 반환 집계 dict."""
    res = {"n": n, "entered": 0, "skipped": 0, "nodata": 0,
           "total_pnl": 0.0, "wins": 0,
           "avoided_loss": 0.0, "avoided_cnt": 0,
           "jackpot_kept": [], "jackpot_missed": []}
    for t in trades:
        bars = klines.get(t["trade_id"]) or []
        if not bars:
            res["nodata"] += 1
            continue
        e_ms = iso_ms(t["timestamp_utc"])
        entry, atr, side = t["entry_price"], t["atr_at_entry"], t["side"]
        size, actual = t["position_size_usd"], t["pnl_usd"]
        sym = t["symbol"].replace("USDT", "")
        is_jp = t["trade_id"] in top_ids
        if n == 0:
            e_floor = (e_ms // 60000) * 60000
            status, cp, start_ms = "enter", entry, e_ms
            rbars = [b for b in bars if b[0] >= e_floor]
        else:
            status, cp, start_ms, rbars = confirm(bars, e_ms, entry, side, n)
        if status == "nodata":
            res["nodata"] += 1
            continue
        if status == "skip":
            res["skipped"] += 1
            if actual < 0:
                res["avoided_loss"] += actual
                res["avoided_cnt"] += 1
            if is_jp:
                res["jackpot_missed"].append((sym, actual))
            continue
        xp, reason = replay(cp, atr, side, rbars, start_ms)
        p = actual if xp is None else pnl_of(cp, xp, side, size)
        res["entered"] += 1
        res["total_pnl"] += p
        if p > 0:
            res["wins"] += 1
        if is_jp:
            res["jackpot_kept"].append((sym, round(p, 1)))
    return res


def build_client():
    from dotenv import load_dotenv
    from pybit.unified_trading import HTTP
    load_dotenv(ROOT / "config" / ".env")
    key = os.environ.get("BYBIT_API_KEY", "")
    if not key:
        raise RuntimeError("BYBIT_API_KEY 없음 — config/.env 확인")
    return HTTP(testnet=False, demo=True, api_key=key,
                api_secret=os.environ.get("BYBIT_API_SECRET", ""))


def fetch_1m(client, sym, a, b):
    """1m klines [a,b) — 앞에서부터 채우는 페이지네이션, (ts, high, low, close) 오름차순.
    Bybit는 start+end 범위에서 end에 가까운 최근 limit봉을 반환하므로, 페이지 창을
    1000봉(=1000분) 이하로 잘라야 진입 시점부터 빠짐없이 커버된다.
    """
    PAGE_MS = 1000 * 60000  # 1000봉 = 1000분
    out, cur = [], a
    while cur < b:
        page_end = min(cur + PAGE_MS, b)
        r = client.get_kline(category="linear", symbol=sym, interval="1",
                             start=cur, end=page_end, limit=1000)
        if r.get("retCode") != 0:
            break
        lst = sorted(r["result"]["list"], key=lambda x: int(x[0]))
        if lst:
            out += lst
            cur = max(int(lst[-1][0]) + 60000, page_end)  # 진행 보장(빈 창도 건너뜀)
        else:
            cur = page_end
        time.sleep(0.1)
    seen, u = set(), []
    for k in out:
        ts = int(k[0])
        if ts in seen:
            continue
        seen.add(ts)
        u.append((ts, float(k[2]), float(k[3]), float(k[4])))
    return sorted(u)


def load_trades():
    """정본 거래 중 진입/청산/필수필드 갖춘 것만."""
    from build_canonical import load_canonical
    req = ("trade_id", "timestamp_utc", "entry_price", "atr_at_entry", "side",
           "position_size_usd")
    out = []
    for t in load_canonical():
        if all(t.get(k) not in (None, "") for k in req) and t.get("exit_timestamp_utc"):
            out.append(t)
    return out


def load_klines(client, trades):
    """전용 캐시 우선, 없는 trade_id만 [진입, 진입+48h] 조회 후 캐시. 반환 {trade_id: bars}."""
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    kl = {}
    if CACHE.exists():
        kl = {k: [tuple(b) for b in v] for k, v in json.load(open(CACHE)).items()}
    miss = [t for t in trades if t["trade_id"] not in kl]
    for i, t in enumerate(miss, 1):
        e = iso_ms(t["timestamp_utc"])
        kl[t["trade_id"]] = fetch_1m(client, t["symbol"], e, min(e + MAX_HOLD_MS, now_ms))
        if i % 25 == 0:
            print(f"  klines {i}/{len(miss)}")
        time.sleep(0.06)
    if miss:
        json.dump(kl, open(CACHE, "w"))
    return kl


FIX_MS = iso_ms("2026-06-04T00:00:00+00:00")


def _fmt_res(r, label):
    wr = r["wins"] / r["entered"] * 100 if r["entered"] else 0.0
    print(f"[{label}] 진입 {r['entered']} / 스킵 {r['skipped']} / 제외 {r['nodata']} "
          f"| 순PnL {r['total_pnl']:>+9.0f} | 승률 {wr:>4.0f}% "
          f"| 피한손실 {r['avoided_loss']:>+8.0f}({r['avoided_cnt']}건) "
          f"| 잭팟 지킴 {len(r['jackpot_kept'])}/놓침 {len(r['jackpot_missed'])}")


def render(trades, klines, top_ids, cohort_label):
    base = simulate(trades, klines, 0, top_ids)
    actual_tot = sum(t["pnl_usd"] for t in trades)
    print(f"\n=== [{cohort_label}] 기준선 재현검증 (n={len(trades)}) ===")
    if actual_tot:
        print(f"  기준선(즉시진입) 재생 순PnL {base['total_pnl']:+.0f} | 실제 합계 {actual_tot:+.0f} "
              f"| 재현율 {base['total_pnl']/actual_tot*100:.0f}%")
    else:
        print("  (실제합계 0)")
    print("  ※ 재현율이 크게 어긋나면 아래 지연 결과는 신뢰 불가 — 판정 보류.")
    print(f"\n=== [{cohort_label}] 지연 스윕 ===")
    _fmt_res(base, "N=0 기준")
    for n in DELAYS:
        _fmt_res(simulate(trades, klines, n, top_ids), f"N={n}분")


def main():
    client = build_client()
    trades = load_trades()
    print(f"정본 거래 {len(trades)}건 로드. 1분봉 준비 중...")
    klines = load_klines(client, trades)
    top_ids = {t["trade_id"] for t in sorted(trades, key=lambda x: -x["pnl_usd"])[:5]}
    post = [t for t in trades if iso_ms(t["timestamp_utc"]) >= FIX_MS]
    render(trades, klines, top_ids, "전체 228")
    render(post, klines, {t["trade_id"] for t in sorted(post, key=lambda x: -x["pnl_usd"])[:5]},
           "수정후 신뢰코호트")
    print("\n⚠ 진입가 변경 시 출구경로도 바뀌어 완전 재현 불가(§8.9). 방향성 스크리닝 — "
          "유망 시 v11 forward A/B로만 확정, 이 숫자로 규칙 직접 변경 금지.")


if __name__ == "__main__":
    main()
