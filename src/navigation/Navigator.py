import threading

from pynput import keyboard

from ok.gui.Communicate import communicate
from src.navigation.Interactor import Interactor
from src.navigation.RouteStore import RouteStore
from src.navigation.Teleporter import Teleporter
from src.navigation.Zipliner import Zipliner
from src.navigation.Walker import Walker


class Navigator:
    """导航编排类，通过 RouteStore 获取路线并串联传送、滑索、步行完成完整路线

    用法:
        navigator = Navigator(self)  # self 为任意 BaseEfTask 实例
        navigator.navigate_to("军械库")
    """

    def __init__(self, task, store: RouteStore = None):
        """
        Args:
            task: BaseEfTask 实例
            store: RouteStore 实例，不传则新建
        """
        self.task = task
        self.store = store or RouteStore()
        self.teleporter = Teleporter(task)
        self.zipliner = Zipliner(task)
        self.walker = Walker(task)
        self.interactor = Interactor(task)
        self._stop_event = threading.Event()
        self._kb_listener = None
        self._debug_mode = False
        self._step_event = threading.Event()

    def set_debug_mode(self, enabled):
        """设置调试模式"""
        self._debug_mode = enabled
        if not enabled:
            self._step_event.set()  # 关闭调试时立即放行

    def step_next(self):
        """单步放行"""
        self._step_event.set()

    def _debug_wait(self, step_idx, detail_idx, summary):
        """调试断点：更新状态文本并阻塞等待放行"""
        if not self._debug_mode:
            return True
        self.task.info_set("调试", f"步骤{step_idx + 1} 第{detail_idx + 1}个: {summary} | 等待下一步...")
        communicate.task.emit(self.task)
        self._step_event.clear()
        while not self._step_event.wait(0.1):
            if self._stop_event.is_set():
                return False
        self.task.info_set("调试", "执行中...")
        return True

    def _start_kb_listener(self):
        """启动键盘监听: F11=单步, F12=停止"""
        self._stop_event.clear()

        def on_press(key):
            if key == keyboard.Key.f12:
                self._stop_event.set()
                self._step_event.set()  # 解除调试等待
                return False
            elif key == keyboard.Key.f11:
                if self._debug_mode:
                    self.step_next()

        self._kb_listener = keyboard.Listener(on_press=on_press)
        self._kb_listener.start()

    def _stop_kb_listener(self):
        """停止键盘监听"""
        if self._kb_listener:
            self._kb_listener.stop()
            self._kb_listener = None

    def navigate_to(self, name, dest_type=None, need_scroll=False) -> bool:
        """导航到指定目的地，执行完整路线：传送 → steps(滑索/步行)
        导航过程中可按 F11 单步执行，F12 停止。

        Args:
            name: 目的地名称
            dest_type: 目的地类型，用于同名不同类型的消歧
            need_scroll: 是否启用滚动放大视角（传给 Zipliner）

        Returns:
            bool: 是否成功到达
        """
        task = self.task
        dest = self.store.find(name, dest_type=dest_type)
        if not dest:
            task.log_error(f"未找到目的地: {name}")
            return False

        teleport_point = dest.get("teleport")
        steps = dest.get("steps", [])

        task.log_info(f"开始导航到: {name} (类型: {dest.get('type')}, 地图: {dest.get('area')})")

        # 启动键盘监听 (F11/F12)
        self._start_kb_listener()

        try:
            # 传送到起始点
            if teleport_point:
                task.log_info(f"传送到: {teleport_point}")
                if not self.teleporter.teleport_to(teleport_point, stop_event=self._stop_event):
                    if self._stop_event.is_set():
                        task.log_info("传送被 F12 中断")
                        return False
                    task.log_error(f"传送到 {teleport_point} 失败")
                    return False
                task.ensure_main()

            # 传送完成后调试暂停
            if teleport_point and self._debug_mode:
                if not self._debug_wait(0, 0, f"传送到 {teleport_point} 完成"):
                    task.log_info("导航已停止")
                    return False

            # 按顺序执行 steps
            for i, step in enumerate(steps):
                if self._stop_event.is_set():
                    task.log_info("导航已被 F12 停止")
                    return False

                step_type = step.get("type")
                task.log_info(f"执行步骤 {i + 1}/{len(steps)}: {step_type}")

                # 构造调试回调，绑定当前 step_idx（始终传递，由 _debug_wait 内部判断是否生效）
                debug_cb = (lambda si: lambda di, s: self._debug_wait(si, di, s))(i)

                if step_type == "walk":
                    actions = step.get("actions", [])
                    if not self.walker.execute(actions, stop_event=self._stop_event, debug_callback=debug_cb):
                        task.log_info("导航已停止")
                        return False

                elif step_type == "zipline":
                    nodes = step.get("nodes", [])
                    if not self.zipliner.execute(nodes, need_scroll=need_scroll, stop_event=self._stop_event, debug_callback=debug_cb):
                        task.log_info("导航已停止")
                        return False

                else:
                    task.log_error(f"未知步骤类型: {step_type}")

            # 导航完成后执行交互
            dest_type = dest.get("type")
            if dest_type:
                task.log_info(f"开始交互: {dest_type}")
                self.interactor.execute(dest_type, dest)

            task.log_info(f"已到达目的地: {name}")
            return True
        finally:
            self._stop_kb_listener()
