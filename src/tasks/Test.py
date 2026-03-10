from src.tasks.BaseEfTask import BaseEfTask
from src.tasks.AutoCombatTask import (
    has_rectangles,
    isolate_white_text_to_black,
    yellow_skill_color,
    white_skill_color,
)
from src.data.FeatureList import FeatureList as fL
import re
import numpy as np

class Test(BaseEfTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "测试"
        self.lv_regex = re.compile(r"(?i)lv|\d{2}")

    def test_times_ocr(self):
        box1 = self.box_of_screen(1749 / 1920, 107 / 1080, 1789 / 1920, 134 / 1080)
        box2 = self.box_of_screen(
            (1749 + (1832 - 1750)) / 1920,
            107 / 1080,
            (1789 + (1832 - 1750)) / 1920,
            134 / 1080,
        )
        self.wait_click_ocr(
            match=re.compile(r"^\d+/5$"),
            after_sleep=2,
            time_out=2,
            box=box1,
            log=True,
        )
        self.wait_click_ocr(
            match=re.compile(r"^\d+/5$"),
            after_sleep=2,
            time_out=2,
            box=box2,
            log=True,
        )
    def test_room_ocr(self):
        self.wait_click_ocr(match=[re.compile(i) for i in ["会客", "培养", "制造"]], time_out=5, after_sleep=2,log=True)

    def run(self):
        self.log_info("开始监控战斗状态")

        was_in_combat = False

        while True:
            is_in_combat = self.in_combat(required_yellow=1)

            if is_in_combat and not was_in_combat:
                if self.debug:
                    self.screenshot('test_enter_combat')
                self.log_info("战斗进入状态", notify=True)

            if not is_in_combat and was_in_combat:
                if self.debug:
                    self.screenshot('test_out_of_combat')
                self.log_info("战斗退出状态", notify=True)

            was_in_combat = is_in_combat
            self.sleep(0.05)

    def ocr_lv(self):
        lv = self.ocr(0.02, 0.89, 0.23, 0.93, match=self.lv_regex, name='lv_text')
        if len(lv) > 0:
            return True
        lv = self.ocr(
            0.02,
            0.89,
            0.23,
            0.93,
            frame_processor=isolate_white_text_to_black,
            match=self.lv_regex,
            name='lv_text'
        )
        return len(lv) > 0

    def in_combat(self, required_yellow=0):
        return self.get_skill_bar_count() >= required_yellow and self.in_team() and not self.ocr_lv()

    def in_team(self):
        return self.find_one('skill_1') and self.find_one('skill_2') and self.find_one('skill_3') and self.find_one(
            'skill_4')

    def get_skill_bar_count(self):
        skill_area_box = self.box_of_screen_scaled(3840, 2160, 1586, 1940, 2266, 1983)
        skill_area = skill_area_box.crop_frame(self.frame)
        if not has_rectangles(skill_area):
            return -1

        count = 0
        y_start, y_end = 1958, 1970

        bars = [
            (1604, 1796),
            (1824, 2013),
            (2043, 2231)
        ]

        for x1, x2 in bars:
            if self.check_is_pure_color_in_4k(x1, y_start, x2, y_end, yellow_skill_color):
                count += 1
            else:
                break

        if count == 0:
            has_white_left = self.check_is_pure_color_in_4k(1604, y_start, 1614, y_end, white_skill_color,
                                                            threshold=0.1)
            if not has_white_left:
                count = -1
        return count

    def check_is_pure_color_in_4k(self, x1, y1, x2, y2, color_range=None, threshold=0.9):
        skill_area_box = self.box_of_screen_scaled(3840, 2160, x1, y1, x2, y2)
        bar = skill_area_box.crop_frame(self.frame)

        if bar.size == 0:
            return False

        height, width, _ = bar.shape
        consecutive_matches = 0

        for i in range(height):
            row_pixels = bar[i]
            unique_colors, counts = np.unique(row_pixels, axis=0, return_counts=True)
            most_frequent_index = np.argmax(counts)
            dominant_count = counts[most_frequent_index]
            dominant_color = unique_colors[most_frequent_index]

            is_valid_row = (dominant_count / width) >= threshold

            if is_valid_row and color_range:
                b, g, r = dominant_color
                if not (color_range['r'][0] <= r <= color_range['r'][1] and
                        color_range['g'][0] <= g <= color_range['g'][1] and
                        color_range['b'][0] <= b <= color_range['b'][1]):
                    is_valid_row = False

            if is_valid_row:
                consecutive_matches += 1
                if consecutive_matches >= 2:
                    return True
            else:
                consecutive_matches = 0

        return False
