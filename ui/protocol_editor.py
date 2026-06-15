"""协议命令清单编辑器对话框."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget,
    QTableWidgetItem, QPushButton, QStyledItemDelegate, QLineEdit,
    QAbstractItemView, QHeaderView, QLabel, QComboBox, QStyle, QApplication,
)
from PySide6.QtCore import Qt, QModelIndex
from PySide6.QtGui import QPainter

from core.protocol_config import ProtocolConfig


CMD_TYPE_QUERY = "下发"
CMD_TYPE_REPORT = "上报"
CMD_TYPES = [CMD_TYPE_QUERY, CMD_TYPE_REPORT]


class _EditorDelegate(QStyledItemDelegate):
    """显示加左边距，编辑时不透明背景，避免重影."""

    MARGIN = 10

    def paint(self, painter: QPainter, option, index: QModelIndex):
        opt = option
        self.initStyleOption(opt, index)
        opt.text = ""  # 清空文字，让基类只画背景
        widget = option.widget
        style = widget.style() if widget else QApplication.style()
        style.drawPrimitive(QStyle.PE_PanelItemViewItem, opt, painter, widget)
        text = index.data(Qt.DisplayRole) or ""
        if text:
            text_rect = option.rect.adjusted(self.MARGIN, 0, 0, 0)
            painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, text)

    def sizeHint(self, option, index):
        hint = super().sizeHint(option, index)
        hint.setWidth(hint.width() + self.MARGIN)
        return hint

    def createEditor(self, parent, option, index):  # noqa: ARG002
        editor = QLineEdit(parent)
        editor.setAutoFillBackground(True)
        editor.setTextMargins(self.MARGIN, 0, 0, 0)
        return editor


COL_TYPE = 1
COL_TX_DATA = 3
COL_RX_DATA = 4


def parse_fields_text(text: str) -> list[dict]:
    """解析字段文本 '温度:2, 湿度:2' → [{"name": "温度", "size": 2}, ...]"""
    fields = []
    if not text or not text.strip() or text.strip() == "-":
        return fields
    for part in text.replace("，", ",").replace("|", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            name, size_str = part.split(":", 1)
            name = name.strip()
            try:
                size = int(size_str.strip().replace("B", "").replace("b", ""))
            except ValueError:
                size = 0
        else:
            name = part
            size = 0
        if size >= 1:
            fields.append({"name": name, "size": size})
    return fields


def fields_to_text(fields: list[dict]) -> str:
    """字段列表 → 显示文本（size 必须 >=1，否则跳过）."""
    if not fields:
        return ""
    parts = []
    for f in fields:
        name = f.get("name", "预留")
        size = f.get("size", 0)
        if size >= 1:
            parts.append(f"{name}:{size}B")
    return " | ".join(parts)


def calc_fields_size(fields: list[dict]) -> int:
    """计算字段总大小."""
    return sum(f.get("size", 0) for f in fields if f.get("size", 0) > 0)


class FieldsEditDialog(QDialog):
    """字段编辑弹窗（编辑单个数据列的字段定义）."""

    def __init__(self, title: str, fields: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self._init_ui(fields)
        self._auto_fit()

    def _init_ui(self, fields: list[dict]):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        hint = QLabel("双击单元格编辑，字节最小为 1")
        hint.setStyleSheet("color: #888; font-style: italic; font-size: 11px;")
        layout.addWidget(hint)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["名称", "字节"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setMinimumSectionSize(50)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.table.setItemDelegate(_EditorDelegate(self.table))

        self.table.cellChanged.connect(self._on_cell_changed)
        layout.addWidget(self.table)

        for f in fields:
            self._append_row(f.get("name", "预留"), f.get("size", 0))

        # 底部工具栏：左侧操作按钮，右侧确定取消
        bottom = QHBoxLayout()

        btn_add = QPushButton("+ 添加")
        btn_add.clicked.connect(self._add_row)
        bottom.addWidget(btn_add)

        btn_del = QPushButton("删除")
        btn_del.clicked.connect(self._del_row)
        bottom.addWidget(btn_del)

        btn_up = QPushButton("↑")
        btn_up.setFixedWidth(36)
        btn_up.clicked.connect(self._move_up)
        bottom.addWidget(btn_up)

        btn_down = QPushButton("↓")
        btn_down.setFixedWidth(36)
        btn_down.clicked.connect(self._move_down)
        bottom.addWidget(btn_down)

        bottom.addStretch()

        btn_ok = QPushButton("确定")
        btn_ok.clicked.connect(self.accept)
        bottom.addWidget(btn_ok)

        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        bottom.addWidget(btn_cancel)

        layout.addLayout(bottom)

    def _on_cell_changed(self):
        self.table.resizeColumnsToContents()
        self.table.viewport().update()

    def _auto_fit(self):
        """根据内容自适应列宽和窗口大小."""
        self.table.resizeColumnsToContents()

        header = self.table.horizontalHeader()
        total_cols = header.length() + self.table.verticalHeader().width() + 20
        row_h = self.table.verticalHeader().defaultSectionSize()
        visible_rows = max(self.table.rowCount(), 3)
        header_h = self.table.horizontalHeader().height()
        table_h = header_h + row_h * visible_rows + 10

        ideal_w = max(total_cols, 380)
        ideal_h = table_h + 110

        screen = self.screen()
        if screen:
            ideal_w = min(ideal_w, int(screen.availableGeometry().width() * 0.7))
            ideal_h = min(ideal_h, int(screen.availableGeometry().height() * 0.7))

        self.resize(ideal_w, ideal_h)
        self.setMinimumSize(340, 240)

    def _append_row(self, name: str = "预留", size: int = 1):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(name))
        self.table.setItem(row, 1, QTableWidgetItem(str(size)))

    def _add_row(self):
        self._append_row("预留", 1)
        self.table.setCurrentCell(self.table.rowCount() - 1, 0)
        self.table.editItem(self.table.item(self.table.rowCount() - 1, 0))

    def _del_row(self):
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)

    def _move_up(self):
        row = self.table.currentRow()
        if row <= 0:
            return
        self._swap(row, row - 1)
        self.table.setCurrentCell(row - 1, 0)

    def _move_down(self):
        row = self.table.currentRow()
        if row < 0 or row >= self.table.rowCount() - 1:
            return
        self._swap(row, row + 1)
        self.table.setCurrentCell(row + 1, 0)

    def _swap(self, a: int, b: int):
        for col in range(2):
            ia = self.table.takeItem(a, col)
            ib = self.table.takeItem(b, col)
            self.table.setItem(a, col, ib)
            self.table.setItem(b, col, ia)

    def get_fields(self) -> list[dict]:
        fields = []
        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 0)
            size_item = self.table.item(row, 1)
            name = name_item.text().strip() if name_item else "预留"
            try:
                size = int(size_item.text().strip()) if size_item else 0
            except ValueError:
                size = 0
            if size >= 1:
                fields.append({"name": name, "size": size})
        return fields


class ProtocolEditorDialog(QDialog):
    """协议命令清单编辑器.

    列顺序: 名称 | 类型 | 命令(HEX) | 发送数据 | 接收数据

    发送数据/接收数据列显示字段摘要，双击弹窗编辑。
    查询命令: 两列都可编辑
    上报命令: 发送数据显示 "-"，接收数据可编辑
    """

    def __init__(self, commands: list[dict], protocol_config: ProtocolConfig | None = None,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("协议命令清单编辑")
        self.setMinimumSize(620, 320)
        self._protocol_config = protocol_config or ProtocolConfig()
        self._init_ui(commands)
        self._auto_fit()

    def _init_ui(self, commands: list[dict]):
        self._current_combo: QComboBox | None = None

        layout = QVBoxLayout(self)

        title = QLabel("双击「发送数据」或「接收数据」列可编辑字段定义")
        title.setStyleSheet("color: #888; font-style: italic; padding: 4px 0;")
        layout.addWidget(title)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["名称", "类型", "命令 (HEX)", "发送数据", "接收数据"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setMinimumSectionSize(50)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.table.setItemDelegate(_EditorDelegate(self.table))

        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        self.table.cellChanged.connect(self._on_cell_changed)

        layout.addWidget(self.table)

        # 底部工具栏：左侧操作按钮，右侧确定取消
        bottom = QHBoxLayout()

        btn_add_query = QPushButton("+ 查询命令")
        btn_add_query.clicked.connect(lambda: self._add_row(CMD_TYPE_QUERY))
        bottom.addWidget(btn_add_query)

        btn_add_report = QPushButton("+ 上报命令")
        btn_add_report.clicked.connect(lambda: self._add_row(CMD_TYPE_REPORT))
        bottom.addWidget(btn_add_report)

        btn_copy = QPushButton("复制")
        btn_copy.clicked.connect(self._copy_row)
        bottom.addWidget(btn_copy)

        btn_delete = QPushButton("删除")
        btn_delete.clicked.connect(self._delete_rows)
        bottom.addWidget(btn_delete)

        btn_up = QPushButton("↑")
        btn_up.setFixedWidth(36)
        btn_up.clicked.connect(self._move_up)
        bottom.addWidget(btn_up)

        btn_down = QPushButton("↓")
        btn_down.setFixedWidth(36)
        btn_down.clicked.connect(self._move_down)
        bottom.addWidget(btn_down)

        bottom.addStretch()

        btn_ok = QPushButton("确定")
        btn_ok.clicked.connect(self.accept)
        bottom.addWidget(btn_ok)

        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        bottom.addWidget(btn_cancel)

        layout.addLayout(bottom)

        self._load_commands(commands)

    def _on_cell_changed(self):
        self.table.resizeColumnsToContents()
        self.table.viewport().update()

    def _load_commands(self, commands: list[dict]):
        for item in commands:
            cmd_type = item.get("type", CMD_TYPE_QUERY)
            tx_fields = item.get("tx_fields", [])
            rx_fields = item.get("rx_fields", item.get("fields", []))
            self._append_row(item.get("name", ""), item.get("cmd", ""), cmd_type, tx_fields, rx_fields)

    def _auto_fit(self):
        """根据内容自适应列宽和窗口大小."""
        self.table.resizeColumnsToContents()

        header = self.table.horizontalHeader()
        total_cols = header.length() + self.table.verticalHeader().width() + 20

        row_h = self.table.verticalHeader().defaultSectionSize()
        header_h = self.table.horizontalHeader().height()
        visible_rows = min(self.table.rowCount(), 15)
        table_h = header_h + row_h * max(visible_rows, 3) + 10

        ideal_w = max(total_cols, 700)
        ideal_h = table_h + 120  # 标题+工具栏+底部按钮

        screen = self.screen()
        if screen:
            max_w = int(screen.availableGeometry().width() * 0.85)
            max_h = int(screen.availableGeometry().height() * 0.85)
            ideal_w = min(ideal_w, max_w)
            ideal_h = min(ideal_h, max_h)

        self.resize(ideal_w, ideal_h)
        self.setMinimumSize(620, 320)

    def _on_cell_double_clicked(self, row: int, col: int):
        if col == COL_TYPE:
            self._open_type_combo(row)
        elif col == COL_TX_DATA:
            self._open_fields_editor(row, "tx")
        elif col == COL_RX_DATA:
            self._open_fields_editor(row, "rx")

    def _open_type_combo(self, row: int):
        # 清理上一次残留的 combo，防止重叠
        if self._current_combo is not None:
            self._current_combo.deleteLater()
            self._current_combo = None

        item = self.table.item(row, COL_TYPE)
        current = item.text() if item else CMD_TYPE_QUERY

        combo = QComboBox(self)
        self._current_combo = combo
        combo.addItems(CMD_TYPES)
        combo.setCurrentText(current)

        rect = self.table.visualRect(self.table.model().index(row, COL_TYPE))
        pos = self.table.viewport().mapToGlobal(rect.topLeft())
        combo.move(self.mapFromGlobal(pos))
        combo.resize(rect.width(), rect.height())
        combo.showPopup()

        def on_selected(text: str):
            old_type = self.table.item(row, COL_TYPE).text() if self.table.item(row, COL_TYPE) else ""
            new_item = QTableWidgetItem(text)
            new_item.setFlags(new_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, COL_TYPE, new_item)
            if old_type != text:
                self._update_row_for_type(row, text)
            if self._current_combo is combo:
                self._current_combo = None
            combo.deleteLater()

        combo.currentTextChanged.connect(on_selected)

    def _update_row_for_type(self, row: int, cmd_type: str):
        tx_item = self.table.item(row, COL_TX_DATA)
        if cmd_type == CMD_TYPE_REPORT:
            if tx_item:
                tx_item.setText("-")
        else:
            if tx_item:
                if tx_item.text() == "-":
                    tx_item.setText("预留")

    def _open_fields_editor(self, row: int, direction: str):
        """打开字段编辑弹窗."""
        cmd_type = self.table.item(row, COL_TYPE).text() if self.table.item(row, COL_TYPE) else CMD_TYPE_QUERY
        cmd_name = self.table.item(row, 0).text() if self.table.item(row, 0) else f"行{row}"

        if direction == "tx" and cmd_type == CMD_TYPE_REPORT:
            return  # 上报命令不允许编辑发送数据

        col = COL_TX_DATA if direction == "tx" else COL_RX_DATA
        item = self.table.item(row, col)
        current_text = item.text() if item else ""

        if direction == "tx":
            title = f"发送数据字段: {cmd_name}"
        else:
            title = f"接收数据字段: {cmd_name}"

        fields = parse_fields_text(current_text)
        dialog = FieldsEditDialog(title, fields, self)
        if dialog.exec() == FieldsEditDialog.Accepted:
            new_fields = dialog.get_fields()
            if item:
                item.setText(fields_to_text(new_fields))
            else:
                self.table.setItem(row, col, QTableWidgetItem(fields_to_text(new_fields)))

    def _append_row(self, name: str = "", cmd: str = "", cmd_type: str = CMD_TYPE_QUERY,
                    tx_fields: list[dict] | None = None, rx_fields: list[dict] | None = None):
        row = self.table.rowCount()
        self.table.insertRow(row)

        self.table.setItem(row, 0, QTableWidgetItem(name))
        type_item = QTableWidgetItem(cmd_type)
        type_item.setFlags(type_item.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(row, 1, type_item)
        self.table.setItem(row, 2, QTableWidgetItem(cmd))

        if cmd_type == CMD_TYPE_REPORT:
            tx_item = QTableWidgetItem("-")
            tx_item.setFlags(tx_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, COL_TX_DATA, tx_item)
        else:
            tx_item = QTableWidgetItem(fields_to_text(tx_fields or []))
            tx_item.setFlags(tx_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, COL_TX_DATA, tx_item)

        rx_item = QTableWidgetItem(fields_to_text(rx_fields or []))
        rx_item.setFlags(rx_item.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(row, COL_RX_DATA, rx_item)

    def _add_row(self, cmd_type: str = CMD_TYPE_QUERY):
        self._append_row("", "01", cmd_type, [], [])
        self.table.setCurrentCell(self.table.rowCount() - 1, 0)
        self.table.editItem(self.table.item(self.table.rowCount() - 1, 0))

    def _copy_row(self):
        """复制选中行."""
        row = self.table.currentRow()
        if row < 0:
            return

        name = self.table.item(row, 0)
        cmd_type = self.table.item(row, 1)
        cmd = self.table.item(row, 2)
        tx_item = self.table.item(row, COL_TX_DATA)
        rx_item = self.table.item(row, COL_RX_DATA)

        cmd_type_text = cmd_type.text() if cmd_type else CMD_TYPE_QUERY
        if cmd_type_text == CMD_TYPE_REPORT:
            tx_fields = []
        else:
            tx_fields = parse_fields_text(tx_item.text() if tx_item else "")
        rx_fields = parse_fields_text(rx_item.text() if rx_item else "")

        self._append_row(
            (name.text() if name else "") + " 副本",
            cmd.text() if cmd else "",
            cmd_type_text,
            tx_fields,
            rx_fields,
        )
        self.table.setCurrentCell(self.table.rowCount() - 1, 0)

    def _delete_rows(self):
        rows = sorted(set(idx.row() for idx in self.table.selectedIndexes()), reverse=True)
        if not rows:
            return
        for row in rows:
            self.table.removeRow(row)

    def _move_up(self):
        row = self.table.currentRow()
        if row <= 0:
            return
        self._swap_rows(row, row - 1)
        self.table.setCurrentCell(row - 1, self.table.currentColumn())

    def _move_down(self):
        row = self.table.currentRow()
        if row < 0 or row >= self.table.rowCount() - 1:
            return
        self._swap_rows(row, row + 1)
        self.table.setCurrentCell(row + 1, self.table.currentColumn())

    def _swap_rows(self, row_a: int, row_b: int):
        for col in range(self.table.columnCount()):
            item_a = self.table.takeItem(row_a, col)
            item_b = self.table.takeItem(row_b, col)
            self.table.setItem(row_a, col, item_b)
            self.table.setItem(row_b, col, item_a)

    def get_protocol_config(self) -> ProtocolConfig:
        return self._protocol_config

    def get_commands(self) -> list[dict]:
        commands = []
        for row in range(self.table.rowCount()):
            name = self.table.item(row, 0)
            cmd_type = self.table.item(row, 1)
            cmd = self.table.item(row, 2)
            tx_item = self.table.item(row, COL_TX_DATA)
            rx_item = self.table.item(row, COL_RX_DATA)

            cmd_type_text = cmd_type.text().strip() if cmd_type else CMD_TYPE_QUERY

            if cmd_type_text == CMD_TYPE_REPORT:
                tx_fields = []
            else:
                tx_fields = parse_fields_text(tx_item.text() if tx_item else "")
            rx_fields = parse_fields_text(rx_item.text() if rx_item else "")

            commands.append({
                "name": name.text().strip() if name else "",
                "cmd": cmd.text().strip() if cmd else "",
                "type": cmd_type_text,
                "tx_fields": tx_fields,
                "rx_fields": rx_fields,
                "tx_data_len": calc_fields_size(tx_fields),
                "rx_data_len": calc_fields_size(rx_fields),
            })
        return commands
