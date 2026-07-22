[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$BackupPath,

    [switch]$ConfirmRestore,

    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ComposeDirectory = "C:\eos\docker\compose"
$EnvFile = "../../.env"
$ContainerName = "eos-n8n"
$ContainerTemporaryFile = "/tmp/eos_n8n_restore_$([Guid]::NewGuid().ToString('N')).dump"
$N8nStopped = $false
$ContainerFileCopied = $false

function Invoke-Compose {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$ComposeArguments,

        [Parameter(Mandatory = $true)]
        [string]$Operation
    )

    & docker compose --env-file $EnvFile @ComposeArguments
    $CommandExitCode = $LASTEXITCODE

    if ($CommandExitCode -ne 0) {
        throw "$Operation failed with exit code $CommandExitCode."
    }
}

function Wait-N8nHealthy {
    param([int]$TimeoutSeconds = 180)

    $Deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        $HealthStatus = & docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' $ContainerName 2>$null |
            Select-Object -First 1

        if ($LASTEXITCODE -eq 0 -and $HealthStatus -eq "healthy") {
            return
        }

        Start-Sleep -Seconds 5
    } while ((Get-Date) -lt $Deadline)

    throw "n8n did not become healthy within $TimeoutSeconds seconds."
}

try {
    if (-not (Test-Path -LiteralPath $ComposeDirectory -PathType Container)) {
        throw "Compose directory was not found: $ComposeDirectory"
    }

    Set-Location -LiteralPath $ComposeDirectory

    if (-not (Test-Path -LiteralPath $BackupPath -PathType Leaf)) {
        throw "Backup file was not found."
    }

    $Backup = Get-Item -LiteralPath $BackupPath
    if ($Backup.Length -le 0) {
        throw "Backup file is empty."
    }

    if (-not $DryRun -and -not $ConfirmRestore) {
        Write-Warning "Restore would overwrite the n8n database. No changes were made."
        Write-Warning "Use -ConfirmRestore only after reviewing a successful -DryRun."
        exit 2
    }

    Invoke-Compose -ComposeArguments @("cp", $Backup.FullName, "n8n-postgres:$ContainerTemporaryFile") -Operation "copy backup into n8n PostgreSQL container"
    $ContainerFileCopied = $true
    Invoke-Compose -ComposeArguments @("exec", "-T", "n8n-postgres", "pg_restore", "--list", $ContainerTemporaryFile) -Operation "n8n backup validation" | Out-Null

    if ($DryRun) {
        Write-Host "Validation succeeded. No containers were stopped and no database changes were made."
        Write-Host "Restore plan: stop n8n, restore the validated dump in one transaction with clean/if-exists, start n8n, wait for Docker health=healthy."
    }
    else {
        Write-Warning "Confirmed restore will overwrite the n8n database."

        Invoke-Compose -ComposeArguments @("stop", "n8n") -Operation "stop n8n"
        $N8nStopped = $true

        $RestoreCommand = 'pg_restore --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --clean --if-exists --no-owner --no-privileges --exit-on-error --single-transaction "{0}"' -f $ContainerTemporaryFile
        Invoke-Compose -ComposeArguments @("exec", "-T", "n8n-postgres", "sh", "-c", $RestoreCommand) -Operation "restore n8n PostgreSQL database"

        Invoke-Compose -ComposeArguments @("up", "-d", "n8n") -Operation "start n8n"
        Wait-N8nHealthy

        Write-Host "n8n database restore completed successfully and n8n is healthy."
        Write-Host "Source backup was preserved: $($Backup.FullName)"
    }
}
catch {
    if ($N8nStopped) {
        & docker compose --env-file $EnvFile up -d n8n 2>$null | Out-Null
        Write-Warning "Restore failed after n8n was stopped. A best-effort n8n start was requested. Check container health and logs."
    }

    Write-Error "n8n restore failed: $($_.Exception.Message)"
    exit 1
}
finally {
    if ($ContainerFileCopied -and (Test-Path -LiteralPath $ComposeDirectory -PathType Container)) {
        Set-Location -LiteralPath $ComposeDirectory
        & docker compose --env-file $EnvFile exec -T n8n-postgres rm -f $ContainerTemporaryFile 2>$null | Out-Null
    }
}

exit 0
