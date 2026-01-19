# PyInstaller hook для jaraco
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# Собираем все подмодули jaraco
hiddenimports = collect_submodules('jaraco')
hiddenimports += ['more_itertools', 'autocommand']

# Собираем данные
datas = collect_data_files('jaraco')







