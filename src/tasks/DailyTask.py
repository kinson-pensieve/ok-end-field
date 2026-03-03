import re
import time
from enum import Enum
from dataclasses import dataclass
from typing import List, Optional
from qfluentwidgets import FluentIcon
from ok import Box
from src.tasks.BaseEfTask import BaseEfTask
from src.interaction.ScreenPosition import ScreenPosition
from src.data.characters import all_list
from src.data.world_map import (
    areas_list,
    outpost_dict,
    default_goods,
    exchange_goods_dict,
)
from src.data.world_map_utils import (
    get_area_by_outpost_name,
    get_goods_by_outpost_name,
)
from src.data.FeatureList import FeatureList as fL
from src.image.hsv_config import HSVRange as hR

class LiaisonResult(int, Enum):
    SUCCESS = 1
    FAIL = 2
    FIND_CHAT_ICON = 3


@dataclass
class GoodsInfo:
    good_name: str
    good_price: int
    friend_price: Optional[int]
    name_box: "Box"  # 只保留这一个 Box
    friend_name_box: Optional["Box"]  # 可选，只有当 friend_price 存在且可点击时才有值


class DailyTask(BaseEfTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "日常任务"
        self.description = "一键收菜"
        self.icon = FluentIcon.SYNC
        buy_sell = dict()
        for area in areas_list:
            buy_sell[f"{area}买入价"] = 900
            buy_sell[f"{area}卖出价"] = 4500
            buy_sell[area] = True
        self.default_config.update(buy_sell)
        self.default_config.update(
            {
                "送礼任务最多尝试次数": 2,
                "送礼": True,
                "据点兑换": True,
                "转交运送委托": True,
                "转交委托奖励领取": True,
                "造装备": True,
                "收信用": True,
                "尝试仅收培育室": False,
                "买卖货": True,
                "日常奖励": True,
            }
        )
        self.config_description.update(
            {
                "尝试仅收培育室":'前置是启用收信用'
            }
        )
        self.add_exit_after_config()
        self.config_description.update(
            {
                "尝试仅收培育室": "在好友交流助力时，优先尝试仅收取培育室的助力,但每次至少助力一次舱室",
            }
        )
        self.all_name_pattern = [re.compile(i) for i in all_list]
        if self.debug:
            self.default_config.update(
                {
                    "重复测试的次数": 1,
                }
            )
        # self.config_type["下拉菜单选项"] = {'type': "drop_down",
        #                               'options': ['第一', '第二', '第3']}

    # def run(self):
    #     self.collect_and_give_gifts()
    def run(self):
        self.log_info("开始执行日常任务...", notify=True)
        repeat_times = 1
        if self.debug:
            repeat_times = self.config.get("重复测试的次数", 1)
            self.log_info(f"当前为调试模式，重复执行 {repeat_times} 次")
        if not self._logged_in:
            self.ensure_main(time_out=240)
        else:
            self.ensure_main()
        tasks = [  # 确保在主界面
            ("送礼", self.give_gift_main),
            ("据点兑换", self.exchange_outpost_goods),
            ("转交运送委托", self.delivery_send_others),
            ("转交委托奖励领取", self.claim_delivery_rewards),
            ("造装备", self.make_weapon),
            ("收信用", self.collect_credit),
            ("买卖货", self.buy_sell),
            ("日常奖励", self.claim_daily_rewards),
        ]
        all_fail_tasks = []
        if self.debug:
            tasks = tasks * repeat_times
        failed_tasks = []
        for key, func in tasks:
            if key != "ensure_main":
                keys = [key] if isinstance(key, str) else list(key)
                if not any(self.config.get(k) for k in keys):
                    continue
            result = func()
            self.ensure_main()
            if result is False:
                self.log_info(f"任务 {key} 执行失败或未完成", notify=True)
                failed_tasks.append(key)
        if failed_tasks:
            if self.debug:
                all_fail_tasks.append(failed_tasks)
            self.log_info(f"以下任务未完成或失败: {failed_tasks}", notify=True)
        else:
            self.log_info("日常完成!", notify=True)
        if self.debug and all_fail_tasks:
            self.log_info(f"所有重复测试的失败任务: {all_fail_tasks}", notify=True)

    def wait_friend_list(self, end_icon_name="friend_chat_icon"):
        start_time = time.time()
        while True:
            if time.time() - start_time > 20:
                self.log_info("加载好友列表超时")
                return False
            if self.find_feature(feature_name=end_icon_name):
                return True
    def collect_credit(self):
        self.info_set("current_task", "collect_credit")
        self.send_key("f5", after_sleep=2)
        self.wait_click_ocr(match=re.compile("信用交易所"), box=self.box.top, time_out=5, after_sleep=2)
        result = self.wait_click_ocr(match=[re.compile("收取信用"), re.compile("无待领取信用")], box=self.box.bottom_left,
                                     time_out=5, after_sleep=2)
        if not result:
            self.log_info("未找到可收取信用或无待领取信用的选项")
            return False
        if "收取信用" in result[0].name:
            self.wait_pop_up(after_sleep=2)
        self.ensure_main()
        self.back(after_sleep=2)
        left_exchange_time = 5
        left_help_time = 5
        exchange_time = 0
        help_time = 0
        is_first_time = True
        exchange_help_box = self.box_of_screen(0.1, 561 / 861, 0.9, 0.9)
        exchange_not_found = False
        while True:
            if is_first_time:
                self.wait_click_ocr(match=re.compile("好友"), box=self.box.right, time_out=5, after_sleep=2)
            else:
                self.send_key("f", after_sleep=2)
                if left_exchange_time <= 0 and left_help_time <= 0:
                    self.wait_click_ocr(match=re.compile("结束拜访"), box=self.box.bottom_right, time_out=5, after_sleep=2)
                    self.log_info("交流和助力次数已完成，结束拜访")
                    self.wait_click_ocr(match=re.compile("确认"), box=self.box.bottom_right, time_out=5, after_sleep=2)
                    if exchange_not_found:
                        self.log_info("未完全找满交流对象，可能存在部分交流次数未完成")
                    self.info_set("exchange_time", exchange_time)
                    self.info_set("help_time", help_time)
                    return True

            result = None
            self.wait_ui_stable(refresh_interval=0.5)
            start_time = time.time()
            scroll_count = 0
            while not result:
                if is_first_time or scroll_count > 0:
                    self.span_box = self.box_of_screen(3400 / 3840, 301 / 2160, 3692 / 3840, 1883 / 2160)
                else:
                    self.span_box = self.box_of_screen(3400 / 3840, 615 / 2160, 3692 / 3840, 1883 / 2160)
                if time.time() - start_time > 40:
                    self.log_info("找不到可交流或助力的玩家")
                    return False
                if left_exchange_time > 0:
                    result = self.find_feature(
                        feature_name="can_exchange_info_icon", box=self.span_box
                    )
                    if scroll_count >= 7:  # 交流只有循环 >=7 次才允许找 help
                        self.back(after_sleep=2)
                        self.ensure_in_friend_boat()
                        self.send_key("f", after_sleep=2)
                        self.wait_ui_stable(refresh_interval=0.5)
                        left_exchange_time = 0
                        exchange_not_found = True
                        continue

                # 如果 exchange 已经没次数，正常找 help
                elif left_help_time > 0:
                    result = self.find_feature(
                        feature_name="can_help_icon", box=self.span_box
                    )
                if not result:
                    scroll_count += 1
                    self.scroll_relative(0.5, 0.5, -4)
                    self.wait_ui_stable(refresh_interval=0.5)

            self.click(result, after_sleep=2)
            self.wait_click_ocr(match=re.compile("确定"), box=self.box.bottom_right, time_out=5, after_sleep=2)
            if not self.ensure_in_friend_boat():
                self.log_info("未能进入好友帝江号")
                return False
            self.sleep(2)
            actions = []
            if left_exchange_time > 0:
                actions.append("交流")
            if left_help_time > 0:
                actions.append("助力")
            self.log_info(f"已进入好友帝江号，准备进行{''.join(actions)}操作")
            self.send_key("y", after_sleep=2)
            if left_exchange_time > 0:
                self.wait_click_ocr(match=re.compile("情报交流"), box=exchange_help_box, time_out=5, after_sleep=2)
                left_exchange_time -= 1
                exchange_time += 1
            if left_help_time > 0:
                result = self.wait_ocr(match=re.compile("生产助力"), box=exchange_help_box, time_out=5)
                if result:
                    for res in result:
                        if not self.config.get("尝试仅收培育室"):
                            self.click(res, after_sleep=2)
                            left_help_time -= 1
                            help_time += 1
                            if left_help_time <= 0:
                                break
                        if res == result[-1]:
                            self.scroll_relative(res.x / self.width, res.y / self.height, count=-8)
                            self.wait_ui_stable(refresh_interval=0.5)
                            if result := self.wait_ocr(match=re.compile("生产助力"), box=exchange_help_box, time_out=5):
                                self.log_info("继续进行助力操作")
                                self.click(result[-1], after_sleep=2)
                                if self.find_feature(feature_name="reward_ok"):
                                    self.wait_pop_up(after_sleep=2)
                                left_help_time -= 1
                                help_time += 1
            self.back(after_sleep=2)
            is_first_time = False

    def claim_delivery_rewards(self):
        self.info_set("current_task", "claim_delivery_rewards")
        self.log_info("开始领取转交委托奖励")

        area = areas_list[0]
        self.to_model_area(area, "仓储节点")

        if not self.wait_click_ocr(
                match=re.compile("我转交的委托"),
                box=self.box.top_left,
                time_out=5,
                after_sleep=2,
        ):
            self.log_info(f"'未找到我转交的委托'节点，返回主界面")
            self.ensure_main()

        results = self.wait_ocr(
            match=re.compile("一键领取"),
            box=self.box.bottom_right,
            time_out=5,
        )

        if not results:
            self.log_info(f"当前没有可领取的转交委托奖励，返回主界面")
            self.ensure_main()

        if results:
            self.click(results, after_sleep=2)
            if not self.wait_pop_up():
                self.log_info("未找到 '确认' 按钮，可能未成功领取奖励")
                self.ensure_main()
            self.sleep(2)

        self.log_info(f"转交委托奖励领取完成，返回主界面")
        self.ensure_main()

        self.log_info("转交委托奖励领取任务完成")

    def delivery_send_others(self):
        self.info_set("current_task", "delivery_send_others")

        for area in areas_list:
            activity_num = 0
            count = 0
            self.log_info(f"开始处理区域: {area}")

            while True:
                # 守卫式 1: 已完成预定次数
                if 0 < activity_num <= count:
                    self.log_info(
                        f"{area}仓储节点已完成{activity_num}次，停止继续"
                    )
                    break

                self.to_model_area(area, "仓储节点")

                # 守卫式 2: 找不到仓储入口直接退出
                if not self.wait_click_ocr(
                        match=re.compile("本地仓储节点"),
                        box=self.box.top_left,
                        time_out=5,
                        after_sleep=2,
                ):
                    self.log_info(f"{area}未找到本地仓储节点，返回主界面")
                    self.ensure_main()
                    break

                # 检查可操作货物
                results = self.wait_ocr(
                    match=re.compile("货物装箱"),
                    box=self.box.bottom,
                    time_out=5,
                )

                # 守卫式 3: 没有货物可操作则退出
                if not results:
                    self.log_info(
                        f"{area} 当前没有货物装箱可操作，返回主界面"
                    )
                    self.ensure_main()
                    break

                # 第一次确定活动数量
                if activity_num == 0:
                    activity_num = len(results)
                    self.log_info(
                        f"{area}共有{activity_num}次可进行转交运送委托的活动",
                        notify=True,
                    )

                # 执行一次转交操作
                self.click(results[0], after_sleep=2)

                steps = [
                    ("下一步", self.box.bottom_right),
                    ("填充至满", self.box.top_right),
                    ("下一步", self.box.bottom_right),
                    ("开始运送", self.box.bottom_right),
                    ("获得调度券", self.box.bottom_right)
                ]

                for i in range(len(steps)):
                    step = steps[i]
                    match = step[0]
                    box = step[1]
                    timeout = 12 if i > 2 else 5
                    res = None
                    for i in range(2):
                        self.next_frame()
                        if i==0:
                            res = self.wait_ocr(match=re.compile(match), box=box, time_out=timeout,log=True)
                        else:
                            res =self.ocr(match=re.compile(match), box=box,frame_processor=self.make_hsv_isolator(hR.DARK_GRAY_TEXT), log=True)
                            if not res:
                                res = self.ocr(match=re.compile(match), box=box, frame_processor=self.make_hsv_isolator(hR.WHITE), log=True)
                        if res:
                            self.log_info(f"找到步骤 {match}，继续下一步")
                            self.sleep(1)
                            self.click(res[0], after_sleep=2)
                            break

                    if not res:
                        self.log_info(f"步骤 {match} 未找到，跳过本次活动")

                        break
                self.ensure_main()
                # 操作后快捷键
                self.send_key("v", after_sleep=1)
                self.send_key("j", after_sleep=1)

                # 最终确认
                if not self.wait_click_ocr(
                        match=re.compile("转交运送委托"),
                        box=self.box.bottom_left,
                        time_out=5,
                        after_sleep=2,
                ):
                    self.log_info(
                        "未找到 '转交运送委托' 按钮，跳过本次活动"
                    )
                    self.ensure_main()
                    break
                if not self.wait_click_ocr(
                        match=re.compile("确认"),
                        box=self.box.bottom_right,
                        time_out=5,
                        after_sleep=2,
                ):
                    self.log_info("未找到 '确认' 按钮，跳过本次活动")
                    self.ensure_main()
                    break

                self.sleep(2)
                count += 1
                self.log_info(f"{area} 已完成 {count}/{activity_num} 次转交")

    def get_outpost_ticket_num(self, outpost_name):
        num_str = self.wait_ocr(
            match=re.compile(r"\d+"),
            box=self.box_of_screen(
                1224 / 1920,
                235 / 1080,
                1551 / 1920,
                356 / 1080,
            ),
            time_out=5,
        )

        num = 0
        if num_str and hasattr(num_str[0], "name"):
            try:
                num = int(num_str[0].name)
            except ValueError:
                num = 0

        self.log_info(f"{outpost_name} 据点当前券数量: {num}")
        return num

    def exchange_the_outpost_goods(self, outpost_name):
        self.log_info(f"开始处理据点: {outpost_name}")
        self.wait_click_ocr(
            match=outpost_name, box=self.box.top, time_out=5, after_sleep=2
        )

        can_exchange_goods = default_goods.get(
            get_area_by_outpost_name(outpost_name), []
        )
        max_attempts = 5
        attempt = 0
        skip_goods = set()

        while attempt < max_attempts:
            num = self.get_outpost_ticket_num(outpost_name)
            if num < 1000:
                self.log_info(f"{outpost_name} 据点当前券数量不足 (<1000)，停止兑换")
                break
            attempt += 1
            self.log_info(f"尝试第 {attempt}/{max_attempts} 次更换货品")
            self.wait_click_ocr(match="更换货品", after_sleep=2)

            goods = self.wait_ocr(
                match=[re.compile(i) for i in get_goods_by_outpost_name(outpost_name)],
                time_out=5,
            )
            if not goods:
                self.log_info(f"{outpost_name} 没有可兑换的货物，结束本次尝试")
                break
            exchange_good = None
            for good in goods:
                # 1. 使用集合进行瞬时排除
                if good.name in skip_goods:
                    self.log_info(f"跳过已处理货物: {good.name}")
                    continue

                # 2. 检查名称关键词匹配
                is_valid = any(keyword in good.name for keyword in can_exchange_goods)

                if not is_valid:
                    self.log_info(f"{good.name} 不在可兑换列表中，跳过")
                    continue

                # 3. 命中目标
                skip_goods.add(good.name)  # set 使用 add
                exchange_good = good
                self.log_info(f"成功锁定兑换目标: {good.name}")
                break

            if not exchange_good:
                self.log_info(f"{outpost_name} 没有可兑换的货物，结束本次尝试")
                break

            self.log_info(f"选择货物进行兑换: {exchange_good.name}")
            self.click(exchange_good, after_sleep=2)
            self.wait_click_ocr(
                match=re.compile("确认"),
                box=self.box.bottom_right,
                time_out=5,
                after_sleep=2,
            )

            num = self.get_outpost_ticket_num(outpost_name)
            if num < 1000:
                self.log_info(f"{outpost_name} 据点当前券数量不足 (<1000)，停止兑换")
                break

            plus_button = self.find_one(
                feature_name="plus_button",
                box=self.box.bottom_right,
                threshold=0.8,
            )
            if plus_button:
                self.log_info(f"找到加号按钮，执行点击")
                self.click(plus_button, down_time=12)
                self.wait_click_ocr(
                    match="交易",
                    box=self.box.bottom_right,
                    time_out=5,
                    after_sleep=2,
                )
                self.wait_pop_up(after_sleep=2)

        self.log_info(f"{outpost_name} 兑换操作完成")

    def test_ocr(self):
        box1 = self.box_of_screen(1749 / 1920, 107 / 1080, 1789 / 1920, 134 / 1080)
        box2 = self.box_of_screen(
            (1749 + (1832 - 1750)) / 1920, 107 / 1080, (1789 + (1832 - 1750)) / 1920, 134 / 1080
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

    def exchange_outpost_goods(self):
        self.info_set("current_task", "exchange_outpost_goods")
        self.log_info("开始据点兑换任务")

        for area in areas_list:
            self.log_info(f"进入区域: {area}")
            self.to_model_area(area, "据点管理")

            outposts = outpost_dict.get(area, [])
            if not outposts:
                self.log_info(f"{area} 没有据点可兑换")
                continue

            for outpost_name in outposts:
                self.log_info(f"开始兑换据点: {outpost_name}")
                self.exchange_the_outpost_goods(outpost_name)
                self.log_info(f"完成兑换据点: {outpost_name}")

            self.log_info(f"{area} 区域据点兑换完成，返回主界面")
            self.ensure_main()

        self.log_info("据点兑换任务完成")

    def make_weapon(self):
        self.info_set("current_task", "make_weapon")
        self.log_info("开始造装备任务")

        self.back()
        self.log_info("打开终端界面")

        if not self.wait_click_ocr(
                match=re.compile("装备"),
                box=self.box.right,
                time_out=5,
                after_sleep=2,
        ):
            self.log_info("未找到装备按钮，任务失败")
            return False
        self.log_info("找到装备按钮并点击")

        if not self.wait_click_ocr(
                match=re.compile("制作"),
                box=self.box.bottom_right,
                time_out=5,
                after_sleep=2,
        ):
            self.log_info("未找到制作按钮，任务失败")
            return False
        self.log_info("找到制作按钮并点击")
        self.log_info("等待弹窗完成，造装备任务准备完成")
        self.wait_pop_up()

        return True

    def claim_daily_rewards(self):
        self.info_set("current_task", "claim_daily_rewards")
        self.log_info("开始领取日常奖励任务")

        self.sleep(2)
        self.send_key("f8", after_sleep=2)
        self.log_info("按下 F8 打开日常奖励界面")

        if not self.wait_click_ocr(
                match=re.compile("日常"),
                box=self.box.top,
                time_out=5,
                after_sleep=2,
        ):
            self.log_info("未找到日常奖励按钮，任务失败")
            return False
        self.log_info("找到日常奖励按钮并点击")

        # 循环领取所有可领取奖励
        self.wait_click_ocr(
            match=re.compile("领取"),
            box=self.box.right,
            time_out=5,
            after_sleep=2,
        )

        # 检查是否有额外奖励可领取
        if result := self.find_one(
                feature_name="claim_gift", box=self.box.left, threshold=0.8
        ):
            self.log_info("发现可领取的额外奖励，点击领取")
            self.click(result, after_sleep=2)
            self.wait_pop_up()
            self.log_info("额外奖励领取完成")
            return True

        self.log_info("日常奖励领取完成")
        return True

    def transfer_to_home_point(self):
        """通过地图界面传送到帝江号指定点"""
        self.ensure_main()
        self.log_info("开始传送到帝江号")
        self.send_key("m", after_sleep=2)
        self.log_info("打开地图界面 (按下 M)")

        # 1. 确认是否打开地图并找到目标区域
        target_area = self.wait_ocr(
            match=re.compile("帝江号"), box=self.box.top, time_out=5
        )
        if not target_area:
            self.log_info("未找到帝江号区域，传送失败")
            return False
        self.log_info("找到帝江号区域，点击进入")
        self.click(target_area, after_sleep=2)

        # 2. 寻找传送点图标
        tp_icon = self.find_feature(
            feature_name="transfer_point", box=self.box.left, threshold=0.7
        )
        if not tp_icon:
            self.log_info("未找到传送点图标，传送失败")
            return False
        self.log_info("找到传送点图标，点击传送点")
        self.click(tp_icon, after_sleep=2)

        # 3. 等待传送按钮出现并点击
        transfer_btn = self.wait_ocr(
            match="传送", box=self.box.bottom_right, time_out=10, log=True
        )
        if not transfer_btn:
            self.log_info("未找到传送按钮，传送失败")
            return False
        self.log_info("找到传送按钮，点击进行传送")
        self.click(transfer_btn, after_sleep=2)

        # 4. 等待传送完成，验证是否到达舰桥
        self.log_info("等待传送完成，检查舰桥界面")
        if not self.wait_ocr(
                match="舰桥", box=self.box.left, time_out=60, log=True
        ):
            self.log_info("传送超时，未到达舰桥")
            return False

        self.log_info("传送完成，已到达帝江号舰桥")
        return True

    def go_main_hall(self) -> bool:
        self.log_info("开始前往中央环厅")
        for attempt in range(1, 13):
            self.log_info(f"第 {attempt}/12 次尝试移动前进")
            self.move_keys("w", duration=1)
            if self.wait_ocr(
                    match="中央环厅", box=self.box.left, log=True
            ):
                self.log_info("已到达中央环厅")
                return True
        self.log_info("前往中央环厅失败，未找到目标")
        return False

    def go_operator_liaison_station(self):
        self.log_info("开始前往干员联络站")
        self.send_key("m", after_sleep=2)
        self.log_info("打开地图界面 (按下 M)")

        # 查找联络站特征
        result = self.find_one(
            feature_name="operator_liaison_station",
            box=self.box_of_screen(0, 0, 1, 1),
            threshold=0.7,
        )
        if not result:
            self.log_info("未找到干员联络站图标")
            return LiaisonResult.FAIL
        self.log_info("找到干员联络站图标，点击进入")
        self.click(result, after_sleep=2)

        # 查找追踪按钮
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

        self.send_key("m", after_sleep=2)
        self.log_info("关闭地图界面 (按下 M)")

        self.align_ocr_or_find_target_to_center(
            ocr_match_or_feature_name_list="operator_liaison_station_out_map",
            only_x=True,
            threshold=0.7,
            ocr=False,
        )
        self.log_info("已对齐地图目标")

        # 开始移动到联络台
        start_time = time.time()
        short_distance_flag = False
        fail_count = 0

        while not self.wait_ocr(
                match=re.compile("联络"), box=self.box.bottom_right, time_out=1
        ):
            chat_box = self.find_feature(
                feature_name="chat_icon_dark",
            )
            if not chat_box:
                chat_box = self.find_feature(
                    feature_name="chat_icon_2",
                )
            else:
                self.send_key("f", after_sleep=2)
                return LiaisonResult.FIND_CHAT_ICON
            if chat_box:
                self.log_info("发现干员，点击交互图标")
                self.send_key_down("alt")
                self.sleep(0.5)
                self.click(chat_box)
                self.send_key_up("alt")
                return LiaisonResult.FIND_CHAT_ICON

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
                    self.log_info("找到导航路径，继续对齐并前进")
                    self.align_ocr_or_find_target_to_center(
                        ocr_match_or_feature_name_list="operator_liaison_station_out_map",
                        only_x=True,
                        threshold=0.7,
                        ocr=False,
                    )
                    self.move_keys("w", duration=1)
                else:
                    fail_count += 1
                    self.log_info(f"未找到导航路径，连续失败次数: {fail_count}")
                    if fail_count >= 3:
                        self.log_info("长时间未找到导航，切换短距离移动")
                        short_distance_flag = True
                    self.move_keys("w", duration=0.5)
            else:
                self.move_keys("w", duration=0.5)

            self.sleep(0.5)
            if time.time() - start_time > 60:
                self.log_info("长时间未找到联络台，任务超时")
                return LiaisonResult.FAIL

        self.log_info("成功到达干员联络台")
        return LiaisonResult.SUCCESS

    def operator_liaison_task(self):
        self.log_info("开始执行干员联络任务")

        # 尝试打开信任度界面并确认联络
        for attempt in range(1, 11):
            self.log_info(f"第 {attempt}/10 次尝试打开信任度界面")
            self.send_key("f", after_sleep=2)

            if not self.wait_click_ocr(
                    match=[re.compile(i) for i in ["会客", "培养", "制造"]],
                    time_out=5,
                    after_sleep=2,
            ):
                self.log_info("未找到联络界面，任务失败")
                return False
            self.log_info("找到联络界面")

            if not self.wait_click_ocr(
                    match=re.compile("确认联络"),
                    box=self.box.bottom_right,
                    time_out=5,
                    log=True,
            ):
                self.log_info("未找到确认联络按钮，任务失败")
                return False
            self.log_info("点击确认联络按钮")
            while self.ocr(match=re.compile("干员联络"), box=self.box.top_left):
                self.next_frame()
                self.sleep(0.1)
            find_flag = self.align_ocr_or_find_target_to_center(
                ocr_match_or_feature_name_list=[re.compile("工作"), re.compile("休息")],
                raise_if_fail=False,
                only_x=True,
                max_time=14,
                max_step=150,
                min_step=20,
                slow_radius=100,
                tolerance=100,
                once_time=0.1
            )
            if find_flag:
                self.log_info("界面对齐完成")
                break

        # 寻找干员进行交互
        self.log_info("开始寻找干员进行交互")
        start_time = time.time()
        chat_box = None

        while chat_box is None:
            chat_box = self.wait_ocr(
                match=self.all_name_pattern,
                box=self.box.bottom_right,
                time_out=2,
            )
            if chat_box:
                self.log_info("发现干员，点击进行交互")
                self.send_key_down("alt")
                self.sleep(0.5)
                self.click_box(chat_box)
                self.send_key_up("alt")
                self.log_info("干员联络完成")
                return True

            self.move_keys("w", duration=0.5)
            self.log_info("未找到干员，继续前进移动")
            self.sleep(0.5)

            if time.time() - start_time > 30:
                self.log_info("长时间未找到干员，任务超时")
                return False
        return False

    def collect_and_give_gifts(self):
        self.log_info("开始收取或赠送礼物")
        start_time = time.time()

        # 等待“收下”或“赠送”按钮出现
        while True:
            if time.time() - start_time > 30:
                self.log_info("等待 收下/赠送 超时")
                return False
            self.click(0.5, 0.5, after_sleep=0.5)
            result = self.wait_click_ocr(
                match=[re.compile("收下"), re.compile("赠送")],
                box=self.box.bottom_right,
                time_out=2,
                after_sleep=2,
            )
            if result:
                self.log_info(f"找到按钮: {result[0].name}")
                break
        # 如果是“收下”，先处理收下流程
        if result and len(result) > 0 and "收下" in result[0].name:
            self.log_info("开始收下礼物")
            self.skip_dialog(
                end_list=[re.compile("ms")], end_box=self.box.bottom_left
            )
            self.sleep(1)
            self.wait_click_ocr(
                match=re.compile("确认"),
                box=self.box.bottom_right,
                time_out=5,
                after_sleep=2,
            )
            self.send_key("f", after_sleep=2)

            start_time = time.time()
            while True:
                if time.time() - start_time > 30:
                    self.log_info("等待 收下/赠送 超时")
                    return False
                self.click(0.5, 0.5, after_sleep=0.5)
                result = self.wait_ocr(
                    match=[re.compile("赠送")],
                    box=self.box.bottom_right,
                    time_out=2,
                )
                if result:
                    self.log_info("收下完成，准备赠送礼物")
                    break

        # 开始赠送流程
        self.wait_click_ocr(
            match=re.compile("赠送"),
            box=self.box.bottom_right,
            time_out=5,
            after_sleep=2,
        )
        self.click(144 / 1920, 855 / 1080, after_sleep=2)
        self.log_info("点击赠送礼物位置")
        self.log_info("本次成功")
        if self.wait_click_ocr(
                match=re.compile("确认赠送"),
                box=self.box.bottom_right,
                time_out=5,
                after_sleep=2,
        ):
            self.log_info("确认赠送按钮已出现")
            start_time = time.time()
            while True:
                if time.time() - start_time > 30:
                    self.log_info("等待 离开按钮 超时")
                    return False
                self.click(0.5, 0.5, after_sleep=0.5)
                result = self.wait_click_ocr(
                    match=[re.compile("离开")],
                    box=self.box.bottom_right,
                    time_out=2,
                    after_sleep=2,
                )
                if result:
                    self.log_info("赠送完成，点击离开")
                    break
            self.log_info("成功赠送礼物")
            return True
        else:
            self.back(after_sleep=2)
            self.back(after_sleep=2)
            self.wait_click_ocr(match=re.compile("确认"), box=self.box.bottom_right, time_out=5, after_sleep=2)
        self.log_info("赠送礼物失败")
        return False

    def give_gift_to_liaison(self):
        self.log_info("传送至帝江号指定点")
        if not self.transfer_to_home_point():
            self.log_info("传送失败，无法开始送礼任务")
            return False
        while self.ocr(match="舰桥", box=self.box.left):
            self.next_frame()
            self.sleep(0.5)
        self.log_info("前往中央环厅")
        if not self.go_main_hall():
            self.log_info("未到达中央环厅，送礼任务中断")
            return False

        self.log_info("前往干员联络站")
        result = self.go_operator_liaison_station()

        if result == LiaisonResult.FIND_CHAT_ICON:
            self.log_info("发现干员聊天图标，开始收取或赠送礼物")
            return self.collect_and_give_gifts()

        elif result == LiaisonResult.SUCCESS:
            self.log_info("成功到达干员联络台，开始干员联络任务")
            if self.operator_liaison_task():
                self.log_info("干员联络完成，开始收取或赠送礼物")
                return self.collect_and_give_gifts()
            else:
                self.log_info("干员联络任务失败")
                return False

        else:
            self.log_info("前往联络站失败")
            return False

    def give_gift_main(self):
        self.info_set("current_task", "give_gift")
        self.log_info("开始执行送礼任务")

        max_retry = self.config.get("送礼任务最多尝试次数", 1)

        for i in range(max_retry):
            self.log_info(f"送礼任务 - 第 {i + 1}/{max_retry} 次尝试")

            success = self.give_gift_to_liaison()
            if success:
                self.log_info(f"第 {i + 1} 次送礼任务成功")
                return True

            self.log_info(f"第 {i + 1} 次送礼任务失败")

        self.log_info("送礼任务最终失败")
        return False
    def get_goods_piece(self):
        test_goods_re = re.compile("货组")
        market_text_y = None
        market_text = self.wait_ocr(match=re.compile("市场"), box=self.box.left)
        if market_text:
            market_text_y = market_text[0].y
        self.next_frame()
        goods = self.ocr(
            match=test_goods_re,
            log=True,
            box=self.box_of_screen(0, market_text[0].y / self.height, 1, 1),
        )

        sum_good_info = []
        for good in goods:
            self.click(good, after_sleep=1)
            self.next_frame()
            good_piece = self.ocr(
                match=re.compile(r"^\d+$"),
                box=self.box_of_screen(
                    1527 / 1920, 367 / 1080, 1600 / 1920, 400 / 1080
                ),
                log=True,
            )
            self.wait_click_ocr(
                match=re.compile("查看好友价格"),
                box=self.box.bottom_right,
                after_sleep=2,
            )
            self.wait_ui_stable(refresh_interval=1)
            self.next_frame()
            friend_name_piece = self.ocr(
                match=re.compile(r"\d+$"),
                box=self.box_of_screen(800 / 1920, 430 / 1080, 1270 / 1920, 490 / 1080),
                frame_processor=self.make_hsv_isolator(hR.DARK_GRAY_TEXT),
                log=True,
            )
            if not good_piece:
                good_piece = []
            if not friend_name_piece:
                friend_name_piece = []
            self.log_info(
                f"货物名称: {good.name}, "
                f"价格: {[i.name for i in good_piece]}, "
                f"价格来源人和价格: {[i.name for i in friend_name_piece]}"
            )
            sum_good_info.append([good] + good_piece + friend_name_piece)
            while not self.wait_ocr(
                match=re.compile("地区建设"), box=self.box.top_left, time_out=1
            ):
                self.back(after_sleep=0.5)

        return sum_good_info, market_text_y

    def azalyze_goods_piece(
        self, good_infos: List[List["Box"]], buy_price: int, sell_price: int
    ):
        processed_goods: List[GoodsInfo] = []

        # ========= 数据解析 =========
        for good_info in good_infos:
            try:
                name_box = good_info[0]
                friend_name_box = good_info[2] if len(good_info) > 2 else None
                good_name = name_box.name
                good_price = int(good_info[1].name)

                friend_price = (
                    int(good_info[3].name)
                    if len(good_info) > 3 and good_info[3].name.isdigit()
                    else None
                )

                processed_goods.append(
                    GoodsInfo(
                        good_name=good_name,
                        good_price=good_price,
                        friend_price=friend_price,
                        name_box=name_box,
                        friend_name_box=friend_name_box,
                    )
                )

            except Exception as e:
                self.log_error(f"解析货物失败: {good_info} | 错误: {e}")

        if not processed_goods:
            self.log_info("没有有效货物数据")
            return None, [], False

        # ========= 打印列表 =========
        self.log_info("===== 当前货物列表 =====")
        for good in processed_goods:
            self.log_info(
                f"[货物] 名称:{good.good_name:<10} "
                f"买价:{good.good_price:>6} "
                f"卖价:{str(good.friend_price):>6} "
            )

        # ========= 推荐购买 =========
        buy_good = min(processed_goods, key=lambda x: x.good_price)

        self.log_info(
            f"推荐购买 | 名称:{buy_good.good_name} " f"| 价格:{buy_good.good_price}"
        )

        # ========= 推荐出售 =========
        sell_goods = [
            good for good in processed_goods if good.friend_price > sell_price
        ]

        if sell_goods:
            self.log_info("===== 推荐出售列表 =====")
            for good in sell_goods:
                self.log_info(
                    f"推荐出售 | 名称:{good.good_name} " f"| 卖价:{good.friend_price}"
                )
        else:
            self.log_info("没有符合出售条件的货物")

        # ========= 购买判断 =========
        if buy_good.good_price < buy_price:
            self.log_info(
                f"满足购买条件 | 实际价格:{buy_good.good_price} "
                f"< 设定上限:{buy_price}"
            )
            return buy_good, sell_goods, True  # 返回可点击对象
        else:
            self.log_info(
                f"不满足购买条件 | 实际价格:{buy_good.good_price} "
                f">= 设定上限:{buy_price}"
            )
            return buy_good, sell_goods, False

    def to_friend_exchange(self):
        self.log_info("前往物资调度终端")
        self.send_key("m", after_sleep=2)
        result = self.find_feature(fL.market_dispatch_terminal)
        if not result:
            self.log_info("未找到物资调度终端")
            return False
        self.click(result, after_sleep=2)

        # 查找追踪按钮
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

        self.send_key("m", after_sleep=2)
        self.log_info("关闭地图界面 (按下 M)")

        self.align_ocr_or_find_target_to_center(
            ocr_match_or_feature_name_list=fL.market_dispatch_terminal_out,
            only_x=True,
            threshold=0.7,
            ocr=False,
        )
        self.log_info("已对齐地图目标")
        start_time = time.time()
        short_distance_flag = False
        fail_count = 0
        while not self.wait_ocr(
            match=re.compile("物资调度终端"), box=self.box.bottom_right, time_out=1
        ):
            if time.time() - start_time > 200:
                self.log_info("前往干员联络站超时")
                return False
            if not short_distance_flag:
                nav = self.find_feature(
                    fL.market_dispatch_terminal_out,
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
                        ocr_match_or_feature_name_list=fL.market_dispatch_terminal_out,
                        only_x=True,
                        threshold=0.7,
                        ocr=False,
                    )
                    self.move_keys("w", duration=1)
                else:
                    fail_count += 1
                    self.log_info(f"未找到导航路径，连续失败次数: {fail_count}")
                    if fail_count >= 3:
                        self.log_info("长时间未找到导航，切换短距离移动")
                        short_distance_flag = True
                    self.move_keys("w", duration=0.5)
            else:
                self.move_keys("w", duration=0.5)
        self.send_key("f", after_sleep=2)
        return True

    def buy_sell(self):
        for area in areas_list:
            if not self.config.get(area, False):
                self.log_info(f"跳过{area}，因为配置中未启用")
                continue
            self.ensure_main()
            self.log_info(f"前往{area}")
            self.to_model_area(area, "物资调度")
            self.wait_ui_stable(refresh_interval=1)
            self.wait_click_ocr(
                match=re.compile("弹性"), box=self.box.top, after_sleep=2
            )
            result = self.find_feature(fL.market_good_icon)
            if not result:
                self.log_info("未找到货物")
                continue
            self.click(result, after_sleep=2)
            good_infos,_= self.get_goods_piece()
            buy_price = self.config.get(f"{area}买入价", 0)
            sell_price = self.config.get(f"{area}卖出价", 0)
            if not (buy_price and sell_price):
                self.log_info("未找到买入价或卖出价")
                continue
            buy_good, sell_goods, can_buy = self.azalyze_goods_piece(
                good_infos, buy_price, sell_price
            )
            puls_minus_box = self.box_of_screen(0.36, 0.6630, 0.592, 0.8019)
            if buy_good:
                if not can_buy:
                    if self.wait_ocr(
                        match=[re.compile("即将"), re.compile("溢出")],
                        box=self.box.top_left,
                        time_out=3,
                    ):
                        can_buy = True
                if can_buy:
                    self.click(buy_good.name_box, after_sleep=2)
                    plus_button = self.find_feature(fL.market_plus_button,box=puls_minus_box)
                    minus_button = self.find_feature(fL.market_minus_button,box=puls_minus_box)
                    if plus_button:
                        self.click(plus_button, down_time=12)
                        self.wait_click_ocr(
                            match=re.compile("购买"),
                            box=self.box.bottom_right,
                            after_sleep=2,
                        )
                        self.wait_pop_up(after_sleep=2)
                    else:
                        self.log_info("未找到加号按钮，无法购买")
                        while not self.wait_ocr(
                            match=re.compile("地区建设"),
                            box=self.box.top_left,
                            time_out=1,
                        ):
                            self.back(after_sleep=0.5)
            for sell_good in sell_goods:
                if not (self.wait_click_ocr(match=re.compile(sell_good.name_box.name[-3:]),after_sleep=2) or self.wait_click_ocr(match=re.compile(sell_good.good_name[:3]),after_sleep=2)):
                    self.log_info("未找到卖出货物，无法出售")
                    continue
                self.wait_click_ocr(
                    match=re.compile("查看好友价格"),
                    box=self.box.bottom_right,
                    after_sleep=2,
                )
                self.wait_ui_stable(refresh_interval=1)
                c_y = (
                    sell_good.friend_name_box.y + sell_good.friend_name_box.height // 2
                )
                c_x = sell_good.friend_name_box.x - int((808 - 737) / 1920 * self.width)
                self.click(c_x, c_y, after_sleep=1)
                self.wait_click_ocr(
                    match=re.compile("前往"), box=self.box.center, after_sleep=2
                )
                if not self.ensure_in_friend_boat():
                    self.log_info("未进入好友船")
                    return False
                self.to_friend_exchange()
                self.wait_click_ocr(match=re.compile(area), box=self.box.top, after_sleep=2)
                if not (self.wait_click_ocr(match=re.compile(sell_good.name_box.name[-3:]),after_sleep=2) or self.wait_click_ocr(match=re.compile(sell_good.good_name[:3]),after_sleep=2)):
                    self.log_info("未找到卖出货物，无法出售")
                    continue
                plus_button = self.find_feature(fL.market_plus_button,box=puls_minus_box)
                minus_button = self.find_feature(fL.market_minus_button,box=puls_minus_box)
                if plus_button:
                    self.click(plus_button, down_time=12)
                    self.wait_click_ocr(
                        match=re.compile("出售"),
                        box=self.box.bottom_right,
                        after_sleep=2,
                    )
                    self.wait_pop_up(after_sleep=2)
                else:
                    self.log_info("未找到加号按钮，无法出售")
                    while not self.wait_ocr(
                        match=re.compile("地区建设"), box=self.box.top_left, time_out=1
                    ):
                        self.back(after_sleep=0.5)
        return True
