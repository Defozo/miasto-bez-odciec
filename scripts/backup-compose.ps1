param([string]$Destination = 'artifacts/private/backups')
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$backupDir = Join-Path (Join-Path (Get-Location) $Destination) (Get-Date -Format 'yyyyMMddTHHmmss')
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
# pg_dump's custom archive stays binary through Docker copy, never a shell pipe.
docker compose exec -T db pg_dump -U smartcity -Fc -f /tmp/smart-city-backup.dump smartcity
if ($LASTEXITCODE -ne 0) { throw 'Database backup failed' }
docker compose cp db:/tmp/smart-city-backup.dump (Join-Path $backupDir 'database.dump')
if ($LASTEXITCODE -ne 0) { throw 'Copy database backup failed' }
docker compose exec -T api python -c 'import shutil; shutil.make_archive("/tmp/smart-city-evidence", "gztar", "/data")'
if ($LASTEXITCODE -ne 0) { throw 'Evidence backup failed' }
docker compose cp api:/tmp/smart-city-evidence.tar.gz (Join-Path $backupDir 'evidence.tar.gz')
if ($LASTEXITCODE -ne 0) { throw 'Copy evidence backup failed' }
Write-Output "Backup zapisany: $backupDir"
