#!/bin/bash
# Создание DMG образа для macOS
# Запуск: ./build/installer/create_dmg.sh [версия]

set -e

VERSION="${1:-1.0.0}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
DIST_DIR="$ROOT_DIR/dist"
APP_NAME="OfflineWhisper"

echo "=== Создание DMG для macOS ==="
echo "Версия: $VERSION"
echo ""

# Находим .app
APP_PATH="$DIST_DIR/$APP_NAME.app"
if [ ! -d "$APP_PATH" ]; then
    APP_PATH="$DIST_DIR/$APP_NAME/$APP_NAME.app"
fi

if [ ! -d "$APP_PATH" ]; then
    echo "Ошибка: $APP_NAME.app не найден!"
    echo "Сначала выполните сборку: ./build/build_macos.sh"
    exit 1
fi

echo "Найдено приложение: $APP_PATH"

# Создаём временную папку для DMG
DMG_DIR="$DIST_DIR/dmg_staging"
DMG_FILE="$DIST_DIR/${APP_NAME}-${VERSION}.dmg"
VOLUME_NAME="Offline Whisper"

rm -rf "$DMG_DIR"
mkdir -p "$DMG_DIR"

# Копируем приложение
echo "Копирование приложения..."
cp -R "$APP_PATH" "$DMG_DIR/"

# Создаём симлинк на Applications
ln -s /Applications "$DMG_DIR/Applications"

# Создаём фоновое изображение (опционально)
BACKGROUND_DIR="$DMG_DIR/.background"
mkdir -p "$BACKGROUND_DIR"

# Если есть фон, копируем
BACKGROUND_SRC="$ROOT_DIR/assets/dmg_background.png"
if [ -f "$BACKGROUND_SRC" ]; then
    cp "$BACKGROUND_SRC" "$BACKGROUND_DIR/background.png"
fi

# Удаляем старый DMG если есть
rm -f "$DMG_FILE"

# Создаём DMG
echo "Создание DMG..."

if command -v create-dmg &> /dev/null; then
    # Используем create-dmg для красивого DMG
    # Установка: brew install create-dmg

    CREATE_DMG_ARGS=(
        --volname "$VOLUME_NAME"
        --window-pos 200 120
        --window-size 660 400
        --icon-size 100
        --icon "$APP_NAME.app" 180 185
        --hide-extension "$APP_NAME.app"
        --app-drop-link 480 185
        --no-internet-enable
    )

    # Добавляем фон если есть
    if [ -f "$BACKGROUND_SRC" ]; then
        CREATE_DMG_ARGS+=(--background "$BACKGROUND_SRC")
    fi

    create-dmg "${CREATE_DMG_ARGS[@]}" "$DMG_FILE" "$DMG_DIR"

else
    # Fallback на hdiutil
    echo "create-dmg не найден, используем hdiutil..."
    echo "Для красивого DMG установите: brew install create-dmg"

    # Создаём временный DMG
    TEMP_DMG="$DIST_DIR/temp.dmg"

    hdiutil create -volname "$VOLUME_NAME" \
        -srcfolder "$DMG_DIR" \
        -ov -format UDRW \
        "$TEMP_DMG"

    # Конвертируем в сжатый формат
    hdiutil convert "$TEMP_DMG" \
        -format UDZO \
        -imagekey zlib-level=9 \
        -o "$DMG_FILE"

    rm -f "$TEMP_DMG"
fi

# Очистка
rm -rf "$DMG_DIR"

# Проверяем результат
if [ -f "$DMG_FILE" ]; then
    echo ""
    echo "DMG создан успешно!"
    echo "Файл: $DMG_FILE"
    SIZE=$(du -h "$DMG_FILE" | cut -f1)
    echo "Размер: $SIZE"

    # Верификация
    echo ""
    echo "Верификация DMG..."
    hdiutil verify "$DMG_FILE"

    echo ""
    echo "=== Готово ==="
else
    echo "Ошибка: DMG не создан!"
    exit 1
fi







