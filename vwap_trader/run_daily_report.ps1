# A-4 일일 리포트 실행 래퍼 (윈도 작업 스케줄러용)
$env:PYTHONIOENCODING = "utf-8"
Set-Location "C:\Users\PC\Desktop\현진\code\vwap_trader"
& ".\venv\Scripts\python.exe" "daily_report.py" *>> "logs\daily_report.log"
