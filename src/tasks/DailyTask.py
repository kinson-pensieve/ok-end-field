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
                "转交运送委托": True,
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
        self.log_info("开始执行日常任务...")
        if self.debug:

            repeat_times = self.config.get("重复测试的次数", 1)
            self.log_info(f"当前为调试模式，重复执行 {repeat_times} 次")
        tasks = [
            ("送礼", self.give_gift_to_liaison),
            ("造装备", self.make_weapon),
            ("日常奖励", self.claim_daily_rewards),
            ("据点兑换", self.exchange_outpost_goods),
            ("转交运送委托", self.delivery_send_others),
        ]
        if self.debug:
            tasks = tasks * repeat_times
            all_fail_tasks = []
        failed_tasks = []
        for key, func in tasks:
            if key != "ensure_main":
                keys = [key] if isinstance(key, str) else list(key)
                if not any(self.config.get(k) for k in keys):
                    continue
            self.ensure_main()
            self.sleep(2)
            result = func()
            if result is False:
                self.log_info(f"任务 {key} 执行失败或未完成")
                failed_tasks.append(key)
        if failed_tasks:
            if self.debug:
                all_fail_tasks.append(failed_tasks)
            self.log_info(f"以下任务未完成或失败: {failed_tasks}", notify=True)
        else:
            self.log_info("日常完成!", notify=True)
        if self.debug and all_fail_tasks:
            self.log_info(f"所有重复测试的失败任务: {all_fail_tasks}", notify=True)

    def delivery_send_others(self):
        self.info_set("current_task", "delivery_send_others")

        for area in areas_list:
            activity_num = 0
            count = 0
            self.log_info(f"开始处理区域: {area}", notify=True)

            while True:
                # 守卫式 1: 已完成预定次数
                if 0 < activity_num <= count:
                    self.log_info(
                        f"{area}仓储节点已完成{activity_num}次，停止继续", notify=True
                    )
                    break

                self.to_model_area(area, "仓储节点")

                # 守卫式 2: 找不到仓储入口直接退出
                if not self.wait_click_ocr(
                    match=re.compile("本地仓储节点"),
                    box=screen_position.TOP_LEFT.value,
                    time_out=5,
                    after_sleep=2,
                ):
                    self.log_info(f"{area}未找到本地仓储节点，返回主界面", notify=True)
                    self.ensure_main()
                    break

                # 检查可操作货物
                results = self.wait_ocr(
                    match=re.compile("货物装箱"),
                    box=screen_position.BOTTOM.value,
                    time_out=5,
                )

                # 守卫式 3: 没有货物可操作则退出
                if not results:
                    self.log_info(
                        f"{area} 当前没有货物装箱可操作，返回主界面", notify=True
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
                    ("下一步", screen_position.BOTTOM_RIGHT),
                    ("填充至满", screen_position.TOP_RIGHT),
                    ("下一步", screen_position.BOTTOM_RIGHT),
                    ("开始运送", screen_position.BOTTOM_RIGHT, 12),
                    ("获得调度券", screen_position.BOTTOM_RIGHT, 12),
                    (["工业", "探索"], screen_position.TOP_LEFT, 5),
                ]

                for step in steps:
                    match = step[0]
                    box = step[1].value
                    timeout = step[2] if len(step) > 2 else 5
                    res = self.wait_ocr(match=match, box=box, time_out=timeout)
                    if not res:
                        self.log_info(f"步骤 {match} 未找到，跳过本次活动", notify=True)
                        self.ensure_main()
                        break

                # 操作后快捷键
                self.send_key("v", after_sleep=1)
                self.send_key("j", after_sleep=1)

                # 最终确认
                if not self.wait_click_ocr(
                    match=re.compile("转交运送委托"),
                    box=screen_position.BOTTOM_LEFT.value,
                    time_out=5,
                    after_sleep=2,
                ):
                    self.log_info(
                        "未找到 '转交运送委托' 按钮，跳过本次活动", notify=True
                    )
                    self.ensure_main()
                    break
                if not self.wait_click_ocr(
                    match=re.compile("确认"),
                    box=screen_position.BOTTOM_RIGHT.value,
                    time_out=5,
                    after_sleep=2,
                ):
                    self.log_info("未找到 '确认' 按钮，跳过本次活动", notify=True)
                    self.ensure_main()
                    break

                self.sleep(2)
                count += 1
                self.log_info(f"{area} 已完成 {count}/{activity_num} 次转交")

    def exchange_the_outpost_goods(self, outpost_name):
        self.log_info(f"开始处理据点: {outpost_name}", notify=True)
        self.wait_click_ocr(
            match=outpost_name, box=screen_position.TOP.value, time_out=5, after_sleep=2
        )

        can_exchange_goods = default_goods.get(
            get_area_by_outpost_name(outpost_name), []
        )
        max_attempts = 5
        attempt = 0
        skip_goods = set()

        while attempt < max_attempts:
            num_str = self.wait_ocr(
                match=re.compile(r"\d+"),
                box=self.box_of_screen(
                    x=1224 / 1920, y=235 / 1080, width=327, height=121
                ),
                time_out=5,
            )
            num = 0
            if num_str and len(num_str) > 0 and hasattr(num_str[0], "name"):
                try:
                    num = int(num_str[0].name)
                except ValueError:
                    num = 0

            self.log_info(f"{outpost_name} 据点当前券数量: {num}")
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
                box=screen_position.BOTTOM_RIGHT.value,
                time_out=5,
                after_sleep=2,
            )

            num_str = self.wait_ocr(
                match=re.compile(r"\d+"),
                box=self.box_of_screen(
                    x=1224 / 1920, y=235 / 1080, width=327, height=121
                ),
                time_out=5,
            )
            num = 0
            if num_str and len(num_str) > 0 and hasattr(num_str[0], "name"):
                try:
                    num = int(num_str[0].name)
                except ValueError:
                    num = 0

            self.log_info(f"{outpost_name} 据点当前券数量: {num}")
            if num < 1000:
                self.log_info(f"{outpost_name} 据点当前券数量不足 (<1000)，停止兑换")
                break

            plus_button = self.find_one(
                feature_name="plus_button",
                box=screen_position.BOTTOM_RIGHT.value,
                threshold=0.8,
            )
            if plus_button:
                self.log_info(f"找到加号按钮，执行点击")
                self.click(plus_button, down_time=12)
                self.wait_click_ocr(
                    match="交易",
                    box=screen_position.BOTTOM_RIGHT.value,
                    time_out=5,
                    after_sleep=2,
                )
                self.wait_pop_up()
                self.sleep(2)

        self.log_info(f"{outpost_name} 兑换操作完成")

    def test_ocr(self):
        self.wait_click_ocr(
            match=re.compile("获得调度卷"),
            box=screen_position.BOTTOM_RIGHT.value,
            after_sleep=2,
            time_out=12,
            log=True,
        )

    def exchange_outpost_goods(self):
        self.info_set("current_task", "exchange_outpost_goods")
        self.log_info("开始据点兑换任务", notify=True)

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

        self.log_info("据点兑换任务完成", notify=True)

    def make_weapon(self):
        self.info_set("current_task", "make_weapon")
        self.log_info("开始造装备任务")

        self.back()
        self.log_info("打开终端界面")

        if not self.wait_click_ocr(
            match=re.compile("装备"),
            box=screen_position.RIGHT.value,
            time_out=5,
            after_sleep=2,
        ):
            self.log_info("未找到装备按钮，任务失败", notify=True)
            return False
        self.log_info("找到装备按钮并点击")

        if not self.wait_click_ocr(
            match=re.compile("制作"),
            box=screen_position.BOTTOM_RIGHT.value,
            time_out=5,
            after_sleep=2,
        ):
            self.log_info("未找到制作按钮，任务失败", notify=True)
            return False
        self.log_info("找到制作按钮并点击")

        self.wait_pop_up()
        self.log_info("等待弹窗完成，造装备任务准备完成")

        return True

    def claim_daily_rewards(self):
        self.info_set("current_task", "claim_daily_rewards")
        self.log_info("开始领取日常奖励任务", notify=True)

        self.sleep(2)
        self.send_key("f8", after_sleep=2)
        self.log_info("按下 F8 打开日常奖励界面")

        if not self.wait_click_ocr(
            match=re.compile("日常"),
            box=screen_position.TOP.value,
            time_out=5,
            after_sleep=2,
        ):
            self.log_info("未找到日常奖励按钮，任务失败", notify=True)
            return False
        self.log_info("找到日常奖励按钮并点击")

        # 循环领取所有可领取奖励
        self.wait_click_ocr(
            match=re.compile("领取"),
            box=screen_position.RIGHT.value,
            time_out=5,
            after_sleep=2,
        )

        # 检查是否有额外奖励可领取
        if result := self.find_one(
            feature_name="claim_gift", box=screen_position.LEFT.value, threshold=0.8
        ):
            self.log_info("发现可领取的额外奖励，点击领取")
            self.click(result, after_sleep=2)
            self.wait_pop_up()
            self.log_info("额外奖励领取完成")
            return True

        self.log_info("日常奖励领取完成", notify=True)
        return True

    def transfer_to_home_point(self):
        """通过地图界面传送到帝江号指定点"""
        self.log_info("开始传送到帝江号", notify=True)
        self.send_key("m")
        self.log_info("打开地图界面 (按下 M)")

        # 1. 确认是否打开地图并找到目标区域
        target_area = self.wait_ocr(
            match=re.compile("帝江号"), box=screen_position.TOP.value, time_out=5
        )
        if not target_area:
            self.log_info("未找到帝江号区域，传送失败", notify=True)
            return False
        self.log_info("找到帝江号区域，点击进入")
        self.click(target_area, after_sleep=2)

        # 2. 寻找传送点图标
        tp_icon = self.find_feature(
            feature_name="transfer_point", box=screen_position.LEFT.value, threshold=0.7
        )
        if not tp_icon:
            self.log_info("未找到传送点图标，传送失败", notify=True)
            return False
        self.log_info("找到传送点图标，点击传送点")
        self.click(tp_icon, after_sleep=2)

        # 3. 等待传送按钮出现并点击
        transfer_btn = self.wait_ocr(
            match="传送", box=screen_position.BOTTOM_RIGHT.value, time_out=10, log=True
        )
        if not transfer_btn:
            self.log_info("未找到传送按钮，传送失败", notify=True)
            return False
        self.log_info("找到传送按钮，点击进行传送")
        self.click(transfer_btn, after_sleep=2)

        # 4. 等待传送完成，验证是否到达舰桥
        self.log_info("等待传送完成，检查舰桥界面")
        if not self.wait_ocr(
            match="舰桥", box=screen_position.LEFT.value, time_out=60, log=True
        ):
            self.log_info("传送超时，未到达舰桥", notify=True)
            return False

        self.log_info("传送完成，已到达帝江号舰桥", notify=True)
        return True

    def go_main_hall(self) -> bool:
        self.log_info("开始前往中央环厅")
        for attempt in range(1, 13):
            self.log_info(f"第 {attempt}/12 次尝试移动前进")
            self.move_keys("w", duration=1)
            if self.wait_ocr(
                match="中央环厅", box=screen_position.LEFT.value, log=True
            ):
                self.log_info("已到达中央环厅")
                return True
        self.log_info("前往中央环厅失败，未找到目标")
        return False

    def go_operator_liaison_station(self):
        self.log_info("开始前往干员联络站", notify=True)
        self.send_key("m", after_sleep=2)
        self.log_info("打开地图界面 (按下 M)")

        # 查找联络站特征
        result = self.find_one(
            feature_name="operator_liaison_station",
            box=self.box_of_screen(0, 0, 1, 1),
            threshold=0.7,
        )
        if not result:
            self.log_info("未找到干员联络站图标", notify=True)
            return LiaisonResult.FAIL
        self.log_info("找到干员联络站图标，点击进入")
        self.click(result, after_sleep=2)

        # 查找追踪按钮
        if result := self.wait_ocr(
            match=re.compile("追踪"), box=screen_position.BOTTOM_RIGHT.value, time_out=5
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
            match=re.compile("联络"), box=screen_position.BOTTOM_RIGHT.value, time_out=1
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
                self.log_info("长时间未找到联络台，任务超时", notify=True)
                raise Exception("长时间未找到联络台")

        self.log_info("成功到达干员联络台")
        return LiaisonResult.SUCCESS

    def operator_liaison_task(self):
        self.log_info("开始执行干员联络任务", notify=True)
        find_flag = False

        # 尝试打开信任度界面并确认联络
        for attempt in range(1, 11):
            self.log_info(f"第 {attempt}/10 次尝试打开信任度界面")
            self.send_key("f", after_sleep=2)

            if not self.wait_click_ocr(
                match=[re.compile(i) for i in ["会客", "培养", "制造"]],
                time_out=5,
                after_sleep=2,
            ):
                self.log_info("未找到联络界面，任务失败", notify=True)
                return False
            self.log_info("找到联络界面")

            if not self.wait_click_ocr(
                match=re.compile("确认联络"),
                box=screen_position.BOTTOM_RIGHT.value,
                time_out=5,
                log=True,
            ):
                self.log_info("未找到确认联络按钮，任务失败", notify=True)
                return False
            self.log_info("点击确认联络按钮")

            find_flag = self.align_ocr_or_find_target_to_center(
                ocr_match_or_feature_name_list=[re.compile("工作"), re.compile("休息")],
                raise_if_fail=False,
                only_x=True,
                max_time=5,
                max_step=150,
                min_step=50,
                slow_radius=20,
                tolerance=100,
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
                box=screen_position.BOTTOM_RIGHT.value,
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
                self.log_info("长时间未找到干员，任务超时", notify=True)
                raise Exception("长时间未找到干员")

    def collect_and_give_gifts(self):
        self.log_info("开始收取或赠送礼物", notify=True)
        start_time = time.time()
        result = None

        # 等待“收下”或“赠送”按钮出现
        while True:
            if time.time() - start_time > 30:
                self.log_info("等待 收下/赠送 超时", notify=True)
                return False
            self.click(0.5, 0.5, after_sleep=0.5)
            result = self.wait_click_ocr(
                match=[re.compile("收下"), re.compile("赠送")],
                box=screen_position.BOTTOM_RIGHT.value,
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
                end_list=[re.compile("ms")], end_box=screen_position.BOTTOM_LEFT.value
            )
            self.sleep(1)
            self.wait_click_ocr(
                match=re.compile("确认"),
                box=screen_position.BOTTOM_RIGHT.value,
                time_out=5,
                after_sleep=2,
            )
            self.send_key("f", after_sleep=2)

            start_time = time.time()
            while True:
                if time.time() - start_time > 30:
                    self.log_info("等待 收下/赠送 超时", notify=True)
                    return False
                self.click(0.5, 0.5, after_sleep=0.5)
                result = self.wait_ocr(
                    match=[re.compile("赠送")],
                    box=screen_position.BOTTOM_RIGHT.value,
                    time_out=2,
                )
                if result:
                    self.log_info("收下完成，准备赠送礼物")
                    break

        # 开始赠送流程
        self.wait_click_ocr(
            match=re.compile("赠送"),
            box=screen_position.BOTTOM_RIGHT.value,
            time_out=5,
            after_sleep=2,
        )
        self.click(144 / 1920, 855 / 1080, after_sleep=2)
        self.log_info("点击赠送礼物位置")

        if self.wait_click_ocr(
            match=re.compile("确认赠送"),
            box=screen_position.BOTTOM_RIGHT.value,
            time_out=5,
            after_sleep=2,
        ):
            self.log_info("确认赠送按钮已出现")
            start_time = time.time()
            while True:
                if time.time() - start_time > 30:
                    self.log_info("等待 离开按钮 超时", notify=True)
                    return False
                self.click(0.5, 0.5, after_sleep=0.5)
                result = self.wait_click_ocr(
                    match=[re.compile("离开")],
                    box=screen_position.BOTTOM_RIGHT.value,
                    time_out=2,
                    after_sleep=2,
                )
                if result:
                    self.log_info("赠送完成，点击离开")
                    break
            self.log_info("成功赠送礼物", notify=True)
            return True
        else:
            self.back(after_sleep=2)
            self.back(after_sleep=2)
            self.wait_click_ocr(match=re.compile("确认"),box=screen_position.BOTTOM_RIGHT.value, time_out=5, after_sleep=2)
        self.log_info("赠送礼物失败", notify=True)
        return False

    def give_gift_to_liaison(self):
        self.log_info("开始送礼任务", notify=True)

        self.log_info("传送至帝江号指定点")
        if not self.transfer_to_home_point():
            self.log_info("传送失败，无法开始送礼任务", notify=True)
            return False

        self.log_info("前往中央环厅")
        if not self.go_main_hall():
            self.log_info("未到达中央环厅，送礼任务中断", notify=True)
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
                self.log_info("干员联络任务失败", notify=True)
                return False

        else:
            self.log_info("前往联络站失败", notify=True)
            raise Exception("前往联络站失败")
