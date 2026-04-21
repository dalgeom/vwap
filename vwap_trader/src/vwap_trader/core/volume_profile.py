# 부록 H-1 — Volume Profile 계산
# 부록 H-1.2 — VA 기울기(va_slope) 계산 (회의 #15, 2026-04-20 신설)
# Dev-Core(이승준) 구현

from vwap_trader.models import Candle, VolumeProfile

N_BINS: int = 200
VALUE_AREA_PCT: float = 0.70
HVN_TOP_PCT: float = 0.25

VA_SLOPE_WINDOW_HOURS: int = 168   # 부록 H-1.2 — 7일


def compute_volume_profile(candles_168h: list[Candle]) -> VolumeProfile:
    """7일(168시간) Volume Profile 계산 (부록 H-1).

    Raises:
        ValueError: 캔들이 0개인 경우
    """
    if not candles_168h:
        raise ValueError("candles_168h must not be empty")

    high_7d: float = max(c.high for c in candles_168h)
    low_7d: float = min(c.low for c in candles_168h)

    if high_7d == low_7d:
        poc = high_7d
        return VolumeProfile(poc=poc, val=poc, vah=poc, hvn_prices=[poc])

    bin_width: float = (high_7d - low_7d) / N_BINS
    bins: list[float] = [0.0] * N_BINS

    for candle in candles_168h:
        c_low_idx = max(int((candle.low - low_7d) / bin_width), 0)
        c_high_idx = min(int((candle.high - low_7d) / bin_width), N_BINS - 1)
        span = c_high_idx - c_low_idx + 1
        vol_per_bin = candle.volume / span if span > 0 else candle.volume
        for i in range(c_low_idx, c_high_idx + 1):
            bins[i] += vol_per_bin

    total_vol: float = sum(bins)

    poc_idx = bins.index(max(bins))
    poc: float = low_7d + (poc_idx + 0.5) * bin_width

    sorted_bins = sorted(range(N_BINS), key=lambda i: bins[i], reverse=True)
    va_bins: set[int] = set()
    cum = 0.0
    for idx in sorted_bins:
        va_bins.add(idx)
        cum += bins[idx]
        if cum >= total_vol * VALUE_AREA_PCT:
            break

    va_low_idx = min(va_bins)
    va_high_idx = max(va_bins)
    val: float = low_7d + va_low_idx * bin_width
    vah: float = low_7d + (va_high_idx + 1) * bin_width

    hvn_threshold = sorted(bins, reverse=True)[int(N_BINS * HVN_TOP_PCT)]
    hvn_prices: list[float] = [
        low_7d + (i + 0.5) * bin_width
        for i, vol in enumerate(bins)
        if vol >= hvn_threshold
    ]

    return VolumeProfile(poc=poc, val=val, vah=vah, hvn_prices=hvn_prices)


def compute_va_slope(
    candles_1h: list[Candle],
    *,
    window_hours: int = VA_SLOPE_WINDOW_HOURS,
) -> float:
    """부록 H-1.2 — 7일 간격 POC 변화율.

    기준점: 직전 window_hours 봉의 VP 의 POC (POC_now)
    비교점: 그 이전 window_hours 봉의 VP 의 POC (POC_7d_ago)
    반환: (POC_now - POC_7d_ago) / POC_7d_ago  (소수, 음수 허용)

    데이터 부족 (len < 2 * window_hours) 시 0.0 반환 — 부록 B-0 엣지 1 준용.
    """
    if len(candles_1h) < 2 * window_hours:
        return 0.0

    now_window = candles_1h[-window_hours:]
    past_window = candles_1h[-2 * window_hours : -window_hours]

    vp_now = compute_volume_profile(now_window)
    vp_past = compute_volume_profile(past_window)

    if vp_past.poc <= 0:
        return 0.0

    return (vp_now.poc - vp_past.poc) / vp_past.poc
