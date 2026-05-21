# 모멘텀 봇 업그레이드 히스토리 (2026-05-21)

## 현재: v5 — 1시간봉 + BE+Trailing Stop

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

## 검증 타임라인

| 시점 | 목표 | 판단 기준 |
|------|------|----------|
| 50건 (≈1개월) | 백테스트 vs 실전 비교 | WR >80%, EV >0 |
| 200건 (≈3개월) | Go/No-Go | PF >1.2, 유의미한 양의 EV |
| 실패 시 | 대안 | 15분봉 전환 or mean reversion 검토 |
