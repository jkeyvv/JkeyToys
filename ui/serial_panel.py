"""串口配置面板."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QComboBox, QPushButton, QLabel, QSpinBox, QDoubleSpinBox,
)
from PySide6.QtCore import Signal

from core.serial_worker import list_serial_ports


class SerialPanel(QWidget):
    """串口配置面板.

    信号:
        open_clicked(dict): 点击打开串口，传递配置参数
        close_clicked(): 点击关闭串口
    """

    open_clicked = Signal(dict)
    close_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_open = False
        self._init_ui()

    def _init_ui(self):
        group = QGroupBox("串口配置")
        layout = QVBoxLayout(group)

        # 串口选择
        row_port = QHBoxLayout()
        row_port.addWidget(QLabel("串口:"))
        self.combo_port = QComboBox()
        self.combo_port.setMinimumWidth(120)
        row_port.addWidget(self.combo_port, 1)
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.setFixedWidth(60)
        self.btn_refresh.clicked.connect(self.refresh_ports)
        row_port.addWidget(self.btn_refresh)
        layout.addLayout(row_port)

        # 波特率
        row_baud = QHBoxLayout()
        row_baud.addWidget(QLabel("波特率:"))
        self.combo_baud = QComboBox()
        self.combo_baud.addItems(["9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600"])
        self.combo_baud.setCurrentText("115200")
        self.combo_baud.setEditable(True)
        row_baud.addWidget(self.combo_baud, 1)
        layout.addLayout(row_baud)

        # 数据位
        row_data = QHBoxLayout()
        row_data.addWidget(QLabel("数据位:"))
        self.combo_databits = QComboBox()
        self.combo_databits.addItems(["5", "6", "7", "8"])
        self.combo_databits.setCurrentText("8")
        row_data.addWidget(self.combo_databits, 1)
        layout.addLayout(row_data)

        # 停止位
        row_stop = QHBoxLayout()
        row_stop.addWidget(QLabel("停止位:"))
        self.combo_stopbits = QComboBox()
        self.combo_stopbits.addItems(["1", "1.5", "2"])
        row_stop.addWidget(self.combo_stopbits, 1)
        layout.addLayout(row_stop)

        # 校验位
        row_parity = QHBoxLayout()
        row_parity.addWidget(QLabel("校验位:"))
        self.combo_parity = QComboBox()
        self.combo_parity.addItems(["None", "Even", "Odd", "Mark", "Space"])
        row_parity.addWidget(self.combo_parity, 1)
        layout.addLayout(row_parity)

        # 打开/关闭按钮
        self.btn_open = QPushButton("打开串口")
        self.btn_open.setStyleSheet("QPushButton { background-color: #6B9B7A; color: white; font-weight: bold; padding: 8px; }")
        self.btn_open.clicked.connect(self._on_open_close)
        layout.addWidget(self.btn_open)

        # 状态
        self.lbl_status = QLabel("● 未连接")
        self.lbl_status.setStyleSheet("color: gray; font-weight: bold;")
        layout.addWidget(self.lbl_status)

        layout.addStretch()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(group)

        self.refresh_ports()

    def refresh_ports(self):
        """刷新可用串口列表."""
        self.combo_port.clear()
        ports = list_serial_ports()
        self.combo_port.addItems(ports)

    def _on_open_close(self):
        if self._is_open:
            self.close_clicked.emit()
        else:
            config = {
                "port": self.combo_port.currentText(),
                "baudrate": int(self.combo_baud.currentText()),
                "databits": int(self.combo_databits.currentText()),
                "stopbits": float(self.combo_stopbits.currentText()),
                "parity": self.combo_parity.currentText(),
            }
            self.open_clicked.emit(config)

    def set_connected(self, connected: bool):
        """更新连接状态显示."""
        self._is_open = connected
        if connected:
            self.btn_open.setText("关闭串口")
            self.btn_open.setStyleSheet("QPushButton { background-color: #C47A6E; color: white; font-weight: bold; padding: 8px; }")
            self.lbl_status.setText("● 已连接")
            self.lbl_status.setStyleSheet("color: #6B9B7A; font-weight: bold;")
            self._set_config_enabled(False)
        else:
            self.btn_open.setText("打开串口")
            self.btn_open.setStyleSheet("QPushButton { background-color: #6B9B7A; color: white; font-weight: bold; padding: 8px; }")
            self.lbl_status.setText("● 未连接")
            self.lbl_status.setStyleSheet("color: gray; font-weight: bold;")
            self._set_config_enabled(True)

    def _set_config_enabled(self, enabled: bool):
        self.combo_port.setEnabled(enabled)
        self.combo_baud.setEnabled(enabled)
        self.combo_databits.setEnabled(enabled)
        self.combo_stopbits.setEnabled(enabled)
        self.combo_parity.setEnabled(enabled)
        self.btn_refresh.setEnabled(enabled)
