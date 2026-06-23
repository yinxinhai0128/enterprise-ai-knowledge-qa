$ErrorActionPreference = "Stop"

function Assert-NativeSuccess([string]$Step) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE"
    }
}

docker compose build --pull api
Assert-NativeSuccess "docker compose build"

$uid = docker run --rm --entrypoint id enterprise-kb-api:rc -u
Assert-NativeSuccess "container UID verification"
if ($uid.Trim() -ne "10001") { throw "unexpected container UID: $uid" }

$gid = docker run --rm --entrypoint id enterprise-kb-api:rc -g
Assert-NativeSuccess "container GID verification"
if ($gid.Trim() -ne "10001") { throw "unexpected container GID: $gid" }

$checks = @(
    @{ Arguments = @("!", "-w", "/app/app/main.py"); Name = "source is not writable" },
    @{ Arguments = @("!", "-w", "/app/config"); Name = "config is not writable" },
    @{ Arguments = @("-w", "/app/storage"); Name = "storage is writable" },
    @{ Arguments = @("-w", "/app/chroma_db"); Name = "chroma data is writable" },
    @{ Arguments = @("-w", "/app/logs"); Name = "logs are writable" },
    @{ Arguments = @("!", "-e", "/app/.env"); Name = ".env is absent" },
    @{ Arguments = @("!", "-e", "/app/tests"); Name = "tests are absent" },
    @{ Arguments = @("!", "-e", "/app/backups"); Name = "backups are absent" },
    @{ Arguments = @("!", "-e", "/app/.git"); Name = "Git metadata is absent" }
)
foreach ($check in $checks) {
    docker run --rm --entrypoint test enterprise-kb-api:rc @($check.Arguments)
    Assert-NativeSuccess $check.Name
}

$python = if (Test-Path ".venv/Scripts/python.exe") {
    ".venv/Scripts/python.exe"
} else {
    "python"
}
& $python scripts/container_audit.py --image "local://enterprise-kb-api:rc"
Assert-NativeSuccess "container vulnerability policy audit"
