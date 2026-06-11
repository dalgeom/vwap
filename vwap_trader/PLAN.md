# Momentum Bot — 전략 계획서 (v6)

> 최종 업데이트: 2026-06-07
>
> 🆕 **v6 전환 (2026-06-07)**: 처음으로 거래로직 변경. ① **F1 — 역추세 진입 차단**(long in BTC-down regime / short in BTC-up 차단, shadow reason `counter_trend`). 근거: backtest n124 +$741→+$1,398, WR 35→39%, 잭팟 4/5 유지(역추세 ALLO 1건만 상실). 진입결정이라 경로·entry오염 무관해 백테스트 견고. ② **BE forward A/B** — 진입을 trade_id parity로 50/50 분할, arm A=be_trigger 1.5(control)/arm B=0.75(early BE). I3(BE 당김)는 OHLC 백테스트 불가 판정(§8.9)이라 실거래 A/B로만 검증 가능. trade/shadow record에 `bot_version:v6`·`ab_arm`·`be_trigger_atr` 기록. config: `filters.block_counter_trend`, `strategy.ab_test_enabled`/`be_trigger_atr_b`.
> 이전 펀딩 역추세 봇 PLAN은 [PLAN_funding_legacy.md](PLAN_funding_legacy.md) 참조 (폐기됨)
>
> 📌 **분석 답변 규칙 (사용자 명시 요청 2026-06-05, 모든 세션 기본값)**: 이 프로젝트의 데이터/포지션 분석을 요청받으면, 정확한 수치·근거(표·통계)는 유지하되 **반드시 비전문가도 이해할 쉬운 풀이(일상어·비유)를 함께** 제공한다. 전문용어·영어단어는 최소화하고 쓸 땐 즉시 우리말로 푼다. 따로 요청 없어도 기본. 구조: ①정확한 데이터 → ②"쉬운 설명" 비유. (상세: prom.txt §7)
>
> ⚠️ **PnL 기록 버그 3종(연쇄) — 전부 수정 완료.** 분석은 항상 거래소 closed-pnl 재구축 정본(`rebuild_pnl.py` → `data/trades_momentum_corrected.jsonl`) 사용. 원본 jsonl은 과거분 오염 잔존, unmatched는 §8.7 직접보정. ① (05-29) `_get_closed_pnl_price`가 race 시 직전거래 exit 오기록 → GRASS2 -$1,798=가짜(실 -$105), §8.2/§8.6 무효. ② (06-04) `place_order` 응답에 avgPrice 없어 entry가 신호가 fallback → `_fetch_actual_entry` 수정(§8.7). ③ **(06-05) closed-pnl 옛레코드 오매칭 — loose 1% 매칭+전파지연이 같은심볼 옛거래값 반환(STG +249→-72 오기록). freshness 게이트 수정(§8.8).** 실제 누적·통계 §5.4, 6월 분석 §5.5, 신호결론 §8.5+, 메모리 `project_pnl_recording_bug`.

---

## 1. 프로젝트 목표

Bybit USDT 무기한 선물 데모 계좌에서 **모멘텀 추종(Big Move Follow-Through)** 전략 자동 운영.
P99.5 percentile 이상 1h 봉 수익률 → 모멘텀 방향으로 진입 → BE+Trailing Stop 청산.

- **현재 단계**: **v6 운영(2026-06-07~, 첫 거래로직 변경: F1 역추세차단 + BE A/B)**, 데이터 수집 중 (**131 trades**, corrected 정본 106시점 +$1,389, 이후 거래소 직접검증. 잭팟 의존 §5.4·§8.10). **v6 잭팟 3건 전부 arm A: BEAT +$685·H +$648·VELVET +$1,359**(외 MON +45·SOL +131·ESPORTS BE−0·ALLO −126 SL). **arm B 실청산 여전 0건이나 PIPPIN(arm B) BE 첫 발동**(본전잠금, 청산 전 n=1). equity ~$25,766. 신호연구·track_f1(F1 점수판, 현 n=4 net WIN 경고등) 병행.
- **검증 임계점**: 50건(첫 평가), **200건(Go/No-Go) — 현재 131**. v6 데이터 별도 축적 중(저변동 가뭄으로 진입 느림).

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
| **v5.1+** | **2026-06-01** | **Trailing SL spike-retrace 버그 수정** (best_price 봉고점 되밀림 시 무효 SL 거부→BE floor 재확정) | **운영 중** |
| **v5.1+** | **2026-06-04** | **entry_price 버그 수정** (`place_order` 응답에 avgPrice 없어 신호가 fallback → `_fetch_actual_entry`로 실체결가 기록) | **운영 중, bar265+ 0.00% 검증** |
| **v5.1+** | **2026-06-05** | **closed-pnl 옛레코드 오매칭 수정** (loose 1% 매칭+전파지연이 같은심볼 옛거래값 반환 → `createdTime>=진입시각` freshness 게이트) | **운영 중, §8.8** |
| **v6** | **2026-06-07** | **첫 거래로직 변경**: F1 역추세 진입 차단(`block_counter_trend`) + BE forward A/B(arm A 1.5 / B 0.75, trade_id parity 50/50) | **적용 완료, 재가동 대기. bot_version=v6** |

---

## 4. v5.1 변경 사항 (요약)

v5 백테스트 WR 98.7% vs 실전 30% 괴리의 원인은 **BE/Trail 폴링 지연**(HYPE1: be_triggered인데 SL 초기값 → -2.81%). 진단 과정(4가설 기각)은 §10 의사결정 이력 참조.

| 변경 | 계기 | 효과 / 검증 |
|------|------|-------------|
| **1m 폴링** (`_main_loop` 분리) | BE/Trail 1h 지연 (HYPE1) | 매 분 BE/Trail 갱신, 정각만 scan. NEAR2/LIT3 BE 보호 ✓ |
| **Tier Cap** (`_apply_tier_cap`) | GRASS2 -30.1% / -$1,798 (⚠️ **버그였음**, 실제 -$105 — §8.2 철회) | 24h volume 기반 notional 축소. 4건 발동. **동기 무효 → 재검토 대상** |
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

## 5. 운영 현황 스냅샷 (2026-06-05 기준, 106 trades — 봇 가동 중이라 변동, 최신은 rebuild_pnl.py 재실행)

> 실시간 데이터는 [data/trades_momentum.jsonl](data/trades_momentum.jsonl), [data/state_momentum.json](data/state_momentum.json) 직접 참조. **분석은 항상 corrected**([data/trades_momentum_corrected.jsonl](data/trades_momentum_corrected.jsonl), `rebuild_pnl.py`로 재생성). 원본 jsonl은 v5.1+ 신규분만 정확(`pnl_source:exchange`), 과거분·일부 신규분(§8.8 STG 등)은 버그 오염 잔존.

