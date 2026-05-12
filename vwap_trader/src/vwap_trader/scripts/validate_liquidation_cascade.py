"""
Phase 2 - Step 2: 청산 캐스케이드 이벤트 트레이딩 검증

가설:
  대규모 청산 발생 시 가격이 과도하게 밀린다.
  청산 후 mean reversion (반등)이 발생하며, 이 반등에 양수 EV가 있다.

청산 캐스케이드 식별:
  - OI(미결제약정) 급감 + 가격 급변 = 강제 청산 발생
  - OI 5분 변화율 하위 N% + 가격 변동 상위 N% = 이벤트

검증:
  1. 이벤트 식별 (OI 급감 + 가격 급변)
  2. 이벤트 후 5분~60분 가격 반응 측정
  3. 역방향 반등 크기/확률/t-stat 확인
  4. 수수료 차감 후 EV 계산

데이터: BTC + 주요 ALT, 최근 3개월 파일럿
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from pybit.unified_trading import HTTP

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

# ── 설정 ──────────────────────────────────────────────────
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "SUIUSDT"]
PILOT_DAYS = 90
OI_INTERVAL = "5min"
PRICE_INTERVAL = "5"  # 5분봉 (OI와 맞춤)

CACHE_DIR = Path(__file__).resolve().parents[4] / "data" / "liq_pilot_cache"
RESULTS_DIR = Path(__file__).resolve().parents[4] / "data" / "lag_results"

MAX_PER_CALL = 200
RATE_LIMIT_SLEEP = 0.15

TAKER_FEE_PCT = 0.055  # Bybit taker 수수료 (%)
ROUND_TRIP_FEE = TAKER_FEE_PCT * 2  # 진입 + 청산


# ── 데이터 다운로드 ───────────────────────────────────────
def download_oi_history(symbol: str, days: int) -> list[dict]:
    """Bybit OI 5분 히스토리 다운로드."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"{symbol}_{days}d_oi5m.json"

    if cache_file.exists():
        print(f"  [cache] {symbol} OI -- {cache_file.name}")
        with open(cache_file, "r") as f:
            return json.load(f)

    print(f"  [download] {symbol} OI 5min {days}d...")
    session = HTTP(testnet=False)

    end_ms = int(time.time() * 1000)
    start_ms = end_ms - (days * 24 * 60 * 60 * 1000)
    all_data = []
    cursor_end = end_ms
    calls = 0

    while cursor_end > start_ms:
        try:
            resp = session.get_open_interest(
                category="linear",
                symbol=symbol,
                intervalTime=OI_INTERVAL,
                limit=MAX_PER_CALL,
                endTime=cursor_end,
            )
            if resp.get("retCode") != 0:
                print(f"    API error: {resp}")
                break

            rows = resp["result"]["list"]
            if not rows:
                break

            for row in rows:
                ts = int(row["timestamp"])
                if ts < start_ms:
                    continue
                all_data.append({"ts": ts, "oi": float(row["openInterest"])})

            oldest = min(int(r["timestamp"]) for r in rows)
            cursor_end = oldest - 1
            calls += 1

            if calls % 50 == 0:
                print(f"    {calls} calls, {len(all_data)} rows...")
            time.sleep(RATE_LIMIT_SLEEP)

        except Exception as e:
            if "rate limit" in str(e).lower() or "429" in str(e):
                print("    Rate limit -- waiting 5s")
                time.sleep(5)
            else:
                print(f"    Error: {e}")
                break

    seen = set()
    unique = []
    for d in all_data:
        if d["ts"] not in seen:
            seen.add(d["ts"])
            unique.append(d)
    unique.sort(key=lambda x: x["ts"])

    with open(cache_file, "w") as f:
        json.dump(unique, f)
    print(f"    Done: {len(unique)} rows -> {cache_file.name}")
    return unique


