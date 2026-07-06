"""
Credits Balance Widget для MindType Cloud.

Показывает баланс кредитов с иконкой diamond и кнопкой покупки.
Classic Mac OS System 7 Style.
"""

import logging
from typing import Callable, Optional

from PyQt6.QtCore import Qt, QUrl, pyqtSignal, QThread
from PyQt6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QDialog,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
)
from PyQt6.QtGui import QDesktopServices, QPixmap, QPainter, QColor

logger = logging.getLogger(__name__)

# URL для покупки кредитов
BUY_CREDITS_URL = "https://mindtype.space/buy-credits"


def create_diamond_icon(size: int = 16) -> QPixmap:
    """Create a pixelated diamond icon in System 7 style."""
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(255, 255, 255, 0))

    painter = QPainter(pixmap)
    black = QColor(0, 0, 0)

    # Diamond shape (centered)
    # Top point
    painter.fillRect(7, 1, 2, 2, black)
    # Upper left/right
    painter.fillRect(5, 3, 2, 2, black)
    painter.fillRect(9, 3, 2, 2, black)
    # Middle
    painter.fillRect(3, 5, 2, 2, black)
    painter.fillRect(11, 5, 2, 2, black)
    # Center row (widest)
    painter.fillRect(1, 7, 2, 2, black)
    painter.fillRect(13, 7, 2, 2, black)
    # Lower left/right
    painter.fillRect(3, 9, 2, 2, black)
    painter.fillRect(11, 9, 2, 2, black)
    # Bottom half
    painter.fillRect(5, 11, 2, 2, black)
    painter.fillRect(9, 11, 2, 2, black)
    # Bottom point
    painter.fillRect(7, 13, 2, 2, black)

    # Inner highlights (white/gray for 3D effect)
    painter.fillRect(7, 3, 2, 2, QColor(255, 255, 255))
    painter.fillRect(5, 5, 2, 2, QColor(255, 255, 255))
    painter.fillRect(7, 5, 2, 2, QColor(200, 200, 200))
    painter.fillRect(9, 5, 2, 2, QColor(150, 150, 150))
    painter.fillRect(5, 7, 2, 2, QColor(200, 200, 200))
    painter.fillRect(7, 7, 2, 2, QColor(180, 180, 180))
    painter.fillRect(9, 7, 2, 2, QColor(130, 130, 130))
    painter.fillRect(5, 9, 2, 2, QColor(150, 150, 150))
    painter.fillRect(7, 9, 2, 2, QColor(130, 130, 130))
    painter.fillRect(9, 9, 2, 2, QColor(100, 100, 100))
    painter.fillRect(7, 11, 2, 2, QColor(80, 80, 80))

    painter.end()
    return pixmap