### 5.0 계좌 레벨 (cumRealisedPnl 항등식, 2026-06-01 감사 — 1회성)
- **데모 초기 지급 = $40,000.00 확정** (walletBalance + cumRealisedPnl −$15,834.76 = 정확히 $40,000 → 추가입금·보너스 없는 단일 지급).
- **현재 totalEquity ~$24,050** (미실현 +$436 포함, 06-05 직접조회). 계좌 평생 실현 ≈ −$16k (−40%).
- ⚠️ 이 손실은 **거의 전부 5분봉 v1~v4 시대(전부 실패) 손실**(≈ −$17.7k 역산). **1h봉 v5/v5.1 시대(106건 corrected) = +$1,389 = 우상향.** 봇 평가는 v5 시대만 유효, 과거 era는 무관.
- 데모 API는 transaction log ~1일·closed_pnl 40건만 보관 → 과거 날짜별 조회 불가. v5 완전본은 로컬 corrected jsonl이 유일.

### 5.1 누적 추이 (역사 압축)
- 데이터셋 성장: 64건(06-01, +$2,025) → 93건(06-04, +$1,900) → **106건(06-05, +$1,389)**. 누적 감소는 6월 적자(§5.3) 반영. 모든 시점 `rebuild_pnl.py` deterministic 1:1 재구축.
- ★ **냉철히**: 누적 흑자는 **잭팟 소수건에 전적 의존.** fat-tail winner 전부 TrailSL(BEAT+895·NEAR+719·PORTAL+649·ALLO+624·BSB+541·HYPE+373·STG+250). catastrophic 손실은 부재(최대 −$148대). **edge는 잭팟 빈도/크기 의존 — 안정성 단정 불가, 표본 계속 축적.** ⚠️ 데모 closedPnl=시뮬레이션값(실거래 슬리피지 별개).

### 5.2 106건 통계 분해 (2026-06-05 corrected, STG·H 보정 후)

> 전체: n106, WR 36.8%, 누적 +$1,389.11, EV +$13.1, PF 1.23. ⚠️ rebuild unmatched 잔존 EPICUSDT(−73.58, 값은 거래소와 일치). 보정이력 §8.8.

| 분해축 | 그룹 | n | WR | EV/건 | 비고 |
|--------|------|---|-----|-------|------|
| **hold** | ≤2 (즉사권) | — | 낮음 | **음(−)** | 손실의 원천 = H1 adverse selection (06-04 n93: ≤2 EV−$77 vs ≥3 +$104) |
| | ≥3 | — | 높음 | **양(+)** | 살아남으면 이김 |
| **exit** | TrailSL/Timeout | — | ~95% | 큰 양(+) | **전략의 전부**(잭팟) |
| | SL | — | 0% | 큰 음(−) | 손실 전부 |
| | BE | — | — | ~0 | MFE 반납 청산 |
| **\|sigret\|** | <10 | — | — | 약한 음 | 약신호 |
| | 10–20 | — | — | **양(+)** | **sweet spot** |
| | ≥20 (극단) | — | 낮음 | **음(−)** | 손해 편향, 단 잭팟 동반(5월) |

> 분해축 절대수치는 06-04 n93 기준이 가장 정밀(§10 이력). 106건에서도 ① 즉사(hold≤2)=손실 전부 ② TrailSL=흑자 전부 ③ sigret 비선형(중간 최고, 극단 손해) **세 결론 모두 유지**. 6월만 떼면 더 선명(§5.3).

**핵심**: ① 즉사가 손실 전부 = H1. ② TrailSL이 흑자 전부 = 잭팟 의존 정량확인. ③ sigret 비선형 → I6 동기, 단 단순컷 부결(§11).

### 5.3 6월 거래 분석 (2026-06-05 corrected 41건 — 깨끗한 데이터)

> **6월 실현 −$798.09, WR 34.1%, EV −$19.47, PF 0.64 → 6월은 적자.** 전체 누적 흑자는 5월 잭팟 덕이고 6월은 갉아먹는 중. 단 risk 건당 통제(대부분 −$100~130대).

| 분해 | 그룹 | n | PnL | EV | 비고 |
|------|------|---|-----|-----|------|
| **exit** | TrailSL | 11 | +$1,037 | +$94 | 생명줄 |
| | Timeout | 2 | +$337 | +$168 | STG+250·EDGE+87 |
| | SL | 24 | **−$2,179** | **−$91** | WR 0/24, 학살 |
| **hold** | ≤2 즉사 | 19 | **−$1,040** | **−$54.75** | H1 재확증 |
| | ≥3 | 22 | +$242 | +$11 | |
| **\|sigret\|** | ≥20 극단 | 6 | **−$651** | **−$108** | **WR 0/6 전멸**(PORTAL·ALLO·LAB93·US·EPIC·OPN) |
| | 10–20 | 7 | +$387 | +$55 | sweet spot |
| | <10 | 28 | −$534 | −$19 | 약신호 |
| **방향** | long | 30 | **−$726** | −$24 | 6월 학살 주범 |
| | short | 11 | −$72 | −$6.6 | |
| **regime** | UP_HIGH | 13 | +$287 | +$22 | 유일 흑자 |
| | FLAT_HIGH | 14 | **−$652** | −$47 | 최악 |
| | DOWN_HIGH | 10 | −$173 | −$17 | |

> ★ **H1(즉사)·sigret 극단=손해는 6월에도 견고**(오히려 더 선명: 극단 6건 전멸). 단 **방향·regime은 §5.2(5월 누적)와 뒤집힘** — 6월 long·FLAT_HIGH가 최악(§5.2는 long·DOWN/FLAT 우위였음). 시장이 하락/횡보라 long 막차가 터진 것. **표본 작아 노이즈 가능 → 200건 전 게이팅 금지** 재확인.

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

### 8.2 Catastrophic Slip — ⚠️ 무효 (2026-05-29 철회)
**철회 사유**: 이 항목의 유일한 근거 GRASS2 -$1,798은 **PnL 기록 버그**였음. 거래소 closed-pnl 실제 -$105.08 (exit 0.40264 오기록 ← 실제 0.56438, 직전 거래값 혼입). 재구축 47건 **최대 손실 -$135로 catastrophic loss 부재.** 저유동성 호가창 잠식 문제는 데이터상 존재한 적 없음. → **Tier Cap(§2.3)의 동기 소멸** → 별도 재검토 필요(현재 ALLO/NEAR 등 위너 사이즈를 불필요하게 깎고 있을 수 있음).
**단, 데모 계정 한계**: closedPnl은 시뮬레이션값. 실거래 전환 시 저유동성 슬리피지는 별도 검증 필요 — 아래는 그때 참고용 후보로만 보존(현재 미적용):
- min_volume_usdt $20M → $50M~100M / 진입 직후 -10% 강제 reduce-only / Bybit native trailingStop / 고변동성 blacklist

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

> ⚠️ **5/28 원문은 PnL 버그 오염 라벨 기반 → §8.5+에서 corrected 64건으로 재계산 완료.** 아래 손익규모는 참고용, **확정 결론은 §8.5+** 참조. (MFE/MAE 기반 "82% 즉시역행" 방향성은 corrected에서 57.5%로 유지됨.)

