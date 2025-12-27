# Runtime hook для jaraco
# Создаёт заглушку для jaraco модуля, который требуется pkg_resources

import sys
import types

# Создаём пустые модули jaraco если их нет
if 'jaraco' not in sys.modules:
    jaraco = types.ModuleType('jaraco')
    jaraco.__path__ = []
    sys.modules['jaraco'] = jaraco

if 'jaraco.text' not in sys.modules:
    jaraco_text = types.ModuleType('jaraco.text')
    sys.modules['jaraco.text'] = jaraco_text

if 'jaraco.functools' not in sys.modules:
    jaraco_functools = types.ModuleType('jaraco.functools')

    # Добавляем базовые функции которые могут понадобиться
    def pass_none(func):
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        return wrapper

    jaraco_functools.pass_none = pass_none
    sys.modules['jaraco.functools'] = jaraco_functools

if 'jaraco.context' not in sys.modules:
    jaraco_context = types.ModuleType('jaraco.context')
    sys.modules['jaraco.context'] = jaraco_context







