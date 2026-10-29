# 2026-10-29 롱 전용 분석 스크립트 (재현용)

모두 세션 임시폴더(scratchpad)에서 쓰던 그대로라 `SP` 경로(캐시·중간 산출물 위치)가 하드코딩돼 있다. 재현하려면 `SP`를 쓸 폴더로 바꾸고 아래 순서로 실행한다 (인터넷 필요, 거래소 공개 시세만 사용).

1. `shadow_sim.py` → 실전 shadow+거래 신호를 1h봉으로 시뮬 (`bars_cache.json`, `sim_out.json`)
2. `shadow_sim_demo.py`, `sim_demo_trades.py` → 데모 구간 (`bars_cache_demo.json`)
3. `featscan.py`(유니버스 `universe.json` 생성) → `featscan2.py`(특징별 3분위)
4. `fetch5m.py` → 5분봉 캐시(`bars5m.json`). ★1h봉 시뮬은 봇의 분 단위 추적손절을 과대평가함 — 출구 실험은 반드시 5분봉으로.
5. `trail5m.py`(손절폭·트레일·만기), `portsim5.py`(포트폴리오), `mc.py`(회복 확률 몬테카를로)
- `decomp.py`(방향·구간별 분해), `vol_diag.py`(일별 진입·shadow 사유), `exitgrid*.py`/`portsim.py`(1h봉 버전 — 참고용, 결론은 5분봉 기준)

⚠ 전부 in-sample(이 데이터에서 본 것), 수수료·슬리피지는 건당 고정비용 가정. 보정: 1h봉 시뮬 vs 실전 86건 손익 합 -94.7 vs -105.2, 건별 상관 1.00.
