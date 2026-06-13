"""命令调试面板 - 自动匹配查询响应与主动上报."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QPushButton, QLabel,
    QScrollArea, QDialog, QFormLayout, QLineEdit,
    QComboBox, QGroupBox,
)
from PySide6.QtCore import Signal, Qt, QTimer, QMimeData, QPoint
from PySide6.QtGui import QFont, QColor, QTextCursor, QTextCharFormat, QDrag, QPainter


@dataclass
class PendingQuery:
    """待处理的查询命令."""
    cmd: int
    name: str
    btn: object  # QueryButton
    timer: QTimer


class QueryButton(QPushButton):
    """命令调试面板中的按钮实例，支持拖拽排序."""

    def __init__(self, name: str, cmd: str, tx_data: str,
                 tx_fields: list[dict] | None = None,
                 rx_fields: list[dict] | None = None,
                 tx_data_len: int = 0, rx_data_len: int = 0,
                 parent=None):
        super().__init__(name, parent)
        self.query_name = name
        self.cmd = cmd
        self.tx_data = tx_data  # HEX 字符串
        self.tx_fields = tx_fields or []
        self.rx_fields = rx_fields or []
        self.tx_data_len = tx_data_len
        self.rx_data_len = rx_data_len
        self.setFixedHeight(32)
        self.setMinimumWidth(80)
        self.setCursor(Qt.PointingHandCursor)
        self._drag_start_pos = None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start_pos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_start_pos and (event.pos() - self._drag_start_pos).manhattanLength() > 10:
            drag = QDrag(self)
            mime = QMimeData()
            mime.setText("button_drag")
            drag.setMimeData(mime)

            # 拖拽时显示按钮快照
            pixmap = self.grab()
            painter = QPainter(pixmap)
            painter.setOpacity(0.6)
            painter.end()
            drag.setPixmap(pixmap)

            drag.exec_(Qt.MoveAction)
            self._drag_start_pos = None
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_start_pos = None
        super().mouseReleaseEvent(event)


class ButtonEditDialog(QDialog):
    """按钮编辑对话框：选择命令模板、按字段填写 TX 数据."""

    def __init__(self, templates: list[dict], edit_data: dict | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑按钮" if edit_data else "添加按钮")
        self._templates = templates
        self._field_inputs: list[tuple[QLineEdit, QComboBox, int]] = []  # (输入框, 进制选择, 字节数)
        self._delete_clicked = False
        self._init_ui(edit_data)

    def _init_ui(self, edit_data: dict | None):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # 基本信息
        form = QFormLayout()

        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText("留空则使用命令名称")
        form.addRow("名称:", self.edit_name)

        self.combo_cmd = QComboBox()
        for t in self._templates:
            self.combo_cmd.addItem(f"{t['name']} (CMD=0x{t['cmd']})", t)
        form.addRow("命令:", self.combo_cmd)

        layout.addLayout(form)

        # TX 字段区域
        self.fields_group = QGroupBox("发送字段")
        self.fields_layout = QVBoxLayout(self.fields_group)
        layout.addWidget(self.fields_group, 1)

        # 连接信号
        self.combo_cmd.currentIndexChanged.connect(self._update_fields)

        # 初始化字段
        self._update_fields()

        # 填充编辑数据
        if edit_data:
            self.edit_name.setText(edit_data.get("name", ""))
            for i, t in enumerate(self._templates):
                if t["cmd"] == edit_data.get("cmd", ""):
                    self.combo_cmd.setCurrentIndex(i)
                    break
            # 填充字段值
            self._fill_field_values(edit_data.get("tx_data", ""))

        # 按钮
        btn_layout = QHBoxLayout()

        # 仅编辑模式显示删除按钮
        if edit_data:
            btn_delete = QPushButton("删除")
            btn_delete.clicked.connect(self._on_delete)
            btn_layout.addWidget(btn_delete)

        btn_layout.addStretch()

        btn_ok = QPushButton("确定")
        btn_ok.clicked.connect(self.accept)
        btn_layout.addWidget(btn_ok)

        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        layout.addLayout(btn_layout)

    def showEvent(self, event):
        """对话框显示后调整大小."""
        super().showEvent(event)
        QTimer.singleShot(0, self._adjust_size)

    def _adjust_size(self):
        """根据内容调整对话框大小."""
        hint = self.sizeHint()
        screen = self.screen()
        if screen:
            max_h = int(screen.availableGeometry().height() * 0.6)
            hint.setHeight(min(hint.height(), max_h))
        self.resize(max(hint.width(), 420), max(hint.height(), 200))

    def _on_delete(self):
        """删除按钮点击."""
        self._delete_clicked = True
        self.reject()

    def _update_fields(self):
        """根据选择的命令更新字段输入框."""
        # 清空旧的字段输入
        self._field_inputs.clear()
        while self.fields_layout.count():
            child = self.fields_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        idx = self.combo_cmd.currentIndex()
        if idx < 0 or idx >= len(self._templates):
            return

        template = self._templates[idx]
        tx_fields = template.get("tx_fields", [])

        if not tx_fields:
            lbl = QLabel("该命令无 TX 字段")
            lbl.setStyleSheet("color: #888; font-style: italic;")
            self.fields_layout.addWidget(lbl)
            return

        for f in tx_fields:
            name = f.get("name", "Reserve")
            size = f.get("size", 0)
            if size < 1:
                continue

            row = QHBoxLayout()

            # 字段名称
            lbl = QLabel(f"{name}:")
            lbl.setFixedWidth(80)
            row.addWidget(lbl)

            # 输入框
            edit = QLineEdit()
            edit.setPlaceholderText("0")
            row.addWidget(edit, 1)

            # 进制选择
            combo_base = QComboBox()
            combo_base.addItems(["DEC", "HEX"])
            combo_base.setFixedWidth(70)
            row.addWidget(combo_base)

            self.fields_layout.addLayout(row)
            self._field_inputs.append((edit, combo_base, size))

    def _fill_field_values(self, tx_data: str):
        """用已有的 TX 数据填充字段输入框."""
        if not tx_data or not self._field_inputs:
            return

        try:
            data_bytes = bytes.fromhex(tx_data.replace(" ", ""))
        except ValueError:
            return

        offset = 0
        for edit, combo_base, size in self._field_inputs:
            if offset >= len(data_bytes):
                break
            value = data_bytes[offset: offset + size]
            offset += size

            # 默认用十进制显示
            int_val = int.from_bytes(value, "big")
            edit.setText(str(int_val))
            combo_base.setCurrentText("DEC")

    def get_result(self) -> dict | None:
        """返回按钮配置."""
        name = self.edit_name.text().strip()
        cmd = self.combo_cmd.currentData()

        if not cmd:
            return None

        # 名称为空时使用命令名称
        if not name:
            name = cmd.get("name", "")

        # 从字段输入构建 TX 数据
        tx_data = ""
        if self._field_inputs:
            data_bytes = b""
            for edit, combo_base, size in self._field_inputs:
                text = edit.text().strip()
                if not text:
                    text = "0"
                try:
                    if combo_base.currentText() == "HEX":
                        val = int(text, 16)
                    else:
                        val = int(text)
                    data_bytes += val.to_bytes(size, "big")
                except (ValueError, OverflowError):
                    data_bytes += b"\x00" * size
            tx_data = data_bytes.hex().upper()
        else:
            # 没有字段定义，使用旧的 tx_data 逻辑
            tx_data = ""
            tx_size = cmd.get("tx_data_len", 0)
            if tx_size > 0:
                tx_data = "00" * tx_size

        return {
            "name": name,
            "cmd": cmd["cmd"],
            "tx_data": tx_data,
            "tx_fields": cmd.get("tx_fields", []),
            "rx_fields": cmd.get("rx_fields", []),
            "tx_data_len": cmd.get("tx_data_len", 0),
            "rx_data_len": cmd.get("rx_data_len", 0),
        }


class ProtocolPanel(QWidget):
    """命令调试面板.

    按钮实例从命令模板创建，仅限查询命令。
    上报命令从命令模板自动识别。

    信号:
        send_frame_requested(int, bytes): 请求发送协议帧
        buttons_changed(list): 按钮列表变更
        commands_changed(list): 命令模板被编辑器修改
        protocol_config_changed(object): 协议配置被导入修改
    """

    send_frame_requested = Signal(int, bytes)
    buttons_changed = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._query_buttons: list[QueryButton] = []
        self._command_templates: list[dict] = []  # 命令模板（全集）
        self._protocol_config = None
        self._protocol = None
        self._query_timeout_ms = 3000

        self._pending_queries: list[PendingQuery] = []

        self._init_ui()

    def _init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(4)

        # ========== 左侧: 按钮区域 ==========
        left_panel = QWidget()
        left_panel.setFixedWidth(200)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(4, 4, 4, 4)

        header = QHBoxLayout()
        header.addWidget(QLabel("调试命令"))
        header.addStretch()

        btn_add = QPushButton("+ 添加")
        btn_add.setFixedWidth(60)
        btn_add.clicked.connect(self._add_button)
        header.addWidget(btn_add)

        left_layout.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; }")

        self._button_container = QWidget()
        self._button_container.setAcceptDrops(True)
        self._button_container.dragEnterEvent = self._container_drag_enter
        self._button_container.dropEvent = self._container_drop
        self._button_layout = QVBoxLayout(self._button_container)
        self._button_layout.setAlignment(Qt.AlignTop)
        self._button_layout.setSpacing(2)

        scroll.setWidget(self._button_container)
        left_layout.addWidget(scroll)

        main_layout.addWidget(left_panel)

        # ========== 右侧: 日志 ==========
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(4, 4, 4, 4)

        ctrl_layout = QHBoxLayout()

        # 字段显示进制切换
        self._field_base = "DEC"  # HEX, DEC, BIN
        self.btn_base = QPushButton("字段显示: DEC")
        self.btn_base.setFixedWidth(100)
        self.btn_base.clicked.connect(self._toggle_field_base)
        ctrl_layout.addWidget(self.btn_base)

        btn_clear = QPushButton("清空日志")
        btn_clear.clicked.connect(self._clear_log)
        ctrl_layout.addWidget(btn_clear)

        right_layout.addLayout(ctrl_layout)

        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setFont(QFont("Consolas", 10))
        self.txt_log.setStyleSheet("QTextEdit { background-color: #1e1e1e; color: #d4d4d4; }")
        right_layout.addWidget(self.txt_log)

        # 监听滚动条，到底部自动开启，向上滑自动关闭
        scrollbar = self.txt_log.verticalScrollBar()
        scrollbar.rangeChanged.connect(self._on_scroll_range_changed)
        scrollbar.valueChanged.connect(self._on_scroll_value_changed)

        stats_layout = QHBoxLayout()
        self.lbl_stats = QLabel("查询: 0 | 响应: 0 | 上报: 0 | 超时: 0")
        self.lbl_stats.setStyleSheet("color: #6B9BBF; font-weight: bold;")
        stats_layout.addWidget(self.lbl_stats)
        stats_layout.addStretch()
        right_layout.addLayout(stats_layout)

        main_layout.addWidget(right_panel, 1)

        self._count_query = 0
        self._count_response = 0
        self._count_report = 0
        self._count_timeout = 0
        self._auto_scroll = True
        self._user_scrolling = False  # 用户是否主动滚动中

    def _on_scroll_value_changed(self, value: int):
        """滚动条位置变化，判断是否在底部."""
        scrollbar = self.txt_log.verticalScrollBar()
        self._auto_scroll = (value >= scrollbar.maximum())
        self._user_scrolling = not self._auto_scroll

    def _on_scroll_range_changed(self, min_val: int, max_val: int):
        """滚动条范围变化（新内容加入），如果在底部则自动滚到底."""
        if self._auto_scroll:
            self.txt_log.verticalScrollBar().setValue(max_val)

    def _toggle_field_base(self):
        """切换字段显示进制."""
        bases = ["HEX", "DEC", "BIN"]
        idx = bases.index(self._field_base)
        self._field_base = bases[(idx + 1) % len(bases)]
        self.btn_base.setText(f"字段显示: {self._field_base}")

    # ========== 拖拽排序 ==========

    def _container_drag_enter(self, event):
        if event.mimeData().hasText() and event.mimeData().text() == "button_drag":
            event.acceptProposedAction()

    def _container_drop(self, event):
        """处理按钮拖拽放下，交换位置."""
        source = event.source()
        if not isinstance(source, QueryButton):
            return

        # 找到鼠标位置下方的目标按钮
        target = self._find_button_at(event.pos())
        if target and target is not source:
            self._swap_buttons(source, target)
            self.buttons_changed.emit(self._collect_buttons())

        event.acceptProposedAction()

    def _find_button_at(self, pos: QPoint) -> QueryButton | None:
        """查找指定位置的按钮."""
        widget = self._button_container.childAt(pos)
        while widget and not isinstance(widget, QueryButton):
            widget = widget.parent()
        return widget if isinstance(widget, QueryButton) else None

    def _swap_buttons(self, btn_a: QueryButton, btn_b: QueryButton):
        """交换两个按钮在布局中的位置."""
        idx_a = self._query_buttons.index(btn_a)
        idx_b = self._query_buttons.index(btn_b)

        # 交换列表位置
        self._query_buttons[idx_a], self._query_buttons[idx_b] = \
            self._query_buttons[idx_b], self._query_buttons[idx_a]

        # 重建布局
        for btn in self._query_buttons:
            self._button_layout.removeWidget(btn)
        for btn in self._query_buttons:
            self._button_layout.addWidget(btn)

    # ========== 公开接口 ==========

    def set_protocol_config(self, config):
        self._protocol_config = config
        self._query_timeout_ms = config.query_timeout_ms

    def set_protocol(self, protocol):
        self._protocol = protocol

    def set_command_templates(self, templates: list[dict]):
        """设置命令模板（由 MainWindow 调用）."""
        self._command_templates = templates

    def load_buttons(self, buttons: list[dict]):
        """加载按钮实例列表（由 MainWindow 启动时调用）."""
        for btn in self._query_buttons[:]:
            self._button_layout.removeWidget(btn)
            btn.deleteLater()
        self._query_buttons.clear()

        for item in buttons:
            self._create_button_from_config(item)

    # ========== 按钮管理 ==========

    def _get_query_templates(self) -> list[dict]:
        """获取所有查询类型的命令模板."""
        return [t for t in self._command_templates if t.get("type") == "查询"]

    def _add_button(self):
        """添加按钮."""
        templates = self._get_query_templates()
        if not templates:
            return

        dialog = ButtonEditDialog(templates, parent=self)
        if dialog.exec() != ButtonEditDialog.Accepted:
            return

        result = dialog.get_result()
        if result:
            self._create_button_from_config(result)
            self.buttons_changed.emit(self._collect_buttons())

    def _create_button_from_config(self, config: dict):
        """从配置创建按钮."""
        btn = QueryButton(
            name=config.get("name", ""),
            cmd=config.get("cmd", ""),
            tx_data=config.get("tx_data", ""),
            tx_fields=config.get("tx_fields", []),
            rx_fields=config.get("rx_fields", []),
            tx_data_len=config.get("tx_data_len", 0),
            rx_data_len=config.get("rx_data_len", 0),
        )

        tip = f"CMD: 0x{btn.cmd}\nTX: {btn.tx_data or '(空)'}"
        if btn.tx_fields:
            parts = [f"{f['name']}" for f in btn.tx_fields if f.get('size', 0) >= 1]
            if parts:
                tip += f"\nTX字段: {', '.join(parts)}"
        btn.setToolTip(tip)
        btn.clicked.connect(lambda _, b=btn: self._on_query_clicked(b))
        btn.setContextMenuPolicy(Qt.CustomContextMenu)
        btn.customContextMenuRequested.connect(lambda pos, b=btn: self._edit_button(b))

        self._button_layout.addWidget(btn)
        self._query_buttons.append(btn)

    def _edit_button(self, btn: QueryButton):
        """右键编辑按钮."""
        templates = self._get_query_templates()
        edit_data = {
            "name": btn.query_name,
            "cmd": btn.cmd,
            "tx_data": btn.tx_data,
        }
        dialog = ButtonEditDialog(templates, edit_data, self)
        result = dialog.exec()

        # 删除按钮
        if result == ButtonEditDialog.Rejected and dialog._delete_clicked:
            self._delete_button(btn)
            return

        if result != ButtonEditDialog.Accepted:
            return

        result_data = dialog.get_result()
        if result_data:
            btn.query_name = result_data["name"]
            btn.setText(result_data["name"])
            btn.cmd = result_data["cmd"]
            btn.tx_data = result_data["tx_data"]
            btn.tx_fields = result_data.get("tx_fields", [])
            btn.rx_fields = result_data.get("rx_fields", [])
            btn.tx_data_len = result_data.get("tx_data_len", 0)
            btn.rx_data_len = result_data.get("rx_data_len", 0)

            tip = f"CMD: 0x{btn.cmd}\nTX: {btn.tx_data or '(空)'}"
            if btn.tx_fields:
                parts = [f"{f['name']}" for f in btn.tx_fields if f.get('size', 0) >= 1]
                if parts:
                    tip += f"\nTX字段: {', '.join(parts)}"
            btn.setToolTip(tip)

            self.buttons_changed.emit(self._collect_buttons())

    def _delete_button(self, btn: QueryButton):
        """删除指定按钮."""
        self._query_buttons.remove(btn)
        self._button_layout.removeWidget(btn)
        btn.deleteLater()
        self.buttons_changed.emit(self._collect_buttons())

    def _collect_buttons(self) -> list[dict]:
        """收集当前按钮配置."""
        buttons = []
        for btn in self._query_buttons:
            buttons.append({
                "name": btn.query_name,
                "cmd": btn.cmd,
                "tx_data": btn.tx_data,
                "tx_fields": btn.tx_fields,
                "rx_fields": btn.rx_fields,
                "tx_data_len": btn.tx_data_len,
                "rx_data_len": btn.rx_data_len,
            })
        return buttons

    # ========== 收发逻辑 ==========

    def _on_query_clicked(self, btn: QueryButton):
        try:
            cmd = int(btn.cmd, 16) if btn.cmd.startswith("0x") else int(btn.cmd, 16)
        except ValueError:
            self._append_log("ERROR", f"命令格式错误: {btn.cmd}", QColor("#f44336"))
            return

        data_bytes = b""
        if btn.tx_data:
            try:
                data_bytes = bytes.fromhex(btn.tx_data.replace(" ", ""))
            except ValueError:
                self._append_log("ERROR", f"数据格式错误: {btn.tx_data}", QColor("#f44336"))
                return

        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda c=cmd, n=btn.query_name: self._on_query_timeout(c, n))
        timer.start(self._query_timeout_ms)
        self._pending_queries.append(PendingQuery(
            cmd=cmd, name=btn.query_name, btn=btn, timer=timer,
        ))

        self._count_query += 1
        self._update_stats()

        frame_bytes = self._protocol.encode(cmd, data_bytes) if self._protocol else b""
        frame_hex = frame_bytes.hex(" ").upper()

        tx_warn = ""
        if btn.tx_data_len > 0 and len(data_bytes) != btn.tx_data_len:
            tx_warn = f" ⚠长度不匹配"

        # 构建完整消息
        msg = f"{btn.query_name} │ CMD=0x{cmd:02X} │ DATA={data_bytes.hex(' ').upper() or '空'}{tx_warn}"

        # 主消息
        self._append_log("TX", msg, QColor("#FFA500") if tx_warn else QColor("#4FC3F7"))

        # 字段解析（在 RAW 数据之前）
        if btn.tx_fields:
            fields_text = self._format_fields(data_bytes, btn.tx_fields)
            if fields_text:
                self._append_log("", f"  └─ {fields_text}", QColor("#888"))
            else:
                field_names = [f"{f['name']}:{f.get('size', 0)}B" for f in btn.tx_fields if f.get('size', 0) >= 1]
                if field_names:
                    self._append_log("", f"  └─ {' │ '.join(field_names)} (数据为空)", QColor("#888"))
        elif data_bytes:
            self._append_log("", f"  └─ DATA={data_bytes.hex(' ').upper()}", QColor("#888"))

        # RAW 数据
        if frame_hex:
            self._append_raw(frame_hex)

        self.send_frame_requested.emit(cmd, data_bytes)

    def append_rx_frame(self, frame):
        pending = self._find_pending(frame.cmd)

        if pending is not None:
            pending.timer.stop()
            self._pending_queries.remove(pending)
            self._count_response += 1

            warn = self._check_rx_data_len(pending.btn, len(frame.data))
            warn_str = " ⚠长度不匹配" if warn else ""
            msg = f"{pending.name} │ CMD=0x{frame.cmd:02X} │ DATA={frame.data_hex}{warn_str}"

            # 主消息
            self._append_log("RX", msg, QColor("#FFA500") if warn else QColor("#81C784"))

            # 字段解析
            if pending.btn.rx_fields:
                fields_text = self._format_fields(frame.data, pending.btn.rx_fields)
                if fields_text:
                    self._append_log("", f"  └─ {fields_text}", QColor("#888"))

            # RAW 数据
            if frame.raw_hex:
                self._append_raw(frame.raw_hex)
        else:
            report_name, report_template = self._find_report(frame.cmd)
            self._count_report += 1
            rx_fields = report_template.get("rx_fields", []) if report_template else []
            rx_data_len = report_template.get("rx_data_len", 0) if report_template else 0

            warn = ""
            if rx_data_len > 0 and len(frame.data) != rx_data_len:
                warn = " ⚠长度不匹配"

            display_name = report_name or f"未知"
            msg = f"{display_name} │ CMD=0x{frame.cmd:02X} │ DATA={frame.data_hex}{warn}"

            # 主消息
            self._append_log("上报", msg, QColor("#FFA500") if warn else QColor("#FF9800"))

            # 字段解析
            if rx_fields:
                fields_text = self._format_fields(frame.data, rx_fields)
                if fields_text:
                    self._append_log("", f"  └─ {fields_text}", QColor("#888"))

            # RAW 数据
            if frame.raw_hex:
                self._append_raw(frame.raw_hex)

        self._update_stats()

    def _find_pending(self, cmd: int) -> PendingQuery | None:
        for pq in self._pending_queries:
            if pq.cmd == cmd:
                return pq
        return None

    def _find_report(self, cmd: int) -> tuple[str | None, dict | None]:
        """从命令模板中查找匹配的上报命令."""
        for t in self._command_templates:
            if t.get("type") != "上报":
                continue
            try:
                report_cmd = int(t["cmd"], 16) if t["cmd"].startswith("0x") else int(t["cmd"], 16)
                if report_cmd == cmd:
                    return t.get("name"), t
            except (ValueError, KeyError):
                continue
        return None, None

    @staticmethod
    def _check_rx_data_len(btn: QueryButton | None, actual_len: int) -> str:
        if btn is None or btn.rx_data_len <= 0:
            return ""
        if actual_len != btn.rx_data_len:
            return f" [接收长度不匹配: 期望{btn.rx_data_len} 实际{actual_len}]"
        return ""

    def _format_fields(self, data: bytes, fields: list[dict]) -> str:
        """格式化字段数据，返回紧凑的字段显示."""
        if not fields or not data:
            return ""

        parts = []
        offset = 0
        for field in fields:
            name = field.get("name", "Reserve")
            size = field.get("size", 0)

            if size <= 0:
                continue

            value = data[offset: offset + size]
            offset += size

            if offset > len(data):
                parts.append(f"{name}:{self._format_value(value)}?")
                break

            parts.append(f"{name}:{self._format_value(value)}")

            if offset >= len(data):
                break

        return " │ ".join(parts) if parts else ""

    def _format_value(self, value: bytes) -> str:
        """根据当前进制格式化字节值."""
        if self._field_base == "HEX":
            return value.hex().upper()
        elif self._field_base == "DEC":
            return str(int.from_bytes(value, "big"))
        elif self._field_base == "BIN":
            return bin(int.from_bytes(value, "big"))[2:].zfill(len(value) * 8)
        return value.hex().upper()

    def _on_query_timeout(self, cmd: int, name: str):
        self._pending_queries = [pq for pq in self._pending_queries if not (pq.cmd == cmd and pq.name == name)]
        self._count_timeout += 1
        self._append_log(
            "超时",
            f"{name} │ CMD=0x{cmd:02X} │ 无响应",
            QColor("#f44336"),
        )
        self._update_stats()

    # ========== 日志 ==========

    def _append_log(self, direction: str, message: str, color: QColor):
        cursor = self.txt_log.textCursor()
        cursor.movePosition(QTextCursor.End)

        if direction:
            # 主消息：带时间戳和方向标签
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            fmt_time = QTextCharFormat()
            fmt_time.setForeground(QColor("#666"))
            cursor.insertText(f"[{timestamp}] ", fmt_time)

            fmt_dir = QTextCharFormat()
            fmt_dir.setForeground(color)
            fmt_dir.setFontWeight(QFont.Bold)
            cursor.insertText(f"{direction:4s} ", fmt_dir)

            fmt_msg = QTextCharFormat()
            fmt_msg.setForeground(QColor("#d4d4d4"))
            cursor.insertText(message, fmt_msg)
        else:
            # 子消息：缩进对齐命令名称（[HH:MM:SS.mmm] TX   = 21字符）
            fmt_msg = QTextCharFormat()
            fmt_msg.setForeground(color)
            cursor.insertText(f"                     {message}", fmt_msg)

        cursor.insertText("\n")

    def _append_raw(self, raw_hex: str):
        """显示 RAW 数据行."""
        cursor = self.txt_log.textCursor()
        cursor.movePosition(QTextCursor.End)

        fmt_raw = QTextCharFormat()
        fmt_raw.setForeground(QColor("#555"))
        raw_display = raw_hex
        if len(raw_hex) > 60:
            raw_display = raw_hex[:60] + "..."
        cursor.insertText(f"                     {raw_display}\n", fmt_raw)

    def _update_stats(self):
        self.lbl_stats.setText(
            f"查询: {self._count_query} | 响应: {self._count_response} | "
            f"上报: {self._count_report} | 超时: {self._count_timeout}"
        )

    def _clear_log(self):
        self.txt_log.clear()
        self._count_query = 0
        self._count_response = 0
        self._count_report = 0
        self._count_timeout = 0
        self._update_stats()
