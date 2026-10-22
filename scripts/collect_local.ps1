<#
    One local collector run (the "bridge" collector, ADR-002). Started every 30 minutes by the
    Windows scheduled task that scripts/register_local_collector.ps1 creates.

    Polls for 29 minutes, writes Parquet into data/runs/<run_id>, copies it into data/lake,
    and uploads to the Hugging Face dataset when HF_TOKEN and HF_DATASET_REPO are set in .env.
    Output is appended to data/logs/collector_<yyyy-MM-dd>.log (the API key is redacted).

    Manual one-off test (3 minutes, no upload):
        .\scripts\collect_local.ps1 -MaxRuntimeMin 3 -NoUpload
#>
param(
    [double]$MaxRuntimeMin = 29,
    [switch]$NoUpload
)

$ErrorActionPreference = 'Stop'
$Repo = Split-Path -Parent $PSScriptRoot
Set-Location $Repo

$Py = Join-Path $Repo '.venv\Scripts\python.exe'
if (-not (Test-Path $Py)) { throw "No virtual environment at $Py - run 'uv sync' first." }

$LogDir = Join-Path $Repo 'data\logs'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Log = Join-Path $LogDir ("collector_{0:yyyy-MM-dd}.log" -f (Get-Date))

$CollectorArgs = @('-m', 'movemelbourne.collect.run_collection', '--max-runtime-min', "$MaxRuntimeMin",
                   '--align-to-slot-min', '30')
if ($NoUpload) { $CollectorArgs += '--no-upload' }

# Python logs to stdout; native stderr would become terminating errors under 'Stop' in
# Windows PowerShell 5.1, so relax it for the call and rely on the exit code.
$ErrorActionPreference = 'Continue'
& $Py @CollectorArgs *>&1 | ForEach-Object { "$_" } | Add-Content -Path $Log -Encoding utf8
$Code = $LASTEXITCODE
Add-Content -Path $Log -Encoding utf8 -Value ("{0:s} collector exited with code {1}" -f (Get-Date), $Code)
exit $Code
