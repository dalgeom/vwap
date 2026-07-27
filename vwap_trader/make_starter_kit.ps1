# 친구용 스타터 킷 생성: 소스 + exe + 빈 데이터 + 문서 → zip
# 사용: .\make_starter_kit.ps1   → dist\momentum_bot_v10_starter.zip
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path "dist\MomentumBot\momentum_app.exe")) { throw "먼저 .\build_exe.ps1 로 빌드하세요" }

$kit = "dist\starter_kit"
if (Test-Path $kit) { Remove-Item -Recurse -Force $kit }
New-Item -ItemType Directory -Force "$kit\vwap_trader" | Out-Null

# 1) 소스 복사 (개인 데이터·환경·산출물 제외)
robocopy . "$kit\vwap_trader" /E /NFL /NDL /NJH /NJS `
    /XD venv venv_app dist build logs data reports __pycache__ .pytest_cache .git `
    /XF .env bot_out.log bot_err.log prom.txt
if ($LASTEXITCODE -ge 8) { throw "robocopy 실패: $LASTEXITCODE" }
$global:LASTEXITCODE = 0  # robocopy는 0-7이 성공(파일 복사됨 등)인데 그대로 두면 스크립트 종료코드로 새어나감

# 2) 빈 데이터·리포트·로그 폴더 (친구는 자기 계좌로 새 출발 — 데이터 섞임 원천 차단)
foreach ($d in "data", "reports", "logs") {
    New-Item -ItemType Directory -Force "$kit\vwap_trader\$d" | Out-Null
}

# 3) .env 템플릿 (키는 앱 설정 화면에서 입력)
@"
BYBIT_API_KEY=
BYBIT_API_SECRET=
"@ | Out-File -Encoding utf8 "$kit\vwap_trader\config\.env"

# 4) exe + 문서
Copy-Item -Recurse "dist\MomentumBot" "$kit\MomentumBot"
Copy-Item "docs\app\시작하기.md" "$kit\시작하기.md"
Copy-Item "docs\app\개발자메모.md" "$kit\개발자메모.md"

# 5) 검증: 개인 데이터가 없는지 (거래기록·리포트·키)
if (Test-Path "$kit\vwap_trader\data\trades_momentum.jsonl") { throw "검증 실패: 거래기록 포함됨" }
$personalPatterns = @("trades_momentum*.jsonl", "equity_history.jsonl", "app_settings.json", "*.bak_*")
foreach ($pat in $personalPatterns) {
    $found = Get-ChildItem -Path "$kit" -Recurse -Filter $pat -ErrorAction SilentlyContinue
    if ($found) { throw "검증 실패: 개인 데이터 파일 포함됨 ($pat): $($found[0].FullName)" }
}
$reportMd = Get-ChildItem -Path "$kit\vwap_trader\reports" -Filter "*.md" -ErrorAction SilentlyContinue
if ($reportMd) { throw "검증 실패: 리포트 md 포함됨: $($reportMd[0].FullName)" }
$envText = Get-Content "$kit\vwap_trader\config\.env" -Raw
if ($envText -match "=\S") { throw "검증 실패: .env에 값이 있음" }

# 6) zip
$zip = "dist\momentum_bot_v10_starter.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path "$kit\*" -DestinationPath $zip
Write-Host "완료: $zip"
