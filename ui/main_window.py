"""主窗口."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QStatusBar, QMenuBar, QMenu, QMessageBox, QSplitter, QTabWidget,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction

from ui.serial_panel import SerialPanel
from ui.data_panel import DataPanel
from ui.protocol_panel import ProtocolPanel
from core.serial_worker import SerialWorker
from core.protocol import Protocol
from core.protocol_config import ProtocolConfig
from version import __version__


# 协议配置文件路径
PROTOCOL_DIR = Path(__file__).parent.parent / "protocol"
PROTOCOL_FILE = PROTOCOL_DIR / "protocol.json"
DEFAULT_PROTOCOL_FILE = PROTOCOL_DIR / "protocol_default.json"


class MainWindow(QMainWindow):
    """JkeyToys 主窗口."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("JkeyToys - UART 调试工具")
        self.setMinimumSize(1000, 650)
        self.resize(1200, 750)

        # 加载协议文件（首次用默认，之后用上次保存的）
        self._protocol_config, self._commands, self._buttons = self._load_protocol_file()
        self._protocol = Protocol(self._protocol_config)
        self._worker = SerialWorker(self._protocol, self)
        self._init_ui()
        self._init_menu()
        self._connect_signals()

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        splitter = QSplitter(Qt.Horizontal)

        # 左侧: 串口配置
        self.serial_panel = SerialPanel()
        self.serial_panel.setMinimumWidth(220)
        self.serial_panel.setMaximumWidth(280)
        splitter.addWidget(self.serial_panel)

        # 右侧: Tab 切换
        self.tab_widget = QTabWidget()

        # Tab 1: 数据收发
        self.data_panel = DataPanel()
        self.tab_widget.addTab(self.data_panel, "📊 数据收发")

        # Tab 2: 命令调试
        self.protocol_panel = ProtocolPanel()
        self.protocol_panel.set_protocol_config(self._protocol_config)
        self.protocol_panel.set_protocol(self._protocol)
        self.protocol_panel.set_command_templates(self._commands)
        self.protocol_panel.load_buttons(self._buttons)
        self.tab_widget.addTab(self.protocol_panel, "🔍 命令调试")

        splitter.addWidget(self.tab_widget)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        layout = QHBoxLayout(central)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(splitter)

        # 状态栏
        self.statusBar().showMessage("就绪")

    def _init_menu(self):
        menubar = self.menuBar()

        # 文件菜单
        file_menu = menubar.addMenu("文件(&F)")

        act_import = QAction("导入协议...", self)
        act_import.triggered.connect(self._import_protocol)
        file_menu.addAction(act_import)

        act_export = QAction("导出协议...", self)
        act_export.triggered.connect(self._export_protocol)
        file_menu.addAction(act_export)

        file_menu.addSeparator()

        act_exit = QAction("退出(&Q)", self)
        act_exit.setShortcut("Ctrl+Q")
        act_exit.triggered.connect(self.close)
        file_menu.addAction(act_exit)

        # 协议菜单
        protocol_menu = menubar.addMenu("协议(&P)")
        act_protocol = QAction("协议配置...", self)
        act_protocol.triggered.connect(self._open_protocol_settings)
        protocol_menu.addAction(act_protocol)

        act_commands = QAction("命令编辑...", self)
        act_commands.triggered.connect(self._open_command_editor)
        protocol_menu.addAction(act_commands)

        # 帮助菜单
        help_menu = menubar.addMenu("帮助(&H)")
        act_about = QAction("关于(&A)", self)
        act_about.triggered.connect(self._show_about)
        help_menu.addAction(act_about)

        # 工具栏
        toolbar = self.addToolBar("工具")
        toolbar.setMovable(False)

        act_refresh = QAction("🔄 刷新串口", self)
        act_refresh.setShortcut("F5")
        act_refresh.triggered.connect(self.serial_panel.refresh_ports)
        toolbar.addAction(act_refresh)

    def _connect_signals(self):
        # 串口面板 -> 主窗口
        self.serial_panel.open_clicked.connect(self._on_open_serial)
        self.serial_panel.close_clicked.connect(self._on_close_serial)

        # 数据面板 -> 主窗口
        self.data_panel.send_raw_requested.connect(self._on_send_raw)

        # 协议面板 -> 主窗口
        self.protocol_panel.send_frame_requested.connect(self._on_send_frame)
        self.protocol_panel.buttons_changed.connect(self._on_buttons_changed)

        # 工作线程 -> 主窗口
        self._worker.data_received.connect(self._on_data_received)
        self._worker.frame_received.connect(self._on_frame_received)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.connection_changed.connect(self._on_connection_changed)

    # ========== 协议文件读写 ==========

    def _load_protocol_file(self) -> tuple[ProtocolConfig, list[dict], list[dict]]:
        """加载 protocol.json，首次运行从 protocol_default.json 复制."""
        if not PROTOCOL_FILE.exists() and DEFAULT_PROTOCOL_FILE.exists():
            import shutil
            shutil.copy2(DEFAULT_PROTOCOL_FILE, PROTOCOL_FILE)

        if PROTOCOL_FILE.exists():
            try:
                with open(PROTOCOL_FILE, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                config = ProtocolConfig.from_dict(raw.get("protocol", {}))
                commands = raw.get("commands", [])
                buttons = raw.get("buttons", [])
                return config, commands, buttons
            except Exception:
                pass
        return ProtocolConfig(), [], []

    def _save_protocol_file(self):
        """保存当前协议配置、命令模板和按钮实例到 protocol.json."""
        data = {
            "protocol": self._protocol_config.to_dict(),
            "commands": self._commands,
            "buttons": self._buttons,
        }
        try:
            with open(PROTOCOL_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存协议文件失败: {e}")

    # ========== 信号处理 ==========

    def _on_buttons_changed(self, buttons: list[dict]):
        """按钮实例列表变更."""
        self._buttons = buttons
        self._save_protocol_file()

    def _apply_protocol_config(self, config: ProtocolConfig):
        """应用协议配置变更."""
        self._protocol_config = config
        self._protocol = Protocol(config)
        self._worker.set_protocol(self._protocol)
        self.protocol_panel.set_protocol_config(config)
        self.protocol_panel.set_protocol(self._protocol)
        self.protocol_panel.set_command_templates(self._commands)
        self._save_protocol_file()
        self.statusBar().showMessage("协议配置已更新")

    # ========== 串口操作 ==========

    def _on_open_serial(self, config: dict):
        success = self._worker.open_port(**config)
        if success:
            self.statusBar().showMessage(
                f"已连接 {config['port']} @ {config['baudrate']}bps"
            )

    def _on_close_serial(self):
        self._worker.close_port()
        self.statusBar().showMessage("已断开连接")

    def _on_send_raw(self, data: bytes):
        if self._worker.is_connected:
            self._worker.send_raw(data)
            self.data_panel.append_tx_data(data)
        else:
            self.statusBar().showMessage("串口未连接，无法发送")

    def _on_send_frame(self, cmd: int, data: bytes):
        if self._worker.is_connected:
            self._worker.send_frame(cmd, data)
            frame_bytes = self._protocol.encode(cmd, data)
            self.data_panel.append_tx_data(frame_bytes)
        else:
            self.statusBar().showMessage("串口未连接，无法发送")

    def _on_data_received(self, raw: bytes):
        self.data_panel.append_rx_data(raw, "RX")

    def _on_frame_received(self, frame):
        self.protocol_panel.append_rx_frame(frame)

    def _on_error(self, msg: str):
        self.statusBar().showMessage(f"错误: {msg}")
        self.data_panel.append_rx_data(f"[ERROR] {msg}".encode(), "ERR")

    def _on_connection_changed(self, connected: bool):
        self.serial_panel.set_connected(connected)
        if not connected:
            self.statusBar().showMessage("连接已断开")

    # ========== 对话框 ==========

    def _show_about(self):
        QMessageBox.about(
            self,
            "关于 JkeyToys",
            f"JkeyToys v{__version__}\n\n"
            "基于 PySide6 的 UART 调试工具\n"
            "支持自定义帧协议通信和原始数据打印\n\n"
            "协议格式: AA 55 | LEN | CMD | DATA | CRC16 | 0D 0A",
        )

    def _open_protocol_settings(self):
        """打开协议配置对话框."""
        from ui.protocol_settings_dialog import ProtocolSettingsDialog

        dialog = ProtocolSettingsDialog(self._protocol_config, self)
        if dialog.exec() != ProtocolSettingsDialog.Accepted:
            return

        config = dialog.get_config()
        self._apply_protocol_config(config)

    def _open_command_editor(self):
        """打开命令编辑对话框."""
        from ui.protocol_editor import ProtocolEditorDialog

        dialog = ProtocolEditorDialog(self._commands, self._protocol_config, self)
        if dialog.exec() != ProtocolEditorDialog.Accepted:
            return

        new_config = dialog.get_protocol_config()
        if new_config and new_config != self._protocol_config:
            self._protocol_config = new_config
            self._protocol = Protocol(new_config)
            self._worker.set_protocol(self._protocol)
            self.protocol_panel.set_protocol_config(new_config)
            self.protocol_panel.set_protocol(self._protocol)

        self._commands = dialog.get_commands()
        self.protocol_panel.set_command_templates(self._commands)
        self._save_protocol_file()
        self.statusBar().showMessage("命令清单已更新")

    def _import_protocol(self):
        """从 JSON 文件导入协议配置和命令."""
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(
            self, "导入协议配置", str(PROTOCOL_DIR), "JSON 文件 (*.json);;所有文件 (*)"
        )
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception as e:
            QMessageBox.warning(self, "导入失败", f"读取文件失败:\n{e}")
            return

        # 解析配置
        protocol_data = raw.get("protocol", {})
        commands = raw.get("commands", [])
        buttons = raw.get("buttons", [])

        if protocol_data:
            try:
                config = ProtocolConfig.from_dict(protocol_data)
                self._apply_protocol_config(config)
            except Exception:
                pass

        if commands:
            self._commands = commands
            self.protocol_panel.set_command_templates(self._commands)

        if buttons:
            self._buttons = buttons
            self.protocol_panel.load_buttons(self._buttons)

        self._save_protocol_file()
        self.statusBar().showMessage(f"已从 {path} 导入协议配置")

    def _export_protocol(self):
        """导出协议配置和命令到 JSON 文件."""
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getSaveFileName(
            self, "导出协议配置", str(PROTOCOL_DIR / "protocol_export.json"), "JSON 文件 (*.json);;所有文件 (*)"
        )
        if not path:
            return

        data = {
            "protocol": self._protocol_config.to_dict(),
            "commands": self._commands,
            "buttons": self._buttons,
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.statusBar().showMessage(f"已导出协议配置到 {path}")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", f"写入文件失败:\n{e}")

    def closeEvent(self, event):
        if self._worker.is_connected:
            self._worker.close_port()
        event.accept()
