import re
import time

from src.tasks.BaseEfTask import BaseEfTask


class NavigationMixin(BaseEfTask):
    def start_tracking_and_align_target(self, target_feature_in_map, target_feature_out_map):
        """在地图中开启追踪并在地图外完成朝向对齐。"""
        result = self.find_one(
            feature_name=target_feature_in_map,
            box=self.box_of_screen(0, 0, 1, 1),
            threshold=0.7,
        )
        if not result:
            self.log_info(f"未找到{target_feature_in_map}图标")
            return False
        self.log_info(f"找到{target_feature_in_map}图标，点击进入")
        self.click(result, after_sleep=2)

        if result := self.wait_ocr(
                match=re.compile("追踪"), box=self.box.bottom_right, time_out=5
        ):
            if (
                    "追踪" in result[0].name
                    and "取" not in result[0].name
                    and "消" not in result[0].name
            ):
                self.log_info("点击追踪按钮")
                self.click(result, after_sleep=2)

        self.press_key("m", after_sleep=2)
        self.log_info("关闭地图界面 (按下 M)")

        self.align_ocr_or_find_target_to_center(
            ocr_match_or_feature_name_list=target_feature_out_map,
            only_x=True,
            threshold=0.7,
            ocr=False,
        )
        self.log_info("已对齐地图目标")
        return True

    def navigate_until_target(
            self,
            target_ocr_pattern,
            nav_feature_name,
            timeout: int = 60,
            pre_loop_callback=None,
            found_special_callback=None,
    ):
        """通用导航循环：识别目标前持续前进并动态对齐。"""
        start_time = time.time()
        short_distance_flag = False
        fail_count = 0

        while not self.wait_ocr(
                match=target_ocr_pattern,
                box=self.box.bottom_right,
                time_out=1,
        ):
            if time.time() - start_time > timeout:
                self.log_info("导航超时")
                return False

            if found_special_callback:
                special_result = found_special_callback()
                if special_result is not None:
                    return special_result

            if pre_loop_callback:
                pre_loop_callback()

            if not short_distance_flag:
                nav = self.find_feature(
                    nav_feature_name,
                    box=self.box_of_screen(
                        (1920 - 1550) / 1920,
                        150 / 1080,
                        1550 / 1920,
                        (1080 - 150) / 1080,
                    ),
                    threshold=0.7,
                )

                if nav:
                    fail_count = 0
                    self.log_info("找到导航路径，继续对齐并前进")

                    self.align_ocr_or_find_target_to_center(
                        ocr_match_or_feature_name_list=nav_feature_name,
                        only_x=True,
                        threshold=0.7,
                        ocr=False,
                    )

                    self.move_keys("w", duration=1)
                else:
                    fail_count += 1
                    self.log_info(f"未找到导航路径，连续失败次数: {fail_count}")

                    if fail_count >= 3:
                        self.log_info("切换短距离移动")
                        short_distance_flag = True

                    self.move_keys("w", duration=0.5)
            else:
                self.move_keys("w", duration=0.5)

            self.sleep(0.5)

        return True
