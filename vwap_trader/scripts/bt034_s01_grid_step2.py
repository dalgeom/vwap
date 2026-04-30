"""
bt034_s01_grid_step2.py — S-01: 4H Swing + 15m Pullback Long / 1차 그리드 스크리닝
Dev-Backtest(정민호) / TASK-BT-S01 Step 2 / 결정 #78

216조합 × 10심볼 백테스트.
IS: 2022-07-01 ~ 2023-12-31
OOS: 2024-01-01 ~ 2024-12-31
선별: EV(ATR) > 0 AND OOS Sharpe 상위 20% (~43조합)

파라미터 그리드 (216 = 2×2×3×3×2×3):
  lookback      : 15, 20
  vol_confirm   : 1.3, 1.5
  touch_pct     : 1.003, 1.005, 1.008
  breakout_atr  : 0.2, 0.3, 0.5
  rsi_gate      : None, 30
  max_hold_bars : 36, 48, 60

진입: 조건 A(4H 돌파) + B(1H 추세) + C(15m EMA21 터치+양봉) + D(5봉 쿨다운)
청산: 초기 SL(1.5×ATR_15m) | 백업 SL(ATR_1H) | Chandelier Trail(+1.5% 후) | max_hold
비용: BTC/ETH 0.0015, 기타 0.0019 (왕복)
"""
from __future__ import annotations

import bisect
import csv
import itertools
import json
import math
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT  = Path(__file__).parent.parent
CACHE_DIR  = REPO_ROOT / "data" / "cache"
RESULT_DIR = REPO_ROOT / "data" / "backtest_results"
RESULT_DIR.mkdir(parents=True, exist_ok=True)

IS_START  = datetime(2022, 7,  1,  tzinfo=timezone.utc)
IS_END    = datetime(2023, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
OOS_START = datetime(2024, 1,  1,  tzinfo=timezone.utc)
OOS_END   = datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc)

SYMBOLS_10 = [
    "ARBUSDT", "AVAXUSDT", "BNBUSDT", "BTCUSDT", "DOTUSDT",
    "ETHUSDT", "LINKUSDT", "NEARUSDT", "OPUSDT", "SOLUSDT",
]
TIER1       = {"BTCUSDT", "ETHUSDT"}
FEE_TIER1   = 0.0015
FEE_TIER2   = 0.0019

ATR14_4H = 14
SMA20_4H = 20
EMA9_P   = 9
EMA20_P  = 20
EMA21_P  = 21
ATR14_1H = 14
ATR14_15M = 14
RSI_P     = 14
FRESH_BARS = 12   # 4H 돌파 후 유효 1H 창 (봉 수)

GRID_KEYS = ["lookback", "vol_confirm", "touch_pct", "breakout_atr", "rsi_gate", "max_hold_bars"]
GRID_VALS = [
    [15, 20],
    [1.3, 1.5],
    [1.003, 1.005, 1.008],
    [0.2, 0.3, 0.5],
    [None, 30],
    [36, 48, 60],
]
ALL_COMBOS = list(itertools.product(*GRID_VALS))  # 216


# ─────────────────────── 데이터 로드 ─────────────────────────────

def _load_csv(path: Path, ts_field: str = "auto") -> list[dict]:
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        hdrs = reader.fieldnames or []
        tc = "ts_ms" if "ts_ms" in hdrs else "timestamp"
        for row in reader:
            ts = int(row[tc])
            rows.append({
                "ts_ms": ts,
                "dt": datetime.fromtimestamp(ts / 1000, tz=timezone.utc),
                "open": float(row["open"]), "high": float(row["high"]),
                "low": float(row["low"]),   "close": float(row["close"]),
                "volume": float(row["volume"]),
            })
    rows.sort(key=lambda r: r["ts_ms"])
    return rows


def load_1h(sym: str) -> list[dict]:
    p = CACHE_DIR / f"{sym}_60.csv"
    return _load_csv(p) if p.exists() else []


def load_15m(sym: str) -> list[dict]:
    p = CACHE_DIR / f"{sym}_15m.csv"
    return _load_csv(p) if p.exists() else []


# ─────────────────────── 4H 집계 ─────────────────────────────────

