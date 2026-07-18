$ErrorActionPreference = "Stop"

$ContainerName = "eos-postgres"
$ContainerTempFile = "/tmp/eos_postgres_backup.dump"
$BackupRoot = "D:\EnterpriseOS\backups\postgresql"
$RetentionDays = 30
$Timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
$BackupFile = Join-Path $BackupRoot "eos_postgres_$Timestamp.dump"

function Confirm-DockerCommand {
    param([string]$Operation)

    if ($LASTEXITCODE -ne 0) {
        throw "$Operation failed with exit code $LASTEXITCODE"
    }
}

try {
    New-Item -ItemType Directory -Force $BackupRoot | Out-Null

    docker exec $ContainerName sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --file=/tmp/eos_postgres_backup.dump'
    Confirm-DockerCommand "PostgreSQL dump"

    docker exec $ContainerName pg_restore --list $ContainerTempFile | Out-Null
    Confirm-DockerCommand "Backup validation"

    docker cp "${ContainerName}:${ContainerTempFile}" $BackupFile
    Confirm-DockerCommand "Backup copy"

    $CreatedBackup = Get-Item $BackupFile

    if ($CreatedBackup.Length -le 0) {
        throw "Created backup is empty"
    }

    Get-ChildItem $BackupRoot -Filter "eos_postgres_*.dump" -File |
        Where-Object {
            $_.LastWriteTime -lt (Get-Date).AddDays(-$RetentionDays)
        } |
        Remove-Item -Force

    Write-Host "Backup created successfully"
    Write-Host "File: $BackupFile"
    Write-Host "Size: $($CreatedBackup.Length) bytes"
}
finally {
    docker exec $ContainerName rm -f $ContainerTempFile 2>$null |
        Out-Null
}
