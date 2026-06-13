"""数据收发面板."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QTextEdit, QPushButton, QLabel, QComboBox, QCheckBox, QSplitter,
)
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QFont, QTextCursor, QColor, QTextCharFormat


class DataPanel(QWidget):
    """数据收发面板.

    信号:
        send_raw_requested(bytes): 请求发送原始数据
    """

    send_raw_requested = Signal(bytes)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rx_mode = "HEX"
        self._tx_mode = "HEX"
        self._auto_scroll = True
        self._show_timestamp = True
        self._init_ui()

    def _init_ui(self):
        splitter = QSplitter(Qt.Vertical)

        # === 接收区 ===
        rx_group = QGroupBox("数据接收")
        rx_layout = QVBoxLayout(rx_group)

        rx_ctrl = QHBoxLayout()
        rx_ctrl.addWidget(QLabel("显示模式:"))
        self.combo_rx_mode = QComboBox()
        self.combo_rx_mode.addItems(["HEX", "ASCII"])
        self.combo_rx_mode.currentTextChanged.connect(self._on_rx_mode_changed)
        rx_ctrl.addWidget(self.combo_rx_mode)

        self.chk_timestamp = QCheckBox("时间戳")
        self.chk_timestamp.setChecked(True)
        self.chk_timestamp.toggled.connect(lambda v: setattr(self, "_show_timestamp", v))
        rx_ctrl.addWidget(self.chk_timestamp)

        rx_ctrl.addStretch()

        self.btn_clear_rx = QPushButton("清空接收")
        self.btn_clear_rx.clicked.connect(lambda: self.txt_receive.clear())
        rx_ctrl.addWidget(self.btn_clear_rx)

        rx_layout.addLayout(rx_ctrl)

        self.txt_receive = QTextEdit()
        self.txt_receive.setReadOnly(True)
        self.txt_receive.setFont(QFont("Consolas", 10))
        self.txt_receive.setStyleSheet("QTextEdit { background-color: #1e1e1e; color: #d4d4d4; }")
        rx_layout.addWidget(self.txt_receive)

        # 监听滚动条，到底部自动开启，向上滑自动关闭
        scrollbar = self.txt_receive.verticalScrollBar()
        scrollbar.rangeChanged.connect(self._on_scroll_range_changed)
        scrollbar.valueChanged.connect(self._on_scroll_value_changed)

        splitter.addWidget(rx_group)

        # === 发送区 ===
        tx_group = QGroupBox("数据发送")
        tx_layout = QVBoxLayout(tx_group)

        tx_ctrl = QHBoxLayout()
        tx_ctrl.addWidget(QLabel("发送模式:"))
        self.combo_tx_mode = QComboBox()
        self.combo_tx_mode.addItems(["HEX", "ASCII"])
        self.combo_tx_mode.currentTextChanged.connect(self._on_tx_mode_changed)
        tx_ctrl.addWidget(self.combo_tx_mode)

        tx_ctrl.addStretch()

        self.btn_clear_tx = QPushButton("清空发送")
        self.btn_clear_tx.clicked.connect(lambda: self.txt_send.clear())
        tx_ctrl.addWidget(self.btn_clear_tx)

        tx_layout.addLayout(tx_ctrl)

        self.txt_send = QTextEdit()
        self.txt_send.setFont(QFont("Consolas", 10))
        self.txt_send.setMaximumHeight(100)
        self.txt_send.setPlaceholderText("输入要发送的数据... HEX模式请用空格分隔 (如: AA 01 02 03)")
        tx_layout.addWidget(self.txt_send)

        btn_row = QHBoxLayout()
        self.btn_send = QPushButton("发送")
        self.btn_send.setStyleSheet("QPushButton { background-color: #6B9BBF; color: white; font-weight: bold; padding: 8px 24px; }")
        self.btn_send.clicked.connect(self._on_send)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_send)
        tx_layout.addLayout(btn_row)

        splitter.addWidget(tx_group)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(splitter)

    def _on_scroll_value_changed(self, value: int):
        """滚动条位置变化，判断是否在底部."""
        scrollbar = self.txt_receive.verticalScrollBar()
        self._auto_scroll = (value >= scrollbar.maximum())

    def _on_scroll_range_changed(self, min_val: int, max_val: int):
        """滚动条范围变化（新内容加入），如果在底部则自动滚到底."""
        if self._auto_scroll:
            self.txt_receive.verticalScrollBar().setValue(max_val)

    def _on_rx_mode_changed(self, mode: str):
        self._rx_mode = mode

    def _on_tx_mode_changed(self, mode: str):
        self._tx_mode = mode

    def append_rx_data(self, raw: bytes, direction: str = "RX"):
        """追加接收到的原始数据."""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3] if self._show_timestamp else ""

        if self._rx_mode == "HEX":
            text = raw.hex(" ").upper()
        else:
            try:
                text = raw.decode("ascii", errors="replace")
            except Exception:
                text = raw.hex(" ").upper()

        prefix = f"[{timestamp}] {direction}: " if timestamp else f"{direction}: "
        self._append_colored(prefix, text, direction)

    def append_tx_data(self, raw: bytes):
        """追加发送数据."""
        self.append_rx_data(raw, "TX")

    def _append_colored(self, prefix: str, text: str, direction: str):
        cursor = self.txt_receive.textCursor()
        cursor.movePosition(QTextCursor.End)

        fmt_prefix = QTextCharFormat()
        if direction == "TX":
            fmt_prefix.setForeground(QColor("#4FC3F7"))
        else:
            fmt_prefix.setForeground(QColor("#81C784"))

        fmt_data = QTextCharFormat()
        fmt_data.setForeground(QColor("#d4d4d4"))

        cursor.insertText(prefix, fmt_prefix)
        cursor.insertText(text + "\n", fmt_data)

    def _on_send(self):
        text = self.txt_send.toPlainText().strip()
        if not text:
            return

        try:
            if self._tx_mode == "HEX":
                hex_str = text.replace(" ", "").replace("\n", "")
                data = bytes.fromhex(hex_str)
            else:
                data = text.encode("utf-8")

            self.send_raw_requested.emit(data)

        except ValueError as e:
            self.append_rx_data(f"[ERROR] 数据格式错误: {e}".encode(), "ERR")
