import json
import re
import time
import random
import win32gui
import win32api
from dataclasses import dataclass
from pathlib import Path
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
            f"{AREA_ALL}: 武陵 + 四号谷地\n"
            f"{AREA_WULING}: 仅武陵\n"
            f"{AREA_VALLEY}: 仅四号谷地"
        )

        self.store = RouteStore()
        self.navigator = Navigator(self, store=self.store)

        self.wuling_location = ["武陵城"]
        self.valley_location = ["供能高地", "矿脉源区", "源石研究园"]
        self._last_refresh_ts = 0

        # Load recycling stations for resource recycling center detection
        self.recycling_stations = self._load_recycling_stations()


    def _load_recycling_stations(self) -> list[dict]:
        """Load recycling station coordinates from JSON file.

        File format:
        [
          {
            "name": "资源回收站",
            "region": "武陵",
            "area": "武陵城",
            "direction": "top_left",
            "coordinates": "0.5,0.5"
          }
        ]

        Returns:
            list[dict]: list of recycling stations with coordinates and direction
        """
        stations_file = Path(__file__).parent.parent.parent / "assets" / "recycling_stations.json"
        if not stations_file.exists():
            self.log_warning(f"recycling_stations.json not found at {stations_file}")
            return []
        try:
            with open(stations_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            self.log_error(f"failed to load recycling_stations.json: {e}")
            return []

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

        Flow: to_model_area -> click action button -> execute packing (if needed) -> 开始运送 -> 点击屏幕继续

        For 查看任务: task panel is already open, read pickup location then navigate to storage.

        Args:
            area: area name to select in the warehouse panel

        Returns:
            dict | None | bool: dict (pickup route) if 查看任务, True if accepted, False if failed, None if no orders
        """
        self.ensure_main(time_out=120)
        self.log_info(f"opening warehouse node for area: {area}")
        self.to_model_area(area, "仓储节点")

        # scan for action buttons by priority: 查看任务 > 查看报价 > 货物装箱
        action_box = self.box_of_screen(0.13, 0.79, 0.77, 0.84)
        action_priorities = ["查看任务", "查看报价", "货物装箱"]
        target = None
        start = time.time()
        while time.time() - start < 5:
            self.next_frame()
            all_results = self.ocr(
                match=re.compile("|".join(action_priorities)), box=action_box,
                frame_processor=self.make_hsv_isolator(hR.DARK_GRAY_TEXT),
            )
            if all_results:
                # pick highest priority, then leftmost
                for action in action_priorities:
                    matches = [r for r in all_results if action in r.name]
                    if matches:
                        matches.sort(key=lambda r: r.x)
                        target = matches[0]
                        break
            if target:
                break
            self.sleep(0.3)
        if not target:
            self.log_info("未找到可用操作按钮，该区域无本地仓储订单")
            self.back(after_sleep=1)
            return None
        action_name = target.name
        self.log_info(f"clicking: {action_name}")
        self.sleep(2)
        self.click(target, after_sleep=1)

        if "查看任务" in action_name:
            # already packed, task panel is now open (equivalent to pressing J)
            # read pickup location from panel, then need to navigate to storage
            pickup_route = self._read_pickup_from_panel()
            return pickup_route  # return route dict to signal special handling

        if "货物装箱" in action_name:
            # full packing flow: 下一步 -> 填充至满 -> 下一步
            if not self.wait_click_ocr(match="下一步", box="bottom_right", time_out=5, after_sleep=1):
                self.log_error("未找到第一个'下一步'按钮")
                return False

            fill_box = self.box_of_screen(0.85, 0.21, 0.95, 0.28)
            if not self.wait_click_ocr(match="填充至满", box=fill_box, time_out=5, after_sleep=1):
                self.log_error("未找到'填充至满'按钮")
                return False

            if not self.wait_click_ocr(match="下一步", box="bottom_right", time_out=5, after_sleep=1):
                self.log_error("未找到第二个'下一步'按钮")
                return False

        # 查看报价 and 货物装箱 both continue from here: 开始运送 -> 点击屏幕继续
        if not self.wait_click_ocr(match="开始运送", box="bottom_right", time_out=10, after_sleep=2):
            self.log_error("未找到'开始运送'按钮")
            return False

        if not self.wait_ocr(match="点击屏幕继续", box="bottom", time_out=10):
            self.log_error("未找到'点击屏幕继续'提示")
            return False
        self.click_relative(0.5, 0.5, after_sleep=2)

        self.log_info("local order accepted successfully")
        return True

    # ── detection ──

    def _read_pickup_from_panel(self):
        """Read the task panel (already open) to find the area name,
        then look up a storage node route in that area.

        Used when 查看任务 is clicked - the panel is already open without pressing J.

        Returns:
            dict | None: route dict for the storage node, or None
        """
        task_info_box = self.box_of_screen(0.32, 0.07, 0.45, 0.16)
        results = self.ocr(
            match=re.compile(r"[\u4e00-\u9fff]+"),
            box=task_info_box,
            log=True,
        )
        if not results:
            self.log_error("task panel OCR returned no text")
            self.back()
            self.ensure_main(time_out=10)
            return None

        area = None
        for r in results:
            if TASK_KEYWORD not in r.name:
                area = r.name.strip()
                break

        self.back()
        self.ensure_main(time_out=10)

        if not area:
            self.log_error("unable to detect area name from task panel")
            return None

        self.log_info(f"detected delivery area: {area}")
        route = self.store.find_by_area_and_type(area, "仓储节点")
        if not route:
            self.log_error(f"no storage node route found for area: {area}, please record the route first")
            return None

        return route

    def _detect_pickup_location(self):
        """Open task panel with J, OCR the task info area to find the area name,
        then look up a storage node route in that area.

        Returns:
            dict | None: route dict for the storage node, or None
        """
        self.press_key("j", after_sleep=2)
        task_info_box = self.box_of_screen(0.32, 0.07, 0.45, 0.16)
        results = self.ocr(
            match=re.compile(r"[\u4e00-\u9fff]+"),
            box=task_info_box,
            log=True,
        )
        if not results:
            self.log_error("task panel OCR returned no text")
            self.back()
            self.ensure_main(time_out=10)
            return None

        area = None
        for r in results:
            if TASK_KEYWORD not in r.name:
                area = r.name.strip()
                break

        self.back()
        self.ensure_main(time_out=10)

        if not area:
            self.log_error("unable to detect area name from task panel")
            return None

        self.log_info(f"detected delivery area: {area}")
        route = self.store.find_by_area_and_type(area, "仓储节点")
        if not route:
            self.log_error(f"no storage node route found for area: {area}, please record the route first")
            return None

        return route

    def _detect_destination(self, current_area: str = None):
        """Detect the delivery destination name by HSV color isolation (yellow/gold).
        Scans screen region (0.36,0.25)~(0.97,0.29) for colored destination text.

        For resource recycling center, iterates through stations in the area and clicks
        to confirm the correct one via "追踪中的任务" prompt.

        Args:
            current_area: Current area name, used for recycling station matching

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
        if not results:
            self.log_error("unable to detect destination text by color")
            return None

        destination = results[0].name.strip()
        self.log_info(f"detected destination: {destination}")

        # Handle resource recycling center (special case)
        if destination == "资源回收站":
            confirmed_destination = self._confirm_recycling_station(current_area)
            return confirmed_destination if confirmed_destination else None

        return destination

    def _confirm_recycling_station(self, area: str) -> str | None:
        """For recycling stations, iterate through all stations in the area.
        Works like Teleporter: open map -> drag by direction -> click coordinates -> detect "追踪中的任务" in bottom_right.
        Returns the station name which is used to find the corresponding delivery route.

        Args:
            area: Current area name to filter recycling stations

        Returns:
            str | None: station name if confirmed, None otherwise
        """
        # Find all recycling stations in the current area
        area_stations = [
            s for s in self.recycling_stations
            if s.get("area") == area
        ]

        if not area_stations:
            self.log_error(f"no recycling stations found for area: {area}")
            return None

        self.log_info(f"found {len(area_stations)} recycling stations in {area}, iterating to confirm")

        # Close task panel before confirming stations
        self.back()
        self.ensure_main(time_out=5)

        for station in area_stations:
            station_name = station.get("name")
            self.log_info(f"confirming recycling station: {station_name}")

            # Open map for this station
            self.press_key("m", after_sleep=2)
            self.sleep(1)

            # Drag map to direction (like Teleporter)
            direction = station.get("direction", "")
            if direction:
                self.log_debug(f"dragging map to {direction}...")
                self._drag_to_direction(direction)
                self.sleep(0.5)

            # Click the station coordinates on map
            coordinates = station.get("coordinates", "")
            if not coordinates:
                self.log_error(f"no coordinates for station: {station_name}")
                self.press_key("esc", after_sleep=0.5)  # Close map back to task panel
                continue

            self.log_debug(f"clicking coordinates: {coordinates}")
            try:
                x, y = map(float, coordinates.split(","))
                self.click(x, y, after_sleep=0.5)
            except Exception as e:
                self.log_error(f"failed to parse coordinates: {coordinates}, error: {e}")
                self.press_key("esc", after_sleep=0.5)  # Close map back to task panel
                continue

            # Check if "追踪中任务" appears in bottom_right (confirms this is the correct station)
            tracking_box = self.wait_ocr(match="追踪中任务", box="bottom_right", time_out=2)
            if tracking_box:
                self.log_info(f"confirmed recycling station: {station_name}")
                self.press_key("esc", after_sleep=0.5)  # Close map, keep task panel for caller to handle
                return station_name
            else:
                self.log_info(f"station {station_name} is not the target, closing map and retrying")
                self.press_key("esc", after_sleep=0.5)  # Close map back to task panel

        self.log_error("failed to confirm any recycling station in area")
        return None

    def _drag_to_direction(self, direction, drag_count=3):
        """Drag map to specified direction (same as Teleporter)"""
        center_x = int(self.width / 2)
        center_y = int(self.height / 2)

        direction_map = {
            "right": (-self.width // 2, 0),
            "left": (self.width // 2, 0),
            "bottom": (0, -self.height // 2),
            "top": (0, self.height // 2),
            "bottom_right": (-self.width // 2, -self.height // 2),
            "top_right": (-self.width // 2, self.height // 2),
            "bottom_left": (self.width // 2, -self.height // 2),
            "top_left": (self.width // 2, self.height // 2),
        }

        if direction == "center":
            self.log_debug("executing center drag: bottom_right then drag back...")
            self._drag_to_direction("bottom_right")
            self.sleep(0.15)
            self._move_mouse_to(center_x, center_y)
            self.sleep(0.05)
            self.drag_mouse(int(self.width / 2), int(self.height / 2))
            self._move_mouse_to(center_x, center_y)
            return

        offset = direction_map.get(direction)
        if offset:
            for i in range(drag_count):
                if drag_count > 1:
                    self.log_debug(f"dragging {i+1}/{drag_count}...")

                self._move_mouse_to(
                    center_x + random.randint(-50, 50),
                    center_y + random.randint(-50, 50))
                self.sleep(0.05)
                self.drag_mouse(offset[0], offset[1])

                if i < drag_count - 1:
                    self.sleep(0.15)

            self._move_mouse_to(center_x, center_y)
        else:
            self.log_error(f"unknown direction: {direction}")

    def _move_mouse_to(self, x, y):
        """Move mouse to position without clicking (same as Teleporter)"""
        if isinstance(x, float) and 0 <= x <= 1:
            abs_x = int(x * self.width)
        else:
            abs_x = int(x)

        if isinstance(y, float) and 0 <= y <= 1:
            abs_y = int(y * self.height)
        else:
            abs_y = int(y)

        hwnd = self.hwnd.hwnd
        rect = win32gui.GetWindowRect(hwnd)
        window_x, window_y = rect[0], rect[1]

        screen_x = window_x + abs_x
        screen_y = window_y + abs_y

        win32api.SetCursorPos((screen_x, screen_y))

    # ── main flow ──

    def _run_single_delivery(self, order_type, area=None):
        """Execute a single delivery cycle: accept -> navigate to storage -> detect destination -> navigate -> deliver

        For local orders, handles three cases:
        - 查看任务: panel opened automatically, read pickup location
        - 查看报价: need to click 开始运送, then read pickup location with J
        - 货物装箱: need full packing flow, then read pickup location with J

        Args:
            order_type: ORDER_COMMISSION or ORDER_LOCAL
            area: area name, required for ORDER_LOCAL

        Returns:
            bool | None: True if completed, False if failed, None if no local orders
        """
        # accept order
        pickup_route = None
        if order_type == ORDER_COMMISSION:
            if not self._accept_commission_order():
                self.log_error("failed to accept commission order")
                return False
        elif order_type == ORDER_LOCAL:
            result = self._accept_local_order(area)
            if result is None:
                return None  # no orders available, skip
            elif isinstance(result, dict):
                # 查看任务: result is already the pickup route from the task panel
                pickup_route = result
            elif not result:
                self.log_error("failed to accept local order")
                return False

        # detect pickup location and navigate to storage node (only if not already obtained)
        if not pickup_route:
            pickup_route = self._detect_pickup_location()
        if not pickup_route:
            return False
        pickup_name = pickup_route.get("name")
        pickup_area = pickup_route.get("area")
        self.log_info(f"navigating to storage node: {pickup_name}")
        if not self.navigator.navigate_to(pickup_name, dest_type="仓储节点"):
            self.log_error(f"navigation to storage node failed: {pickup_name}")
            return False

        # detect destination from task panel
        self.press_key("j", after_sleep=2)
        destination = self._detect_destination(current_area=pickup_area)
        if not destination:
            self.log_error("unable to detect destination, task aborted")
            return False
        self.back()  # close task panel
        self.ensure_main(time_out=10)  # confirm returned to main world (will press ESC repeatedly if needed)

        # navigate to destination and deliver
        # Always use "送货" type for delivery - recycling stations are also delivered via "送货", not "资源回收站"
        dest_type = "送货"
        dest_route = self.store.find(destination, dest_type=dest_type)
        if not dest_route:
            self.log_error(f"no route found for destination: {destination}, please record the route first")
            return False
        self.log_info(f"navigating to destination: {destination}")
        if not self.navigator.navigate_to(destination, dest_type=dest_type):
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
            bool: True if delivery completed successfully
        """
        self.ensure_main()
        if order_type is None:
            order_type = self.config.get(CFG_ORDER_TYPE)
        if area_filter is None:
            area_filter = self.config.get(CFG_AREA, AREA_ALL)

        if order_type == ORDER_LOCAL:
            # Determine which areas to process based on filter
            if area_filter == AREA_ALL:
                areas = [AREA_WULING, AREA_VALLEY]
            else:
                areas = [area_filter]

            # Loop through each area until no more orders found
            for area in areas:
                while True:
                    self.log_info(f"attempting local delivery in {area}")
                    result = self._run_single_delivery(ORDER_LOCAL, area=area)
                    if result is None:
                        self.log_info(f"no more local orders in {area}")
                        break
                    if not result:
                        return False
            return True
        else:
            return self._run_single_delivery(ORDER_COMMISSION)

    def run(self):
        return self.execute()
