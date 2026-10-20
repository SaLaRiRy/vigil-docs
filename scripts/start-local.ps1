param(
    [switch]$SkipFrontend
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$runtime = Join-Path $repo '.runtime'
New-Item -ItemType Directory -Force -Path $runtime | Out-Null

function Test-Port([int]$Port) {
    return $null -ne (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
}

function Wait-Ready([string]$Name, [scriptblock]$Check, [int]$TimeoutSeconds = 120) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (& $Check) {
            Write-Host "$Name is ready"
            return
        }
        Start-Sleep -Seconds 2
    }
    throw "$Name did not become ready within $TimeoutSeconds seconds"
}

if (-not (Get-Command rabbitmqctl -ErrorAction SilentlyContinue)) {
    throw 'rabbitmqctl is required but was not found on PATH'
}
try {
    rabbitmqctl status | Out-Null
} catch {
    throw 'RabbitMQ is not running. Start the local RabbitMQ Windows service and rerun this script.'
}
if (-not (Test-Port 3306)) { throw 'MySQL is not listening on port 3306' }
if (-not (Test-Port 6379)) { throw 'Redis is not listening on port 6379' }

if (-not $env:JWT_SECRET) {
    $env:JWT_SECRET = ([Guid]::NewGuid().ToString('N') + [Guid]::NewGuid().ToString('N'))
}

$python = Join-Path $repo 'python-service\.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw 'python-service\.venv is missing' }

$javaHome = 'C:\Program Files\JetBrains\IntelliJ IDEA 2023.1\jbr'
$maven = 'C:\Program Files\JetBrains\IntelliJ IDEA 2023.1\plugins\maven\lib\maven3\bin\mvn.cmd'
if (-not (Test-Path $javaHome)) { throw "JDK 17 not found: $javaHome" }
if (-not (Test-Path $maven)) { throw "Maven not found: $maven" }

$env:JAVA_HOME = $javaHome
$env:MAVEN_OPTS = '-Duser.home=C:/Users/87590 -Dmaven.repo.local=C:/Users/87590/.m2/repository'
$env:SERVER_PORT = '8080'
$env:AI_SERVICE_URL = 'http://127.0.0.1:8000/api'

if (-not (Test-Port 8000)) {
    Start-Process -FilePath $python `
        -ArgumentList @('-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', '8000') `
        -WorkingDirectory (Join-Path $repo 'python-service') `
        -RedirectStandardOutput (Join-Path $runtime 'python-api.out.log') `
        -RedirectStandardError (Join-Path $runtime 'python-api.err.log') `
        -WindowStyle Hidden | Out-Null
}
Wait-Ready 'Python API' { try { (Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8000/health' -TimeoutSec 5).StatusCode -eq 200 } catch { $false } }

$consumerRunning = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like '*consumer.py*' -and $_.CommandLine -like '*python-service*'
}
if (-not $consumerRunning) {
    Start-Process -FilePath $python `
        -ArgumentList @('consumer.py') `
        -WorkingDirectory (Join-Path $repo 'python-service') `
        -RedirectStandardOutput (Join-Path $runtime 'python-consumer.out.log') `
        -RedirectStandardError (Join-Path $runtime 'python-consumer.err.log') `
        -WindowStyle Hidden | Out-Null
}
Wait-Ready 'Python document consumer' {
    try {
        $queueStatus = rabbitmqctl list_queues name consumers | Out-String
        return $queueStatus -match 'agentcraft\.document\.process\.v1\s+1'
    } catch {
        return $false
    }
}

if (-not (Test-Port 8080)) {
    Start-Process -FilePath $maven `
        -ArgumentList @('spring-boot:run', '-q') `
        -WorkingDirectory $repo `
        -RedirectStandardOutput (Join-Path $runtime 'java.out.log') `
        -RedirectStandardError (Join-Path $runtime 'java.err.log') `
        -WindowStyle Hidden | Out-Null
}
Wait-Ready 'Java backend' { try { (Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8080/api/auth/login' -Method Options -TimeoutSec 5).StatusCode -lt 500 } catch { $false } } 180

if (-not $SkipFrontend) {
    if (-not (Test-Port 3000)) {
        Start-Process -FilePath 'npm.cmd' `
            -ArgumentList @('run', 'dev', '--', '--host', '127.0.0.1', '--port', '3000') `
            -WorkingDirectory (Join-Path $repo 'frontend') `
            -RedirectStandardOutput (Join-Path $runtime 'frontend.out.log') `
            -RedirectStandardError (Join-Path $runtime 'frontend.err.log') `
            -WindowStyle Hidden | Out-Null
    }
    Wait-Ready 'Frontend' { try { (Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:3000' -TimeoutSec 5).StatusCode -eq 200 } catch { $false } }
}

Write-Host 'Local AgentCraft stack is ready. Logs are in .runtime.'