**손실 원인 확정** (473건 분석): 패자의 **82%가 진입 직후 역행(MFE<0.5%)** = 구조적 **adverse selection**(신호가 단기 극점을 잡음). **진입 시점 변수(신호세기·변동성·BTC방향·꼬리·거래량)로는 winner/loser 변별 불가** — §5.4의 8% threshold도 단일 필터론 weak winner(NEAR/PROVE) 죽임.

**조기컷 = 막다른 길** (검증 완료, 재시도 금지):
- 인트라바 백테스트는 WR 98.7%로 실전 손실 재현 못 해 → 조기컷 **검증 자체가 불가**.
- 실전 1분봉 검증(37건): "N분내 MFE<X% 컷"은 cut 0.3%만 미세 개선, 0.5%+는 **늦게 터진 대박(NEAR/HYPE)을 죽여 역효과**(-$600~800). 시간 기반 컷으론 즉시死 vs 늦터지는 대박 분리 불가.

**변별신호 가설** (analyze_signal_features.py, 38건): "**이미 한참 오른 막차 = 탈진**"
- **선행추세** `ret_12/24`: 패자가 진입 전 이미 더 올라 있음.
- **연속 동방향봉** `consec`.
- **OI 변화** `oi_chg`: 승자=OI 증가 / 패자=OI 감소 (부호가 갈림). 예: ESPORTS(OI감소→즉사) vs XLM(OI증가→winner).
- ⚠️ **38건 표본, 다중비교·기간효과 주의. 단일필드 불완전 → 검증된 룰 아닌 가설.** 봇 로깅(§4.7)으로 표본 확대 후 재검증.

**신호는 더해지지 않고 곱해진다 — interaction (5/29 실증)**: 단일 필드 필터는 전부 반례에 무너짐. 핵심 대조:
- **ALLO** (+44% 최대 winner): `ret_12=73·ret_24=108`(극단 막차), `signal 99.8`(초강), `DOWN_HIGH`(역추세 long) — **모든 위험 플래그 red인데 대박**. OI **+5.5**.
- **ESPORTS** (-9% 즉사): 동일하게 극단 막차·강신호인데 OI **-2.9**.
- 차이는 **OI 부호 하나**. → **막차 + OI↑(실수요) = 폭발 / 막차 + OI↓(가짜) = 붕괴.** ret_12의 의미가 OI에 따라 정반대로 뒤집힌다.
- 결론: "극단=대박"도 "극단=죽음"도 아니다. **조합의 코너에서만 갈린다** → 단일 필드 필터가 다 실패한 근본 원인. 미래 룰은 linear 필터가 아니라 **decision-tree식 비선형/상호작용**이어야 한다.
- ⚠️ 극단 표본 2건(ALLO/ESPORTS) — 가설. ALLO만 기억하는 selection bias 경계.

**경로**: 로깅(현재) → 표본 50건+ → **극단 신호 진입을 OI 부호로 쪼개 OI↑ 그룹이 체계적으로 이기는지 검증**(8:2면 interaction 실재, 5:5면 ALLO는 운). 단일 필드 필터 적용 금지(weak/극단 winner 죽임). 상세는 메모리 `project_signal_research`.

### 8.5+ 재계산 결과 (2026-06-01 corrected 64건, deterministic 1:1)

위 §8.5 5/28 원문·"재검토 필요" 박스는 **PnL 버그 오염 라벨 기반**. 거래소 closed-pnl 재구축으로 갱신(64건):
- **WR 37.5%, 누적 +$2,025, PF 1.54**(승합 +$5,776/패합 -$3,750). 잭팟 의존 — §5.1.
- winner: 100% TrailSL/Timeout, hold median ~11봉, avg MFE +19.7%. loser: SL 위주, hold median 2봉.
- ★ **adverse selection 확인(약화 아님)**: loser 중 MFE<0.5% = **57.5%**, winner MFE<0.5% = **0%**. 즉시역행이 손실 주 메커니즘. winner는 예외없이 초반 유리하게 감.
- **OI 단순 부호로는 변별 불가 (확정)**: ctx 25건 — oi+ 15건 WR40%/+$95, **oi- 10건 WR30%/+$545**. OI 음수 그룹이 총액 오히려 큼(ALLO·PORTAL 잭팟 포함). "OI↑=좋다" 단일 필터 **틀림.** §8.5 가설은 "막차 AND oi↓" 조합이지 단순 부호 아님.
- ★★ **"극단 막차(ret24>50%)"는 위험 편향이나 잭팟 예외 존재**: ret24>50 진입 4건 = **ALLO(+624, ret24=108, 최대급 잭팟!)** · ID(-88) · HEI(-131) · PORTAL(-119) → **1승 3패이나 합계 +$286**(ALLO가 3패 덮음). → 막차는 손실 편향이지만 ALLO 같은 폭발이 섞여 **단순 ret24 상한 필터는 그 잭팟을 죽인다** = 단일 필드 필터 금지 재확인. n=4 소표본.
- ⚠️ 데모 계정 closedPnl(시뮬레이션값). 스크립트 `rebuild_pnl.py`·`analyze_signal_corrected.py`.

### 8.6 Tier Cap 재검토 (2026-05-29)
- 도입 근거 GRASS2 catastrophic(-$1,798)이 버그였음(실 -$105) → **원래 동기 무효.**
- corrected 분석: 캡은 저유동성 ~$1,000 tier4 거래 ~7건에 binding, **양 꼬리 모두 클립**(손실 ~-$194 방지 + 소액 winner 절단). counterfactual은 필터별로 불안정해 순효과 단정 불가.
- **결정: 캡 제거 안 함**(실거래 저유동성 슬리피지 대비 합리적 가드). 단 fat-tail 우측꼬리 절단 비용 실재 → **live 실슬리피지 데이터 후 tier4 $1,000→$2,000 완화 또는 universe min_vol 상향($20M→$50M) 재검토.** 현재 config 미변경.

### 8.7 entry_price 버그 & rebuild unmatched (2026-06-04 수정)
- **버그(2종 중 entry 계열)**: `place_order` 응답에 체결가 없는데 `result.get("avgPrice")`로 읽음 → 항상 0 → entry_price가 **신호가(직전봉 종가)로 fallback**. 막차일수록 실체결과 괴리(H +2%). 영향: ① slippage 로그 전부 0(무용, H10 검증불가) ② BE/trail floor가 신호가 기준이라 실제 본전 아님(실매매 손해) ③ rebuild가 entry로 매칭하다 막차 winner를 **unmatched로 떨굼**.
- **수정**: `_fetch_actual_entry(symbol,side)` — 시장가 직후 0.4s 후 `get_positions` avgPrice. positionIdx Buy=1/Sell=2. 실패 시 신호가 fallback. **bar265+ 진입부터 entry==avgPrice 0.00% 검증.** 과거분 무영향.
- ⚠️ **corrected 정본도 unmatched는 오염**: H(c7c674b4)가 estimated +$611 유지(`unmatched_keep_recorded`), 거래소 실값 **+$568**. **rebuild 후 unmatched_list는 `get_closed_pnl(symbol)`로 직접 보정 필수.** (수정으로 신규분은 해소.)