def build_4h(rows_1h: list[dict]) -> list[dict]:
    acc: dict[int, dict] = {}
    order: list[int] = []
    for r in rows_1h:
        bh  = (r["dt"].hour // 4) * 4
        key = int(r["dt"].replace(hour=bh, minute=0, second=0, microsecond=0).timestamp() * 1000)
        if key not in acc:
            acc[key] = {
                "ts_ms": key,
                "dt": r["dt"].replace(hour=bh, minute=0, second=0, microsecond=0),
                "open": r["open"], "high": r["high"],
                "low": r["low"], "close": r["close"],
                "volume": r["volume"],
            }
            order.append(key)
        else:
            a = acc[key]
            a["high"] = max(a["high"], r["high"])
            a["low"]  = min(a["low"],  r["low"])
            a["close"]  = r["close"]
            a["volume"] += r["volume"]
    return [acc[k] for k in order[:-1]]  # 완성 봉만


# ─────────────────────── 지표 계산 ───────────────────────────────

def calc_ema(vals: list[float], p: int) -> list[float | None]:
    n = len(vals)
    out: list[float | None] = [None] * n
    if n < p:
        return out
    k = 2.0 / (p + 1)
    v = sum(vals[:p]) / p
    out[p - 1] = v
    for i in range(p, n):
        v = vals[i] * k + v * (1 - k)
        out[i] = v
    return out


def calc_atr(rows: list[dict], p: int) -> list[float | None]:
    n = len(rows)
    out: list[float | None] = [None] * n
    if n <= p:
        return out
    tr = [0.0] * n
    for i in range(1, n):
        h, l, pc = rows[i]["high"], rows[i]["low"], rows[i - 1]["close"]
        tr[i] = max(h - l, abs(h - pc), abs(l - pc))
    atr = sum(tr[1: p + 1]) / p
    out[p] = atr
    for i in range(p + 1, n):
        atr = (atr * (p - 1) + tr[i]) / p
        out[i] = atr
    return out


def calc_vol_sma(rows: list[dict], p: int) -> list[float | None]:
    n = len(rows)
    out: list[float | None] = [None] * n
    if n < p:
        return out
    s = sum(rows[j]["volume"] for j in range(p))
    out[p - 1] = s / p
    for i in range(p, n):
        s += rows[i]["volume"] - rows[i - p]["volume"]
        out[i] = s / p
    return out


def calc_rsi(vals: list[float], p: int) -> list[float | None]:
    n = len(vals)
    out: list[float | None] = [None] * n
    if n <= p:
        return out
    gains = [max(vals[i] - vals[i - 1], 0.0) for i in range(1, n)]
    losses = [max(vals[i - 1] - vals[i], 0.0) for i in range(1, n)]
    ag = sum(gains[:p]) / p
    al = sum(losses[:p]) / p
    def _rsi(ag, al):
        return 100.0 if al == 0 else 100.0 - 100.0 / (1 + ag / al)
    out[p] = _rsi(ag, al)
    for i in range(p, n - 1):
        ag = (ag * (p - 1) + gains[i]) / p
        al = (al * (p - 1) + losses[i]) / p
        out[i + 1] = _rsi(ag, al)
    return out


def build_daily_vwap(rows_1h: list[dict]) -> list[float]:
    out = [0.0] * len(rows_1h)
    cum: dict[str, tuple[float, float]] = {}
    for i, r in enumerate(rows_1h):
        tp = (r["high"] + r["low"] + r["close"]) / 3.0
        ds = r["dt"].strftime("%Y-%m-%d")
        pv, vol = cum.get(ds, (0.0, 0.0))
        cum[ds] = (pv + tp * r["volume"], vol + r["volume"])
        pv, vol = cum[ds]
        out[i] = pv / vol if vol > 0 else r["close"]
    return out


# ─────────────────────── 심볼 데이터 사전 적재 ───────────────────

class SymData:
    __slots__ = (
        "symbol", "fee",
        "rows_15m", "ema21_15m", "atr_15m", "rsi_15m",
        "rows_1h",  "ema9_1h", "ema20_1h", "vwap_1h", "atr_1h", "ts_1h",
        "rows_4h",  "atr_4h", "vsma_4h",
    )

    def __init__(self, symbol: str):
        self.symbol = symbol
        self.fee = FEE_TIER1 if symbol in TIER1 else FEE_TIER2

        self.rows_1h  = load_1h(symbol)
        self.rows_15m = load_15m(symbol)
        self.rows_4h  = build_4h(self.rows_1h)

        c1h  = [r["close"] for r in self.rows_1h]
        c15m = [r["close"] for r in self.rows_15m]

        self.ema9_1h   = calc_ema(c1h, EMA9_P)
        self.ema20_1h  = calc_ema(c1h, EMA20_P)
        self.vwap_1h   = build_daily_vwap(self.rows_1h)
        self.atr_1h    = calc_atr(self.rows_1h, ATR14_1H)

        self.ema21_15m = calc_ema(c15m, EMA21_P)
        self.atr_15m   = calc_atr(self.rows_15m, ATR14_15M)
        self.rsi_15m   = calc_rsi(c15m, RSI_P)

        self.atr_4h    = calc_atr(self.rows_4h, ATR14_4H)
        self.vsma_4h   = calc_vol_sma(self.rows_4h, SMA20_4H)

        self.ts_1h = [r["ts_ms"] for r in self.rows_1h]


# ─────────────────────── 4H 돌파 창 계산 ─────────────────────────

def compute_windows(sd: SymData, lookback: int, vol_confirm: float, breakout_atr: float) -> list[tuple[int, int]]:
    """4H 돌파 이벤트 → 유효 진입 창 [(window_start_ms, window_end_ms)]."""
    rows_4h  = sd.rows_4h
    atr_4h   = sd.atr_4h
    vsma_4h  = sd.vsma_4h
    n4 = len(rows_4h)
    min_i = max(lookback, ATR14_4H, SMA20_4H)
    windows: list[tuple[int, int]] = []

    for i in range(min_i, n4):
        a = atr_4h[i]
        v = vsma_4h[i]
        if a is None or v is None or a <= 0 or v <= 0:
            continue
        swing_high = max(rows_4h[j]["high"] for j in range(i - lookback, i))
        r4 = rows_4h[i]
        if r4["close"] <= swing_high:
            continue
        if (r4["close"] - swing_high) <= a * breakout_atr:
            continue
        if r4["volume"] <= v * vol_confirm:
            continue
        if r4["close"] <= r4["open"]:
            continue
        ws = r4["ts_ms"] + 4 * 3600 * 1000
        we = ws + FRESH_BARS * 3600 * 1000
        windows.append((ws, we))

    return windows


# ─────────────────────── 심볼 × 조합 백테스트 ───────────────────

def run_combo_on_symbol(
    sd: SymData,
    windows: list[tuple[int, int]],
    touch_pct: float,
    rsi_gate,
    max_hold_bars: int,
) -> list[dict]:
    """15m 바-단위 시뮬레이션. 트레이드 목록 반환."""
    rows15 = sd.rows_15m
    e21    = sd.ema21_15m
    atr15  = sd.atr_15m
    rsi15  = sd.rsi_15m
    rows1h = sd.rows_1h
    e9_1h  = sd.ema9_1h
    e20_1h = sd.ema20_1h
    vwap1h = sd.vwap_1h
    atr1h  = sd.atr_1h
    ts_1h  = sd.ts_1h
    fee    = sd.fee
    n15 = len(rows15)

    # 빠른 창 조회를 위해 정렬 보장 (이미 정렬됨)
    win_starts = [w[0] for w in windows]
    win_ends   = [w[1] for w in windows]

    trades: list[dict] = []
    pos = None
    last_sig_idx = -999
    rsi_triggered = False  # rsi_gate 전용

    for i in range(EMA21_P + ATR14_15M, n15):
        r15 = rows15[i]
        ts_cur = r15["ts_ms"]

        # ── 포지션 관리 ──────────────────────────────────────
        if pos is not None:
            bars_held = i - pos["ei"]
            rh = pos["rh"]
            if r15["high"] > rh:
                pos["rh"] = rh = r15["high"]

            # 트레일링 전환 조건
            if not pos["trail"] and (r15["close"] - pos["ep"]) / pos["ep"] >= 0.015:
                pos["trail"] = True

            # 챈들리어 SL 업데이트
            if pos["trail"]:
                csl = rh - 3.0 * pos["ea"]
                if csl > pos["sl"]:
                    pos["sl"] = csl

            # SL 체크 (low 기준)
            if r15["low"] <= pos["sl"]:
                xp = r15["open"] if r15["open"] <= pos["sl"] else pos["sl"]
                pnl_net = (xp - pos["ep"]) - pos["ep"] * fee
                trades.append({
                    "entry_dt": pos["dt"].strftime("%Y-%m-%d %H:%M"),
                    "exit_dt":  r15["dt"].strftime("%Y-%m-%d %H:%M"),
                    "entry_px": pos["ep"],
                    "exit_px":  xp,
                    "pnl_atr":  pnl_net / pos["ea"],
                    "reason":   "sl",
                })
                pos = None
                last_sig_idx = i
                continue

            # 최대 보유 체크
            if bars_held >= max_hold_bars:
                xp = r15["close"]
                pnl_net = (xp - pos["ep"]) - pos["ep"] * fee
                trades.append({
                    "entry_dt": pos["dt"].strftime("%Y-%m-%d %H:%M"),
                    "exit_dt":  r15["dt"].strftime("%Y-%m-%d %H:%M"),
                    "entry_px": pos["ep"],
                    "exit_px":  xp,
                    "pnl_atr":  pnl_net / pos["ea"],
                    "reason":   "max_hold",
                })
                pos = None
                last_sig_idx = i
                continue

            continue  # 포지션 유지

        # ── 진입 조건 확인 ────────────────────────────────────

        # 조건 A: 활성 4H 돌파 창 확인 (binary search)
        # windows는 정렬됨. ts_cur가 어느 창 안에 있는지 확인
        in_window = False
        idx_w = bisect.bisect_right(win_starts, ts_cur) - 1
        if idx_w >= 0 and ts_cur < win_ends[idx_w]:
            in_window = True
        if not in_window:
            rsi_triggered = False
            continue

        # 지표 유효성
        e21_i = e21[i]
        a15_i = atr15[i]
        if e21_i is None or a15_i is None or a15_i <= 0:
            continue

        # 조건 B: 직전 완성 1H 봉 기준 (completed 1H bar)
        i1h = bisect.bisect_right(ts_1h, ts_cur - 3_600_000) - 1
        if i1h < 0:
            continue
        eg9  = e9_1h[i1h]
        eg20 = e20_1h[i1h]
        vw   = vwap1h[i1h]
        a1h_i = atr1h[i1h]
        if eg9 is None or eg20 is None:
            continue
        if not (eg9 > eg20 and rows1h[i1h]["close"] > vw):
            continue

        # 쿨다운 D
        if i - last_sig_idx <= 5:
            continue

        # RSI 게이트
        if rsi_gate is not None:
            r15_rsi = rsi15[i]
            if r15_rsi is not None and r15_rsi <= rsi_gate:
                rsi_triggered = True
            if not rsi_triggered:
                continue

        # 조건 C: EMA21 터치 + 양봉
        if r15["close"] <= e21_i * touch_pct and r15["close"] > r15["open"]:
            ep = r15["close"]
            ea = a15_i
            sl_15m = ep - 1.5 * ea
            sl_1h  = ep - (a1h_i if a1h_i else ea * 4)
            sl = max(sl_15m, sl_1h)   # 더 타이트한 SL
            pos = {
                "ei": i, "dt": r15["dt"], "ep": ep, "ea": ea,
                "sl": sl, "rh": r15["high"], "trail": False,
            }
            last_sig_idx = i
            if rsi_gate is not None:
                rsi_triggered = False

    return trades


# ─────────────────────── 통계 계산 ───────────────────────────────

def calc_stats(trades: list[dict], period_start: datetime, period_end: datetime) -> dict:
    in_period = [
        t for t in trades
        if period_start <= datetime.strptime(t["entry_dt"], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc) <= period_end
    ]
    n = len(in_period)
    if n == 0:
        return {"n": 0, "ev": 0.0, "sharpe": 0.0, "mdd": 0.0, "wr": 0.0, "daily_rate": 0.0}

    pnls = [t["pnl_atr"] for t in in_period]
    ev   = sum(pnls) / n
    wins = sum(1 for p in pnls if p > 0)
    wr   = wins / n

    std = math.sqrt(sum((p - ev) ** 2 for p in pnls) / n) if n > 1 else 0.0
    sharpe = ev / std if std > 0 else 0.0

    # daily equity curve for MDD
    daily_pnl: dict[str, float] = {}
    for t in in_period:
        d = t["entry_dt"][:10]
        daily_pnl[d] = daily_pnl.get(d, 0.0) + t["pnl_atr"]
    days = sorted(daily_pnl)
    cum, peak, mdd = 0.0, 0.0, 0.0
    for d in days:
        cum += daily_pnl[d]
        if cum > peak:
            peak = cum
        dd = peak - cum
        if dd > mdd:
            mdd = dd

    cal_days = (period_end.date() - period_start.date()).days + 1
    daily_rate = n / cal_days

    return {
        "n": n, "ev": round(ev, 4), "sharpe": round(sharpe, 4),
        "mdd": round(mdd, 4), "wr": round(wr, 4),
        "daily_rate": round(daily_rate, 4),
    }


# ─────────────────────── 메인 ────────────────────────────────────

def main() -> None:
    now    = datetime.now(tz=timezone.utc)
    ts_str = now.strftime("%Y%m%d_%H%M%S")

    print("=" * 72)
    print("BT034 S-01 1차 그리드 스크리닝 (216조합 × 10심볼)")
    print(f"  IS : {IS_START.date()} ~ {IS_END.date()}")
    print(f"  OOS: {OOS_START.date()} ~ {OOS_END.date()}")
    print("=" * 72)

    # ── 심볼별 데이터 적재
    sym_data: dict[str, SymData] = {}
    for sym in SYMBOLS_10:
        print(f"  로드: {sym} ... ", end="", flush=True)
        sd = SymData(sym)
        if not sd.rows_15m or not sd.rows_1h:
            print("SKIP (데이터 없음)")
            continue
        sym_data[sym] = sd
        print(f"15m={len(sd.rows_15m)}봉, 1H={len(sd.rows_1h)}봉, 4H={len(sd.rows_4h)}봉")

    active_syms = list(sym_data.keys())
    print(f"\n  활성 심볼: {active_syms} ({len(active_syms)}개)")
    print(f"  조합: {len(ALL_COMBOS)}개\n")

    # ── 그리드 스크리닝
    combo_results: list[dict] = []

    for ci, combo in enumerate(ALL_COMBOS):
        lookback, vol_confirm, touch_pct, breakout_atr, rsi_gate, max_hold_bars = combo
        combo_id = (f"lb{lookback}_vc{str(vol_confirm).replace('.','')}_"
                    f"tp{str(touch_pct).replace('.','')}_"
                    f"ba{str(breakout_atr).replace('.','')}_"
                    f"rg{rsi_gate}_mh{max_hold_bars}")

        all_trades: list[dict] = []

        for sym, sd in sym_data.items():
            windows = compute_windows(sd, lookback, vol_confirm, breakout_atr)
            trades  = run_combo_on_symbol(sd, windows, touch_pct, rsi_gate, max_hold_bars)
            all_trades.extend(trades)

        is_stats  = calc_stats(all_trades, IS_START,  IS_END)
        oos_stats = calc_stats(all_trades, OOS_START, OOS_END)

        combo_results.append({
            "combo_id":     combo_id,
            "params": {k: v for k, v in zip(GRID_KEYS, combo)},
            "is":  is_stats,
            "oos": oos_stats,
        })

        if (ci + 1) % 20 == 0 or ci == len(ALL_COMBOS) - 1:
            print(f"  [{ci + 1:3d}/216] {combo_id:55s}  "
                  f"OOS N={oos_stats['n']:3d}  EV={oos_stats['ev']:+.3f}  "
                  f"Sharpe={oos_stats['sharpe']:+.3f}")

    # ── 선별: EV > 0 AND OOS Sharpe 상위 20%
    ev_pass  = [r for r in combo_results if r["oos"]["ev"] > 0 and r["oos"]["n"] >= 10]
    top_n    = max(1, round(len(combo_results) * 0.20))   # 상위 20% ≈ 43개
    ranked   = sorted(combo_results, key=lambda r: r["oos"]["sharpe"], reverse=True)
    top20pct = [r for r in ranked[:top_n] if r["oos"]["ev"] > 0]

    # ── 결과 출력
    print("\n" + "=" * 72)
    print(f"[선별 결과] EV>0 통과: {len(ev_pass)}개 / 전체 {len(combo_results)}개")
    print(f"[OOS Sharpe 상위 20%({top_n}개) + EV>0 교집합]: {len(top20pct)}개")
    print()
    print(f"  {'#':>3} {'조합ID':55s} {'OOS N':>6} {'OOS EV':>8} {'OOS Sharpe':>11} {'OOS MDD':>8} {'OOS 건/일':>9}")
    print("  " + "-" * 104)
    for rank, r in enumerate(top20pct, 1):
        o = r["oos"]
        print(f"  {rank:>3} {r['combo_id']:55s} {o['n']:>6} {o['ev']:>+8.4f} "
              f"{o['sharpe']:>+11.4f} {o['mdd']:>8.4f} {o['daily_rate']:>9.4f}")

    # ── JSON 저장
    out = {
        "task": "BT034-S01-Step2",
        "run_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "is_period": f"{IS_START.date()}~{IS_END.date()}",
        "oos_period": f"{OOS_START.date()}~{OOS_END.date()}",
        "symbols": active_syms,
        "total_combos": len(ALL_COMBOS),
        "top20pct_ev_pass": [
            {
                "rank": i + 1,
                "combo_id": r["combo_id"],
                "params": r["params"],
                "is": r["is"],
                "oos": r["oos"],
            }
            for i, r in enumerate(top20pct)
        ],
        "all_combos_ranked": [
            {
                "rank": i + 1,
                "combo_id": r["combo_id"],
                "params": r["params"],
                "is": r["is"],
                "oos": r["oos"],
            }
            for i, r in enumerate(ranked)
        ],
    }

    out_path = RESULT_DIR / f"bt034_s01_step2_{ts_str}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n[저장] {out_path}")


if __name__ == "__main__":
    main()
