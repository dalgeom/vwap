# 정본 자동 병합기 설계 — A-1 `build_canonical.py`

> 작성: 2026-07-06 | 근거: PROJECT_ANALYSIS_ROADMAP.md §6-A-1 / A-2·A-3 설계(2026-07-03) §4 "A-1은 나중에 이 함수를 감싼다"
> 성격: **인프라(거래로직 무변경)** — 봇 수익·승률에 영향 0, v10 검증과 병행 안전.
> 목적: 지금까지 매 분석 세션마다 손으로 하던 "corrected 106 + raw 신규분 병합"을 단일 함수로 자동화.
> 모든 분석 스크립트의 단일 입구를 만든다 — 실수 여지(병합 누락·중복·버그값 사용)를 기계가 제거.

---

## 1. 현재 데이터 지형 (2026-07-06 실측)

| 파일 | 건수 | 성격 |
|------|------|------|
| `data/trades_momentum.jsonl` (raw) | 222 | 봇 append 원본. trade_id 전건 존재, 중복 0. 단 6/05 이전 구간은 PnL 버그 시절 값 포함 |
| `data/trades_momentum_corrected.jsonl` | 106 | 6/05 거래소 실측 재구축본. **106건 전부 raw와 trade_id 겹침** |
| `data/pnl_corrections.jsonl` | 5+ | A-2가 estimated→exchange 정정을 append하는 오버레이 |

- 스키마 차이: corrected에는 후기 필드 9개(`bot_version`, `ab_arm`, `be_trigger_atr`, `signal_ret_6/12/24`, `signal_consec`, `signal_oi_chg`, `signal_vol_ratio`)가 없고, 재구축 감사 필드 4개(`match_conf`, `exchange_order_id`, `match_dt_s`, `exchange_avg_entry`)가 따로 있다.
- 발견된 불일치: `daily_report.py`(A-4)는 raw+corrections만 읽어 corrected 106건이 미반영 — 누적 성적이 정본과 다른 숫자를 내는 중. 본 작업에서 함께 해소한다.

## 2. 제1원칙

**입력 3파일은 전부 읽기 전용. 정본은 파생물이며, 진실은 항상 함수(`load_canonical`), 파일은 스냅샷.**

- A-2·A-3 설계의 제1원칙("원본은 봇의 append 외 수정 금지")을 그대로 계승.
- 정본 파일이 오래된 채 최신인 척하는 stale 사고를 막기 위해, 분석은 파일이 아니라 함수를 import한다.

## 3. 병합 규칙 (핵심 로직)

1. trade_id로 매칭. **겹치는 106건 = 필드 유니온**: corrected 행이 베이스(손익 실측값), raw 쌍둥이에서 corrected에 없는 필드만 보충(`bot_version` 등). 양쪽에 다 있는 필드는 corrected 승.
2. raw에만 있는 건(현재 116)은 그대로.
3. 그 위에 `corrections.apply_corrections()` 오버레이(A-2 정정분).
4. 각 행에 출처 표식 1필드 추가 — `canonical_src`: `"corrected+raw"` | `"raw"`.
5. `exit_timestamp_utc` 오름차순 정렬(없으면 `timestamp_utc` 폴백).
6. 자체 검증: 결과 trade_id 중복 0 — 위반 시 즉시 예외(조용한 오염 금지).

## 4. 인터페이스 (이중)

- **import**: `from build_canonical import load_canonical` → `list[dict]`. 호출 시마다 소스 3개에서 갓 병합(222건 규모라 캐시 불필요). 앞으로 모든 분석 스크립트의 단일 입구.
- **CLI**: `python build_canonical.py` → `data/trades_canonical.jsonl` 기록 + 요약 출력(총 건수·누적 PnL·`canonical_src`별/`pnl_source`별 분포).
- `data/trades_canonical.jsonl`은 **.gitignore 등록** — 입력 3개가 git에 있으므로 언제든 재생성 가능한 파생물.

## 5. daily_report.py 통합 (사용자 승인됨)

- `daily_report.py` main의 `apply_corrections(fe.load_trades(), corr)` → `load_canonical()` 교체(1줄).
- corrections 오버레이는 `load_canonical` 내부에서 이미 적용되므로 이중 적용 제거. 단 `corr`(read_corrections 결과)의 다른 용도(estimated 잔존 카운트 등)는 그대로 유지.
- 효과: 일일 리포트 누적 성적에 옛 106건의 거래소 실측값 반영 — 기존 발행분과 숫자가 달라지는 것은 의도된 교정.

## 6. 오류 처리

- corrected 파일 부재 → 경고 로그 후 raw+corrections만으로 동작(환경 이식성).
- corrections 부재 → `corrections.py`가 이미 빈 dict로 처리.
- raw 부재 → 즉시 예외(정본을 만들 수 없는 상태는 침묵하지 않는다).

## 7. 테스트 (`tests/test_build_canonical.py`, 기존 pytest 스타일)

- ① 유니온 병합: corrected 값 우선 + raw 필드 보충 확인
- ② raw-only 행 통과
- ③ corrections 오버레이 적용(pnl_usd/exit_price/pnl_pct/pnl_source 교체)
- ④ exit_timestamp_utc 정렬
- ⑤ trade_id 중복 시 예외
- ⑥ corrected 부재 폴백
- ⑦ `canonical_src` 표식 정확성

## 8. 이 작업이 아닌 것 (스코프 경계)

- 5분봉 시대 파일(`trades_momentum_v1~v41.jsonl`) 미포함 — 정본 = 1h봉 시대만(로드맵 정의).
- 기존 분석 스크립트(analysis_*.py, backtest_*.py 등) 일괄 전환 안 함 — 새 분석부터 `load_canonical` 사용.
- 봇(`momentum_bot.py`) 무변경 — v10 검증 보호.
- shadow/slippage 병합 없음 — trades 정본만.

## 9. 리스크 / 롤백

- 입력 전부 읽기 전용 + 산출물은 파생 파일 1개뿐 → 최악의 경우도 스크립트·파생파일 삭제로 원복, 봇 무영향.
- daily_report 통합은 1줄 교체 — 문제 시 해당 줄만 revert.