### 8.8 closed-pnl 옛레코드 오매칭 버그 (2026-06-05 수정 — PnL 버그 3번째·연쇄)
- **증상**: STG Timeout 청산(MFE 24.7%, 진짜 **+$249.54**)이 live jsonl에 **−$71.77**(이전 STG SL거래값)로 기록. `pnl_source=exchange`인데도 부호 반대 → 오늘 6건 jsonl합 −$434 vs 거래소 −$112(차 전부 STG 한 건).
- **근본원인**: `_get_closed_pnl_record`(05-29 첫 수정본)가 side+entry±1%+qty±1% 매칭하는데, 같은 심볼 STG short 2건(06-02 entry 0.31155 vs 06-04 0.3092 = **0.76% 차**, qty도 0.76%)이 **둘 다 1% 허용오차 통과**. 청산 직후 신선 레코드 미전파 상태에서 옛 06-02 레코드만 존재 → matches 비어있지 않아 retry 없이 **즉시 옛 레코드 반환**(exit·pnl 글자그대로 복사). retry는 "matches 빔"만 보고 "stale 매칭 존재"는 못 거름. **loose 1% 매칭 + 거래소 전파지연 조합** = 같은 심볼 entry 1% 이내 2회+ 거래하면 누구나 교차오염.
- **수정**: `_get_closed_pnl_record`에 **freshness 게이트** — closed-pnl 레코드 `createdTime >= 진입시각(pos.entry_time ms)`인 것만 매칭. 옛거래(타 거래 진입 전 청산) 자동배제, 신선 레코드 미전파 시 matches 비어 retry 정상작동. **실증검증은 미래 동일심볼 반복거래 청산 때** 로그 `Closed PnL matched ...(try N)`로 (라이브 거래소 의존이라 단위테스트 불가).
- **과거 복구(06-05)**: rebuild_pnl.py 재실행 → STG는 orderId 1:1 할당으로 −71.77→**+249.54 자동정정**(+321). HUSDT unmatched는 거래소 직접조회로 +611.71→**+568.12 수동보정**(corrected 직접패치, `exchange_avg_entry` 추가). EPICUSDT −73.58은 거래소와 일치(라벨만 unmatched). **corrected 최종 106건 +$1,389.11.**
- **★ 실증검증 완료(2026-06-05)**: 06-05에 **ZEC가 short→long→short 3회 반복 청산**되며 셋 다 거래소 closed-pnl과 dt 0~1초로 정확 1:1 매칭(+628.75/−121.46/−124.58), 옛값 복사(−71 류) 재발 0건. 같은 심볼 1% 이내 반복거래에서 freshness 게이트가 실거래로 정상작동 확인 → 버그 종결.

### 8.9 BE-trigger(I3) 백테스트 불가 판정 + F1 backtest 채택 (2026-06-07)

- **동기**: 사용자 관찰 "green이던 포지션이 red로 청산" = BE 트리거가 **중앙값 +3.9%(1.5ATR)**로 멀어, 그 전엔 SL이 초기 −1.5ATR(손실선)에 방치 → +2~3% 떠 있어도 무방비. 손익해부: 패자 80건 중 즉시역행(MFE<0.5%) 46건(−$4,799, 출구로 불가) vs **green→red 28건(−$2,211, BE 당기면 구제가능)**.
- **I3 backtest 시도(1m 경로 replay)**: 봇 stop 로직(초기 1.5ATR→BE시 entry→best∓2ATR trail+spike-retrace 가드)을 1m klines로 재생. **baseline(be=1.5) 검증 실패** — 전체 124건 replay −$286 vs 실제 +$741. cohort 분리하니 원인 확정: **PRE-fix 98건(entry_price 버그 §8.7, 5월 잭팟 전부)은 entry 기준점 오염으로 재현 불가**(PORTAL replay +16 vs 실제 +649), POST-fix 26건만 신뢰(replay −1,495 vs 실제 −1,265, 오차 $20/건).
- **결론**: 잭팟이 전부 entry오염 구간에 있어 **BE 당김의 핵심 trade-off(잭팟 ejection)를 역사 데이터로 측정 불가**. POST-fix clean 26건(잭팟 없는 drawdown)에선 be 1.5→0.5가 +$258 출혈감소이나 **같은 레벨(be≤1.0)이 잭팟을 ejection**(full-sweep BEAT/ALLO/PORTAL 붕괴, MAE 메커니즘 일치). drought엔 약·잭팟엔 독, 같은 손잡이 → **net 판정 불가, forward A/B만이 유효** → v6 BE A/B 도입.
- **F1(역추세 제거)은 대조적으로 견고**: 진입 결정이라 intra-trade path·entry오염 무관. n124 backtest +$741→+$1,398(WR 35→39%, EV +6→+14), 잭팟 4/5 유지(역추세 ALLO만 상실, 23건 역추세 합 −$657·WR22%). 이론 정합(추세 거스르지 마라). → v6 즉시 적용 채택. ⚠️ in-sample·regime분류(btc_4h) 5월/6월 flip 위험은 잔존 → forward로 계속 확인.
- 도구: `backtest_be.py`(1m 경로 replay, POST-fix 거래에선 유효). entry버그 없는 거래가 쌓일수록 신뢰도 상승.

### 8.10 세 팩터 조합분석 (2026-06-11, 85건 — 연속성·돈흐름·파도크기)

사용자 요청으로 신호 시점 3팩터를 이분(good/bad)해 8조합 교차분석. 데이터셋 = corrected 정본 ctx 67 + raw 신규(ctx+exchange) 18 = **85건**(총 +$918, WR 36%). good 정의: **연속성**(`signal_consec≥2`, 직전 2봉+ 동방향) / **돈흐름**(`signal_oi_chg>0`, OI 증가) / **파도크기**(`|signal_return_pct|` 10~20%, sweet spot).

| good 개수 | n | 총손익 | 비고 |
|---|---|---|---|
| 0개 | 20 | −$192 | |
| 1개 | 45 | −$289 | 파도크기만(n6 **+$1,176** WR67%)만 흑자 / 연속성만(n10 −$488)·돈흐름만(n29 −$977) 적자 |
| 2개 | 20 | **+$1,399** | 흑자 전부 |
| **3개 다** | **0** | — | 셋 다 good은 85건 중 0건(완벽신호 부재) |

★ **핵심: 잭팟이 "good 칸"에 안 모인다** — BEAT/PORTAL(파도크기만), H +648(파도 **bad**=막차 −35%지만 연속성·돈흐름 good), **ZEC +629(셋 다 bad!)**, ALLO(돈흐름+파도). 두 대박 프로필이 정반대 → "good 신호만 골라 진입"하면 ZEC/H 잭팟을 죽인다 = §8.5 "단일/조합 단순필터 실패, interaction은 코너에서만" **재확인**. ⚠️ 칸당 2~6건 극소(파도크기만 +$1,176도 BEAT+PORTAL 2건 착시), 85건/8칸 통계무의미 = **사후 탐색이지 미래 룰 아님. 200건 게이트·데이터마이닝 금지**(H6/H7/H15 교차 = §11 일괄검정 대상).

