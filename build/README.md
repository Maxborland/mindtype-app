# Инструкции по сборке MindType

Этот каталог содержит скрипты для сборки приложения MindType для всех поддерживаемых платформ: Windows, Linux и macOS.

## Быстрый старт

### Windows
```powershell
# Сборка для Windows (Nuitka)
.\build\build_all.ps1 -Platform windows

# Сборка для всех платформ (если доступны)
.\build\build_all.ps1 -Platform all
```

### Linux
```bash
# Сборка для Linux
./build/build_all.sh

# Сборка с очисткой
./build/build_all.sh --clean
```

### macOS
```bash
# Сборка для macOS
./build/build_all.sh

# Сборка с указанием версии
./build/build_all.sh macos 1.1.0 --clean
```

## Требования

### Общие требования
- Python 3.8 или выше
- pip (менеджер пакетов Python)
- Все зависимости из `requirements.txt`

### Windows
- **Nuitka** (рекомендуется) или PyInstaller
- **Inno Setup 6** (опционально, для создания установщика)
- Visual C++ Build Tools (для Nuitka)

Установка Nuitka:
```powershell
pip install nuitka ordered-set zstandard
```

### Linux
- **PyInstaller**
- **appimagetool** (автоматически скачивается при сборке)
- **wget** или **curl** (для скачивания appimagetool)

Установка PyInstaller:
```bash
pip3 install pyinstaller
```

### macOS
- **PyInstaller**
- **Xcode Command Line Tools**
- **create-dmg** (опционально, для красивого DMG) - `brew install create-dmg`

Установка PyInstaller:
```bash
pip3 install pyinstaller
```

## Детальные инструкции

### Windows

#### Сборка с Nuitka (рекомендуется)
Nuitka компилирует Python в нативный код, что обеспечивает лучшую производительность и защиту от декомпиляции.

```powershell
# Базовая сборка
.\build\build_windows_nuitka.ps1

# Сборка с параметрами
.\build\build_windows_nuitka.ps1 -Version "1.1.0" -Clean

# Сборка в один файл
.\build\build_windows_nuitka.ps1 -Onefile

# Сборка без установщика
.\build\build_windows_nuitka.ps1 -NoInstaller
```

**Параметры:**
- `-Version` - версия приложения (по умолчанию читается из `app/env.py`)
- `-Clean` - очистить предыдущие сборки
- `-Onefile` - создать один исполняемый файл (вместо папки)
- `-NoInstaller` - не создавать установщик Inno Setup

**Результаты:**
- `dist/MindType/MindType.exe` - исполняемый файл
- `dist/MindType-{version}-Setup.exe` - установщик (если Inno Setup установлен)

#### Сборка с PyInstaller
```powershell
.\build\build_windows.ps1 -Version "1.1.0" -Clean
```

### Linux

#### Сборка AppImage
```bash
# Базовая сборка
./build/build_linux.sh

# Сборка с параметрами
./build/build_linux.sh 1.1.0 --clean
```

**Результаты:**
- `dist/OfflineWhisper/` - папка с исполняемым файлом
- `dist/MindType-{version}-x86_64.AppImage` - AppImage файл

**Примечания:**
- AppImage автоматически скачивает `appimagetool` при первом запуске
- Модели Whisper копируются в папку приложения автоматически
- AppImage можно запускать на любом Linux дистрибутиве без установки

### macOS

#### Сборка DMG
```bash
# Базовая сборка
./build/build_macos.sh

# Сборка с параметрами
./build/build_macos.sh 1.1.0 --clean
```

**Результаты:**
- `dist/OfflineWhisper.app` - приложение macOS
- `dist/MindType-{version}.dmg` - образ диска для установки

**Примечания:**
- Для красивого DMG установите `create-dmg`: `brew install create-dmg`
- Без `create-dmg` используется стандартный `hdiutil`
- Модели Whisper копируются в `.app` bundle автоматически

## Универсальные скрипты

### build_all.ps1 (Windows)
Главный скрипт для автоматизации сборки всех платформ на Windows.

