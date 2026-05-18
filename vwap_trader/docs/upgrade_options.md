# 모멘텀 봇 업그레이드 로드맵 (2026-05-18 갱신)

## 현재 상태 (2026-05-18)

- **Phase 0 완료**: v4(옵션 G) 구현
- **Phase 1 완료**: 319건 regime 라벨링 + 탐색 분석
- **v4 pullback entry 실패 확인**: 12건, MFE=0 75%, 구조적 충돌 (fill=모멘텀 소진)
- **v4.1 가동 중**: pullback off + 나머지 옵션 G 유지 (시장가 진입 복귀)
- **Phase 2 진행 중**: v4.1 봇 Demo 운영, 300건 수집 목표

---

## 폐기된 옵션 (참고용)

| 옵션 | 상태 | 이유 |
|------|------|------|
| A (v3 원복) | ❌ | v3도 EV -$22/건. 돌아갈 곳 없음 |
| B (안전 필터) | ❌ 실패 | Short를 하락장에 집중 → 상관관계 폭탄 |
| D (B+C) | ❌ | B 제거해야 하므로 무의미 |
| E (A/B 테스트) | ❌ | EV -$70/건에서 A/B 테스트 의미 없음 |

---

## 새 로드맵: 옵션 G → Regime-Aware 시스템

### Phase 0: 옵션 G 적용 ✅ 완료 (2026-05-18)

**목표**: 데이터 수집하면서 돈을 덜 잃는 구조로 전환

변경 내용:
1. **옵션 B 필터 제거** — `short_only_btc_down: false`
2. **클러스터 제한** — 같은 5분 bar에서 최대 2건만 진입 (signal_strength 상위 2개)
3. **방향별 포지션 cap** — Long 최대 3건, Short 최대 3건 동시
4. **Pullback Entry** — bar close 즉시 시장가 진입 대신, 0.3 ATR pullback에 limit order, 3 bars 미체결 시 취소
5. **Regime 태그 로깅 추가** — 매 거래에 BTC 4h return, BTC 4h ATR(volatility), regime 라벨 기록

기대 효과:
- 클러스터 10건 동시 SL → 최대 2건으로 제한 (-$2,000 → -$400)
- Pullback으로 MFE=0 비율 52% → ~20% 감소
- 일 거래수: ~30~40건 (fill rate 65% 가정)

완료: v4 봇 가동 확인 (2026-05-18 11:33 KST). Regime 로그 정상 출력.

**v4 pullback entry 실패 (12건, 2026-05-18)**:
- 12건 중 MFE=0 = 9건 (75%). v2(27%)의 3배.
- 이항검정 p < 0.001 — 구조적 문제 확인
- 원인: pullback fill = "모멘텀 소진 증거" (adverse selection)
- 모멘텀 follow-through에서 pullback은 "건강한 되돌림"이 아니라 "반전 시작"
- **pullback_enabled: false로 전환 → v4.1 (시장가 진입 복귀)**
- 나머지 옵션 G(클러스터 제한, 방향 cap, regime 로깅) 유지
- 데이터: `trades_momentum_v4.jsonl` (12건 백업)
- 전문가 자문: `prompt_expert_urgent.md` 참조

---

### Phase 1: Regime 라벨링 + 탐색 분석 ✅ 완료 (2026-05-18)

**목표**: 319건(v2+v3+v3.1) 데이터에 regime 태그 붙여서 탐색 분석

**결과 요약** (스크립트: `vwap_trader/regime_analysis.py`):

관측된 regime 3종 (전부 HIGH volatility):
- DOWN_HIGH: 220건 (69%), EV -$24/건
- UP_HIGH: 88건 (28%), EV -$17/건
- FLAT_HIGH: 11건 (3%), EV -$92/건

핵심 발견:
1. **DOWN_HIGH + Short = 전체 손실의 63%** (156건, EV -$31/건, 총 -$4,830)
2. **모든 regime에서 EV 음수** — "거래해도 되는" regime이 아직 없음
3. 가장 나은 조합: DOWN_HIGH+Long (-$6/건), UP_HIGH+Long (-$10/건) — 둘 다 BEP 근처
4. **LOW volatility 데이터 전무** — v4에서 수집 필요
5. MFE=0 비율: 전 regime에서 ~31% (FLAT_HIGH는 45%)

가설:
- "DOWN_HIGH + Short 차단"이 가장 확실한 규칙 (156건 근거)
- 단 v4의 클러스터 제한이 이미 이 문제를 부분 완화
- LOW volatility regime에서 성과가 다를 수 있음 → v4 데이터로 검증 필요

산출물: `vwap_trader/regime_analysis.py` (BTC 4h 자동 fetch + regime 라벨링 + 분석)

---