**추가 팩터 후보(미적용, 표본 우선)**: ① 이미 기록 중·미분석 = **선행추세(`signal_ret_6/12/24`=진입 전 막차 정도)** 0순위 분석대상, regime·atr절대값·시각/요일·사이즈. ② 미기록 신규후보 = ★**거래량(volume, 진짜모멘텀 vs 얇은호가 가짜)** 1순위 로깅추가 가치(§8.1 기지목), 가격위치·봉모양·funding·시장동반성. ⚠️ 팩터 증식 = 다중비교 데이터마이닝, **표본이 먼저**(85건으론 3팩터도 못 가름).

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
| 2026-05-23 | **실전 WR 30% vs 백테스트 98.7% 괴리 진단**: 인트라바SL·유니버스·신호검출 ❌ 기각 → **진짜 원인 = BE/Trail 1h 폴링지연(HYPE1)** → **v5.1(1m 폴링) 시작** |
| 2026-05-24~27 | v5.1 운영검증: BE보호(NEAR2/LIT3), trailing winner(BSB +$275), tier cap 발동(GRASS2 −$1,798이 도입계기·후에 버그판명), clock resync·cooldown state·RL sleep 완화 구현. signal_ret 임계분석(weak=손실주범, 8%컷 +$1,246 추정·표본부족 보류) |
| 2026-05-28 | **신호연구 473건**: 패자 82% 진입직후 역행 = adverse selection, 조기컷 막다른길 확정. 변별가설(ret_12/24·consec·OI). **신호컨텍스트 5필드 로깅 추가**(`signal_ret_6/12/24`·consec·oi_chg, 거래로직 무영향) |
| 2026-05-29 | **Shadow Log 구현**(`shadow_momentum.jsonl`, 걸린신호 기록=생존편향 깨기). **ALLO +$644 최대winner**(역추세 막차 잭팟). **interaction 가설**(막차+OI↑=폭발/OI↓=붕괴, 단일필터 실패 근본원인). **★ PnL버그 발견·수정**(`_get_closed_pnl` race로 직전거래 exit 오기록, GRASS2 −$1,798=가짜 실−$105) + **거래소 재구축**(47건 1:1, 실제 **+$2,010**, tier cap 동기 무효 §8.2/§8.6, `trades_momentum_corrected.jsonl` 생성) |
| 2026-06-01 | **trailing SL spike-retrace 버그 수정**: best_price(봉 고점) 되밀림 시 trail SL이 현재가 초과 → Bybit 10001 거부 + 롤백으로 SL 초기값 묶임. 가드 추가(trail이 현재가 침범 시 entry/BE floor 재확정). H 0.5121→0.5440 복구 검증 |
| 2026-06-01 | **사전등록 가설 보드(§11) 등록** (65 closed 시점) — 진입선별 1렌즈 편중 교정. Primary 6 / Secondary 8 / Null 1 + v6 개입후보 5 분리. OI 가설 검정력 한계 명시(Secondary 강등) |
| 2026-06-01 | **계좌 감사**(§5.0): 데모 시작 **$40,000 확정**(cumRealised 항등식). 평생 −$15,835(5분봉 시대 ≈−$17.7k가 지배), **v5/v5.1 시대 +$1,912=우상향**. 데모 API 단기보관으로 과거 날짜조회 불가 |
| 2026-06-01 | **OI 가설 반례 누적**: PORTAL(OI+4.3, 최극단막차 ret24=140) −9.8% 즉사 / H(OI−0.2) +20% 최대 winner → "막차+OI↑=폭발" 반증. §8.5+ "단순부호 변별불가" 재확인. ⚠️오픈 미실현, peeking 금지 |
| 2026-06-01 | **PC 핸드오프**: 정각(15:00) 정전·DNS 단절 무해 — 진입+SL atomic(place_order 동봉), 재시작 후 state↔거래소 reconcile **완전일치**(orphan/phantom 0). bar 261, 5 positions(short3: ASTER·ALLO·HOME / long2: H·STG) |
| 2026-06-04 | **entry_price 버그 수정**: `place_order` 응답에 avgPrice 없어 entry가 신호가로 fallback → slippage 로그 전부0·BE floor 신호가기준(실본전 아님)·rebuild 매칭실패(막차 winner unmatched). `_fetch_actual_entry`(시장가 직후 get_positions로 실 avgPrice) 추가, bar265+ 0.00% 검증. 메모리 `project_pnl_recording_bug` 갱신 |
| 2026-06-04 | **93건 통계 분해**(§5.4): hold≤2 즉사 EV−$77 vs hold≥3 +$104(H1 확증), TrailSL 32건이 흑자 전부, sigret 비선형(10–20 sweet spot/≥20 손해). **I6 등록**(극단 sigret 상한/축소) + **백테스트 부결**(컷 민감=overfitting, 잭팟 컷경계 산재, n93 채택불가) — §11 |
| 2026-06-04 | **rebuild unmatched 주의**: entry_price 버그로 막차 winner가 entry매칭 실패→corrected가 estimated 유지. H(c7c674b4) +611(오염) vs 거래소 진짜 +568. unmatched_list는 get_closed_pnl 직접보정(§8.7) |
| 2026-06-04 | **PC 핸드오프**: bar 326, 95 closed, 3 positions(전부 short: EDGE·STG·HOME). 손실 3클러스터(−$591) 후에도 risk 통제(건당 0.5%), 변경 없이 표본 축적 지속 결정 |
| 2026-06-05 | **closed-pnl 옛레코드 오매칭 버그(3번째 PnL 버그) 발견·수정**: STG Timeout +$249.54가 −$71.77(이전 SL거래값)로 오기록. loose 1% 매칭+전파지연이 같은심볼 옛레코드 반환. `createdTime>=진입시각` freshness 게이트 추가(§8.8). 봇 재시작으로 적용 |
| 2026-06-05 | **과거 데이터 복구**: rebuild_pnl.py 재실행 → STG +321 자동정정, HUSDT unmatched +611→+568 수동보정. corrected 정본 106건 **+$1,389.11**(WR 36.8%, EV +$13.1, PF 1.23) |
| 2026-06-05 | **6월 분석**(§5.3, corrected 41건): 6월 실현 **−$798**(WR 34.1%, PF 0.64) 적자. H1(즉사)·sigret 극단=손해 재확증(극단 6건 WR0/6 전멸). 단 방향·regime은 5월과 뒤집힘(6월 long·FLAT_HIGH 최악) = 표본 노이즈, 200건 전 게이팅 금지 재확인 |
| 2026-06-05 | **PC 핸드오프**: bar 352, 106 closed, 3 positions(전부 short: ZEC·XMR·ZRO, 미실현 +$436, ZEC가 +$382 잭팟후보). totalEquity ~$24,050. 변경 없이 표본 축적 지속 |
| 2026-06-05 | **6월 심층분석 + §11 갱신**: 6월 손실 본질 = long against-btc 11건 −$747(short는 본전~흑자). **`short_cap`=3이 하락장 short신호 47건 중 23%만 통과시켜 올바른 방향 차단 = 신규발견**. consec0 고립스파이크 17건 −$766 최악. 트레일링·BE는 정상작동(BE트리거 1.5ATR 도달 3건 본전), 손실 다수는 즉시역행(MFE<0.5% 15/27건)=출구 아닌 입구 문제. **H14(cap 비대칭)·H15(consec) Primary 신규등록**. 6월 단독근거라 즉시 게이팅 금지, 200건 일괄검정 |
| 2026-06-05 | **PC 핸드오프(인계)**: bar 354, 106 closed, 3 positions(전부 short: ZEC·XMR·ZRO, ZEC best 373.61=잭팟후보·be잠금, XMR be잠금, ZRO 미잠금). STOP_MOMENTUM으로 graceful 종료 후 push. 코드 무변경, 표본 축적 지속. 분석 답변=쉬운 설명 규칙 신설(상단 📌·prom.txt §7·메모리) |
| 2026-06-06 | **신 PC 재가동 + §8.8 freshness 수정 실증검증 완료**: ZEC 3회 반복청산(short+628.75/long−121.46/short−124.58) 전건 거래소 1:1 정확매칭, 옛값오염 재발0 → 버그 종결(§8.8). 06-05 청산 7건(거래소 대조 전건일치) 실현 +$190.48(잭팟 ZEC+628 빼면 −$438, long4건 전멸·short net+547=6월 방향패턴 재현). shadow 06-05 40건: short_cap 26건(25 DOWN_HIGH=추세순행 차단, H14 정황) vs rank_cutoff 14 long(17:00 UP군집). **전부 기존가설 재확인·소표본·forward미확정 → §11 무변경, peeking 금지, 200건 일괄검정 유지** |
| 2026-06-07 | **심층 자아성찰 분석 + 선별진입 backtest**(n124): 누적 정점 06-01 +$2,025 → 현재 **+$741**(6일 drawdown 실재, 잭팟 가뭄). 손실해부: 패자 80건 중 즉시역행(MFE<0.5%) 46건 −$4,799(출구로 불가) vs green→red 28건 −$2,211(BE로 구제가능). 하드TP 시뮬: 모든 익절선이 +$741→음수(잭팟 절단). **F1(역추세 제거) backtest +$741→+$1,398**(잭팟 4/5 유지)=가장 견고. I3(BE 당김) 1m 경로replay: PRE-fix 잭팟 entry오염(§8.7)으로 **백테스트 불가 판정**(§8.9), POST-fix clean 26건만 신뢰(BE 1.5→0.5 +$258 출혈감소이나 같은레벨이 잭팟 ejection) → forward A/B 필요 |
| 2026-06-07 | **★ v6 전환 (첫 거래로직 변경, 사용자 지시)**: ① **F1 역추세 진입 차단** 적용(`block_counter_trend:true`, shadow `counter_trend`) ② **BE forward A/B** 가동(trade_id parity 50/50, arm A 1.5/B 0.75, `ab_test_enabled`). bot_version=v6, trade record `ab_arm`/`be_trigger_atr` 추가. 검증: import·직렬화 round-trip·legacy호환·config·50/50 split·F1 로직 전건 통과. 기존 오픈포지션은 legacy(arm A) 처리. 사용자가 직접 종료·재가동. **이후 데이터는 v6로 축적, A/B는 arm별 실현PnL 비교로 검정** |
| 2026-06-08 | **v6 첫 운영 결과(~16h, bar 420, 126 trades)**: v6 청산 2건 +$729.51 — **BEAT long arm A TrailSL +$684.69**(MFE53.5%/MAE0.23% 잭팟)·MON legacy +$44.82. BEAT=arm A(옛BE)라 **BE변경 검증 아님**, 단 **F1이 추세순행 잭팟은 통과**(백테스트서 죽인 ALLO는 역추세였음). F1 차단 2건(HOME short/WLD long). **★ track_f1.py 신규**(막은 counter_trend의 would-be 결과 R-배수 점수판): 첫판독 HOME 막은 게 **소급 +29%(+2.6R) winner**=F1 약점 라이브(ALLO 동형), WLD 본전. 확정0.0R·HOME포함+2.6R, **n=2라 결론보류**(124건선 역추세 net−$657=장기F1이득 기대). equity $22,994→~$23,900 회복 |
| 2026-06-08 | **PC 핸드오프(인계)**: bar 420, 126 closed, 2 positions(둘다 legacy: SOL long BE잠금·ALLO short sigret−26.5 극단·BE미잠금). v6 가동중 graceful 종료 후 push. prom.txt v6 갱신. 신 PC서 git pull→재가동. **추가변경 금지, v6 표본(arm A/B·counter_trend) 축적이 1순위** |
| 2026-06-08 | **신 PC 재가동 6h 운영(코드 무변경)**: 2포지션 청산 — SOL long Timeout **+$131**(best67.06→65.43 만기)·**ALLO short SL −$126** green→red 실증(best 0.29144=+13%→0.41473). 순≈본전, equity~$23,724, 청산 후 무포지션(128 closed). ★ **ALLO 반사실**: arm A BE발동가 0.262 미도달이나 **arm B(0.75ATR)=0.299는 best 통과→본전이었을 사례**(메모리 `project_be_ab_allo_case`, n=1 단정금지). ★ **v6 진입급감(13→1건)은 F1 무관=신호가뭄**(F1 counter_trend 2건만 차단, 06-07 shadow도 2건뿐). 핸드오프(bar 427, STOP graceful 종료 후 push) |
| 2026-06-09 | **신 PC 운영 지속(코드 무변경)**: HUSDT short **TrailSL +$648.08(+66.8%, arm A, v6 잭팟)** 청산(어제 미실현 정점 +$819 → 트레일링 되돌림 −$171 허용하고 확정, 청산가 0.13378). **★ v6 코드 무죄 3중검증**(사용자 "하루아침에 진입 마름" 의심 대응): ① F1은 신호 탐지 *후* 차단하며 **반드시 shadow 기록** → 06-08~09 shadow 0건 = F1이 막은 것도 0 = `feed_candle` 탐지단계서 이미 0. ② 봇로그 scan 정상(`38/40 scanned, 0 candidates`, Traceback 無, ERROR는 전부 10006 rate-limit retry회복). ③ **봇코드 완전우회 독립 klines P99.5 계산**: BTC/ETH/SOL/DOGE/XRP/BNB 최근24봉 신호 **0**(마지막봉 0.5~1.4% vs 임계 2~3%), **HUSDT만 5건**(탐지로직 정상 반증) → 진입가뭄=코드무관, 100% 시장 저변동. **거시배경(웹검색)**: Fed 금리인하 기대소멸(2026 0회 68.8%·신의장 Warsh 매파·10yr 4.45%) + 비트코인 ETF 사상최대 주간유출 $3.4B + 고래매도 + 미-이란 긴장 → 6월초 BTC −12%($72.8k→$64.1k, 봇기록 entry BTC $63.4k와 정합) 급락 후 **유동성 고갈 횡보**(여름까지 지속 전망). 모멘텀봇에 구조적 불리(큰파도 부재), 단 개별알트 폭락(H)은 산발. **★ 첫 arm B 실진입: PIPPINUSDT short**(be_trigger 0.75ATR) — 한때 +6.4%(+$51) 이익에도 **BE 미발동**(best가 0.75ATR 문턱 미도달 = 변동성 큰 잔챙이알트는 ATR이 커서 0.75ATR도 멀다, **첫 관찰**), 이후 green→red(+$51→−$22) 진행. **arm B 첫 표본 생성(n=1 오픈, 결론보류)** — 청산 결과(특히 BE 끝까지 미발동 여부) 기록가치. ★ **트레일링 한계 정리(사용자 문답)**: 100% 완벽 트레일링 불가능(타이트=green→red막으나 잭팟 ejection / 느슨=잭팟 살되 반납, 같은 다이얼 trade-off). green 절대 red금지=가능하나 잭팟 증발(§8.9 실증). **손실 대부분은 즉시역행 46건 −$4,799=트레일링으론 불가(입구문제), green→red 28건 −$2,211만 BE로 일부구제** → 레버는 ATR배수뿐 아니라 입구(F1)·부분익절(I2)·사이징. 무변경, 표본축적 지속 |
| 2026-06-10 | **track_f1 중간판독 n=4 (이전 n=2 → 확대)**: F1이 차단한 counter_trend 4건 would-be 결과 **전부 winner, 손실 0** — HOME short(+3.51R Timeout)·WLD long(+1.13R TrailSL)·BEAT long(+2.01R TrailSL)·VELVET long(+2.51R OPEN*). resolved 3건 **+6.66R(~+$766)**, OPEN포함 +9.17R. 스크립트 판정 *"F1 net NEGATIVE, reconsider"*. **★ 그러나 F1 변경 보류 — 4가지 이유**: ① n=4(확정 3, peeking·데이터마이닝 위험). ② **backtest n124와 정면충돌**(§8.9: 역추세 23건 net −$657·WR22% = 역사적으론 역추세 분명히 손해) → 라이브는 아직 "역추세 패자" 미출현 단계일 뿐. ③ **결정적: 막힌 4건 전부 극단막차**(sigret −25.6/21.7/19.3) = selection. 가뭄기 역추세 신호가 하필 다 강한 막차였고 극단막차는 잭팟 동반경향(ALLO +624 동형) → F1이 "역추세"를 막으려다 마침 "역추세+잭팟형 막차"만 집중차단 = backtest서 F1이 죽인 유일 잭팟(ALLO 역추세)의 알려진 비용이 라이브서 도드라진 구간. ④ track_f1 path 단일경로·entry≈signal_price 근사(방향성만), VELVET OPEN은 미실현 paper(peeking). **결론: 경고등 ON(무시 금지)이나 n=4로 F1 끄면 데이터마이닝.** 감시 핵심 = 역추세 신호 중 **실제 폭락 패자 출현 여부**(n 15~20+서도 net WIN 유지 시 F1 재고가 데이터기반 결정). 200건 게이트·peeking금지 유지, 무변경 |
| 2026-06-11 | **★ VELVET long TrailSL 잭팟 +$1,359**(거래소 실값, 봇 est +$1,385.67·arm A) 청산 — 진입 0.36469→best 0.91465(MFE **+150.8%**/MAE 0.47%, hold 5bars), 청산 ~0.864. **밤새 봇 가동 중 트레일링이 폭등 추격**(SL 로그: 00:00 BE발동 0.36→ 02:00 0.46→ 08:17 0.84→ 09:00 0.87), 08시경 급등을 SL이 따라올라 이익 잠금 = **"봇 켜둠"의 가치 실증**(꺼졌으면 SL 0.46 묶여 절반↓). BEAT·H에 이은 **3번째 잭팟, 또 arm A**(arm B 잭팟 여전 0). ESPORTS BE 본전 −$0.46 동반청산. ⚠️ VELVET pnl **ESTIMATED**(청산 직후 거래소 정산 전파지연, "Closed PnL NOT found 5 tries" → 봇이 SL가 0.8718로 추정 +1385.67, 거래소 실값 +1359.23, §8.7 동형) → **재가동 후 `rebuild_pnl.py`로 거래소 실값 정정 필요**. **★ PIPPIN(arm B) BE 첫 발동**: 변동성 큰 잔챙이라 0.75ATR 문턱(≈7.6%) 멀어 며칠 걸렸으나 best 0.01928 도달로 발동, SL=entry(0.02163) 본전잠금 — **arm B 빠른BE 첫 실증**(단 청산 전, n=1). 봇 reconcile 정상(VELVET 청산 3분 지연 자체해소, phantom 아님). **핸드오프(잠깐 재부팅)**: bar 486, **131 closed**, 포지션 3개 전부 short(PIPPIN arm B BE잠금 +$57 / SIREN arm A −$1 / POWER arm A −$5), state=거래소 일치, equity **$25,766**. 재가동: clock resync→cd vwap_trader→봇시작→State loaded 3 positions bar=486 확인. 무변경, 표본축적 지속(사용자 "표본수집 우선" 결정) |

