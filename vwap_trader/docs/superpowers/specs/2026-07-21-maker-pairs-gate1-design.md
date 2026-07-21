# Maker 실행 쌍 스프레드 MR — Gate 1 소급 채점 설계

> 최초 작성: 2026-07-21 (DEV PC 세션, 브레인스토밍 산출물)
> 상태: **설계 승인됨 → 구현 계획 대기**
> 관련: PLAN.md §1.1·§10(보완재 4연패)·§11. 선행: **쌍 스프레드 MR(taker) = NO-GO but 엣지 실재**(gross EV +0.13%/거래·승률 53%·target 93%, 오직 taker 0.42% 비용에 사망).
>
> **역할 분담(사용자 지시)**: 그리드·판정기준 등 기술 세부는 assistant 자율. 사용자는 최종 GO/NO-GO 리포트만 판단.

## 0. 배경 — 왜 이것만 되살리나
보완재 4연패(개별MR·쌍MR·XS모멘텀·펀딩) 중 **쌍 스프레드만 진짜 엣지**를 보였음: gross EV +0.13%/거래, 승률 53%, 목표달성 93%, 표본 1.06만(견고). 죽인 건 엣지 부재가 아니라 **2다리 taker 수수료 0.42%** 하나. → 되돌림은 본질적으로 **maker(지정가로 유동성 제공)에 적합** — 벌어진 극단에 지정가 걸고 기다리면 taker로 쫓을 필요 없음. maker 수수료는 taker의 ~1/5. **"maker 실행이 이 실재 엣지를 건질 수 있나"**를 검정.

## 1. 가설
**"쌍 스프레드 MR의 실재 엣지(+0.13% gross)를 maker 실행으로 순이익화할 수 있다 — 아낀 수수료 > 놓친 거래(adverse selection) 손실."**

## 2. ★ 이건 p-hacking이 아니다 (규율 명시)
- ❌ p-hacking = 같은 테스트가 실패하니 통과할 때까지 비용을 슬쩍 낮춰 재실행.
- ✅ 정당 = "엣지는 실재(taker 결과가 증명), 실행모델이 관문"이라는 **다른 가설**을 **새로 사전등록**하고, **체결 위험(adverse selection)을 정직하게 모델링**해 검정. 수수료를 임의로 0으로 놓는 게 아니라 실제 경로로 체결을 판정.

## 3. 스코프 (Gate 1만)
봇 무변경. 소급 채점만. 통과해야 Gate 2 설계.

## 4. 메커니즘 (쌍 harness 재사용 + 체결/비용층 신규)
- **신호**: 스프레드 z ≥ z_entry (쌍과 동일. `pairs_spread`·`mr_signal.zscore` 재사용). 매 봉 후보(taker 결과와 apples-to-apples 위해 신호집합 동일).
- **★ maker 진입 — 실제 경로 체결**: 신호봉 스프레드 레벨 `L = spread[i]`에 지정가.
  - short(z>0, 스프레드 하락 베팅=스프레드 매도): 이후 `fill_window`봉 중 **spread ≥ L** 되는 첫 봉에서 체결(가격 L). 없으면 **미체결=놓침**.
  - long(z<0): **spread ≤ L** 되는 첫 봉 체결. 없으면 놓침.
  - ⇒ 즉시 되돌아가는(내가 이기는) 거래는 지정가를 안 건드려 **놓침** = adverse selection 자동 반영.
- **청산**: 체결봉 f부터 `simulate_pair_exit` 재사용(진입가 L, future z/s from f+1). 출구 target/stop/time.
- **비용**(2다리, 출구사유별):
  - 진입 maker: 2 × MAKER_FEE (슬리피지 ~0, 내가 가격 지정)
  - 출구 target(되돌림이 가격 데려옴=maker): 2 × MAKER_FEE
  - 출구 stop·time(즉시 나가야=taker): 2 × TAKER_FEE + 2 × SLIP
  - MAKER_FEE=0.0002(0.02%/편도), TAKER_FEE=0.00055, SLIP=0.0005. → target거래 ~0.08% / stop·time거래 ~0.25% (taker 0.42% 대비 대폭↓, target이 93%라 평균 크게↓)
