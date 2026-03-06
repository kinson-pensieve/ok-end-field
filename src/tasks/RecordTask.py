from qfluentwidgets import FluentIcon

from src.tasks.BaseNavTask import BaseNavTask
from src.navigation.Recorder import Recorder
from src.navigation.RouteStore import RouteStore
from src.navigation.Teleporter import Teleporter

DEST_TYPES = ["采集物", "矿物", "资源回收站", "送货", "仓储节点", "能量淤积点"]


class RecordTask(BaseNavTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "导航录制"
        self.description = "传送后录制键鼠操作，自动生成导航路线。运行中按F12可终止当前任务"
        self.icon = FluentIcon.ALBUM

        self.store = RouteStore()
        self.teleporter = Teleporter(self)

        # 构建传送点下拉列表
        tp_display_names = ["无"]
        self.tp_mapping = {}
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
            tp_display_names.append(display)
            self.tp_mapping[display] = tp

        self.default_config.update({
            "目的地名称": "",
            "目的地类型": DEST_TYPES[0],
            "传送点": "无",
        })

        self.config_type["目的地类型"] = {
            "type": "drop_down",
            "options": DEST_TYPES,
        }
        self.config_type["传送点"] = {
            "type": "drop_down",
            "options": tp_display_names,
        }

        self.config_description = {
            "目的地名称": "录制路线的名称，如军械库",
            "目的地类型": "目的地交互类型",
            "传送点": "录制起点，程序会先传送到此处",
        }

    def run(self):
        dest_name = self.config.get("目的地名称", "").strip()
        if not dest_name:
            self.log_error("请填写目的地名称")
            return False

        dest_type = self.config.get("目的地类型", "")
        tp_display = self.config.get("传送点", "")

        tp_name = ""
        area = ""

        if tp_display and tp_display != "无":
            tp_info = self.tp_mapping.get(tp_display)
            if not tp_info:
                self.log_error(f"未找到传送点: {tp_display}")
                return False
            tp_name = tp_info.get("name", "")
            area = tp_info.get("area", "")

            # 1. 传送到起点
            self.log_info(f"传送到: {tp_name}")
            if not self.teleporter.teleport_to(tp_name):
                self.log_error(f"传送到 {tp_name} 失败")
                return False
            self.ensure_main()
            self.sleep(2)

        # 2. 通知用户即将开始录制
        self.notification("3秒后开始录制，按 F12 停止")
        self.sleep(3)

        # 3. 开始录制（阻塞直到按 F12）
        recorder = Recorder(self)
        recorder.start()

        # 4. 保存录制结果
        steps = recorder.get_steps()
        if not steps:
            self.log_error("录制结果为空，未保存")
            return False

        route = {
            "name": dest_name,
            "type": dest_type,
            "area": area,
            "teleport": tp_name,
            "steps": steps,
        }

        self.store.save(route)
        self.store.flush()
        self._reload_navigators()
        self.log_info(f"路线已保存: {dest_name}", notify=True)
        return True

    def _reload_navigators(self):
        """通知所有持有 RouteStore 的任务重新加载路线数据"""
        for task in self.executor.onetime_tasks + self.executor.trigger_tasks:
            if hasattr(task, 'reload_routes'):
                task.reload_routes()
                self.log_info(f"已重新加载 {task.name} 的路线数据")
            elif hasattr(task, 'store') and isinstance(task.store, RouteStore):
                task.store.reload()
                self.log_info(f"已重新加载 {task.name} 的路线数据")