---

## 11. 사전등록 가설 보드 (pre-registered 2026-06-01, 65 closed)

**목적**: OI 단일 가설 올인 방지. 같은 누적 데이터셋으로 다각도 가설을 **일괄** 검증 + 사후 cherry-pick·데이터마이닝 차단.

> 🆕 **v6 LIVE 검증 전환 (2026-06-07)**: H3/H9·H14(방향×regime) 계열은 더 이상 관측만이 아니라 **F1(역추세 진입 차단)으로 라이브 적용**됨 — 막힌 신호의 forward 성과는 **`track_f1.py`**가 R-배수로 집계(H13/H14 반사실 자동화). I3(BE 당김)은 **BE forward A/B**(arm A 1.5 / B 0.75)로 라이브 측정 중. 즉 H3/H14/I3은 "200건 일괄검정" 대신 **v6 라이브 A/B·점수판**으로 먼저 결판난다. 나머지 H1/H2/H4/H5/H7~H13은 여전히 관측·200건 일괄.

**규율 (pre-registration)**:
- 주지표 = **EV(평균 PnL/건) + 총 PnL.** WR은 보조 (잭팟 구조라 WR 오도). 방향 **단측 사전지정**, 사후 변경 금지(§10 이력에만 기록).
- 1차 검증 = **200 closed 일괄.** 중간 peeking으로 조기 중단/적용 금지.
- 다중비교: **Primary만 confirmatory** (α=0.05/6, Bonferroni). **Secondary는 탐색·가설생성 전용** — "유의"해도 확정 아님, 후속 사전등록으로 재검증해야 채택.
- ⚠️ 검정력: 200건(ctx ~150)에서 1분할(~75/75)은 견디나, 2분할(~37)·극단 부분집합·요일 셀은 부족 → Secondary 분류 근거.

