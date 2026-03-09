import re
import time
import threading

import win32gui
from pynput import keyboard, mouse

from src.image.hsv_config import HSVRange as hR
from src.ui.RecordOverlay import RecordOverlay


class Recorder:
    """导航录制工具类，监听键鼠操作并生成 route.json 格式的 steps

    用法:
        recorder = Recorder(self)  # self 为 BaseEfTask 实例
        recorder.start()           # 阻塞直到按 F12 停止
        steps = recorder.get_steps()
    """

    # 需要录制的移动按键
    MOVE_KEYS = {'w', 'a', 's', 'd', 'space', 'shift'}

    def __init__(self, task):
        self.task = task
        self.state = "IDLE"  # IDLE / WALKING / ZIPLINING / DONE
        self.steps = []
        self.current_walk_actions = []

        # 按键追踪：记录当前按下的键集合及其起始时间
        self.active_keys = set()
        self.active_keys_start = 0

        # 鼠标追踪：累积 dx/dy，空闲后刷出
        self.mouse_dx = 0
        self.mouse_dy = 0
        self.mouse_last_time = 0
        self.prev_mouse_pos = None
        self._screen_center = self._calc_screen_center()

        # 滑索录制
        self.zipline_nodes = []
        self._zipline_ready = False  # 检测到"登上滑索架"时置 True
        self._current_zipline_distance = None
        self._zipline_mouse_dx = 0
        self._zipline_mouse_dy = 0

        # 监听器
        self._kb_listener = None
        self._mouse_listener = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

    def start(self):
        """开始录制，阻塞直到按 F12 停止"""
        self.state = "WALKING"
        self.active_keys_start = time.time()
        self.task.log_info("录制已开始，按 F12 停止")

        # 显示 OCR 识别框叠加层
        RecordOverlay.show_overlay()

        self._kb_listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        self._mouse_listener = mouse.Listener(
            on_move=self._on_mouse_move,
            on_click=self._on_mouse_click,
        )
        self._kb_listener.start()
        self._mouse_listener.start()

        # 鼠标聚合刷新线程
        flush_thread = threading.Thread(target=self._mouse_flush_loop, daemon=True)
        flush_thread.start()

        # 主循环：处理滑索录制等需要 OCR 的操作
        while not self._stop_event.is_set():
            if self.state == "ZIPLINING":
                self._zipline_record_loop()
            elif self.state == "WALKING":
                self._check_zipline()
                self._draw_ocr_boxes()
                time.sleep(0.5)
            else:
                time.sleep(0.1)

        self._kb_listener.stop()
        self._mouse_listener.stop()

    def get_steps(self):
        """返回录制的 steps 列表"""
        return self.steps

    # ── 键盘回调 ──

    def _on_key_press(self, key):
        if self.state == "DONE":
            return False

        # F12 停止录制
        if key == keyboard.Key.f12:
            self._stop()
            return False

        if self.state == "WALKING":
            if self._is_f_key(key) and self._zipline_ready:
                threading.Thread(target=self._handle_f_key, daemon=True).start()
                return

            key_name = self._to_key_name(key)
            if key_name and key_name in self.MOVE_KEYS and key_name not in self.active_keys:
                with self._lock:
                    self._flush_active_keys()
                    self.active_keys.add(key_name)
                    self.active_keys_start = time.time()

    def _on_key_release(self, key):
        if self.state == "DONE":
            return False

        if self.state == "WALKING":
            key_name = self._to_key_name(key)
            if key_name and key_name in self.active_keys:
                with self._lock:
                    self._flush_active_keys()
                    self.active_keys.discard(key_name)
                    if self.active_keys:
                        self.active_keys_start = time.time()

    # ── 鼠标回调 ──

    def _on_mouse_move(self, x, y):
        if self.state not in ("WALKING", "ZIPLINING"):
            return

        cx, cy = self._screen_center
        with self._lock:
            if self.prev_mouse_pos is not None:
                # 判断是否从中心出发（用户真实移动），忽略回到中心的重置
                prev_at_center = (abs(self.prev_mouse_pos[0] - cx) <= 2
                                  and abs(self.prev_mouse_pos[1] - cy) <= 2)
                if prev_at_center:
                    dx = x - cx
                    dy = y - cy
                    if dx != 0 or dy != 0:
                        if self.state == "ZIPLINING":
                            self._zipline_mouse_dx += dx
                            self._zipline_mouse_dy += dy
                        else:
                            self.mouse_dx += dx
                            self.mouse_dy += dy
                            self.mouse_last_time = time.time()
            self.prev_mouse_pos = (x, y)

    def _on_mouse_click(self, x, y, button, pressed):
        if not pressed:
            return

        if self.state == "ZIPLINING" and button == mouse.Button.left:
            if self._current_zipline_distance is not None:
                node = {"distance": self._current_zipline_distance}
                if self._zipline_mouse_dx or self._zipline_mouse_dy:
                    node["angle_x"] = self._pixels_to_degrees(self._zipline_mouse_dx)
                    node["angle_y"] = self._pixels_to_degrees(self._zipline_mouse_dy)
                self.zipline_nodes.append(node)
                self.task.log_info(
                    f"录制滑索节点: distance={self._current_zipline_distance}, "
                    f"mouse=({self._zipline_mouse_dx}, {self._zipline_mouse_dy})"
                )
                self._current_zipline_distance = None
                self._zipline_mouse_dx = 0
                self._zipline_mouse_dy = 0
            return

        if self.state == "WALKING":
            btn = "left" if button == mouse.Button.left else "right"
            with self._lock:
                self._flush_active_keys()
                self._flush_mouse()
                self.current_walk_actions.append({"type": "click", "button": btn})

    def _mouse_flush_loop(self):
        """定时检查鼠标缓冲，空闲超过 100ms 则刷出"""
        while not self._stop_event.is_set():
            time.sleep(0.1)
            with self._lock:
                if self.mouse_last_time > 0 and time.time() - self.mouse_last_time > 0.1:
                    self._flush_mouse()

    # ── 刷出缓冲 ──

    def _flush_active_keys(self):
        """将当前按键集合输出为一条 walk action"""
        if not self.active_keys or self.active_keys_start <= 0:
            return
        duration = round(time.time() - self.active_keys_start, 2)
        if duration < 0.05:
            return
        keys = sorted(self.active_keys)
        key = keys[0] if len(keys) == 1 else keys
        self.current_walk_actions.append({"key": key, "duration": duration})

    def _flush_mouse(self):
        """将累积的鼠标位移转为角度，输出为一条 angle action"""
        if self.mouse_dx == 0 and self.mouse_dy == 0:
            return
        self.current_walk_actions.append({
            "angle_x": self._pixels_to_degrees(self.mouse_dx),
            "angle_y": self._pixels_to_degrees(self.mouse_dy),
        })
        self.mouse_dx = 0
        self.mouse_dy = 0
        self.mouse_last_time = 0

    def _flush_walk_step(self):
        """将当前 walk actions 打包为一个 step"""
        if self.current_walk_actions:
            self.steps.append({
                "type": "walk",
                "actions": list(self.current_walk_actions),
            })
            self.current_walk_actions = []

    # ── OCR 识别框显示 ──

    def _draw_ocr_boxes(self):
        """全屏 OCR 并显示识别框，让用户实时看到识别结果"""
        task = self.task
        task.next_frame()
        results = task.ocr()
        if results:
            boxes = results if isinstance(results, list) else [results]
            task.draw_boxes("record_ocr", boxes, color="green", debug=False)

    # ── 滑索检测 ──

    def _check_zipline(self):
        """持续检测交互区域是否出现'登上滑索架'，置为 True 后保持，直到被 _handle_f_key 消费"""
        if self._zipline_ready:
            return
        task = self.task
        task.next_frame()
        result = task.ocr(x=0.64, y=0.62, to_x=0.80, to_y=0.68,
                          match=re.compile("登上滑索架"), log=False)
        if result:
            self._zipline_ready = True

    # ── F 键处理 ──

    def _handle_f_key(self):
        """按 F 时检查是否已检测到滑索架，是则进入滑索模式，否则录为普通按键"""
        if self._zipline_ready:
            self.task.log_info("检测到滑索架，进入滑索录制模式")
            with self._lock:
                self._flush_active_keys()
                self._flush_mouse()
                self._flush_walk_step()
            self.zipline_nodes = []
            self._zipline_mouse_dx = 0
            self._zipline_mouse_dy = 0
            self._zipline_ready = False
            self.state = "ZIPLINING"

    # ── 滑索录制 ──

    def _zipline_record_loop(self):
        """滑索模式主循环：持续检测金色距离文字，点击回调立即保存"""
        task = self.task

        while self.state == "ZIPLINING" and not self._stop_event.is_set():
            task.next_frame()

            # 检测是否已回到大世界
            if task.in_world():
                self._exit_zipline()
                return

            # 持续检测金色距离文字，更新 _current_zipline_distance 供点击回调读取
            results = task.ocr(
                x=0.40, y=0.40, to_x=0.60, to_y=0.60,
                frame_processor=task.make_hsv_isolator(hR.GOLD_SELECTED),
            )
            if results:
                boxes = results if isinstance(results, list) else [results]
                task.draw_boxes("record_ocr", boxes, color="green", debug=False)
                for r in boxes:
                    text = r.name if hasattr(r, 'name') else str(r)
                    m = re.search(r'\d+', text)
                    if m:
                        self._current_zipline_distance = int(m.group())
                        break

            task.sleep(0.3)

    def _exit_zipline(self):
        """退出滑索模式，记录节点列表，恢复步行录制"""
        task = self.task
        task.log_info(f"离开滑索架，记录节点: {self.zipline_nodes}")
        if self.zipline_nodes:
            self.steps.append({
                "type": "zipline",
                "nodes": list(self.zipline_nodes),
            })
        self.zipline_nodes = []
        self._zipline_mouse_dx = 0
        self._zipline_mouse_dy = 0
        self.prev_mouse_pos = None
        self.active_keys_start = time.time()
        self.state = "WALKING"

    # ── 停止 ──

    def _stop(self):
        """停止录制，刷出所有缓冲，清除 OCR 识别框"""
        self.task.log_info("录制已停止")
        self.task.clear_box()
        RecordOverlay.hide_overlay()
        with self._lock:
            self._flush_active_keys()
            self._flush_mouse()
            self._flush_walk_step()
        self.state = "DONE"
        self._stop_event.set()

    # ── 工具方法 ──

    @staticmethod
    def _to_key_name(key):
        """将 pynput key 转为字符串名称"""
        if hasattr(key, 'char') and key.char:
            return key.char.lower()
        key_map = {
            keyboard.Key.space: 'space',
            keyboard.Key.shift: 'shift',
            keyboard.Key.shift_l: 'shift',
            keyboard.Key.shift_r: 'shift',
        }
        return key_map.get(key)

    @staticmethod
    def _is_f_key(key):
        return hasattr(key, 'char') and key.char and key.char.lower() == 'f'

    # 一圈360°所需像素 = FULL_CIRCLE_RATIO × 窗口宽度
    FULL_CIRCLE_RATIO = 2.222

    def _calc_screen_center(self):
        """计算游戏窗口在屏幕上的中心坐标"""
        hwnd = self.task.hwnd.hwnd
        left, top, right, bottom = win32gui.GetClientRect(hwnd)
        cx, cy = (right - left) // 2, (bottom - top) // 2
        screen_x, screen_y = win32gui.ClientToScreen(hwnd, (cx, cy))
        return screen_x, screen_y

    def _pixels_to_degrees(self, px):
        """将像素位移转为角度"""
        pixels_per_circle = self.FULL_CIRCLE_RATIO * self.task.width
        return round(px / pixels_per_circle * 360, 2)
