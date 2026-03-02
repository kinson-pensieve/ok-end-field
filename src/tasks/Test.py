import re
import time
from src.data.world_map import exchange_goods_dict,areas_list
from src.image.hsv_config import HSVRange as hR
from src.tasks.BaseEfTask import BaseEfTask
from ok import Box
from dataclasses import dataclass
from typing import List, Optional
from src.data.FeatureList import FeatureList as fL


@dataclass
class GoodsInfo:
    good_name: str
    good_price: int
    friend_price: Optional[int]
    name_box: "Box"  # 只保留这一个 Box
    friend_name_box: Optional["Box"]  # 可选，只有当 friend_price 存在且可点击时才有值


class Test(BaseEfTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "测试"
        default_config = dict()
        for area in areas_list:
            default_config[f"{area}买入价"] = 900
            default_config[f"{area}卖出价"] = 4500
            default_config[area]=True
        self.default_config.update(default_config)
    def get_goods_piece(self):
        test_goods_re = re.compile("货组")
        market_text_y=None
        market_text=self.wait_ocr(match=re.compile("市场"),box=self.box.left)
        if market_text:
            market_text_y=market_text[0].y
        self.next_frame()
        goods=self.ocr(match=test_goods_re,log=True,box=self.box_of_screen(0,market_text[0].y/self.height,1,1))

        sum_good_info=[]
        for good in goods:
            self.click(good,after_sleep=1)
            self.next_frame()
            good_piece=self.ocr(match=re.compile(r"^\d+$"),box=self.box_of_screen(1527/1920,367/1080,1600/1920,400/1080),log=True)
            self.wait_click_ocr(match=re.compile("查看好友价格"), box=self.box.bottom_right, after_sleep=2)
            self.wait_ui_stable(refresh_interval=1)
            self.next_frame()
            friend_name_piece=self.ocr(match=re.compile(r"\d+$"),box=self.box_of_screen(800/1920,430/1080,1270/1920,490/1080),frame_processor=self.make_hsv_isolator(hR.DARK_GRAY_TEXT),log=True)
            if not good_piece:
                good_piece=[]
            if not friend_name_piece:
                friend_name_piece=[]
            self.log_info(
                f"货物名称: {good.name}, "
                f"价格: {[i.name for i in good_piece]}, "
                f"价格来源人和价格: {[i.name for i in friend_name_piece]}"
            )
            sum_good_info.append([good]+good_piece+friend_name_piece)
            while not self.wait_ocr(match=re.compile("地区建设"),box=self.box.top_left,time_out=1):
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
                friend_name_box=good_info[2] if len(good_info) > 2 else None
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
            return None, [],False

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
        sell_goods = [good for good in processed_goods if good.friend_price > sell_price]

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
            return buy_good,sell_goods,True  # 返回可点击对象
        else:
            self.log_info(
                f"不满足购买条件 | 实际价格:{buy_good.good_price} "
                f">= 设定上限:{buy_price}"
            )
            return buy_good, sell_goods,False

    def to_friend_exchange(self):
        self.log_info("前往物资调度终端")
        self.send_key("m", after_sleep=2)
        result=self.find_feature(fL.market_dispatch_terminal)
        if not result:
            self.log_info("未找到物资调度终端")
            return False
        self.click(result,after_sleep=2)

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
        short_distance_flag=False
        fail_count=0
        while not self.wait_ocr(match=re.compile("物资调度终端"), box=self.box.bottom_right, time_out=1):
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
            if not self._logged_in:
                self.ensure_main(time_out=240)
            else:
                self.ensure_main()
            self.log_info(f"前往{area}")
            self.to_model_area(area,"物资调度")
            self.wait_ui_stable(refresh_interval=1)
            self.wait_click_ocr(match=re.compile("弹性"), box=self.box.top, after_sleep=2)
            result=self.find_feature(fL.market_good_icon)
            if not result:
                self.log_info("未找到货物")
                return False
            self.click(result,after_sleep=2)
            good_infos, market_text_y = self.get_goods_piece()
            buy_price = self.config.get(f"{area}买入价", 0)
            sell_price = self.config.get(f"{area}卖出价", 0)
            if not (buy_price and sell_price and market_text_y):
                self.log_info("未找到买入价或卖出价")
                return False
            buy_good, sell_goods, can_buy = self.azalyze_goods_piece(good_infos, buy_price, sell_price)
            if buy_good:
                if not can_buy:
                    if self.wait_ocr(match=[re.compile("即将"),re.compile("溢出")], box=self.box.top_left, time_out=3):
                        can_buy=True
                if can_buy:
                    self.click(buy_good.name_box, after_sleep=1)
                    plus_button=self.find_feature(fL.market_plus_button)
                    minus_button=self.find_feature(fL.market_minus_button)
                    if plus_button:
                        self.click(plus_button, down_time=12)
                        self.wait_click_ocr(match=re.compile("购买"), box=self.box.bottom_right, after_sleep=2)
                        self.wait_pop_up(after_sleep=2)
                    else:
                        self.log_info("未找到加号按钮，无法购买")
                        while not self.wait_ocr(
                            match=re.compile("地区建设"), box=self.box.top_left, time_out=1
                        ):
                            self.back(after_sleep=0.5)
            change_y=False
            for sell_good in sell_goods:
                self.click(sell_good.name_box, after_sleep=1)
                self.wait_click_ocr(
                    match=re.compile("查看好友价格"),
                    box=self.box.bottom_right,
                    after_sleep=2,
                )
                self.wait_ui_stable(refresh_interval=1)
                c_y=sell_good.friend_name_box.y + sell_good.friend_name_box.height // 2
                c_x=sell_good.friend_name_box.x-int((808-737)/1920*self.width)
                self.click(c_x,c_y, after_sleep=1)
                self.wait_click_ocr(match=re.compile("前往"), box=self.box.center, after_sleep=2)
                if not self.ensure_in_friend_boat():
                    self.log_info("未进入好友船")
                    return False
                self.to_friend_exchange()
                if not change_y:
                    market_text = self.wait_ocr(match=re.compile("市场"), box=self.box.left)
                    if market_text:
                        market_text_after_y = market_text[0].y
                        for i in range(len(sell_goods)):
                            sell_goods[i].name_box.y += market_text_after_y - market_text_y
                        change_y=True
                self.click(sell_good.name_box, after_sleep=1)
                plus_button=self.find_feature(fL.market_plus_button)
                minus_button=self.find_feature(fL.market_minus_button)
                if plus_button:
                    self.click(plus_button, down_time=12)
                    self.wait_click_ocr(match=re.compile("出售"), box=self.box.bottom_right, after_sleep=2)
                    self.wait_pop_up(after_sleep=2)
                else:
                    self.log_info("未找到加号按钮，无法出售")
                    while not self.wait_ocr(
                        match=re.compile("地区建设"), box=self.box.top_left, time_out=1
                    ):
                        self.back(after_sleep=0.5)
