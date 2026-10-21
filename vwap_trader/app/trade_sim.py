"""공개 1h봉으로 봇 청산규칙(SL 3.0ATR·BE 1.5 후 트레일 2.0ATR·48봉 만기)을 재현하는 공용 시뮬 엔진.

출처: analysis_flip_mirror.py(2026-10-18 메인 PC 작성)의 bars/sim — 실제 숏 재현 건별 상관 0.96 검증.
관측소(regime_engine)·H-13/H-14 판정·반사실 분석이 전부 이 하나를 쓴다(엔진 분기 = 숫자 불일치 사고).
⚠봉 내 고저 순서는 보수적(손절 우선). 수수료·슬리피지 미반영 — 두 방향의 '비교'에만 쓸 것.
"""
import datetime
import time


def fetch_bars(cli, sym: str, ts_iso: str, keep: int = 48, limit: int = 60,
               sleep: float = 0.1):
    """진입 시각(정시 내림)부터 keep개의 1h봉 [(ts, o, h, l, c)] — 실패 시 None.

    원본(analysis_flip_mirror 2026-10-18, 숏 재현 상관 0.96 검증) 로직 보존:
    정시 내림 → limit개 조회 → 진입 정시 이전 봉 제거 → keep개 컷(=48봉 만기 계약).
    ts_iso는 tz 포함 문자열 전제(naive면 이 PC 로컬 시간으로 해석 — 원본 동작 보존).
    거래소가 빈 목록을 주면 [] 반환, 예외면 None. sleep은 성공·실패 모두 실행."""
    t0 = datetime.datetime.fromisoformat(ts_iso).replace(minute=0, second=0, microsecond=0)
    ms = int(t0.timestamp() * 1000)
    try:
        r = cli.get_kline(category="linear", symbol=sym, interval="60", start=ms, limit=limit)["result"]["list"]
        b = sorted([(int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4])) for k in r])
        b = [x for x in b if x[0] >= ms][:keep]
    except Exception:
        b = None
    time.sleep(sleep)
    return b


def sim_pct(dirn: int, entry: float, atr: float, bars,
            sl_mult: float = 3.0, be_mult: float = 1.5, tr_mult: float = 2.0) -> float:
    """dirn: +1 롱 / -1 숏. 반환: 노셔널 대비 수익률(%).
    bars가 비어 있으면 IndexError — 호출부가 `if not bs or len(bs) < 3` 가드 책임."""
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
