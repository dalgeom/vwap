# A-4 일일 리포트 실행 래퍼 (윈도 작업 스케줄러용)
# 1) daily_report.py 사실 보고서 생성  2) claude -p(구독=무과금) 자아성찰로 슬롯 채움
$ErrorActionPreference = "Continue"
$env:PYTHONIOENCODING = "utf-8"
Set-Location "C:\Users\PC\Desktop\현진\code\vwap_trader"
$log = "logs\daily_report.log"
$claude = "$env:APPDATA\npm\claude.cmd"

# 1. 사실 리포트 생성 (기존 동작 — 모든 스트림 로그로)
& ".\venv\Scripts\python.exe" "daily_report.py" *>> $log

# 2. 오늘 리포트 파일 = KST 어제 (daily_report의 day 로직과 동일: UTC now +9h -1일)
$day = (Get-Date).ToUniversalTime().AddHours(9).AddDays(-1).ToString('yyyy-MM-dd')
$report = "reports\$day.md"

# 3. 자아성찰 (claude -p headless, 구독 인증=무과금. 실패해도 리포트는 유지)
if ((Test-Path $report) -and (Test-Path $claude)) {
    try {
        $facts = Get-Content -Raw -Encoding utf8 $report
        $prompt = @"
너는 자동매매 봇이고 사장님께 매일 보고서를 쓴다. 아래 오늘 보고서를 읽고, 맨 끝 '오늘의 자아성찰' 자리에 그대로 들어갈 성찰 문단을 써라.

[출력 규칙 엄수]
- 오직 성찰 문단(3~5문장) 하나만 출력.
- 제목/머리말/꼬리말/구분선(---)/따옴표/'성찰입니다' 같은 안내문 금지.
- 파일수정·권한 언급 금지. 너는 글만 쓴다.
- 5단계 보고·메타설명 금지.
- 우리말, 과장·단정 금지(잭팟은 소수표본=계기판).
- 내용: 오늘 배운 점 1~2개 + 앞으로 해볼 구체 제안 1개.

--- 오늘 보고서 ---
$facts
"@
        $reflection = ($prompt | & $claude -p --output-format text 2>> $log | Out-String).Trim()
        if ($reflection) {
            $placeholder = '_오늘의 자아성찰은 매일 AI가 직접 작성합니다 (Claude Code CLI 로그인 후 자동 활성)._'
            $content = (Get-Content -Raw -Encoding utf8 $report).Replace($placeholder, $reflection)
            [System.IO.File]::WriteAllText((Resolve-Path $report).Path, $content, (New-Object System.Text.UTF8Encoding($false)))
            "reflection written to $report" | Out-File -Append -Encoding utf8 $log
        } else {
            "reflection empty - placeholder kept" | Out-File -Append -Encoding utf8 $log
        }
    } catch {
        "reflection step failed: $_" | Out-File -Append -Encoding utf8 $log
    }
}
