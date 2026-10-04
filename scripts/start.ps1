param([switch]$Docker, [switch]$WithAI, [switch]$Install)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (!(Test-Path .venv/Scripts/python.exe)) { python -m venv .venv }
if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { throw 'Creating virtualenv failed' }
if ($Install) {
    & .venv/Scripts/python.exe -m pip install --require-hashes -r requirements.lock
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency install failed' }
    Push-Location apps/web
    try { npm ci; if ($LASTEXITCODE -ne 0) { throw 'Web dependency install failed' }; npm run build; if ($LASTEXITCODE -ne 0) { throw 'Web build failed' } } finally { Pop-Location }
}
& .venv/Scripts/python.exe scripts/bootstrap-secrets.py
if ($LASTEXITCODE -ne 0) { throw 'Secret bootstrap failed' }
$secretNames = @('SMART_CITY_DB_PASSWORD','SMART_CITY_OPERATOR_PASSWORD','SMART_CITY_VERIFIER_PASSWORD','SMART_CITY_ADMIN_PASSWORD')
if ($WithAI) { $secretNames += @('GROQ_API_KEY','FIRECRAWL_API_KEY'); $env:SMART_CITY_ENABLE_GROQ = 'true'; $env:SMART_CITY_ENABLE_FIRECRAWL = 'true' }
if ($Docker) {
    psst --global @secretNames -- docker compose up --build -d --wait
    if ($LASTEXITCODE -ne 0) { throw 'Compose startup failed' }
    $workerContainers = @(docker ps --filter label=com.docker.compose.project=smart-city --filter label=com.docker.compose.service=worker --format '{{.ID}}')
    if ($LASTEXITCODE -ne 0 -or $workerContainers.Count -ne 1) { throw 'Expected exactly one running project worker container' }
    $workerStartedAt = docker inspect --format '{{.State.StartedAt}}' $workerContainers[0]
    if ($LASTEXITCODE -ne 0) { throw 'Worker startup lookup failed' }
    & .venv/Scripts/python.exe scripts/wait-worker.py --base http://localhost:8087 --started-after $workerStartedAt
    if ($LASTEXITCODE -ne 0) { throw 'Worker initialization failed' }
    psst --global @secretNames -- docker compose exec -T api python scripts/smoke.py --base http://localhost:8000 --output /data/startup-acceptance.json
    if ($LASTEXITCODE -ne 0) { throw 'Full fixture acceptance failed. Inspect the retained project containers.' }
    Write-Output 'Miasto bez odcięć: http://localhost:8087'
} else {
    psst --global @secretNames -- .venv/Scripts/python.exe scripts/run-local.py
    if ($LASTEXITCODE -ne 0) { throw 'Local startup failed' }
}
