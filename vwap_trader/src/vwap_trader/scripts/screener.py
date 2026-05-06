"""
매일 실행: 변동성 상위 코인 중 추세 지속성 스코어링 → 오늘 거래할 코인 선정

스코어 구성 (100점 만점):
  1. 최근 7일 EMA 크로스 적중률  (0~50점) — 신호가 실제로 방향 맞췄는지
  2. ADX 상승 추세              (0~30점) — 추세가 강해지고 있는지
  3. 최근 가격 직선성 (R²)      (0~20점) — 방향이 깔끔한지, 흔들리는지

결과: selected_coins.json 저장 → main.py가 읽어서 오늘 거래할 심볼 결정
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

from vwap_trader.infra.bybit_client import BybitClient

# ── 설정 ─────────────────────────────────────────────────────
INTERVAL       = "15"         # 15분봉
RECENT_CANDLES = 672          # 최근 7일 (7×24×4)
SCAN_LIMIT     = 30           # 변동성 상위 N개 스캔
SELECT_TOP     = 5            # 최종 선정 개수
MIN_VOL_USDT   = 50_000_000
ADX_PERIOD     = 14
ATR_PERIOD     = 14
MIN_SIGNALS    = 3            # 최소 신호 수 (신호 적으면 통계 부족)
BLACKLIST      = {"BTCUSDT", "ETHUSDT"}

DATA_DIR   = Path(__file__).parents[3] / "data"
OUTPUT     = DATA_DIR / "selected_coins.json"


# ── 지표 계산 ────────────────────────────────────────────────

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


def _calc_atr(candles, p: int = ATR_PERIOD) -> float | None:
    if len(candles) < p + 1:
        return None
    trs = [
        max(candles[i].high - candles[i].low,
            abs(candles[i].high - candles[i-1].close),
            abs(candles[i].low  - candles[i-1].close))
        for i in range(1, len(candles))
    ]
    s = _wilder(trs, p)
    return s[-1] if s else None


def _calc_adx_series(candles, p: int = ADX_PERIOD) -> list[float]:
    """ADX 시계열 반환 (최근 N개)."""
    if len(candles) < p * 2 + 2:
        return []
    highs  = [c.high  for c in candles]
    lows   = [c.low   for c in candles]
    closes = [c.close for c in candles]
    trs, pdms, mdms = [], [], []
    for i in range(1, len(candles)):
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i-1]),
                 abs(lows[i]  - closes[i-1]))
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
        if a == 0:
            continue
        pdi = 100 * pd / a
        mdi = 100 * md / a
        den = pdi + mdi
        dxs.append(100 * abs(pdi - mdi) / den if den else 0.0)
    return _wilder(dxs, p)


def _r_squared(values: list[float]) -> float:
    """최근 가격의 직선성 (0~1). 1에 가까울수록 깔끔한 추세."""
    n = len(values)
    if n < 3:
        return 0.0
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(values) / n
    ss_tot = sum((y - my) ** 2 for y in values)
    ss_res = sum((y - (my + (sum((x - mx)*(y - my) for x, y in zip(xs, values)) /
                             max(sum((x - mx)**2 for x in xs), 1e-10)) * (x - mx)))
                  ** 2 for x, y in zip(xs, values))
    return max(0.0, 1.0 - ss_res / ss_tot) if ss_tot > 0 else 0.0


# ── 심볼 스크리닝 ────────────────────────────────────────────

def get_volatile_symbols(client: BybitClient) -> list[tuple[str, float]]:
    try:
        resp = client._session.get_tickers(category="linear")
    except Exception as e:
        print(f"ticker 조회 실패: {e}")
        return []
    results = []
    for t in resp.get("result", {}).get("list", []):
        sym = t.get("symbol", "")
        if not sym.endswith("USDT") or sym in BLACKLIST:
            continue
        try:
            high24 = float(t.get("highPrice24h", 0) or 0)
            low24  = float(t.get("lowPrice24h",  0) or 0)
            price  = float(t.get("lastPrice",    0) or 0)
            vol    = float(t.get("turnover24h",  0) or 0)
        except (ValueError, TypeError):
            continue
        if price <= 0 or low24 <= 0 or vol < MIN_VOL_USDT:
            continue
        results.append((sym, (high24 - low24) / price * 100))
    results.sort(key=lambda x: x[1], reverse=True)
    return results[:SCAN_LIMIT]


# ── 코인 스코어 계산 ─────────────────────────────────────────

def score_coin(sym: str, candles) -> dict:
    """최근 7일 데이터로 추세 지속성 점수 계산."""
    if len(candles) < 100:
        return {"symbol": sym, "score": 0, "reason": "data_insufficient"}

    closes = [c.close for c in candles]
    min_i  = 50

    # ── 점수 1: 최근 EMA 크로스 적중률 (0~50점) ──────────────
    ema9  = _ema(closes, 9)
    ema21 = _ema(closes, 21)
    atr   = _calc_atr(candles)

    if len(ema9) < 2 or len(ema21) < 2 or atr is None or atr <= 0:
        return {"symbol": sym, "score": 0, "reason": "indicator_fail"}

    signals = []
    for i in range(min_i, len(candles) - 1):
        e9  = _ema(closes[:i+1], 9)
        e21 = _ema(closes[:i+1], 21)
        if len(e9) < 2 or len(e21) < 2:
            continue
        if e9[-2] <= e21[-2] and e9[-1] > e21[-1]:
            direction = "long"
        elif e9[-2] >= e21[-2] and e9[-1] < e21[-1]:
            direction = "short"
        else:
            continue

        ep = candles[i].close
        tp = ep + atr * (1.0 if direction == "long" else -1.0)
        sl = ep - atr * (0.5 if direction == "long" else -0.5)
        hit = None
        for j in range(i + 1, min(i + 32 + 1, len(candles))):
            c = candles[j]
            if direction == "long":
                if c.low <= sl:  hit = "sl"; break
                if c.high >= tp: hit = "tp"; break
            else:
                if c.high >= sl: hit = "sl"; break
                if c.low <= tp:  hit = "tp"; break
        if hit:
            signals.append(hit)

    if len(signals) < MIN_SIGNALS:
        win_rate  = 0.0
        score_ema = 0
    else:
        win_rate  = signals.count("tp") / len(signals)
        score_ema = int(win_rate * 50)          # 최대 50점

    # ── 점수 2: ADX 상승 추세 (0~30점) ───────────────────────
    adx_series = _calc_adx_series(candles)
    if len(adx_series) >= 10:
        recent_adx = adx_series[-10:]
        adx_slope  = (recent_adx[-1] - recent_adx[0]) / max(recent_adx[0], 1e-6)
        adx_now    = adx_series[-1]
        # ADX 현재값 20 이상이면서 상승 중일수록 높은 점수
        score_adx  = min(30, max(0, int((adx_now / 40) * 15 + (adx_slope * 50) * 15)))
    else:
        score_adx  = 0

    # ── 점수 3: 가격 직선성 R² (0~20점) ──────────────────────
    # 최근 48봉(12h) 기준
    recent_prices = closes[-48:]
    r2            = _r_squared(recent_prices)
    score_r2      = int(r2 * 20)

    # 적중률 33.3% 미만이면 선정 불가 (손익분기 미달)
    MIN_WIN_RATE = 1 / 3
    disqualified = len(signals) >= MIN_SIGNALS and win_rate < MIN_WIN_RATE

    total = 0 if disqualified else score_ema + score_adx + score_r2

    return {
        "symbol":        sym,
        "score":         total,
        "disqualified":  disqualified,
        "score_ema":    score_ema,
        "score_adx":    score_adx,
        "score_r2":     score_r2,
        "win_rate":     round(win_rate, 3),
        "signals":      len(signals),
        "adx_now":      round(adx_series[-1], 1) if adx_series else 0,
        "r_squared":    round(r2, 3),
    }


# ── 메인 ─────────────────────────────────────────────────────

def run(client: BybitClient | None = None) -> list[str]:
    if client is None:
        client = BybitClient(
            api_key=os.getenv("BYBIT_API_KEY", ""),
            api_secret=os.getenv("BYBIT_API_SECRET", ""),
        )

    print("변동성 상위 심볼 스캔 중...")
    candidates = get_volatile_symbols(client)
    print(f"후보: {len(candidates)}개\n")

    scores = []
    for sym, atr_pct in candidates:
        candles = client.get_candles(sym, INTERVAL, RECENT_CANDLES)
        candles = candles[:-1]
        result  = score_coin(sym, candles)
        scores.append((atr_pct, result))
        s = result
        s_ema = s.get("score_ema", 0)
        s_adx = s.get("score_adx", 0)
        s_r2  = s.get("score_r2",  0)
        disq = " [탈락:적중률미달]" if s.get("disqualified") else ""
        print(
            f"  {sym:<18}"
            f" ATR%{atr_pct:>5.1f}"
            f"  score{s['score']:>4}/100"
            f"  (EMA{s_ema:>2} ADX{s_adx:>2} R2{s_r2:>2})"
            f"  hit{s.get('win_rate', 0):.0%}"
            f"  ADX{s.get('adx_now', 0):>5.1f}"
            f"  R2={s.get('r_squared', 0):.2f}"
            f"  sig={s.get('signals', 0)}"
            f"{disq}"
        )

    # 점수 기준 정렬
    scores.sort(key=lambda x: x[1]["score"], reverse=True)
    selected = [r["symbol"] for _, r in scores[:SELECT_TOP] if r["score"] > 0]

    print(f"\n{'='*60}")
    print(f"  오늘 선정된 코인 (상위 {SELECT_TOP})")
    print(f"{'='*60}")
    for _, r in scores[:SELECT_TOP]:
        if r["score"] > 0:
            print(f"  {r['symbol']:<18} 점수 {r['score']}/100  적중률 {r.get('win_rate', 0):.0%}")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    output = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "selected": selected,
        "scores": [r for _, r in scores],
    }
    OUTPUT.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n저장: {OUTPUT}")
    return selected


if __name__ == "__main__":
    run()
