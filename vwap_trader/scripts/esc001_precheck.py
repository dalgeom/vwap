"""ESC-001 S-04b 재검증: ATR_ratio < 0.9."""
import pandas as pd
import numpy as np

ATR_THRESHOLD = 0.9   # 이번 검증 임계치 (이전: 0.6)

BASE = r'c:\Users\DEV_BASIC\Downloads\code\vwap_trader\data\cache'
df1h = pd.read_csv(f'{BASE}/BTCUSDT_60.csv')
df4h = pd.read_csv(f'{BASE}/BTCUSDT_240.csv')

df1h['ts'] = pd.to_datetime(df1h['ts_ms'], unit='ms')
df4h['ts'] = pd.to_datetime(df4h['ts_ms'], unit='ms')

start, end = '2024-01-01', '2025-12-31 23:59:59'
df1h = df1h[(df1h['ts'] >= start) & (df1h['ts'] <= end)].reset_index(drop=True).copy()
df4h = df4h[(df4h['ts'] >= start) & (df4h['ts'] <= end)].reset_index(drop=True).copy()


def calc_atr_ratio(df, atr_period=14, ma_period=20):
    d = df.copy()
    d['tr'] = pd.concat([
        d['high'] - d['low'],
        (d['high'] - d['close'].shift(1)).abs(),
        (d['low']  - d['close'].shift(1)).abs(),
    ], axis=1).max(axis=1)
    d['atr'] = d['tr'].ewm(span=atr_period, adjust=False).mean()
    d['atr_ma'] = d['atr'].rolling(ma_period).mean()
    d['atr_ratio'] = d['atr'] / d['atr_ma']
    return d


df1h = calc_atr_ratio(df1h)
df4h = calc_atr_ratio(df4h)

# ─── Step 1: ATR_ratio 발동률 비교 ────────────────────────────────────
valid1h  = df1h.dropna(subset=['atr_ratio'])
total_1h = len(valid1h)
fired_06 = int((valid1h['atr_ratio'] < 0.6).sum())
fired_09 = int((valid1h['atr_ratio'] < ATR_THRESHOLD).sum())
pct_06   = fired_06 / total_1h * 100
pct_09   = fired_09 / total_1h * 100

print("=== Step 1: ATR_ratio 발동률 비교 ===")
print(f"  < 0.6 (이전): {fired_06}봉  {pct_06:.2f}%")
print(f"  < {ATR_THRESHOLD} (이번): {fired_09}봉  {pct_09:.2f}%")
print(f"  ATR_ratio 분포: p10={valid1h['atr_ratio'].quantile(0.1):.3f}  p25={valid1h['atr_ratio'].quantile(0.25):.3f}  median={valid1h['atr_ratio'].quantile(0.5):.3f}  p75={valid1h['atr_ratio'].quantile(0.75):.3f}")

# ─── 4H Swing 방향 매핑 ───────────────────────────────────────────────
df4h['ema9']  = df4h['close'].ewm(span=9,  adjust=False).mean()
df4h['ema20'] = df4h['close'].ewm(span=20, adjust=False).mean()
df4h['swing_up'] = (df4h['ema9'] > df4h['ema20']) & (df4h['close'] > df4h['ema20'])

df4h_map = df4h[['ts', 'swing_up']].set_index('ts').resample('1h').ffill().reset_index()
df4h_map.columns = ['ts', 'swing_up_4h']
df1h = df1h.merge(df4h_map, on='ts', how='left')
df1h['swing_up_4h'] = df1h['swing_up_4h'].fillna(False)

# ─── 1H Module B Long 근사 조건 ──────────────────────────────────────
df1h['ema9_1h']  = df1h['close'].ewm(span=9,  adjust=False).mean()
df1h['ema20_1h'] = df1h['close'].ewm(span=20, adjust=False).mean()
df1h['trend_ok'] = (df1h['close'] > df1h['ema20_1h']) & (df1h['ema9_1h'] > df1h['ema20_1h'])

rng = df1h['high'] - df1h['low']
df1h['strong_close'] = df1h['close'] >= df1h['low'] + 0.67 * rng
df1h['vol_ma20']     = df1h['volume'].rolling(20).mean()
df1h['vol_ok']       = df1h['volume'] > df1h['vol_ma20'] * 1.2


