# Momentum Bot — 전략 계획서 (v10)

> 최종 업데이트: **2026-06-29 (v10 대규모 업그레이드 — ★§5.10 단일참조/진단가이드 필독)**
>
> 🆕 **v10 (2026-06-29)**: 196건 종합감사로 거래로직 4개 동시변경(v7.1 사이즈cap·v8 변동성게이트·v9 잭팟사이징·v10 유니버스확대) + 3기각(F1완화·부분익절·신호임계). 백테스트 +3020→+8777(2.9배). **상세·효과·부작용·최악진단·데이터계획 = §5.10. 봇 나빠지면 §5.10 D/E.** 버전이력 §3, 시계열 §10.
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

### 1.1 방법론 철학 (★ 프로젝트의 사고방식 — 모든 세션 필독, 2026-06-17 사용자와 합의)

> 새 세션은 이 절을 읽으면 "왜 이렇게 천천히, 변경 없이 표본만 모으는가"를 이해할 수 있다. 이게 이 프로젝트의 goal이자 일하는 방식이다.

- **Goal**: 트레이딩에 신이 아닌 이상 정답지(100% 승률)는 없다. 목표는 **수많은 factor와 그 조합 속에서 "이 봇만의 꾸준히 우상향하는 edge/패턴"을 찾아내, 봇을 v1→v7→…로 끊임없이 진화시키는 것**(메모리 [[project_core_philosophy]]: "끊임없이 공부·분석·성장·승률 높이기"). 척도는 **"손절 건수↓"가 아니라 "건당 기대값(EV)↑"** — 손절은 손실을 작게 끊는 정상 비용이지 적이 아니다(승률 34%·잦은 손절 = 모멘텀 추종의 정상 구조).
- **핵심 함정 — 과최적화/데이터마이닝**: factor 조합을 많이 돌릴수록, 순전히 우연으로 과거에 딱 맞는 "가짜 정답"이 **반드시** 나온다(동전 1000명이 던지면 10연속 앞면 나오는 사람이 생기듯, 그는 예언자가 아니다). 백테스트는 환상적인데 실전 넣으면 무너지는 전략 대부분이 이것. 단일·단순 조합 필터가 전부 실패한 것(§8.5: 잭팟이 "나쁜 신호 칸"에 숨음)도 같은 뿌리.
- **∴ 진짜 제약 = factor 부족이 아니라 "표본 부족"**: factor 1개 늘릴 때마다 검증에 필요한 표본은 기하급수로 증가(차원의 저주). 163건에 수십 factor 조합 = 가짜 패턴 양산 보장. **factor 수와 표본 수의 균형이 맞아야 한다 → 지금은 factor를 늘릴 때가 아니라 표본을 채울 때.**
- **정공법 (이 봇이 이미 갖춘 규율)**: ① 가설 먼저(왜 edge일지 경제적·구조적 근거 — 무근거 factor 난사 금지) ② **사전등록**(§11 가설보드 — 사후 cherry-pick 차단) ③ 충분한 표본에서 **일괄 검정**(200건 Go/No-Go, 중간 peeking 금지) ④ 우연 보정(Bonferroni) 후 **살아남은 것만 채택** → 그 위에 다음 factor를 신중히 얹는다. v6(F1·BE A/B)·v7(정원·거래량)도 이 사이클의 한 바퀴.
- **현 단계의 미덕 = "참기"**: 조급하게 factor·로직을 늘리는 게 아니라, 표본이 200건+ 찰 때까지 **무변경으로 모으는 것.** 그게 가짜 정답을 진짜로 착각해 실전에서 무너지는 걸 막는 유일한 길이다. (이번 163건 점검의 구체 근거는 §5.7.)

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
| **v7** | **2026-06-15** | **둘째 거래로직 변경**: 방향별 조건부 정원확장(`max_short 3→5`/`max_long 3→4`, 확장자리만 연속성조건; `cap_consec_priority`) + 거래량 로깅(`signal_vol_ratio`, 기록전용) | **2026-06-15 재시작 발효(bar586). 라이브 청산 5건 net −$144·정원확장 0발동(가뭄)=사실상 미검증. bot_version=v7. 상세 §5.7·§10·§11 H14** |
| **v7.1** | **2026-06-29** | **셋째 거래로직 변경(사이즈)**: tier1/tier2/hard_cap `10000·5000→4000` 하향(대형코인 베팅 축소, tier3/4 유지). 196건감사 H11(대형>5k EV−$42·WR18%) 근거 | **config만 변경, bot_version=v7.1. 백테스트(clip 결정론) +3020→+3653(+$633). 재가동 대기. §5.10·§11 H11** |
| **v8** | **2026-06-29** | **넷째 거래로직 변경(변동성게이트)**: 저변동코인(`min_atr_pct` 1.0 미만=가짜모멘텀)·BTC초고변동(`max_btc_4h_atr` 1600 초과=동조휩쏘) 진입차단(`vol_gate_enabled`, shadow `low_vol_coin`/`btc_chaos`). 196건 레짐분석(저변동=잭팟없는칸) 근거 | **config+코드(_scan_universe 게이트). bot_version=v8. 백테스트(보수) +3020→+4887(+$1,867), 잭팟 STG1건만 희생·39건 차단. 게이트로직 백테스트 재현검증 OK. 재가동 대기. §7.5·§10** |
| **v9** | **2026-06-29** | **다섯째 거래로직 변경(잭팟사이징)**: `sizing_mode: fixed`·`fixed_notional_usd: 2000` — ATR리스크균등을 고정금액 균등으로. 196건감사: 현 ATR사이징이 **잭팟(고변동코인)에 거꾸로 작게 베팅**(VELVET+1386에 $997 / HYPE+373에 $7693, 잭팟16/21이 고변동인데 평균$1273) | **position_sizer fixed옵션+호출부 분기. bot_version=v9. 백테스트 고정+게이트(D안) +3020→+8777·maxDD−1964→−2125·수익위험비1.54→4.13(레버업아닌 배분효율). tier_cap·lot floor 통과(저유동tier4 1000 binding, fixed2000<cap4000이라 v7.1 tier1/2 cap은 fixed모드선 비활성). ⚠️in-sample·실거래 소형알트 슬리피지 미검증(데모맹점). 롤백 sizing_mode:atr. §7.5·§10** |
| **v10** | **2026-06-29** | **여섯째 거래로직 변경(유니버스확대)**: `min_volume_usdt 20M→10M`(+22개 소형코인). 196건: 소형(고변동)=잭팟밀도 18% vs 대형 5%·EV+48 vs −28 | **config 한줄. bot_version=v10. ⚠️과거 미스캔=백테스트 불가=forward만 검증. 슬리피지는 tier4 cap$1000+slippage_cooldown 방어(5M이하 제외). 롤백 20_000_000. §7.5②·§10** |

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

## 5. 운영 현황 스냅샷 (§5.0~5.3은 2026-06-05/106 trades 시점, **최신 누적은 §5.8 — 180건**)

