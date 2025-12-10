#!/usr/bin/env python3
"""
Генератор лицензионных ключей для Offline Whisper.
Использование: python keygen.py [количество_ключей]
"""

import sys
import os

# Добавляем путь к app для импорта
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.licensing.key_validator import generate_license_key, KeyValidator


def main():
    count = 1
    if len(sys.argv) > 1:
        try:
            count = int(sys.argv[1])
        except ValueError:
            print(f"Ошибка: '{sys.argv[1]}' не является числом")
            print("Использование: python keygen.py [количество_ключей]")
            sys.exit(1)

    if count < 1:
        count = 1
    elif count > 1000:
        print("Предупреждение: генерация более 1000 ключей за раз не рекомендуется")
        count = 1000

    print(f"Генерация {count} лицензионных ключей для Offline Whisper")
    print("=" * 50)
    print()

    keys = []
    for i in range(count):
        key = generate_license_key()
        keys.append(key)

        # Верификация
        is_valid = KeyValidator.validate(key)
        status = "✓" if is_valid else "✗ ОШИБКА"

        print(f"{i + 1:4d}. {key}  {status}")

    print()
    print("=" * 50)
    print(f"Сгенерировано: {len(keys)} ключей")

    # Сохраняем в файл если много ключей
    if count > 5:
        filename = f"license_keys_{len(keys)}.txt"
        with open(filename, "w", encoding="utf-8") as f:
            f.write("# Лицензионные ключи Offline Whisper\n")
            f.write(f"# Сгенерировано: {len(keys)} шт.\n")
            f.write("#\n")
            for key in keys:
                f.write(f"{key}\n")
        print(f"\nКлючи сохранены в файл: {filename}")


if __name__ == "__main__":
    main()







