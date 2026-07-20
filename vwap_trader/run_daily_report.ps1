# A-4 일일 리포트 실행 래퍼 (윈도 작업 스케줄러용)
# 1) daily_report.py 사실 보고서 생성  2) claude -p(구독=무과금) 자아성찰로 슬롯 채움
# -Day YYYY-MM-DD 지정 시 그 날짜 재생성(미지정=KST 어제, 스케줄 기본).
param([string]$Day = "")
$ErrorActionPreference = "Continue"
$env:PYTHONIOENCODING = "utf-8"
# 한글 프롬프트를 claude(native)로 파이프할 때 ?로 깨지지 않게 UTF-8 강제
$OutputEncoding = New-Object System.Text.UTF8Encoding $false
try {
    [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
    [Console]::InputEncoding = New-Object System.Text.UTF8Encoding $false
} catch {}
Set-Location "C:\Users\PC\Desktop\현진\code\vwap_trader"
$log = "logs\daily_report.log"
$claude = "$env:APPDATA\npm\claude.cmd"

# 1. 사실 리포트 생성 (기존 동작 — 모든 스트림 로그로)
if ($Day) {
    & ".\venv\Scripts\python.exe" "daily_report.py" $Day *>> $log
    $day = $Day
} else {
    & ".\venv\Scripts\python.exe" "daily_report.py" *>> $log
    # KST 어제 (daily_report의 day 로직과 동일: UTC now +9h -1일)
    $day = (Get-Date).ToUniversalTime().AddHours(9).AddDays(-1).ToString('yyyy-MM-dd')
}
$report = "reports\$day.md"

# 3. 자아성찰 (claude -p headless, 구독 인증=무과금. 실패해도 리포트는 유지)
if ((Test-Path $report) -and (Test-Path $claude)) {
    try {
        $facts = Get-Content -Raw -Encoding utf8 $report
        $ctxFile = "reports\_reflection_context.md"
        $fixedCtx = ""
        if (Test-Path $ctxFile) { $fixedCtx = Get-Content -Raw -Encoding utf8 $ctxFile }
        $prompt = @"
너는 자동매매 봇이고 사장님께 매일 보고서를 쓴다. 아래 오늘 보고서를 읽고, 맨 끝 '오늘의 자아성찰' 자리에 그대로 들어갈 성찰 문단을 써라.

[출력 규칙 엄수]
- 오직 성찰 문단(3~5문장) 하나만 출력.
- 제목/머리말/꼬리말/구분선(---)/따옴표/'성찰입니다' 같은 안내문 금지.
- 파일수정·권한 언급 금지. 너는 글만 쓴다.
- 5단계 보고·메타설명 금지.
- 우리말, 과장·단정 금지(잭팟은 소수표본=계기판).
- 내용: 오늘 배운 점 1~2개 + 앞으로 해볼 구체 제안 1개.
- 마지막 문장은 반드시 '제안:'으로 시작하는 구체적 실행 1개로 끝내라(아래 고정 사실과 충돌 금지).

--- 고정 사실 (제안 전 필독) ---
$fixedCtx

--- 오늘 보고서 ---
$facts
"@
        # 콘솔 인코딩 불안정 회피: 프롬프트를 UTF-8 파일로 쓰고 cmd < > 리다이렉션(바이트 그대로)
        $u8 = New-Object System.Text.UTF8Encoding $false
        $pf = Join-Path (Get-Location).Path "logs\_reflect_prompt.txt"
        $of = Join-Path (Get-Location).Path "logs\_reflect_out.txt"
        [System.IO.File]::WriteAllText($pf, $prompt, $u8)
        if (Test-Path $of) { Remove-Item $of -Force }
        cmd /c "`"$claude`" -p --output-format text < `"$pf`" > `"$of`" 2>> `"$log`""
        $reflection = ""
        if (Test-Path $of) { $reflection = (Get-Content -Raw -Encoding utf8 $of).Trim() }
        Remove-Item $pf, $of -Force -ErrorAction SilentlyContinue
        if ($reflection) {
            $placeholder = '_오늘의 자아성찰은 매일 AI가 직접 작성합니다 (Claude Code CLI 로그인 후 자동 활성)._'
            $content = (Get-Content -Raw -Encoding utf8 $report).Replace($placeholder, $reflection)
            [System.IO.File]::WriteAllText((Resolve-Path $report).Path, $content, (New-Object System.Text.UTF8Encoding($false)))
            "reflection written to $report" | Out-File -Append -Encoding utf8 $log
            # 성찰 제안 → 백로그 승격 (제안 소멸 방지, PLAN §5.12 C)
            $blog = "reports\backlog.md"
            if (-not (Test-Path $blog)) {
                "# 성찰 제안 백로그 (daily_report 자동 누적)" | Out-File -Encoding utf8 $blog
            }
            $m = [regex]::Match($reflection, '제안\s*[::]\s*(.+)')
            if ($m.Success) {
                $prop = ($m.Groups[1].Value.Trim() -replace "\s+", ' ')
                "- [ ] $day — $prop" | Out-File -Append -Encoding utf8 $blog
            } else {
                "- [ ] $day — (제안 표식 없음, 성찰 전문은 reports\$day.md 참조)" | Out-File -Append -Encoding utf8 $blog
            }
        } else {
            "reflection empty - placeholder kept" | Out-File -Append -Encoding utf8 $log
        }
    } catch {
        "reflection step failed: $_" | Out-File -Append -Encoding utf8 $log
    }
}
