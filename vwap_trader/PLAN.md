# Momentum Bot — 전략 계획서 (v5.1+)

> 최종 업데이트: 2026-05-29
> 이전 펀딩 역추세 봇 PLAN은 [PLAN_funding_legacy.md](PLAN_funding_legacy.md) 참조 (폐기됨)

---

## 1. 프로젝트 목표

Bybit USDT 무기한 선물 데모 계좌에서 **모멘텀 추종(Big Move Follow-Through)** 전략 자동 운영.
P99.5 percentile 이상 1h 봉 수익률 → 모멘텀 방향으로 진입 → BE+Trailing Stop 청산.

- **현재 단계**: v5.1+ 운영, 데이터 수집 중 (43 trades, 4 open). 신호연구 병행 — 변별신호 로깅 + shadow log 가동
- **검증 임계점**: 50건(첫 평가), 200건(Go/No-Go)

---

## 2. 현재 전략 — v5.1

### 핵심 원리
"1시간 봉 수익률이 과거 500봉의 99.5%ile을 초과하면, 그 방향으로 모멘텀이 계속될 확률이 높다."

### 2.1 동작 흐름

1. **매 1분**: 오픈 포지션 BE/Trail SL 갱신 (`_manage_positions`)
2. **매 정각 (분=0)**: 클럭 재sync + universe 스캔 + 신호 발생 시 진입
3. SL/TP는 Bybit 거래소에 등록 → 봇 다운 시에도 청산 보호
4. 봉 종가 close → 다음 1h 봉 open에서 시장가 진입

### 2.2 설정값 ([config/momentum_config.yaml](config/momentum_config.yaml))

| 항목 | 값 |
|------|----|
| Timeframe | 1h (signal) |
| 신호 임계값 | abs(ret) > 500봉 rolling 99.5%ile |
| ATR 기간 | 20 |
| 초기 SL | 1.5 × ATR |
| BE Trigger | 1.5 × ATR 수익 시 SL → entry |
| Trailing | best ± 2.0 × ATR |
| Max Hold | 48 bars (48h) |
| Cooldown | 1 bar (코인별) |
| 거래당 리스크 | 0.5% |
| 동시 포지션 | max 10 (long 3 + short 3 cap) |
| 정각당 max 진입 | 2건 |
| min 24h volume | $20M |

### 2.3 Tier Cap (v5.1 신규)

24h turnover 기준 position notional cap:

| Tier | 24h Volume | Max Position |
|------|------|------|
| 1 | > $500M | $10,000 |
| 2 | > $100M | $5,000 |
| 3 | > $50M | $2,000 |
| 4 | < $50M | $1,000 |
| Hard cap | — | $10,000 |

risk_pct로 계산된 사이즈가 cap을 넘으면 qty 비례 축소 (lot_size 단위 floor).

---

## 3. 버전 히스토리

| 버전 | 날짜 | 변경 내용 | 결과 |
|------|------|-----------|------|
| v1 | 2026-05-09 | 5분봉 모멘텀 + Fixed TP/SL | 비용 > edge, PF 0.88 |
| v2 | — | 데이터 수집만 | 동일 |
| v3.1 | 2026-05-17 | BTC DOWN 필터 (옵션 B) | EV -$70, 상관관계 집중 실패 |
| v4 | — | Pullback Entry (옵션 C) | MFE=0 75%, adverse selection |
| v4.1 | 2026-05-19 | 클러스터 제한 (옵션 G) | EV -$52, 5분봉 한계 명확 |
| v5 | 2026-05-21 | **1h 봉 전환 + BE+Trailing Stop** | OOS WR 98.7% 백테스트 |
| **v5.1** | **2026-05-23~27** | **1m 폴링 + Tier Cap + Clock resync + bot_version** | **운영 중** |
| **v5.1+** | **2026-05-28~29** | **신호 컨텍스트 5필드 로깅 + Shadow Log (걸린 신호 기록)** | **운영 중, 거래로직 무변경** |

---

## 4. v5.1 변경 사항 (요약)

v5 백테스트 WR 98.7% vs 실전 30% 괴리의 원인은 **BE/Trail 폴링 지연**(HYPE1: be_triggered인데 SL 초기값 → -2.81%). 진단 과정(4가설 기각)은 §10 의사결정 이력 참조.

