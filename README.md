# MindType Desktop Application

Десктопное приложение для голосового ввода текста с использованием Whisper AI.

## 🚀 Возможности

- 🎤 Голосовой ввод в реальном времени
- 🌍 Поддержка множества языков
- 🔒 Работает полностью офлайн
- ⌨️ Горячие клавиши для быстрого доступа
- 📋 Автоматическая вставка текста
- 🎨 Современный интерфейс на PyQt6

## 📋 Требования

- Python 3.10+
- Windows / macOS / Linux
- Микрофон

## 🛠 Установка

### Через pip

```bash
pip install -r requirements.txt
```

### Запуск

```bash
python main.py
```

## 🔨 Сборка

### Windows (PyInstaller)

```powershell
.\build\build_windows.ps1
```

### Windows (Nuitka - рекомендуется)

```powershell
.\build\build_windows_nuitka.ps1
```

### Linux

```bash
./build/build_linux.sh
```

### macOS

```bash
./build/build_macos.sh
```

## 📦 Структура проекта

```
├── app/              # Основной код приложения
│   ├── main.py       # Точка входа
│   ├── transcriber.py # Транскрибация аудио
│   ├── licensing/    # Система лицензирования
│   └── platform/     # Платформо-специфичный код
├── build/            # Скрипты сборки
├── assets/           # Иконки и ресурсы
├── models/           # Модели Whisper (не в git)
└── tools/            # Вспомогательные инструменты
```

## 🔐 Лицензирование

Приложение использует систему лицензирования для управления активациями.

## 🛠 Технологии

- **PyQt6** - GUI фреймворк
- **faster-whisper** - Транскрибация аудио
- **sounddevice** - Запись аудио
- **PyInstaller/Nuitka** - Сборка исполняемых файлов

## 📄 Лицензия

Private - All rights reserved














