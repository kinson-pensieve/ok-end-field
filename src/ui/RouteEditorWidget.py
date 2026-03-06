import json
import copy

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QStackedWidget, QListWidget, QListWidgetItem,
    QSizePolicy, QGroupBox, QLabel,
)
from qfluentwidgets import (
    PushButton, PrimaryPushButton, FluentIcon,
    LineEdit, ComboBox, SpinBox, DoubleSpinBox,
    TextEdit, BodyLabel, StrongBodyLabel, CaptionLabel, CheckBox,
)

from ok.gui.Communicate import communicate

DEST_TYPES = ["采集物", "矿物", "资源回收站", "送货", "仓储节点", "能量淤积点"]
KEY_OPTIONS = ["w", "a", "s", "d", "f", "space", "shift"]


def _action_summary(action):
    """生成动作的摘要文本（顺序与 Walker.execute 一致）"""
    parts = []
    if "sleep" in action:
        parts.append(f"等待 {action['sleep']}s")
    if "angle_x" in action:
        y = action.get("angle_y", 0)
        parts.append(f"视角 {action['angle_x']}°/{y}°")
    if "mouse_x" in action:
        y = action.get("mouse_y", 0)
        parts.append(f"鼠标 {action['mouse_x']}px/{y}px")
    if "key" in action:
        key = action["key"]
        dur = action.get("duration", 0)
        count = action.get("count", 1)
        key_str = f"[{','.join(key)}]" if isinstance(key, list) else key
        s = f"按键 {key_str} {dur}s"
        if count > 1:
            s += f" ×{count}"
        parts.append(s)
    if "button" in action:
        parts.append(f"点击 {action['button']}")
    text = " → ".join(parts) if parts else "(空动作)"
    after = action.get("after_sleep")
    if after:
        text += f" (+等待{after}s)"
    return text


def _node_summary(node):
    """生成滑索节点的摘要文本"""
    s = f"距离 {node.get('distance', 0)}"
    if "angle_x" in node or "angle_y" in node:
        ax = node.get("angle_x", 0)
        ay = node.get("angle_y", 0)
        s += f" 视角{ax}°/{ay}°"
    return s


def _step_summary(step):
    """生成步骤的摘要文本"""
    t = step.get("type", "")
    if t == "walk":
        n = len(step.get("actions", []))
        return f"步行 ({n}个动作)"
    elif t == "zipline":
        n = len(step.get("nodes", []))
        return f"滑索 ({n}个节点)"
    return str(step)


