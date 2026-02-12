import re

from qfluentwidgets import FluentIcon

from src.data.characters import all_list
from src.data.world_map import areas_list, outpost_dict, default_goods
from src.data.world_map_utils import get_area_by_outpost_name, get_goods_by_outpost_name
from src.tasks.BaseEfTask import BaseEfTask
from src.interaction.ScreenPosition import ScreenPosition as screen_position
import time
from enum import Enum


class LiaisonResult(Enum):
    SUCCESS = 1
    FAIL = 2
    FIND_CHAT_ICON = 3


class DailyTask(BaseEfTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "日常任务"
        self.description = "用户点击时调用run方法"
        self.icon = FluentIcon.SYNC
        self.default_config.update(
            {
                "送礼": True,
                "造装备": True,
                "日常奖励": True,
                "据点兑换": True,
            }
        )
        self.all_name_pattern = [re.compile(i) for i in all_list]
        # self.config_type["下拉菜单选项"] = {'type': "drop_down",
        #                               'options': ['第一', '第二', '第3']}

    # def run(self):
    #     self.collect_and_give_gifts()
    def run(self):
        self.log_info("开始执行日常任务...")

        tasks = [
            ("送礼", self.give_gift_to_liaison),
            ("造装备", self.make_weapon),
            ("日常奖励", self.claim_daily_rewards),
            ("据点兑换", self.exchange_outpost_goods)
        ]

        failed_tasks = []
        for key, func in tasks:
            # -------- 关键逻辑开始 --------
            if key != "ensure_main":
                # 统一转为列表
                keys = [key] if isinstance(key, str) else list(key)

                # or 规则：任一为 True 即执行
                if not any(self.config.get(k) for k in keys):
                    continue
            self.ensure_main()
            result = func()  # 不捕获异常，异常自然向上传递

            if result is False:
                self.log_info(f"任务 {key} 执行失败或未完成")
                failed_tasks.append(key)

        if failed_tasks:
            self.log_info(f"以下任务未完成或失败: {failed_tasks}", notify=True)
        else:
            self.log_info("日常完成!", notify=True)

    def to_model_area(self, area, model):
        self.send_key("y", after_sleep=2)
        if not self.wait_click_ocr(match="更换", box=screen_position.LEFT.value, time_out=2, after_sleep=2):
            return
        if not self.wait_click_ocr(match=re.compile(area),
                                   box=self.box_of_screen(648 / 1920, 196 / 1080, 648 / 1920 + 628 / 1920,
                                                          196 / 1080 + 192 / 1080),
                                   time_out=2, after_sleep=2):
            return
        if not self.wait_click_ocr(match="确认", box=screen_position.BOTTOM_RIGHT.value, time_out=2, after_sleep=2):
            return
        box = self.wait_ocr(match=re.compile(f"{model}"), box=screen_position.RIGHT.value, time_out=5)
        if box:
            self.click(box[0], move_back=True, after_sleep=0.5)
        else:
            self.log_error(f"未找到‘{model}’按钮，任务中止。")
            return

    def delivery_send_others(self):
        self.info_set('current_task', "delivery_send_others")
        for area in areas_list:
            for _ in range(3):
                self.to_model_area(area, "仓储节点")
                if not self.wait_click_ocr(match="本地仓储节点", box=screen_position.TOP_LEFT.value, time_out=5, after_sleep=2):
                    return

    def exchange_the_outpost_goods(self, outpost_name):
        self.wait_click_ocr(match=outpost_name, box=screen_position.TOP.value, time_out=5, after_sleep=2)
        not_enough = False
        can_exchange_goods = default_goods.get(get_area_by_outpost_name(outpost_name), [])
        max_attempts = 5
        attempt = 0
        skip_goods = []
        while attempt < max_attempts and not not_enough:
            attempt += 1
            self.wait_click_ocr(match="更换货品", after_sleep=2)
            goods = self.wait_ocr(match=[re.compile(i) for i in get_goods_by_outpost_name(outpost_name)], time_out=5)
            for good in goods:
                if good.name in skip_goods:
                    continue
                skip_goods.append(good.name)
                if not any(i in good.name for i in can_exchange_goods):
                    continue
                self.click(good, after_sleep=2)
                self.wait_click_ocr(match="确认", box=screen_position.BOTTOM_RIGHT.value, time_out=5, after_sleep=2)
                num_str = self.wait_ocr(match=re.compile(r"\d+"),
                                        box=self.box_of_screen(x=1224 / 1920, y=235 / 1080, width=327, height=121),
                                        time_out=5)

                try:
                    num = int(num_str[0].name)
                except (ValueError, TypeError, IndexError, AttributeError):
                    num = 0

                if num < 1000:
                    not_enough = True
                    break
                plus_button = self.find_one(feature_name="plus_button", box=screen_position.BOTTOM_RIGHT.value,
                                            threshold=0.8)
                if plus_button:
                    self.click(plus_button, down_time=12)
                    self.wait_click_ocr(match="交易", box=screen_position.BOTTOM_RIGHT.value, time_out=5, after_sleep=2)
                    self.wait_pop_up()
                    self.sleep(2)

    def test_ocr(self):
        self.ocr(match="1", log=True)

    def exchange_outpost_goods(self):
        self.info_set('current_task', "exchange_outpost_goods")
        for area in areas_list:
            self.to_model_area(area, "据点管理")
            for outpost_name in outpost_dict.get(area):
                self.exchange_the_outpost_goods(outpost_name)
            self.ensure_main()

    def make_weapon(self):
        self.info_set('current_task', "make_weapon")
        self.back()
        if not self.wait_click_ocr(match=re.compile("装备"), box=screen_position.RIGHT.value, time_out=5, after_sleep=2):
            self.log_info("未找到装备按钮")
            return False
        if not self.wait_click_ocr(match=re.compile("制作"), box=screen_position.BOTTOM_RIGHT.value, time_out=5, after_sleep=2):
            self.log_info("未找到制作按钮")
            return False
        self.wait_pop_up()
        return True

    def claim_daily_rewards(self):
        self.info_set('current_task', "claim_daily_rewards")
        self.sleep(2)
        self.send_key("f8", after_sleep=2)
        if not self.wait_click_ocr(match=re.compile("日常"), box=screen_position.TOP.value, time_out=5, after_sleep=2):
            self.log_info("未找到日常奖励按钮")
            return False
        while self.wait_click_ocr(match=re.compile("领取"), box=screen_position.RIGHT.value, time_out=5, after_sleep=2):
            pass
        if result := self.find_one(feature_name="claim_gift", box=screen_position.LEFT.value, threshold=0.8):
            self.click(result, after_sleep=2)
            self.wait_pop_up()
            return True
        return False

    def transfer_to_home_point(self):
        """
        通过地图界面传送到帝江号指定点
        """
        self.send_key("m")

        # 1. 确认是否打开地图并找到目标区域
        target_area = self.wait_ocr(match=re.compile("帝江号"), box=screen_position.TOP.value, time_out=5)
        if not target_area:
            return False

        self.click(target_area, after_sleep=2)

        # 2. 寻找传送点图标
        tp_icon = self.find_feature(
            feature_name="transfer_point", box=screen_position.LEFT.value, threshold=0.7
        )
        if not tp_icon:
            return False

        self.click(tp_icon)

        # 3. 等待传送按钮出现并点击
        transfer_btn = self.wait_ocr(
            match="传送", box=screen_position.BOTTOM_RIGHT.value, time_out=10, log=True
        )
        if not transfer_btn:
            return False

        self.click(transfer_btn,after_sleep=2)
        self.wait_ocr(match="舰桥", box=screen_position.LEFT.value, time_out=40, log=True)
        # 4. 最终状态验证（检查是否仍停留在地图界面/或根据业务逻辑验证）
        # 原逻辑最后有一个 wait_ocr("帝江号") 的判断，这里作为最终验证

    def go_main_hall(self) -> bool:
        for _ in range(12):
            self.move_keys("w", duration=1)
            if self.wait_ocr(match="中央环厅", box=screen_position.LEFT.value,log=True):
                return True
        return False

    def go_operator_liaison_station(self):
        self.send_key("m", after_sleep=2)
        result = self.find_one(
            feature_name="operator_liaison_station",
            box=self.box_of_screen(0, 0, 1, 1),
            threshold=0.7,
        )
        if result:
            self.click(result, after_sleep=2)
            if result:= self.wait_ocr(match=re.compile("追踪"), box=screen_position.BOTTOM_RIGHT.value, time_out=5):
                if "追踪" in result[0].name and "取" not in result[0].name and "消" not in result[0].name:
                    self.click(result, after_sleep=2)
                self.send_key("m", after_sleep=2)
                self.align_ocr_or_find_target_to_center(
                    ocr_match_or_feature_name="operator_liaison_station_out_map",
                    only_x=True,
                    threshold=0.7,
                    ocr=False,
                )
                start_time = time.time()
                short_distance_flag = False
                fail_count = 0
                while not self.wait_ocr(
                        match=re.compile("联络"), box=screen_position.BOTTOM_RIGHT.value, time_out=1
                ):
                    chat_box = self.wait_ocr(match=self.all_name_pattern, box=screen_position.BOTTOM_RIGHT.value, time_out=2)
                    if chat_box:
                        self.send_key_down("alt")
                        self.sleep(0.5)
                        self.click_box(chat_box)
                        self.send_key_up("alt")
                        return LiaisonResult.FIND_CHAT_ICON
                    # 每几步重新align一次（只有导航存在时）
                    if not short_distance_flag:
                        nav = self.find_feature(
                            "operator_liaison_station_out_map",
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
                            self.align_ocr_or_find_target_to_center(
                                ocr_match_or_feature_name="operator_liaison_station_out_map",
                                only_x=True,
                                threshold=0.7,
                                ocr=False,
                            )
                            self.move_keys("w", duration=1)
                        else:
                            fail_count += 1
                            if fail_count >= 3:
                                self.log_info(
                                    "长时间未找到导航，可能已接近目标点，切换短距离移动"
                                )
                                short_distance_flag = True
                            self.move_keys("w", duration=0.5)
                    else:
                        self.move_keys("w", duration=0.5)
                    self.sleep(0.5)
                    if time.time() - start_time > 60:
                        self.log_info("长时间未找到联络台")
                        raise Exception("长时间未找到联络台")
                return LiaisonResult.SUCCESS
        return LiaisonResult.FAIL

    def operator_liaison_task(self):
        find_flag = False
        for _ in range(10):
            self.send_key("f", after_sleep=2)
            if not self.wait_click_ocr(
                    match=[re.compile(i) for i in ["会客", "培养", "制造"]],
                    time_out=5,
                    after_sleep=2,
            ):
                self.log_info("未找到信任度界面")
                return False
            if not self.wait_click_ocr(
                    match="确认联络",
                    box=screen_position.BOTTOM_RIGHT.value,
                    time_out=5,
                    after_sleep=2,
                    log=True,
            ):
                self.log_info("未找到确认联络按钮")
                return False
            find_flag = self.align_ocr_or_find_target_to_center(
                ocr_match_or_feature_name=[re.compile("工作"), re.compile("休息")],
                raise_if_fail=False,
                only_x=True,
                max_time=7,
            )
            if find_flag:
                break
        start_time = time.time()
        chat_box = None

        while chat_box is None:

            chat_box = self.wait_ocr(match=self.all_name_pattern, box=screen_position.BOTTOM_RIGHT.value, time_out=2)

            if chat_box:
                self.send_key_down("alt")
                self.sleep(0.5)
                self.click_box(chat_box)
                self.send_key_up("alt")
                return True

            self.move_keys("w", duration=0.5)
            self.sleep(0.5)

            if time.time() - start_time > 30:
                self.log_info("长时间未找到干员")
                raise Exception("长时间未找到干员")

    def collect_and_give_gifts(self):
        start_time = time.time()
        result = None
        while True:
            if time.time() - start_time > 30:
                self.log_info("等待 收下/赠送 超时")
                return False
            self.click(0.5, 0.5, after_sleep=0.5)
            result = self.wait_click_ocr(
                match=[re.compile("收下"), re.compile("赠送")],
                box=screen_position.BOTTOM_RIGHT.value,
                time_out=2,
                after_sleep=2,
            )
            if result:
                break

        if result and len(result) > 0 and "收下" in result[0].name:
            self.skip_dialog(end_list=[re.compile("ms")], end_box=screen_position.BOTTOM_LEFT.value)
            self.sleep(1)
            self.wait_click_ocr(match="确认", box=screen_position.BOTTOM_RIGHT.value, time_out=5, after_sleep=2)
            self.send_key("f", after_sleep=2)
            start_time = time.time()
            while True:
                if time.time() - start_time > 30:
                    self.log_info("等待 收下/赠送 超时")
                    return False
                self.click(0.5, 0.5, after_sleep=0.5)
                result = self.wait_ocr(
                    match=[re.compile("赠送")],
                    box=screen_position.BOTTOM_RIGHT.value,
                    time_out=2,
                )
                if result:
                    break
        self.wait_click_ocr(
            match=re.compile("赠送"), box=screen_position.BOTTOM_RIGHT.value, time_out=5, after_sleep=2
        )
        self.click(144 / 1920, 855 / 1080, after_sleep=2)
        if self.wait_click_ocr(
                match=re.compile("确认赠送"), box=screen_position.BOTTOM_RIGHT.value, time_out=5, after_sleep=2
        ):
            start_time = time.time()
            while True:
                if time.time() - start_time > 30:
                    self.log_info("等待 收下/赠送 超时")
                    return False
                self.click(0.5, 0.5, after_sleep=0.5)
                result = self.wait_click_ocr(
                    match=[re.compile("离开")],
                    box=screen_position.BOTTOM_RIGHT.value,
                    time_out=2,
                    after_sleep=2,
                )
                if result:
                    break
            self.log_info("成功赠送礼物")
            return True
        self.log_info("赠送礼物失败")
        return False

    def give_gift_to_liaison(self):
        self.log_info("开始送礼任务")
        self.transfer_to_home_point()
        if self.go_main_hall():
            result = self.go_operator_liaison_station()

            if result == LiaisonResult.FIND_CHAT_ICON:
                return self.collect_and_give_gifts()

            elif result == LiaisonResult.SUCCESS:
                if self.operator_liaison_task():
                    return self.collect_and_give_gifts()
            else:
                raise Exception("前往联络站失败")


