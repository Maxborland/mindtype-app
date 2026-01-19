# PyInstaller hook для faster-whisper
# Собирает все необходимые зависимости

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_dynamic_libs

# Собираем данные ctranslate2
datas = collect_data_files('ctranslate2')
datas += collect_data_files('faster_whisper')
datas += collect_data_files('tokenizers')

# Собираем все подмодули
hiddenimports = collect_submodules('ctranslate2')
hiddenimports += collect_submodules('faster_whisper')
hiddenimports += collect_submodules('tokenizers')
hiddenimports += collect_submodules('huggingface_hub')

# Собираем динамические библиотеки
binaries = collect_dynamic_libs('ctranslate2')







