#!/usr/bin/env pwsh
# Windows handoff bootstrap for paris-builder. ASCII-only on purpose: Windows
# PowerShell 5.1 reads non-BOM script files through the ANSI code page, which
# would corrupt Chinese path literals. Chinese paths are discovered at runtime.
#
#   powershell -ExecutionPolicy Bypass -File tools\setup_windows.ps1
#   pwsh -File tools/setup_windows.ps1                      # PowerShell 7+
#   ... -SkipInstall   dependencies already present
#   ... -SkipTests     fast environment probe
#
# The original author worked on macOS (.venv/bin/activate, ~/.nvm node, Apple
# Keychain). This script prepares and verifies the same pipeline on Windows and
# is safe to re-run. It never writes into recorded run evidence.
#
# Python writes progress to stderr, which PowerShell would otherwise turn into a
# terminating error, so subprocesses run with stderr demoted and exit codes
# checked explicitly.
[CmdletBinding()]
param(
    [switch]$SkipInstall,
    [switch]$SkipTests
)

$ErrorActionPreference = 'Stop'
try {
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $OutputEncoding = [System.Text.UTF8Encoding]::new($false)
} catch {
    Write-Verbose 'console encoding could not be switched to UTF-8'
}

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

function Invoke-Python {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & python @Arguments 2>&1 | ForEach-Object { Write-Host $_ }
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
    return $code
}

Write-Host "== paris-builder Windows handoff ==" -ForegroundColor Cyan
Write-Host "project: $root"
Write-Host ("powershell: " + $PSVersionTable.PSVersion)

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw 'python is not on PATH; install Python 3.10+ first'
}
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw 'node is not on PATH; it is required for tools/validate_schematic.cjs'
}
Write-Host ("python : " + (& python --version 2>&1))
Write-Host ("node   : " + (& node --version 2>&1))

if (-not $SkipInstall) {
    Write-Host "`n-- installing Python dependencies --" -ForegroundColor Cyan
    # requirements.lock holds the core three; the retrieval index additionally
    # needs onnxruntime + tokenizers for the local multilingual encoder.
    $code = Invoke-Python -m pip install --quiet --disable-pip-version-check `
        'nbtlib==1.12.1' 'numpy>=1.26,<3' 'Pillow>=9.5' 'onnxruntime>=1.16' 'tokenizers>=0.15'
    if ($code -ne 0) { throw 'pip install failed' }
}

$env:PYTHONPATH = 'src'

Write-Host "`n-- UTF-8 text I/O call sites --" -ForegroundColor Cyan
if ((Invoke-Python tools/check_utf8_encoding.py) -ne 0) { throw 'UTF-8 call sites are incomplete' }

Write-Host "`n-- node and font resolution --" -ForegroundColor Cyan
$probe = "import json; from paris_builder.fonts import font_report, node_binary; " +
         "print('node:', node_binary()); print('font:', json.dumps(font_report(), ensure_ascii=False))"
if ((Invoke-Python -c $probe) -ne 0) { throw 'font/node resolution failed' }

if (-not $SkipTests) {
    Write-Host "`n-- unit and regression tests --" -ForegroundColor Cyan
    if ((Invoke-Python -m unittest discover -s tests) -ne 0) { throw 'test suite failed' }
}

Write-Host "`n-- delivery reproduction audit (no files are modified) --" -ForegroundColor Cyan
# Discover the acceptance zip by pattern instead of a Chinese literal.
$parent = Split-Path -Parent $root
$zip = Get-ChildItem -LiteralPath $parent -Recurse -Depth 1 -Filter 'PAR-002-*-*.zip' -File -ErrorAction SilentlyContinue |
    Select-Object -First 1
$report = Join-Path $root 'runs\PAR-002-v0.4\delivery_verification.json'
if ($zip) {
    Write-Host ("zip    : " + $zip.FullName)
    Invoke-Python tools/verify_delivery.py --out runs/PAR-002-v0.4/delivery_verification.json --zip $zip.FullName | Out-Null
} else {
    Invoke-Python tools/verify_delivery.py --out runs/PAR-002-v0.4/delivery_verification.json | Out-Null
}
# The tool exits non-zero when an optional check was skipped (NOT_RUN); judge the
# recorded statuses instead of the process exit code.
$statuses = (Get-Content $report -Raw -Encoding UTF8 | ConvertFrom-Json).check_status
$statuses.PSObject.Properties | ForEach-Object { Write-Host ("   {0}: {1}" -f $_.Name, $_.Value) }
$failed = @($statuses.PSObject.Properties | Where-Object { $_.Value -ne 'PASS' -and $_.Value -ne 'NOT_RUN' })
if ($failed.Count -gt 0) { throw ('delivery audit failed: ' + ($failed.Name -join ', ')) }

Write-Host "`nWindows handoff checks complete." -ForegroundColor Green
Write-Host "Remaining user-only step: paste PAR-002.schem and STATE-LAB.schem in Minecraft 1.21.11"
Write-Host "and record the update A/B plus visual acceptance (delivery game-acceptance guide)."
