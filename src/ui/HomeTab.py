import time

from PySide6.QtCore import QEvent, Qt, Signal, QRect, QSize, QPoint, QTimer
from PySide6.QtWidgets import (QFrame, QVBoxLayout, QHBoxLayout, QWidget,
                               QSplitter, QScrollArea, QSizePolicy, QLabel,
                               QLayout, QLayoutItem, QTableWidgetItem)
from qfluentwidgets import (FluentIcon, SwitchButton, BodyLabel, IconWidget,
                            SubtitleLabel, StrongBodyLabel, CaptionLabel, PushButton, qconfig,
                            NavigationItemPosition)

from ok import og
from ok.gui.Communicate import communicate
from ok.gui.tasks.ConfigItemFactory import config_widget
from ok.gui.tasks.TooltipTableWidget import TooltipTableWidget
from ok.gui.widget.CustomTab import CustomTab
from ok.gui.widget.UpdateConfigWidgetItem import value_to_string


class FlowLayout(QLayout):
    """Flow layout that arranges widgets left-to-right and wraps to next line."""

    def __init__(self, parent=None, h_spacing=8, v_spacing=8, max_per_row=0):
        super().__init__(parent)
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self._max_per_row = max_per_row
        self._items = []

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _do_layout(self, rect, test_only):
        m = self.contentsMargins()
        effective = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x = effective.x()
        y = effective.y()
        line_height = 0

        col_count = 0
        for item in self._items:
            wid = item.widget()
            if wid and not wid.isVisible():
                continue
            item_size = item.sizeHint()
            next_x = x + item_size.width() + self._h_spacing
            force_wrap = self._max_per_row > 0 and col_count >= self._max_per_row
            if (next_x - self._h_spacing > effective.right() + 1 or force_wrap) and line_height > 0:
                x = effective.x()
                y = y + line_height + self._v_spacing
                next_x = x + item_size.width() + self._h_spacing
                line_height = 0
                col_count = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item_size))
            x = next_x
            line_height = max(line_height, item_size.height())
            col_count += 1

        return y + line_height - rect.y() + m.bottom()

def _card_style_normal():
    from qfluentwidgets import isDarkTheme
    if isDarkTheme():
        return """
            QFrame#taskCard {
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
                background-color: rgba(255, 255, 255, 0.03);
            }
            QFrame#taskCard:hover {
                border: 1px solid rgba(255, 255, 255, 0.15);
                background-color: rgba(255, 255, 255, 0.06);
            }
        """
    return """
        QFrame#taskCard {
            border: 1px solid rgba(0, 0, 0, 0.08);
            border-radius: 8px;
            background-color: rgba(0, 0, 0, 0.02);
        }
        QFrame#taskCard:hover {
            border: 1px solid rgba(0, 0, 0, 0.15);
            background-color: rgba(0, 0, 0, 0.05);
        }
    """


def _card_style_selected():
    return """
        QFrame#taskCard {
            border: 1px solid rgba(100, 160, 255, 0.6);
            border-radius: 8px;
            background-color: rgba(100, 160, 255, 0.1);
        }
    """


class TriggerCard(QFrame):
    """Compact card for a trigger task with enable/disable switch."""
    clicked = Signal(object)

    def __init__(self, task):
        super().__init__()
        self.task = task
        self._selected = False
        self.setObjectName('taskCard')
        self.setFixedSize(150, 120)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(_card_style_normal())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignCenter)

        # Top: icon
        icon_widget = IconWidget(task.icon or FluentIcon.ROBOT, self)
        icon_widget.setFixedSize(22, 22)
        layout.addWidget(icon_widget, 0, Qt.AlignCenter)

        # Middle: name
        name_label = BodyLabel(og.app.tr(task.name))
        name_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(name_label, 0, Qt.AlignCenter)

        # Bottom: switch
        self.switch = SwitchButton()
        self.switch.setOnText(self.tr('On'))
        self.switch.setOffText(self.tr('Off'))
        self.switch.setChecked(task.enabled)
        self.switch.checkedChanged.connect(self._on_switch_changed)
        layout.addWidget(self.switch, 0, Qt.AlignCenter)

        communicate.task.connect(self._on_task_signal)
        qconfig.themeChangedFinished.connect(self._on_theme_changed)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.task)
        super().mousePressEvent(event)

    def set_selected(self, selected):
        self._selected = selected
        self.setStyleSheet(_card_style_selected() if selected else _card_style_normal())

    def _on_switch_changed(self, checked):
        if checked:
            self.task.enable()
        else:
            self.task.disable()

    def _on_theme_changed(self):
        self.setStyleSheet(_card_style_selected() if self._selected else _card_style_normal())

    def _on_task_signal(self, task):
        if task == self.task:
            self.switch.setChecked(task.enabled)