> 실시간 데이터는 [data/trades_momentum.jsonl](data/trades_momentum.jsonl), [data/state_momentum.json](data/state_momentum.json) 직접 참조. **분석은 항상 corrected**([data/trades_momentum_corrected.jsonl](data/trades_momentum_corrected.jsonl), `rebuild_pnl.py`로 재생성). 원본 jsonl은 v5.1+ 신규분만 정확(`pnl_source:exchange`), 과거분·일부 신규분(§8.8 STG 등)은 버그 오염 잔존.

### 5.0 계좌 레벨 (2026-06-01 감사 — 1회성, 압축)
- 데모 초기 지급 **$40,000 확정**(cumRealised 항등식). 평생 실현 ≈ −$16k(−40%)는 **거의 전부 5분봉 v1~v4 시대 손실**(≈−$17.7k 역산) — 1h봉 v5+ 시대(106건 corrected +$1,389)는 우상향이라 **봇 평가는 v5 시대만 유효**, 과거 era 무관. 데모 API 단기보관(closed_pnl 40건·~7일)이라 과거 날짜조회 불가, v5 완전본은 로컬 corrected jsonl이 유일.

### 5.1 누적 추이 (역사 압축)
- 데이터셋 성장: 64건(06-01, +$2,025) → 93건(06-04, +$1,900) → **106건(06-05, +$1,389)**. 누적 감소는 6월 적자(§5.3) 반영. 모든 시점 `rebuild_pnl.py` deterministic 1:1 재구축.
- ★ **냉철히**: 누적 흑자는 **잭팟 소수건에 전적 의존.** fat-tail winner 전부 TrailSL(BEAT+895·NEAR+719·PORTAL+649·ALLO+624·BSB+541·HYPE+373·STG+250). catastrophic 손실은 부재(최대 −$148대). **edge는 잭팟 빈도/크기 의존 — 안정성 단정 불가, 표본 계속 축적.** ⚠️ 데모 closedPnl=시뮬레이션값(실거래 슬리피지 별개).

### 5.2 106건 통계 분해 (2026-06-05 corrected) — 3대 결론 (이후 155·163·180건서 전부 재확인)

> n106, WR 36.8%, +$1,389.11, EV +$13.1, PF 1.23. (절대수치는 06-04 n93이 최정밀, §10.)

**① 즉사(hold≤2)=손실 전부** (H1 adverse selection: n93 ≤2 EV−$77 vs ≥3 +$104) **② TrailSL/Timeout=흑자 전부** (잭팟, WR~95%) / SL=손실 전부(WR0%) / BE~0 **③ |sigret| 비선형** (<10 약손실, 10–20 sweet spot, ≥20 극단 손해편향 — I6 동기·단순컷 부결 §11).

### 5.3 6월 거래 분석 (2026-06-05 corrected 41건)

> **6월 실현 −$798, WR 34.1%, PF 0.64 = 적자**(5월 잭팟 까먹는 중, 단 건당 −$100~130 통제). SL 24건 −$2,179(WR0/24)·즉사 19건 −$1,040 = **H1 재확증**. 극단 sigret≥20 6건 **WR0/6 전멸**(−$651). **★ 방향·regime은 5월과 뒤집힘**(6월 long·FLAT_HIGH 최악 — 시장 하락/횡보로 long 막차 터짐) → 표본 노이즈, 200건 전 게이팅 금지 재확인.

### 5.6 중간점검 누적 (155→180건, 2026-06-15~22, 압축)

> 정본기반 누적: 155건 +$3,113(EV+20·PF1.36) → 163건 +$3,417 → 180건 ≈+$3,4xx. ⚠️ raw jsonl 합은 과거버그 오염(쓰지말것), 신규 다수 estimated(§8.7). (상세 시계열은 §10.)

- **★ 잭팟 의존 정량**(155건): top5 winner +$4,333=누적 **139%**, 빼면 150건 −$1,220 적자. 흑자=fat-tail 소수 전적의존(설계특성, 평가핵심=잭팟 빈도).
- **exit 분해**: TrailSL/Timeout=흑자 전부(WR93~100%) / SL=손실 전부(WR0%) / BE≈0.
- **★ 손절 89건 분해**(163건): **즉시역행(MFE<0.5%) 52건 −$7,033=손절손실 67%=입구 변별불가**(출구 구제불가, 떴다꺾임 37건만 BE구제). → 목표="손절 건수↓" 아닌 **"건당 EV↑"**.
- **방향**: short EV+$28 > long EV+$16(단 잭팟 top5 전부 long). v7 정원확장 동기.
- **arm A/B 판정불가**: 잭팟 우연몰림 지배. ★180건서 **arm B(빠른BE) 첫 잭팟 ESPORTS short +$283**("빠른BE가 잭팟 자름" 우려 첫 반례, n=1).
- **★ H14 소급→v7 도출**: short_cap 41건 +97R(꾸준 consec≥1)·long 22건 +23R(단발 consec0)=방향 정반대. 단발 short 잭팟 forward 반례 누적(OPG/ZKC/BEAT, H14).
- **데이터손실사고(06-19)**: 봇 켠 채 IDE에서 trades 삭제·저장→6건 복구(.bak_20260619). **봇 가동중 파일편집 금지**(prom §9).

### 5.9 196건 인계 점검 (2026-06-29, PC 이전) — 거래량 폭발 ≠ 신호 확정 + 무결성 사고 재발

> 180→196건(+16). 정본기반 누적 ≈ +$3,xxx. 인계 시점 **무포지션·equity ~$25,133·봇 graceful 종료**. 이번 세션(06-22~29) 약 **−$584**(손절 다발이 BTC 잭팟 +$198 압도 = 잭팟 가뭄). 06-22~23 극심한 가뭄(매시간 scan 0 candidates·shadow 0) → 06-25 14시 변동성 폭발(rank_cutoff 다발=신호 동시다발) → 이후 산발.

