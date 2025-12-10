# Запуск приложения с правами администратора (необходимо для глобальных хоткеев)
$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptPath

# Активируем venv и добавляем CUDA пути
$venvActivate = Join-Path $scriptPath ".venv\Scripts\Activate.ps1"
$cudnnPath = Join-Path $scriptPath ".venv\Lib\site-packages\nvidia\cudnn\bin"
$cublasPath = Join-Path $scriptPath ".venv\Lib\site-packages\nvidia\cublas\bin"

# Добавляем CUDA пути в PATH
$env:PATH = "$cudnnPath;$cublasPath;$env:PATH"

# Активируем виртуальное окружение
& $venvActivate

# Запускаем приложение
python main.py









