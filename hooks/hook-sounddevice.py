# PyInstaller hook для sounddevice
# Включает PortAudio библиотеки

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_data_files

# Собираем динамические библиотеки PortAudio
binaries = collect_dynamic_libs('sounddevice')
binaries += collect_dynamic_libs('_sounddevice_data')

# Данные
datas = collect_data_files('sounddevice')
datas += collect_data_files('_sounddevice_data')