def calc_swing_retrace(closes, highs, lows, n=15):
    retrace = pd.Series(np.nan, index=closes.index)
    for i in range(n * 2, len(closes)):
        wh = highs.iloc[i - n:i]
        H_swing = wh.max()
        h_idx = int(wh.values.argmax())
        if h_idx == 0:
            continue
        L_swing = lows.iloc[i - n:i - n + h_idx + 1].min()
        if H_swing <= L_swing:
            continue
        retrace.iloc[i] = (H_swing - closes.iloc[i]) / (H_swing - L_swing)
    return retrace


print("\n  [swing retrace 계산 중 (~15초)...]")
df1h['retrace']    = calc_swing_retrace(df1h['close'], df1h['high'], df1h['low'])
df1h['retrace_ok'] = (df1h['retrace'] >= 0.30) & (df1h['retrace'] <= 0.70)

mb_long_base = (
    df1h['swing_up_4h'] &
    df1h['trend_ok'] &
    df1h['strong_close'] &
    df1h['vol_ok'] &
    df1h['retrace_ok']
)
mb_total = int(mb_long_base.sum())

s04_old   = mb_long_base & (df1h['atr_ratio'] < 0.6)
s04b      = mb_long_base & (df1h['atr_ratio'] < ATR_THRESHOLD)
s04_old_n = int(s04_old.sum())
s04b_n    = int(s04b.sum())

n_days       = df1h['ts'].dt.date.nunique()
s04b_per_day = s04b_n / n_days

pass_rate_09     = s04b_n / mb_total * 100 if mb_total > 0 else 0
filter_elim_rate = 100.0 - pass_rate_09

# ─── Step 2 ───────────────────────────────────────────────────────────
print("\n=== Step 2: Module B Long 신호 x ATR 필터 ===")
print(f"  분석 기간: {n_days}일")
print(f"  MB Long 근사 신호 (ATR 없음): {mb_total}건 ({mb_total/n_days:.3f}건/일)")
print(f"  S-04  (< 0.6 이전): {s04_old_n}건 ({s04_old_n/n_days:.4f}건/일) | 통과율 {s04_old_n/mb_total*100:.1f}%")
print(f"  S-04b (< {ATR_THRESHOLD} 이번): {s04b_n}건 ({s04b_per_day:.3f}건/일) | 통과율 {pass_rate_09:.1f}%")

# ─── Step 3: 선별력 ───────────────────────────────────────────────────
selectivity_ok = filter_elim_rate >= 10.0
print("\n=== Step 3: ATR 필터 선별력 ===")
print(f"  < {ATR_THRESHOLD} 제거율: {filter_elim_rate:.1f}%")
print(f"  판정: {'유효 (>= 10%)' if selectivity_ok else '무필터 동일 (< 10%) -> FAIL'}")

# ─── Step 4: 합산 추정 ────────────────────────────────────────────────
current_system  = 1.930
total_with_s04b = current_system + s04b_per_day
contrib_pass    = s04b_per_day >= 0.10
freq_pass       = total_with_s04b >= 2.0

print("\n=== Step 4: 시스템 합산 추정 ===")
print(f"  현재 시스템: {current_system:.3f}건/일")
print(f"  S-04b 기여:  {s04b_per_day:.3f}건/일")
print(f"  합산 추정:   {total_with_s04b:.3f}건/일")
print(f"  합산 >= 2.0건/일: {'Y' if freq_pass else 'N'}")
print(f"  S-04b 단독 >= 0.10건/일: {'PASS' if contrib_pass else 'FAIL'}")

esc_pass = contrib_pass and selectivity_ok

# ─── 강제 출력 형식 ───────────────────────────────────────────────────
print("\n" + "=" * 60)
print("=== 출력 형식 (강제) ===")
print(f"Step 1: ATR_ratio < {ATR_THRESHOLD} 발동률 = {pct_09:.2f}%  ({fired_09}봉 / {total_1h}봉)")
print(f"Step 2: Long 신호 중 ATR 조건 충족 = {s04b_n}건 ({pass_rate_09:.1f}%) -> 건/일 = {s04b_per_day:.3f}")
print(f"Step 3: ATR 필터 제거율 = {filter_elim_rate:.1f}% -> 선별력: {'유효' if selectivity_ok else '무필터 동일'}")
print(f"Step 4: 시스템 합산 추정 = {total_with_s04b:.3f}건/일 -> 철칙 충족: {'Y' if freq_pass else 'N'}")
print(f"판단: ESC-001 {'PASS' if esc_pass else 'FAIL'}")
