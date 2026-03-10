import re
import time
from dataclasses import dataclass
from typing import List, Tuple

from qfluentwidgets import FluentIcon
from ok import Box

from src.image.hsv_config import HSVRange as hR
from src.data.FeatureList import FeatureList as fL
from src.tasks.BaseNavTask import BaseNavTask
from src.navigation.Navigator import Navigator
from src.navigation.RouteStore import RouteStore

TASK_KEYWORD = "送货任务"

CFG_ORDER_TYPE = "接单方式"
ORDER_COMMISSION = "运送委托"
ORDER_LOCAL = "本地仓储"

CFG_AREA = "送货区域"
AREA_ALL = "全部"
AREA_WULING = "武陵"
AREA_VALLEY = "四号谷地"


@dataclass
class DeliveryRow:
    """Commission row - contains OCR elements and bounding box"""
    elems: List[Box]
    box: Tuple[float, float, float, float]


class GugaDeliveryTask(BaseNavTask):
    """Guga delivery task - uses Navigator route system for automated delivery"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "咕嘎物流"
        self.description = "基于自动导航的送货任务，需提前录制仓储节点和送货目的地的路线"
        self.icon = FluentIcon.SEND
        self.default_config = {
            "_enabled": True,
            CFG_ORDER_TYPE: ORDER_COMMISSION,
            CFG_AREA: AREA_ALL,
        }
        self.config_type[CFG_ORDER_TYPE] = {
            "type": "drop_down",
            "options": [ORDER_COMMISSION, ORDER_LOCAL],
        }
        self.config_description[CFG_ORDER_TYPE] = (
            f"{ORDER_COMMISSION}: 从运送委托列表接取他人委托\n"
            f"{ORDER_LOCAL}: 从本地仓储接取自有订单"
        )
        self.config_type[CFG_AREA] = {
            "type": "drop_down",
            "options": [AREA_ALL, AREA_WULING, AREA_VALLEY],
        }
        self.config_description[CFG_AREA] = (
            f"{AREA_ALL}: 武陵(×1) + 四号谷地(×3)\n"
            f"{AREA_WULING}: 仅武陵(×1)\n"
            f"{AREA_VALLEY}: 仅四号谷地(×3)"
        )

        self.store = RouteStore()
        self.navigator = Navigator(self, store=self.store)

        self.wuling_location = ["武陵城"]
        self.valley_location = ["供能高地", "矿脉源区", "源石研究园"]
        self.local_warehouses = [
            {"area": AREA_WULING, "count": 1},
            {"area": AREA_VALLEY, "count": 3},
        ]
        self._last_refresh_ts = 0

    # ── commission acceptance (from DeliveryTask) ──

    def _merge_left_right_groups(self) -> List[DeliveryRow]:
        """Merge OCR results from left/right/mid areas into commission rows"""

        def split_items_by_marker(items: list, marker: str):
            groups = []
            current = []
            for item in items:
                name = getattr(item, "name", "").strip()
                if not name:
                    continue
                current.append(item)
                if marker in name:
                    groups.append(current)
                    current = []
            if current:
                groups.append(current)
            return groups

        screen_scale_y1_y2 = {
            1.5: (254 / 1280, 1134 / 1280),
            1.0: (0.1271, 0.8561 + (0.8561 - 0.1271) / 11),
            9 / 16: (0.075, 0.7916),
            16 / 9: (290 / 1080, 926 / 1080),
        }
        screen_scale_desc = {
            1.5: "3:2（如 3000x2000）",
            1.0: "1:1（方屏/接近方屏窗口）",
            9 / 16: "9:16（竖屏）",
            16 / 9: "16:9（如 1920x1080、2560x1440）",
        }
        x_ranges = [
            (0.4776, 0.5505),
            (0.8438, 0.9167),
            (0.3141, 0.3641),
        ]
        screen_scale_areas = {
            ratio: [[x1, y1, x2, y2] for (x1, x2) in x_ranges]
            for ratio, (y1, y2) in screen_scale_y1_y2.items()
        }
        ratio = self.width / self.height
        area = screen_scale_areas.get(ratio)
        if area is None:
            supported = "、".join(
                f"{k:.4f} -> {v}" for k, v in screen_scale_desc.items()
            )
            raise ValueError(
                f"不支持的屏幕比例: {ratio:.6f}（当前分辨率: {self.width}x{self.height}）。"
                f"支持的比例有：{supported}。请调整游戏窗口比例"
            )

        left_box = self.box_of_screen(area[0][0], area[0][1], area[0][2], area[0][3])
        right_box = self.box_of_screen(area[1][0], area[1][1], area[1][2], area[1][3])
        mid_box = self.box_of_screen(area[2][0], area[2][1], area[2][2], area[2][3])

        areas = [
            ("left", left_box, 10),
            ("right", right_box, 10),
            ("mid", mid_box, 5),
        ]
        expected_ratio = [2, 2, 1]
        total_ratio = sum(expected_ratio)

        results = {name: [] for name, _, _ in areas}
        start_time = time.time()

        while True:
            self.next_frame()
            for name, box, _ in areas:
                results[name] = self.ocr(
                    match=re.compile(r"[\u4e00-\u9fff]+"),
                    box=box, log=True, threshold=0.8,
                )
            counts = [len(results[name]) for name, _, _ in areas]

            if time.time() - start_time > 2:
                break

            min_ok = all(c >= min_count for c, (_, _, min_count) in zip(counts, areas))
            total_count = sum(counts)
            if total_count % total_ratio != 0:
                ratio_ok = False
            else:
                unit = total_count // total_ratio
                ratio_ok = all(c == r * unit for c, r in zip(counts, expected_ratio))

            if min_ok and ratio_ok:
                break
            else:
                self.sleep(0.1)

        left_items = [i for i in results["left"] if getattr(i, "name", "").strip()]
        right_items = [i for i in results["right"] if getattr(i, "name", "").strip()]
        mid_items = [i for i in results["mid"] if getattr(i, "name", "").strip()]

        left_groups = [
            g for g in split_items_by_marker(left_items, "查看位置") if len(g) >= 2
        ]
        right_groups = [
            g for g in split_items_by_marker(right_items, "接取运送委托") if len(g) >= 2
        ]
        available_left = left_groups.copy()
        available_mid = mid_items.copy()

        rows = []
        for rg in right_groups:
            if rg[0].y < rg[1].y:
                rg_min_y = rg[0].y
                rg_max_y = rg[1].y + rg[1].height
            else:
                rg_min_y = rg[1].y
                rg_max_y = rg[0].y + rg[0].height

            matched_left = None
            matched_mid = None

            for lg in available_left:
                ys = [e.y for e in lg]
                if min(ys) >= rg_min_y and max(ys) <= rg_max_y:
                    matched_left = lg
                    break

            for m in available_mid:
                if rg_min_y <= m.y <= rg_max_y:
                    matched_mid = m
                    break

            if matched_left:
                available_left.remove(matched_left)
            if matched_mid:
                available_mid.remove(matched_mid)

            elems = []
            if matched_left:
                elems += matched_left
            if matched_mid:
                elems += [matched_mid]
            elems += rg

            if len(elems) >= 5:
                min_x = min(e.x for e in [elems[0], elems[-1]])
                max_x = max(e.x for e in [elems[0], elems[-1]])
                min_y = min(e.y for e in [elems[-2], elems[-1]])
                max_y = max(e.y + e.height for e in [elems[-2], elems[-1]])
                rows.append(DeliveryRow(elems=elems, box=(min_x, min_y, max_x, max_y)))

        return rows

    def _detect_ticket_type(self, row: DeliveryRow) -> str | None:
        """Detect ticket type from a commission row"""
        first_name = row.elems[0].name
        if any(k in first_name for k in self.wuling_location):
            return "ticket_wuling"
        if any(k in first_name for k in self.valley_location):
            return "ticket_valley"
        return None

    def _accept_commission_order(self):
        """Open commission panel, filter for wuling 7.31w orders, and accept one

        Returns:
            bool: True if order accepted successfully
        """
        self.ensure_main(time_out=120)
        self.log_info("opening commission panel")
        self.to_model_area("武陵", "仓储节点")
        delivery_box = self.wait_ocr(match="运送委托列表", time_out=5)
        if delivery_box:
            self.click(delivery_box[0], move_back=True, after_sleep=0.5)
        cx = int(self.width * 0.5)
        cy = int(self.height * 0.5)
        for _ in range(6):
            self.scroll(cx, cy, -8)
            self.sleep(0.2)
        self.wait_ui_stable(refresh_interval=1)

        while True:
            rows = self._merge_left_right_groups()
            for row in rows:
                if not row:
                    continue
                ticket_type = self._detect_ticket_type(row)
                if ticket_type != "ticket_wuling":
                    continue
                if "易损" not in row.elems[2].name or "不易损" in row.elems[2].name:
                    continue

                x, y, to_x, to_y = row.box
                box = self.box_of_screen(
                    x / self.width, y / self.height,
                    to_x / self.width, to_y / self.height,
                )
                if self.width >= 3800:
                    feature_list = [fL.wuling_7_31w_4k, fL.wuling_7_31w_dark_4k]
                elif self.width >= 2500:
                    feature_list = [fL.wuling_7_31w_2k, fL.wuling_7_31w_dark_2k]
                else:
                    feature_list = [fL.wuling_7_31w, fL.wuling_7_31w_dark]

                result = None
                for feature_name in feature_list:
                    result = self.find_feature(
                        feature_name=feature_name, box=box, threshold=0.98,
                    )
                    if result:
                        break
                if result:
                    self.click(row.elems[-1], after_sleep=2, down_time=0.1, move_back=True)
                    self.log_info("attempting to accept commission")
                    self.next_frame()
                    if not self.wait_ocr(match="接取运送委托", box=self.box.bottom_right, time_out=1):
                        self.log_info("commission accepted successfully")
                        return True
                    else:
                        self.log_info("accept failed (possibly taken), continuing search")

            self.log_info("no matching commission found, refreshing")
            for i in range(2):
                if last_refresh_box := self.wait_ocr(match="刷新", box=self.box.bottom_right):
                    now = time.time()
                    wait = max(0.0, 5.4 - (now - self._last_refresh_ts))
                    if wait > 0:
                        self.sleep(wait)
                    self.click(last_refresh_box, move_back=True)
                    self._last_refresh_ts = time.time()
                    self.wait_ui_stable(refresh_interval=1)
                    break
                else:
                    self.log_info("refresh button not found, retrying...")
                    time.sleep(1.0)

    def _accept_local_order(self, area):
        """Accept a local storage order from the warehouse node.

        Flow: to_model_area -> click 货物装箱 -> 下一步 -> 填充至满 -> 下一步 -> 开始运送 -> 点击屏幕继续

        Args:
            area: area name to select in the warehouse panel

        Returns:
            bool | None: True if accepted, False if failed, None if no orders
        """
        self.ensure_main(time_out=120)
        self.log_info(f"opening warehouse node for area: {area}")
        self.to_model_area(area, "仓储节点")

        # click first "货物装箱" (left to right)
        cargo_box = self.box_of_screen(0.13, 0.79, 0.77, 0.84)
        cargo_results = None
        start = time.time()
        while time.time() - start < 5:
            self.next_frame()
            cargo_results = self.ocr(
                match="货物装箱", box=cargo_box,
                frame_processor=self.make_hsv_isolator(hR.DARK_GRAY_TEXT),
            )
            if cargo_results:
                break
            self.sleep(0.3)
        if not cargo_results:
            self.log_info("未找到'货物装箱'，该区域无本地仓储订单")
            self.back(after_sleep=1)
            return None
        cargo_results.sort(key=lambda r: r.x)
        self.click(cargo_results[0], after_sleep=1)

        # click 下一步
        if not self.wait_click_ocr(match="下一步", box="bottom_right", time_out=5, after_sleep=1):
            self.log_error("未找到第一个'下一步'按钮")
            return False

        # click 填充至满
        fill_box = self.box_of_screen(0.85, 0.21, 0.95, 0.28)
        if not self.wait_click_ocr(match="填充至满", box=fill_box, time_out=5, after_sleep=1):
            self.log_error("未找到'填充至满'按钮")
            return False

        # click 下一步 again
        if not self.wait_click_ocr(match="下一步", box="bottom_right", time_out=5, after_sleep=1):
            self.log_error("未找到第二个'下一步'按钮")
            return False

        # wait for animation (~5s), then click 开始运送
        if not self.wait_click_ocr(match="开始运送", box="bottom_right", time_out=10, after_sleep=2):
            self.log_error("未找到'开始运送'按钮")
            return False

        # click screen to continue
        if not self.wait_ocr(match="点击屏幕继续", box="bottom", time_out=10):
            self.log_error("未找到'点击屏幕继续'提示")
            return False
        self.click_relative(0.5, 0.5, after_sleep=2)

        self.log_info("local order accepted successfully")
        return True

    # ── detection ──

    def _detect_pickup_location(self):
        """Open task panel with J, OCR the task info area to find the area name,
        then look up a storage node route in that area.

        Returns:
            dict | None: route dict for the storage node, or None
        """
        self.press_key("j", after_sleep=2)
        task_info_box = self.box_of_screen(0.32, 0.07, 0.40, 0.16)
        results = self.ocr(
            match=re.compile(r"[\u4e00-\u9fff]+"),
            box=task_info_box,
            log=True,
        )
        if not results:
            self.log_error("task panel OCR returned no text")
            self.back(after_sleep=1)
            return None

        area = None
        for r in results:
            if TASK_KEYWORD not in r.name:
                area = r.name.strip()
                break

        self.back(after_sleep=1)

        if not area:
            self.log_error("unable to detect area name from task panel")
            return None

        self.log_info(f"detected delivery area: {area}")
        route = self.store.find_by_area_and_type(area, "仓储节点")
        if not route:
            self.log_error(f"no storage node route found for area: {area}, please record the route first")
            return None

        return route

    def _detect_destination(self):
        """Detect the delivery destination name by HSV color isolation (yellow/gold).
        Scans screen region (0.36,0.25)~(0.97,0.29) for colored destination text.

        Returns:
            str | None: destination name, or None if not detected
        """
        dest_box = self.box_of_screen(0.36, 0.25, 0.97, 0.29)
        results = self.ocr(
            match=re.compile(r"[\u4e00-\u9fff]+"),
            box=dest_box,
            frame_processor=self.make_hsv_isolator(hR.DEST_TEXT),
            log=True,
        )
        if results:
            name = results[0].name.strip()
            self.log_info(f"detected destination: {name}")
            return name

        self.log_error("unable to detect destination text by color")
        return None

    # ── main flow ──

    def _run_single_delivery(self, order_type, area=None):
        """Execute a single delivery cycle: accept -> detect destination -> navigate -> deliver

        Args:
            order_type: ORDER_COMMISSION or ORDER_LOCAL
            area: area name, required for ORDER_LOCAL

        Returns:
            bool | None: True if completed, False if failed, None if no local orders
        """
        # accept order
        if order_type == ORDER_COMMISSION:
            if not self._accept_commission_order():
                self.log_error("failed to accept commission order")
                return False
        elif order_type == ORDER_LOCAL:
            result = self._accept_local_order(area)
            if result is None:
                return None  # no orders available, skip
            if not result:
                self.log_error("failed to accept local order")
                return False

        # detect pickup and navigate to storage (commission only)
        if order_type == ORDER_COMMISSION:
            pickup_route = self._detect_pickup_location()
            if not pickup_route:
                return False
            pickup_name = pickup_route.get("name")

            self.log_info(f"navigating to storage node: {pickup_name}")
            if not self.navigator.navigate_to(pickup_name, dest_type="仓储节点"):
                self.log_error(f"navigation to storage node failed: {pickup_name}")
                return False

        # detect destination
        destination = self._detect_destination()
        if not destination:
            self.log_error("unable to detect destination, task aborted")
            return False

        # navigate to destination and deliver
        dest_route = self.store.find(destination, dest_type="送货")
        if not dest_route:
            self.log_error(f"no route found for destination: {destination}, please record the route first")
            return False
        self.log_info(f"navigating to destination: {destination}")
        if not self.navigator.navigate_to(destination, dest_type="送货"):
            self.log_error(f"navigation to destination failed: {destination}")
            return False

        self.log_info("delivery completed")
        return True

    def execute(self, order_type=None, area_filter=None):
        """Execute delivery task. Can be called by other tasks.

        Args:
            order_type: ORDER_COMMISSION or ORDER_LOCAL, defaults to config value
            area_filter: AREA_ALL / AREA_WULING / AREA_VALLEY, defaults to config value

        Returns:
            bool: True if all deliveries completed successfully
        """
        self.ensure_main()
        if order_type is None:
            order_type = self.config.get(CFG_ORDER_TYPE)
        if area_filter is None:
            area_filter = self.config.get(CFG_AREA, AREA_ALL)

        if order_type == ORDER_LOCAL:
            warehouses = [
                w for w in self.local_warehouses
                if area_filter == AREA_ALL or w["area"] == area_filter
            ]
            total = sum(w["count"] for w in warehouses)
            completed = 0
            for warehouse in warehouses:
                area = warehouse["area"]
                count = warehouse["count"]
                for i in range(count):
                    completed += 1
                    self.log_info(f"local delivery {completed}/{total} (area: {area})")
                    result = self._run_single_delivery(ORDER_LOCAL, area=area)
                    if result is None:
                        self.log_info(f"no more local orders in {area}, skipping")
                        break
                    if not result:
                        return False
            return True
        else:
            return self._run_single_delivery(ORDER_COMMISSION)

    def run(self):
        return self.execute()