- **★ 거래량(`signal_vol_ratio`) 폭발 = 좋은 신호 아님 확정**: BTC short **17.5배** 폭발→즉시역행 −$114 / SLX long 8.8배→한때 +8.3% 떴다 본전(−$19) / (§5.8 BEAT 7.5배 즉사·ESPORTS 4.87배 잭팟). 큰 거래량=큰 파도라 **양방향 다 가능, 단독 변별력 없음** = §8.5 "interaction은 코너에서만, 단일필터 실패" 재확인. 거래량은 진입팩터 후보지만 단독 아닌 조합으로만.
- **★ BTC 같은 코인·같은 방향(short) 이틀 차 +$198(06-24)/−$114(06-25) 정반대** = 모멘텀 추종 본질 실증(방향 적중=잭팟, 빗나감=손절, 손절은 작게 끊는 비용 §1.1). 06-24 BTC는 **단발(consec0) short** 만기형 잭팟 = H14 forward 반례 4건째(OPG/ZKC/BEAT/BTC).
- **★ slippage cooldown 첫 실발동: AGLDUSDT**(06-27 long SL −$113, 슬립 1%p 초과→48h 진입금지, state에 06-29 03:06Z까지 잔존). 이전 세션 내내 cooldown 0이었음 = **§6 안전장치 실작동 첫 사례**(저유동성 미끄러짐 실재, §8.2 데모 슬리피지 관측 표본).
- **★ arm B(빠른 본전잠금)가 큰 이익 못 지킨 사례**: SLX long arm B 한때 +8.3%(MFE 8.28)→본전선 끌려와 BE −$18.79. "빠른BE가 잭팟 일찍 자름" 우려 정황(§5.8 ESPORTS arm B 잭팟 반례와 **양립** — arm별 BE 효과 양방향 표본 누적 중, 200건서 일괄검정).
- **★★ 데이터 무결성 사고 재발(2회째)**: 06-22 세션서 정정한 ESPORTS/MET pnl(estimated→exchange)이 **06-29에 estimated로 롤백**된 것 발견 → 재정정. 원인=06-19과 동일(**봇 켠 채 IDE에서 `trades_momentum.jsonl` 저장** → 옛 버퍼가 그 사이 정정·append를 덮어씀). 06-25 정정(SOLAYER/BTC)·06-28(PUMPFUN)은 무사. **교훈 강화: 봇 가동 중 그 파일 IDE 저장 절대 금지, 정정 전 `.bak` 백업 필수**(prom §9, 백업 `.bak_20260629`).
- **estimated 정정 루틴 확립**: 이번 세션 신규 청산분 5건(ESPORTS/MET/SOLAYER/BTC/PUMPFUN) 거래소 `get_closed_pnl` 풀정밀도(`closedPnl`·`avgExitPrice`)로 직접패치(`pnl_pct`=가격변화율 재계산, `pnl_source→exchange`). raw 잔존 estimated **27건은 전부 06-20 이전** = 데모 API 7일 보관 초과로 재조회 불가(§8.7 한계, 분석은 corrected 정본).
- **★ 196건 = 사실상 게이트 도달.** 2026-06-29 "더 기다림 없이 지금 데이터로 업그레이드"(사용자 [[feedback_no_more_sample_gating]]) → **대규모 변경 §5.10 참조.**

### 5.10 ★★★ 2026-06-29 대규모 업그레이드 (v7.1~v10) — 단일 참조 + 진단가이드

> 196건 종합감사 후 **거래로직 4개 동시 변경**(프로젝트 첫 다중변경). **봇 성과가 나빠지면(승률↓·우하향·연속손실) 이 절 D/E를 먼저 읽고 원인추적·롤백.** 시계열은 §10, 가설보드는 §11.

**A. 적용 4개**

| ver | 변경 | 왜(196건 근거) | 위치 | 백테스트 | 롤백 |
|-----|------|----------------|------|----------|------|
| v7.1 | 대형 사이즈 cap 10k/5k→**4k** | 대형>5k EV−$42·WR18%(H11) | config tier_caps tier1/2/hard | +$633(clip 결정론) | 값 복원 |
| v8 | **변동성게이트**: 저변동코인(atr%<1.0)·BTC초고변동(btc_4h_atr>1600) 진입차단 | 잭팟없는칸(저변동 EV−34·WR22% / BTC Q4 EV−38) | config vol_gate_enabled + momentum_bot `_scan_universe` | +$1,867(잭팟 STG1만 희생) | vol_gate_enabled:false |
| v9 | **잭팟사이징**: ATR리스크균등→고정 **$2000** | ATR이 잭팟(고변동)에 거꾸로 작게베팅(VELVET+1386에 $997 / HYPE+373에 $7693) | config sizing_mode:fixed + position_sizer | 고정+게이트 +$8,777·수익위험비4.13 | sizing_mode:atr |
| v10 | 유니버스 20M→**10M** | 소형=잭팟밀도18%(대형5%)·EV+48 | config universe.min_volume | ⚠️과거 미스캔=백테스트 불가, forward만 | 20_000_000 |

**종합 백테스트**: +$3,020 → **+$8,777 (2.9배)**, maxDD −1,964→−2,125, 수익/위험비 **1.54→4.13**(레버업 아닌 배분효율).

**B. 기각 3개 (★재시도 금지 — 데이터가 손해/무효라고 증명)**
- **F1 완화**: F1이 막은 역추세 큰막차 실현 **0승4패 −$373**(shadow +21R·track_f1 +79R은 단일경로 신기루). 역추세 차단 유지.
- **부분익절**: 잭팟8건(+$4,602) 절반절단이 떴다꺾임구제(+$1,790) 압도. **H2 43%반납=비효율 아닌 잭팟 살리는 필요비용.**
- **신호임계**: 99.0 낮추면 약신호 손실만↑·잭팟 안늘어남(강신호에만). 99.5 최적.

**C. 예상 효과 (가설)**
- v8이 가뭄 잔손실↓(가짜모멘텀·BTC동조휩쏘 차단) + v9가 잭팟크기↑(고변동에 제대로 베팅) + v10이 잭팟빈도↑(소형풀 32→54개). → **계단식 우상향**(내림폭↓·오름폭↑) 기대. ⚠️전부 in-sample/백테스트, forward 미검증.

**D. ★ 예상 부작용·위험**
1. **★v9 실거래 슬리피지(최대 구멍)**: 잭팟=소형알트인데 고정$2000(tier4는 $1000)도 얇은 호가 잠식 가능 → 데모 +8777이 실거래선 줄어듦. **데모의 최대 맹점.**
2. **v9 maxDD↑**(−1964→−2125): 한방 손실 커짐(v8 게이트가 일부 완화).
3. **v10 forward only**: 과거 데이터 0이라 검증 불가. 소형코인 슬리피지·scan부하(+22코인).
4. **4개 동시변경**: forward서 무엇이 효과/노이즈인지 **분리 난해**(교란).
5. **in-sample 과최적화**: 임계(atr%1.0·btc1600)·고정($2000) 전부 과거 최적값. 미래 안 맞을 수.

**E. ★★ 최악 시나리오 진단 가이드 (증상 → 의심 → 대책)**

| 증상 | 1순위 의심 | 메커니즘 | 진단법 | 대책 |
|------|-----------|----------|--------|------|
| 한방 큰손실 빈발·maxDD 폭증 | **v9** | 고정$2000이 고변동코인에 과대 | trades pnl 분포·maxDD 추적 | sizing_mode:atr 롤백 또는 fixed_notional↓($1500) |
| 특정 소형코인 큰 슬립 손실 | **v9+v10** | 얇은호가 잠식 | slippage_momentum >1%p 급증 | min_volume 20M 복원 + sizing atr |
| 잭팟이 실종(큰 winner 안나옴) | **v8 과차단** | 변동성칸이 잭팟도 막음 | shadow `low_vol_coin`/`btc_chaos`가 would-be winner였는지(track) | min_atr_pct↓·max_btc_4h_atr↑ 또는 vol_gate off |
| 진입 급감(가뭄 아닌데) | **v8** | 게이트 과하게 거름 | shadow reason 분포 | 게이트 임계 완화 |
| 승률↓·EV↓ 전반 | 복합/시장 | 4개동시라 분리난해 | **bot_version=v10 구간만** 떼서 §5.2식 차원분해 | 의심순 1개씩 롤백(A/B) |
| 전반 우하향 지속 | 시장(잭팟가뭄) vs 변경 | 모멘텀 본질 or in-sample 붕괴 | v10구간 잭팟빈도 vs 과거 비교 | **잭팟 정상인데 우하향=변경문제(롤백) / 잭팟가뭄=시장(§7.4 사망판정)** |

