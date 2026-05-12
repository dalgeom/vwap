"""
Phase 2 — Step 1: BTC→ALT 지연 추종 현상 검증

목적: "BTC가 움직이면 ALT가 늦게 따라가는가?" 를 데이터로 확인.

검증 방법:
  1. 교차상관 분석 (cross-correlation)
     - BTC 1분 수익률 vs ALT 1분 수익률의 시차별 상관계수
     - lag 0 ~ lag 30분까지 측정
     - lag > 0에서 상관이 더 높으면 → 지연 현상 존재

  2. 이벤트 스터디 (event study)
     - BTC가 5분 내 0.5% 이상 급등한 이벤트 식별
     - 각 이벤트에서 ALT의 평균 반응 곡선 (0~30분) 측정
     - 지연이 보이면 → 트레이딩 가능 여부 판단

데이터: Bybit 1분봉, 최근 3개월 파일럿
코인: BTCUSDT + 주요 ALT 5개 (ETHUSDT, SOLUSDT, XRPUSDT, DOGEUSDT, SUIUSDT)
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from pybit.unified_trading import HTTP

# Windows cp949 encoding fix
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

# ── 설정 ──────────────────────────────────────────────────
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "SUIUSDT"]
INTERVAL = "1"  # 1분봉
PILOT_DAYS = 90  # 최근 3개월

CACHE_DIR = Path(__file__).resolve().parents[4] / "data" / "lag_pilot_cache"
RESULTS_DIR = Path(__file__).resolve().parents[4] / "data" / "lag_results"

MAX_PER_CALL = 200
RATE_LIMIT_SLEEP = 0.15  # Bybit rate limit 여유


# ── 데이터 다운로드 ───────────────────────────────────────
def download_1m_candles(symbol: str, days: int) -> list[dict]:
    """Bybit에서 1분봉 다운로드. 캐시 있으면 스킵."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"{symbol}_{days}d_1m.json"

    if cache_file.exists():
        print(f"  [캐시] {symbol} — {cache_file.name}")
        with open(cache_file, "r") as f:
            return json.load(f)

    print(f"  [다운로드] {symbol} 1분봉 {days}일...")
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
                interval=INTERVAL,
                limit=MAX_PER_CALL,
                end=cursor_end,
            )
            if resp.get("retCode") != 0:
                print(f"    API 에러: {resp}")
                break

            rows = resp["result"]["list"]
            if not rows:
                break

            for row in rows:
                ts_ms = int(row[0])
                if ts_ms < start_ms:
                    continue
                all_candles.append({
                    "ts": ts_ms,
                    "o": float(row[1]),
                    "h": float(row[2]),
                    "l": float(row[3]),
                    "c": float(row[4]),
                    "v": float(row[5]),
                })

            oldest_ts = min(int(r[0]) for r in rows)
            cursor_end = oldest_ts - 1
            calls += 1

            if calls % 50 == 0:
                print(f"    {calls} 호출 완료, 봉 {len(all_candles)}개...")
            time.sleep(RATE_LIMIT_SLEEP)

        except Exception as e:
            err = str(e).lower()
            if "rate limit" in err or "429" in err:
                print("    Rate limit — 5초 대기")
                time.sleep(5)
            else:
                print(f"    에러: {e}")
                break

    # 중복 제거 + 시간순 정렬
    seen = set()
    unique = []
    for c in all_candles:
        if c["ts"] not in seen:
            seen.add(c["ts"])
            unique.append(c)
    unique.sort(key=lambda x: x["ts"])

    with open(cache_file, "w") as f:
        json.dump(unique, f)
    print(f"    완료: {len(unique)}봉 저장 → {cache_file.name}")
    return unique