def download_5m_candles(symbol: str, days: int) -> list[dict]:
    """Bybit 5분봉 다운로드."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"{symbol}_{days}d_5m.json"

    if cache_file.exists():
        print(f"  [cache] {symbol} 5m -- {cache_file.name}")
        with open(cache_file, "r") as f:
            return json.load(f)

    print(f"  [download] {symbol} 5m candles {days}d...")
    session = HTTP(testnet=False)

    end_ms = int(time.time() * 1000)
    start_ms = end_ms - (days * 24 * 60 * 60 * 1000)
    all_candles = []
    cursor_end = end_ms
    calls = 0

    while cursor_end > start_ms:
        try:
            resp = session.get_kline(
                category="linear",
                symbol=symbol,
                interval=PRICE_INTERVAL,
                limit=MAX_PER_CALL,
                end=cursor_end,
            )
            if resp.get("retCode") != 0:
                print(f"    API error: {resp}")
                break

            rows = resp["result"]["list"]
            if not rows:
                break

            for row in rows:
                ts = int(row[0])
                if ts < start_ms:
                    continue
                all_candles.append({
                    "ts": ts,
                    "o": float(row[1]),
                    "h": float(row[2]),
                    "l": float(row[3]),
                    "c": float(row[4]),
                    "v": float(row[5]),
                })

            oldest = min(int(r[0]) for r in rows)
            cursor_end = oldest - 1
            calls += 1

            if calls % 50 == 0:
                print(f"    {calls} calls, {len(all_candles)} candles...")
            time.sleep(RATE_LIMIT_SLEEP)

        except Exception as e:
            if "rate limit" in str(e).lower() or "429" in str(e):
                time.sleep(5)
            else:
                print(f"    Error: {e}")
                break

    seen = set()
    unique = []
    for c in all_candles:
        if c["ts"] not in seen:
            seen.add(c["ts"])
            unique.append(c)
    unique.sort(key=lambda x: x["ts"])

    with open(cache_file, "w") as f:
        json.dump(unique, f)
    print(f"    Done: {len(unique)} candles -> {cache_file.name}")
    return unique


# ── 분석 ─────────────────────────────────────────────────
def align_oi_and_price(oi_data: list[dict], candles: list[dict]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """OI와 가격 데이터를 타임스탬프 기준으로 정렬."""
    oi_map = {d["ts"]: d["oi"] for d in oi_data}
    price_map = {c["ts"]: c for c in candles}

    common_ts = sorted(set(oi_map.keys()) & set(price_map.keys()))
    if len(common_ts) < 100:
        return np.array([]), np.array([]), np.array([]), np.array([])

    ts = np.array(common_ts)
    oi = np.array([oi_map[t] for t in common_ts])
    closes = np.array([price_map[t]["c"] for t in common_ts])
    volumes = np.array([price_map[t]["v"] for t in common_ts])
    return ts, oi, closes, volumes


def find_liquidation_events(
    ts: np.ndarray,
    oi: np.ndarray,
    closes: np.ndarray,
    oi_drop_pctile: float = 5.0,
    price_move_pctile: float = 90.0,
    cooldown: int = 6,  # 6 x 5min = 30min
) -> list[dict]:
    """
    청산 캐스케이드 이벤트 식별.

    조건:
      - OI 5분 변화율이 하위 oi_drop_pctile% (급감)
      - 동시에 가격 변동 절대값이 상위 price_move_pctile%
    """
    if len(oi) < 10:
        return []

    # OI 변화율 (%)
    oi_change = np.diff(oi) / oi[:-1] * 100
    # 가격 변화율 (%)
    price_change = np.diff(closes) / closes[:-1] * 100

    # 임계값 계산
    oi_threshold = np.percentile(oi_change, oi_drop_pctile)
    price_threshold = np.percentile(np.abs(price_change), price_move_pctile)

    events = []
    last_idx = -cooldown

    for i in range(len(oi_change)):
        if (i - last_idx) < cooldown:
            continue

        oi_dropped = oi_change[i] < oi_threshold
        price_moved = abs(price_change[i]) > price_threshold

        if oi_dropped and price_moved:
            direction = "long_liq" if price_change[i] < 0 else "short_liq"
            events.append({
                "idx": i + 1,  # closes[i+1] 시점
                "ts": int(ts[i + 1]),
                "oi_change_pct": round(oi_change[i], 4),
                "price_change_pct": round(price_change[i], 4),
                "direction": direction,
                "close": closes[i + 1],
            })
            last_idx = i

    return events


def measure_post_event_response(
    events: list[dict],
    closes: np.ndarray,
    max_bars: int = 12,  # 12 x 5min = 60min
) -> dict:
    """
    청산 이벤트 후 가격 반응 측정.
    역방향 = mean reversion (반등).
    """
    long_liq_responses = []  # 롱청산 (가격 급락) 후 → 반등 기대 (양수)
    short_liq_responses = []  # 숏청산 (가격 급등) 후 → 하락 기대 (양수 = 역방향)

    for ev in events:
        idx = ev["idx"]
        if idx + max_bars >= len(closes):
            continue

        future_returns = []
        for k in range(1, max_bars + 1):
            ret = (closes[idx + k] - closes[idx]) / closes[idx] * 100
            future_returns.append(ret)

        if ev["direction"] == "long_liq":
            # 롱 청산 → 가격 하락 → 반등 기대 → 양수가 좋음
            long_liq_responses.append(future_returns)
        else:
            # 숏 청산 → 가격 상승 → 하락 기대 → 부호 반전하여 양수가 좋음
            short_liq_responses.append([-r for r in future_returns])

    result = {}

    for label, responses in [("long_liq", long_liq_responses), ("short_liq", short_liq_responses)]:
        if not responses:
            continue
        arr = np.array(responses)
        n = len(responses)
        mean = np.mean(arr, axis=0)
        std = np.std(arr, axis=0)
        se = std / np.sqrt(n)
        t_stat = np.where(se > 0, mean / se, 0)

        result[label] = {
            "n": n,
            "mean_response": [round(x, 4) for x in mean],
            "std_response": [round(x, 4) for x in std],
            "t_stat": [round(x, 2) for x in t_stat],
        }

    # 통합 (양방향 합산)
    all_responses = long_liq_responses + short_liq_responses
    if all_responses:
        arr = np.array(all_responses)
        n = len(all_responses)
        mean = np.mean(arr, axis=0)
        std = np.std(arr, axis=0)
        se = std / np.sqrt(n)
        t_stat = np.where(se > 0, mean / se, 0)

        result["combined"] = {
            "n": n,
            "mean_response": [round(x, 4) for x in mean],
            "std_response": [round(x, 4) for x in std],
            "t_stat": [round(x, 2) for x in t_stat],
        }

    return result


# ── 메인 ─────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("Liquidation Cascade Event Trading Validation")
    print("=" * 60)

    # 1. 데이터 다운로드
    print("\n[1/3] Data download (OI 5min + Price 5min)")
    oi_data = {}
    price_data = {}
    for sym in SYMBOLS:
        oi_data[sym] = download_oi_history(sym, PILOT_DAYS)
        price_data[sym] = download_5m_candles(sym, PILOT_DAYS)
        print(f"    {sym}: OI {len(oi_data[sym])} rows, Price {len(price_data[sym])} candles")

    # 2. 이벤트 식별
    print("\n[2/3] Liquidation event detection")
    print("-" * 60)

    all_results = {}

    # 여러 임계값 조합 테스트
    configs = [
        {"oi_pctile": 5.0, "price_pctile": 90.0, "label": "strict (OI<5% + Price>90%)"},
        {"oi_pctile": 10.0, "price_pctile": 85.0, "label": "moderate (OI<10% + Price>85%)"},
        {"oi_pctile": 15.0, "price_pctile": 80.0, "label": "loose (OI<15% + Price>80%)"},
    ]

    for cfg in configs:
        print(f"\n  Config: {cfg['label']}")
        print(f"  {'='*50}")

        cfg_results = {}
        for sym in SYMBOLS:
            ts, oi, closes, volumes = align_oi_and_price(oi_data[sym], price_data[sym])
            if len(ts) < 100:
                print(f"    {sym}: insufficient aligned data ({len(ts)} bars)")
                continue

            events = find_liquidation_events(
                ts, oi, closes,
                oi_drop_pctile=cfg["oi_pctile"],
                price_move_pctile=cfg["price_pctile"],
            )

            if len(events) < 5:
                print(f"    {sym}: {len(events)} events (too few, skip)")
                continue

            response = measure_post_event_response(events, closes, max_bars=12)

            print(f"\n    {sym}: {len(events)} events detected")

            # 방향별 통계
            long_n = sum(1 for e in events if e["direction"] == "long_liq")
            short_n = sum(1 for e in events if e["direction"] == "short_liq")
            print(f"      Long liq (price drop): {long_n}, Short liq (price spike): {short_n}")

            # 통합 결과 출력
            if "combined" in response:
                comb = response["combined"]
                mean = comb["mean_response"]
                tstat = comb["t_stat"]

                print(f"\n      Post-event mean reversion (n={comb['n']}):")
                time_labels = [5, 10, 15, 20, 30, 45, 60]  # 분
                for j, minutes in enumerate(time_labels):
                    bar_idx = (minutes // 5) - 1
                    if bar_idx < len(mean):
                        sig = "***" if abs(tstat[bar_idx]) > 2.58 else "**" if abs(tstat[bar_idx]) > 1.96 else "*" if abs(tstat[bar_idx]) > 1.64 else ""
                        # 수수료 차감
                        net = mean[bar_idx] - ROUND_TRIP_FEE
                        print(f"        {minutes:3d}min: {mean[bar_idx]:+.4f}% (t={tstat[bar_idx]:.2f}) {sig}  | net fee: {net:+.4f}%")

            cfg_results[sym] = {
                "events": len(events),
                "long_liq": long_n,
                "short_liq": short_n,
                "response": response,
            }

        all_results[cfg["label"]] = cfg_results

    # 3. 최종 판정
    print("\n" + "=" * 60)
    print("VERDICT")
    print("=" * 60)

    viable_found = False

    for cfg_label, cfg_data in all_results.items():
        print(f"\n  [{cfg_label}]")
        for sym, sym_data in cfg_data.items():
            if "combined" not in sym_data["response"]:
                continue
            comb = sym_data["response"]["combined"]
            mean = comb["mean_response"]
            tstat = comb["t_stat"]
            n = comb["n"]

            # 수수료 후 양수 + 통계적 유의 구간 찾기
            for bar_idx in range(len(mean)):
                minutes = (bar_idx + 1) * 5
                net = mean[bar_idx] - ROUND_TRIP_FEE
                if net > 0 and abs(tstat[bar_idx]) > 1.96:
                    viable_found = True
                    print(f"    {sym} @ {minutes}min: net +{net:.4f}% (t={tstat[bar_idx]:.2f}, n={n})")

    if viable_found:
        print("\n  >> Viable edge found -> proceed to strategy design")
    else:
        print("\n  >> No viable edge after fees -> consider next candidate")

    # 결과 저장
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    output_file = RESULTS_DIR / "liquidation_cascade_results.json"
    with open(output_file, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\n  Results saved: {output_file}")


if __name__ == "__main__":
    main()