class OnetimeCard(QFrame):
    """Compact card for a onetime task."""
    clicked = Signal(object)

    def __init__(self, task):
        super().__init__()
        self.task = task
        self._selected = False
        self.setObjectName('taskCard')
        self.setFixedSize(150, 100)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(_card_style_normal())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignCenter)

        # Top: icon
        icon_widget = IconWidget(task.icon or FluentIcon.BOOK_SHELF, self)
        icon_widget.setFixedSize(22, 22)
        layout.addWidget(icon_widget, 0, Qt.AlignCenter)

        # Bottom: name
        name_label = BodyLabel(og.app.tr(task.name))
        name_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(name_label, 0, Qt.AlignCenter)

        communicate.task.connect(self._on_task_signal)
        qconfig.themeChangedFinished.connect(self._on_theme_changed)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.task)
        super().mousePressEvent(event)

    def set_selected(self, selected):
        self._selected = selected
        self.setStyleSheet(_card_style_selected() if selected else _card_style_normal())

    def _on_theme_changed(self):
        self.setStyleSheet(_card_style_selected() if self._selected else _card_style_normal())

    def _on_task_signal(self, task):
        pass


class ConfigPanel(QScrollArea):
    """Right-side config drawer panel for a task."""

    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setMinimumWidth(360)
        self.setMaximumWidth(520)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._apply_theme()
        self._current_widget = None
        self._current_task = None
        self._current_onetime = False
        self.hide()
        communicate.task.connect(self._on_task_changed)
        qconfig.themeChangedFinished.connect(self._apply_theme)

    def _apply_theme(self):
        from qfluentwidgets import isDarkTheme
        if isDarkTheme():
            bg = "rgb(39, 39, 39)"
            border_color = "rgba(255, 255, 255, 0.08)"
        else:
            bg = "rgb(243, 243, 243)"
            border_color = "rgba(0, 0, 0, 0.08)"
        self.setStyleSheet(f"""
            QScrollArea {{
                border-left: 1px solid {border_color};
                background-color: {bg};
            }}
            QScrollArea > QWidget > QWidget {{
                background-color: {bg};
            }}
        """)

    def _on_task_changed(self, task):
        if self._current_task and task == self._current_task:
            self.show_task(self._current_task, self._current_onetime)

    def show_task(self, task, onetime=False):
        self._current_task = task
        self._current_onetime = onetime
        # Clear previous content
        if self._current_widget:
            self._current_widget.deleteLater()

        container = QWidget()
        container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # Header: icon + name
        header = QHBoxLayout()
        header.setSpacing(8)
        icon = IconWidget(task.icon or FluentIcon.ROBOT)
        icon.setFixedSize(24, 24)
        header.addWidget(icon)
        title = StrongBodyLabel(og.app.tr(task.name))
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)

        # Description
        if task.description:
            desc = CaptionLabel(og.app.tr(task.description))
            desc.setWordWrap(True)
            layout.addWidget(desc)

        # Config items
        if task.config and task.config.has_user_config():
            for key, value in task.config.items():
                if not key.startswith('_'):
                    the_type = task.config_type.get(key) if task.config_type else None
                    if the_type and the_type.get('type') == 'custom_widget':
                        factory = the_type.get('widget_factory')
                        if factory:
                            item_widget = factory()
                        else:
                            continue
                    else:
                        item_widget = config_widget(
                            task.config_type, task.config_description,
                            task.config, key, value, task
                        )
                    for child in item_widget.findChildren(QLabel):
                        child.setWordWrap(True)
                    item_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
                    layout.addWidget(item_widget)

        # Action buttons
        if onetime:
            from ok.gui.tasks.TaskCard import TaskButtons
            task_buttons = TaskButtons(task)
            task_buttons.update_buttons()

            def on_task_signal(t, tb=task_buttons):
                try:
                    if t == tb.task:
                        tb.update_buttons()
                except RuntimeError:
                    pass

            communicate.task.connect(on_task_signal)
            task_buttons.destroyed.connect(lambda: communicate.task.disconnect(on_task_signal))
            layout.addWidget(task_buttons)
        else:
            # Reset button
            if task.default_config:
                reset_btn = PushButton(FluentIcon.CANCEL, self.tr("Reset Config"))
                reset_btn.clicked.connect(lambda: task.config.reset_to_default())
                layout.addWidget(reset_btn)

        layout.addStretch()

        self._current_widget = container
        self.setWidget(container)
        self.show()
        # Update splitter sizes to show panel
        splitter = self.parent()
        if isinstance(splitter, QSplitter):
            splitter.setSizes([splitter.width() - 520, 520])

    def clear(self):
        if self._current_widget:
            self._current_widget.deleteLater()
            self._current_widget = None
        self.hide()
        # Restore splitter sizes
        splitter = self.parent()
        if isinstance(splitter, QSplitter):
            splitter.setSizes([splitter.width(), 0])


