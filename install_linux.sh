#!/bin/bash

# Скрипт установки MindType для Linux
# Рекомендуется использовать Ubuntu 22.04+ или Debian 12+

set -e

echo "=== MindType: Установка для Linux ==="

# 1. Проверка зависимостей системы
echo "Проверка системных зависимостей..."
sudo apt-get update
sudo apt-get install -y \
    python3-venv \
    python3-pip \
    libxcb-cursor0 \
    libxcb-xinerama0 \
    libxcb-icccm4 \
    libxcb-render-util0 \
    libxcb-shape0 \
    libxcb-xkb1 \
    libxkbcommon-x11-0 \
    libpulse0 \
    libasound2 \
    libportaudio2 \
    make \
    g++ \
    git \
    wget

# 2. Создание виртуального окружения
if [ ! -d "venv" ]; then
    echo "Создание venv..."
    python3 -m venv venv
fi

source venv/bin/activate

# 3. Установка Python зависимостей
echo "Установка Python пакетов..."
pip install --upgrade pip
pip install -r requirements.txt

# 4. Сборка whisper.cpp бинарника
echo "Настройка движка транскрипции (whisper.cpp)..."
BIN_DIR="bin/linux-x64"
mkdir -p "$BIN_DIR"

if [ ! -f "$BIN_DIR/whisper-cli" ]; then
    echo "Сборка whisper-cli из исходников..."
    TEMP_DIR=$(mktemp -d)
    git clone --depth 1 https://github.com/ggerganov/whisper.cpp "$TEMP_DIR"
    cd "$TEMP_DIR"

    # Проверка наличия Vulkan для ускорения
    if command -v vulkaninfo >/dev/null 2>&1 || [ -f "/usr/lib/x86_64-linux-gnu/libvulkan.so.1" ]; then
        echo "Обнаружен Vulkan! Сборка с поддержкой GPU..."
        GGML_VULKAN=1 make -j whisper-cli
    else
        echo "GPU не обнаружен, сборка для CPU..."
        make -j whisper-cli
    fi

    cp whisper-cli "../../$BIN_DIR/"
    cd -
    rm -rf "$TEMP_DIR"
    echo "Бинарник whisper-cli успешно установлен в $BIN_DIR"
else
    echo "Бинарник whisper-cli уже существует."
fi

chmod +x "$BIN_DIR/whisper-cli"

echo "=== Установка завершена! ==="
echo "Запустите приложение командой: source venv/bin/activate && python main.py"