### Primary — confirmatory (~200건 검정력 O)
| ID | 가설 (방향) | 검정 필드 | 현황 |
|----|------------|-----------|------|
| H1 | adverse selection 지속: loser 즉시역행률(MFE<0.5%) ≫ winner | MFE | **n93·6월(41) 모두 강력 확증: hold≤2 즉사=손실 전부. 6월 즉사 19건 −$1,040(EV−$55) vs ≥3 +$242** |
| H2 | 출구 비효율: winner가 peak MFE의 **median >30% 반납** (→ I1/I2 동기) | best_price·exit_price | BSB 79→50%·ALLO 18.5→0%·H 14.7→0%. 단 TrailSL PF830라 "비효율"이지 고장 아님 |
| H3 | regime 비대칭: side×regime EV 차 (예: UP_HIGH long > DOWN long) | regime·side | §7.2 등재 |
| H4 | 군집 노이즈: 동일봉 동시신호 수↑ → EV↓ | timestamp 군집크기 | 미탐색 |
| H5 | 배치내 순위: 동일봉 최강 signal_strength 진입 EV↑ | signal_strength | shadow와 직결 |
| **H14** | ★cap 방향 비대칭: 추세장(특히 DOWN_HIGH)서 `short_cap`(=3)이 올바른 방향(추세순행) 진입을 막아 long-against-trend 과진입 유발 → EV↓ | shadow cap-reason × side, side×btc방향 EV | **6월 신규발견: short 신호 47건 중 23%(11건)만 진입, 36건이 short_cap(30)/rank(6) 차단. long against-btc 11건 −$747 = 6월 손실 전부(long with-btc는 본전). ⚠️막힌 short forward 성과는 klines 소급 필요(H13 연계)** |
| **H15** | 연속성: `signal_consec=0`(직전 추세 없는 고립 단발 스파이크)=가짜 모멘텀, EV ≪ consec≥3 | signal_consec | **6월 강력: consec0 17건 −$766(EV−43, WR29%) vs consec3+ 4건 +$577. §8.5 consec 가설 Primary 승격** |
| **H0** | **(NULL·기각 목표)** 어떤 진입시점 변수도 EV를 노이즈 이상 분리 못 함 | 전 진입필드 | 단일필드 전패 → 현 baseline |

