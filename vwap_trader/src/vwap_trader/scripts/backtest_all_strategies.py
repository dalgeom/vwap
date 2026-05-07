"""
4가지 전략 2025년 백테스트 비교
A. 평균회귀 (BB + RSI + ADX<20)
B. 변동성 돌파 (Donchian + 거래량 + 4H EMA)
C. 펀딩비 캐리 (고펀딩 역방향 진입)
D. 페어 트레이딩 (공적분 페어 z-score)

공통: 초기 $10,000 | 리스크 2% | 실효 레버리지 3x 캡 | 수수료 0.055%x2
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from math import floor, sqrt
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parents[3] / "config" / ".env")

from vwap_trader.infra.bybit_client import BybitClient

# ── 공통 설정 ────────────────────────────────────────────────────
INITIAL_BALANCE = 10_000.0
RISK_PCT        = 0.02
MAX_LEV_REAL    = 3.0
FEE_RATE        = 0.00055 * 2
ATR_PERIOD      = 14
ADX_PERIOD      = 14

START_DT = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
END_DT   = datetime(2025, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
START_MS = int(START_DT.timestamp() * 1000)
END_MS   = int(END_DT.timestamp() * 1000)

COINS = [
    "B3USDT", "IOUSDT", "LABUSDT", "WIFUSDT", "TONUSDT", "DASHUSDT",
    "ICPUSDT", "NEARUSDT", "ZECUSDT", "FILUSDT", "FARTCOINUSDT",
    "ENAUSDT", "TAOUSDT", "ONDOUSDT", "SUIUSDT", "DOGEUSDT",
    "BNBUSDT", "1000PEPEUSDT", "LINKUSDT", "ADAUSDT", "HYPEUSDT",
    "SOLUSDT", "XRPUSDT", "XAUTUSDT",
]

CACHE_DIR  = Path(__file__).parents[3] / "data" / "backtest_cache"
RESULT_DIR = Path(__file__).parents[3] / "data" / "backtest_results"


# ══════════════════════════════════════════════════════════════════
# 공통 지표 함수
# ══════════════════════════════════════════════════════════════════

def _ema(vals: list[float], p: int) -> list[float]:
    if len(vals) < p:
        return []
    k = 2.0 / (p + 1)
    r = [sum(vals[:p]) / p]
    for v in vals[p:]:
        r.append(v * k + r[-1] * (1 - k))
    return r


def _sma(vals: list[float], p: int) -> list[float]:
    if len(vals) < p:
        return []
    r = []
    s = sum(vals[:p])
    r.append(s / p)
    for i in range(p, len(vals)):
        s += vals[i] - vals[i - p]
        r.append(s / p)
    return r


def _wilder(vals: list[float], p: int) -> list[float]:
    if len(vals) < p:
        return []
    r = [sum(vals[:p]) / p]
    for v in vals[p:]:
        r.append(r[-1] * (p - 1) / p + v / p)
    return r


def _rsi(closes: list[float], p: int = 14) -> list[float]:
    if len(closes) < p + 1:
        return []
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(d if d > 0 else 0.0)
        losses.append(-d if d < 0 else 0.0)
    avg_g = _wilder(gains, p)
    avg_l = _wilder(losses, p)
    rsi = []
    for g, l in zip(avg_g, avg_l):
        if l == 0:
            rsi.append(100.0)
        else:
            rs = g / l
            rsi.append(100 - 100 / (1 + rs))
    return rsi


def _bollinger(closes: list[float], p: int = 20, mult: float = 2.5):
    """returns (upper, middle, lower) lists, same length as sma."""
    sma = _sma(closes, p)
    upper, lower = [], []
    for i in range(len(sma)):
        window = closes[i: i + p]
        mean = sma[i]
        std = sqrt(sum((x - mean) ** 2 for x in window) / p) if len(window) == p else 0
        upper.append(mean + mult * std)
        lower.append(mean - mult * std)
    return upper, sma, lower


def _calc_tr_series(rows: list[dict]) -> list[float]:
    trs = []
    for i in range(1, len(rows)):
        h, l, pc = rows[i]["h"], rows[i]["l"], rows[i - 1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return trs


def _calc_atr_val(rows: list[dict], p: int = ATR_PERIOD) -> float | None:
    if len(rows) < p + 1:
        return None
    trs = _calc_tr_series(rows)
    s = _wilder(trs, p)
    return s[-1] if s else None


def _calc_adx_val(rows: list[dict], p: int = ADX_PERIOD) -> float | None:
    if len(rows) < p * 2 + 2:
        return None
    highs  = [r["h"] for r in rows]
    lows   = [r["l"] for r in rows]
    closes = [r["c"] for r in rows]
    trs, pdms, mdms = [], [], []
    for i in range(1, len(rows)):
        tr   = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
        up   = highs[i] - highs[i-1]
        down = lows[i-1] - lows[i]
        trs.append(tr)
        pdms.append(up   if up > down and up > 0   else 0.0)
        mdms.append(down if down > up and down > 0 else 0.0)
    atr_s = _wilder(trs, p)
    pdi_s = _wilder(pdms, p)
    mdi_s = _wilder(mdms, p)
    dxs = []
    for a, pd, md in zip(atr_s, pdi_s, mdi_s):
        if a == 0: continue
        pdi = 100*pd/a; mdi = 100*md/a; den = pdi+mdi
        dxs.append(100*abs(pdi-mdi)/den if den else 0.0)
    adx = _wilder(dxs, p)
    return adx[-1] if adx else None


# ══════════════════════════════════════════════════════════════════
# 데이터 로드
# ══════════════════════════════════════════════════════════════════

def _cache_path(sym: str) -> Path:
    return CACHE_DIR / f"{sym}_2025_15m.json"


def fetch_or_load(client: BybitClient, sym: str) -> list[dict]:
    cp = _cache_path(sym)
    if cp.exists():
        data = json.loads(cp.read_text(encoding="utf-8"))
        print(f"  {sym:<20} cache: {len(data)}")
        return data

    print(f"  {sym:<20} downloading...", end="", flush=True)
    all_rows: list[dict] = []
    current_end = END_MS

    while current_end > START_MS:
        try:
            resp = client._session.get_kline(
                category="linear", symbol=sym, interval="15",
                limit=200, end=current_end,
            )
        except Exception as e:
            print(f" API error: {e}")
            break
        raw = resp.get("result", {}).get("list", [])
        if not raw:
            break
        for row in raw:
            ts_ms = int(row[0])
            if ts_ms < START_MS:
                continue
            all_rows.append({
                "ts": ts_ms,
                "o": float(row[1]), "h": float(row[2]),
                "l": float(row[3]), "c": float(row[4]),
                "v": float(row[5]),
            })
        oldest = min(int(r[0]) for r in raw)
        if oldest <= START_MS:
            break
        current_end = oldest - 1

    seen = set()
    unique = []
    for r in all_rows:
        if r["ts"] not in seen:
            seen.add(r["ts"])
            unique.append(r)
    unique.sort(key=lambda x: x["ts"])
    print(f" {len(unique)}")
    if unique:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps(unique, ensure_ascii=False), encoding="utf-8")
    return unique


def fetch_funding_history(client: BybitClient, sym: str) -> list[dict]:
    """Bybit 펀딩비 이력 다운로드 (캐시)."""
    cp = CACHE_DIR / f"{sym}_2025_funding.json"
    if cp.exists():
        data = json.loads(cp.read_text(encoding="utf-8"))
        print(f"  {sym:<20} funding cache: {len(data)}")
        return data

    print(f"  {sym:<20} funding download...", end="", flush=True)
    all_items: list[dict] = []
    end_ms = END_MS

    while end_ms > START_MS:
        try:
            resp = client._session.get_funding_rate_history(
                category="linear", symbol=sym, limit=200, endTime=end_ms,
            )
        except Exception as e:
            print(f" API error: {e}")
            break
        items = resp.get("result", {}).get("list", [])
        if not items:
            break
        for item in items:
            ts = int(item["fundingRateTimestamp"])
            if ts < START_MS:
                continue
            all_items.append({
                "ts": ts,
                "rate": float(item["fundingRate"]),
            })
        oldest = min(int(i["fundingRateTimestamp"]) for i in items)
        if oldest <= START_MS:
            break
        end_ms = oldest - 1
        time.sleep(0.1)

    seen = set()
    unique = []
    for r in all_items:
        if r["ts"] not in seen:
            seen.add(r["ts"])
            unique.append(r)
    unique.sort(key=lambda x: x["ts"])
    print(f" {len(unique)}")
    if unique:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps(unique, ensure_ascii=False), encoding="utf-8")
    return unique


def build_4h_candles(rows_15m: list[dict]) -> list[dict]:
    """15m -> 4H 합성."""
    result = []
    bucket: list[dict] = []
    for r in rows_15m:
        # 4H 경계: ts % (4*60*60*1000) == 0
        bar_start = r["ts"] - (r["ts"] % (4 * 3600 * 1000))
        if bucket and bucket[0]["ts"] - (bucket[0]["ts"] % (4*3600*1000)) != bar_start:
            result.append({
                "ts": bucket[0]["ts"] - (bucket[0]["ts"] % (4*3600*1000)),
                "o": bucket[0]["o"],
                "h": max(b["h"] for b in bucket),
                "l": min(b["l"] for b in bucket),
                "c": bucket[-1]["c"],
                "v": sum(b["v"] for b in bucket),
            })
            bucket = []
        bucket.append(r)
    if bucket:
        result.append({
            "ts": bucket[0]["ts"] - (bucket[0]["ts"] % (4*3600*1000)),
            "o": bucket[0]["o"],
            "h": max(b["h"] for b in bucket),
            "l": min(b["l"] for b in bucket),
            "c": bucket[-1]["c"],
            "v": sum(b["v"] for b in bucket),
        })
    return result


# ══════════════════════════════════════════════════════════════════
# 공통 거래 실행 헬퍼
# ══════════════════════════════════════════════════════════════════

def calc_pnl(direction: str, entry: float, exit_p: float, balance: float,
             sl_dist: float) -> float:
    """실제 USDT P&L 계산 (리스크 기반 수량)."""
    risk_usdt = balance * RISK_PCT
    qty = risk_usdt / sl_dist
    qty = min(qty, balance * MAX_LEV_REAL / entry)
    if direction == "long":
        pnl = qty * (exit_p - entry)
    else:
        pnl = qty * (entry - exit_p)
    fee = qty * entry * FEE_RATE
    return pnl - fee


# ══════════════════════════════════════════════════════════════════
# 전략 A: 평균회귀 (BB + RSI + ADX<20)
# ══════════════════════════════════════════════════════════════════

def strategy_a(all_data: dict[str, list[dict]]) -> dict:
    """
    진입: ADX<20 + BB(20,2.5) 외부 종가 + RSI>75(숏)/RSI<25(롱)
    TP: SMA(20) 복귀
    SL: 진입봉 고/저 + 0.5 ATR
    타임아웃: 48봉(12h)
    """
    MAX_HOLD = 48
    BB_PERIOD = 20
    BB_MULT = 2.5
    RSI_PERIOD = 14
    LOOKBACK = 120

    balance = INITIAL_BALANCE
    trades = []
    position = None

    # 모든 타임슬롯 수집
    ts_set = set()
    for rows in all_data.values():
        for r in rows:
            ts_set.add(r["ts"])
    all_ts = sorted(ts_set)

    sym_idx = {}
    for sym, rows in all_data.items():
        sym_idx[sym] = {r["ts"]: i for i, r in enumerate(rows)}

    for slot_i, ts_ms in enumerate(all_ts):
        # 청산 체크
        if position:
            sym = position["symbol"]
            rows = all_data[sym]
            idx = sym_idx[sym].get(ts_ms)
            if idx is not None:
                row = rows[idx]
                closed = False
                exit_p = None
                reason = None

                # SL/TP
                if position["dir"] == "long":
                    if row["l"] <= position["sl"]:
                        exit_p, reason = position["sl"], "sl"; closed = True
                    elif row["h"] >= position["tp_price"]:
                        exit_p, reason = position["tp_price"], "tp"; closed = True
                else:
                    if row["h"] >= position["sl"]:
                        exit_p, reason = position["sl"], "sl"; closed = True
                    elif row["l"] <= position["tp_price"]:
                        exit_p, reason = position["tp_price"], "tp"; closed = True

                # 동적 TP 업데이트 (SMA20 추적)
                if not closed and idx >= BB_PERIOD:
                    window_c = [r["c"] for r in rows[idx - BB_PERIOD + 1: idx + 1]]
                    if len(window_c) == BB_PERIOD:
                        sma_now = sum(window_c) / BB_PERIOD
                        position["tp_price"] = sma_now

                # 타임아웃
                if not closed and slot_i - position["entry_slot"] >= MAX_HOLD:
                    exit_p, reason = row["c"], "timeout"; closed = True

                if closed and exit_p is not None:
                    pnl = calc_pnl(position["dir"], position["entry"], exit_p,
                                   position["bal"], position["sl_dist"])
                    balance += pnl
                    trades.append({
                        "symbol": sym, "dir": position["dir"],
                        "entry": position["entry"], "exit": round(exit_p, 6),
                        "reason": reason, "pnl_usdt": round(pnl, 4),
                        "balance": round(balance, 4),
                    })
                    position = None

        # 진입 스캔
        if position is None and balance > 100:
            for sym, rows in all_data.items():
                idx = sym_idx[sym].get(ts_ms)
                if idx is None or idx < LOOKBACK:
                    continue

                window = rows[idx - LOOKBACK: idx + 1]
                closes = [r["c"] for r in window]

                # ADX < 20 (횡보 구간만)
                adx = _calc_adx_val(window)
                if adx is None or adx >= 20:
                    continue

                # BB
                if len(closes) < BB_PERIOD:
                    continue
                upper, mid, lower = _bollinger(closes, BB_PERIOD, BB_MULT)
                if not upper:
                    continue

                cur_close = closes[-1]
                bb_upper = upper[-1]
                bb_lower = lower[-1]
                sma_mid  = mid[-1]

                # RSI
                rsi_vals = _rsi(closes, RSI_PERIOD)
                if not rsi_vals:
                    continue
                cur_rsi = rsi_vals[-1]

                # ATR
                atr = _calc_atr_val(window)
                if atr is None or atr <= 0:
                    continue

                signal = None
                if cur_close < bb_lower and cur_rsi < 25:
                    signal = "long"
                elif cur_close > bb_upper and cur_rsi > 75:
                    signal = "short"

                if not signal:
                    continue

                ep = cur_close
                entry_row = rows[idx]
                if signal == "long":
                    sl = entry_row["l"] - 0.5 * atr
                    tp = sma_mid
                    if tp <= ep:
                        continue  # TP가 진입가보다 낮으면 스킵
                else:
                    sl = entry_row["h"] + 0.5 * atr
                    tp = sma_mid
                    if tp >= ep:
                        continue

                sl_dist = abs(ep - sl)
                if sl_dist / ep < 0.001 or sl_dist == 0:
                    continue

                position = {
                    "symbol": sym, "dir": signal, "entry": ep,
                    "sl": sl, "tp_price": tp, "sl_dist": sl_dist,
                    "bal": balance, "entry_slot": slot_i,
                }
                break

    return {"strategy": "A_MeanReversion", "trades": trades,
            "final_balance": round(balance, 4)}


# ══════════════════════════════════════════════════════════════════
# 전략 B: 변동성 돌파 (Donchian + Volume + 4H EMA)
# ══════════════════════════════════════════════════════════════════

def strategy_b(all_data: dict[str, list[dict]],
               all_4h: dict[str, list[dict]]) -> dict:
    """
    진입: Donchian(20) 돌파 + 거래량 > 20봉 평균 x1.5 + 4H EMA50 방향 일치
    SL: 2.0 ATR
    TP: 3.0 ATR (trailing chandelier)
    타임아웃: 32봉(8h)
    """
    MAX_HOLD = 32
    DON_PERIOD = 20
    VOL_MULT = 1.5
    SL_MULT = 2.0
    TP_MULT = 3.0
    LOOKBACK = 120

    balance = INITIAL_BALANCE
    trades = []
    position = None

    ts_set = set()
    for rows in all_data.values():
        for r in rows:
            ts_set.add(r["ts"])
    all_ts = sorted(ts_set)

    sym_idx = {}
    for sym, rows in all_data.items():
        sym_idx[sym] = {r["ts"]: i for i, r in enumerate(rows)}

    # 4H ts -> idx
    sym_4h_idx = {}
    for sym, rows in all_4h.items():
        sym_4h_idx[sym] = {r["ts"]: i for i, r in enumerate(rows)}

    for slot_i, ts_ms in enumerate(all_ts):
        if position:
            sym = position["symbol"]
            rows = all_data[sym]
            idx = sym_idx[sym].get(ts_ms)
            if idx is not None:
                row = rows[idx]
                closed = False
                exit_p = None
                reason = None

                if position["dir"] == "long":
                    if row["l"] <= position["sl"]:
                        exit_p, reason = position["sl"], "sl"; closed = True
                    elif row["h"] >= position["tp"]:
                        exit_p, reason = position["tp"], "tp"; closed = True
                    else:
                        # Chandelier trailing: SL = highest_high - 3*ATR
                        position["best"] = max(position["best"], row["h"])
                        new_sl = position["best"] - position["trail_atr"]
                        if new_sl > position["sl"]:
                            position["sl"] = new_sl
                else:
                    if row["h"] >= position["sl"]:
                        exit_p, reason = position["sl"], "sl"; closed = True
                    elif row["l"] <= position["tp"]:
                        exit_p, reason = position["tp"], "tp"; closed = True
                    else:
                        position["best"] = min(position["best"], row["l"])
                        new_sl = position["best"] + position["trail_atr"]
                        if new_sl < position["sl"]:
                            position["sl"] = new_sl

                if not closed and slot_i - position["entry_slot"] >= MAX_HOLD:
                    exit_p, reason = row["c"], "timeout"; closed = True

                if closed and exit_p is not None:
                    pnl = calc_pnl(position["dir"], position["entry"], exit_p,
                                   position["bal"], position["sl_dist"])
                    balance += pnl
                    trades.append({
                        "symbol": sym, "dir": position["dir"],
                        "entry": position["entry"], "exit": round(exit_p, 6),
                        "reason": reason, "pnl_usdt": round(pnl, 4),
                        "balance": round(balance, 4),
                    })
                    position = None

        if position is None and balance > 100:
            for sym, rows in all_data.items():
                idx = sym_idx[sym].get(ts_ms)
                if idx is None or idx < LOOKBACK:
                    continue

                window = rows[idx - LOOKBACK: idx + 1]

                # 4H EMA50 방향
                if sym not in all_4h:
                    continue
                bar_4h_ts = ts_ms - (ts_ms % (4 * 3600 * 1000))
                h4_idx = sym_4h_idx[sym].get(bar_4h_ts)
                if h4_idx is None or h4_idx < 50:
                    continue
                h4_closes = [r["c"] for r in all_4h[sym][max(0, h4_idx-60): h4_idx+1]]
                ema50_4h = _ema(h4_closes, 50)
                if not ema50_4h:
                    continue
                htf_bullish = h4_closes[-1] > ema50_4h[-1]

                # Donchian channel
                if idx < DON_PERIOD:
                    continue
                don_window = rows[idx - DON_PERIOD: idx]  # 이전 20봉 (현재 제외)
                don_high = max(r["h"] for r in don_window)
                don_low  = min(r["l"] for r in don_window)

                cur = rows[idx]
                cur_close = cur["c"]

                # Volume filter
                vol_window = [r["v"] for r in rows[idx - DON_PERIOD: idx]]
                avg_vol = sum(vol_window) / len(vol_window) if vol_window else 0
                if cur["v"] < avg_vol * VOL_MULT:
                    continue

                # ATR
                atr = _calc_atr_val(window)
                if atr is None or atr <= 0:
                    continue

                signal = None
                if cur_close > don_high and htf_bullish:
                    signal = "long"
                elif cur_close < don_low and not htf_bullish:
                    signal = "short"

                if not signal:
                    continue

                ep = cur_close
                if signal == "long":
                    sl = ep - SL_MULT * atr
                    tp = ep + TP_MULT * atr
                else:
                    sl = ep + SL_MULT * atr
                    tp = ep - TP_MULT * atr

                sl_dist = abs(ep - sl)
                if sl_dist / ep < 0.001:
                    continue

                position = {
                    "symbol": sym, "dir": signal, "entry": ep,
                    "sl": sl, "tp": tp, "sl_dist": sl_dist,
                    "bal": balance, "entry_slot": slot_i,
                    "best": ep, "trail_atr": TP_MULT * atr,
                }
                break

    return {"strategy": "B_VolBreakout", "trades": trades,
            "final_balance": round(balance, 4)}


# ══════════════════════════════════════════════════════════════════
# 전략 C: 펀딩비 캐리 (선물만, 헤지 없음)
# ══════════════════════════════════════════════════════════════════

def strategy_c(all_data: dict[str, list[dict]],
               all_funding: dict[str, list[dict]]) -> dict:
    """
    펀딩 > +0.01%: 숏 진입 (펀딩 수령)
    펀딩 < -0.01%: 롱 진입 (펀딩 수령)
    포지션 보유 중 펀딩 수령, 다음 펀딩까지 보유
    SL: 1.5 ATR (변동성 방어)
    TP: 없음 (펀딩 수령 후 청산)
    """
    FUNDING_THRESH = 0.0001  # 0.01%
    SL_MULT = 1.5
    HOLD_BARS = 32  # 8h (펀딩 사이클)

    balance = INITIAL_BALANCE
    trades = []
    position = None

    # 펀딩 타임스탬프 -> {symbol: rate} 맵
    funding_map: dict[int, dict[str, float]] = {}
    for sym, fdata in all_funding.items():
        for f in fdata:
            ts = f["ts"]
            if ts not in funding_map:
                funding_map[ts] = {}
            funding_map[ts][sym] = f["rate"]

    funding_times = sorted(funding_map.keys())

    sym_idx = {}
    for sym, rows in all_data.items():
        sym_idx[sym] = {r["ts"]: i for i, r in enumerate(rows)}

    # 펀딩 시점마다 체크
    for ft in funding_times:
        dt = datetime.fromtimestamp(ft / 1000, tz=timezone.utc)

        # 포지션 있으면: 펀딩 수령 + 청산 판단
        if position:
            sym = position["symbol"]
            # 가장 가까운 15m 캔들 찾기
            rows = all_data.get(sym, [])
            idx_map = sym_idx.get(sym, {})
            # ft에 가장 가까운 ts 찾기
            nearest_idx = None
            for check_ts in range(ft, ft + 900_000, 900_000):  # 15분 내
                if check_ts in idx_map:
                    nearest_idx = idx_map[check_ts]
                    break
            if nearest_idx is None:
                # 1봉 전/후로 확대 검색
                for check_ts in range(ft - 900_000, ft + 1_800_000, 900_000):
                    if check_ts in idx_map:
                        nearest_idx = idx_map[check_ts]
                        break

            if nearest_idx is not None:
                cur_price = rows[nearest_idx]["c"]

                # 펀딩 수령 계산
                funding_rates = funding_map.get(ft, {})
                sym_rate = funding_rates.get(sym, 0)
                qty = min(position["bal"] * RISK_PCT / position["sl_dist"],
                          position["bal"] * MAX_LEV_REAL / position["entry"])
                if position["dir"] == "short" and sym_rate > 0:
                    # 숏 포지션 + 양의 펀딩 = 수령
                    funding_income = qty * position["entry"] * sym_rate
                    position["funding_total"] += funding_income
                elif position["dir"] == "long" and sym_rate < 0:
                    # 롱 포지션 + 음의 펀딩 = 수령
                    funding_income = qty * position["entry"] * abs(sym_rate)
                    position["funding_total"] += funding_income
                else:
                    # 반대편 = 지불
                    funding_cost = qty * position["entry"] * abs(sym_rate)
                    position["funding_total"] -= funding_cost

                # SL 체크
                sl_hit = False
                if position["dir"] == "long" and cur_price <= position["sl"]:
                    sl_hit = True
                elif position["dir"] == "short" and cur_price >= position["sl"]:
                    sl_hit = True

                position["hold_count"] += 1

                # 청산: SL 또는 1사이클(8h) 후
                if sl_hit or position["hold_count"] >= 1:
                    exit_p = position["sl"] if sl_hit else cur_price
                    reason = "sl" if sl_hit else "funding_exit"
                    pnl = calc_pnl(position["dir"], position["entry"], exit_p,
                                   position["bal"], position["sl_dist"])
                    pnl += position["funding_total"]
                    balance += pnl
                    trades.append({
                        "symbol": sym, "dir": position["dir"],
                        "entry": position["entry"], "exit": round(exit_p, 6),
                        "reason": reason, "pnl_usdt": round(pnl, 4),
                        "funding": round(position["funding_total"], 4),
                        "balance": round(balance, 4),
                    })
                    position = None

        # 진입 스캔 (포지션 없을 때)
        if position is None and balance > 100:
            # 가장 높은 |펀딩|인 코인 찾기
            rates = funding_map.get(ft, {})
            if not rates:
                continue

            candidates = sorted(rates.items(), key=lambda x: abs(x[1]), reverse=True)
            for sym, rate in candidates:
                if abs(rate) < FUNDING_THRESH:
                    continue
                if sym not in all_data:
                    continue

                rows = all_data[sym]
                idx_map = sym_idx.get(sym, {})
                nearest_idx = None
                for check_ts in range(ft, ft + 900_000, 900_000):
                    if check_ts in idx_map:
                        nearest_idx = idx_map[check_ts]
                        break
                if nearest_idx is None:
                    for check_ts in range(ft - 900_000, ft + 1_800_000, 900_000):
                        if check_ts in idx_map:
                            nearest_idx = idx_map[check_ts]
                            break
                if nearest_idx is None or nearest_idx < 30:
                    continue

                window = rows[max(0, nearest_idx - 30): nearest_idx + 1]
                atr = _calc_atr_val(window)
                if atr is None or atr <= 0:
                    continue

                ep = rows[nearest_idx]["c"]
                # 양의 펀딩 = 숏 (펀딩 수령), 음의 펀딩 = 롱
                signal = "short" if rate > 0 else "long"
                if signal == "long":
                    sl = ep - SL_MULT * atr
                else:
                    sl = ep + SL_MULT * atr

                sl_dist = abs(ep - sl)
                if sl_dist / ep < 0.001:
                    continue

                position = {
                    "symbol": sym, "dir": signal, "entry": ep,
                    "sl": sl, "sl_dist": sl_dist,
                    "bal": balance, "hold_count": 0,
                    "funding_total": 0.0,
                }
                break

    return {"strategy": "C_FundingCarry", "trades": trades,
            "final_balance": round(balance, 4)}


# ══════════════════════════════════════════════════════════════════
# 전략 D: 페어 트레이딩 (공적분 기반)
# ══════════════════════════════════════════════════════════════════

def _find_cointegrated_pairs(all_data: dict[str, list[dict]],
                              window: int = 500) -> list[tuple[str, str, float]]:
    """상관관계 + 스프레드 정상성으로 페어 후보 선별."""
    syms = list(all_data.keys())
    pairs = []
    for i in range(len(syms)):
        for j in range(i + 1, len(syms)):
            a_rows = all_data[syms[i]]
            b_rows = all_data[syms[j]]
            if len(a_rows) < window or len(b_rows) < window:
                continue

            # 동일 타임스탬프 매칭
            b_map = {r["ts"]: r["c"] for r in b_rows}
            matched_a, matched_b = [], []
            for r in a_rows[-window:]:
                if r["ts"] in b_map:
                    matched_a.append(r["c"])
                    matched_b.append(b_map[r["ts"]])

            if len(matched_a) < window * 0.8:
                continue

            # 상관관계
            n = len(matched_a)
            ma = sum(matched_a) / n
            mb = sum(matched_b) / n
            cov = sum((a - ma) * (b - mb) for a, b in zip(matched_a, matched_b)) / n
            sa = sqrt(sum((a - ma) ** 2 for a in matched_a) / n)
            sb = sqrt(sum((b - mb) ** 2 for b in matched_b) / n)
            if sa == 0 or sb == 0:
                continue
            corr = cov / (sa * sb)
            if abs(corr) < 0.7:
                continue

            # 스프레드의 mean reversion 속도 (간이 ADF)
            # log(A/B) 스프레드
            spreads = []
            for a, b in zip(matched_a, matched_b):
                if b > 0 and a > 0:
                    spreads.append(a / b)
            if len(spreads) < 100:
                continue

            # half-life 추정
            mean_s = sum(spreads) / len(spreads)
            diffs = [spreads[i] - spreads[i-1] for i in range(1, len(spreads))]
            lags  = [spreads[i-1] - mean_s for i in range(1, len(spreads))]
            num = sum(d * l for d, l in zip(diffs, lags))
            den = sum(l * l for l in lags)
            if den == 0:
                continue
            beta = num / den
            if beta >= 0:
                continue  # mean reverting이 아님
            half_life = -0.693 / beta  # ln(2) / |beta|
            if half_life < 5 or half_life > 200:
                continue  # 너무 빠르거나 너무 느림

            pairs.append((syms[i], syms[j], corr, half_life))

    pairs.sort(key=lambda x: x[3])  # half-life 짧은 순
    return [(a, b, hl) for a, b, _, hl in pairs[:5]]


def strategy_d(all_data: dict[str, list[dict]]) -> dict:
    """
    공적분 페어의 z-score 기반 진입/청산.
    z > 2: 숏 스프레드 (A 숏 + B 롱)
    z < -2: 롱 스프레드 (A 롱 + B 숏)
    청산: z가 0 교차
    SL: |z| > 3.5
    """
    Z_ENTRY = 2.0
    Z_EXIT  = 0.0
    Z_STOP  = 3.5
    LOOKBACK = 100
    MAX_HOLD = 192  # 48h

    balance = INITIAL_BALANCE
    trades = []
    position = None

    # 페어 찾기 (첫 2000봉 기준)
    print("  pair cointegration scan...", end="", flush=True)
    pairs = _find_cointegrated_pairs(all_data, 2000)
    if not pairs:
        print(" no pairs found")
        return {"strategy": "D_PairTrading", "trades": [], "final_balance": balance}
    print(f" {len(pairs)} pairs")
    for a, b, hl in pairs:
        print(f"    {a} / {b}  half-life={hl:.1f}")

    # 첫번째 페어로 거래
    ts_set = set()
    for rows in all_data.values():
        for r in rows:
            ts_set.add(r["ts"])
    all_ts = sorted(ts_set)

    for pair_a, pair_b, _ in pairs[:3]:  # 상위 3개 페어 순회
        if pair_a not in all_data or pair_b not in all_data:
            continue

        a_map = {r["ts"]: r["c"] for r in all_data[pair_a]}
        b_map = {r["ts"]: r["c"] for r in all_data[pair_b]}

        common_ts = sorted(set(a_map.keys()) & set(b_map.keys()))
        if len(common_ts) < LOOKBACK + 100:
            continue

        # 스프레드 시계열
        spreads_all = [(ts, a_map[ts] / b_map[ts]) for ts in common_ts]

        for si in range(LOOKBACK, len(spreads_all)):
            ts_ms = spreads_all[si][0]
            cur_spread = spreads_all[si][1]

            window_s = [s for _, s in spreads_all[si - LOOKBACK: si]]
            mean_s = sum(window_s) / len(window_s)
            std_s = sqrt(sum((s - mean_s) ** 2 for s in window_s) / len(window_s))
            if std_s == 0:
                continue
            z = (cur_spread - mean_s) / std_s

            # 청산 체크
            if position and position["pair"] == (pair_a, pair_b):
                close_reason = None
                if position["z_dir"] == "short_spread" and z <= Z_EXIT:
                    close_reason = "z_exit"
                elif position["z_dir"] == "long_spread" and z >= Z_EXIT:
                    close_reason = "z_exit"
                elif abs(z) > Z_STOP:
                    close_reason = "z_stop"
                elif si - position["entry_si"] >= MAX_HOLD:
                    close_reason = "timeout"

                if close_reason:
                    a_exit = a_map.get(ts_ms, position["a_entry"])
                    b_exit = b_map.get(ts_ms, position["b_entry"])

                    # A leg PnL
                    if position["a_dir"] == "long":
                        a_pnl_pct = (a_exit - position["a_entry"]) / position["a_entry"]
                    else:
                        a_pnl_pct = (position["a_entry"] - a_exit) / position["a_entry"]

                    # B leg PnL
                    if position["b_dir"] == "long":
                        b_pnl_pct = (b_exit - position["b_entry"]) / position["b_entry"]
                    else:
                        b_pnl_pct = (position["b_entry"] - b_exit) / position["b_entry"]

                    # 각 레그 절반 리스크
                    half_risk = position["bal"] * RISK_PCT / 2
                    lev = min(MAX_LEV_REAL, 2.0)  # 페어는 보수적
                    a_notional = half_risk * lev / 0.02  # ~리스크 역산
                    b_notional = half_risk * lev / 0.02
                    total_fee = (a_notional + b_notional) * FEE_RATE
                    total_pnl = (a_pnl_pct * a_notional + b_pnl_pct * b_notional) - total_fee

                    balance += total_pnl
                    trades.append({
                        "pair": f"{pair_a}/{pair_b}",
                        "z_dir": position["z_dir"],
                        "z_entry": round(position["z_val"], 2),
                        "z_exit": round(z, 2),
                        "reason": close_reason,
                        "pnl_usdt": round(total_pnl, 4),
                        "balance": round(balance, 4),
                    })
                    position = None

            # 진입
            if position is None and balance > 100:
                if z > Z_ENTRY:
                    # short spread: A 숏 + B 롱
                    position = {
                        "pair": (pair_a, pair_b), "z_dir": "short_spread",
                        "a_dir": "short", "b_dir": "long",
                        "a_entry": a_map[ts_ms], "b_entry": b_map[ts_ms],
                        "z_val": z, "entry_si": si, "bal": balance,
                    }
                elif z < -Z_ENTRY:
                    # long spread: A 롱 + B 숏
                    position = {
                        "pair": (pair_a, pair_b), "z_dir": "long_spread",
                        "a_dir": "long", "b_dir": "short",
                        "a_entry": a_map[ts_ms], "b_entry": b_map[ts_ms],
                        "z_val": z, "entry_si": si, "bal": balance,
                    }

    return {"strategy": "D_PairTrading", "trades": trades,
            "final_balance": round(balance, 4)}


# ══════════════════════════════════════════════════════════════════
# 결과 출력
# ══════════════════════════════════════════════════════════════════

def print_result(result: dict) -> None:
    name   = result["strategy"]
    trades = result.get("trades", [])
    final  = result.get("final_balance", INITIAL_BALANCE)
    pnl    = final - INITIAL_BALANCE
    pnl_pct = pnl / INITIAL_BALANCE * 100

    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")

    if not trades:
        print("  No trades")
        return

    n = len(trades)

    # 청산 사유 집계
    reasons: dict[str, int] = {}
    for t in trades:
        r = t.get("reason", "unknown")
        reasons[r] = reasons.get(r, 0) + 1

    wins = sum(1 for t in trades if t["pnl_usdt"] > 0)
    total_pnl_sum = sum(t["pnl_usdt"] for t in trades)

    # 드로다운
    bal_curve = [INITIAL_BALANCE] + [t["balance"] for t in trades]
    peak = bal_curve[0]
    max_dd = 0.0
    for b in bal_curve:
        peak = max(peak, b)
        dd = (peak - b) / peak if peak > 0 else 0
        max_dd = max(max_dd, dd)

    # 연속 손실
    streak = cur = 0
    for t in trades:
        if t["pnl_usdt"] < 0:
            cur += 1; streak = max(streak, cur)
        else:
            cur = 0

    print(f"  Initial:       ${INITIAL_BALANCE:>10,.2f}")
    print(f"  Final:         ${final:>10,.2f}")
    print(f"  P&L:           ${pnl:>+10,.2f}  ({pnl_pct:>+.2f}%)")
    print(f"  Trades:        {n:>6}")
    print(f"  Win rate:      {wins/n:.1%}  ({wins}/{n})")
    print(f"  Avg P&L/trade: ${total_pnl_sum/n:>+.2f}")
    print(f"  Max drawdown:  {max_dd:.1%}")
    print(f"  Max loss streak: {streak}")
    print(f"  Trades/day:    {n/365:.2f}")
    print(f"  Exit reasons:")
    for r, cnt in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"    {r:<20} {cnt:>5}  ({cnt/n:.1%})")


# ══════════════════════════════════════════════════════════════════
# 메인
# ══════════════════════════════════════════════════════════════════

def main():
    client = BybitClient(
        api_key=os.getenv("BYBIT_API_KEY", ""),
        api_secret=os.getenv("BYBIT_API_SECRET", ""),
    )
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    RESULT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. 15m OHLCV 로드
    print(f"=== 15m OHLCV data ({len(COINS)} coins) ===")
    all_data: dict[str, list[dict]] = {}
    for sym in COINS:
        rows = fetch_or_load(client, sym)
        if len(rows) >= 200:
            all_data[sym] = rows
        else:
            print(f"  {sym:<20} insufficient ({len(rows)}) - skip")

    if not all_data:
        print("No data available")
        return

    # 2. 4H 합성 (전략 B용)
    print(f"\n=== Building 4H candles ===")
    all_4h: dict[str, list[dict]] = {}
    for sym, rows in all_data.items():
        all_4h[sym] = build_4h_candles(rows)
        print(f"  {sym:<20} {len(all_4h[sym])} bars")

    # 3. 펀딩비 이력 (전략 C용)
    print(f"\n=== Funding rate history ===")
    all_funding: dict[str, list[dict]] = {}
    for sym in list(all_data.keys()):
        fdata = fetch_funding_history(client, sym)
        if fdata:
            all_funding[sym] = fdata

    # 4. 전략 실행
    print(f"\n{'#'*60}")
    print(f"  Running 4 strategies on {len(all_data)} coins")
    print(f"  Period: 2025-01-01 ~ 2025-12-31")
    print(f"{'#'*60}")

    print("\n>>> Strategy A: Mean Reversion ...")
    result_a = strategy_a(all_data)
    print_result(result_a)

    print("\n>>> Strategy B: Volatility Breakout ...")
    result_b = strategy_b(all_data, all_4h)
    print_result(result_b)

    print("\n>>> Strategy C: Funding Carry ...")
    result_c = strategy_c(all_data, all_funding)
    print_result(result_c)

    print("\n>>> Strategy D: Pair Trading ...")
    result_d = strategy_d(all_data)
    print_result(result_d)

    # 5. 비교 요약
    results = [result_a, result_b, result_c, result_d]
    print(f"\n{'='*70}")
    print(f"  COMPARISON SUMMARY")
    print(f"{'='*70}")
    print(f"  {'Strategy':<25} {'Final $':>10} {'P&L %':>8} {'Trades':>7} {'Win%':>6} {'MaxDD':>7}")
    print(f"  {'-'*63}")
    for r in results:
        t = r.get("trades", [])
        f = r.get("final_balance", INITIAL_BALANCE)
        pnl_p = (f - INITIAL_BALANCE) / INITIAL_BALANCE * 100
        n = len(t)
        wins = sum(1 for x in t if x.get("pnl_usdt", 0) > 0) if t else 0
        wr = wins / n if n else 0

        bal_c = [INITIAL_BALANCE] + [x["balance"] for x in t]
        pk = bal_c[0]; mdd = 0
        for b in bal_c:
            pk = max(pk, b)
            mdd = max(mdd, (pk - b) / pk if pk > 0 else 0)

        print(f"  {r['strategy']:<25} ${f:>9,.2f} {pnl_p:>+7.2f}% {n:>7} {wr:>5.1%} {mdd:>6.1%}")

    # 저장
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = RESULT_DIR / f"backtest_4strategies_{ts}.json"
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
