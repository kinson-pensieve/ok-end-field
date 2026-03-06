import ctypes
import random
import re
import time
from functools import partial

import pyautogui

from src.interaction.Mouse import active_and_send_mouse_delta
from src.tasks.BaseEfTask import BaseEfTask, TOLERANCE

user32 = ctypes.windll.user32
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004


class BaseNavTask(BaseEfTask):
    """导航相关任务的中间基类，覆盖 BaseEfTask 中需要定制的方法"""

    def make_hsv_isolator(self, ranges, kernel_size=2):
        return partial(self.isolate_by_hsv_ranges, ranges=ranges, kernel_size=kernel_size)

    def align_ocr_or_find_target_to_center(
            self,
            ocr_match_or_feature_name_list,
            only_x=False,
            only_y=False,
            box=None,
            threshold=0.8,
            max_time=50,
            ocr=True,
            raise_if_fail=True,
            is_num=False,
            need_scroll=False,
            max_step=100,
            min_step=10,
            slow_radius=200,
            once_time=0.2,
            tolerance=TOLERANCE,
            ocr_frame_processor_list=None,
            scan_timeout=1,
    ):
        if box:
            feature_box = box
        else:
            feature_box = self.box_of_screen(
                (1920 - 1550) / 1920,
                150 / 1080,
                1550 / 1920,
                (1080 - 150) / 1080,
            )
        last_target = None
        last_target_fail_count = 0
        success = False
        random_move_count = 0
        move_count = 0
        scroll_bool = False
        sum_dx = 0
        sum_dy = 0
        for i in range(max_time):
            start_action_time = time.time()
            if ocr:
                start_time = time.time()
                result = None
                if not isinstance(ocr_frame_processor_list, list):
                    ocr_frame_processor_list = [ocr_frame_processor_list]
                while time.time() - start_time < scan_timeout:
                    frame = self.next_frame()
                    for proc_idx, ocr_frame_processor in enumerate(ocr_frame_processor_list):
                        all_text = self.ocr(
                            box=box,
                            frame=frame,
                            frame_processor=ocr_frame_processor,
                        )
                        if all_text and ocr_match_or_feature_name_list:
                            result = [r for r in all_text if ocr_match_or_feature_name_list.search(r.name)] if hasattr(ocr_match_or_feature_name_list, 'search') else [r for r in all_text if r.name == ocr_match_or_feature_name_list]
                            result = result if result else None
                        if result:
                            break
                    if result:
                        break
                    time.sleep(0.1)
            else:
                if isinstance(ocr_match_or_feature_name_list, str):
                    ocr_match_or_feature_name_list = [ocr_match_or_feature_name_list]
                start_time = time.time()
                result = None
                while True:
                    if time.time() - start_time >= scan_timeout:
                        break
                    self.next_frame()
                    for feature_name in ocr_match_or_feature_name_list:
                        if time.time() - start_time >= scan_timeout:
                            break
                        result = self.find_feature(
                            feature_name=feature_name,
                            threshold=threshold,
                            box=feature_box,
                        )
                        if result:
                            break
                    if result:
                        break
                    self.sleep(0.1)
            if result:
                success = True
                random_move_count = 0
                move_count = 0
                if isinstance(result, list):
                    result = result[0]
                if is_num:
                    result.y = result.y - int(self.height * ((525 - 486) / 1080))
                if only_y:
                    result.x = self.width // 2 - result.width // 2
                if only_x:
                    result.y = self.height // 2 - result.height // 2
                target_center = (
                    result.x + result.width // 2,
                    result.y + result.height // 2,
                )
                screen_center_pos = self.screen_center()
                last_target = result
                last_target_fail_count = 0
                dx = target_center[0] - screen_center_pos[0]
                dy = target_center[1] - screen_center_pos[1]
                if abs(dx) <= tolerance and abs(dy) <= tolerance:
                    self.log_info(f"对齐完成: 偏移=({dx},{dy}), 轮次={i+1}")
                    return True
                else:
                    dx, dy = self.move_to_target_once(result, max_step=max_step, min_step=min_step,
                                                      slow_radius=slow_radius)
                    sum_dx += dx
                    sum_dy += dy

            else:
                max_offset = 60
                if last_target:
                    decay = 0.9 ** last_target_fail_count
                    screen_center_x, screen_center_y = self.screen_center()
                    offset_x = int((screen_center_x - last_target.x) * decay)
                    offset_y = int((screen_center_y - last_target.y) * decay)
                    offset_width = int(last_target.width / 2 * decay)
                    offset_height = int(last_target.height / 2 * decay)
                    last_target.x = screen_center_x - offset_x
                    last_target.y = screen_center_y - offset_y
                    last_target.width = offset_width
                    last_target.height = offset_height
                    dx, dy = self.move_to_target_once(last_target)
                    sum_dx += dx
                    sum_dy += dy
                    last_target_fail_count += 1
                    random_move_count = 0
                    move_count += 1
                    if move_count >= 10:
                        last_target = None
                        move_count = 0
                else:
                    if not success:
                        max_offset = self.width // 4
                    last_target = None
                    last_target_fail_count = 0
                    dx = random.randint(-max_offset, max_offset)
                    if not success:
                        dy = 0
                    else:
                        dy = random.randint(-max_offset, max_offset)
                    active_and_send_mouse_delta(
                        self.hwnd.hwnd,
                        dx,
                        dy,
                        activate=True,
                    )
                    sum_dx += dx
                    sum_dy += dy
                    move_count = 0
                    random_move_count += 1
                    if random_move_count >= 10:
                        success = False
                        random_move_count = 0

            if time.time() - start_action_time < once_time:
                self.sleep(once_time - (time.time() - start_action_time))
            if not scroll_bool and need_scroll:
                scroll_bool = True
                for _ in range(6):
                    pyautogui.scroll(80)
                    self.sleep(1)
        self.log_error(f"对齐失败: 共尝试{max_time}轮, 累计移动=({sum_dx},{sum_dy})")
        if raise_if_fail:
            raise Exception("对中失败")
        else:
            return False

    def to_model_area(self, area, model):
        self.send_key("y", after_sleep=2)
        if not self.wait_click_ocr(
                match="更换", box="left", time_out=2, after_sleep=2
        ):
            return
        if not self.wait_click_ocr(
                match=re.compile(area),
                box=self.box_of_screen(
                    648 / 1920, 196 / 1080, 648 / 1920 + 628 / 1920, 196 / 1080 + 192 / 1080
                ),
                time_out=2,
                after_sleep=2,
        ):
            return
        if not self.wait_click_ocr(
                match="确认",
                box="bottom_right",
                time_out=2,
                after_sleep=2,
        ):
            return
        box = self.wait_ocr(
            match=re.compile(f"{model}"), box="right", time_out=5
        )
        if box:
            self.click(box[0], move_back=True, after_sleep=0.5)
        else:
            self.log_error(f"未找到'{model}'按钮，任务中止。")
            return

    def skip_dialog(self, end_list=re.compile("确认"), end_box=None):
        if not end_box:
            end_box = "bottom_right"
        start_time = time.time()
        while True:
            if time.time() - start_time > 60:
                self.log_info("skip_dialog 超时退出")
                return False
            if self.wait_ocr(match=["工业", "探索"], box="top_left", time_out=1.5):
                return True
            if self.find_one("skip_dialog_esc", horizontal_variance=0.05):
                self.send_key("esc", after_sleep=0.1)
                start = time.time()
                clicked_confirm = False
                while time.time() - start < 3:
                    confirm = self.find_confirm()
                    if confirm:
                        self.click(confirm, after_sleep=0.4)
                        clicked_confirm = True
                    elif clicked_confirm:
                        self.log_debug("AutoSkipDialogTask no confirm break")
                        return True
            if end_list and self.wait_click_ocr(match=end_list, box=end_box, time_out=0.5):
                return True

    def ensure_main(self, esc=True, time_out=30, after_sleep=2):
        self.info_set("current task", f"wait main esc={esc}")
        if not self.wait_until(
                lambda: self.is_main(esc=esc), time_out=time_out, raise_if_not_found=False
        ):
            raise Exception("Please start in game world and in team!")
        self.sleep(after_sleep)
        self.info_set("current task", f"in main esc={esc}")

    def is_main(self, esc=False):
        self.next_frame()
        if self.in_world():
            self._logged_in = True
            return True
        if self.wait_login():
            return True
        if result := self.ocr(match=re.compile("结束拜访"), box="bottom_right"):
            self.click(result, after_sleep=1.5)
            return False
        if result := self.ocr(match=[re.compile("确认"), re.compile("确定")], box="bottom_right"):
            self.click(result, after_sleep=1.5)
            return False
        if esc:
            self.back(after_sleep=1.5)
            return False
        return False

    def wait_pop_up(self, after_sleep=0):
        count = 0
        while True:
            if count > 30:
                return False
            result = self.find_one(
                feature_name="reward_ok", box="bottom", threshold=0.8
            )
            if result:
                self.click(result, after_sleep=after_sleep)
                return True
            self.sleep(1)
            count += 1

    def drag_mouse(self, dx, dy, steps=10, hold_time=0.1, release_delay=0.1):
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        self.sleep(hold_time)

        for _ in range(steps):
            step_dx = dx // steps
            step_dy = dy // steps
            user32.mouse_event(MOUSEEVENTF_MOVE, step_dx, step_dy, 0, 0)
            time.sleep(0.02)

        self.sleep(release_delay)

        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
