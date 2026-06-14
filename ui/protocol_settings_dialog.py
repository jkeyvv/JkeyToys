"""协议帧格式配置对话框."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QComboBox, QSpinBox, QCheckBox,
    QPushButton, QLabel,
    QGroupBox, QTextEdit,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from core.protocol_config import ProtocolConfig


CRC_TYPES = ["CRC16-MODBUS", "CRC16-CCITT", "CRC32", "XOR", "无"]


class ProtocolSettingsDialog(QDialog):
    """协议帧格式配置对话框.

    Args:
        config: 当前协议配置
    """

    def __init__(self, config: ProtocolConfig | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("协议帧格式配置")
        self.setMinimumSize(500, 420)
        self.resize(540, 460)
        self._config = config or ProtocolConfig()
        self._init_ui()
        self._load_config(self._config)

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # ---- 帧格式配置 ----
        frame_group = QGroupBox("帧格式")
        form = QFormLayout(frame_group)

        self.edit_header = QLineEdit()
        self.edit_header.setPlaceholderText("如: AA55 或 AA 55")
        form.addRow("帧头 (HEX):", self.edit_header)

        self.edit_dummy = QLineEdit()
        self.edit_dummy.setPlaceholderText("留空表示无 Dummy 字段")
        form.addRow("Dummy (HEX):", self.edit_dummy)

        self.edit_tail = QLineEdit()
        self.edit_tail.setPlaceholderText("如: 0D0A 或 0D 0A")
        form.addRow("帧尾 (HEX):", self.edit_tail)

        self.spin_length_size = QSpinBox()
        self.spin_length_size.setRange(0, 4)
        form.addRow("长度字段 (字节):", self.spin_length_size)

        self.spin_cmd_size = QSpinBox()
        self.spin_cmd_size.setRange(1, 4)
        form.addRow("命令字段 (字节):", self.spin_cmd_size)

        self.combo_crc = QComboBox()
        self.combo_crc.addItems(CRC_TYPES)
        form.addRow("CRC 算法:", self.combo_crc)

        self.spin_crc_size = QSpinBox()
        self.spin_crc_size.setRange(0, 4)
        form.addRow("CRC 字段 (字节):", self.spin_crc_size)

        self.combo_byte_order = QComboBox()
        self.combo_byte_order.addItem("大端 (Big-Endian)", "big")
        self.combo_byte_order.addItem("小端 (Little-Endian)", "little")
        form.addRow("字节序:", self.combo_byte_order)

        self.combo_cmd_pos = QComboBox()
        self.combo_cmd_pos.addItem("LEN 之前（默认）", True)
        self.combo_cmd_pos.addItem("LEN 之后", False)
        form.addRow("CMD 位置:", self.combo_cmd_pos)

        self.spin_timeout = QSpinBox()
        self.spin_timeout.setRange(500, 30000)
        self.spin_timeout.setSingleStep(500)
        self.spin_timeout.setSuffix(" ms")
        form.addRow("查询超时:", self.spin_timeout)

        layout.addWidget(frame_group)

        # ---- 实时预览 ----
        preview_group = QGroupBox("帧结构预览")
        preview_layout = QVBoxLayout(preview_group)
        self.txt_preview = QTextEdit()
        self.txt_preview.setReadOnly(True)
        self.txt_preview.setFont(QFont("Consolas", 10))
        self.txt_preview.setMaximumHeight(80)
        self.txt_preview.setStyleSheet("QTextEdit { background-color: #1e1e1e; color: #d4d4d4; }")
        preview_layout.addWidget(self.txt_preview)
        layout.addWidget(preview_group)

        # 连接信号实时更新预览
        for w in [self.edit_header, self.edit_dummy, self.edit_tail]:
            w.textChanged.connect(self._update_preview)
        for w in [self.spin_length_size, self.spin_cmd_size, self.spin_crc_size]:
            w.valueChanged.connect(self._update_preview)
        self.combo_crc.currentTextChanged.connect(self._on_crc_changed)
        self.combo_cmd_pos.currentIndexChanged.connect(self._update_preview)

        # ---- 工具栏 ----
        toolbar = QHBoxLayout()

        btn_reset = QPushButton("恢复默认")
        btn_reset.clicked.connect(self._reset_default)
        toolbar.addWidget(btn_reset)

        toolbar.addStretch()

        btn_ok = QPushButton("确定")
        btn_ok.clicked.connect(self.accept)
        toolbar.addWidget(btn_ok)

        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        toolbar.addWidget(btn_cancel)

        layout.addLayout(toolbar)

    def _load_config(self, config: ProtocolConfig):
        """加载配置到界面."""
        self.edit_header.setText(config.header.hex(" ").upper())
        self.edit_dummy.setText(config.dummy_byte.hex(" ").upper() if config.dummy_byte else "")
        self.edit_tail.setText(config.tail.hex(" ").upper())
        self.spin_length_size.setValue(config.length_size)
        self.spin_cmd_size.setValue(config.cmd_size)
        self.spin_crc_size.setValue(config.crc_size)
        self.spin_timeout.setValue(config.query_timeout_ms)

        idx = self.combo_cmd_pos.findData(config.cmd_before_len)
        self.combo_cmd_pos.setCurrentIndex(max(idx, 0))

        idx = self.combo_crc.findText(config.crc_type)
        self.combo_crc.setCurrentIndex(max(idx, 0))

        idx = self.combo_byte_order.findData(config.byte_order)
        self.combo_byte_order.setCurrentIndex(max(idx, 0))

        self._update_preview()

    def _on_crc_changed(self, text: str):
        """CRC 类型变化时自动调整 CRC 大小."""
        if text == "无":
            self.spin_crc_size.setValue(0)
        elif text == "XOR":
            self.spin_crc_size.setValue(1)
        elif text == "CRC32":
            if self.spin_crc_size.value() < 4:
                self.spin_crc_size.setValue(4)
        elif self.spin_crc_size.value() < 2:
            self.spin_crc_size.setValue(2)
        self._update_preview()

    def _update_preview(self):
        """更新帧结构预览."""
        try:
            cfg = self.get_config()
        except Exception:
            self.txt_preview.setPlainText("（配置有误，请检查 HEX 输入）")
            return

        byte_order_str = "大端" if cfg.byte_order == "big" else "小端"
        parts = []
        parts.append(f"帧头 [{cfg.header.hex(' ').upper()}]")
        if cfg.dummy_byte:
            parts.append(f"DUMMY [{cfg.dummy_byte.hex(' ').upper()}]")
        if cfg.cmd_before_len:
            if cfg.cmd_size > 0:
                parts.append(f"CMD [{cfg.cmd_size}B]")
            if cfg.length_size > 0:
                parts.append(f"LEN [{cfg.length_size}B] (DATA)")
        else:
            if cfg.length_size > 0:
                parts.append(f"LEN [{cfg.length_size}B] (CMD+DATA)")
            if cfg.cmd_size > 0:
                parts.append(f"CMD [{cfg.cmd_size}B]")
        parts.append(f"DATA [NB]")
        if cfg.crc_size > 0:
            parts.append(f"CRC [{cfg.crc_type} {cfg.crc_size}B]")
        parts.append(f"帧尾 [{cfg.tail.hex(' ').upper()}]")
        parts.append(f"字节序 [{byte_order_str}]")

        # 示例帧
        example_data = b"\x01\x02"
        cmd_sample = b"\x01" * cfg.cmd_size
        if cfg.length_size > 0:
            if cfg.cmd_before_len:
                length_val = len(example_data)
            else:
                length_val = cfg.cmd_size + len(example_data)
            length_bytes = length_val.to_bytes(cfg.length_size, cfg.byte_order)
        else:
            length_bytes = b""

        if cfg.cmd_before_len:
            example = cfg.header + cfg.dummy_byte + cmd_sample + length_bytes + example_data
        else:
            example = cfg.header + cfg.dummy_byte + length_bytes + cmd_sample + example_data

        if cfg.crc_size > 0:
            example += b"\x00" * cfg.crc_size
        example += cfg.tail

        self.txt_preview.setPlainText(
            " | ".join(parts) + f"\n示例: {example.hex(' ').upper()}"
        )

    def get_config(self) -> ProtocolConfig:
        """从界面获取配置."""
        return ProtocolConfig(
            header=ProtocolConfig.hex_to_bytes(self.edit_header.text()),
            dummy_byte=ProtocolConfig.hex_to_bytes(self.edit_dummy.text()) if self.edit_dummy.text().strip() else b"",
            tail=ProtocolConfig.hex_to_bytes(self.edit_tail.text()),
            length_size=self.spin_length_size.value(),
            cmd_size=self.spin_cmd_size.value(),
            crc_size=self.spin_crc_size.value(),
            crc_type=self.combo_crc.currentText(),
            cmd_before_len=self.combo_cmd_pos.currentData(),
            byte_order=self.combo_byte_order.currentData(),
            query_timeout_ms=self.spin_timeout.value(),
        )

    def _reset_default(self):
        """恢复默认配置."""
        self._load_config(ProtocolConfig())