### Secondary — exploratory (검정력 부족, 가설생성 전용)
| ID | 가설 (방향) | 검정 필드 | 한계 |
|----|------------|-----------|------|
| H6 | ★OI interaction: 극단막차(abs ret24>50)서 OI+ EV > OI− | ret24×oi_chg | **헤드라인이나 최저 검정력**, ~20 극단 필요 → 200건엔 미완 |
| H7 | 막차 main effect: abs(ret24)↑ → 평균 EV↓·우측꼬리 비대 | ret24 | 기술적(잭팟 예외 ALLO) |
| H8 | BTC변동: btc_4h_atr↑ 진입 → 즉시역행률↑ | btc_4h_atr·MFE | |
| H9 | 추세정합: 신호↔BTC 1h 방향 일치 시 EV↑ | btc_1h_change·side | 반례 ALLO(역추세 잭팟) |
| H10 | 슬리피지: 진입 슬립↑ → EV↓ | slippage_momentum | |
| H11 | tier(사이즈): 저유동성 tier EV 차 | position_size_usd | 시총·상장일 필드 없음(프록시만) |
| H12 | 시간: 특정 요일/시간대 EV 약화 | day_of_week·hour_of_day | 셀당 표본 극소, 장기 |
| H13 | 반사실: shadow(거른 신호)가 entered만큼 벌면 선별 무가치 | shadow vs trades | shadow 누적 느림(7건), 장기 |

### v6 개입 후보 (관측데이터로 검정 불가 — backtest/live A-B 필요, 가설 아님)
- **I1** trail 거리(2ATR) 튜닝 · **I2** 부분익절(scale-out) · **I3** BE 트리거(1.5ATR) 타이밍 · **I4** BTC 1h 급변 시 신규진입 정지(chaos=관망) · **I5** regime 게이팅 진입.
- **I6** 극단 sigret 상한/축소 (H7 동기): `|signal_return_pct|`이 큰 트리거봉 진입을 제외 또는 사이징 축소. **관측(2026-06-04, 93 closed)**: 최근20건 즉사(hold≤2,손실) sigret 평균 **+17.4** vs 생존/이익 **−0.5**; 93건 구간별 EV `|sigret|<10 +$8.8(PF1.18) / 10–20 +$90(PF2.74) / ≥20 −$5(PF0.94)`. **중간(10–20)이 sweet spot, 극단(≥20)만 EV음수 — 비선형.** ⚠️ 단 `≥20` 구간 maxW **+$540**(잭팟 동반) → 단순 제외 시 잭팟 동반 사망 위험, 절대 단순컷 금지·backtest 필수. **역방향 진입은 별개 대규모 검증 사안**(중간강도 추종이 best라 전면 반전은 오답).
  - **6월 관측(2026-06-05, n41)**: 극단 `≥20` **6건 전멸 −$651(WR 0/6, EV−$108)**, `10–20` 7건 +$387(EV+$55), `<10` 28건 −$534. 6월엔 극단에 잭팟 미동반 → I6 정황 강화. 단 5월엔 극단에 잭팟 섞여(BSB+540) 단순컷 부결됐음 = 기간에 따라 극단 구간 성격이 달라짐 → 여전히 200건 일괄검정 필요.
  - **backtest 채점 (93건, 2026-06-04, 단순제거 시뮬)**: baseline 누적 +1900. 컷별 → `≥30 제외:+1990 / ≥25:+2334 / ≥20:+1951(EV~0) / ≥15:+648`. **컷 위치에 극도로 민감 = overfitting 경고.** `≥25`가 좋아보이는 건 BSB long(+540,sigret24.4)이 우연히 컷 아래로 생존한 덕; `≥20` 구간 10건 내부 = 잭팟 2건(BSB long+540, BSB short+261=+802) + 손실 8건(−853) = 합 −51(EV≈0, 거를 동기 약함). `≥15`로 내리면 15–20 황금구간(+1251) 침범해 반토막. 절반사이징은 효과 미미(+25). **결론: n93에선 채택 불가(부결), 200건 재검증.** 잭팟이 컷 경계에 산재 = 단순컷 신뢰불가 실증.
- 적용 조건: H2/H3/H7/H8 등이 신호를 준 **뒤** backtest 검증 통과 시에만. 단독 도입 금지.
