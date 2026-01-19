"""
Персистентное хранение истории диалогов голосового ассистента.

Хранит диалоги в JSON файле в %APPDATA%/MindType/assistant_history.json
Каждый диалог включает: id, timestamp, system_prompt, messages, title
"""

import json
import logging
import os
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)


def _get_history_file_path() -> Path:
    """Получить путь к файлу истории диалогов."""
    if os.name == "nt":
        # Windows: %APPDATA%/MindType/
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        # Linux/macOS: ~/.config/MindType/
        base = Path.home() / ".config"

    app_dir = base / "MindType"
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir / "assistant_history.json"


@dataclass
class DialogMessage:
    """Сообщение в диалоге."""
    role: str  # "user" | "assistant" | "system"
    content: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, str]:
        return {"role": self.role, "content": self.content, "timestamp": self.timestamp}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DialogMessage":
        return cls(
            role=data.get("role", "user"),
            content=data.get("content", ""),
            timestamp=data.get("timestamp", datetime.now().isoformat()),
        )


@dataclass
class Dialog:
    """Диалог с ассистентом."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    system_prompt: str = ""
    messages: List[DialogMessage] = field(default_factory=list)
    title: str = ""  # Автогенерируется из первого сообщения

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "system_prompt": self.system_prompt,
            "messages": [m.to_dict() for m in self.messages],
            "title": self.title,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Dialog":
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            timestamp=data.get("timestamp", datetime.now().isoformat()),
            system_prompt=data.get("system_prompt", ""),
            messages=[DialogMessage.from_dict(m) for m in data.get("messages", [])],
            title=data.get("title", ""),
        )

    def generate_title(self) -> str:
        """Сгенерировать заголовок из первого сообщения пользователя."""
        for msg in self.messages:
            if msg.role == "user" and msg.content:
                # Берём первые 50 символов
                title = msg.content[:50]
                if len(msg.content) > 50:
                    title += "..."
                return title
        return "Новый диалог"

    def get_llm_messages(self) -> List[Dict[str, str]]:
        """Получить сообщения в формате для LLM (с system prompt первым)."""
        result = []
        if self.system_prompt:
            result.append({"role": "system", "content": self.system_prompt})
        for msg in self.messages:
            result.append({"role": msg.role, "content": msg.content})
        return result


class DialogHistoryManager:
    """Менеджер истории диалогов."""

    MAX_DIALOGS = 100  # Максимум диалогов в истории

    def __init__(self, history_file: Optional[Path] = None):
        self._history_file = history_file or _get_history_file_path()
        self._dialogs: List[Dialog] = []
        self._current_dialog: Optional[Dialog] = None
        self._load()

    def _load(self) -> None:
        """Загрузить историю из файла."""
        if not self._history_file.exists():
            logger.info(f"[DialogHistory] Файл истории не найден, создаём новый: {self._history_file}")
            self._dialogs = []
            return

        try:
            with open(self._history_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            self._dialogs = [Dialog.from_dict(d) for d in data.get("dialogs", [])]
            logger.info(f"[DialogHistory] Загружено {len(self._dialogs)} диалогов из {self._history_file}")
        except Exception as e:
            logger.error(f"[DialogHistory] Ошибка загрузки истории: {e}")
            self._dialogs = []

    def _save(self) -> None:
        """Сохранить историю в файл."""
        try:
            data = {"dialogs": [d.to_dict() for d in self._dialogs]}
            with open(self._history_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.debug(f"[DialogHistory] Сохранено {len(self._dialogs)} диалогов")
        except Exception as e:
            logger.error(f"[DialogHistory] Ошибка сохранения истории: {e}")

    def start_new_dialog(self, system_prompt: str = "") -> Dialog:
        """Начать новый диалог."""
        self._current_dialog = Dialog(system_prompt=system_prompt)
        logger.info(f"[DialogHistory] Начат новый диалог: {self._current_dialog.id}")
        return self._current_dialog

    def add_message(self, role: str, content: str) -> None:
        """Добавить сообщение в текущий диалог."""
        if not self._current_dialog:
            self.start_new_dialog()

        msg = DialogMessage(role=role, content=content)
        self._current_dialog.messages.append(msg)

        # Генерируем заголовок при первом сообщении пользователя
        if not self._current_dialog.title and role == "user":
            self._current_dialog.title = self._current_dialog.generate_title()

        # Автосохранение после каждого сообщения
        self._save_current_dialog()

    def _save_current_dialog(self) -> None:
        """Сохранить текущий диалог в историю."""
        if not self._current_dialog or not self._current_dialog.messages:
            return

        # Ищем существующий диалог по ID
        existing_idx = None
        for i, d in enumerate(self._dialogs):
            if d.id == self._current_dialog.id:
                existing_idx = i
                break

        if existing_idx is not None:
            # Обновляем существующий
            self._dialogs[existing_idx] = self._current_dialog
        else:
            # Добавляем новый в начало
            self._dialogs.insert(0, self._current_dialog)

        # Ограничиваем количество диалогов
        if len(self._dialogs) > self.MAX_DIALOGS:
            self._dialogs = self._dialogs[:self.MAX_DIALOGS]

        self._save()

    def get_current_dialog(self) -> Optional[Dialog]:
        """Получить текущий диалог."""
        return self._current_dialog

    def set_current_dialog(self, dialog: Dialog) -> None:
        """Установить текущий диалог (для загрузки из истории)."""
        self._current_dialog = dialog
        logger.info(f"[DialogHistory] Загружен диалог: {dialog.id} ({dialog.title})")

    def clear_current_dialog(self) -> None:
        """Очистить текущий диалог (начать заново)."""
        if self._current_dialog:
            # Сохраняем текущий перед очисткой
            self._save_current_dialog()
        self._current_dialog = None
        logger.info("[DialogHistory] Текущий диалог очищен")

    def get_all_dialogs(self) -> List[Dialog]:
        """Получить все диалоги (отсортированы по дате, новые первые)."""
        return sorted(self._dialogs, key=lambda d: d.timestamp, reverse=True)

    def get_dialog_by_id(self, dialog_id: str) -> Optional[Dialog]:
        """Получить диалог по ID."""
        for d in self._dialogs:
            if d.id == dialog_id:
                return d
        return None

    def delete_dialog(self, dialog_id: str) -> bool:
        """Удалить диалог по ID."""
        for i, d in enumerate(self._dialogs):
            if d.id == dialog_id:
                del self._dialogs[i]
                self._save()
                logger.info(f"[DialogHistory] Удалён диалог: {dialog_id}")

                # Если удаляем текущий диалог — сбрасываем
                if self._current_dialog and self._current_dialog.id == dialog_id:
                    self._current_dialog = None

                return True
        return False

    def clear_all(self) -> None:
        """Очистить всю историю."""
        self._dialogs = []
        self._current_dialog = None
        self._save()
        logger.info("[DialogHistory] Вся история диалогов очищена")

    def get_current_context_for_llm(self, max_messages: int = 20) -> List[Dict[str, str]]:
        """
        Получить контекст текущего диалога для отправки в LLM.

        Args:
            max_messages: Максимальное количество сообщений (без system prompt)

        Returns:
            Список сообщений в формате [{"role": "...", "content": "..."}]
        """
        if not self._current_dialog:
            return []

        result = []

        # System prompt всегда первым
        if self._current_dialog.system_prompt:
            result.append({
                "role": "system",
                "content": self._current_dialog.system_prompt
            })

        # Ограничиваем количество сообщений (берём последние)
        messages = self._current_dialog.messages[-max_messages:]
        for msg in messages:
            result.append({"role": msg.role, "content": msg.content})

        return result


# Глобальный экземпляр
_dialog_history_manager: Optional[DialogHistoryManager] = None


def get_dialog_history_manager() -> DialogHistoryManager:
    """Получить глобальный менеджер истории диалогов."""
    global _dialog_history_manager
    if _dialog_history_manager is None:
        _dialog_history_manager = DialogHistoryManager()
    return _dialog_history_manager