**F. v10 수집 데이터·모니터링 (다음 세션 검증 체크리스트)**
- **태깅**: trades `bot_version=v10`. shadow 새 reason `low_vol_coin`·`btc_chaos`(게이트 차단 기록).
- **★검증 질문 4개**: ①v9 실슬리피지가 백테스트 이득을 잠식하나(slippage_momentum 모니터) ②v8 게이트가 막은 신호가 실제로 나빴나(would-be 추적) ③v10 소형코인(10-20M)이 진짜 잭팟 내나(신규 잭팟의 코인 24h volume 확인) ④arm A/B 실현PnL(§5.6 판정유보 지속).
- **판정 시점**: v10 구간 **30~50건** 쌓이면 차원분해 재실행 → 잭팟빈도·maxDD·슬리피지·게이트차단율 점검.
- **확장 후보(검증 후에만)**: v9 변동성비례(+13473, DD↑) / v10 5M확대(+57코인) / ④새신호(timeframe·복합신호, §1.1 가설먼저).

### 5.11 A-2/3/4 데이터안전 인프라 + v10 순항 (2026-07-03~06, PC 인계)

> 거래로직 무변경 세션. 로드맵(`PROJECT_ANALYSIS_ROADMAP.md` §6-A) 인프라 3개 완성 + v10 forward 순항. 인계 시점 equity ~$29,276·bar 1053·2포지션(VANRY long·EPIC short).

