"""
2025년 전체 백테스트 — 오늘 스크리너 후보 26개 코인
기간: 2025-01-01 ~ 2025-12-31
전략: 매일 스크리닝 → 상위 5개 선정 → EMA9/21 + ADX>20 + 1:2 ATR SL/TP
초기 잔고: 10,000 USDT | 거래당 리스크 2% | 레버리지 5x (실효 3x 캡)
수수료: 0.055% × 2 (진입+청산 taker)
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parents[3] / "config" / ".env")

from vwap_trader.infra.bybit_client import BybitClient

# ── 설정 ─────────────────────────────────────────────────────────
INTERVAL          = "15"
ATR_PERIOD        = 14
ADX_PERIOD        = 14
ADX_THRESHOLD     = 20
SL_ATR_MULT       = 0.5
TP_ATR_MULT       = 1.0
MAX_HOLD          = 32          # 8h = 32봉
FEE_RATE          = 0.00055 * 2 # taker 진입+청산
INITIAL_BALANCE   = 10_000.0
RISK_PCT          = 0.02
MAX_LEV_REAL      = 3.0
SELECT_TOP        = 5
SCREENER_LB       = 672         # 스크리너 룩백 7일 (7×24×4)
MIN_SIGNALS       = 3
MIN_WIN_RATE      = 1 / 3

START_DT = datetime(2025,  1,  1,  0, 0, 0, tzinfo=timezone.utc)
END_DT   = datetime(2025, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
START_MS = int(START_DT.timestamp() * 1000)
END_MS   = int(END_DT.timestamp()   * 1000)

COINS = [
    "B3USDT", "IOUSDT", "LABUSDT", "BILLUSDT", "WIFUSDT", "TONUSDT",
    "DASHUSDT", "ICPUSDT", "NEARUSDT", "ZECUSDT", "FILUSDT", "FARTCOINUSDT",
    "ENAUSDT", "TAOUSDT", "CLUSDT", "ONDOUSDT", "SUIUSDT", "DOGEUSDT",
    "BNBUSDT", "1000PEPEUSDT", "LINKUSDT", "ADAUSDT", "HYPEUSDT", "SOLUSDT",
    "XRPUSDT", "XAUTUSDT",
]

CACHE_DIR  = Path(__file__).parents[3] / "data" / "backtest_cache"
RESULT_DIR = Path(__file__).parents[3] / "data" / "backtest_results"


# ── 지표 ─────────────────────────────────────────────────────────

def _ema(vals: list[float], p: int) -> list[float]:
    if len(vals) < p:
        return []
    k = 2.0 / (p + 1)
    r = [sum(vals[:p]) / p]
    for v in vals[p:]:
        r.append(v * k + r[-1] * (1 - k))
    return r


def _wilder(vals: list[float], p: int) -> list[float]:
    if len(vals) < p:
        return []
    r = [sum(vals[:p]) / p]
    for v in vals[p:]:
        r.append(r[-1] * (p - 1) / p + v / p)
    return r


def _calc_atr(highs, lows, closes, p=ATR_PERIOD) -> float | None:
    if len(closes) < p + 1:
        return None
    trs = [max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
           for i in range(1, len(closes))]
    s = _wilder(trs, p)
    return s[-1] if s else None


def _calc_adx(highs, lows, closes, p=ADX_PERIOD) -> float | None:
    if len(closes) < p * 2 + 2:
        return None
    trs, pdms, mdms = [], [], []
    for i in range(1, len(closes)):
        tr   = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
        up   = highs[i] - highs[i-1]
        down = lows[i-1] - lows[i]
        trs.append(tr)
        pdms.append(up   if up > down and up > 0   else 0.0)
        mdms.append(down if down > up and down > 0 else 0.0)
    atr_s = _wilder(trs,  p)
    pdi_s = _wilder(pdms, p)
    mdi_s = _wilder(mdms, p)
    dxs = []
    for a, pd, md in zip(atr_s, pdi_s, mdi_s):
        if a == 0:
            continue
        pdi = 100 * pd / a
        mdi = 100 * md / a
        den = pdi + mdi
        dxs.append(100 * abs(pdi - mdi) / den if den else 0.0)
    adx = _wilder(dxs, p)
    return adx[-1] if adx else None


def _r_squared(values: list[float]) -> float:
    n = len(values)
    if n < 3:
        return 0.0
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(values) / n
    ss_tot = sum((y - my) ** 2 for y in values)
    if ss_tot == 0:
        return 0.0
    slope = sum((x-mx)*(y-my) for x, y in zip(xs, values)) / max(sum((x-mx)**2 for x in xs), 1e-10)
    ss_res = sum((y - (my + slope*(x-mx)))**2 for x, y in zip(xs, values))
    return max(0.0, 1.0 - ss_res / ss_tot)


# ── 데이터 페치 (캐시 포함) ───────────────────────────────────────

def _cache_path(sym: str) -> Path:
    return CACHE_DIR / f"{sym}_2025_15m.json"


def fetch_or_load(client: BybitClient, sym: str) -> list[dict]:
    """2025년 15m 캔들을 로컬 캐시에서 로드하거나 Bybit에서 다운로드."""
    cp = _cache_path(sym)
    if cp.exists():
        data = json.loads(cp.read_text(encoding="utf-8"))
        print(f"  {sym:<20} 캐시 로드: {len(data)}봉")
        return data

    print(f"  {sym:<20} 다운로드 중...", end="", flush=True)
    all_rows: list[dict] = []
    current_end = END_MS

    while current_end > START_MS:
        try:
            resp = client._session.get_kline(
                category="linear",
                symbol=sym,
                interval=INTERVAL,
                limit=200,
                end=current_end,
            )
        except Exception as e:
            print(f" API 오류: {e}")
            break

        raw = resp.get("result", {}).get("list", [])
        if not raw:
            break

        batch = []
        for row in raw:
            ts_ms = int(row[0])
            if ts_ms < START_MS:
                continue
            batch.append({
                "ts": ts_ms,
                "o": float(row[1]),
                "h": float(row[2]),
                "l": float(row[3]),
                "c": float(row[4]),
                "v": float(row[5]),
            })

        all_rows.extend(batch)
        oldest = min(int(r[0]) for r in raw)
        if oldest <= START_MS:
            break
        current_end = oldest - 1

    # 중복 제거 + 정렬
    seen = set()
    unique = []
    for r in all_rows:
        if r["ts"] not in seen:
            seen.add(r["ts"])
            unique.append(r)
    unique.sort(key=lambda x: x["ts"])

    print(f" {len(unique)}봉")
    if unique:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps(unique, ensure_ascii=False), encoding="utf-8")
    return unique


# ── 스크리너 점수 계산 ────────────────────────────────────────────

def score_coin_fast(rows: list[dict]) -> dict:
    """rows: 최근 SCREENER_LB봉 (672봉 = 7일). 스크리너와 동일 로직."""
    if len(rows) < 100:
        return {"score": 0, "reason": "data_insufficient"}

    closes = [r["c"] for r in rows]
    highs  = [r["h"] for r in rows]
    lows   = [r["l"] for r in rows]

    ema9_full  = _ema(closes, 9)
    ema21_full = _ema(closes, 21)
    trs = [max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
           for i in range(1, len(rows))]
    atr_series = _wilder(trs, ATR_PERIOD)

    if len(ema9_full) < 2 or len(ema21_full) < 2 or not atr_series:
        return {"score": 0, "reason": "indicator_fail"}

    min_i = 50
    signals = []
    for i in range(min_i, len(rows) - 1):
        ix9   = i - 8
        ix21  = i - 20
        ix_atr = i - ATR_PERIOD
        if ix9 < 1 or ix21 < 1 or ix_atr < 0:
            continue
        if ix9 >= len(ema9_full) or ix21 >= len(ema21_full) or ix_atr >= len(atr_series):
            continue
        e9c,  e9p  = ema9_full[ix9],  ema9_full[ix9-1]
        e21c, e21p = ema21_full[ix21], ema21_full[ix21-1]
        atr = atr_series[ix_atr]
        if atr <= 0:
            continue
        if e9p <= e21p and e9c > e21c:
            direction = "long"
        elif e9p >= e21p and e9c < e21c:
            direction = "short"
        else:
            continue
        ep = rows[i]["c"]
        tp = ep + atr * (1.0 if direction == "long" else -1.0)
        sl = ep - atr * (0.5 if direction == "long" else -0.5)
        hit = None
        for j in range(i+1, min(i+33, len(rows))):
            r = rows[j]
            if direction == "long":
                if r["l"] <= sl: hit = "sl"; break
                if r["h"] >= tp: hit = "tp"; break
            else:
                if r["h"] >= sl: hit = "sl"; break
                if r["l"] <= tp: hit = "tp"; break
        if hit:
            signals.append(hit)

    if len(signals) < MIN_SIGNALS:
        win_rate = 0.0
        score_ema = 0
    else:
        win_rate  = signals.count("tp") / len(signals)
        score_ema = int(win_rate * 50)

    # ADX 추세
    adx_series = []
    trs2, pdms, mdms = [], [], []
    for i in range(1, len(rows)):
        tr   = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
        up   = highs[i] - highs[i-1]
        down = lows[i-1] - lows[i]
        trs2.append(tr)
        pdms.append(up   if up > down and up > 0   else 0.0)
        mdms.append(down if down > up and down > 0 else 0.0)
    atr_s2 = _wilder(trs2,  ADX_PERIOD)
    pdi_s  = _wilder(pdms, ADX_PERIOD)
    mdi_s  = _wilder(mdms, ADX_PERIOD)
    dxs = []
    for a, pd, md in zip(atr_s2, pdi_s, mdi_s):
        if a == 0: continue
        pdi = 100*pd/a; mdi = 100*md/a; den = pdi+mdi
        dxs.append(100*abs(pdi-mdi)/den if den else 0.0)
    adx_series = _wilder(dxs, ADX_PERIOD)
    if len(adx_series) >= 10:
        ra = adx_series[-10:]
        slope = (ra[-1]-ra[0]) / max(ra[0], 1e-6)
        score_adx = min(30, max(0, int((adx_series[-1]/40)*15 + slope*50*15)))
    else:
        score_adx = 0

    r2 = _r_squared(closes[-48:])
    score_r2 = int(r2 * 20)

    disqualified = len(signals) >= MIN_SIGNALS and win_rate < MIN_WIN_RATE
    total = 0 if disqualified else score_ema + score_adx + score_r2
    return {"score": total, "win_rate": win_rate, "disqualified": disqualified}


# ── 메인 백테스트 ─────────────────────────────────────────────────

def run_backtest(all_data: dict[str, list[dict]]) -> dict:
    """
    all_data: {symbol: [row, ...]} 형태, 2025년 전체 15m 캔들
    returns: 결과 dict
    """
    # 전체 타임슬롯 생성 (2025년 15m 단위)
    ts_set = set()
    for rows in all_data.values():
        for r in rows:
            ts_set.add(r["ts"])
    all_ts = sorted(ts_set)
    if not all_ts:
        return {}

    # 코인별 ts→row 인덱스 맵
    sym_ts_map: dict[str, dict[int, int]] = {}
    for sym, rows in all_data.items():
        sym_ts_map[sym] = {r["ts"]: idx for idx, r in enumerate(rows)}

    # 초기화
    balance    = INITIAL_BALANCE
    trades     = []
    position   = None  # dict or None
    selected   = list(all_data.keys())[:SELECT_TOP]  # 첫날 임시
    last_screen_day = ""

    print(f"\n백테스트 시작 | 타임슬롯: {len(all_ts):,}개 | 코인: {len(all_data)}개")

    for slot_i, ts_ms in enumerate(all_ts):
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)

        # ── 매일 UTC 06:00에 스크리닝 ──
        day_str = dt.strftime("%Y-%m-%d")
        if dt.hour == 6 and dt.minute == 0 and day_str != last_screen_day:
            last_screen_day = day_str
            scores = []
            for sym, rows in all_data.items():
                idx = sym_ts_map[sym].get(ts_ms)
                if idx is None or idx < SCREENER_LB:
                    continue
                window = rows[max(0, idx - SCREENER_LB): idx]
                sc = score_coin_fast(window)
                scores.append((sym, sc["score"]))
            scores.sort(key=lambda x: x[1], reverse=True)
            new_sel = [s for s, sc in scores[:SELECT_TOP] if sc > 0]
            if new_sel:
                selected = new_sel

        # ── 포지션 청산 체크 ──────────────────────────────────────
        if position:
            sym  = position["symbol"]
            rows = all_data.get(sym, [])
            idx  = sym_ts_map[sym].get(ts_ms)
            if idx is not None and idx < len(rows):
                row = rows[idx]
                closed = False
                exit_price = None
                reason = None

                # SL/TP 체크
                if position["dir"] == "long":
                    if row["l"] <= position["sl"]:
                        exit_price, reason = position["sl"], "sl"
                        closed = True
                    elif row["h"] >= position["tp"]:
                        exit_price, reason = position["tp"], "tp"
                        closed = True
                else:
                    if row["h"] >= position["sl"]:
                        exit_price, reason = position["sl"], "sl"
                        closed = True
                    elif row["l"] <= position["tp"]:
                        exit_price, reason = position["tp"], "tp"
                        closed = True

                # 8h 타임아웃
                if not closed:
                    bars_held = slot_i - position["entry_slot"]
                    if bars_held >= MAX_HOLD:
                        exit_price, reason = row["c"], "timeout"
                        closed = True

                # EMA 역크로스
                if not closed and idx >= 21:
                    wc = [r["c"] for r in rows[max(0, idx-30): idx+1]]
                    e9  = _ema(wc, 9)
                    e21 = _ema(wc, 21)
                    if e9 and e21:
                        if position["dir"] == "long"  and e9[-1] < e21[-1]:
                            exit_price, reason = row["c"], "ema_cross"
                            closed = True
                        elif position["dir"] == "short" and e9[-1] > e21[-1]:
                            exit_price, reason = row["c"], "ema_cross"
                            closed = True

                if closed and exit_price is not None:
                    ep = position["entry"]
                    raw = (exit_price - ep) / ep if position["dir"] == "long" else (ep - exit_price) / ep
                    lev = min(MAX_LEV_REAL, position["notional"] / position["balance_at_entry"])
                    net_pct = (raw - FEE_RATE) * lev
                    pnl_usdt = position["balance_at_entry"] * RISK_PCT / SL_ATR_MULT / TP_ATR_MULT
                    # 실제 P&L: 리스크 금액 기준
                    risk_usdt  = position["balance_at_entry"] * RISK_PCT
                    sl_dist_pct = position["sl_dist"] / ep
                    qty = risk_usdt / position["sl_dist"]
                    qty = min(qty, position["balance_at_entry"] * MAX_LEV_REAL / ep)
                    actual_pnl = qty * (exit_price - ep) if position["dir"] == "long" else qty * (ep - exit_price)
                    fee_usdt   = qty * ep * FEE_RATE
                    actual_pnl -= fee_usdt
                    balance += actual_pnl
                    trades.append({
                        "symbol":     sym,
                        "dir":        position["dir"],
                        "entry_time": position["entry_dt"],
                        "exit_time":  dt.isoformat(),
                        "entry":      round(ep, 6),
                        "exit":       round(exit_price, 6),
                        "reason":     reason,
                        "pnl_usdt":   round(actual_pnl, 4),
                        "balance":    round(balance, 4),
                    })
                    position = None

        # ── 진입 신호 스캔 ────────────────────────────────────────
        if position is None:
            for sym in selected:
                rows = all_data.get(sym, [])
                idx  = sym_ts_map[sym].get(ts_ms)
                if idx is None or idx < 60:
                    continue

                window_c = rows[max(0, idx-120): idx+1]
                closes = [r["c"] for r in window_c]
                highs  = [r["h"] for r in window_c]
                lows   = [r["l"] for r in window_c]

                e9  = _ema(closes, 9)
                e21 = _ema(closes, 21)
                if len(e9) < 2 or len(e21) < 2:
                    continue

                prev9, cur9   = e9[-2],  e9[-1]
                prev21, cur21 = e21[-2], e21[-1]

                if prev9 <= prev21 and cur9 > cur21:
                    signal = "long"
                elif prev9 >= prev21 and cur9 < cur21:
                    signal = "short"
                else:
                    continue

                adx = _calc_adx(highs, lows, closes)
                if adx is None or adx < ADX_THRESHOLD:
                    continue

                atr = _calc_atr(highs, lows, closes)
                if atr is None or atr <= 0:
                    continue

                ep = rows[idx]["c"]
                if signal == "long":
                    sl = ep - atr * SL_ATR_MULT
                    tp = ep + atr * TP_ATR_MULT
                else:
                    sl = ep + atr * SL_ATR_MULT
                    tp = ep - atr * TP_ATR_MULT

                sl_dist = abs(ep - sl)
                if sl_dist / ep < 0.001:
                    continue

                notional = min(balance * RISK_PCT / sl_dist * ep,
                               balance * MAX_LEV_REAL)
                if notional < 50:
                    continue

                position = {
                    "symbol":           sym,
                    "dir":              signal,
                    "entry":            ep,
                    "sl":               sl,
                    "tp":               tp,
                    "sl_dist":          sl_dist,
                    "notional":         notional,
                    "balance_at_entry": balance,
                    "entry_slot":       slot_i,
                    "entry_dt":         dt.isoformat(),
                }
                break  # 최대 1포지션

    # 포지션 미청산 시 마지막 가격으로 강제 청산
    if position:
        sym  = position["symbol"]
        rows = all_data.get(sym, [])
        if rows:
            last_row = rows[-1]
            ep = position["entry"]
            exit_price = last_row["c"]
            qty = min(position["balance_at_entry"] * RISK_PCT / position["sl_dist"],
                      position["balance_at_entry"] * MAX_LEV_REAL / ep)
            actual_pnl = qty * (exit_price - ep) if position["dir"] == "long" else qty * (ep - exit_price)
            actual_pnl -= qty * ep * FEE_RATE
            balance += actual_pnl
            trades.append({
                "symbol":   sym,
                "dir":      position["dir"],
                "entry_time": position["entry_dt"],
                "exit_time":  datetime.fromtimestamp(last_row["ts"]/1000, tz=timezone.utc).isoformat(),
                "entry":    round(ep, 6),
                "exit":     round(exit_price, 6),
                "reason":   "end_of_data",
                "pnl_usdt": round(actual_pnl, 4),
                "balance":  round(balance, 4),
            })

    return {"trades": trades, "final_balance": round(balance, 4)}


# ── 결과 요약 출력 ────────────────────────────────────────────────

def print_summary(result: dict) -> None:
    trades  = result.get("trades", [])
    final_b = result.get("final_balance", INITIAL_BALANCE)

    if not trades:
        print("\n거래 없음")
        return

    n       = len(trades)
    wins    = sum(1 for t in trades if t["reason"] == "tp")
    losses  = sum(1 for t in trades if t["reason"] == "sl")
    timeout = sum(1 for t in trades if t["reason"] == "timeout")
    ema_ex  = sum(1 for t in trades if t["reason"] == "ema_cross")
    total_pnl = final_b - INITIAL_BALANCE
    pnl_pct   = total_pnl / INITIAL_BALANCE * 100

    # 최대 드로다운
    bal_curve = [INITIAL_BALANCE] + [t["balance"] for t in trades]
    peak = bal_curve[0]
    max_dd = 0.0
    for b in bal_curve:
        peak = max(peak, b)
        dd = (peak - b) / peak
        max_dd = max(max_dd, dd)

    # 연속 손실
    streak = cur = 0
    for t in trades:
        if t["pnl_usdt"] < 0:
            cur += 1
            streak = max(streak, cur)
        else:
            cur = 0

    # 심볼별 거래 수
    sym_counts: dict[str, int] = {}
    for t in trades:
        sym_counts[t["symbol"]] = sym_counts.get(t["symbol"], 0) + 1

    print(f"""
{'='*65}
  2025년 백테스트 결과 요약
  기간: 2025-01-01 ~ 2025-12-31
  전략: EMA9/21 크로스 + ADX>{ADX_THRESHOLD} + ATR SL/TP (1:2)
{'='*65}

  초기 잔고:       $  {INITIAL_BALANCE:>10,.2f}
  최종 잔고:       $  {final_b:>10,.2f}
  총 손익:         $  {total_pnl:>+10,.2f}   ({pnl_pct:>+.2f}%)

  총 거래 수:        {n:>6}건
    ├ TP 익절:       {wins:>6}건  ({wins/n:.1%})
    ├ SL 손절:       {losses:>6}건  ({losses/n:.1%})
    ├ EMA 역크로스:  {ema_ex:>6}건  ({ema_ex/n:.1%})
    └ 타임아웃(8h):  {timeout:>6}건  ({timeout/n:.1%})

  승률 (TP 기준):    {wins/n:.1%}
  평균 손익/거래:   ${sum(t['pnl_usdt'] for t in trades)/n:>+.2f}
  최대 드로다운:    {max_dd:.1%}
  최대 연속 손실:   {streak}회
  하루 평균 거래:   {n/365:.2f}건

  코인별 거래 수 (상위 10):""")

    for sym, cnt in sorted(sym_counts.items(), key=lambda x: -x[1])[:10]:
        sym_wins = sum(1 for t in trades if t["symbol"]==sym and t["reason"]=="tp")
        print(f"    {sym:<22} {cnt:>4}건  승률 {sym_wins/cnt:.0%}")

    print(f"\n  손익분기 승률: 33.3%  |  실제 승률: {wins/n:.1%}")
    if wins/n > 0.333:
        print("  → 손익분기 초과 달성")
    else:
        print("  → 손익분기 미달")
    print(f"{'='*65}")


# ── 메인 ─────────────────────────────────────────────────────────

def main():
    client = BybitClient(
        api_key=os.getenv("BYBIT_API_KEY", ""),
        api_secret=os.getenv("BYBIT_API_SECRET", ""),
    )

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    RESULT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"데이터 로드 중... (총 {len(COINS)}개 코인)")
    all_data: dict[str, list[dict]] = {}
    for sym in COINS:
        rows = fetch_or_load(client, sym)
        if len(rows) < 200:
            print(f"  {sym:<20} 데이터 부족 ({len(rows)}봉) - 제외")
            continue
        all_data[sym] = rows

    if not all_data:
        print("사용 가능한 데이터 없음")
        return

    print(f"\n총 {len(all_data)}개 코인으로 백테스트 실행")
    result = run_backtest(all_data)

    print_summary(result)

    ts  = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = RESULT_DIR / f"backtest_2025_{ts}.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n상세 결과 저장: {out}")


if __name__ == "__main__":
    main()
