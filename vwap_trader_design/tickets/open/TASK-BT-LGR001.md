# TASK-BT-LGR001 — Cat.9: Liquidity Grab + Reversal (LGR-001)

**상태**: OPEN  
**발행**: 의장 (결정 #80, 2026-04-30)  
**명세 출처**: A(박정우) v1.0 → B(김도현) v1.1 재설계 (2026-04-30)  
**담당**: Dev-Backtest(정민호)

---

## 변경 이력

| 버전 | 날짜 | 변경 내용 |
|------|------|-----------|
| v1.0 | 2026-04-30 | A(박정우) 초안 |
| v1.1 | 2026-04-30 | ESC-LGR-02 FAIL 후 B(김도현) 재설계: 조건 B close→low, grab_atr 0.5→1.0, pin_ratio 하한 0.5, TP 트레일링 전용 |

---

## 전략 개요

**전략명**: LGR-001 (Liquidity Grab + Reversal)  
**카테고리**: Cat.9 — 유동성 레벨 사냥  
**핵심 논리**: 스윙 고/저점 위 스톱 클러스터를 마켓 메이커가 침범한 직후 급반전 구조 포착

**S-01과의 핵심 차이**:

| 항목 | S-01 (실패) | LGR-001 |
|------|------------|---------|
| 반전 근거 | EMA21 터치 (구조 없음) | 스윙 저점 저가 침범 후 복귀 (청산 소진 증거) |
| SL 기준 | 진입가 기준 1.5×ATR → 노이즈 내 | grab 봉 극단값 너머 → 추가 사냥 시만 히트 |
| 노이즈 흡수 | 불가 (SL 히트 85.7%) | grab 봉 wick 전체 흡수 가능 |

---

## 진입 조건 (v1.1)

**전제**: 1H 봉 기준, swing_low = 최근 `lookback`봉 내 구조적 저점 (형성 후 `n_fresh`봉 이상 경과)

### [Condition A — 핀바 확인]
- `pin_ratio = (close - low) / (high - low)` ≥ `pin_ratio` 파라미터
- AND `close > open`
- AND `close > swing_low`
- 의미: 봉 범위의 하방 wick이 크고 위로 회복 → 매도 거부

### [Condition B — Grab 확인] *(v1.1 수정)*
- `grab_candle.low ≤ swing_low`  ← **v1.0 `close ≤ swing_low`에서 변경**
- AND `grab_candle.low ≥ swing_low - grab_atr × ATR(1H,14)`
- 의미: 저점 이탈 후 ATR 이내 회복 — 저가 터치면 grab 인정

### [A ∧ B 통합 진입]
- 동일 봉에서 Condition A AND Condition B 동시 충족 → grab 봉 close 시 진입
- 또는: grab 봉이 작은 음봉이고 **다음 봉(+1봉)**에서 Condition A 충족 시 허용 → +1봉 close 진입

### [추세 필터 (선택)]
- `trend_filter=ON`: 4H EMA50 위→롱만, 아래→숏만, ±0.5% 중립→양방향

---

## 청산 조건 (v1.1)

| 항목 | 내용 |
|------|------|
| SL (롱) | `grab_candle_low - sl_buf × ATR(1H,14)` ← **불변 (S-01 교훈)** |
| SL (숏) | `grab_candle_high + sl_buf × ATR(1H,14)` |
| TP | 없음 — 트레일링 전용 |
| 트레일링 (초기) | 9 EMA 하회 시 청산 |
| 트레일링 (수익 ≥ 2%) | 직전 1H 스윙 저점 트레일 전환 |

**SL 기준 주의**: 진입가 기준 아닌 **grab 봉 극단값 기준**. S-01 교훈 반영. 수정 금지.

---

## 파라미터 그리드

| 파라미터 | 후보값 | 개수 |
|----------|--------|------|
| `lookback` | 10, 15, 20 | 3 |
| `n_fresh` | 5, 8, 12 | 3 |
| `grab_atr` | 0.5, 1.0, 1.5 | 3 |
| `pin_ratio` | 0.5, 0.6, 0.7 | 3 |
| `sl_buf` | 0.1, 0.2, 0.3 | 3 |
| `trend_filter` | ON, OFF | 2 |

**합계**: 3×3×3×3×3×2 = **486 조합**

---

## 착수 순서

### Step 1 — ESC 선행 검증 (3개, 순서대로)

**ESC-LGR-01**: 스윙 레벨 형성 빈도 → **PASS** ✅ (39.91건/일)

**ESC-LGR-02 (v1.1 재검증)**: Grab + 핀바 조건 동시 성립 빈도 → **조건부 PASS** ✅ (결정 #81)
- best: pin=0.5, grab=1.0 → 0.918건/일
- 합격선: ~~1.5건/일~~ → **1.0건/일** (F 결정 #81, N≥30 통계 기준 재확인)
- 0.918건/일 × 91일 = 84건 → fold당 N≥30 충족 확인

**ESC-LGR-03**: 단일 파라미터 EV 사전 확인
- 대표 파라미터: lookback=15, n_fresh=8, grab_atr=1.0, pin_ratio=0.5, sl_buf=0.2, trend_filter=OFF
- IS 기간 **EV > 0.05** 시에만 그리드 착수 ← F 결정 #81, 기존 EV>0에서 상향
- EV ≤ 0.05 → 즉시 에스컬레이션

→ ESC 3개 모두 PASS 시 Step 2 착수

### Step 2 — 그리드 스크리닝
- 10심볼 × 486 조합
- 상위 20% 조합 추출

### Step 3 — WF BT
- IS: 2022-07-01 ~ 2023-12-31 (18개월)
- OOS: 2024-01-01 ~ 2024-12-31 (12개월)
- WF: 12개월 IS / 3개월 OOS × 3 fold

---

## 합격 기준

| 지표 | 기준 |
|------|------|
| OOS EV(ATR) | > 0 |
| OOS Sharpe | > 0.3 |
| OOS MDD | < 25% |
| 건/일 시스템 합산 | ≥ 2.0 (Cat.2 포함) |
| **Cat.2 월별 상관계수** | 보고 필수 (F 판단용) |
| WF 일관성 | 3 fold 중 2 이상 EV 양수 |

---

## Trade Log 필수 기록 항목 (G 검수용)

각 거래에:
- `entry_price`
- `grab_candle_low` (롱) 또는 `grab_candle_high` (숏)
- `actual_sl_price`
- `gap` (grab 극단 ~ 진입가 거리, ATR 단위)
- `entry_mode` (동봉 / +1봉)
