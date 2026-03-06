from qfluentwidgets import FluentIcon

from ok.gui.Communicate import communicate
from src.tasks.BaseNavTask import BaseNavTask
from src.navigation.Navigator import Navigator
from src.navigation.RouteStore import RouteStore
from src.navigation.Teleporter import Teleporter


class NavigationTask(BaseNavTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "自动导航"
        self.description = "传送+滑索+步行，自动导航到目的地。运行中按F12可终止当前任务"
        self.icon = FluentIcon.SEND

        self.store = RouteStore()
        self.navigator = Navigator(self, store=self.store)
        self.teleporter = Teleporter(self)

        self.name_mapping = {}
        display_names = self._build_display_names()

        self._route_editor = None  # 延迟创建

        self.default_config.update({
            "目的地": display_names[0] if display_names else "",
            "单步调试": "关闭",
            "路线编辑器": "",  # 占位，用于 custom_widget
        })

        self.config_type["目的地"] = {
            "type": "drop_down",
            "options": display_names,
        }
        self.config_type["单步调试"] = {
            "type": "drop_down",
            "options": ["关闭", "开启"],
        }
        self.config_description["单步调试"] = "开启后每步暂停，按F11继续下一步"

        self.config_type["路线编辑器"] = {
            "type": "custom_widget",
            "widget_factory": self._create_route_editor,
        }

    def _build_display_names(self):
        """从 store 构建下拉框选项列表和 name_mapping"""
        self.name_mapping.clear()
        display_names = []
        for route in self.store.all():
            name = route.get("name", "")
            route_type = route.get("type", "")
            map_name = route.get("area", "")
            display_name = f"[{map_name}]{name} ({route_type})"
            display_names.append(display_name)
            self.name_mapping[display_name] = {"name": name, "type": route_type}
        return display_names

    def _create_route_editor(self):
        """创建路线编辑器 widget（由 ConfigPanel 调用）"""
        from src.ui.RouteEditorWidget import RouteEditorWidget
        editor = RouteEditorWidget(self)
        editor.route_saved.connect(self._on_route_saved)
        editor.route_deleted.connect(self._on_route_deleted)
        self._route_editor = editor

        # 加载当前选中目的地的路线
        self._load_route_for_dest(self.config.get("目的地"))

        return editor

    def reload_routes(self):
        """重新加载路线数据并刷新下拉框选项"""
        self.store.reload()
        display_names = self._build_display_names()
        self.config_type["目的地"]["options"] = display_names

    def on_create(self):
        """load_config 之后，监听下拉框变化"""
        self.config.add_listener("目的地", self._load_route_for_dest)

    def _load_route_for_dest(self, display_name):
        route_info = self.name_mapping.get(display_name)
        if route_info and self._route_editor:
            route = self.store.find(route_info["name"], route_info["type"])
            if route:
                self._route_editor.load_route(route)

    def debug_step_next(self):
        """单步放行（UI 调用）"""
        self.navigator.step_next()

    def debug_continue(self):
        """关闭调试模式，继续执行（UI 调用）"""
        self.navigator.set_debug_mode(False)

    def run(self):
        selected_display = self.config.get("目的地")
        route_info = self.name_mapping.get(selected_display)

        if not route_info:
            self.log_error(f"未找到目的地: {selected_display}")
            return False

        route = self.store.find(route_info["name"], route_info["type"])
        if not route:
            self.log_error(f"未找到路线: {route_info['name']}")
            return False

        debug = self.config.get("单步调试") == "开启"
        self.navigator.set_debug_mode(debug)

        return self.navigator.navigate_to(
            route_info["name"],
            dest_type=route_info["type"],
        )

    def _on_route_saved(self):
        """路线保存后刷新下拉框"""
        self.reload_routes()
        communicate.task.emit(self)

    def _on_route_deleted(self):
        """路线删除后刷新下拉框"""
        self.reload_routes()
        display_names = self.config_type["目的地"]["options"]
        if display_names:
            self.config["目的地"] = display_names[0]
        else:
            self.config["目的地"] = ""
        communicate.task.emit(self)
