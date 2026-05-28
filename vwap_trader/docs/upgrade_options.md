# 모멘텀 봇 업그레이드 히스토리

## 현재: v5.1 (2026-05-28, 37 trades)

### v5 → v5.1 진단 배경

v5 백테스트 OOS WR 98.7% vs 실전 WR 30%의 큰 괴리. 4개 가설 순차 기각:

| 가설 | 결과 |
|------|----|
| 인트라바 SL 미반영 | ❌ OOS 0%p 차이 |
| 유니버스 편향 | ❌ 메이저/스몰캡 WR 차이 1.8%p |
| 신호 검출 방식 (`np.percentile` vs `rolling`) | ❌ WR 그대로 |
| **봇 BE/Trail 폴링 지연** | ✅ **확정** |

**결정적 증거**: HYPEUSDT trade 2 — be_triggered=true이지만 sl=초기값. 봇이 1h마다만 깨어나 BE→SL 변경 요청 보낼 시점에 이미 가격이 SL 통과 → Bybit 거부 → rollback → 초기 SL 청산 -2.81%.

### v5.1 변경 사항

| 변경 | 위치 | 효과 |
|------|------|------|
| 1m 폴링 (`_main_loop` 분리) | momentum_bot.py:833 | BE/Trail 매 분 갱신 |
| `_apply_tier_cap()` | momentum_bot.py:172 | catastrophic slip 손실 한정 |
| `_resync_clock_offset()` **매 분** + balance fail 시 즉시 | momentum_bot.py:53, 859 | ErrCode 10002 차단 |
| `slippage_cooldown` state 저장/복원 | momentum_bot.py:768 | 봇 재시작 시 cooldown 유지 |
| Rate Limit 완화 (sleep 0.25/0.5/0.2 → 0.4/0.7/0.4) | _fetch_candles/_scan/_manage | ErrCode 10006 부분 완화 |
| trade record `bot_version` 필드 | momentum_bot.py:678 | v5/v5.1 분석 분리 |

### v5.1 검증 결과 (37 trades, v5.1 6건 청산)

**BE 보호 작동** (3건 ✓):
- trade 23 NEARUSDT: 청산 -0.06% (sl=entry로 정확히 이동)
- trade 28 LITUSDT: 청산 -0.12% (동일)
- 오픈 ERAUSDT: BE→Trail 진행 중

**Trailing winner** (2건 ✓, **1m 폴링 효과 검증**):
- trade 35 BSBUSDT: hold 38봉, **+23.92% (+$275)** 🌟
- trade 36 GRASSUSDT: hold 22봉, +3.63% (+$35)

**Tier Cap 실제 발동** (4건 ✓):
- trade 33 ESPORTS $908, trade 34 PHA $999.96, GRASS short $999.68, XPL short $999.94

**즉시 반전 SL** (4건 ⚠️ — 전략 약점):
- trade 32 NEAR (-3.75%, sig +6.76%), 33 ESPORTS (-12.81%, sig +13.67%), 34 PHA (-7.29%, sig +13.37%), 37 ETH (-0.66%, sig -2.25%)
- hold 0~2봉, MFE < 1.6%. 신호 직후 즉시 trend reversal.

**Catastrophic Slip 사례** (1건, Tier Cap 도입 전):
- trade 27 GRASSUSDT: 5분 만에 -30.10% (-$1,798) → tier cap 도입 계기

**Clock Drift 자동 보정** ✓:
- 1시간당 -150ms 표준 drift + 6분에 1초+ 급격 drift 발견 (5/27 09:00)
- → resync 빈도 매 정각 → **매 분**으로 강화 → ErrCode 10002 0건

**Rate Limit 시간대 의존성** ⚠️:
- UTC 10/14시 (미국 시장) 5~6건 폭주
- 다른 시간대 1~2건 안정
- sleep 완화로 부분 해결, burst limit은 한계

### Signal_ret 임계값 분석 (n=37, 표본 작음)

| Threshold | n | WR | Net PnL |
|---|---|---|---|
| 모두 | 37 | 32.4% | -$495 |
| **abs >= 8% (가상)** | ~10 | **~50%** | **약 +$1,200** 🌟 |
| abs < 5% (weak) | ~14 | ~35% | 음수 |

**핵심**: 약한 신호가 손실 주범. "강한 신호 reject" 가설은 정반대. 다만 NEAR1/PROVE 같은 weak winner도 존재 → 단순 threshold filter 위험. **표본 100건+ 후 검증, volume spike/regime 등 추가 filter 필요**.

---

## v5 — 1시간봉 + BE+Trailing Stop (2026-05-21)

### 전략
- Timeframe: 1h (5분봉에서 전환)
- Signal: P99.5 momentum follow-through
- Entry: 시장가 (next bar open)
- Exit: Breakeven + Trailing Stop (2.0 ATR)
- SL 초기: 1.5 ATR → BE trigger (1.5 ATR 수익) → Trail (best - 2 ATR)

### 근거
- 다중 TF 백테스트: 15m/1h/4h 전부 양의 EV (2023-2026, 12심볼)
- Bybit 실제 1h 캔들 OOS 검증: EV +5.04%, WR 98.7%
- Trailing > Fixed TP: +50% EV 개선 (fat tail capture)
- 5분봉 실전 실패 원인 해소: 더 긴 TF = 모멘텀 지속, 비용 비율 감소

---

## 폐기된 옵션

| 옵션 | 버전 | 결과 | 교훈 |
|------|------|------|------|
| A (데이터만 수집) | v2 | PF 0.88 | edge < 비용 |
| B (BTC DOWN 필터) | v3.1 | EV -$70 | 상관관계 집중 |
| C (Pullback Entry) | v4 | MFE=0 75% | adverse selection |
| D (B+C) | — | 미실행 | B/C 둘 다 실패 |
| E (A/B Test) | — | 미실행 | EV 음수에서 무의미 |
| G (클러스터 제한) | v4.1 | EV -$52 | 5분봉 한계 |

---

> 검증 타임라인 및 향후 모니터링은 [PLAN.md §7](../PLAN.md#7-향후-모니터링-항목) 참조.
