## estimated 자동정정 (A-2) — 매일 실행 등록
윈도 작업 스케줄러(taskschd.msc) → 작업 만들기:
- 트리거: 매일 1회 (봇 정각 scan 피해 매시 30분 권장, 예: 매일 12:30)
- 동작: 프로그램 시작
  - 프로그램: C:\Users\PC\Desktop\현진\code\vwap_trader\venv\Scripts\python.exe
  - 인수: fix_estimated.py
  - 시작 위치: C:\Users\PC\Desktop\현진\code\vwap_trader
  - 환경변수 PYTHONIOENCODING=utf-8 (배치 래퍼 권장)
수동 실행: cd vwap_trader; PYTHONIOENCODING=utf-8 ./venv/Scripts/python.exe fix_estimated.py

동작: pnl_source=estimated이고 청산 7일 이내이며 아직 미정정인 거래를 거래소 실값으로 조회해
data/pnl_corrections.jsonl 에 append(원본 trades_momentum.jsonl 불변). 분석은 corrections.apply_corrections로 오버레이.

## 일일 배치 (A-4) — 매일 실행 등록 (권장: fix_estimated 대신 이걸 등록)
daily_report.py는 내부에서 fix_estimated 정정을 먼저 수행하므로, 스케줄러엔 **daily_report.py 하나만** 등록하면 됩니다.
- 트리거: 매일 1회 (봇 정각 scan 피해 매시 30분, 예: 매일 12:30)
- 프로그램: C:\Users\PC\Desktop\현진\code\vwap_trader\venv\Scripts\python.exe
- 인수: daily_report.py
- 시작 위치: C:\Users\PC\Desktop\현진\code\vwap_trader
- 환경변수 PYTHONIOENCODING=utf-8
동작: ①estimated 정정(→pnl_corrections.jsonl) ②reports/YYYY-MM-DD.md 생성.
수동 실행: cd vwap_trader; PYTHONIOENCODING=utf-8 ./venv/Scripts/python.exe daily_report.py
