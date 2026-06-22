$ErrorActionPreference = "Stop"

docker compose build --pull api
docker run --rm --entrypoint sh enterprise-kb-api:stage8 -c `
  'test "$(id -u)" = 10001 && test ! -w /app/app/main.py && test ! -e /app/.env && test ! -e /app/tests && test ! -e /app/backups && test ! -e /app/.git'

if (Get-Command trivy -ErrorAction SilentlyContinue) {
    trivy image --exit-code 1 --severity CRITICAL,HIGH enterprise-kb-api:stage8
} else {
    docker scout cves --only-severity critical,high --exit-code enterprise-kb-api:stage8
}
