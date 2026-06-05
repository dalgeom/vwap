# Momentum Bot — 전략 계획서 (v5.1+)

> 최종 업데이트: 2026-06-05
> 이전 펀딩 역추세 봇 PLAN은 [PLAN_funding_legacy.md](PLAN_funding_legacy.md) 참조 (폐기됨)
>
> ⚠️ **PnL 기록 버그 3종(연쇄) — 전부 수정 완료.** 분석은 항상 거래소 closed-pnl 재구축 정본(`rebuild_pnl.py` → `data/trades_momentum_corrected.jsonl`) 사용. 원본 jsonl은 과거분 오염 잔존, unmatched는 §8.7 직접보정. ① (05-29) `_get_closed_pnl_price`가 race 시 직전거래 exit 오기록 → GRASS2 -$1,798=가짜(실 -$105), §8.2/§8.6 무효. ② (06-04) `place_order` 응답에 avgPrice 없어 entry가 신호가 fallback → `_fetch_actual_entry` 수정(§8.7). ③ **(06-05) closed-pnl 옛레코드 오매칭 — loose 1% 매칭+전파지연이 같은심볼 옛거래값 반환(STG +249→-72 오기록). freshness 게이트 수정(§8.8).** 실제 누적·통계 §5.4, 6월 분석 §5.5, 신호결론 §8.5+, 메모리 `project_pnl_recording_bug`.

---

## 1. 프로젝트 목표

Bybit USDT 무기한 선물 데모 계좌에서 **모멘텀 추종(Big Move Follow-Through)** 전략 자동 운영.
P99.5 percentile 이상 1h 봉 수익률 → 모멘텀 방향으로 진입 → BE+Trailing Stop 청산.

- **현재 단계**: v5.1+ 운영, 데이터 수집 중 (**106 trades / corrected 106 누적 +$1,389**, WR 36.8%, EV +$13.1/건, PF 1.23, 잭팟 의존 §5.4). 신호연구 병행 — 변별신호 로깅 + shadow log(~65줄).
- **검증 임계점**: 50건(첫 평가), **200건(Go/No-Go) — 현재 106**

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
| 2026-05-29 | **ALLO +44.47% (+$644) 최대 winner 실현** — ret_12=73·DOWN_HIGH 역추세, 모든 위험 플래그 red인데 대박. 전체 누적 +$388 전환 |
| 2026-05-29 | **interaction 가설**: 신호는 더해지지 않고 곱해짐. 막차+OI↑=폭발 / 막차+OI↓(ESPORTS)=붕괴. 단일 필드 필터 실패의 근본 원인 → 비선형 룰 필요 (§8.5) |
| 2026-05-29 | **PnL 기록 버그 발견** — `_get_closed_pnl_price`가 청산 직후 race 시 직전 무관 거래의 exit를 기록(side만으로 fallback). 47건 중 4건 exit 오염(GRASS 치명) |
| 2026-05-29 | **버그 수정**: closed-pnl 강한매칭(side+entry±1%+qty±1%)+retry 5×0.6s, 엉뚱레코드/ticker fallback 제거, 거래소 실 closedPnl 직접 기록(`pnl_source` 필드 추가). 봇 재가동 |
| 2026-05-29 | **거래소 재구축**(deterministic 1:1, 47건 전건 매칭, 2회 run 동일 해시): 기록 +$202 → 실제 **+$2,010**. **GRASS2 -$1,798=가짜(-$105)** → catastrophic slip/Tier Cap 동기 무효(§8.2/§8.6). v5.1기 +$97 breakeven, adverse selection 확인(loser MFE<0.5%=55%) (§8.5+). `trades_momentum_corrected.jsonl` 생성, 메모리 기록 |
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

---

## 11. 사전등록 가설 보드 (pre-registered 2026-06-01, 65 closed)

**목적**: OI 단일 가설 올인 방지. 같은 누적 데이터셋으로 다각도 가설을 **일괄** 검증 + 사후 cherry-pick·데이터마이닝 차단.

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
