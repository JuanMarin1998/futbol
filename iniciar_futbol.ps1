# Inicia Django y el proveedor Flashscore con un solo comando.
$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
$scraperDir = Join-Path $projectRoot "flashscore-scraper"
$scraperFile = Join-Path $scraperDir "run.py"
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue

if (-not $pythonCommand) {
    throw "No se encontró Python. Activa primero el entorno virtual del proyecto."
}
if (-not (Test-Path $scraperFile)) {
    throw "No se encontró el proveedor en '$scraperFile'. Verifica que flashscore-scraper esté dentro de la carpeta del proyecto."
}

function Test-LocalPort([int]$Port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne(700)) { return $false }
        $client.EndConnect($async)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

$scraperProcess = $null
$startedHere = $false

try {
    if (Test-LocalPort 8090) {
        Write-Host "Flashscore ya está escuchando en el puerto 8090; no se iniciará otra instancia." -ForegroundColor Green
    } else {
        Write-Host "Iniciando el proveedor Flashscore en el puerto 8090..." -ForegroundColor Cyan
        $previousPort = $env:PORT
        $env:PORT = "8090"
        try {
            $scraperProcess = Start-Process -FilePath $pythonCommand.Source -ArgumentList "run.py" -WorkingDirectory $scraperDir -PassThru -WindowStyle Normal
            $startedHere = $true
        } finally {
            $env:PORT = $previousPort
        }

        $ready = $false
        for ($i = 0; $i -lt 30; $i++) {
            Start-Sleep -Seconds 1
            if (Test-LocalPort 8090) { $ready = $true; break }
            if ($scraperProcess.HasExited) {
                throw "El proveedor Flashscore se cerró al iniciar. Revisa la ventana del proveedor para ver el error."
            }
        }
        if (-not $ready) {
            throw "El proveedor no respondió en el puerto 8090 en 30 segundos. Revisa la ventana del proveedor."
        }
        Write-Host "Proveedor Flashscore listo en http://127.0.0.1:8090" -ForegroundColor Green
    }

    Write-Host "Iniciando Django en http://127.0.0.1:8000 ..." -ForegroundColor Green
    Set-Location $projectRoot
    & $pythonCommand.Source "manage.py" "runserver" "127.0.0.1:8000"
} finally {
    if ($startedHere -and $scraperProcess -and -not $scraperProcess.HasExited) {
        Write-Host "Cerrando el proveedor Flashscore iniciado por este script..." -ForegroundColor Yellow
        Stop-Process -Id $scraperProcess.Id -Force -ErrorAction SilentlyContinue
    }
}