def candles_to_returns(candles: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    """캔들 → (timestamps_ms, 1분 수익률 %) 변환."""
    closes = np.array([c["c"] for c in candles])
    ts = np.array([c["ts"] for c in candles])
    returns = np.diff(closes) / closes[:-1] * 100  # %
    return ts[1:], returns


# ── 분석 1: 교차상관 ─────────────────────────────────────
def cross_correlation(btc_ret: np.ndarray, alt_ret: np.ndarray, max_lag: int = 30) -> dict:
    """
    BTC 수익률 vs ALT 수익률의 시차별 상관계수.
    lag=k: corr(BTC[t], ALT[t+k]) — BTC가 k분 전에 움직이고 ALT가 지금 반응
    양수 lag에서 상관이 높으면 → ALT가 BTC를 따라감 (지연)
    """
    n = min(len(btc_ret), len(alt_ret))
    btc = btc_ret[:n]
    alt = alt_ret[:n]

    results = {}
    for lag in range(-5, max_lag + 1):
        if lag >= 0:
            b = btc[:n - lag] if lag > 0 else btc
            a = alt[lag:] if lag > 0 else alt
        else:
            b = btc[-lag:]
            a = alt[:n + lag]

        if len(b) < 100:
            continue
        corr = np.corrcoef(b, a)[0, 1]
        results[lag] = round(corr, 6)

    return results


# ── 분석 2: 이벤트 스터디 ────────────────────────────────
def find_btc_surge_events(
    btc_ts: np.ndarray,
    btc_ret: np.ndarray,
    window: int = 5,
    threshold: float = 0.5,
    cooldown: int = 30,
) -> list[int]:
    """
    BTC가 window분 내에 threshold% 이상 움직인 이벤트의 인덱스.
    cooldown분 이내 중복 이벤트 제거.
    양방향 (급등 + 급락) 모두 감지.
    """
    rolling_ret = np.convolve(btc_ret, np.ones(window), mode="valid")
    events = []
    last_event_idx = -cooldown

    for i in range(len(rolling_ret)):
        if abs(rolling_ret[i]) >= threshold and (i - last_event_idx) >= cooldown:
            direction = "up" if rolling_ret[i] > 0 else "down"
            events.append((i + window - 1, direction, rolling_ret[i]))
            last_event_idx = i

    return events


def measure_alt_response(
    btc_events: list,
    alt_ret: np.ndarray,
    response_window: int = 30,
) -> dict:
    """
    BTC 급등 이벤트 후 ALT의 평균 누적 수익률 곡선 측정.
    """
    up_responses = []
    down_responses = []

    for idx, direction, magnitude in btc_events:
        if idx + response_window >= len(alt_ret):
            continue
        cumret = np.cumsum(alt_ret[idx:idx + response_window])
        if direction == "up":
            up_responses.append(cumret)
        else:
            down_responses.append(-cumret)  # 하락 이벤트는 부호 반전하여 통합

    result = {}
    if up_responses:
        up_arr = np.array(up_responses)
        result["up_events"] = len(up_responses)
        result["up_mean_response"] = [round(x, 4) for x in np.mean(up_arr, axis=0)]
        result["up_std_response"] = [round(x, 4) for x in np.std(up_arr, axis=0)]

    if down_responses:
        down_arr = np.array(down_responses)
        result["down_events"] = len(down_responses)
        result["down_mean_response"] = [round(x, 4) for x in np.mean(down_arr, axis=0)]

    if up_responses or down_responses:
        all_arr = np.array(up_responses + down_responses)
        result["total_events"] = len(up_responses) + len(down_responses)
        result["all_mean_response"] = [round(x, 4) for x in np.mean(all_arr, axis=0)]
        result["all_std_response"] = [round(x, 4) for x in np.std(all_arr, axis=0)]

    return result


# ── 메인 ─────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("BTC→ALT 지연 추종 현상 검증 (Phase 2 - Step 1)")
    print("=" * 60)

    # 1. 데이터 다운로드
    print("\n[1/3] 데이터 다운로드")
    raw_data = {}
    for sym in SYMBOLS:
        raw_data[sym] = download_1m_candles(sym, PILOT_DAYS)
        print(f"    {sym}: {len(raw_data[sym])}봉")

    # 수익률 변환
    returns = {}
    timestamps = {}
    for sym in SYMBOLS:
        ts, ret = candles_to_returns(raw_data[sym])
        timestamps[sym] = ts
        returns[sym] = ret

    btc_ret = returns["BTCUSDT"]
    alts = [s for s in SYMBOLS if s != "BTCUSDT"]

    # 2. 교차상관 분석
    print("\n[2/3] 교차상관 분석 (lag 0 ~ 30분)")
    print("-" * 60)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    xcorr_results = {}

    for alt in alts:
        xcorr = cross_correlation(btc_ret, returns[alt], max_lag=30)
        xcorr_results[alt] = xcorr

        # 핵심 지표 추출
        lag0 = xcorr.get(0, 0)
        peak_lag = max(range(1, 31), key=lambda k: xcorr.get(k, 0))
        peak_corr = xcorr.get(peak_lag, 0)
        improvement = peak_corr - lag0

        print(f"\n  {alt}:")
        print(f"    lag=0 상관: {lag0:.4f}")
        print(f"    최대 상관 lag: {peak_lag}분 (corr={peak_corr:.4f})")
        print(f"    개선폭: {improvement:+.4f}")

        if improvement > 0.005:
            print(f"    → 지연 추종 신호 있음 (lag {peak_lag}분)")
        elif improvement > 0:
            print(f"    → 매우 약한 지연 (노이즈 가능성)")
        else:
            print(f"    → 지연 없음 (동시 반응 또는 선행)")

        # 상세 출력
        key_lags = [0, 1, 2, 3, 5, 10, 15, 20, 30]
        vals = [f"lag{k}={xcorr.get(k, 0):.4f}" for k in key_lags]
        print(f"    상세: {', '.join(vals)}")

    # 3. 이벤트 스터디
    print("\n[3/3] 이벤트 스터디 — BTC 급등/급락 후 ALT 반응")
    print("-" * 60)

    # 다양한 임계값 테스트
    thresholds = [0.3, 0.5, 0.8, 1.0]
    event_results = {}

    for thresh in thresholds:
        events = find_btc_surge_events(
            timestamps["BTCUSDT"], btc_ret,
            window=5, threshold=thresh, cooldown=30
        )
        print(f"\n  BTC 5분 {thresh}%+ 이벤트: {len(events)}건")

        if len(events) < 10:
            print(f"    → 이벤트 부족, 스킵")
            continue

        event_results[str(thresh)] = {"event_count": len(events), "alts": {}}

        for alt in alts:
            response = measure_alt_response(events, returns[alt], response_window=30)
            event_results[str(thresh)]["alts"][alt] = response

            if "all_mean_response" in response:
                resp = response["all_mean_response"]
                n = response["total_events"]
                std = response["all_std_response"]

                print(f"\n    {alt} (n={n}):")
                # 핵심 시점 출력: 1분, 3분, 5분, 10분, 15분, 30분 후
                for t in [0, 2, 4, 9, 14, 29]:
                    if t < len(resp):
                        se = std[t] / np.sqrt(n) if n > 0 else 0
                        t_stat = resp[t] / se if se > 0 else 0
                        sig = "***" if abs(t_stat) > 2.58 else "**" if abs(t_stat) > 1.96 else "*" if abs(t_stat) > 1.64 else ""
                        print(f"      {t+1:2d}분 후: {resp[t]:+.4f}% (t={t_stat:.2f}) {sig}")

    # 결과 저장
    output = {
        "pilot_days": PILOT_DAYS,
        "symbols": SYMBOLS,
        "btc_candle_count": len(raw_data["BTCUSDT"]),
        "cross_correlation": xcorr_results,
        "event_study": event_results,
    }
    output_file = RESULTS_DIR / "lag_validation_results.json"
    with open(output_file, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n결과 저장: {output_file}")

    # ── 최종 판정 ─────────────────────────────────────────
    print("\n" + "=" * 60)
    print("최종 판정")
    print("=" * 60)

    lag_evidence = False
    for alt in alts:
        xcorr = xcorr_results[alt]
        lag0 = xcorr.get(0, 0)
        max_lag_corr = max(xcorr.get(k, 0) for k in range(1, 16))
        if max_lag_corr > lag0 + 0.01:
            lag_evidence = True
            print(f"  {alt}: 지연 추종 증거 있음 (lag0={lag0:.4f}, max_lag={max_lag_corr:.4f})")

    event_evidence = False
    if "0.5" in event_results:
        for alt in alts:
            alt_data = event_results["0.5"]["alts"].get(alt, {})
            resp = alt_data.get("all_mean_response", [])
            if len(resp) >= 10 and resp[4] > 0.05:  # 5분 후 0.05% 이상 추종
                event_evidence = True
                print(f"  {alt}: 이벤트 스터디 양수 반응 (5분 후 {resp[4]:+.4f}%)")

    print()
    if lag_evidence and event_evidence:
        print("  ✓ 두 검증 모두 통과 → Phase 2 계속 진행 (전략 설계)")
    elif lag_evidence or event_evidence:
        print("  △ 부분적 증거 → 추가 분석 필요 (데이터 확대 또는 조건 조정)")
    else:
        print("  ✗ 증거 없음 → 이 전략은 폐기, 다른 엣지 탐색")


if __name__ == "__main__":
    main()
