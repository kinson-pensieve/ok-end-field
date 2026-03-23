import random
import re
import time

from src.image.hsv_config import HSVRange as hR

on_zip_line_tip = ["向目标移动", "离开滑索架"]
on_zip_line_stop = [re.compile(i) for i in on_zip_line_tip]
ZIP_LINE_TIP_BOX = (0.35, 0.94, 0.65, 0.98)


class Zipliner:
    """滑索工具类，根据节点列表依次选择并滑行多个滑索

    用法:
        zipliner = Zipliner(self)  # self 为任意 BaseEfTask 实例
        zipliner.execute([
            {"distance": 66},
            {"distance": 108, "mouse_x": 15.5, "mouse_y": 0},
            {"distance": 53},
        ])
    """

    # 一圈360°所需像素 = FULL_CIRCLE_RATIO × 窗口宽度
    FULL_CIRCLE_RATIO = 2.222

    def __init__(self, task):
        """
        Args:
            task: BaseEfTask 实例，用于调用 OCR、点击、日志等方法
        """
        self.task = task

    def _degrees_to_pixels(self, degrees):
        """将角度转为像素位移"""
        pixels_per_circle = self.FULL_CIRCLE_RATIO * self.task.width
        return round(degrees / 360 * pixels_per_circle)

    def _mount_zipline(self, stop_event=None):
        """检测并登上滑索架

        检测屏幕右下角是否有"登上滑索架"提示，有则按 F 登上，
        然后等待屏幕底部出现"向目标移动"或"离开滑索架"确认已在滑索上。
        """
        task = self.task
        if task.ocr(match=re.compile("登上滑索架"), box="bottom_right", log=True):
            task.log_info("检测到滑索架，按F登上")
            task.send_key("f", after_sleep=2)
            start = time.time()
            retry = 0
            while True:
                if stop_event and stop_event.is_set():
                    return False
                task.next_frame()
                task.sleep(0.1)
                mount_result = task.ocr(box=task.box_of_screen(*ZIP_LINE_TIP_BOX))
                if mount_result:
                    task.log_debug(f"登上检测: {[r.name for r in mount_result]}")
                    matched = [r for r in mount_result
                              if any(len(set(r.name) & set(tip)) >= 3 for tip in on_zip_line_tip)]
                    if matched:
                        task.log_info("已成功登上滑索架")
                        return True
                retry += 1
                if retry % 5 == 0:
                    jitter = random.randint(-3, 3)
                    task.active_and_send_mouse_delta(jitter, 0)
                if time.time() - start > 30:
                    task.log_error("登上滑索架超时")
                    return False
        return True

    def _scan_target(self, frame, distance_pattern, box=None, gold_only=False):
        """扫描目标距离数字

        Args:
            frame: 当前帧图像
            distance_pattern: 距离数字的正则匹配模式
            box: 搜索区域，None 为默认区域
            gold_only: 是否只扫描金色

        Returns:
            (result, is_gold): result 为 OCR 结果对象，is_gold 表示是否金色命中
        """
        task = self.task

        # 先扫金色
        gold_result = task.ocr(
            box=box, frame=frame,
            frame_processor=task.make_hsv_isolator(hR.GOLD_SELECTED),
        )
        if gold_result:
            matched = [r for r in gold_result if distance_pattern.search(r.name)]
            if matched:
                return matched[0], True

        if gold_only:
            return None, False

        # 再扫白色
        white_result = task.ocr(
            box=box, frame=frame,
            frame_processor=task.make_hsv_isolator(hR.WHITE),
        )
        if white_result:
            matched = [r for r in white_result if distance_pattern.search(r.name)]
            if matched:
                return matched[0], False

        return None, False

    def _pixels_to_degrees(self, pixels):
        """将像素位移转为角度"""
        pixels_per_circle = self.FULL_CIRCLE_RATIO * self.task.width
        return round(pixels / pixels_per_circle * 360, 2)

    def _calc_offset(self, result):
        """计算 OCR 结果相对屏幕中心的偏移，含 is_num Y 补偿

        Returns:
            (angle_x, angle_y, px_dx, px_dy): 角度偏移和像素偏移
        """
        task = self.task
        # is_num Y 补偿：数字位置偏差修正
        adjusted_y = result.y - int(task.height * ((525 - 486) / 1080))
        target_center_x = result.x + result.width // 2
        target_center_y = adjusted_y + result.height // 2
        screen_cx, screen_cy = task.screen_center()
        px_dx = target_center_x - screen_cx
        px_dy = target_center_y - screen_cy
        angle_x = self._pixels_to_degrees(px_dx)
        angle_y = self._pixels_to_degrees(px_dy)
        return angle_x, angle_y, px_dx, px_dy

    def _align_to_target(self, distance, tolerance=10, max_attempts=50, stop_event=None):
        """滑索专用对中方法：角度开环移动 + 白色消失确认 + 金色精调

        Args:
            distance: 目标距离数字（整数）
            tolerance: 对中容差（像素）
            max_attempts: 最大尝试次数
            stop_event: 可选的 threading.Event，触发时中断执行

        Returns:
            bool: 是否对齐成功
        """
        task = self.task
        pattern = re.compile(str(distance))
        # 阶段2搜索框：屏幕中心正方形（以宽度40%为边长，768×768 @1080p）
        half_ratio = 0.20  # 宽度的40%的一半
        v_half = half_ratio * task.width / task.height  # 等像素换算为高度比例
        small_box = task.box_of_screen(0.5 - half_ratio, 0.5 - v_half,
                                       0.5 + half_ratio, 0.5 + v_half)
        # 阶段3搜索框：更小的中心正方形（以宽度20%为边长，384×384 @1080p）
        tiny_ratio = 0.10
        tv_half = tiny_ratio * task.width / task.height
        tiny_box = task.box_of_screen(0.5 - tiny_ratio, 0.5 - tv_half,
                                      0.5 + tiny_ratio, 0.5 + tv_half)
        tolerance_deg = self._pixels_to_degrees(tolerance)

        for attempt in range(max_attempts):
            if stop_event and stop_event.is_set():
                return False
            # ── 阶段1: 大范围扫描（金色+白色）──
            frame = task.next_frame()
            result, is_gold = self._scan_target(frame, pattern)

            if result is None:
                # 没找到目标，系统化扫描：每次固定转30°
                scan_deg = 30 if (attempt % 12) < 6 else -30
                scan_px = self._degrees_to_pixels(scan_deg)
                task.log_info(f"对齐第{attempt + 1}轮: 未找到目标，系统扫描 {scan_deg}°")
                task.active_and_send_mouse_delta(scan_px, 0)
                task.sleep(0.2)
                continue

            angle_x, angle_y, px_dx, px_dy = self._calc_offset(result)
            color = "金色" if is_gold else "白色"
            task.log_info(f"对齐第{attempt + 1}轮: {color}命中, "
                          f"像素=({px_dx},{px_dy})")

            # 如果金色且已在容差内，直接完成
            if is_gold and abs(px_dx) <= tolerance and abs(px_dy) <= tolerance:
                task.log_info(f"对齐完成: 角度=({angle_x}°,{angle_y}°), "
                              f"像素=({px_dx},{px_dy}), 轮次={attempt + 1}")
                return True

            # 一步移动到目标位置（白色打折避免过冲）
            scale = 0.85 if not is_gold else 1.0
            move_px_x = self._degrees_to_pixels(angle_x * scale)
            move_px_y = self._degrees_to_pixels(angle_y * scale)
            task.log_debug(f"执行移动: {angle_x}°/{angle_y}° ×{scale} → {move_px_x}px/{move_px_y}px")

            task.active_and_send_mouse_delta(move_px_x, move_px_y)
            task.sleep(0.15)

            # 只有金色命中且偏移在阶段2搜索范围内才进入精调，否则回阶段1继续逼近
            if not (is_gold and abs(px_dx) <= half_ratio * task.width and abs(px_dy) <= v_half * task.height):
                continue

            # ── 阶段2: 小范围金色精调（带文字匹配）──
            small_fail = 0
            small_total = 0
            last_good_dx = None  # 最后一次成功检测的偏移
            last_good_dy = None
            while small_fail < 10 and small_total < 30:
                if stop_event and stop_event.is_set():
                    return False
                frame = task.next_frame()
                result, is_gold = self._scan_target(frame, pattern, box=small_box, gold_only=True)

                small_total += 1
                if is_gold:
                    small_fail = 0  # 找到金色，重置连续失败计数
                    angle_x, angle_y, px_dx, px_dy = self._calc_offset(result)
                    last_good_dx = px_dx
                    last_good_dy = px_dy
                    task.log_debug(f"阶段2: 金色命中, "
                                   f"角度=({angle_x}°,{angle_y}°), 像素=({px_dx},{px_dy})")
                    if abs(px_dx) <= tolerance and abs(px_dy) <= tolerance:
                        task.log_info(f"对齐完成(阶段2): 像素=({px_dx},{px_dy}), 轮次={attempt + 1}")
                        return True
                    # 微调（衰减系数防止震荡）
                    adj_px_x = self._degrees_to_pixels(angle_x * 0.85)
                    adj_px_y = self._degrees_to_pixels(angle_y * 0.85)
                    task.log_debug(f"阶段2微调: {angle_x}°/{angle_y}° ×0.85 → {adj_px_x}px/{adj_px_y}px")
                    task.active_and_send_mouse_delta(adj_px_x, adj_px_y)
                    task.sleep(0.1)
                else:
                    small_fail += 1
                    # 每3次失败小幅随机抖动，避免3D遮挡导致固定角度识别失败
                    if small_fail % 3 == 0:
                        jitter = random.randint(-5, 5)
                        task.active_and_send_mouse_delta(jitter, 0)
                    task.sleep(0.1)

            # 阶段2退出后判断：最后偏移接近容差且丢失了数字 → 进阶段3，否则回阶段1
            near_center = (last_good_dx is not None
                           and abs(last_good_dx) <= tolerance * 3
                           and abs(last_good_dy) <= tolerance * 3)
            if not near_center:
                task.log_info(f"阶段2退出: 目标不够近(last={last_good_dx},{last_good_dy})，回退阶段1")
                continue
            # ── 阶段3: 纯金色位置确认（不匹配文字）──
            task.log_info("进入阶段3: 纯金色位置确认")
            phase3_fail = 0
            phase3_total = 0
            while phase3_fail < 10 and phase3_total < 30:
                if stop_event and stop_event.is_set():
                    return False
                phase3_total += 1
                frame = task.next_frame()
                gold_raw = task.ocr(
                    box=tiny_box, frame=frame,
                    frame_processor=task.make_hsv_isolator(hR.GOLD_SELECTED),
                )
                if gold_raw:
                    phase3_fail = 0
                    _, _, raw_dx, raw_dy = self._calc_offset(gold_raw[0])
                    task.log_debug(f"阶段3: 金色检测, 像素=({raw_dx},{raw_dy})")
                    if abs(raw_dx) <= tolerance and abs(raw_dy) <= tolerance:
                        task.log_info(f"对齐完成(阶段3): 像素=({raw_dx},{raw_dy}), 轮次={attempt + 1}")
                        return True
                    adj_px_x = round(raw_dx * 0.85)
                    adj_px_y = round(raw_dy * 0.85)
                    task.log_debug(f"阶段3微调: {raw_dx}px/{raw_dy}px ×0.85 → {adj_px_x}px/{adj_px_y}px")
                    task.active_and_send_mouse_delta(adj_px_x, adj_px_y)
                    task.sleep(0.1)
                else:
                    phase3_fail += 1
                    if phase3_fail % 3 == 0:
                        jitter = random.randint(-5, 5)
                        task.active_and_send_mouse_delta(jitter, 0)
                    task.sleep(0.1)

            # 阶段2+3 均失败，回退到阶段1
            task.log_info(f"阶段3连续{phase3_fail}次失败，回退重新搜索")

        task.log_error(f"滑索对齐失败: 共尝试{max_attempts}轮, 容差={tolerance}px/{tolerance_deg}°")
        raise Exception("滑索对中失败")

    def execute(self, nodes, need_scroll=False, stop_event=None, debug_callback=None):
        """按节点列表依次滑行多个滑索

        先检测是否需要登上滑索架，确认在滑索上后，
        对每个节点：若有 mouse_x/mouse_y 先调整视角，然后对齐距离 → 点击 → 等待到达

        Args:
            nodes: 滑索节点列表，例如 [{"distance": 66}, {"distance": 108, "mouse_x": 200, "mouse_y": 0}]
            need_scroll: 是否启用滚动放大视角以提高对齐成功率
            stop_event: 可选的 threading.Event，触发时中断执行
            debug_callback: 可选回调 (detail_idx, summary) → bool，节点到达后调用

        Returns:
            bool: True 正常完成，False 被中断
        """
        task = self.task

        # 检测并登上滑索架
        if not self._mount_zipline(stop_event=stop_event):
            if stop_event and stop_event.is_set():
                return False
            raise Exception("无法登上滑索架")

        for i, node in enumerate(nodes):
            if stop_event and stop_event.is_set():
                task.send_key("esc", after_sleep=2)
                return False
            distance = node["distance"]

            # 对齐前移动鼠标调整视角
            if "angle_x" in node or "angle_y" in node:
                ax = node.get("angle_x", 0)
                ay = node.get("angle_y", 0)
                px = self._degrees_to_pixels(ax)
                py = self._degrees_to_pixels(ay)
                task.log_info(f"滑索 {i + 1}/{len(nodes)}: 调整视角 {ax}°/{ay}° → {px}px/{py}px")
                task.active_and_send_mouse_delta(px, py)
                task.sleep(0.5)
            elif "mouse_x" in node or "mouse_y" in node:
                mx = node.get("mouse_x", 0)
                my = node.get("mouse_y", 0)
                task.log_info(f"滑索 {i + 1}/{len(nodes)}: 调整视角 mouse {mx}px/{my}px")
                task.active_and_send_mouse_delta(mx, my)
                task.sleep(0.5)

            if node.get("direct_click"):
                task.log_info(f"滑索 {i + 1}/{len(nodes)}: 直接点击（跳过对齐）")
            else:
                task.log_info(f"滑索 {i + 1}/{len(nodes)}: 对齐距离 {distance}")
                if not self._align_to_target(distance, stop_event=stop_event):
                    if stop_event and stop_event.is_set():
                        return False

            task.click(after_sleep=0.5)
            start = time.time()
            while True:
                if stop_event and stop_event.is_set():
                    task.send_key("esc", after_sleep=2)
                    return False
                task.next_frame()
                task.sleep(0.1)
                result = task.ocr(
                    match=on_zip_line_stop,
                    box=task.box_of_screen(*ZIP_LINE_TIP_BOX),
                )
                if result:
                    break
                if time.time() - start > 60:
                    raise Exception("滑索超时，强制退出")

            if debug_callback:
                if not debug_callback(i, f"距离 {distance}"):
                    task.send_key("esc", after_sleep=2)
                    return False
        task.log_info(f"滑索序列完成，共滑行 {len(nodes)} 段")
        task.send_key("esc", after_sleep=2)
        task.log_info("已离开滑索架")
        return True
