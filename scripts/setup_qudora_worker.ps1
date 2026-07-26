param([string]$WorkerPath = ".qudora-worker")

$workerRoot = Join-Path (Get-Location) $WorkerPath
python -m venv $workerRoot
& (Join-Path $workerRoot "Scripts\python.exe") -m pip install --upgrade pip
& (Join-Path $workerRoot "Scripts\python.exe") -m pip install -r requirements-qudora-worker.txt
Write-Host "Set QUDORA_WORKER_PYTHON=$workerRoot\Scripts\python.exe in .env, then restart the API."
