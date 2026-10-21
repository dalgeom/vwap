"""공개 1h봉으로 봇 청산규칙(SL 3.0ATR·BE 1.5 후 트레일 2.0ATR·48봉 만기)을 재현하는 공용 시뮬 엔진.

출처: analysis_flip_mirror.py(2026-10-18 메인 PC 작성)의 bars/sim — 실제 숏 재현 건별 상관 0.96 검증.
관측소(regime_engine)·H-13/H-14 판정·반사실 분석이 전부 이 하나를 쓴다(엔진 분기 = 숫자 불일치 사고).
⚠봉 내 고저 순서는 보수적(손절 우선). 수수료·슬리피지 미반영 — 두 방향의 '비교'에만 쓸 것.
"""
import datetime
import time


def fetch_bars(cli, sym: str, ts_iso: str, limit: int = 56, sleep: float = 0.1):
    """진입 시각부터 limit개의 1h봉 [(ts, o, h, l, c)] — 실패 시 None."""
    t0 = datetime.datetime.fromisoformat(ts_iso)
    start = int(t0.timestamp() * 1000)
    try:
        r = cli.get_kline(category="linear", symbol=sym, interval="60",
                          start=start, limit=limit)
        ks = sorted(r["result"]["list"], key=lambda k: int(k[0]))
        out = [(int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]))
               for k in ks]
    except Exception:
        out = None
    time.sleep(sleep)
    return out


def sim_pct(dirn: int, entry: float, atr: float, bars,
            sl_mult: float = 3.0, be_mult: float = 1.5, tr_mult: float = 2.0) -> float:
    """dirn: +1 롱 / -1 숏. 반환: 노셔널 대비 수익률(%)."""
    sl = entry - dirn * sl_mult * atr
    be = False
    best = entry
    for _, _, hi, lo, cl in bars:
        if (dirn == 1 and lo <= sl) or (dirn == -1 and hi >= sl):
            return dirn * (sl - entry) / entry * 100
        fav = hi if dirn == 1 else lo
        best = max(best, fav) if dirn == 1 else min(best, fav)
        if not be and dirn * (best - entry) >= be_mult * atr:
            be = True
        if be:
            ns = best - dirn * tr_mult * atr
            ns = max(entry, ns) if dirn == 1 else min(entry, ns)
            sl = max(sl, ns) if dirn == 1 else min(sl, ns)
    return dirn * (bars[-1][4] - entry) / entry * 100