class RouteEditorWidget(QWidget):
    """路线编辑器，支持 UI 和 JSON 两种编辑模式"""

    route_saved = Signal()
    route_deleted = Signal()

    def __init__(self, task):
        super().__init__()
        self.task = task
        self.store = task.store
        self.teleporter = task.teleporter
        self._route = {}  # 当前编辑的路线数据
        self._updating = False  # 防止循环更新

        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(6)

        # 模式切换按钮
        self._mode_btn = PushButton("切换JSON模式")
        self._mode_btn.clicked.connect(self._toggle_mode)
        main_layout.addWidget(self._mode_btn)

        # 堆叠 widget：UI 模式 / JSON 模式
        self._stack = QStackedWidget()
        main_layout.addWidget(self._stack, 1)

        # === UI 模式 ===
        ui_widget = QWidget()
        ui_layout = QVBoxLayout(ui_widget)
        ui_layout.setContentsMargins(0, 0, 0, 0)
        ui_layout.setSpacing(8)

        # QGroupBox 标题样式（白色加粗，深色背景下可见）
        group_style = "QGroupBox { color: white; font-weight: bold; }"

        # 基本信息
        info_group = QGroupBox("基本信息")
        info_group.setStyleSheet(group_style)
        info_form = QFormLayout(info_group)
        info_form.setSpacing(6)

        self._id_label = CaptionLabel("")
        info_form.addRow(StrongBodyLabel("ID:"), self._id_label)

        self._name_edit = LineEdit()
        self._name_edit.setPlaceholderText("目的地名称")
        info_form.addRow(StrongBodyLabel("名称:"), self._name_edit)

        self._type_combo = ComboBox()
        self._type_combo.addItems(DEST_TYPES)
        info_form.addRow(StrongBodyLabel("类型:"), self._type_combo)

        self._area_edit = LineEdit()
        self._area_edit.setPlaceholderText("区域名称")
        info_form.addRow(StrongBodyLabel("区域:"), self._area_edit)

        self._tp_combo = ComboBox()
        self._tp_combo.addItem("无")
        for tp in self.teleporter.teleport_points:
            name = tp.get("name", "")
            world = tp.get("world", "")
            area = tp.get("area", "")
            region = tp.get("region", "")
            if world == "帝江号":
                display = f"[帝江号] {name}"
            elif area:
                display = f"[{area}] {name}"
            elif region:
                display = f"[{region}] {name}"
            else:
                display = name
            self._tp_combo.addItem(display, userData=name)
        info_form.addRow(StrongBodyLabel("传送点:"), self._tp_combo)

        ui_layout.addWidget(info_group)

        # 步骤列表
        steps_group = QGroupBox("步骤")
        steps_group.setStyleSheet(group_style)
        steps_layout = QVBoxLayout(steps_group)
        steps_layout.setSpacing(4)

        self._steps_list = QListWidget()
        self._steps_list.setMaximumHeight(120)
        self._steps_list.currentRowChanged.connect(self._on_step_selected)
        steps_layout.addWidget(self._steps_list)

        steps_btn_layout = QHBoxLayout()
        btn_add_walk = PushButton("+步行")
        btn_add_walk.clicked.connect(lambda: self._add_step("walk"))
        btn_add_zipline = PushButton("+滑索")
        btn_add_zipline.clicked.connect(lambda: self._add_step("zipline"))
        btn_del_step = PushButton(FluentIcon.DELETE, "删除")
        btn_del_step.clicked.connect(self._delete_step)
        btn_up_step = PushButton(FluentIcon.UP, "上移")
        btn_up_step.clicked.connect(lambda: self._move_step(-1))
        btn_down_step = PushButton(FluentIcon.DOWN, "下移")
        btn_down_step.clicked.connect(lambda: self._move_step(1))
        steps_btn_layout.addWidget(btn_add_walk)
        steps_btn_layout.addWidget(btn_add_zipline)
        steps_btn_layout.addStretch()
        steps_btn_layout.addWidget(btn_del_step)
        steps_btn_layout.addWidget(btn_up_step)
        steps_btn_layout.addWidget(btn_down_step)
        steps_layout.addLayout(steps_btn_layout)

        ui_layout.addWidget(steps_group)

        # 步骤详情（动作/节点列表）
        self._detail_group = QGroupBox("详情")
        self._detail_group.setStyleSheet(group_style)
        detail_layout = QVBoxLayout(self._detail_group)
        detail_layout.setSpacing(4)

        self._detail_list = QListWidget()
        self._detail_list.setMaximumHeight(120)
        self._detail_list.currentRowChanged.connect(self._on_detail_selected)
        detail_layout.addWidget(self._detail_list)

        detail_btn_layout = QHBoxLayout()
        self._btn_add_detail = PushButton("+添加")
        self._btn_add_detail.clicked.connect(self._add_detail_item)
        btn_del_detail = PushButton(FluentIcon.DELETE, "删除")
        btn_del_detail.clicked.connect(self._delete_detail_item)
        btn_up_detail = PushButton(FluentIcon.UP, "上移")
        btn_up_detail.clicked.connect(lambda: self._move_detail_item(-1))
        btn_down_detail = PushButton(FluentIcon.DOWN, "下移")
        btn_down_detail.clicked.connect(lambda: self._move_detail_item(1))
        detail_btn_layout.addWidget(self._btn_add_detail)
        detail_btn_layout.addStretch()
        detail_btn_layout.addWidget(btn_del_detail)
        detail_btn_layout.addWidget(btn_up_detail)
        detail_btn_layout.addWidget(btn_down_detail)
        detail_layout.addLayout(detail_btn_layout)

        self._detail_group.hide()
        ui_layout.addWidget(self._detail_group)

        # 编辑区域（选中动作/节点时显示编辑字段）
        self._edit_group = QGroupBox("编辑")
        self._edit_group.setStyleSheet(group_style)
        self._edit_layout = QVBoxLayout(self._edit_group)
        self._edit_layout.setSpacing(4)

        # 动作编辑字段
        self._action_edit_widget = self._build_action_edit()
        self._edit_layout.addWidget(self._action_edit_widget)

        # 滑索节点编辑字段
        self._node_edit_widget = self._build_node_edit()
        self._edit_layout.addWidget(self._node_edit_widget)

        self._edit_group.hide()
        ui_layout.addWidget(self._edit_group)

        ui_layout.addStretch()
        self._stack.addWidget(ui_widget)

        # === JSON 模式 ===
        json_widget = QWidget()
        json_layout = QVBoxLayout(json_widget)
        json_layout.setContentsMargins(0, 0, 0, 0)

        self._json_edit = TextEdit()
        self._json_edit.setMinimumHeight(300)
        json_layout.addWidget(self._json_edit)

        self._stack.addWidget(json_widget)

        # 底部按钮
        btn_layout = QHBoxLayout()
        del_btn = PushButton(FluentIcon.DELETE, "删除路线")
        del_btn.clicked.connect(self._delete_route)
        btn_layout.addWidget(del_btn)

        # 调试按钮
        self._btn_debug_next = PushButton(FluentIcon.PLAY, "下一步(F11)")
        self._btn_debug_next.clicked.connect(self._on_debug_next)
        self._btn_debug_next.hide()
        btn_layout.addWidget(self._btn_debug_next)

        self._btn_debug_continue = PushButton(FluentIcon.SEND, "继续执行")
        self._btn_debug_continue.clicked.connect(self._on_debug_continue)
        self._btn_debug_continue.hide()
        btn_layout.addWidget(self._btn_debug_continue)

        btn_layout.addStretch()
        save_btn = PrimaryPushButton(FluentIcon.SAVE, "保存路线")
        save_btn.clicked.connect(self._save_route)
        btn_layout.addWidget(save_btn)
        main_layout.addLayout(btn_layout)

        # 监听任务状态变化以更新调试按钮可见性
        communicate.task.connect(self._update_debug_buttons)
        self.destroyed.connect(lambda: communicate.task.disconnect(self._update_debug_buttons))

        # 默认 UI 模式
        self._stack.setCurrentIndex(0)

    # ── 动作编辑表单 ──

    def _build_action_edit(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # 等待组
        self._chk_sleep = CheckBox("等待")
        self._chk_sleep.stateChanged.connect(self._on_action_field_changed)
        layout.addWidget(self._chk_sleep)
        sleep_row = QHBoxLayout()
        self._action_sleep = DoubleSpinBox()
        self._action_sleep.setRange(0, 999)
        self._action_sleep.setSingleStep(1)
        self._action_sleep.setDecimals(2)
        self._action_sleep.valueChanged.connect(self._on_action_field_changed)
        sleep_row.addWidget(BodyLabel("秒:"))
        sleep_row.addWidget(self._action_sleep)
        self._sleep_row_widget = QWidget()
        self._sleep_row_widget.setLayout(sleep_row)
        layout.addWidget(self._sleep_row_widget)

        # 视角组
        self._chk_angle = CheckBox("视角")
        self._chk_angle.stateChanged.connect(self._on_action_field_changed)
        layout.addWidget(self._chk_angle)
        angle_row = QHBoxLayout()
        self._action_angle_x = DoubleSpinBox()
        self._action_angle_x.setRange(-9999, 9999)
        self._action_angle_x.setDecimals(2)
        self._action_angle_x.valueChanged.connect(self._on_action_field_changed)
        angle_row.addWidget(BodyLabel("X:"))
        angle_row.addWidget(self._action_angle_x)
        self._action_angle_y = DoubleSpinBox()
        self._action_angle_y.setRange(-9999, 9999)
        self._action_angle_y.setDecimals(2)
        self._action_angle_y.valueChanged.connect(self._on_action_field_changed)
        angle_row.addWidget(BodyLabel("Y:"))
        angle_row.addWidget(self._action_angle_y)
        self._angle_row_widget = QWidget()
        self._angle_row_widget.setLayout(angle_row)
        layout.addWidget(self._angle_row_widget)

        # 鼠标偏移组
        self._chk_mouse = CheckBox("鼠标偏移")
        self._chk_mouse.stateChanged.connect(self._on_action_field_changed)
        layout.addWidget(self._chk_mouse)
        mouse_row = QHBoxLayout()
        self._action_mouse_x = SpinBox()
        self._action_mouse_x.setRange(-9999, 9999)
        self._action_mouse_x.valueChanged.connect(self._on_action_field_changed)
        mouse_row.addWidget(BodyLabel("X:"))
        mouse_row.addWidget(self._action_mouse_x)
        self._action_mouse_y = SpinBox()
        self._action_mouse_y.setRange(-9999, 9999)
        self._action_mouse_y.valueChanged.connect(self._on_action_field_changed)
        mouse_row.addWidget(BodyLabel("Y:"))
        mouse_row.addWidget(self._action_mouse_y)
        self._mouse_row_widget = QWidget()
        self._mouse_row_widget.setLayout(mouse_row)
        layout.addWidget(self._mouse_row_widget)

        # 按键组
        self._chk_key = CheckBox("按键")
        self._chk_key.stateChanged.connect(self._on_action_field_changed)
        layout.addWidget(self._chk_key)
        key_row = QHBoxLayout()
        self._action_key = ComboBox()
        self._action_key.addItems(KEY_OPTIONS)
        self._action_key.currentIndexChanged.connect(self._on_action_field_changed)
        key_row.addWidget(BodyLabel("键:"))
        key_row.addWidget(self._action_key)
        self._action_duration = DoubleSpinBox()
        self._action_duration.setRange(0, 999)
        self._action_duration.setSingleStep(1)
        self._action_duration.setDecimals(2)
        self._action_duration.valueChanged.connect(self._on_action_field_changed)
        key_row.addWidget(BodyLabel("时长:"))
        key_row.addWidget(self._action_duration)
        self._action_count = SpinBox()
        self._action_count.setRange(1, 999)
        self._action_count.valueChanged.connect(self._on_action_field_changed)
        key_row.addWidget(BodyLabel("次数:"))
        key_row.addWidget(self._action_count)
        self._key_row_widget = QWidget()
        self._key_row_widget.setLayout(key_row)
        layout.addWidget(self._key_row_widget)

        # 点击组
        self._chk_button = CheckBox("点击")
        self._chk_button.stateChanged.connect(self._on_action_field_changed)
        layout.addWidget(self._chk_button)
        btn_row = QHBoxLayout()
        self._action_button = ComboBox()
        self._action_button.addItems(["左键", "右键"])
        self._action_button.currentIndexChanged.connect(self._on_action_field_changed)
        btn_row.addWidget(BodyLabel("按钮:"))
        btn_row.addWidget(self._action_button)
        self._button_row_widget = QWidget()
        self._button_row_widget.setLayout(btn_row)
        layout.addWidget(self._button_row_widget)

        # after_sleep（通用）
        after_row = QHBoxLayout()
        after_row.addWidget(BodyLabel("执行后等待:"))
        self._action_after_sleep = DoubleSpinBox()
        self._action_after_sleep.setRange(0, 999)
        self._action_after_sleep.setSingleStep(1)
        self._action_after_sleep.setDecimals(2)
        self._action_after_sleep.valueChanged.connect(self._on_action_field_changed)
        after_row.addWidget(self._action_after_sleep)
        after_row.addWidget(BodyLabel("秒"))
        layout.addLayout(after_row)

        return w

    def _build_node_edit(self):
        w = QWidget()
        layout = QFormLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._node_distance = SpinBox()
        self._node_distance.setRange(0, 9999)
        self._node_distance.valueChanged.connect(self._on_node_field_changed)
        layout.addRow("距离:", self._node_distance)

        self._node_angle_x = DoubleSpinBox()
        self._node_angle_x.setRange(-9999, 9999)
        self._node_angle_x.setDecimals(2)
        self._node_angle_x.valueChanged.connect(self._on_node_field_changed)
        layout.addRow("视角X:", self._node_angle_x)

        self._node_angle_y = DoubleSpinBox()
        self._node_angle_y.setRange(-9999, 9999)
        self._node_angle_y.setDecimals(2)
        self._node_angle_y.valueChanged.connect(self._on_node_field_changed)
        layout.addRow("视角Y:", self._node_angle_y)

        return w

    # ── 模式切换 ──

    def _toggle_mode(self):
        if self._stack.currentIndex() == 0:
            # UI → JSON: 收集数据写入 TextEdit
            route = self._collect_route()
            self._json_edit.setText(json.dumps(route, ensure_ascii=False, indent=2))
            self._stack.setCurrentIndex(1)
            self._mode_btn.setText("切换UI模式")
        else:
            # JSON → UI: 解析 JSON 加载到 UI
            try:
                route = json.loads(self._json_edit.toPlainText())
                self._load_route_to_ui(route)
                self._stack.setCurrentIndex(0)
                self._mode_btn.setText("切换JSON模式")
            except json.JSONDecodeError as e:
                self.task.log_error(f"JSON格式错误: {e}")

    # ── 加载路线 ──

    def load_route(self, route):
        """外部调用：加载路线数据到编辑器"""
        self._route = copy.deepcopy(route) if route else {}
        if self._stack.currentIndex() == 0:
            self._load_route_to_ui(self._route)
        else:
            self._json_edit.setText(json.dumps(self._route, ensure_ascii=False, indent=2))

    def _load_route_to_ui(self, route):
        """将 route dict 填充到 UI 字段"""
        self._updating = True
        try:
            self._route = copy.deepcopy(route) if route else {}

            self._id_label.setText(self._route.get("id", ""))
            self._name_edit.setText(self._route.get("name", ""))

            route_type = self._route.get("type", "")
            idx = self._type_combo.findText(route_type)
            self._type_combo.setCurrentIndex(max(0, idx))

            self._area_edit.setText(self._route.get("area", ""))

            tp_name = self._route.get("teleport", "")
            tp_idx = 0
            for i in range(self._tp_combo.count()):
                if self._tp_combo.itemData(i) == tp_name:
                    tp_idx = i
                    break
            self._tp_combo.setCurrentIndex(tp_idx)

            self._refresh_steps_list()
            self._detail_group.hide()
            self._edit_group.hide()
        finally:
            self._updating = False

    # ── 收集路线数据 ──

    def _collect_route(self):
        """从 UI 字段收集为 route dict"""
        route = copy.deepcopy(self._route)
        route["name"] = self._name_edit.text().strip()
        route["type"] = self._type_combo.currentText()
        route["area"] = self._area_edit.text().strip()

        tp_idx = self._tp_combo.currentIndex()
        tp_name = self._tp_combo.itemData(tp_idx) or ""
        route["teleport"] = tp_name

        return route

    # ── 步骤列表操作 ──

    def _get_steps(self):
        return self._route.setdefault("steps", [])

    def _refresh_steps_list(self):
        self._steps_list.clear()
        for step in self._get_steps():
            self._steps_list.addItem(_step_summary(step))

    def _add_step(self, step_type):
        steps = self._get_steps()
        if step_type == "walk":
            steps.append({"type": "walk", "actions": []})
        else:
            steps.append({"type": "zipline", "nodes": []})
        self._refresh_steps_list()
        self._steps_list.setCurrentRow(len(steps) - 1)

    def _delete_step(self):
        row = self._steps_list.currentRow()
        if row < 0:
            return
        steps = self._get_steps()
        steps.pop(row)
        self._refresh_steps_list()
        self._detail_group.hide()
        self._edit_group.hide()

    def _move_step(self, direction):
        row = self._steps_list.currentRow()
        steps = self._get_steps()
        new_row = row + direction
        if row < 0 or new_row < 0 or new_row >= len(steps):
            return
        steps[row], steps[new_row] = steps[new_row], steps[row]
        self._refresh_steps_list()
        self._steps_list.setCurrentRow(new_row)

    def _on_step_selected(self, row):
        if row < 0:
            self._detail_group.hide()
            self._edit_group.hide()
            return
        steps = self._get_steps()
        if row >= len(steps):
            return
        step = steps[row]
        step_type = step.get("type", "")

        if step_type == "walk":
            self._detail_group.setTitle("动作列表")
            self._btn_add_detail.setText("+动作")
            self._refresh_detail_list_walk(step)
        elif step_type == "zipline":
            self._detail_group.setTitle("节点列表")
            self._btn_add_detail.setText("+节点")
            self._refresh_detail_list_zipline(step)

        self._detail_group.show()
        self._edit_group.hide()

    # ── 详情列表（动作/节点）──

    def _current_step(self):
        row = self._steps_list.currentRow()
        steps = self._get_steps()
        if 0 <= row < len(steps):
            return steps[row]
        return None

    def _current_step_type(self):
        step = self._current_step()
        return step.get("type", "") if step else ""

    def _refresh_detail_list_walk(self, step):
        self._detail_list.clear()
        for action in step.get("actions", []):
            self._detail_list.addItem(_action_summary(action))

    def _refresh_detail_list_zipline(self, step):
        self._detail_list.clear()
        for node in step.get("nodes", []):
            self._detail_list.addItem(_node_summary(node))

    def _add_detail_item(self):
        step = self._current_step()
        if not step:
            return
        if step["type"] == "walk":
            step.setdefault("actions", []).append({"key": "w", "duration": 0.3})
            self._refresh_detail_list_walk(step)
            self._detail_list.setCurrentRow(len(step["actions"]) - 1)
        elif step["type"] == "zipline":
            step.setdefault("nodes", []).append({"distance": 50})
            self._refresh_detail_list_zipline(step)
            self._detail_list.setCurrentRow(len(step["nodes"]) - 1)
        self._refresh_steps_list_item(self._steps_list.currentRow())

    def _delete_detail_item(self):
        step = self._current_step()
        row = self._detail_list.currentRow()
        if not step or row < 0:
            return
        if step["type"] == "walk":
            actions = step.get("actions", [])
            if row < len(actions):
                actions.pop(row)
                self._refresh_detail_list_walk(step)
        elif step["type"] == "zipline":
            nodes = step.get("nodes", [])
            if row < len(nodes):
                nodes.pop(row)
                self._refresh_detail_list_zipline(step)
        self._edit_group.hide()
        self._refresh_steps_list_item(self._steps_list.currentRow())

    def _move_detail_item(self, direction):
        step = self._current_step()
        row = self._detail_list.currentRow()
        if not step or row < 0:
            return
        items = step.get("actions" if step["type"] == "walk" else "nodes", [])
        new_row = row + direction
        if new_row < 0 or new_row >= len(items):
            return
        items[row], items[new_row] = items[new_row], items[row]
        if step["type"] == "walk":
            self._refresh_detail_list_walk(step)
        else:
            self._refresh_detail_list_zipline(step)
        self._detail_list.setCurrentRow(new_row)

    def _refresh_steps_list_item(self, row):
        """刷新步骤列表中某一行的摘要"""
        steps = self._get_steps()
        if 0 <= row < len(steps):
            self._steps_list.item(row).setText(_step_summary(steps[row]))

    def _on_detail_selected(self, row):
        step = self._current_step()
        if not step or row < 0:
            self._edit_group.hide()
            return

        if step["type"] == "walk":
            actions = step.get("actions", [])
            if row < len(actions):
                self._show_action_edit(actions[row])
        elif step["type"] == "zipline":
            nodes = step.get("nodes", [])
            if row < len(nodes):
                self._show_node_edit(nodes[row])

    # ── 动作编辑 ──

    def _show_action_edit(self, action):
        self._updating = True
        try:
            self._action_edit_widget.show()
            self._node_edit_widget.hide()
            self._edit_group.show()

            has_sleep = "sleep" in action
            self._chk_sleep.setChecked(has_sleep)
            self._sleep_row_widget.setVisible(has_sleep)
            if has_sleep:
                self._action_sleep.setValue(action.get("sleep", 1.0))

            has_angle = "angle_x" in action
            self._chk_angle.setChecked(has_angle)
            self._angle_row_widget.setVisible(has_angle)
            if has_angle:
                self._action_angle_x.setValue(action.get("angle_x", 0))
                self._action_angle_y.setValue(action.get("angle_y", 0))

            has_mouse = "mouse_x" in action
            self._chk_mouse.setChecked(has_mouse)
            self._mouse_row_widget.setVisible(has_mouse)
            if has_mouse:
                self._action_mouse_x.setValue(action.get("mouse_x", 0))
                self._action_mouse_y.setValue(action.get("mouse_y", 0))

            has_key = "key" in action
            self._chk_key.setChecked(has_key)
            self._key_row_widget.setVisible(has_key)
            if has_key:
                key = action["key"]
                if isinstance(key, list):
                    key = key[0] if key else "w"
                idx = self._action_key.findText(key)
                self._action_key.setCurrentIndex(max(0, idx))
                self._action_duration.setValue(action.get("duration", 0.3))
                self._action_count.setValue(action.get("count", 1))

            has_button = "button" in action
            self._chk_button.setChecked(has_button)
            self._button_row_widget.setVisible(has_button)
            if has_button:
                btn_map = {"left": "左键", "right": "右键"}
                idx = self._action_button.findText(btn_map.get(action.get("button", "left"), "左键"))
                self._action_button.setCurrentIndex(max(0, idx))

            self._action_after_sleep.setValue(action.get("after_sleep", 0))
        finally:
            self._updating = False

    def _on_action_field_changed(self):
        if self._updating:
            return
        step = self._current_step()
        row = self._detail_list.currentRow()
        if not step or step["type"] != "walk" or row < 0:
            return
        actions = step.get("actions", [])
        if row >= len(actions):
            return

        # 重建 action 从 UI 字段（顺序与 Walker.execute 一致）
        action = {}
        if self._chk_sleep.isChecked():
            action["sleep"] = round(self._action_sleep.value(), 2)
        self._sleep_row_widget.setVisible(self._chk_sleep.isChecked())

        if self._chk_angle.isChecked():
            action["angle_x"] = round(self._action_angle_x.value(), 2)
            action["angle_y"] = round(self._action_angle_y.value(), 2)
        self._angle_row_widget.setVisible(self._chk_angle.isChecked())

        if self._chk_mouse.isChecked():
            action["mouse_x"] = round(self._action_mouse_x.value(), 2)
            action["mouse_y"] = round(self._action_mouse_y.value(), 2)
        self._mouse_row_widget.setVisible(self._chk_mouse.isChecked())

        if self._chk_key.isChecked():
            action["key"] = self._action_key.currentText()
            action["duration"] = round(self._action_duration.value(), 2)
            count = self._action_count.value()
            if count > 1:
                action["count"] = count
        self._key_row_widget.setVisible(self._chk_key.isChecked())

        if self._chk_button.isChecked():
            btn_rmap = {"左键": "left", "右键": "right"}
            action["button"] = btn_rmap.get(self._action_button.currentText(), "left")
        self._button_row_widget.setVisible(self._chk_button.isChecked())

        after = round(self._action_after_sleep.value(), 2)
        if after > 0:
            action["after_sleep"] = after

        actions[row] = action
        self._detail_list.item(row).setText(_action_summary(action))
        self._refresh_steps_list_item(self._steps_list.currentRow())

    # ── 节点编辑 ──

    def _show_node_edit(self, node):
        self._updating = True
        try:
            self._action_edit_widget.hide()
            self._node_edit_widget.show()
            self._edit_group.show()

            self._node_distance.setValue(node.get("distance", 0))
            self._node_angle_x.setValue(node.get("angle_x", 0))
            self._node_angle_y.setValue(node.get("angle_y", 0))
        finally:
            self._updating = False

    def _on_node_field_changed(self):
        if self._updating:
            return
        step = self._current_step()
        row = self._detail_list.currentRow()
        if not step or step["type"] != "zipline" or row < 0:
            return
        nodes = step.get("nodes", [])
        if row >= len(nodes):
            return

        node = {"distance": self._node_distance.value()}
        ax = self._node_angle_x.value()
        ay = self._node_angle_y.value()
        if ax != 0:
            node["angle_x"] = ax
        if ay != 0:
            node["angle_y"] = ay

        nodes[row] = node
        self._detail_list.item(row).setText(_node_summary(node))
        self._refresh_steps_list_item(self._steps_list.currentRow())

    # ── 保存/删除 ──

    def _save_route(self):
        if self._stack.currentIndex() == 1:
            # JSON 模式：从 TextEdit 解析
            try:
                route = json.loads(self._json_edit.toPlainText())
            except json.JSONDecodeError as e:
                self.task.log_error(f"JSON格式错误: {e}")
                return
        else:
            route = self._collect_route()

        if not route.get("name"):
            self.task.log_error("请填写目的地名称")
            return

        self.store.save(route)
        self.store.flush()
        self._route = route
        self.task.log_info(f"路线已保存: {route.get('name', '')}")
        self.route_saved.emit()

    def _on_debug_next(self):
        self.task.debug_step_next()

    def _on_debug_continue(self):
        self.task.debug_continue()

    def _update_debug_buttons(self, task):
        if task != self.task:
            return
        show = task.enabled and task.navigator._debug_mode
        self._btn_debug_next.setVisible(show)
        self._btn_debug_continue.setVisible(show)

    def _delete_route(self):
        route_id = self._route.get("id")
        if not route_id:
            self.task.log_error("当前路线无ID，无法删除")
            return
        name = self._route.get("name", "")
        if self.store.delete(route_id):
            self.store.flush()
            self.task.log_info(f"路线已删除: {name}")
            self.route_deleted.emit()
        else:
            self.task.log_error(f"未找到id为 {route_id} 的路线")
