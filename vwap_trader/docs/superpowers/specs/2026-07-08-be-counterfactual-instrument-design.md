# BE A/B 반사실 계측기 설계 — `be_counterfactual` (봇 내장)

> 작성: 2026-07-08 | 근거: PLAN.md §8.9+(되감기 강등)·§10 2026-07-08(전문가 자문 실행순서 Step 2) / §5.10 F(BE A/B)
> 성격: **봇 내장 실시간 계측(기록 전용)** — 실제 매매·주문 무변경. 되감기(backtest)가 아니라
> 봇이 실시간으로 보는 그 데이터로 두 arm을 동시 측정 → 재현 편향 0.
> 목적: 매 거래에서 실제 arm과 **반대 arm(본전잠금 트리거만 다름)**의 청산 결과를 쌍(paired)으로
> 기록해, BE A/B(arm A 1.5ATR vs arm B 0.75ATR)를 표본 2배·편향 0으로 판정할 재료를 만든다.

---

## 1. 현재 구조 (2026-07-08 실측)

- 진입 시 `_get_ab_arm()`([momentum_bot.py:966](../../../src/vwap_trader/momentum_bot.py#L966))이 trade_id parity로 arm A/B 배정, `OpenPosition.ab_arm`·`be_trigger_atr` 세팅. 두 arm은 **초기 SL(1.5ATR)·추적(2ATR) 동일, 본전잠금 트리거만 다름**(A=1.5·B=0.75, `strategy.be_trigger_atr`/`be_trigger_atr_b`).
- 매분 `_manage_positions()`([:1305](../../../src/vwap_trader/momentum_bot.py#L1305)) → `_update_trailing_sl(pos, price_map)`([:1223](../../../src/vwap_trader/momentum_bot.py#L1223))가 봉 고저가(`_candle_cache`)로 `best_price`·`be_triggered` 갱신 + 실제 거래소 SL 이동. 이후 거래소 size==0이면 청산 인식·`_log_trade`([:739](../../../src/vwap_trader/momentum_bot.py#L739)).
- 현재 A/B는 **실청산 PnL을 arm별로 나눠** 비교(split-sample). 문제: arm B 잭팟 실청산 0건, 표본 반토막, 잭팟 지배로 검정력 부족.

## 2. 제1원칙

**실제 매매·주문·arm 배정·진입/청산 로직을 일절 바꾸지 않는다. 그림자(shadow) arm은 계산·기록만
하며 거래소 API를 호출하지 않는다. 봇 hot loop에 넣으므로, 그림자 로직은 순수 함수로 분리해
API 없이 단위검증한 뒤 부착한다(그림자 버그가 실매매를 멈추면 안 됨).**

## 3. 그림자 상태 (OpenPosition 필드 추가 + state 저장)

포지션마다(신규 진입분만):
- `shadow_arm` (str): 실제의 반대. 실제 A → "B", 실제 B → "A". 레거시/비활성 = "".
- `shadow_be_trigger` (float): 반대 arm의 본전잠금 트리거(A=1.5·B=0.75).
- `shadow_best_price` (float): 그림자 best (진입가로 초기화).
- `shadow_be_triggered` (bool).
- `shadow_sl` (float): 그림자 손절선. 초기 = 실제와 동일(진입 ∓ 1.5ATR).
- `shadow_exit_price` / `shadow_exit_reason` / `shadow_exit_ms` (청산 전 None): 그림자 청산 결과.

`state_momentum.json` 직렬화에 추가(재시작 안전). 계측기 이전 오픈 포지션은 이 필드가 없으므로
로드 시 `shadow_arm=""`(비활성)으로 초기화 → 그림자 없이 정상 처리(허위 그림자 금지).

## 4. 그림자 갱신 = 순수 함수 (backtest_be 로직 계승, 주문 없음)

`update_shadow(direction, entry, atr, shadow_be_trigger, trail_mult, shadow_state, bar_high, bar_low, cur)`
→ `(exited: bool, exit_price, reason)`. 매분, 실제 SL 갱신 **직후** 같은 봉 데이터로 호출.

순서(look-ahead 금지, backtest_be와 동일):
1. **먼저 돌파 검사** (이번 분 시작 시점의 `shadow_sl` 기준): long `bar_low <= shadow_sl` / short `bar_high >= shadow_sl` → 그림자 청산. `exit_price=shadow_sl`, `reason` = `shadow_be_triggered`면 "TrailSL" 아니면 "SL". 반환 후 갱신 중단.
2. 미돌파면 이번 봉으로 갱신: best 갱신 → 본전잠금 트리거(이익 `shadow_be_trigger×ATR` 도달 시 `shadow_sl`=진입) → 추적(`best ∓ trail_mult×ATR`) + spike-retrace 가드(실제와 동일: 추적선이 현재가 침범 시 진입/기존 SL로 제한).

실제 `_update_trailing_sl`은 무변경. 그림자 갱신은 **별도 순수 함수**로 두고 `_manage_positions`가
실제 갱신 뒤 그림자 상태에 대해 호출(그림자 청산되면 pos에 결과 기록, 실매매엔 무영향).

## 5. 청산 쌍 기록 (별도 파일)

- 산출: `data/be_counterfactual.jsonl` — **실제 청산된 거래 1건 = 1줄**(trade_id 키). trades 원장·shadow_momentum과 분리(기존 패턴).
- 규정:
  - 그림자가 실제보다 **먼저** 돌파 → §4에서 그때 `shadow_exit_*` 기록.
  - 실제가 **먼저** 청산(거래소 size==0) → 미청산 그림자는 실제 청산가로 마감(`shadow_exit_price=실제 exit_price`, `reason="REAL_EXIT"`, ms=실제 청산시각).
  - 실제 청산 시점에 한 줄 기록: `trade_id, symbol, direction, entry_price, atr_at_entry, position_size_usd,
    real_arm, real_be_trigger, real_exit_price, real_exit_reason, real_pnl,
    shadow_arm, shadow_be_trigger, shadow_exit_price, shadow_exit_reason, shadow_pnl,
    real_exchange_pnl, real_exit_ms, shadow_exit_ms`.
  - **쌍 비교는 apples-to-apples**: `real_pnl`·`shadow_pnl` **둘 다** `pnl_of(entry, 각 exit_price, direction, position_size_usd)`로 동일 계산(수수료 왕복 0.11%, backtest_be 동일). 판정(Step 3)은 이 둘의 차이만 쓴다.
  - `real_exchange_pnl` = 거래소 실현손익(`_log_trade`가 쓰는 값)을 **검증용 참조**로 병기 → `pnl_of(real_exit_price)`가 실제 실현손익과 맞는지 대조하면 그림자 계산의 신뢰도까지 자동 점검(계측기 자체 재현검증).

## 6. 설정 토글 / 롤백

- `strategy.be_counterfactual_enabled` (기본 true). false면 그림자 갱신·기록 전부 스킵 = 즉시 롤백.
- 신규 필드·파일뿐이므로 코드 제거 없이 토글만으로 원복.

## 7. 오류 처리

- 봉 캐시 없으면(그림자 갱신 불가) 이번 분 그림자 스킵(다음 분 재시도), 실매매 영향 0.
- 그림자 계산 예외는 try/except로 격리 — **그림자 오류가 절대 실매매 루프를 멈추지 않게** 감싼다(로그만).
- `be_counterfactual.jsonl` 쓰기 실패는 로그 후 계속(실매매 무관).

## 8. 테스트 (`tests/test_be_counterfactual.py`)

순수 함수 `update_shadow`를 API 없이 검증(backtest_be 테스트 형식):
- ① long 즉시 SL: bar_low ≤ 초기 SL → exited, "SL", exit=shadow_sl.
- ② long 본전잠금→추적→돌파: best 상승으로 BE arm, 추적 후 저가 돌파 → "TrailSL".
- ③ 미돌파(계속 보유): exited=False, 상태만 갱신.
- ④ short 대칭 1건.
- ⑤ look-ahead 금지: 같은 봉에서 돌파와 갱신이 섞이지 않음(돌파 우선, 이후 갱신 중단).
- ⑥ 쌍 PnL: 실제/그림자 exit로 pnl_of 계산·쌍 레코드 조립.
- 봇 부착부는 통합 스모크(그림자 활성 시 실제 SL·주문 경로 불변)로 확인.

## 9. 이 작업이 아닌 것 (스코프 경계)

- 실제 arm 배정·randomization·진입/청산/사이징/게이트 **무변경**. arm B는 여전히 절반 실기동(사용자 확정: 순수 additive).
- 추적폭(2ATR) 등 다른 출구 파라미터의 반사실은 범위 밖(YAGNI, 필요 시 후속 일반화).
- BE A/B **판정 자체는 Step 3**(사전등록 기준). 이 계측기는 재료(쌍 데이터)만 만든다.
- daily_report 통합·되감기 도구 수정은 범위 밖.

## 10. 리스크 / 롤백

- 최대 리스크 = **hot loop 오염으로 봇 정지**. 완화: 순수 함수 단위테스트 + 그림자 전체 try/except 격리 + 설정 토글.
- 데이터: 새 파일 1개 + state 필드 추가(스키마 append). 파일 삭제·토글 off로 완전 원복, 실매매·기존 데이터 무영향.
- 편향: 그림자 청산가=shadow_sl 가정(실제는 tick 체결)이라 미세 비대칭 — 봇 자체 로직과 동일 근사. 2차효과(자리/자본 재사용)는 미포함(per-trade 출구 비교엔 정확). Step 3 판정은 이 한계를 문구로 고정.
