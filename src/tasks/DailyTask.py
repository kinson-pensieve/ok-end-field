import re
import time
import random
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

from ok import Box
from qfluentwidgets import FluentIcon

from src.data.FeatureList import FeatureList as fL
from src.data.characters import all_list
from src.data.characters_utils import get_contact_list_with_feature_list
from src.data.world_map import (
    areas_list,
    outpost_dict,
    default_goods,
)
from src.data.world_map_utils import (
    get_area_by_outpost_name,
    get_goods_by_outpost_name,
)
from src.image.hsv_config import HSVRange as hR
from src.tasks.BaseEfTask import BaseEfTask


class LiaisonResult(int, Enum):
    """前往联络站流程的结果枚举。

    - `SUCCESS`: 正常抵达并可继续后续联络流程
    - `FAIL`: 导航或交互失败
    - `FIND_CHAT_ICON`: 途中直接发现可交互干员图标，可跳过部分步骤
    """
    SUCCESS = 1
    FAIL = 2
    FIND_CHAT_ICON = 3


@dataclass
class GoodsInfo:
    """单个货物的识别与价格信息。

    Attributes:
        good_name: 货物名称
        good_price: 当前据点买入价
        friend_price: 好友据点卖出价（可能不存在）
        stock_quantity: 当前存货数量（用于控制是否执行售卖）
        name_box: 货物名称对应 OCR 框（用于二次点击定位）
        friend_name_box: 好友价格条目对应 OCR 框（用于定位目标好友）
    """
    good_name: str
    good_price: int
    friend_price: Optional[int]
    stock_quantity: int
    name_box: "Box"  # 只保留这一个 Box
    friend_name_box: Optional["Box"]  # 可选，只有当 friend_price 存在且可点击时才有值