**A. 데이터안전 인프라 (거래로직 무관, v10 검증과 병행)** — brainstorm→spec→plan→subagent 구현, `docs/superpowers/{specs,plans}/2026-07-0*`.
- **A-2 estimated 자동정정** `fix_estimated.py`: estimated→거래소 실값을 별도 `pnl_corrections.jsonl`에 append(원본 trades **append-only 신성화 — 외부수정 금지**, 멱등, 7일 시한). 분석은 `corrections.apply_corrections(trades)` 오버레이.
- **A-3 무결성 가드** `integrity.py`(순수함수)+봇 `run()` 훅: 시작 자동백업(`.bak_*`, keep10)+종료 라인수 비교. IDE저장 사고 감지·복구.
- **★ freshness 버그 수정(PnL버그 계보 4번째)**: 거래소 `createdTime`이 청산시각 아닌 **진입시각**이라, 봇/스크립트가 자기 레코드를 0.4초 차로 배제→estimated 양산하던 버그 → **60초 tolerance**(봇 `_get_closed_pnl_record`+fix_estimated 둘 다). 실증 RAVE/UNI/**TLM**(봇추정 −$1.1 ↔ 거래소 실값 **+$11.04** 부호반대). §8.7/§8.8 계보, estimated 발생 원인 제거.
- **A-4 일일 리포트** `daily_report.py`: 하나의 배치(정정→corrections→`reports/YYYY-MM-DD.md`). 순수함수 4개+테스트 29 passed. **원칙: equity(거래소)=진짜 누적 / trades⊕corrections=통계**(과거 PnL버그 오염은 각주). 메인 PC 매일 12:30 스케줄러 등록.
- 권한 `bypassPermissions`(이 프로젝트 확인 프롬프트 생략). 남은 인프라: A-1(apply_corrections로 핵심 대체)·A-5(watchdog). 측정도구 **B-1**(차단신호 소급채점=정원 rank_cutoff 81%에 잭팟 숨었나)·**B-2**(지연진입 백테스트=즉시역행 50건 정면공략, 목적3)가 유력 후보.

**B. v10 forward 순항 (6/29~7/6)**
- equity $25,133 → **$29,276 (+$4,143, +16%)**. ★★ **TAIKO·LAB 잭팟 견인**: TAIKO 매수 +$1,186·+$469·매도 +$1,032(한 코인 **+$2,687**), LAB 매수 +$2,078(+115%). v10 25건 WR52%·EV+$164·PF4.75(잭팟 덕, 표본 소, 단정 금지).
- ★ **냉정**: 여전 소수 잭팟 집중 의존(둘 빼면 잔손실 = 모멘텀 설계특성 불변). ★ **v10 공로 의심 지속**: TAIKO 24h거래대금 21.1M=옛 20M 경계선(옛 기준으로도 잡힘)·v10 전용 신규코인 5건 −$116 → **유니버스확대가 잭팟 원인이란 증거 약함**. v9 사이즈 역설(잭팟=소형 tier cap $1000 / 손실=중형 $2000)·출렁임상한 부재(고변동 매도 되밀림 위험)는 §5.10 C-1/C-2 후보 그대로.

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
| **A-3 무결성 가드** (07-06) | integrity.py + run() 훅 | 시작 trades 자동백업(keep10) + 종료 라인수 비교(IDE저장 사고 감지·복구) |
| **A-2 corrections** (07-06) | fix_estimated.py → pnl_corrections.jsonl | estimated→거래소 실값을 별도파일 정정(원본 append-only 보존) |

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

### 7.5 미래 개선 방향 — v8 후보 (2026-06-29 신설, "더하기식" 전환)

> ★ **배경**: 196건 감사로 **"빼기식 개선"(기존 거래를 거르거나/줄이거나/일찍 자르기 = F1·필터·부분익절)은 전부 잭팟을 죽여 손해**라는 게 확정됐다(§10 06-29). 잭팟의존 봇은 잭팟 스치는 변경에 구조적 취약. → 개선은 **"더하기식"(잭팟 빈도↑·크기↑·새 alpha)** 방향으로 전환. v1~v7은 대부분 빼기식(버그수정·리스크관리)이었음. "우상향"=매끄러운 곡선이 아니라 **가뭄을 작게 버티고 잭팟으로 점프하는 계단식**(내림폭↓·오름폭↑이 목표).

| # | 방향 | 핵심 | 데이터 근거 | 검증법 | 잭팟영향 |
|---|------|------|-------------|--------|----------|
| **①** | ~~레짐 적응~~ → **v8로 적용완료** | **변동성 게이트**(저변동코인 atr%<1.0 / BTC초고변동 btc_4h_atr>1600 차단). ★성과흐름(연속손절·drawdown) 적응은 무효 확인, **변동성** 적응만 유효 | 196건 레짐분석: BTC Q4초고변동 EV−38·잭팟2 / atr% Q1저변동코인 EV−34·WR22%·잭팟2 = 둘다 잭팟없는칸. 백테스트 보수조합 +1867(잭팟 STG1만) | **v8 적용**(§3·§10). forward로 임계 적정성·공격조정 관찰 | 🟢 잭팟 거의무손상(STG1) |
| **②** | ~~유니버스 확대~~ → **v10 적용(10M)** | min_volume 20M→10M(+22개). 향후 5M(+57개)도 검토(단 초소형 슬리피지) | 소형 잭팟밀도18%(대형5%)·EV+48. 풀 32→54개 | **v10 적용**. 과거데이터0=forward만 검증 | 🟢 잭팟빈도↑ |
| **③** | ~~잭팟 사이징~~ → **v9로 적용완료** | **고정금액 균등**(ATR사이징이 잭팟=고변동에 거꾸로 작게베팅하는걸 교정). 진입시점 잭팟식별은 불완전(평균상 잭팟=고변동·OI유입·큰막차이나 ZEC반례)이라 "식별후 차등" 아닌 "변동성 역상관 제거"로 접근 | 잭팟16/21=고변동인데 평균베팅$1273(저변동$3883). 백테스트 D안 +8777·수익위험비4.13 | **v9 적용**(§3·§10). ⚠️실거래 슬리피지 미검증→forward 확인후 변동성비례 확대 | 🟢 잭팟크기↑ |
| **④** | **새 진입 alpha** (일부탐색) | ★신호임계(percentile) 튜닝 **기각**(99.0낮추면 약신호손실↑·잭팟안늘어남, 현 99.5최적). 미탐색=다른 timeframe(4h/15m)·패턴(거래량돌파·OI급증)·복합신호 | 진짜 진화 | 임계는 재시뮬완료(기각). 신규신호는 klines 재시뮬 or forward | 🟢 새 수익원 |
| 보조 | 트레일링 거리(I1)·봇 운영안정(잭팟 포착률) | 잭팟 더 살리기 | VELVET 밤샘 +150% 추격 | I1은 출구라 1m재현 한계→forward A/B | 🟢 |

**금지/주의**: 빼기식(진입필터·출구조기화) 재시도 금지(닫힘). 더하기식도 §1.1 과최적화 경계(무근거 factor 난사 금지, 가설→사전등록→검정). ②④는 새 코드라 신중.

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

### 8.9+ ★★★ 되감기 백테스트 4종 강등 — 참고용만 (2026-07-08 확정)

- **동기**: B-1(`track_shadow.py`)·B-2(`backtest_delayed_entry.py`) 개발 중 **기준선 재현검증**으로 결정적 확인. B-2 기준선(즉시진입) 재현율 **5~9%**(되감기 +404 vs 실제 +4,517).
- **원인 2개**: ① `fetch_1m` **창 버그** — 48h 창에서 Bybit가 `end` 근처 최근 1000봉만 반환, 페이지네이션이 못 넘어가 **진입 +7~31시간 뒤 구간**을 되감음(진입시점 누락). *B-2에서만 페이지창 1000봉 바운드로 수정, track_* 3종은 미수정.* ② **1분봉 되감기가 봇의 1시간봉 추적익절을 재현 못함** — 1분 잔파동에 추적손절선 조기이탈로 잭팟을 구조적으로 뭉갬(LAB 실+2078→되감기+189, TAIKO 실+1186→+1, H 실+648→−1). 창을 실제 청산시각까지 좁혀도 9% = **방식 자체 한계**(§8.9 I3 재현실패·§10 부분익절 재현실패와 동일 뿌리).
- **★ 일반화**: `track_f1`·`track_cap`·`track_shadow`·`backtest_be` **4종 전부 동일 single-path 1m replay**. 잭팟 지배 손익을 재현 불가하고, 차단신호(track_shadow)는 실제값이 없어 **재현검증조차 불가**.
- **★ 강등 결정**: 이 4종의 출력은 **참고용(가설 생성)만**. **절대값·잭팟 관련 손익 판단 금지.** 과거 이 도구에 기댄 결론은 재검토 대상 — B-1 `short_cap` 결론(무효, `data/shadow_scores.INVALID.txt`), B-2 지연진입 숫자(무효), v7.1 사이즈 "backtest clip +$633"(신뢰도 하향), track_f1 F1 점수판(이미 §10 2026-06-29서 실현 교차검증이 신기루로 판정).
- **★ 방향 전환**(전문가 자문 2026-07-08, §10 참조): 진입 선별=막다른 길(추세추종 구조상). 지렛대=**출구·사이징·처리량(잭팟 추첨 횟수)**. 측정은 백테스트가 아니라 **봇 내 실시간 페어드 반사실 계측**(되감기 편향 0)+**forward 무작위 A/B**. 손익 엔진 분리(손실=빈번·통계가능 / 잭팟=희소·계기판만). **목표 재정의: 승률 → EV×거래빈도×생존.**

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
| 2026-06-15 | **★ v7 전환 (사용자 지시, 두 번째 거래로직 변경)** — `short_cap`/`long_cap` 소급검증(중복제거): **short 41건 +97R(꾸준 consec≥1이 +92R·단발은 본전) / long 22건 +23R(단발 consec0이 +22R·꾸준은 본전)** = 방향별 "좋은신호" **정반대**. → **방향별 조건부 정원확장**: `max_short 3→5`·`max_long 3→4`, 기본 3자리 무조건 + 확장자리만 연속성조건(short확장=꾸준 consec≥1 / long확장=단발 consec0). 순수함수 `cap_admits`+`_quick_consec`, config 토글 `cap_consec_priority`(=false 또는 max 3/3으로 즉시 롤백). **+ 거래량 로깅** `signal_vol_ratio`(신호봉/직전20봉평균, 캐시튜플 volume 복원, **기록전용·거래 무영향**). bot_version=v7. forward추적 `track_cap.py`. 검증: pytest 5(순수함수)·import·config·round-trip 통과. ⚠️ in-sample 소급근거(**forward 0**)·동시손실위험(최악24h −$2,183, 단발제외로 완화)·long표본 6/16건 → 200건 일괄검정 전 **잠정**, peeking 금지. 거래량은 결론 없음(이제 기록 개시) |
| 2026-06-17 | **★ 타 PC 재가동·v7 첫 라이브 + 163건 중간점검**: git pull→재시작(bar586)으로 v7 발효. **손절 89건 분해: 즉시역행(MFE<0.5%) 52건 −$7,033 = 손절손실의 67% = 입구 변별 불가, 떴다꺾인 37건만 출구로 구제 가능**(§5.7) → 목표는 "손절 건수↓"가 아니라 "EV↑". **정본누적 +$3,417**(raw jsonl $1,352는 과거버그 오염, 쓰지 말 것). **v7 라이브 5건 net −$144·정원확장 0발동(가뭄)=미검증**. OPG/ZKC 단발(consec0) short 만기 잭팟(+$409/+$81, v6 진입)=H14 short 처방 forward 반례 2건. **방법론 재정립(사용자)**: factor 조합으로 우상향 edge 탐색이 목표이나 진짜 제약=표본 부족(과최적화 함정), 163건에 factor 남발 금지 → §11 사전등록·200건 게이트가 정공법. 무변경, 표본 축적 지속 |
| 2026-06-22 | **PC 인계(180건, 무포지션, 봇 일시중단)**: ★ **arm B(빠른BE) 첫 잭팟 ESPORTS short +$283**(거래량 4.87배·−73%)→§5.6 "arm B 잭팟0 판정불가" 깨짐(§5.8). 거래량 양면(BEAT 7.5배 즉사 / ESPORTS 4.87배 잭팟)=단독신호 아님. 단발 short 잭팟 3건째(OPG/ZKC/BEAT)=H14 forward 반례. **06-19 데이터손실 사고**(사용자 IDE 삭제)→거래소+대화+로그로 6건 복구(백업 .bak_20260619). v7 정원확장 여전 0발동=핵심기능 미검증. PLAN §1.1 방법론 철학 신설·§5.2/5.3 옛표 축약. Bash/PowerShell 권한 자동허용 설정. equity ~$25,686. 무변경·표본축적 지속(180/200) |
| 2026-06-26~29 | **PC 인계(196건, 무포지션, graceful 종료)**: ★**거래량 폭발=좋은신호 아님 확정**(BTC short 17.5배→즉시역행 −$114 / SLX long 8.8배→본전 −$19). ★**BTC 같은코인 short 이틀차 +$198(06-24 단발)/−$114(06-25)**=모멘텀 본질·H14 반례 4건째. ★**slippage cooldown 첫 실발동**(AGLD 06-27 long, 슬립1%p초과→48h금지, §6 실작동). ★arm B가 큰이익 못지킴(SLX +8.3%→BE −$19, §5.8 ESPORTS 반례와 양립). ★★**무결성 사고 재발**: 06-22 정정(ESPORTS/MET)이 06-29 estimated 롤백 발견→재정정(봇 켠 채 IDE 저장 원인, 06-19 동형). estimated 정정 5건·raw 27건은 7일보관초과(§8.7). 이번 세션 −$584(잭팟 가뭄). equity ~$25,133. §5.9 신설·§5.0 축약. 무변경·축적(196/200, 게이트 임박) |
| 2026-06-29 | **★ 196건 종합감사 + §11 일괄검정 + v7.1(사이즈) 적용** (사용자 "지금이 게이트, 결정하라" 지시, 200건 대기 폐기 [[feedback_no_more_sample_gating]]): **전 차원 재계산**(196건 WR35% +$3,020 EV+15 PF1.28). **§11 판정**: H1(즉시역행62건−$5,979)·H2(승자 MFE 43%반납)·H3(long·하락장 최악−$307/short 전regime견조)·H15(단발−$580/연속1-2 +$2,008) 확증 / **H5 기각(반대: 최강신호 99.9+가 EV−$1)** / **H11 의외강세(>5k EV−$42·WR18%, 1-2.5k +$49)** / H8·H4·H6 기각·미결. **★잭팟의존 극단**(top3=99%, top5빼면 −$1,313). **필터반사실**: 어떤 진입필터(파도·방향·OI·consec)도 잭팟 동반사망=순효과≤0(§8.5 재확인). 토요일−$2,075·나쁜시간(전후반 다음수) 매력적이나 데이터마이닝(H12). **★실행결정**: ① **사이즈 cap 4000 적용**(H11, 백테스트 clip +$633, 잭팟무손상)=v7.1 ② **F1 보류**: track_f1 막은32건 +79.9R(완화 어떤조건도 +R=신기루)이나 **단일경로 Timeout 과대평가**(VELVET+33R/CL−3.7%인데+14.5R 비현실)+**backtest124 역추세−657R 정반대** → 적용불가, forward만(backtest_be 1m replay가 정밀검증 경로) ③ 부분익절(H2 반납구제)=출구라 backtest신뢰낮음, 후순위. equity ~$25,133, 무포지션. 재가동 시 v7.1 발효 |
| 2026-06-29 | **★ F1 큰막차예외 — 2단 검증 후 기각(F1 유지 확정)**: 사용자 "제대로 테스트하라"·"교차검증하라" 지시로 2단계 검증. **①정밀 backtest**(F1 막은 counter_trend 32건을 봇 실제 출구로직 1m replay, `backtest_be` 방식): track_f1 단일경로 +79.9R→**진짜 트레일링 +47.7R로 교정**(VELVET 33.6→3.74R, 과대평가 실증). 쪼개니 큰막차(≥20%) 8건 +21R·WR75%로 "큰막차 역추세는 통과" 유망해보임. **②교차검증(실현 PnL)**: 196건 중 *실제진입* 역추세를 막차크기로 분해 → **큰막차(≥20%) 역추세 4건 = 0승4패 −$373**(SIREN/ESPORTS/US/OPN, OPN sigret43%가 −149). F1이전 큰막차역추세 3건도 0승3패 −359. 대조 **순추세 큰막차 7건 +984·WR43%**(흐름순행은 이김). → **shadow(+21R)와 실현(0승4패)이 정반대 = shadow는 신기루**(진입가근사·selection·트레일링추정오차, VELVET 동형). **세 독립증거(실현 0/4·backtest124 −657R·이론) 모두 "역추세 막는게 맞다"** → **F1 큰막차예외 기각, F1 그대로 유지.** ★교훈: shadow(가정)만 보고 변경했으면 손해 변경, 실현 교차검증이 막음(§1.1 산증거). **다음세션 F1 재변경 시도 금지**(forward에서 역추세가 실제 net win 누적될 때만 재고) |
| 2026-06-29 | **★ 부분익절(I2/H2) 백테스트 → 기각**: §8.9 "출구 백테스트 불가"가 풀렸나 확인(POST-fix 98건에 잭팟 8건 전부 포함). **그러나 baseline 재현 재실패**(replay −248 vs actual +1014, VELVET +345 vs실+1386·**H −1 vs실+648**=1m wick이 손절선 스쳐 잭팟이 시뮬서 죽음, §8.9 한계 지속). 정밀측정 불가하나 **방향 분명**: 측정된 모든 부분익절(절반익절+절반트레일)이 현행보다 나쁨(+1ATR −687 ~ +2ATR −69), 잭팟 과소평가 감안하면 실제 더 나쁨. **결론: 부분익절 기각.** 잭팟 8건(+$4,602)이 떴다꺾임 구제한도(+$1,790) 압도 → 잭팟 절반만 잘라도 손해. **H2(승자 43% 반납)=비효율 아닌 잭팟 살리는 필요비용** 확정. ★★**오늘 전체 패턴**: 입구변경(F1)·출구변경(부분익절) 둘다 잭팟죽여 손해, **사이즈(잭팟무관 변수)만 안전** = 잭팟의존봇은 잭팟 스치는 모든 변경에 취약. "기존신호 사후 거르기/자르기" 길은 닫힘 → **개선은 잭팟 빈도↑·크기↑ 또는 새 alpha 추가 방향으로(§7.5 신설)** |
| 2026-06-29 | **★ v8 변동성 게이트 적용 (레짐적응 결론, 사용자 "오늘 업그레이드하라" 지시)**: 레짐분석 → **"빼기식 안전지대" 발견** = 빼기가 실패한건 "잭팟 숨은칸"(F1/필터)을 걸러서고, **잭팟 원래 없는 칸(변동성 기반)을 거르면 안전**(사이즈cap·변동성 공통원리). ①BTC초고변동(btc_4h_atr Q4 EV−38·잭팟2=동조휩쏘) ②저변동코인(atr% Q1 EV−34·WR22%·잭팟2=가짜모멘텀) 둘다 잭팟없는칸. **성과흐름 적응(연속손절·drawdown)은 무효**(손실후EV+13=승리후+13). 임계민감도 → **보수조합 채택**(atr%<1.0 OR btc>1600): +1867, 잭팟 STG1건만(중간 atr%<1.3 OR btc>1500=+1986/잭팟3은 비효율, 공격 atr%<1.7=+2640/84건제외는 과최적화 → 보수가 최적 trade-off). config 토글+임계 조정가능. ⚠️in-sample(임계 과거최적화)이라 forward로 적정성 관찰. **오늘 총 변경: v7.1 사이즈cap + v8 변동성게이트 = 2개 적용, F1완화·부분익절은 데이터가 손해라 기각**(객관유지) |
| 2026-06-29 | **★ v9 잭팟 사이징 적용 (사용자 "후보 계속 진행" 지시, ③)**: ★발견 = **현 ATR리스크균등 사이징이 잭팟에 거꾸로 베팅** — 잭팟 16/21이 고변동코인인데 거기 평균 $1273만 싣고(VELVET+1386에 $997), 저변동(잭팟5/21)에 $3883. ATR사이징(SL거리 역비례)이 고변동=SL멀다=작게베팅이라 잭팟 억제. **고정 $2000 균등으로 교정**(sizing_mode:fixed). 백테스트: 고정2000 단독 +7919(2.6배)·**고정+게이트(D안) +8777(2.9배)**·maxDD −1964→−2125·수익위험비 1.54→**4.13**(단순레버업 아닌 **배분효율** — 모든 대안이 baseline보다 수익위험비 우월). 게이트(v8)와 시너지(D>C>B>A, 게이트가 키운베팅 낙폭까지 완화). ⚠️**3대 경고: ①in-sample(과거잭팟이 고변동이니 당연, 단 잭팟=큰움직임=고변동 경제논리 robust) ②maxDD↑(한방 더 잃을수있음) ③★실거래 슬리피지 미검증=데모최대맹점**(잭팟 소형알트는 호가얇아 큰사이즈시 +8777 환상가능). 사용자 보수선택($2000, 변동성비례 아님). tier cap·lot 통과(저유동 tier4 1000 binding). **오늘 최종: v7.1+v8+v9 = baseline대비 백테스트 2.9배. 다음 forward로 슬리피지·임계 검증, 확신시 변동성비례 확대(§7.5③)** |
| 2026-06-29 | **★ v10 유니버스확대 적용 + ④신호임계 기각 (사용자 "②④ 둘다 진행")**: **②유니버스**: 소형코인 잭팟밀도 18%(대형 5%)·EV+48, 거래소 597개중 현 ~32개만 스캔→10M로 +22개. **min_volume 20M→10M 적용(v10)**. ⚠️과거 미스캔=백테스트 원천불가, forward만(데이터 0이라 어쩔수없음). 슬리피지는 tier4 cap$1000+cooldown 방어. **④신호임계 재시뮬**(유니버스 40개 600봉 1h, 출구1h근사라 상대비교용): 99.0 EV−0.20 / 99.5 −0.11 / 99.8 −0.05, **잭팟수 셋다 2개동일** → **임계 낮추면 약신호 손실만↑·잭팟 안늘어남(강신호에만), 현 99.5 최적 → 신호임계 변경 기각.** ★함의: 신호 빈도는 임계낮추기(약신호=손해)가 아니라 유니버스확대(새코인 강신호)로만. **오늘 총괄: 적용 4개(v7.1 사이즈cap·v8 변동성게이트·v9 잭팟사이징·v10 유니버스) / 기각 3개(F1완화·부분익절·신호임계 — 데이터가 손해/무효라 객관기각). 빼기식 안전지대(변동성)+잭팟사이징(배분효율)+유니버스(잭팟풀)가 오늘의 축. 미검증=v9슬리피지·v10 forward** |
| 2026-06-29 | **v10 첫 운영(~4h) + PC인계**: ★**v10 발효 전건 확인** — 유니버스 **50개**(41→+9 소형)·v9사이징 정확(ACT $2000 고정 / RAVE $1000=저유동 tier4 cap binding=슬리피지 방어 작동)·v8게이트 정상(고변동 통과·BTC ATR813<1600 미발동). 진입 2건(RAVE·ACT long, 둘다 arm A·**둘다 고변동코인=v9 의도대로 잭팟원천에 베팅**). **청산 1건: RAVE BE −$1.10**(★MFE **10.5%→본전 반납**=green→red, bot_version=v10 첫기록). ACT 보유중(한때+10%→현−0.45%, BE미잠금). ★**관찰(n=2, 단정금지)**: 고변동코인 둘다 +10% MFE 떴다 반납 — **고변동=ATR커서 BE(1.5ATR≈+15%)가 멀어 잭팟전환 전 반납**(§8.9 green→red). v9가 고변동에 베팅하나 BE반납 위험 동반=trade-off 첫 정황(§5.10 F 검증개시). **rate limit 다발**(유니버스50개·UTC14시 부하, 47/50 scan·retry회복=critical아님, §8.4). bar893, **ACT 1포지션 보유**·equity $25,127. STOP graceful 종료. n=2·4h=관찰단계 |
| 2026-07-03~06 | **A-2/3/4 데이터안전 인프라 완성 + v10 순항(§5.11)**: 거래로직 무변경. **A-2**(fix_estimated: estimated→corrections 별도파일, 원본 append-only)·**A-3**(integrity 무결성가드: 시작백업+종료 라인수비교)·**A-4**(daily_report: 매일배치=정정+리포트, 메인PC 12:30 스케줄러). **★ freshness 버그 수정**: 거래소 createdTime=진입시각이라 자기레코드 0.4초 배제→estimated 양산하던 봇 버그를 60초 tolerance로(봇 `_get_closed_pnl_record`+fix_estimated), 실증 TLM 봇추정 −$1.1↔실값 **+$11.04**. 테스트 29 passed. 권한 bypassPermissions. **v10 순항: equity $25,133→$29,276(+16%), TAIKO(총 +$2,687)·LAB(+$2,078) 잭팟 견인**하나 소수집중·v10공로 증거 약함(§5.11 B). **PC인계: 이 PC=메인 봇가동, 다른 PC=잠깐 개발 후 복귀(스케줄러 등록 불필요)**. 2포지션(VANRY long·EPIC short) 보유·equity $29,276·bar1053·STOP graceful 종료 |
| 2026-07-08 | **★★ 되감기 백테스트 방법론 붕괴 + 방향 전환(전문가 자문)**: B-1(track_shadow 차단신호 채점)·B-2(지연진입 백테스트) 개발 완료했으나 **재현검증서 무너짐**(§8.9+). B-2 기준선 재현율 **5~9%** — 원인 ① fetch_1m 창버그(진입 몇시간 뒤 봉 조회, B-2만 수정) ② **1분봉 되감기가 봇 1시간봉 추적익절 재현 불가=잭팟 뭉갬**(LAB 실+2078→+189). **4종(track_f1/cap/shadow, backtest_be) 전부 강등=참고용만, 절대값·잭팟판단 금지.** B-1 short_cap 결론·B-2 지연진입 숫자 **무효화**(shadow_scores.INVALID 마커). **★ 전문가 자문 핵심**: ① 진입 선별=추세추종 구조상 막다른 길(§8.5 재확인) ② 지렛대=**출구·사이징·처리량(잭팟 추첨수)** ③ 측정=백테스트 폐기, **봇 내 실시간 페어드 반사실 계측**(같은 데이터로 두 arm 동시측정=되감기편향0)+**forward 무작위 A/B**(해시배정, 1차지표=빈번사건[즉시역행률·본전전환율], 잭팟 거부권, arm당 N 사전등록·중간 peeking 금지) ④ 손익엔진 분리(손실=통계가능/잭팟=계기판만, top5제외 병행+leave-one-out+블록부트스트랩) ⑤ **목표 재정의: 승률→EV×빈도×생존**(승률 추구=꼬리절단=자살) ⑥ 데모 맹점=**잭팟 진입 슬리피지**(EV+$29.9는 실전확인 전) ⑦ 한번에 한 손잡이. **채택 실행순서**: 1)도구 강등 기록(=이 항목·§8.9+) 2)듀얼라인 반사실 계측기(봇 기록전용 수정) 3)BE A/B 판정기준 사전등록 4)v10게이트 후 C-1 사이징 5)B-1 경로독립 지표 재설계 6)지연진입 forward A/B 7)B-3 배경(가설생성기). Step1 진행 |

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
| H5 | 배치내 순위: 동일봉 최강 signal_strength 진입 EV↑ | signal_strength | **★2026-06-29 기각(반대): 강도 99.5-99.9 EV+$27 vs 최강 99.9+ EV−$1. "센 신호=좋다" 착각, 신호강도로 거르지 말 것** |
| **H14** | ★cap 방향 비대칭: 추세장(특히 DOWN_HIGH)서 `short_cap`(=3)이 올바른 방향(추세순행) 진입을 막아 long-against-trend 과진입 유발 → EV↓ | shadow cap-reason × side, side×btc방향 EV | **6월 신규발견: short 신호 47건 중 23%(11건)만 진입, 36건이 short_cap(30)/rank(6) 차단. long against-btc 11건 −$747 = 6월 손실 전부(long with-btc는 본전).** ★**2026-06-15 소급검증 완료(중복제거): short_cap 41건 +97R(꾸준 consec≥1이 +92R, 단발은 본전)·long_cap 22건 +23R(단발 consec0이 +22R, 꾸준은 본전) = 방향별 정반대 → v7 처방 적용**(short3→5·long3→4 확장자리 연속성조건, §10). forward는 `track_cap.py` 추적. ⚠️ in-sample(forward 0)·동시손실위험이라 200건까지 잠정. **★ 2026-06-17 forward 개시: OPG/ZKC 단발(consec0) short가 만기 잭팟(+$409/+$81, v6 진입분)=확장자리 "consec≥1 꾸준만" 처방의 반례 2건. **★ 2026-06-22 BEAT +$125·06-24 BTC short +$198(둘 다 단발)=반례 4건째**(OPG/ZKC/BEAT/BTC, 누계 +$813). track_cap 누적 중, n 소.** |
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
| H11 | tier(사이즈): 저유동성 tier EV 차 | position_size_usd | **★2026-06-29 196감사 강세: >5k 대형 EV−$42·WR18%(패18 −$1,838 vs 승4 +$921) / 1-2.5k +$49 / <1k +$22. 대형코인=모멘텀 약함(잭팟은 작은알트). → v7.1 cap 4000 적용**(tier1/2/hard 10000·5000→4000, 백테스트 clip +$633, 잭팟 무손상). 프록시지만 효과 강함. forward 검증 |
| H12 | 시간: 특정 요일/시간대 EV 약화 | day_of_week·hour_of_day | 셀당 표본 극소, 장기 |
| H13 | 반사실: shadow(거른 신호)가 entered만큼 벌면 선별 무가치 | shadow vs trades | shadow 누적 느림(7건), 장기 |

### v6 개입 후보 (관측데이터로 검정 불가 — backtest/live A-B 필요, 가설 아님)
- **I1** trail 거리(2ATR) 튜닝 · **I2** 부분익절(scale-out) · **I3** BE 트리거(1.5ATR) 타이밍 · **I4** BTC 1h 급변 시 신규진입 정지(chaos=관망) · **I5** regime 게이팅 진입.
- **I6** 극단 sigret 상한/축소 (H7 동기): `|signal_return_pct|`이 큰 트리거봉 진입을 제외 또는 사이징 축소. **관측(2026-06-04, 93 closed)**: 최근20건 즉사(hold≤2,손실) sigret 평균 **+17.4** vs 생존/이익 **−0.5**; 93건 구간별 EV `|sigret|<10 +$8.8(PF1.18) / 10–20 +$90(PF2.74) / ≥20 −$5(PF0.94)`. **중간(10–20)이 sweet spot, 극단(≥20)만 EV음수 — 비선형.** ⚠️ 단 `≥20` 구간 maxW **+$540**(잭팟 동반) → 단순 제외 시 잭팟 동반 사망 위험, 절대 단순컷 금지·backtest 필수. **역방향 진입은 별개 대규모 검증 사안**(중간강도 추종이 best라 전면 반전은 오답).
  - **6월 관측(2026-06-05, n41)**: 극단 `≥20` **6건 전멸 −$651(WR 0/6, EV−$108)**, `10–20` 7건 +$387(EV+$55), `<10` 28건 −$534. 6월엔 극단에 잭팟 미동반 → I6 정황 강화. 단 5월엔 극단에 잭팟 섞여(BSB+540) 단순컷 부결됐음 = 기간에 따라 극단 구간 성격이 달라짐 → 여전히 200건 일괄검정 필요.
  - **backtest 채점 (93건, 2026-06-04, 단순제거 시뮬)**: baseline 누적 +1900. 컷별 → `≥30 제외:+1990 / ≥25:+2334 / ≥20:+1951(EV~0) / ≥15:+648`. **컷 위치에 극도로 민감 = overfitting 경고.** `≥25`가 좋아보이는 건 BSB long(+540,sigret24.4)이 우연히 컷 아래로 생존한 덕; `≥20` 구간 10건 내부 = 잭팟 2건(BSB long+540, BSB short+261=+802) + 손실 8건(−853) = 합 −51(EV≈0, 거를 동기 약함). `≥15`로 내리면 15–20 황금구간(+1251) 침범해 반토막. 절반사이징은 효과 미미(+25). **결론: n93에선 채택 불가(부결), 200건 재검증.** 잭팟이 컷 경계에 산재 = 단순컷 신뢰불가 실증.
- 적용 조건: H2/H3/H7/H8 등이 신호를 준 **뒤** backtest 검증 통과 시에만. 단독 도입 금지.