class CreditsBalanceWidget(QWidget):
    """Виджет отображения баланса кредитов MindType Cloud."""

    # Сигнал при обновлении баланса
    balance_updated = pyqtSignal(int)
    # Сигнал для запроса истории (parent должен предоставить данные)
    history_requested = pyqtSignal()

    def __init__(
        self,
        translate_func: Optional[Callable] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._t = translate_func or (lambda x: x)
        self._credits: int = 0
        self._build_ui()

    def _build_ui(self):
        """Построить UI виджета."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # Diamond icon
        self.icon_label = QLabel()
        self.icon_label.setPixmap(create_diamond_icon(16))
        self.icon_label.setFixedSize(18, 18)
        layout.addWidget(self.icon_label)

        # Balance
        self.balance_label = QLabel("-- " + self._t("credits"))
        self.balance_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        layout.addWidget(self.balance_label)

        # Buy button
        self.buy_btn = QPushButton("+")
        self.buy_btn.setFixedSize(20, 20)
        self.buy_btn.setToolTip(self._t("buy_credits"))
        self.buy_btn.setStyleSheet("""
            QPushButton {
                font-size: 14px;
                font-weight: bold;
                border: 1.5px solid #000000;
                border-radius: 0;
                background-color: #ffffff;
                padding: 0;
            }
            QPushButton:hover {
                background-color: #f0f0f0;
            }
            QPushButton:pressed {
                background-color: #000000;
                color: #ffffff;
            }
        """)
        self.buy_btn.clicked.connect(self._on_buy_clicked)
        layout.addWidget(self.buy_btn)

        # History button
        self.history_btn = QPushButton("☰")
        self.history_btn.setFixedSize(20, 20)
        self.history_btn.setToolTip(self._t("credits_history"))
        self.history_btn.setStyleSheet("""
            QPushButton {
                font-size: 11px;
                font-weight: bold;
                border: 1.5px solid #000000;
                border-radius: 0;
                background-color: #ffffff;
                padding: 0;
            }
            QPushButton:hover {
                background-color: #f0f0f0;
            }
            QPushButton:pressed {
                background-color: #000000;
                color: #ffffff;
            }
        """)
        self.history_btn.clicked.connect(self._on_history_clicked)
        layout.addWidget(self.history_btn)

    def _on_buy_clicked(self):
        """Открыть страницу покупки кредитов."""
        QDesktopServices.openUrl(QUrl(BUY_CREDITS_URL))

    def _on_history_clicked(self):
        """Запросить показ истории транзакций."""
        self.history_requested.emit()

    def set_balance(self, credits: int):
        """
        Установить баланс кредитов.

        Args:
            credits: Количество кредитов
        """
        self._credits = credits
        self.balance_label.setText(f"{credits} " + self._t("credits"))

        # Стиль в зависимости от баланса (B&W only)
        if credits <= 5:
            # Критически низкий баланс
            self.balance_label.setStyleSheet(
                "font-weight: bold; font-size: 12px; color: #000000;"
            )
        elif credits <= 20:
            # Низкий баланс
            self.balance_label.setStyleSheet(
                "font-weight: bold; font-size: 12px; color: #404040;"
            )
        else:
            # Нормальный баланс
            self.balance_label.setStyleSheet(
                "font-weight: bold; font-size: 12px; color: #000000;"
            )

        self.balance_updated.emit(credits)

    def get_balance(self) -> int:
        """Получить текущий баланс."""
        return self._credits

    def set_loading(self, loading: bool = True):
        """
        Показать состояние загрузки.

        Args:
            loading: True для показа загрузки
        """
        if loading:
            self.balance_label.setText("...")
            self.balance_label.setStyleSheet(
                "font-weight: bold; font-size: 12px; color: #808080;"
            )
        else:
            # Восстановить нормальное отображение
            self.set_balance(self._credits)

    def set_translate_func(self, func: Callable):
        """Установить функцию перевода."""
        self._t = func
        # Обновить текст
        if self._credits > 0:
            self.set_balance(self._credits)
        else:
            self.balance_label.setText("-- " + self._t("credits"))
        # Обновить tooltip кнопок
        self.buy_btn.setToolTip(self._t("buy_credits"))
        self.history_btn.setToolTip(self._t("credits_history"))


class CreditsHistoryDialog(QDialog):
    """Диалог истории транзакций кредитов. System 7 Style."""

    def __init__(
        self,
        history: list,
        translate_func: Optional[Callable] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._t = translate_func or (lambda x: x)
        self._history = history
        self._build_ui()
        from .components import apply_system7_titlebar
        apply_system7_titlebar(self, self.windowTitle())

    def _build_ui(self):
        """Построить UI диалога."""
        self.setWindowTitle(self._t("credits_history_title"))
        self.setMinimumSize(420, 300)
        self.resize(420, 350)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        if not self._history:
            empty_label = QLabel(self._t("credits_history_empty"))
            empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_label.setStyleSheet("color: #808080; font-size: 12px; padding: 40px;")
            layout.addWidget(empty_label)
        else:
            # Таблица транзакций
            table = QTableWidget()
            table.setColumnCount(4)
            table.setHorizontalHeaderLabels([
                self._t("credits_date"),
                self._t("credits_action"),
                self._t("credits_amount"),
                self._t("credits_balance_after"),
            ])
            table.setRowCount(len(self._history))
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            table.setAlternatingRowColors(True)
            table.verticalHeader().setVisible(False)

            header = table.horizontalHeader()
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)

            for i, entry in enumerate(reversed(self._history)):
                # Дата
                date_str = entry.get("date", entry.get("createdAt", ""))
                if date_str and len(date_str) > 10:
                    date_str = date_str[:10]  # YYYY-MM-DD
                table.setItem(i, 0, QTableWidgetItem(date_str))

                # Операция
                action = entry.get("action", entry.get("type", entry.get("description", "")))
                table.setItem(i, 1, QTableWidgetItem(str(action)))

                # Кредиты (изменение)
                amount = entry.get("amount", entry.get("credits", 0))
                amount_item = QTableWidgetItem(str(amount))
                if isinstance(amount, (int, float)):
                    amount_item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                table.setItem(i, 2, amount_item)

                # Остаток
                balance = entry.get("balanceAfter", entry.get("balance", ""))
                balance_item = QTableWidgetItem(str(balance))
                balance_item.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
                table.setItem(i, 3, balance_item)

            table.setStyleSheet("""
                QTableWidget {
                    border: 1.5px solid #000000;
                    font-size: 11px;
                    gridline-color: #c0c0c0;
                }
                QTableWidget::item {
                    padding: 4px 6px;
                }
                QHeaderView::section {
                    background-color: #dddddd;
                    border: 1px solid #000000;
                    font-weight: bold;
                    font-size: 11px;
                    padding: 4px;
                }
            """)

            layout.addWidget(table)

        # Кнопки
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        buy_btn = QPushButton(self._t("buy_credits"))
        buy_btn.setObjectName("primaryButton")  # центральный 3D-стиль
        buy_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(BUY_CREDITS_URL)))
        btn_layout.addWidget(buy_btn)

        close_btn = QPushButton("OK")  # центральный 3D-стиль (дефолтная кнопка)
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)


class CreditsHistoryWorker(QThread):
    """Фоновый поток для загрузки истории кредитов."""

    history_fetched = pyqtSignal(int, list)  # balance, history
    error_occurred = pyqtSignal(str)

    def __init__(self, provider, parent=None):
        super().__init__(parent)
        self.provider = provider

    def run(self):
        """Загрузить историю кредитов."""
        try:
            info = self.provider.get_balance()
            self.history_fetched.emit(info.credits, info.history)
        except Exception as e:
            logger.error(f"Failed to fetch credits history: {e}")
            self.error_occurred.emit(str(e))


class CreditsRefreshWorker(QThread):
    """Фоновый поток для обновления баланса кредитов."""

    balance_fetched = pyqtSignal(int)
    error_occurred = pyqtSignal(str)

    def __init__(self, provider, parent=None):
        super().__init__(parent)
        self.provider = provider

    def run(self):
        """Запустить обновление баланса."""
        try:
            info = self.provider.get_balance()
            self.balance_fetched.emit(info.credits)
        except Exception as e:
            logger.error(f"Failed to refresh credits balance: {e}")
            self.error_occurred.emit(str(e))