| 변경 | 계기 | 효과 / 검증 |
|------|------|-------------|
| **1m 폴링** (`_main_loop` 분리) | BE/Trail 1h 지연 (HYPE1) | 매 분 BE/Trail 갱신, 정각만 scan. NEAR2/LIT3 BE 보호 ✓ |
| **Tier Cap** (`_apply_tier_cap`) | GRASS2 -30.1% / -$1,798 catastrophic slip | 24h volume 기반 notional 축소. 4건 발동 ✓ |
| **Clock Resync 매 분** | 시계 drift → ErrCode 10002 폭주 | 정각→매 분 + balance fail 시 즉시. 10002 = 0건 ✓ |
| **cooldown state 저장** | 재시작 시 cooldown 소실 → 재진입 | ISO 직렬화 저장/복원 + 만료 필터 |
| **Rate Limit sleep 완화** | 정각 scan ErrCode 10006 | 페이지 0.25→0.4, 심볼 0.5→0.7, manage 0.2→0.4. manage RL 4→1 ✓ (§8.4) |
| **bot_version 필드** | v5/v5.1 분석 분리 | `_log_trade`에 기록 |

> OS 시계: 봇 시작 전 `w32tm /resync /force` (관리자 PowerShell)로 정확도 보장.

### 4.7 신호 컨텍스트 로깅 + Shadow Log (v5.1+, 5/28~29)

**배경**: D-소급 신호 연구(§8.5)에서 "진입 시점 변수로는 winner/loser 변별 불가, 그러나 *선행추세·연속성·OI변화*가 변별력 있을 가능성" 가설 도출. 검증 데이터를 봇이 직접 쌓도록 로깅 확장.