- **손익**: `pnl_log = ±(L − exit_s)` − 비용. (short면 +부호)
- **★ 핵심 진단**: **체결률**(=filled/(filled+missed)) + **체결거래 gross EV**(놓친 뒤에도 엣지 남나) + net.

## 5. 사전등록 그리드 (자율 확정, 실행 前 봉인)
| 파라미터 | 후보 | 의미 |
|---|---|---|
| `n` | {24, 72} | rolling 창 |
| `z_entry` | {2.0, 2.5} | 진입 이탈 |
| `z_target` | {0.5, 1.0} | 부분복귀 목표(taker 최적이 여기) |
| `fill_window` | {3, 8} | 지정가 체결 대기 봉수 |

= 16조합(z_stop 3.5 고정), Bonferroni 0.05/16 ≈ 0.003125. 앵커=BTC. 유니버스=알트−BTC.

## 6. 판정 기준 (사전등록, 3중 AND — 쌍과 동일)
1. **수익성**: 최적 건당 순EV > 0(자유마진 없이 0 초과 — maker라 문턱 낮춤), 부트스트랩 P(≤0) < 0.05/16
2. **강건성**: 중앙값 EV > 0, 양수 조합 ≥60%, 최적 이웃 양수
3. **보완성**: 일별 모멘텀 상관 < 0.3, 가뭄이익 ≥50%
- 표본 게이트: 최적 조합 **체결거래 ≥ 100건**. 미만 "잠정".
- ★ 부수 진단(참고): 체결률이 너무 낮으면(예 <30%) 실전 실행 곤란 → 리포트 명시.

## 7. 구조 — 쌍 harness 재사용
```
[사전등록] maker_pairs_config.py (그리드·수수료·임계, 실행 前 커밋)
[재사용]   pairs_spread.* · mr_signal.zscore · pairs_exit.simulate_pair_exit · mr_score.* · mr_data.fetch_1h_history · mr_gate1._momentum_context/_span
[신규]     maker_fill.py        — check_fill, trade_cost (순수)
[신규]     maker_pairs_gate1.py — 백테스트(신호→체결→청산) + 체결률/gross 분해 + 판정 + 리포트
```

## 8. 테스트 전략
- `maker_fill`(순수): check_fill(방향별 체결/미체결·fill_window 경계), trade_cost(출구사유별 maker/taker)
- 재사용 유닛은 기존 테스트
- TDD

## 9. 명시적 비목표 (YAGNI)
- 봇 무변경. 부분체결·호가깊이·동적사이징 없음(Gate 1은 가설 생사만). intra-bar 무시(종가 스프레드 체결 판정).

## 10. 위험·한계
- **★ 체결 모델이 종가 기반**(intra-bar 스프레드 부정의) — 실제론 봉 내 지정가 체결이 더 잦을 수 있어 체결률 과소평가 가능(보수적). 반대로 adverse fill(불리 체결)은 과소반영 가능 → 양방향 근사, 리포트 명시.
- **maker 수수료 가정**(0.02%): Bybit 표준, 실제 등급별 상이. 리베이트 미반영(보수).
- **미체결=기회손실 미계상**: net은 체결거래만 집계(실전선 미체결이 자본 놀림). 체결률로 별도 표기.
- **표본**: 체결 필터로 taker(1.06만)보다 표본↓ → 잠정 가능성.
- ⚠️ adverse selection이 gross를 얼마나 깎느냐가 전부 — 죽을 수도.

## 11. 최종 산출물 — `reports/maker_pairs_gate1_verdict.md`
판정 한 줄 / 근거 3줄 / 최적 카드(파라미터·건당EV·승률·PF·**체결률·gross vs net**·표본·출구분해) / 쉬운 설명 / 권고 / 재현. 사용자는 이 1페이지만 판단.
