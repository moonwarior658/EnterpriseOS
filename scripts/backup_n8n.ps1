[CmdletBinding()]
param(
    [ValidateRange(1, 3650)]
    [int]$RetentionDays = 14
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ComposeDirectory = "C:\eos\docker\compose"
$EnvFile = "../../.env"
$BackupRoot = "C:\eos\backups\n8n"
$Timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
$BackupName = "n8n_$Timestamp.dump"
$FinalBackupPath = Join-Path $BackupRoot $BackupName
$TemporaryBackupPath = "$FinalBackupPath.tmp"
$ContainerTemporaryFile = "/tmp/$BackupName.tmp"

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

try {
    if (-not (Test-Path -LiteralPath $ComposeDirectory -PathType Container)) {
        throw "Compose directory was not found: $ComposeDirectory"
    }

    Set-Location -LiteralPath $ComposeDirectory
    New-Item -ItemType Directory -Path $BackupRoot -Force | Out-Null

    $DumpCommand = 'pg_dump --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --format=custom --file="{0}"' -f $ContainerTemporaryFile
    Invoke-Compose -ComposeArguments @("exec", "-T", "n8n-postgres", "sh", "-c", $DumpCommand) -Operation "n8n PostgreSQL dump"

    Invoke-Compose -ComposeArguments @("exec", "-T", "n8n-postgres", "pg_restore", "--list", $ContainerTemporaryFile) -Operation "n8n backup validation" | Out-Null

    Invoke-Compose -ComposeArguments @("cp", "n8n-postgres:$ContainerTemporaryFile", $TemporaryBackupPath) -Operation "n8n backup copy"

    $TemporaryBackup = Get-Item -LiteralPath $TemporaryBackupPath
    if ($TemporaryBackup.Length -le 0) {
        throw "The copied n8n backup is empty."
    }

    Move-Item -LiteralPath $TemporaryBackupPath -Destination $FinalBackupPath

    $CreatedBackup = Get-Item -LiteralPath $FinalBackupPath
    if ($CreatedBackup.Length -le 0) {
        throw "The final n8n backup is empty."
    }

    $RetentionCutoff = (Get-Date).AddDays(-$RetentionDays)
    Get-ChildItem -LiteralPath $BackupRoot -Filter "n8n_*.dump" -File |
        Where-Object {
            $_.FullName -ne $CreatedBackup.FullName -and
            $_.LastWriteTime -lt $RetentionCutoff
        } |
        Remove-Item -Force

    Write-Host "n8n backup created and validated successfully."
    Write-Host "File: $FinalBackupPath"
    Write-Host "Size: $($CreatedBackup.Length) bytes"
    Write-Host "Retention: $RetentionDays days"
}
catch {
    if (Test-Path -LiteralPath $TemporaryBackupPath) {
        Remove-Item -LiteralPath $TemporaryBackupPath -Force -ErrorAction SilentlyContinue
    }

    Write-Error "n8n backup failed: $($_.Exception.Message)"
    exit 1
}
finally {
    if (Test-Path -LiteralPath $ComposeDirectory -PathType Container) {
        Set-Location -LiteralPath $ComposeDirectory
        & docker compose --env-file $EnvFile exec -T n8n-postgres rm -f $ContainerTemporaryFile 2>$null | Out-Null
    }
}

exit 0