class DailyTask(BaseEfTask):
    """日常任务聚合执行器。

    该类负责串联多个子任务（送礼、据点兑换、转交委托、信用收取、买卖货等），
    并基于配置进行启停控制、失败记录与日志输出。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.span_box = None
        self.name = "日常任务"
        self.description = "一键收菜"
        self.icon = FluentIcon.SYNC
        self.can_contact_dict = get_contact_list_with_feature_list()
        buy_sell = dict()
        for area in areas_list:
            buy_sell[f"{area}买入价"] = 900
            buy_sell[f"{area}卖出价"] = 4500
            buy_sell[area] = True
        self.default_config.update(buy_sell)
        self.default_config.update({"优先送礼对象": list(self.can_contact_dict.keys())[0]})
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
                "收集线索": True,
                "买卖货": True,
                "日常奖励": True,
            }
        )
        self.config_type["优先送礼对象"] = {"type": "drop_down", "options": list(self.can_contact_dict.keys())}
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
    def run(self):
        """日常任务主入口。

        调试模式下可根据配置重复执行，用于稳定性回归验证。
        """
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
            ("送礼", self.execute_gift_task),
            ("据点兑换", self.exchange_outpost_goods),
            ("转交运送委托", self.delivery_send_others),
            ("转交委托奖励领取", self.claim_delivery_rewards),
            ("造装备", self.make_weapon),
            ("收信用", self.collect_credit),
            ("收集线索", self.collect_clue),
            ("买卖货", self.buy_sell),
            ("日常奖励", self.claim_daily_rewards),
        ]
        all_fail_tasks = []
        if self.debug:
            for repeat_idx in range(repeat_times):
                self.log_info(f"开始第 {repeat_idx + 1}/{repeat_times} 轮任务执行")
                failed_tasks = []
                for key, func in tasks:
                    if not self.execute_task(key, func):
                        failed_tasks.append(key)
                if failed_tasks:
                    all_fail_tasks.append((repeat_idx + 1, failed_tasks))
                    self.log_info(f"第 {repeat_idx + 1} 轮 | 失败任务: {failed_tasks}", notify=True)
                else:
                    self.log_info(f"第 {repeat_idx + 1} 轮 | 日常完成!", notify=True)
            if all_fail_tasks:
                self.log_info(f"重复测试完成，失败统计: {all_fail_tasks}", notify=True)
            else:
                self.log_info("所有重复测试均成功完成!", notify=True)
        else:
            failed_tasks = []
            for key, func in tasks:
                if not self.execute_task(key, func):
                    failed_tasks.append(key)
            if failed_tasks:
                self.log_info(f"以下任务未完成或失败: {failed_tasks}", notify=True)
            else:
                self.log_info("日常完成!", notify=True)

    def execute_task(self, key, func):
        """统一执行单个子任务。
 
        Args:
            key: 任务配置键（字符串时会检查是否启用）
            func: 任务执行函数

        Returns:
            bool: 任务执行是否成功（或任务被配置跳过）
        """
        if isinstance(key, str):
            if not self.config.get(key, False):
                return True

        self.log_info(f"开始任务: {key}")
        self.ensure_main()
        result = func()

        if result is False:
            self.log_info(f"任务 {key} 执行失败", notify=True)
            return False
        return True
    def wait_friend_list(self, end_icon_name="friend_chat_icon"):
        """等待好友列表加载完成。

        Args:
            end_icon_name: 作为“加载完成”标志的特征名

        Returns:
            bool: 是否在超时时间内检测到目标特征
        """
        start_time = time.time()
        while True:
            if time.time() - start_time > 20:
                self.log_info("加载好友列表超时")
                return False
            if self.find_feature(feature_name=end_icon_name):
                return True
    def collect_credit(self):
        """收取信用并执行好友交流/助力流程。

        流程包含：
        1) 进入信用交易所并领取信用
        2) 进入好友系统，按剩余次数优先交流再助力
        3) 在次数耗尽或异常情况下结束拜访并返回
        """
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
        left_exchange_time = 5  # 剩余“情报交流”次数
        left_help_time = 5  # 剩余“生产助力”次数
        exchange_time = 0
        help_time = 0
        is_first_time = True
        exchange_help_box = self.box_of_screen(0.1, 561 / 861, 0.9, 0.9)  # 交流/助力按钮主要出现区域
        exchange_not_found = False
        count=0
        while True:
            if count>=10:
                self.log_info("循环过多次仍未找到交流或助力对象，可能出现异常，结束拜访")
                return False
            if is_first_time:
                self.wait_click_ocr(match=re.compile("好友"), box=self.box.right, time_out=5, after_sleep=2)
            else:
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
                    # 首次或已滚动后：使用完整列表扫描区域
                    self.span_box = self.box_of_screen(3400 / 3840, 301 / 2160, 3692 / 3840, 1883 / 2160)
                else:
                    # 首屏未滚动时：略过顶部，减少误检
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
                        self.press_key('f', after_sleep=2)
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
                    self.wait_ui_stable(refresh_interval=1)

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
            select_visit_deadline = time.time() + 30
            while not self.wait_click_ocr(match=re.compile("选择拜访"), box=self.box.top_left, time_out=1):
                if time.time() > select_visit_deadline:
                    self.log_info("等待 '选择拜访' 超时，结束本轮好友流程")
                    return False
                self.back(after_sleep=2)
            is_first_time = False
            count += 1

    def claim_delivery_rewards(self):
        """领取“我转交的委托”奖励。"""
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
        """执行各区域的“转交运送委托”流程。"""
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
                    match=[re.compile("货物装箱"),re.compile("查看报价")],
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
                start_index=0 if not("查看报价" in results[0].name) else 2
                steps = [
                    ("下一步", self.box.bottom_right),
                    ("填充至满", self.box.top_right),
                    ("下一步", self.box.bottom_right),
                    ("开始运送", self.box_of_screen(1548/1920,951/1080,1,1)),
                    ("获得调度券", self.box.bottom_right)
                ]

                for i in range(start_index, len(steps)):
                    step = steps[i]
                    match = step[0]
                    box = step[1]
                    timeout = 12 if i > 2 else 5
                    res = None
                    for time_index in range(2):
                        self.next_frame()
                        if time_index==0:
                            # 第一轮：常规 OCR
                            res = self.wait_ocr(match=re.compile(match), box=box, time_out=timeout,log=True)
                        else:
                            # 第二轮：颜色隔离兜底，提升深色/浅色文字场景命中率
                            res =self.ocr(match=re.compile(match), box=box,frame_processor=self.make_hsv_isolator(hR.DARK_GRAY_TEXT), log=True)
                            if not res:
                                res = self.ocr(match=re.compile(match), box=box, frame_processor=self.make_hsv_isolator(hR.WHITE), log=True)
                        if res:
                            self.log_info(f"找到步骤 {match}，继续下一步")
                            self.sleep(1)
                            self.click(res[0], after_sleep=2)
                            break

                    if not res and i!=2:  # 第3步“下一步”在某些活动中可能被替换为“开始运送”，因此不强制要求必须找到
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

    def read_outpost_ticket_num(self, outpost_name):
        """读取当前据点券数量。

        Args:
            outpost_name: 据点名称（用于日志）

        Returns:
            int: 当前识别到的据点券数量，识别失败时返回 0
        """
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

    def perform_outpost_exchange(self, outpost_name):
        """据点内循环尝试更换货品并兑换。

        当据点券低于阈值（1000）或无可兑换目标时结束。
        """
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
            num = self.read_outpost_ticket_num(outpost_name)
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

            num = self.read_outpost_ticket_num(outpost_name)
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
        """按区域遍历据点并执行兑换任务。"""
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
                self.perform_outpost_exchange(outpost_name)
                self.log_info(f"完成兑换据点: {outpost_name}")

            self.log_info(f"{area} 区域据点兑换完成，返回主界面")
            self.ensure_main()

        self.log_info("据点兑换任务完成")

    def make_weapon(self):
        """执行造装备流程。"""
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
        """领取日常任务奖励及可见的额外礼包。"""
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
            pass

        self.log_info("传送完成，已到达帝江号舰桥")
        return True

    def navigate_to_main_hall(self) -> bool:
        self.log_info("开始前往中央环厅")
        max_attempts = 2
        for attempt in range(1, max_attempts + 1):
            self.log_info(f"第 {attempt}/{max_attempts} 次尝试移动前进")
            self.move_keys("w", duration=1)
            if self.wait_ocr(
                    match="中央环厅", box=self.box.left, log=True
            ):
                self.log_info("已到达中央环厅")
                return True
        self.log_info("前往中央环厅可能失败，尝试后续操作")
        return True
    def start_tracking_and_align_target(self,target_feature_in_map,target_feature_out_map):
        """在地图中开启追踪并在地图外完成朝向对齐。

        Args:
            target_feature_in_map: 地图内目标图标特征名
            target_feature_out_map: 地图外导航目标特征名

        Returns:
            bool: 是否成功开启追踪并完成一次对齐
        """
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
            ocr_match_or_feature_name_list=target_feature_out_map,
            only_x=True,
            threshold=0.7,
            ocr=False,
        )
        self.log_info("已对齐地图目标")
        return True

    def navigate_to_operator_liaison_station(self):
        """前往干员联络站。

        Returns:
            LiaisonResult | bool:
                - `LiaisonResult.FIND_CHAT_ICON`: 途中发现可直接交互对象
                - `True`: 成功到达目标区域
                - `False`: 导航失败
        """
        self.log_info("开始前往干员联络站")
        self.send_key("m", after_sleep=2)
        self.log_info("打开地图界面 (按下 M)")
        # 开始移动到联络台
        if not self.start_tracking_and_align_target(
                fL.operator_liaison_station,fL.operator_liaison_station_out_map
        ):
            return False

        def special_chat_detect():
            chat_box = self.find_feature("chat_icon_dark") or \
                       self.find_feature("chat_icon_2")

            if chat_box:
                self.log_info("发现干员，点击交互图标")
                self.send_key_down("alt")
                self.sleep(0.5)
                self.click(chat_box)
                self.send_key_up("alt")
                return LiaisonResult.FIND_CHAT_ICON

            return None

        return self.navigate_until_target(
            target_ocr_pattern=re.compile("联络"),
            nav_feature_name="operator_liaison_station_out_map",
            timeout=60,
            found_special_callback=special_chat_detect,
        )
    def perform_operator_liaison(self):
        """执行干员联络（会客/培养/制造）并尝试完成一次交互。"""
        self.log_info("开始执行干员联络任务")
        # 尝试打开信任度界面并确认联络
        target_name = self.config.get("优先送礼对象")
        target_feature_name = self.can_contact_dict[target_name]
        search_char_box=self.box_of_screen(795/1920, 248/1080, 1687/1920, 764/1080)
        find_name=""
        for attempt in range(1, 11):
            self.log_info(f"第 {attempt}/10 次尝试打开信任度界面")
            self.press_key('f', after_sleep=2)
            result = {}
            found_target = False

            # 1 查找优先角色（允许 scroll）
            for _ in range(3):
                self.next_frame()

                found = self.find_one(feature_name=target_feature_name, box=search_char_box, threshold=0.7)

                if found:
                    result[target_feature_name] = found
                    found_target = True
                    break

                self.scroll_relative(0.5, 0.5, -3)
                self.wait_ui_stable(refresh_interval=0.5)

            # 2 查找其他角色（不 scroll）
            if not found_target:
                self.back(after_sleep=2)
                self.press_key('f', after_sleep=2)
                self.log_info(f"未找到联络对象 {target_name}，尝试其他目标")

                other_results = {}

                for other_name, other_feature in self.can_contact_dict.items():

                    if other_feature == target_feature_name:
                        continue

                    self.next_frame()

                    found = self.find_one(feature_name=other_feature, box=search_char_box, threshold=0.7)

                    if found:
                        other_results[other_feature] = found

                # 随机选一个
                if other_results:
                    feature = random.choice(list(other_results.keys()))
                    result[feature] = other_results[feature]

            # 3 最终判断
            if not result:
                self.log_info("未找到任何可联络对象")
                return False
            find_feature_name = next(iter(result))

            find_name = next(k for k, v in self.can_contact_dict.items() if v == find_feature_name)
            self.log_info("找到联络对象")
            self.click(list(result.values())[0], after_sleep=2)
            if not self.wait_click_ocr(
                    match=re.compile("确认联络"),
                    box=self.box.bottom_right,
                    time_out=5,
                    log=True,
            ):
                self.log_info("未找到确认联络按钮，任务失败")
                return False
            self.log_info("点击确认联络按钮")
            wait_disappear_count = 0
            while self.ocr(match=re.compile("干员联络"), box=self.box.top_left):
                wait_disappear_count += 1
                if wait_disappear_count >= 200:
                    self.log_info("等待 '干员联络' 文案消失次数超限，任务失败")
                    return False
                self.next_frame()
                self.sleep(0.2)
            self.next_frame()
            if not self.wait_ocr(match=find_name,box=self.box.top, time_out=2):
                self.log_info(f"未找到 {find_name} 的名字,重新打开联络界面")
                self.ensure_main()
                continue
            self.next_frame()
            if chat_box := self.ocr(match=find_name, box=self.box.bottom_right):
                self.log_info("发现干员，点击进行交互")
                self.send_key_down("alt")
                self.sleep(0.5)
                self.click_box(chat_box, after_sleep=1)
                self.next_frame()
                self.wait_click_ocr(match=find_name, box=self.box.bottom_right, time_out=1)
                self.send_key_up("alt")
                self.log_info("干员联络完成")
                return True
            self.log_info(f"找到 {find_name} 的名字，开始界面对齐")
            find_flag = self.align_ocr_or_find_target_to_center(
                ocr_match_or_feature_name_list=find_name,
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
                match=find_name,
                box=self.box.bottom_right,
                time_out=1,
            )
            if chat_box:
                self.log_info("发现干员，点击进行交互")
                self.send_key_down("alt")
                self.sleep(0.5)
                self.click_box(chat_box,after_sleep=1)
                self.next_frame()
                self.wait_click_ocr(match=find_name, box=self.box.bottom_right, time_out=1)
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
        """执行收礼/送礼完整流程。"""
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
            self.press_key('f', after_sleep=2)

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

    def execute_gift_to_liaison(self):
        """传送至帝江号后执行联络与送礼链路。"""
        self.log_info("传送至帝江号指定点")
        if not self.transfer_to_home_point():
            self.log_info("传送失败，无法开始送礼任务")
            return False
        wait_bridge_disappear_count = 0
        while self.ocr(match="舰桥", box=self.box.left):
            wait_bridge_disappear_count += 1
            if wait_bridge_disappear_count >= 120:
                self.log_info("等待 '舰桥' 文案消失次数超限，送礼任务中断")
                return False
            self.next_frame()
            self.sleep(0.5)
        self.log_info("舰桥提示已经消失，等待信赖弹窗并消失")
        start_time = time.time()
        if self.wait_ocr(match=re.compile("信赖"), box=self.box.left, time_out=5):
            while self.ocr(match=re.compile("信赖"), box=self.box.left):
                if time.time() - start_time > 10:
                    self.log_info("等待 '信赖' 弹窗超时，进行下一步")
                self.next_frame()
                self.sleep(0.5)
        self.log_info("前往中央环厅")
        if not self.navigate_to_main_hall():
            self.log_info("未到达中央环厅，送礼任务中断")
            return False

        self.log_info("前往干员联络站")
        result = self.navigate_to_operator_liaison_station()

        if result == LiaisonResult.FIND_CHAT_ICON:
            self.log_info("发现干员聊天图标，开始收取或赠送礼物")
            return self.collect_and_give_gifts()

        elif result:
            self.log_info("成功到达干员联络台，开始干员联络任务")
            if self.perform_operator_liaison():
                self.log_info("干员联络完成，开始收取或赠送礼物")
                return self.collect_and_give_gifts()
            else:
                self.log_info("干员联络任务失败")
                return False

        else:
            self.log_info("前往联络站失败")
            return False

    def execute_gift_task(self):
        """送礼任务入口，支持失败重试。"""
        self.info_set("current_task", "give_gift")
        self.log_info("开始执行送礼任务")

        max_retry = self.config.get("送礼任务最多尝试次数", 1)

        for i in range(max_retry):
            self.log_info(f"送礼任务 - 第 {i + 1}/{max_retry} 次尝试")

            success = self.execute_gift_to_liaison()
            if success:
                self.log_info(f"第 {i + 1} 次送礼任务成功")
                return True

            self.log_info(f"第 {i + 1} 次送礼任务失败")

        self.log_info("送礼任务最终失败")
        return False
    def collect_market_goods_info(self):
        def ocr_stock_quantity() -> int:
            """
            识别当前选中货物的存货数量。
            """
            stock_piece = self.ocr(
                match=re.compile(r"^\d+$"),
                box=self.box_of_screen(353/1920, 607/1080, 613/1920, 635/1080),
                log=True,
            )
            if stock_piece and stock_piece[0].name.isdigit():
                return int(stock_piece[0].name)
            return 0

        """采集当前市场货物与好友价格信息。

        Returns:
            tuple[list, int | None]:
                - 货物信息列表（每项包含名称框、买价、好友名/好友价等 OCR 结果）
                - “市场”标题的 y 坐标（用于调试/后续定位）
        """
        test_goods_re = re.compile("货组")
        market_text_y = None  # 返回给调用方用于后续调试/定位参考
        market_text = self.wait_ocr(match=re.compile("市场"), box=self.box.left)
        if market_text:
            market_text_y = market_text[0].y
        if not market_text:
            self.log_info("未识别到市场文字")
            return [], None
        self.next_frame()
        goods = self.ocr(
            match=test_goods_re,
            log=True,
            box=self.box_of_screen(0, market_text[0].y / self.height, 1, 1),
        )

        sum_good_info = []
        for good in goods:
            self.click(good, after_sleep=2)
            self.wait_ui_stable(refresh_interval=1)
            self.next_frame()
            stock_quantity = ocr_stock_quantity()
            good_piece = self.ocr(
                match=re.compile(r"^\d+$"),
                box=self.box_of_screen(1527 / 1920, 324 / 1080, 1600 / 1920, 400 / 1080),
                frame_processor=self.make_hsv_isolator(hR.DARK_GRAY_TEXT),
                log=True,
            )
            if not good_piece:
                good_piece = self.ocr(
                    match=re.compile(r"^\d+$"),
                    box=self.box_of_screen(1527 / 1920, 324 / 1080, 1600 / 1920, 400 / 1080),
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
                f"存货数量: {stock_quantity}, "
                f"价格: {[i.name for i in good_piece]}, "
                f"价格来源人和价格: {[i.name for i in friend_name_piece]}"
            )
            sum_good_info.append(
                {
                    "good": good,
                    "good_piece": good_piece,
                    "friend_name_piece": friend_name_piece,
                    "stock_quantity": stock_quantity,
                }
            )
            back_to_area_deadline = time.time() + 20
            while not self.wait_ocr(
                match=re.compile("地区建设"), box=self.box.top_left, time_out=1
            ):
                if time.time() > back_to_area_deadline:
                    self.log_info("等待返回 '地区建设' 界面超时，结束当前市场采集")
                    return sum_good_info, market_text_y
                self.back(after_sleep=0.5)

        return sum_good_info, market_text_y

    def analyze_goods_info(
        self, good_infos: List[dict], buy_price: int, sell_price: int
    ):
        """分析货物数据并给出买卖建议。

        Args:
            good_infos: `collect_market_goods_info()` 的原始解析结果
            buy_price: 可接受的最高买入价（低于该值才建议买）
            sell_price: 建议卖出的最低好友价阈值（高于该值才建议卖）

        Returns:
            tuple[GoodsInfo | None, list[GoodsInfo], bool]:
                - 推荐买入货物（可能为 None）
                - 推荐卖出货物列表
                - 是否满足买入条件
        """
        processed_goods: List[GoodsInfo] = []

        # ========= 数据解析 =========
        for good_info in good_infos:
            try:
                name_box = good_info.get("good")
                good_piece = good_info.get("good_piece", [])
                friend_name_piece = good_info.get("friend_name_piece", [])
                stock_quantity = good_info.get("stock_quantity", 0)

                if not name_box or not good_piece:
                    raise ValueError("缺少货物名称或价格信息")

                friend_name_box = friend_name_piece[0] if len(friend_name_piece) > 0 else None
                good_name = name_box.name
                good_price = int(good_piece[0].name)

                friend_price = (
                    int(friend_name_piece[1].name)
                    if len(friend_name_piece) > 1 and friend_name_piece[1].name.isdigit()
                    else None
                )

                processed_goods.append(
                    GoodsInfo(
                        good_name=good_name,
                        good_price=good_price,
                        friend_price=friend_price,
                        stock_quantity=stock_quantity,
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
                f"存货:{good.stock_quantity:>3} "
                f"买价:{good.good_price:>6} "
                f"卖价:{str(good.friend_price):>6} "
            )

        # ========= 推荐购买 =========
        buy_good = min(processed_goods, key=lambda x: x.good_price)

        self.log_info(
            f"推荐购买 | 名称:{buy_good.good_name} " f"| 价格:{buy_good.good_price}"
        )

        # ========= 推荐出售 =========
        try:
            sell_goods = [
                good for good in processed_goods if good.friend_price > sell_price
            ]
        except TypeError:
            self.log_error("好友价格数据异常，无法进行出售分析")
            sell_goods = []

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

    def navigate_to_friend_exchange(self):
        """导航至好友船的物资调度终端并尝试交互。"""
        self.log_info("前往物资调度终端")
        self.send_key("m", after_sleep=2)
        if not self.start_tracking_and_align_target(
                fL.market_dispatch_terminal,fL.market_dispatch_terminal_out
        ):
            return False
        result = self.navigate_until_target(
            target_ocr_pattern=re.compile("物资调度终端"),
            nav_feature_name=fL.market_dispatch_terminal_out,
            timeout=200,
        )

        if result:
            self.press_key('f', after_sleep=2)
        return result
    def buy_sell(self):
        """按区域执行买卖货流程。

        逻辑要点：
        - 本地据点：评估买入条件后执行批量购买
        - 好友据点：根据好友高价信息进行定向出售
        """
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
            good_infos, _ = self.collect_market_goods_info()
            buy_price = self.config.get(f"{area}买入价", 0)
            sell_price = self.config.get(f"{area}卖出价", 0)
            if not (buy_price and sell_price):
                self.log_info("未找到买入价或卖出价")
                continue
            buy_good, sell_goods, can_buy = self.analyze_goods_info(
                good_infos, buy_price, sell_price
            )
            puls_minus_box = self.box_of_screen(0.36, 0.6630, 0.592, 0.8019)  # 数量加减按钮区域（plus/minus）
            if buy_good:
                if not can_buy:
                    if self.wait_ocr(
                        match=[re.compile("即将"), re.compile("溢出")],
                        box=self.box.top_left,
                        time_out=3,
                    ):
                        can_buy = True
                if can_buy:
                    back_to_area_deadline = time.time() + 20
                    while not self.wait_ocr(
                        match=re.compile("地区建设"),
                        box=self.box.top_left,
                        time_out=1,
                    ):
                        if time.time() > back_to_area_deadline:
                            self.log_info(
                                "等待返回 '地区建设' 界面超时，结束买卖货任务"
                            )
                            return False
                        self.back(after_sleep=0.5)
                    self.click(buy_good.name_box, after_sleep=2)
                    plus_button = self.find_feature(fL.market_plus_button,box=puls_minus_box)
                    self.find_feature(fL.market_minus_button, box=puls_minus_box)
                    if plus_button:
                        self.click(plus_button, down_time=12)
                        self.wait_click_ocr(
                            match=re.compile("购买"),
                            box=self.box.bottom_right,
                            after_sleep=2,
                        )
                        self.wait_pop_up(after_sleep=2)
                        # 若本次购买的货物也在“推荐出售”列表中，则同步更新其存货数量
                        for sg in sell_goods:
                            if sg.good_name == buy_good.good_name:
                                sg.stock_quantity += 1
                                self.log_info(
                                    f"{sg.good_name} 本次已购买，存货数量更新为 {sg.stock_quantity}"
                                )
                                break
                    else:
                        self.log_info("未找到加号按钮，无法购买")

            for sell_good in sell_goods:
                if sell_good.stock_quantity <= 0:
                    self.log_info(f"跳过出售 {sell_good.good_name}，存货数量<=0")
                    continue
                # 名称可能存在 OCR 误差：优先尝试末尾 3 字，再尝试前 3 字进行容错匹配
                back_to_area_deadline = time.time() + 20
                while not self.wait_ocr(
                    match=re.compile("地区建设"), box=self.box.top_left, time_out=1
                ):
                    if time.time() > back_to_area_deadline:
                        self.log_info("等待返回 '地区建设' 界面超时，结束买卖货任务")
                        return False
                    self.back(after_sleep=0.5)
                if not (self.wait_click_ocr(match=re.compile(sell_good.name_box.name[-3:]),after_sleep=2) or self.wait_click_ocr(match=re.compile(sell_good.good_name[:3]),after_sleep=2)):
                    self.log_info("未找到卖出货物，无法出售")
                    continue
                self.wait_click_ocr(
                    match=re.compile("查看好友价格"),
                    box=self.box.bottom_right,
                    after_sleep=2,
                )
                self.wait_ui_stable(refresh_interval=1)
                try:
                    c_y = (
                        sell_good.friend_name_box.y + sell_good.friend_name_box.height // 2
                    )
                    c_x = sell_good.friend_name_box.x - int((808 - 737) / 1920 * self.width)
                except AttributeError:
                    self.log_info("未找到好友价格，无法出售")
                    continue
                self.click(c_x, c_y, after_sleep=1)
                go_friend_deadline = time.time() + 20
                while not self.wait_click_ocr(
                        match=re.compile("前往"), box=self.box.center, after_sleep=2
                    ):
                    if time.time() > go_friend_deadline:
                        self.log_info("等待 '前往' 按钮超时，跳过该货物出售")
                        break
                    self.click(c_x, c_y, after_sleep=1)
                if time.time() > go_friend_deadline:
                    continue
                if not self.ensure_in_friend_boat():
                    self.log_info("未进入好友船")
                    return False
                self.navigate_to_friend_exchange()
                self.wait_click_ocr(match=re.compile(area), box=self.box.top, after_sleep=2)
                # 再次容错匹配，避免好友市场中同名/近似名导致漏点
                if not (self.wait_click_ocr(match=re.compile(sell_good.name_box.name[-3:]),after_sleep=2) or self.wait_click_ocr(match=re.compile(sell_good.good_name[:3]),after_sleep=2)):
                    self.log_info("未找到卖出货物，无法出售")
                    continue
                plus_button = self.find_feature(fL.market_plus_button,box=puls_minus_box)
                self.find_feature(fL.market_minus_button, box=puls_minus_box)
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

        return True

    def navigate_until_target(
            self,
            target_ocr_pattern,
            nav_feature_name,
            timeout: int = 60,
            pre_loop_callback=None,
            found_special_callback=None,
    ):
        """通用导航循环：识别目标前持续前进并动态对齐。

        Args:
            target_ocr_pattern: 目标 OCR 文本正则，命中即结束
            nav_feature_name: 导航特征名（地图外方向参考）
            timeout: 最大导航时长（秒）
            pre_loop_callback: 每轮循环前的可选回调
            found_special_callback: 每轮循环中的特殊检测回调，返回非 None 立即结束

        Returns:
            bool | Any: 命中目标返回 True；超时返回 False；
            若 `found_special_callback` 返回非 None，则原样透传该结果。
        """
        start_time = time.time()
        short_distance_flag = False  # 连续识别失败后，进入短步直行兜底
        fail_count = 0  # 导航特征连续丢失计数

        while not self.wait_ocr(
                match=target_ocr_pattern,
                box=self.box.bottom_right,
                time_out=1,
        ):

            # ===== 超时保护 =====
            if time.time() - start_time > timeout:
                self.log_info("导航超时")
                return False

            # ===== 特殊检测（如聊天图标）=====
            if found_special_callback:
                special_result = found_special_callback()
                if special_result is not None:
                    return special_result

            # ===== 外部循环前逻辑 =====
            if pre_loop_callback:
                pre_loop_callback()

            # ===== 主导航逻辑 =====
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
    def collect_clue(self):
        """收集线索，完成相关任务。"""
        self.info_set("current_task", "collect_clue")
        self.log_info("开始收集线索任务")
        self.send_key("i",after_sleep=2)
        exchange_help_box = self.box_of_screen(0.1, 561 / 861, 0.9, 0.9)
        if self.wait_click_ocr(match=re.compile("会客室"), time_out=4, box=exchange_help_box,after_sleep=2):
            self.logger.info("进入会客室,准备处理收集线索")
            self.wait_click_ocr(match=re.compile("确认"), time_out=4, box=self.box.bottom,after_sleep=2)
            if self.wait_click_ocr(match=re.compile("收集"), time_out=4, box=self.box.right,after_sleep=2):
                self.logger.info("点击收集线索")
                self.wait_click_ocr(match="领取", time_out=4, box=self.box.bottom_right,after_sleep=2)
                self.back(after_sleep=1)
            else:
                self.logger.info("未找到收集线索按钮")

            if self.wait_click_ocr(match=re.compile("接收"), time_out=4, box=self.box.right,after_sleep=2):
                self.wait_click_ocr(match=re.compile("全部接收"), time_out=4, box=self.box.right,after_sleep=2)
                self.back(after_sleep=2)
            else:
                self.logger.info("未找到接收按钮")
            results = []

            search_box = self.box_of_screen(
                x=1390 / 3840, y=450 / 2160, to_x=3360 / 3840, to_y=1330 / 2160
            )

            for i in range(1, 8):
                self.next_frame()
                result = self.find_one(
                    feature_name=f"clue_{i}_icon",
                    box=search_box,
                )
                if result:
                    results.append(result)
                    self.sleep(0.5)

            for result in results:
                self.logger.info("点击线索框")
                self.click(result)
                self.wait_click_ocr(match=re.compile("的线索"),time_out=4, box=self.box.top_right,after_sleep=1)
                if not self.wait_ocr(match=[re.compile(i) for i in ["设施","等级"]],box=self.box.left, time_out=1):
                    self.back(after_sleep=2)
            if self.wait_click_ocr(match=re.compile("开展交流"), time_out=4, box=self.box.bottom,after_sleep=1):
                self.wait_pop_up()
            self.log_info("收集线索任务完成")
            return True
        else:
            self.logger.info("未找到会客室，无法收集线索")
            return False
