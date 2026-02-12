param(
  [string]$ProjectRoot = "d:\WorkingSpace\backend",
  [string]$ComposeProjectName = "websocket",
  [switch]$Force
)

$ErrorActionPreference = "Stop"

function Write-Step {
  param([string]$Message)
  Write-Host "==> $Message"
}

$dockerDataRoot = Join-Path $ProjectRoot "docker-data"
$qdrantTarget = Join-Path $dockerDataRoot "qdrant"
$inngestTarget = Join-Path $dockerDataRoot "inngest"
$mem0Target = Join-Path $dockerDataRoot "mem0"
$langfusePostgresTarget = Join-Path $dockerDataRoot "langfuse\postgres"
$langfuseClickhouseDataTarget = Join-Path $dockerDataRoot "langfuse\clickhouse\data"
$langfuseClickhouseLogsTarget = Join-Path $dockerDataRoot "langfuse\clickhouse\logs"
$langfuseMinioTarget = Join-Path $dockerDataRoot "langfuse\minio"

New-Item -ItemType Directory -Force -Path $dockerDataRoot | Out-Null
New-Item -ItemType Directory -Force -Path $qdrantTarget | Out-Null
New-Item -ItemType Directory -Force -Path $inngestTarget | Out-Null
New-Item -ItemType Directory -Force -Path $mem0Target | Out-Null
New-Item -ItemType Directory -Force -Path $langfusePostgresTarget | Out-Null
New-Item -ItemType Directory -Force -Path $langfuseClickhouseDataTarget | Out-Null
New-Item -ItemType Directory -Force -Path $langfuseClickhouseLogsTarget | Out-Null
New-Item -ItemType Directory -Force -Path $langfuseMinioTarget | Out-Null

$qdrantVolume = "${ComposeProjectName}_qdrant_data"

Write-Step "Checking Qdrant volume: $qdrantVolume"
$vol = docker volume ls --format "{{.Name}}" | Select-String -Pattern "^$qdrantVolume$"
if (-not $vol) {
  Write-Host "Qdrant volume '$qdrantVolume' not found. Skipping Qdrant copy."
} else {
  $targetHasData = (Get-ChildItem -Force -ErrorAction SilentlyContinue $qdrantTarget | Measure-Object).Count -gt 0
  if ($targetHasData -and -not $Force) {
    Write-Host "Target '$qdrantTarget' already has data. Use -Force to overwrite copy step."
  } else {
    Write-Step "Copying Qdrant data from volume to host bind-mount..."
    docker run --rm `
      -v "${qdrantVolume}:/from" `
      -v "${qdrantTarget}:/to" `
      alpine sh -c "cp -a /from/. /to/"
    Write-Host "Qdrant data copy done."
  }
}

$oldDedupPath = Join-Path $ProjectRoot "inngest-py\.ingest_dedup.sqlite3"
$newDedupPath = Join-Path $inngestTarget ".ingest_dedup.sqlite3"
if (Test-Path $oldDedupPath) {
  if ((Test-Path $newDedupPath) -and -not $Force) {
    Write-Host "Dedup DB already exists at '$newDedupPath'. Use -Force to overwrite."
  } else {
    Write-Step "Copying Inngest dedup DB to bind-mount path..."
    Copy-Item -Force $oldDedupPath $newDedupPath
    Write-Host "Inngest dedup DB copy done."
  }
} else {
  Write-Host "Old dedup DB not found at '$oldDedupPath'. Skipping."
}

Write-Step "Runtime data migration complete."
Write-Host "Qdrant bind path: $qdrantTarget"
Write-Host "Inngest bind path: $inngestTarget"
Write-Host "Mem0 bind path: $mem0Target"
Write-Host "Langfuse bind root: $(Join-Path $dockerDataRoot 'langfuse')"
