"""
C 전략 보수화 버전 백테스트 (2023~2025)

보수화 조건:
- 임계값: |펀딩| > 0.03% (극단만)
- 동시 최대 5포지션 (분산)
- Limit order 가정: 마찰 0.20% 라운드트립 (maker 0.02%x2 + 슬리피지 0.05%x2 + 스프레드 0.03%x2)
- 코인 유니버스: 유동성 상위 10개만
- 거래당 리스크: 0.5% (기존 2%에서 축소)
- 일일 손실 -2% 시 24h 정지
- SL: 1.0 ATR (기존 1.5에서 축소)
- 동일 방향 4개 이상 집중 시 사이즈 50% 감소
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parents[3] / "config" / ".env")

# ── 보수화 설정 ──────────────────────────────────────────────────
INITIAL_BALANCE = 10_000.0
RISK_PCT        = 0.005       # 0.5% per trade (기존 2% → 0.5%)
MAX_LEV_REAL    = 3.0
FRICTION_RATE   = 0.0020      # 0.20% 라운드트립 (limit order 가정)
ATR_PERIOD      = 14
FUNDING_THRESH  = 0.0003      # 0.03% (기존 0.01% → 0.03%)
SL_MULT         = 1.0         # 1.0 ATR (기존 1.5 → 1.0)
MAX_POSITIONS   = 5           # 동시 최대 5포지션
MAX_SAME_DIR    = 3           # 같은 방향 3개 초과 시 사이즈 50% 감소
DAILY_LOSS_LIMIT = -0.02      # 일일 -2% 시 24h 정지

# 유동성 상위 10개 (24h 거래대금 기준, 소형 알트 제외)
LIQUID_COINS = [
    "DOGEUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "LINKUSDT",
    "ADAUSDT", "NEARUSDT", "SUIUSDT", "1000PEPEUSDT", "FILUSDT",
]

CACHE_DIR  = Path(__file__).parents[3] / "data" / "backtest_cache"
RESULT_DIR = Path(__file__).parents[3] / "data" / "backtest_results"


# ── 지표 ─────────────────────────────────────────────────────────

def _wilder(vals: list[float], p: int) -> list[float]:
    if len(vals) < p:
        return []
    r = [sum(vals[:p]) / p]
    for v in vals[p:]:
        r.append(r[-1] * (p - 1) / p + v / p)
    return r


def _calc_atr_val(rows: list[dict], p: int = ATR_PERIOD) -> float | None:
    if len(rows) < p + 1:
        return None
    trs = [max(rows[i]["h"]-rows[i]["l"],
               abs(rows[i]["h"]-rows[i-1]["c"]),
               abs(rows[i]["l"]-rows[i-1]["c"]))
           for i in range(1, len(rows))]
    s = _wilder(trs, p)
    return s[-1] if s else None


# ── 데이터 로드 ──────────────────────────────────────────────────

def load_data(year: int) -> tuple[dict[str, list[dict]], dict[str, list[dict]]]:
    all_data = {}
    all_funding = {}
    for sym in LIQUID_COINS:
        # 15m candles
        cp = CACHE_DIR / f"{sym}_{year}_15m.json"
        if cp.exists():
            rows = json.loads(cp.read_text(encoding="utf-8"))
            if len(rows) >= 200:
                all_data[sym] = rows
        # funding
        fp = CACHE_DIR / f"{sym}_{year}_funding.json"
        if fp.exists():
            fdata = json.loads(fp.read_text(encoding="utf-8"))
            if fdata:
                all_funding[sym] = fdata
    return all_data, all_funding


# ── 전략 실행 ────────────────────────────────────────────────────

def run_conservative(all_data: dict[str, list[dict]],
                     all_funding: dict[str, list[dict]]) -> dict:
    balance = INITIAL_BALANCE
    trades = []
    positions: list[dict] = []  # 동시 포지션 리스트

    # 펀딩 맵
    funding_map: dict[int, dict[str, float]] = {}
    for sym, fdata in all_funding.items():
        for f in fdata:
            if f["ts"] not in funding_map:
                funding_map[f["ts"]] = {}
            funding_map[f["ts"]][sym] = f["rate"]

    funding_times = sorted(funding_map.keys())

    sym_idx = {}
    for sym, rows in all_data.items():
        sym_idx[sym] = {r["ts"]: i for i, r in enumerate(rows)}

    # 일일 손실 추적
    daily_pnl = 0.0
    current_day = ""
    paused_until = 0  # timestamp until which trading is paused

    total_funding_pnl = 0.0
    total_price_pnl = 0.0
    total_fees = 0.0

    for ft in funding_times:
        dt = datetime.fromtimestamp(ft / 1000, tz=timezone.utc)
        day_str = dt.strftime("%Y-%m-%d")

        # 일일 리셋
        if day_str != current_day:
            current_day = day_str
            daily_pnl = 0.0

        # 일일 정지 체크
        if ft < paused_until:
            # 포지션 청산만 처리
            pass

        # ── 기존 포지션 청산 ──────────────────────────────────────
        closed_indices = []
        for pi, pos in enumerate(positions):
            sym = pos["symbol"]
            rows = all_data.get(sym, [])
            idx_map = sym_idx.get(sym, {})

            nearest_idx = None
            for check_ts in range(ft, ft + 900_000, 900_000):
                if check_ts in idx_map:
                    nearest_idx = idx_map[check_ts]; break
            if nearest_idx is None:
                for check_ts in range(ft - 900_000, ft + 1_800_000, 900_000):
                    if check_ts in idx_map:
                        nearest_idx = idx_map[check_ts]; break
            if nearest_idx is None:
                continue

            cur_price = rows[nearest_idx]["c"]
            rates = funding_map.get(ft, {})
            sym_rate = rates.get(sym, 0)

            # 펀딩 계산
            qty = pos["qty"]
            notional = qty * pos["entry"]

            if pos["dir"] == "short" and sym_rate > 0:
                f_income = notional * sym_rate
            elif pos["dir"] == "long" and sym_rate < 0:
                f_income = notional * abs(sym_rate)
            else:
                f_income = -notional * abs(sym_rate)
            pos["funding_total"] += f_income

            # SL 체크
            sl_hit = False
            if pos["dir"] == "long" and cur_price <= pos["sl"]:
                sl_hit = True
            elif pos["dir"] == "short" and cur_price >= pos["sl"]:
                sl_hit = True

            pos["hold_count"] += 1

            # 청산: SL 또는 1사이클(8h) 후
            if sl_hit or pos["hold_count"] >= 1:
                exit_p = pos["sl"] if sl_hit else cur_price
                reason = "sl" if sl_hit else "funding_exit"

                if pos["dir"] == "long":
                    p_pnl = qty * (exit_p - pos["entry"])
                else:
                    p_pnl = qty * (pos["entry"] - exit_p)
                fee = notional * FRICTION_RATE

                net_pnl = p_pnl + pos["funding_total"] - fee
                balance += net_pnl
                daily_pnl += net_pnl / INITIAL_BALANCE

                total_funding_pnl += pos["funding_total"]
                total_price_pnl += p_pnl
                total_fees += fee

                trades.append({
                    "symbol": sym, "dir": pos["dir"],
                    "entry": pos["entry"], "exit": round(exit_p, 6),
                    "reason": reason,
                    "pnl_usdt": round(net_pnl, 4),
                    "funding_pnl": round(pos["funding_total"], 4),
                    "price_pnl": round(p_pnl, 4),
                    "fee": round(fee, 4),
                    "balance": round(balance, 4),
                })
                closed_indices.append(pi)

        # 인덱스 역순 삭제
        for pi in sorted(closed_indices, reverse=True):
            positions.pop(pi)

        # 일일 손실 한도 체크
        if daily_pnl <= DAILY_LOSS_LIMIT:
            paused_until = ft + 24 * 3600 * 1000  # 24h 정지
            continue

        # 정지 중이면 진입 스킵
        if ft < paused_until:
            continue

        # ── 진입 스캔 ────────────────────────────────────────────
        if len(positions) >= MAX_POSITIONS or balance < 100:
            continue

        rates = funding_map.get(ft, {})
        if not rates:
            continue

        # 현재 방향 집계
        long_count = sum(1 for p in positions if p["dir"] == "long")
        short_count = sum(1 for p in positions if p["dir"] == "short")

        # |펀딩| > 0.03% 코인 중 상위 선택 (이미 포지션 있는 코인 제외)
        held_symbols = {p["symbol"] for p in positions}
        candidates = [(sym, rate) for sym, rate in rates.items()
                      if abs(rate) >= FUNDING_THRESH
                      and sym in all_data
                      and sym not in held_symbols]
        candidates.sort(key=lambda x: abs(x[1]), reverse=True)

        slots_available = MAX_POSITIONS - len(positions)

        for sym, rate in candidates[:slots_available]:
            rows = all_data[sym]
            idx_map = sym_idx.get(sym, {})
            nearest_idx = None
            for check_ts in range(ft, ft + 900_000, 900_000):
                if check_ts in idx_map:
                    nearest_idx = idx_map[check_ts]; break
            if nearest_idx is None:
                for check_ts in range(ft - 900_000, ft + 1_800_000, 900_000):
                    if check_ts in idx_map:
                        nearest_idx = idx_map[check_ts]; break
            if nearest_idx is None or nearest_idx < 30:
                continue

            window = rows[max(0, nearest_idx - 30): nearest_idx + 1]
            atr = _calc_atr_val(window)
            if atr is None or atr <= 0:
                continue

            ep = rows[nearest_idx]["c"]
            signal = "short" if rate > 0 else "long"

            # 동일 방향 집중도 체크
            size_mult = 1.0
            if signal == "long" and long_count >= MAX_SAME_DIR:
                size_mult = 0.5
            elif signal == "short" and short_count >= MAX_SAME_DIR:
                size_mult = 0.5

            if signal == "long":
                sl = ep - SL_MULT * atr
            else:
                sl = ep + SL_MULT * atr

            sl_dist = abs(ep - sl)
            if sl_dist / ep < 0.001:
                continue

            # 수량 계산
            risk_usdt = balance * RISK_PCT * size_mult
            qty = min(risk_usdt / sl_dist, balance * MAX_LEV_REAL / ep / MAX_POSITIONS)

            if qty * ep < 50:  # 최소 노션
                continue

            positions.append({
                "symbol": sym, "dir": signal, "entry": ep,
                "sl": sl, "sl_dist": sl_dist, "qty": qty,
                "hold_count": 0, "funding_total": 0.0,
            })

            if signal == "long":
                long_count += 1
            else:
                short_count += 1

    # 미청산 포지션 강제 청산
    for pos in positions:
        sym = pos["symbol"]
        rows = all_data.get(sym, [])
        if rows:
            exit_p = rows[-1]["c"]
            qty = pos["qty"]
            if pos["dir"] == "long":
                p_pnl = qty * (exit_p - pos["entry"])
            else:
                p_pnl = qty * (pos["entry"] - exit_p)
            fee = qty * pos["entry"] * FRICTION_RATE
            net_pnl = p_pnl + pos["funding_total"] - fee
            balance += net_pnl
            total_funding_pnl += pos["funding_total"]
            total_price_pnl += p_pnl
            total_fees += fee
            trades.append({
                "symbol": sym, "dir": pos["dir"],
                "entry": pos["entry"], "exit": round(exit_p, 6),
                "reason": "end_of_data",
                "pnl_usdt": round(net_pnl, 4),
                "funding_pnl": round(pos["funding_total"], 4),
                "price_pnl": round(p_pnl, 4),
                "fee": round(fee, 4),
                "balance": round(balance, 4),
            })

    return {
        "trades": trades,
        "final_balance": round(balance, 4),
        "total_funding_pnl": round(total_funding_pnl, 2),
        "total_price_pnl": round(total_price_pnl, 2),
        "total_fees": round(total_fees, 2),
    }


# ── 결과 출력 ────────────────────────────────────────────────────

def print_result(year: int, result: dict):
    trades = result["trades"]
    final = result["final_balance"]
    pnl = final - INITIAL_BALANCE
    pnl_pct = pnl / INITIAL_BALANCE * 100
    n = len(trades)
    if n == 0:
        print(f"\n  {year}: No trades")
        return

    f_pnl = result["total_funding_pnl"]
    p_pnl = result["total_price_pnl"]
    fees  = result["total_fees"]

    wins = sum(1 for t in trades if t["pnl_usdt"] > 0)
    sl_count = sum(1 for t in trades if t["reason"] == "sl")
    exit_count = sum(1 for t in trades if t["reason"] == "funding_exit")

    # DD
    bal_curve = [INITIAL_BALANCE] + [t["balance"] for t in trades]
    peak = bal_curve[0]; max_dd = 0
    for b in bal_curve:
        peak = max(peak, b)
        max_dd = max(max_dd, (peak - b) / peak if peak > 0 else 0)

    # 연속 손실
    streak = cur = 0
    for t in trades:
        if t["pnl_usdt"] < 0: cur += 1; streak = max(streak, cur)
        else: cur = 0

    total_income = f_pnl + p_pnl
    f_ratio = f_pnl / total_income * 100 if total_income != 0 else 0

    # 일일 거래수
    days = 365

    print(f"""
{'='*60}
  {year}년 C 전략 [보수화]
{'='*60}
  최종 잔고:     ${final:>12,.2f}
  총 손익:       ${pnl:>+12,.2f}  ({pnl_pct:>+.1f}%)
  거래 수:       {n:>6}건  (승률 {wins/n:.1%}, {n/days:.1f}건/일)
  Max DD:        {max_dd:.1%}
  연속 손실:     {streak}회

  --- PnL 분해 ---
  펀딩:          ${f_pnl:>+10,.2f}  ({f_ratio:.1f}%)
  가격:          ${p_pnl:>+10,.2f}  ({100-f_ratio:.1f}%)
  마찰비용:      ${-fees:>10,.2f}

  --- 청산 ---
  SL:            {sl_count}건 ({sl_count/n:.1%})
  정상(8h):      {exit_count}건 ({exit_count/n:.1%})
{'='*60}""")


# ── 메인 ─────────────────────────────────────────────────────────

def main():
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    all_results = {}

    for year in [2023, 2024, 2025]:
        print(f"\n>>> {year}년 로드 중...")
        all_data, all_funding = load_data(year)
        if not all_data or not all_funding:
            print(f"  데이터 부족 - skip")
            continue
        print(f"  코인: {list(all_data.keys())}")
        print(f"  펀딩: {list(all_funding.keys())}")

        result = run_conservative(all_data, all_funding)
        print_result(year, result)
        all_results[year] = result

    # 비교
    print(f"\n{'#'*60}")
    print(f"  보수화 C 전략 3년 비교")
    print(f"  조건: 임계값 0.03% | 5포지션 | 0.5% 리스크 | 마찰 0.20%")
    print(f"{'#'*60}")
    print(f"  {'년도':<6} {'최종잔고':>12} {'수익률':>8} {'거래':>6} {'승률':>6} {'DD':>6} {'거래/일':>7}")
    print(f"  {'-'*58}")
    for year, r in all_results.items():
        t = r["trades"]
        f = r["final_balance"]
        n = len(t)
        if n == 0:
            continue
        wins = sum(1 for x in t if x["pnl_usdt"] > 0)
        pnl_pct = (f - INITIAL_BALANCE) / INITIAL_BALANCE * 100
        bal_c = [INITIAL_BALANCE] + [x["balance"] for x in t]
        pk = bal_c[0]; mdd = 0
        for b in bal_c:
            pk = max(pk, b); mdd = max(mdd, (pk-b)/pk if pk > 0 else 0)
        print(f"  {year:<6} ${f:>11,.2f} {pnl_pct:>+7.1f}% {n:>6} {wins/n:>5.1%} {mdd:>5.1%} {n/365:>6.2f}")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = RESULT_DIR / f"backtest_c_conservative_{ts}.json"
    serializable = {str(k): v for k, v in all_results.items()}
    out.write_text(json.dumps(serializable, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
