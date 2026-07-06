# 차단신호 소급 채점기 설계 — B-1 `track_shadow.py`

> 작성: 2026-07-06 | 근거: PROJECT_ANALYSIS_ROADMAP.md §6-B-1 / PLAN.md §8(F1 3중 검증 이력)
> 성격: **측정 도구(거래로직 무변경)** — 읽기 전용 분석, v10 검증과 병행 안전.
> 목적: 봇이 차단한 신호 전체를 "안 막았으면 어땠나"로 소급 채점해, 정원·순위 규칙이
> 잭팟을 걸러냈는지(로드맵 최대 미지수 = rank_cutoff)를 데이터로 판정할 재료를 만든다.

---

## 1. 현재 데이터 지형 (2026-07-06 실측)

- `data/shadow_momentum.jsonl`: **267건** (2026-05-29 ~ 07-05).
- 사유 분포: rank_cutoff 99 / short_cap 80 / long_cap 24 / counter_trend 46 / slippage_cooldown 13 / low_vol_coin 3 / order_failed 2. 정원류(rank+cap) = 203건 = 76%.
- 채점 필수 필드(`signal_price`, `atr_at_entry`, `timestamp_utc`, `symbol`, `side`) 결측 0.
- 기존 `track_f1.py`(146줄)·`track_cap.py`(159줄): 코드 90% 중복 + **옛 PC 경로 하드코딩으로 현 환경 실행 불가**. B-1이 이 둘을 일반화·대체한다(두 파일은 검증 이력으로 무변경 존치 — 사용자 확정).

## 2. 제1원칙

**입력(shadow·config)은 읽기 전용. 산출물은 점수 파일 1개뿐. 거래·주문 API는 일절 호출하지 않는다(공개 klines 조회만).**

## 3. 채점 방식 (track_f1 로직 계승 — 기존 검증과 같은 자)

1. 진입 근사 = `signal_price` (실체결은 다음 봉 시가 — 극단 막차 신호일수록 오차 큼, 한계 문구로 고정 출력).
2. 봇 스탑로직 재생: 초기 SL 1.5×ATR → 본전잠금(이익 1.5×ATR 도달 시 SL=본전) → 추적익절 2.0×ATR + spike guard(추적선이 현재가 침범 시 본전/기존 SL로 제한) → 48h 시한만기.
3. 본전잠금 트리거 = **1.5(A그룹) 고정** — F1 3중 검증(track_f1)과 동일 기준이라 비교 가능. B그룹(0.75) 변형 채점은 범위 밖(YAGNI).
4. 지표 = **R-배수** (outcome% ÷ 초기 손절거리%, SL = −1R). 사이징 무관이라 코인 크기별 상한 논쟁과 분리됨.
5. 미종결 신호 = `OPEN`(잠정) — 매 실행 시 재채점.
6. 1m klines: pybit 공개 `get_kline`(demo 계정 클라이언트, 기존과 동일), 1000봉 페이지네이션 + rate-limit sleep(기존 0.1s/페이지, 신호당 0.15s 계승).

## 4. 증분 구조 (사용자 확정: 점수파일 + 증분 재채점)

- 산출: `data/shadow_scores.jsonl` — 1신호 1줄.
- 레코드 키 = `timestamp_utc|symbol|side` 조합(shadow에 고유 id 없음. timestamp는 마이크로초 포함이라 실질 유일).
- 레코드 필드: 키 3개 + `shadow_reason`, `entry`(=signal_price), `atr_at_entry`, `outcome_pct`, `R`, `exit_reason`(SL/TrailSL/Timeout/OPEN), `scored_at`(UTC), 참조용 `signal_return_pct`·`signal_consec`·`regime`.
- 실행 흐름: 기존 scores 로드 → shadow 전건 순회 → **확정 건(exit_reason ∈ {SL, TrailSL, Timeout}) 스킵, 신규·OPEN·NO_DATA만 API 재생** → 전체 목록을 파일로 재기록(파생물이므로 전체 재기록 허용).
- `shadow_scores.jsonl`은 **git 추적** — 재생성에 API 수 분이 들고 "데이터가 자산" 원칙. 원본 shadow는 절대 쓰지 않는다.

## 5. 집계·출력 (콘솔)

1. **사유별 점수판**: 건수 / 승(R>+0.05)·패(R<−0.05)·본전 / sum R / 평균 R / OPEN 수. $ 추정은 track_f1의 RISK_USD 근사 계승(참고치 명시).
2. **파도 dedup 뷰**: 같은 `symbol+side` 신호를 시간순으로 훑어, **그룹의 마지막 신호 시각 기준 48h 이내** 재발이면 같은 파도로 연쇄 병합하고 **첫 신호만** 집계(track_cap 방식 계승). rank_cutoff의 같은-파도 중복 과대평가 방지. **원신호 기준·파도 기준 둘 다 출력, 판정은 파도 기준.**
3. **사유별 판정 문구**: sum R(파도 기준, OPEN 포함/제외 병기)이 +0.3R 초과면 "승자를 걸렀다 — 규칙 재검토 후보", −0.3R 미만이면 "손실을 막았다 — 규칙 유지", 사이면 "판정 불가(표본/근소)".
4. **고정 경고 문구**: "단일경로 소급은 과대평가 경향(F1 실증) — 1차 스크리닝. 유망 시 1m 정밀재생 2차 검증 필요"(로드맵 §6-B-1 주의사항 그대로).

## 6. 오류 처리

- klines 응답 실패/빈 응답 → 해당 신호 `exit_reason="NO_DATA"`로 기록하고 계속(다음 실행 때 재시도 대상).
- shadow 파일 부재 → 즉시 예외. scores 파일 부재 → 첫 실행으로 간주(전량 채점).
- `.env`/API 키 부재 → 즉시 예외 + 안내 메시지(공개 klines라도 기존 스크립트와 동일하게 인증 클라이언트 사용).

## 7. 테스트 (`tests/test_track_shadow.py`)

replay는 순수 함수로 분리해 API 없이 검증:
- ① long: 즉시 SL 히트 → −1R 상당, exit_reason=SL
- ② long: 본전잠금 후 추적익절 → R>0, TrailSL
- ③ 시한만기(48h) → Timeout, 종가 기준
- ④ short 대칭 케이스 1개
- ⑤ 미종결 → OPEN
- ⑥ 증분: 확정 건 스킵 + OPEN·신규만 재채점 대상 선정
- ⑦ 파도 dedup: 48h 내 재발 신호 그룹핑, 첫 신호만 집계
- 실데이터 E2E는 구현 마지막 실제 1회 실행으로 검증(첫 실행 ~5-10분 예상).

## 8. 이 작업이 아닌 것 (스코프 경계)

- `track_f1.py`·`track_cap.py` 수정·삭제 없음(검증 이력 보존, track_shadow가 기능적 대체).
- 봇·daily_report·거래로직 무변경. B그룹(0.75) 트리거 변형, 1m 정밀 2차 검증, daily_report 통합은 전부 범위 밖(필요 시 후속).
- 정원·순위 규칙의 실제 변경은 C 영역 — 이 도구는 측정만 한다.

## 9. 리스크 / 롤백

- 읽기 전용 + 산출물 1개 → 스크립트·점수파일 삭제로 완전 원복, 봇 무영향.
- API 부하는 공개 조회 + sleep으로 기존 스크립트 수준. 봇과 동시 실행해도 주문 경로와 무관.
- 소급 과대평가 리스크는 도구가 스스로 경고 문구를 출력해 관리(§5-4).