### Phase 2: 옵션 G로 Demo 운영 + 데이터 수집 (2~4주)

**목표**: 300건+ 신규 데이터 수집 (regime 태그 포함)

작업:
- 옵션 G 봇 24/7 운영
- 매 거래에 regime 태그 자동 기록
- 주 1회 중간 분석 (승률, PF, regime별 성과)
- **규칙 수정 금지** — 이 기간은 순수 데이터 수집

완료 기준: 300건+ 축적

예상 소요: ~30건/일 × 10~14일 = 300~420건

---

### Phase 3: Regime별 성과 검증 (300건 도달 후, 1~2일)

**목표**: 가설 검증 → Regime 행동 테이블 확정

작업:
1. 300건+ 데이터를 regime별 분할
2. Regime별: 건수, 승률, EV, PF 계산
3. Phase 1 가설 검증:
   - "이 regime에서 거래 안 하면?" 시뮬레이션
   - "이 regime에서 Long만 하면?" 시뮬레이션
4. 시간 분할 검증: 앞 70% 학습 → 뒤 30% 검증
5. **최소 표본 기준**: regime당 30건 미만이면 "모름" 처리

산출물: Regime 행동 테이블 (lookup table)

예시:
```
TREND_UP + LOW_VOL  → Long만, max 2건
TREND_DOWN + HIGH_VOL → Short만, max 2건, pullback 필수
FLAT + LOW_VOL → 거래 안 함
FLAT + HIGH_VOL → Long/Short 모두, max 1건
```

과적합 방어:
- 규칙 수 6~8개 이내
- "거래 안 함"이 가장 강력한 규칙
- 규칙 추가보다 규칙 제거가 항상 안전

---

### Phase 4: Regime 규칙 봇에 적용 (Phase 3 후, 1~2일)

**목표**: 검증된 regime 규칙만 봇에 하드코딩

작업:
1. Regime 행동 테이블을 config에 반영
2. 봇이 매 bar마다 현재 regime 판별 → 행동 테이블 조회 → 진입 허용/차단
3. "모름" regime에서는 보수적 기본값 (max 1건, pullback 필수)

---

### Phase 5: Circuit Breaker 추가 (Phase 4 후, 1일)

**목표**: regime 규칙이 실전에서 안 맞을 때 자동 방어

작업:
1. Rolling window(최근 20건)로 regime별 실시간 성과 추적
2. 특정 regime에서 연속 5패 또는 EV < -$50/건 → 해당 regime 자동 off
3. Off된 regime은 24시간 후 자동 재개 (1건만 허용하고 관찰)

이건 "학습"이 아니라 "안전장치". 과적합 위험 낮음.

---

### Phase 6: 판단 시점 (Phase 4~5 적용 후 300건 추가, ~4주 후)

**목표**: 이 전략을 계속할지, 피벗할지 결정

판단 기준:
- **계속**: Regime 필터 적용 후 PF > 1.1, 특정 regime에서 안정적 양의 EV
- **timeframe 변경**: EV가 여전히 음수지만 패턴은 보임 → 15분/1시간봉으로 전환
- **전략 피벗(옵션 F)**: 어떤 regime에서도 양의 EV 없음 → 모멘텀 follow-through 자체를 포기

---

## 전체 타임라인

| 주차 | Phase | 핵심 활동 | 산출물 |
|------|-------|----------|--------|
| 1주차 | 0+1 | 옵션 G 구현 + regime 라벨링 | 봇 v4(옵션 G), regime 분석 리포트 |
| 2~3주차 | 2 | Demo 운영, 데이터 수집 | 300건+ (regime 태그 포함) |
| 3주차 말 | 3 | Regime 성과 검증 | 행동 테이블 |
| 4주차 | 4+5 | Regime 규칙 적용 + circuit breaker | 봇 v5(regime-aware) |
| 5~8주차 | 2 반복 | v5로 300건+ 추가 수집 | 검증 데이터 |
| 8주차 | 6 | 최종 판단 | 계속 / timeframe 변경 / 피벗 |

---

## 마인드셋

> 지금은 "수익 내는 봇"이 아니라 **"데이터 수집 + 가설 검증 인프라"**를 만드는 단계.
> 매 거래의 손실은 학습 비용이 아닌 연구 데이터.
> Demo 모드에서 최소 500건 이상 수집할 때까지 실계좌 전환 금지.

## 과적합 방어 원칙

1. 시간 분할 검증: 앞 70% 학습 → 뒤 30% 검증
2. 규칙 수 제한: regime × 행동 조합 최대 6~8개
3. 최소 표본: regime당 30건 미만 → "모름" 처리
4. 규칙 확정 후 2주 demo 검증, 수정 금지
5. 규칙 추가보다 규칙 제거가 항상 안전
