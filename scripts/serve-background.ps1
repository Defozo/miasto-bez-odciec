param([int]$Port = 8000, [switch]$Stop)
$ErrorActionPreference = 'Stop'
$projectDir = (Resolve-Path (Split-Path $PSScriptRoot -Parent)).Path
Set-Location $projectDir
$runtimeDir = Join-Path $projectDir '.runtime'
$stateFile = Join-Path $runtimeDir 'processes.json'
$entryFile = Join-Path $PSScriptRoot 'local-process.py'
if ($Stop) {
    # Windows virtualenv launchers can spawn another python process. Stop only
    # processes carrying this project's absolute entrypoint, including children.
    $owned = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -and $_.CommandLine.Contains($entryFile) }
    foreach ($process in $owned) { Stop-Process -Id $process.ProcessId -ErrorAction SilentlyContinue }
    Write-Output 'Project processes stopped.'
    exit 0
}
if (Test-Path -LiteralPath $stateFile) {
    $previous = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
    foreach ($record in $previous.processes) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($record.pid)" -ErrorAction SilentlyContinue
        if ($process -and $process.CommandLine.Contains($entryFile)) {
            throw "The project process $($record.role) is already running (PID $($record.pid)). Use -Stop before restart."
        }
    }
}
if (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue) { throw "Port $Port is occupied. Existing services were not changed." }
New-Item -ItemType Directory -Force $runtimeDir | Out-Null
$env:SMART_CITY_LOCAL_DEMO_AUTH = 'true'
$env:SMART_CITY_PUBLIC_MODE = 'false'
$env:SMART_CITY_ORIGIN = "http://127.0.0.1:$Port"
$env:SMART_CITY_WEB_DIST = Join-Path $projectDir 'apps/web/dist'
$workerOwner = 'worker-' + [guid]::NewGuid().ToString('N')
$env:SMART_CITY_WORKER_OWNER = $workerOwner
& .venv/Scripts/python.exe -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw 'Database migrations failed' }
& .venv/Scripts/python.exe -m services.api.init_db --seed
if ($LASTEXITCODE -ne 0) { throw 'Database initialization failed' }
$records = @()
foreach ($role in @('api', 'worker')) {
    $process = Start-Process -FilePath (Join-Path $projectDir '.venv/Scripts/python.exe') -ArgumentList @('"' + $entryFile + '"', $role, "$Port") -WorkingDirectory $projectDir -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimeDir "$role.out.log") -RedirectStandardError (Join-Path $runtimeDir "$role.err.log")
    $records += @{role=$role;pid=$process.Id}
}
@{project=$projectDir;port=$Port;processes=$records} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $stateFile
$deadline = (Get-Date).AddSeconds(600)
$ready = $false
while ((Get-Date) -lt $deadline) {
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health/ready" -TimeoutSec 3
        if ($health.status -eq 'ready' -and $health.worker.status -eq 'active' -and $health.worker.owner -eq $workerOwner) { $ready = $true; break }
    } catch { }
    Start-Sleep -Seconds 1
}
if (!$ready) { throw 'API or worker readiness failed. Inspect project .runtime logs.' }
Write-Output "Miasto bez odcięć: http://127.0.0.1:$Port"