**4.7.1 신호 컨텍스트 5필드** ([momentum_bot.py `_compute_signal_context`](src/vwap_trader/momentum_bot.py#L1262)):
- `signal_ret_6/12/24` (선행추세, 방향 반영 %), `signal_consec` (연속 동방향봉), `signal_oi_chg` (OI 1h 변화율 %)
- 진입 시 `OpenPosition`에 저장 → `_log_trade`에서 trades 레코드에 기록.
- **거래 결정엔 일절 영향 없음. 순수 기록.** 미래 신규 진입부터 축적.

**4.7.2 Shadow Log** ([momentum_bot.py `_log_shadow`](src/vwap_trader/momentum_bot.py#L1293)):
- **목적**: fire 됐지만 진입 안 된 신호를 기록 → **생존편향(survivorship bias) 깨기**. 진입한 거래만 봐선 "안 들어간 신호가 실제로 더 나빴는지" 대조 불가.
- 출력: `data/shadow_momentum.jsonl`. trades 로그와 **동일 스키마**(exit/pnl 제외 + `shadow_reason`) → 분석 시 union 가능. forward 성과는 symbol+timestamp+signal_price로 추후 klines 소급 재구성.
- `_scan_universe` 재구성: 만석이어도 스캔 수행(`scan_only`), 진입만 skip하고 잡힌 신호 전부 shadow. 9종 reason: `max_pos_full`/`btc_filter`/`slippage_cooldown`/`rank_cutoff`/`long_cap`/`short_cap`/`size_invalid`/`tier_cap`/`order_failed`.
- 로그: `Scan done: N entries, M shadow, ...`.

**비용/주의**: 만석 시 매 정각 풀 스캔(이전엔 skip)하나, 실효 cap이 long3+short3=6이라 `max_pos_full`(10) 경로는 거의 안 걸려 rate-limit 추가비용 미미. **단, shadow가 데이터 소스가 되면서 scan 누락(47/51, RL로 4코인 skip)이 새 관측 구멍** → §8.4 참조.

---

## 5. 운영 현황 스냅샷 (2026-05-29 기준, 43 trades)

> 실시간 데이터는 [data/trades_momentum.jsonl](data/trades_momentum.jsonl), [data/state_momentum.json](data/state_momentum.json) 직접 참조.

### 5.1 누적 통계

| 그룹 | 건수 | WR | 누적 PnL |
|------|------|------|------|
| v5.1 이전 (bot_version 없음) | 31 | 35.5% | -$447 (GRASS2 -$1,798 포함) |
| **v5.1 (tier cap 이후)** | **12** | **41.7%** | **+$214** 🟢 양전환 |
| **합계** | **43** | **37.2%** | **-$233** |

> v5.1만 떼어보면 WR 41.7% / +$214로 **순(net) 플러스 전환**. tier cap이 catastrophic loss를 막고 1m 폴링이 trailing winner를 견인한 효과. 단 12건이라 표본 작음 — 50건까지 안정성 확인 필요.

### 5.2 청산 유형 분포

(43건 실집계, exit_reason 기준)

| 유형 | 건수 | 비고 |
|---|---|---|
| SL | 23 | 손실 주류. GRASS2 catastrophic -30.1% 포함 |
| TrailSL | 15 | winner 견인 (BSB +24%, XLM +4.75% 등) |
| BE 보호 | 3 | NEAR2/LIT3 보호 ✓ (HYPE1은 v5 결함) |
| Timeout | 2 | PROVE +14.2% 등 |

### 5.3 패턴 인사이트

- **Hold 0~3봉 (즉시 반전)**: 거의 100% 손실. 신호 직후 trend reversal — 전략 자체 한계.
- **Hold 7~38봉 (모멘텀 형성)**: trailing이 큰 winner 견인 (BSB +24%, +50%).
- **누적 수익은 6~7건의 jackpot에 의존**: BSB(x2), BEAT1, NEAR1, PROVE, IN2 등.
- **v5.1 trailing 정상 작동 검증**: BSB(38h) +24%, GRASS(22h) +4% — 1m 폴링이 trailing edge 확보.
- **즉시 반전 SL 비율 (v5.1)**: 4/6 = 67% — 전략 약점 지속 (§8.1/§8.5).

---

## 6. 안전장치 종합

| 항목 | 위치 | 동작 |
|------|------|------|
| Bybit SL 등록 | place_order 시 | 거래소가 자동 청산 |
| BE/Trail 1분 갱신 | _manage_positions | best 추적, SL 이동 |
| Tier Cap | _apply_tier_cap | catastrophic slip 손실 한정 |
| Slippage Cooldown | _log_trade | slip > 1%p 시 해당 심볼 48h 차단 |
| **Cooldown State 저장** (v5.1) | _save/_load_state | 봇 재시작 시 cooldown 정보 복원 |
| **Clock Resync 매 분** (v5.1) | _main_loop | timestamp drift 보정 (정각 → 매 분 강화) |
| **Balance Fail 시 즉시 Resync** (v5.1) | _main_loop | timestamp 의심 시 추가 보정 |
| **API Rate Limit 완화** (v5.1) | _fetch_candles, _scan, _manage | sleep 0.5/0.2 → 0.7/0.4 (ErrCode 10006 감소) |
| Daily PnL Reset | UTC 자정 | daily_pnl, daily_trades 초기화 |
| STOP 파일 | data/STOP_MOMENTUM | 다음 분에 봇 정상 종료 |
| Heartbeat | data/heartbeat_momentum | 외부 watchdog용 |

---

## 7. 향후 모니터링 항목

### 7.1 v5.1 효과 검증 (단기, 50건까지)

검증 완료 ✓: Tier Cap 발동(4건), BE 보호(NEAR2/LIT3), Trailing winner(BSB +24%/GRASS +4%), ErrCode 10002 차단, Rate Limit 완화(manage 4→1).

- [ ] **즉시 반전 SL 비율** ⚠️ — v5.1 67% 지속, 전략 약점 (§8.1/§8.5)
- [ ] **50건 누적 시 winner ratio 안정성**
- [ ] **변별신호 검증** — shadow log + 신호 컨텍스트로 entered vs filtered 비교 (§4.7/§8.5)

### 7.2 전략 자체 평가 (중기, 200건)

- [ ] **Winner ratio 안정성** — 큰 winner 5건 의존도 지속? 신뢰성 확인
- [ ] **Catastrophic loss 빈도** — GRASS2 같은 케이스가 다시 나오는지 + tier cap이 손실 1/6 수준으로 한정하는지
- [ ] **regime별 성과** — UP/DOWN/FLAT_HIGH × long/short 분포
- [ ] **시간대별 성과** — 정각 동시 다발 fail 패턴 분석

### 7.3 Go/No-Go 기준 (200건 시점)

- **Go**: WR > 40%, PF > 1.2, 평균 EV > 0, max DD < 15%
- **No-Go**: 위 조건 미달 시 v6 또는 전략 변경 검토

### 7.4 전략 사망 판정

- 60일 rolling Sharpe < 0.5
- 100거래 승률 < 30%
- 월간 누적 PnL < 0% 3개월 연속

---

## 8. 알려진 한계 / 향후 개선 후보

### 8.1 즉시 반전 SL (전략 한계 — 가장 큰 문제)
**문제**: hold 0~3봉 SL이 전체 손실의 주요 원인. 신호 직후 trend reversal, v5.1 후에도 67% 지속.
**원인/가설**: §8.5 — adverse selection(신호가 단기 극점 포착). 진입 시점 변수론 변별 불가, "막차 탈진" 신호가 변별 후보.
**후보 대응** (검증 후 적용):
- volume spike 확인 (real momentum 식별)
- BTC regime과 alt direction 일치 필터
- 신호 직후 1~2분 가격 행동 확인 후 지연 진입 (백테스트 필요)
- pullback 진입 재검토 (v4 실패 이유 재분석 후)

### 8.2 Catastrophic Slip
**문제**: Tier Cap으로 손실 1/6 한정 가능 (검증됨). 그러나 근본 원인(저유동성 코인의 호가창 잠식)은 해결 못 함.
**후보 대응**:
- min_volume_usdt $20M → $50M~100M (universe 축소)
- 진입 직후 -10% 도달 시 강제 reduce-only market order (이중 가드)
- Bybit native trailingStop 사용 (거래소가 1초 단위 처리)
- ESPORTS 같은 고변동성 코인 별도 blacklist (1.5 ATR이 entry의 10%+ 인 코인)

### 8.3 Smart Position Sizing (현재 미적용)
**가능성**: 코인별 historical 슬리피지 데이터 누적 후 tier cap을 더 정밀하게 (예: median slip > 0.5% 코인은 추가 축소).
**제약**: 표본 부족. 50~100건 더 누적 필요.

### 8.4 Rate Limit 부하 (5/27 2단계 완화 — 부분 해결)
**문제**: 매 정각 universe scan 시 ErrCode 10006. **시간대 의존성** 명확: UTC 10/14시 (미국 시장 시간) 5~6건 폭주, 다른 시간대 1~2건 안정. sleep만으론 burst limit 한계.
**적용** (§4.6 참조): _fetch_candles 페이지 0.25→0.4, _scan 심볼 0.5→0.7, _manage 0.2→0.4.
**결과**: _manage_positions RL 4→1건 ✓. scan RL은 시간대별 큰 차이 잔존.
**5/29 재평가**: 거래 체결 실패는 retry로 회복돼 **critical 아님**으로 결론(네트워크 취약은 랜선 일회성 사고). 단 **shadow log가 데이터 소스가 된 지금** scan 누락(매 정각 47/51, RL로 4코인 skip)은 "거래 실패"가 아니라 "관측 누락" — 그 4코인 신호가 candidate에도 shadow에도 안 잡힌다.
**우선순위**: 지금 4/51(~8%)은 치명적 아님. **표본 50건+ 쌓은 뒤** universe 축소($20M→$50M, 51→~30개)로 scan 부하를 줄여 누락 해소 검토. 그 외 후보: 심볼 sleep 0.7→1.0, scan 정각+30초 분산, incremental cache 강화.

### 8.5 신호 연구 — D-소급 변별신호 (5/28, 핵심 발견)

**손실 원인 확정** (473건 분석): 패자의 **82%가 진입 직후 역행(MFE<0.5%)** = 구조적 **adverse selection**(신호가 단기 극점을 잡음). **진입 시점 변수(신호세기·변동성·BTC방향·꼬리·거래량)로는 winner/loser 변별 불가** — §5.4의 8% threshold도 단일 필터론 weak winner(NEAR/PROVE) 죽임.

**조기컷 = 막다른 길** (검증 완료, 재시도 금지):
- 인트라바 백테스트는 WR 98.7%로 실전 손실 재현 못 해 → 조기컷 **검증 자체가 불가**.
- 실전 1분봉 검증(37건): "N분내 MFE<X% 컷"은 cut 0.3%만 미세 개선, 0.5%+는 **늦게 터진 대박(NEAR/HYPE)을 죽여 역효과**(-$600~800). 시간 기반 컷으론 즉시死 vs 늦터지는 대박 분리 불가.

**변별신호 가설** (analyze_signal_features.py, 38건): "**이미 한참 오른 막차 = 탈진**"
- **선행추세** `ret_12/24`: 패자가 진입 전 이미 더 올라 있음.
- **연속 동방향봉** `consec`.
- **OI 변화** `oi_chg`: 승자=OI 증가 / 패자=OI 감소 (부호가 갈림). 예: ESPORTS(OI감소→즉사) vs XLM(OI증가→winner).
- ⚠️ **38건 표본, 다중비교·기간효과 주의. 단일필드 불완전 → 검증된 룰 아닌 가설.** 봇 로깅(§4.7)으로 표본 확대 후 재검증.

**경로**: 로깅(현재) → 표본 50건+ entered vs shadow 비교 검증 → 통계 확인 시 진입 게이트 전환(예: `oi_chg<0` 또는 `ret_12` 과도 시 skip). 상세는 메모리 `project_signal_research`.

---

## 9. 봇 실행

```powershell
cd c:\Users\PC\Desktop\현진\code\vwap_trader
.\venv\Scripts\Activate.ps1
python -m vwap_trader.momentum_bot
```

**중단**:
- 안전: `data/STOP_MOMENTUM` 파일 생성 → 다음 분에 정상 종료
- 즉시: 프로세스 kill (state.json 매 분 저장되어 손실 거의 없음)

**실전 전환 시**: [config/momentum_config.yaml](config/momentum_config.yaml)에서 `exchange.demo: true` → `false`

---

## 10. 의사결정 이력

| 날짜 | 결정 |
|------|------|
| 2026-05-21 | 5분봉 v1~v4.1 전부 실패 → 1h봉 v5 전환 + BE+Trailing |
| 2026-05-23 | 실전 WR 30% vs 백테스트 98.7% 괴리 진단 시작 |
| 2026-05-23 | 가설 검증: 인트라바 SL ❌, 유니버스 편향 ❌, 신호 검출 차이 ❌ |
| 2026-05-23 | **진짜 원인 확정**: BE/Trail 1h 폴링 지연 (HYPE1 케이스) |
| 2026-05-23 | **v5.1 시작**: 1m 폴링 적용 |
| 2026-05-24 | BE 보호 첫 검증 (NEAR2, -0.06%) |
| 2026-05-25 | LIT3 BE 보호 두 번째 검증 (-0.12%) |
| 2026-05-25 | **GRASS2 catastrophic loss** (-$1,798) → tier cap 필요성 확인 |
| 2026-05-26 | tier cap 구현 + bot_version 필드 추가 |
| 2026-05-26 | ErrCode 10002 timestamp drift → 주기적 clock resync (매 정각) 구현 |
| 2026-05-27 | Tier Cap 실제 발동 검증 (PHA/ESPORTS/GRASS 모두 Tier 4 cap 적용) |
| 2026-05-27 | signal_ret 임계값 분석 — "weak 신호가 손실 주범", 8% threshold 시 net +$1,246 추정. 표본 작아 즉시 적용 보류 |
| 2026-05-27 | slippage_cooldown state.json 저장/복원 구현 (봇 재시작 시 cooldown 정보 유지) |
| 2026-05-27 | Clock resync 매 분 강화 + balance fail 시 즉시 resync (정각만으론 부족) |
| 2026-05-27 | Rate Limit sleep 완화: 페이지 0.25→0.4, 심볼 0.5→0.7, manage 0.2→0.4 |
| 2026-05-27 | **BSB v5.1 첫 trailing winner** +23.92% (+$275, hold 38봉) — 1m 폴링 + BE/Trail 정상 작동 검증 |
| 2026-05-28 | GRASS v5.1 두 번째 trailing winner +3.63% (+$35, hold 22봉) |
| 2026-05-28 | ETH 즉시 반전 SL (-0.66%, weak signal -2.25%) — 약한 신호 즉시 반전 패턴 재확인 |
| 2026-05-28 | XPL 신규 진입 (Tier 4 cap $999.94) — 4번째 cap 발동 사례 |
| 2026-05-28 | Rate Limit 시간대 의존성 확인 (UTC 10/14시 폭주, sleep만으론 한계) |
| 2026-05-28 | **신호 연구**: 473건 손실분석 → 패자 82% 진입직후 역행 = adverse selection. 조기컷 막다른 길 확정. D-소급 변별신호 가설(ret_12/24·consec·OI, 38건) |
| 2026-05-28 | **v5.1+ 신호 컨텍스트 5필드 로깅 추가** (signal_ret_6/12/24, consec, oi_chg) — 거래로직 무영향, 가설 검증 데이터 축적용 |
| 2026-05-29 | Rate limit 재평가: 거래실패는 retry로 회복 = critical 아님. shadow log 우선 결정 |
| 2026-05-29 | **Shadow Log 구현** (`shadow_momentum.jsonl`, 9종 reason) — 걸린 신호 기록으로 생존편향 깨기. 만석도 scan-only로 신호 포착 |
| 2026-05-29 | v5.1 통계 양전환 확인 — 12건 WR 41.7% +$214 (전체 43건 -$233) |