```powershell
# Сборка только для Windows
.\build\build_all.ps1 -Platform windows

# Сборка для всех доступных платформ
.\build\build_all.ps1 -Platform all -Clean

# Сборка Linux через WSL
.\build\build_all.ps1 -Platform linux
```

**Параметры:**
- `-Platform` - платформа: `windows`, `linux`, `macos`, `all`
- `-Version` - версия приложения
- `-Clean` - очистить предыдущие сборки
- `-NoInstaller` - не создавать установщик (только для Windows)
- `-Onefile` - создать один файл (только для Windows)

### build_all.sh (Linux/macOS)
Главный скрипт для автоматизации сборки на Linux и macOS.

```bash
# Сборка для текущей платформы
./build/build_all.sh

# Сборка с указанием платформы
./build/build_all.sh linux 1.1.0 --clean
./build/build_all.sh macos --clean
```

## Версия приложения

Версия приложения автоматически читается из `app/env.py` (переменная `APP_VERSION`). Вы можете:

1. Изменить версию в `app/env.py`:
   ```python
   APP_VERSION: str = "1.1.0"
   ```

2. Указать версию вручную при сборке:
   ```powershell
   .\build\build_windows_nuitka.ps1 -Version "1.1.0"
   ```

## Модели Whisper

Модели Whisper должны находиться в папке `models/` в корне проекта. Структура:
```
models/
  ├── tiny/
  ├── small/
  ├── medium/
  ├── large-v3/
  └── distil-large-v2/
```

Модели автоматически копируются в собранное приложение. Если модели отсутствуют, сборка продолжится, но их нужно будет добавить вручную.

## Устранение проблем

### Windows

**Ошибка: "Python не найден"**
- Убедитесь, что Python установлен и добавлен в PATH
- Проверьте: `python --version`

**Ошибка компиляции Nuitka**
- Установите Visual C++ Build Tools
- Проверьте наличие всех зависимостей: `pip install -r requirements.txt`
- Убедитесь, что достаточно места на диске (требуется ~2-5 GB)

**Ошибка: "Inno Setup не найден"**
- Установите Inno Setup 6: https://jrsoftware.org/isinfo.php
- Или используйте флаг `-NoInstaller`

### Linux

**Ошибка: "PyInstaller не найден"**
```bash
pip3 install pyinstaller
```

**Ошибка: "appimagetool не скачивается"**
- Проверьте подключение к интернету
- Убедитесь, что установлены `wget` или `curl`

**Ошибка прав доступа**
```bash
chmod +x build/build_linux.sh
chmod +x build/build_all.sh
```

### macOS

**Ошибка: "Xcode Command Line Tools не найдены"**
```bash
xcode-select --install
```

**Ошибка создания DMG**
- Убедитесь, что достаточно места на диске
- Проверьте права доступа к папке `dist/`

**DMG выглядит некрасиво**
- Установите `create-dmg`: `brew install create-dmg`
- Это создаст DMG с красивым интерфейсом

## Структура результатов сборки

После успешной сборки все артефакты находятся в папке `dist/`:

### Windows
```
dist/
  ├── MindType/
  │   ├── MindType.exe
  │   ├── models/
  │   └── [другие файлы]
  └── MindType-1.0.0-Setup.exe
```

### Linux
```
dist/
  ├── OfflineWhisper/
  │   ├── OfflineWhisper
  │   ├── models/
  │   └── [другие файлы]
  └── MindType-1.0.0-x86_64.AppImage
```

### macOS
```
dist/
  ├── OfflineWhisper.app/
  │   └── Contents/
  │       ├── MacOS/
  │       │   ├── OfflineWhisper
  │       │   └── models/
  │       └── [другие файлы]
  └── MindType-1.0.0.dmg
```

## Дополнительная информация

- Все скрипты поддерживают автоматическое чтение версии из `app/env.py`
- Модели Whisper копируются автоматически при сборке
- Скрипты проверяют наличие всех необходимых инструментов перед сборкой
- Подробные сообщения об ошибках помогают быстро найти проблему

## Поддержка

При возникновении проблем:
1. Проверьте логи сборки выше
2. Убедитесь, что все требования установлены
3. Попробуйте сборку с флагом `-Clean` или `--clean`
4. Проверьте наличие достаточного места на диске