class HomeTab(CustomTab):

    icon = FluentIcon.HOME

    def __init__(self):
        super().__init__()
        self._initialized = False
        self._selected_card = None
        self._all_cards = []

    @property
    def name(self):
        return "首页"

    @property
    def add_after_default_tabs(self):
        return False

    @property
    def position(self):
        return NavigationItemPosition.TOP

    def showEvent(self, event):
        super().showEvent(event)
        if event.type() == QEvent.Show and not self._initialized and self.executor:
            self._initialized = True
            self._init_ui()

    def _init_ui(self):
        # Main horizontal splitter: left content + right config panel
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        # Left side: main content
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)
        left_layout.setAlignment(Qt.AlignTop)

        # Start card (master switch)
        from ok.gui.start.StartCard import StartCard
        self.start_card = StartCard(self.exit_event)
        left_layout.addWidget(self.start_card)

        # Trigger tasks section
        if self.executor.trigger_tasks:
            header = SubtitleLabel("自动触发")
            header.setContentsMargins(0, 8, 0, 4)
            left_layout.addWidget(header)

            triggers_widget = QWidget()
            triggers_layout = FlowLayout(triggers_widget, h_spacing=12, v_spacing=12, max_per_row=4)
            triggers_layout.setContentsMargins(0, 0, 0, 0)

            for task in self.executor.trigger_tasks:
                card = TriggerCard(task)
                card.clicked.connect(lambda t, is_onetime=False: self._on_card_clicked(t, is_onetime))
                triggers_layout.addWidget(card)
                self._all_cards.append(card)

            left_layout.addWidget(triggers_widget)

        # Onetime tasks section
        _tool_task_names = {"自动导航", "导航录制", "测试", "Diagnosis"}
        main_tasks = []
        tool_tasks = []
        for task in self.executor.onetime_tasks:
            if task.name in _tool_task_names:
                tool_tasks.append(task)
            else:
                main_tasks.append(task)

        if main_tasks:
            onetime_header = SubtitleLabel("手动执行")
            onetime_header.setContentsMargins(0, 8, 0, 4)
            left_layout.addWidget(onetime_header)

            onetime_widget = QWidget()
            onetime_layout = FlowLayout(onetime_widget, h_spacing=12, v_spacing=12, max_per_row=4)
            onetime_layout.setContentsMargins(0, 0, 0, 0)

            for task in main_tasks:
                card = OnetimeCard(task)
                card.clicked.connect(lambda t, is_onetime=True: self._on_card_clicked(t, is_onetime))
                onetime_layout.addWidget(card)
                self._all_cards.append(card)

            left_layout.addWidget(onetime_widget)

        if tool_tasks:
            tool_header = SubtitleLabel("工具")
            tool_header.setContentsMargins(0, 8, 0, 4)
            left_layout.addWidget(tool_header)

            tool_widget = QWidget()
            tool_layout = FlowLayout(tool_widget, h_spacing=12, v_spacing=12, max_per_row=4)
            tool_layout.setContentsMargins(0, 0, 0, 0)

            for task in tool_tasks:
                card = OnetimeCard(task)
                card.clicked.connect(lambda t, is_onetime=True: self._on_card_clicked(t, is_onetime))
                tool_layout.addWidget(card)
                self._all_cards.append(card)

            left_layout.addWidget(tool_widget)

        # Task execution info section
        self.task_info_header = SubtitleLabel("")
        self.task_info_header.setContentsMargins(0, 8, 0, 4)
        left_layout.addWidget(self.task_info_header)

        self.task_info_table = TooltipTableWidget(width_percentages=[0.3, 0.7])
        self.task_info_table.setFixedHeight(200)
        self.task_info_table.setColumnCount(2)
        self.task_info_table.setHorizontalHeaderLabels(["信息", "值"])
        left_layout.addWidget(self.task_info_table)

        self.task_info_header.hide()
        self.task_info_table.hide()
        self._last_task = None
        self._current_task_name = ""

        self._info_timer = QTimer()
        self._info_timer.timeout.connect(self._update_info_table)
        self._info_timer.start(1000)

        left_layout.addStretch()
        splitter.addWidget(left_widget)

        # Right side: config panel (hidden by default)
        self.config_panel = ConfigPanel()
        splitter.addWidget(self.config_panel)

        splitter.setSizes([600, 0])
        self.add_widget(splitter, 1)

    def _on_card_clicked(self, task, onetime=False):
        # Deselect previous
        if self._selected_card:
            if self._selected_card.task == task:
                # Click same card again: close panel
                self._selected_card.set_selected(False)
                self._selected_card = None
                self.config_panel.clear()
                return
            self._selected_card.set_selected(False)

        # Select new card
        for card in self._all_cards:
            if card.task == task:
                card.set_selected(True)
                self._selected_card = card
                break

        self.config_panel.show_task(task, onetime=onetime)

    @staticmethod
    def _time_elapsed(start_time):
        if start_time > 0:
            elapsed = time.time() - start_time
            hours, remainder = divmod(elapsed, 3600)
            minutes, seconds = divmod(remainder, 60)
            return f"{int(hours)}h {int(minutes)}m {int(seconds)}s"
        return ""

    def _update_info_table(self):
        current = og.executor.current_task
        if current is not None:
            self._last_task = current
        if current is None and self._last_task is None:
            return

        task = self._last_task
        if task is None:
            return

        is_running = task.enabled
        status = "运行中" if is_running else "已完成"
        elapsed = self._time_elapsed(task.start_time) if is_running else ""
        name_str = f": {og.app.tr(task.name)}"
        if elapsed:
            name_str += f"  耗时: {elapsed}"
        self._current_task_name = name_str

        self.task_info_header.setText(status + self._current_task_name)
        self.task_info_header.show()

        info = task.info
        if not info:
            self.task_info_table.hide()
            return

        self.task_info_table.show()
        self.task_info_table.setRowCount(len(info))
        for row, (key, value) in enumerate(info.items()):
            if not self.task_info_table.item(row, 0):
                item0 = QTableWidgetItem()
                item0.setFlags(item0.flags() & ~Qt.ItemIsEditable)
                self.task_info_table.setItem(row, 0, item0)
            self.task_info_table.item(row, 0).setText(og.app.tr(key))
            if not self.task_info_table.item(row, 1):
                item1 = QTableWidgetItem()
                item1.setFlags(item1.flags() & ~Qt.ItemIsEditable)
                self.task_info_table.setItem(row, 1, item1)
            self.task_info_table.item(row, 1).setText(og.app.tr(value_to_string(value)))
