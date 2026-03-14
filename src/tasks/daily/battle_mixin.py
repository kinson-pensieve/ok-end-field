import re
import time

from src.data.world_map import stages_cost, higher_order_feature_dict
from src.data.world_map_utils import get_stage_category
from src.tasks.mixin.battle_mixin import BattleMixin
from src.tasks.mixin.common import Common


class DailyBattleMixin(BattleMixin,Common):
    def __init__(self, *args,**kwargs):
        super().__init__(*args,**kwargs)
        self.max_half_time = 0

    def battle(self):
        stage_name = self.config.get("体力本")
        category_name = get_stage_category(stage_name)
        self.ensure_main()
        self.press_key('f8', after_sleep=2)
        self.wait_click_ocr(match=re.compile("索引"), time_out=5, after_sleep=2, box=self.box.top, log=True)
        left_ticket = self.detect_ticket_number()
        self.log_info(f"当前体力: {left_ticket}")
        if self.max_half_time > 0:
            if left_ticket < stages_cost[category_name] - 40:
                self.log_info("体力不足")
                return True
        else:
            if left_ticket < stages_cost[category_name]:
                self.log_info("体力不足")
                return True
        self.to_stage(stage_name, category_name)
        if category_name != "能量淤积点":
            return self.battle_space(left_ticket, category_name)
        else:
            self.log_info("尚未实现能量淤积点功能", notify=True)
            return True

    def battle_space(self, left_ticket, category_name):
        self.wait_click_ocr(match=re.compile("进入"), time_out=5, after_sleep=2, box=self.box.bottom_right, log=True)
        if self.wait_click_ocr(match=re.compile("取消"), time_out=5, box=self.box.bottom_left, log=True):
            self.log_info("没有进入战斗，可能是因为已经没理智了")
            return True
        enter_bool = False
        battle_bool = False
        while left_ticket > 0:
            if enter_bool:
                self.wait_click_ocr(match=re.compile("重新挑战"), box=self.box.bottom_left, log=True, time_out=5,
                                    after_sleep=2)
            else:
                self.wait_click_ocr(match=re.compile("进入"), time_out=5, after_sleep=2, box=self.box.bottom_right,
                                    log=True)
                enter_bool = True
            if battle_bool:
                if not self.to_battle(0.1):
                    return False
            else:
                if not self.to_battle():
                    return False
                else:
                    battle_bool = True
            if not self.to_end():
                return False
            left_ticket = self.get_claim(stages_cost[category_name], left_ticket)
            if left_ticket <= 0:
                self.wait_click_ocr(match=re.compile("离开"), box=self.box.bottom_right, log=True, after_sleep=2)
                break
        return True

    def to_stage(self, stage_name, category_name):
        """
        通用关卡进入方法：
        1. 点击左侧类别。
        2. 定位关卡位置。
        3. 点击对应按钮（“前往”或“查看”）。
        4. 自动支持普通关卡和高阶关卡（危境预演）。
        """
        # 点击左侧关卡类别
        self.wait_click_ocr(
            match=re.compile(category_name),
            box=self.box.left,
            log=True,
            after_sleep=2,
            time_out=6
        )

        # 默认按钮文本
        to_text = "前往"
        if category_name == "能量淤积点":
            to_text = "查看"
        # 判断是否是高阶关卡
        is_higher_order = category_name == "危境预演"
        for _ in range(5):
            if is_higher_order:
                # 高阶关卡，使用 feature_dict 查找位置
                location = self.find_feature(feature_name=higher_order_feature_dict[stage_name])
            else:
                # 普通关卡
                location = self.wait_ocr(match=re.compile(stage_name), box=self.box.left, log=True, time_out=5)

            if location:
                enter_bool = self.wait_click_ocr(
                    match=re.compile(to_text),
                    box=self.box_of_screen(location[0].x / self.width, location[0].y / self.height, 1, 1),
                    after_sleep=2,
                    time_out=6,
                )
                if enter_bool:
                    return True
            self.scroll_relative(0.5, 0.5, count=-2)
            self.wait_ui_stable(refresh_interval=0.5)
        return False
        # 如果找到位置，则点击按钮

    def to_battle(self, start_sleep: float = None):
        end_time = time.time()
        while not self.wait_ocr(match=re.compile("撤离"), time_out=1, box=self.box.top_left, log=True):
            if time.time() - end_time > 30:
                self.log_info("等待超时，进入协议空间超时")
                return False
        while not self.wait_ocr(match=re.compile("触碰"), time_out=1, box=self.box.bottom_right, log=True):
            self.move_keys('w', duration=0.25)
        self.press_key("f")
        return self.auto_battle(start_sleep=start_sleep)

    def to_end(self):
        search_box = self.box_of_screen((1920 - 1550) / 1920, 0, 1550 / 1920, (1080 - 150) / 1080)
        for _ in range(9):
            if self.yolo_detect("battle_end", box=search_box):
                break
            self.click(key="middle", after_sleep=2)
            self.move_keys("aw", duration=0.1)
            self.sleep(1)

        self.align_ocr_or_find_target_to_center(
            "battle_end",
            ocr=False,
            use_yolo=True,
            box=search_box,
            max_time=5,
            only_x=True,
            raise_if_fail=False,
            threshold=0.5,
        )
        start_time = time.time()
        while self.align_ocr_or_find_target_to_center("battle_end", ocr=False, use_yolo=True, box=search_box,
                                                      only_x=True, threshold=0.5, tolerance=100):
            if time.time() - start_time > 60:
                return False
            if self.wait_ocr(match=re.compile("领取"), time_out=1, box=self.box.bottom_right):
                self.sleep(0.5)
                self.press_key("f", down_time=0.2)
                break
            else:
                self.move_keys('w', duration=0.25)
        return True

    def get_claim(self, ticket_number, sum_ticket_number):
        """
        执行一次领奖操作，并返回剩余理智。

        逻辑：
        1. 等待界面稳定，并找到“可领取”提示。
        2. 尝试点击“获得奖励”，如果失败则本轮减少消耗理智。
        3. 扣除本轮理智，判断剩余理智是否足够。
        4. 点击“领取”，记录领取状态。
        5. 根据剩余理智和 max_half_time 判断下一轮是否可继续。

        返回：
            int: 扣掉本轮消耗理智后的剩余理智，如果理智不足则返回 0。
        """
        self.log_info("领取奖励,当前理智: {}, 本轮消耗理智: {}".format(sum_ticket_number, ticket_number))
        self.wait_ui_stable(refresh_interval=1)
        start_time = time.time()

        # 等待界面出现“可领取”
        while not self.wait_ocr(match=re.compile("可领取"), box=self.box.top, time_out=1):
            if time.time() - start_time > 60:
                return 0
            self.press_key("f", down_time=0.2)
            self.wait_ui_stable(refresh_interval=1)

        # 本轮默认消耗理智
        need_ticket_number = ticket_number

        # 尝试点击“获得奖励”，失败则本轮减少消耗理智
        if self.max_half_time > 0:
            if not self.wait_click_ocr(
                    match=re.compile("获得奖励"),
                    box=self.box_of_screen(530 / 1920, 330 / 1080, 1400 / 1920, 570 / 1080),
                    time_out=2,
                    log=True
            ):
                need_ticket_number = ticket_number - 40  # 减耗票逻辑
                self.max_half_time -= 1  # 减耗次数减少
                self.log_info("未找到 '获得奖励' 按钮，本轮应减少消耗理智，新的本轮消耗理智: {}, 剩余减耗次数: {}".format(
                    need_ticket_number, self.max_half_time))

        # 扣除本轮消耗理智
        sum_ticket_number -= need_ticket_number
        self.log_info("扣除本轮消耗理智: {}, 剩余理智: {}".format(need_ticket_number, sum_ticket_number))
        if sum_ticket_number < 0:
            return 0  # 理智不足，不能继续

        # 点击“领取”，失败则返回0
        if not self.wait_click_ocr(match=re.compile("领取"), box=self.box.bottom_right, time_out=2, log=True):
            self.log_info("领取失败")
            return 0

        # 如果减耗次数用完，下一轮恢复全额消耗
        if self.max_half_time <= 0:
            need_ticket_number = ticket_number
            self.log_info("减耗次数已用完，下一轮恢复全额消耗理智: {}".format(need_ticket_number))

        # 预测下一轮是否还能继续
        next_sum = sum_ticket_number - need_ticket_number
        self.log_info("预测下一轮消耗理智: {}, 预测下一轮剩余理智: {}".format(need_ticket_number, next_sum))

        if next_sum < 0:
            self.log_info("下一轮理智不足，无法继续")
            return 0
        else:
            # 返回本轮剩余理智，不返回next_sum，因为减耗只用于判断下一轮可否继续
            return sum_ticket_number
