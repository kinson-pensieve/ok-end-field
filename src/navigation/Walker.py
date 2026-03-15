class Walker:
    """步行工具类，按预录指令序列执行步行/视角操作，可被任意 Task 调用

    用法:
        walker = Walker(self)  # self 为任意 BaseEfTask 实例
        walker.execute([
            {"key": "w", "duration": 3},
            {"key": ["w", "a"], "duration": 1.5},
            {"type": "mouse", "dx": 15.5, "dy": 0},
        ])
    """

    # 一圈360°所需像素 = FULL_CIRCLE_RATIO × 窗口宽度
    FULL_CIRCLE_RATIO = 2.222

    def __init__(self, task):
        """
        Args:
            task: BaseEfTask 实例，用于调用 move_keys、日志等方法
        """
        self.task = task

    def _degrees_to_pixels(self, degrees):
        """将角度转为像素位移"""
        pixels_per_circle = self.FULL_CIRCLE_RATIO * self.task.width
        return round(degrees / 360 * pixels_per_circle)

    def execute(self, actions, stop_event=None, debug_callback=None):
        """按顺序执行步行/视角/点击指令序列

        Args:
            actions: 指令列表，每项可包含以下字段（同一 action 中可组合，按顺序执行）:
                等待: {"sleep": 1.0}
                鼠标视角: {"angle_x": 90, "angle_y": 0}  (角度)
                鼠标偏移: {"mouse_x": 200, "mouse_y": 0}  (像素)
                鼠标点击: {"button": "left"/"right"}
                按键指令: {"key": "w", "duration": 0.4}
                组合示例: {"angle_x": 90, "key": "w", "duration": 1.0, "after_sleep": 0.5}
                所有 action 可附加 "after_sleep": 0.5 在最后等待
            stop_event: 可选的 threading.Event，触发时中断执行
            debug_callback: 可选回调 (detail_idx, summary) → bool，动作完毕后调用

        Returns:
            bool: True 正常完成，False 被中断
        """
        task = self.task
        for i, action in enumerate(actions):
            if stop_event and stop_event.is_set():
                return False

            # 1. 等待
            if "sleep" in action:
                duration = action["sleep"]
                task.log_debug(f"步行指令 {i + 1}/{len(actions)}: sleep {duration}s")
                task.sleep(duration)

            # 2. 视角调整（角度）
            if "angle_x" in action:
                dx = self._degrees_to_pixels(action["angle_x"])
                dy = self._degrees_to_pixels(action.get("angle_y", 0))
                task.log_debug(f"步行指令 {i + 1}/{len(actions)}: angle {action['angle_x']}°/{action.get('angle_y', 0)}° → {dx}px/{dy}px")
                task.active_and_send_mouse_delta(dx, dy)

            # 3. 鼠标偏移（像素，兼容旧格式）
            if "mouse_x" in action:
                dx = action["mouse_x"]
                dy = action.get("mouse_y", 0)
                task.log_debug(f"步行指令 {i + 1}/{len(actions)}: mouse dx={dx}px, dy={dy}px")
                task.active_and_send_mouse_delta(dx, dy)

            # 4. count 包裹按键
            if "key" in action:
                key = action["key"]
                duration = action["duration"]
                count = action.get("count", 1)
                for j in range(count):
                    if stop_event and stop_event.is_set():
                        return False
                    task.log_debug(f"步行指令 {i + 1}/{len(actions)}: key={key}, duration={duration}s")
                    task.move_keys(key, duration)
                    task.sleep(0.2)

            # 4.2 点击
            if "button" in action:
                button = action["button"]
                task.log_debug(f"步行指令 {i + 1}/{len(actions)}: click {button}")
                task.click(key=button)

            # 4.3 执行后等待
            after_sleep = action.get("after_sleep")
            if after_sleep:
                task.sleep(after_sleep)

            if debug_callback:
                from src.ui.RouteEditorWidget import _action_summary
                if not debug_callback(i, _action_summary(action)):
                    return False
        return True
