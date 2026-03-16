import json
import re
import time
import random
import win32gui
import win32api
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

# Removed: @dataclass DeliveryRow (no longer used with TakeDeliveryTask approach)

CFG_ORDER_TYPE = "接单方式"
ORDER_COMMISSION = "运送委托"
ORDER_LOCAL = "本地仓储"

CFG_AREA = "送货区域"
AREA_ALL = "全部"
AREA_WULING = "武陵"
AREA_VALLEY = "四号谷地"

# Commission filter configuration per area
COMMISSION_CONFIG = {
    AREA_WULING: {
        "ticket_types": ["ticket_wuling"],
        "filter_min": 7.9,
        "filter_max": 7.99,
    },
    AREA_VALLEY: {
        "ticket_types": ["ticket_valley"],
        "filter_min": 30.0,
        "filter_max": 32.0,
    },
}


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

    # ── commission acceptance (TakeDeliveryTask approach) ──

    def _process_ocr_results(self, full_texts: list, filter_min: float, reward_pattern, filter_max: float = 100.0) -> tuple:
        """Process OCR results - extract rewards, accept buttons, and refresh button.

        Args:
            full_texts: list of OCRItem from OCR
            filter_min: minimum reward threshold
            reward_pattern: compiled regex for matching reward amounts
            filter_max: maximum reward threshold (default 100.0)

        Returns:
            tuple: (rewards list, accept_btns list, refresh_btn)
        """
        rewards = []
        accept_btns = []
        refresh_btn = None

        for t in full_texts:
            name = t.name.strip()
            if ("刷新" in name or "秒后可刷新" in name) and t.y > self.height * 0.8:
                refresh_btn = t
            elif "接取运送委托" in name:
                accept_btns.append(t)
            else:
                match = reward_pattern.search(name)
                if match:
                    try:
                        val = float(match.group(1))
                        if val >= filter_min and val <= filter_max:
                            rewards.append((t, val))
                        elif val > filter_max:
                            self.log_debug(f"reward amount too large ({val}), filtered")
                    except:
                        pass

        return rewards, accept_btns, refresh_btn

    def _detect_ticket_type_with_ceiling(self, reward_obj, ticket_types: list, y_ceiling: float):
        """Detect ticket type by searching for icon above reward text, with ceiling constraint.

        Args:
            reward_obj: OCRItem with the reward amount
            ticket_types: list of feature names to search for
            y_ceiling: Y coordinate ceiling to prevent overlapping with previous row

        Returns:
            OCRItem or None: detected ticket feature object
        """
        search_hw_ratio = 3.6
        search_h_ratio = 2.4
        min_box_size = 110

        search_width = max(reward_obj.height * search_hw_ratio, min_box_size)
        search_height = max(reward_obj.height * search_h_ratio, min_box_size)

        x_offset_val = (reward_obj.width / 2) - (search_width / 2)
        target_y = reward_obj.y - search_height

        # ceiling constraint: prevent searching into previous row
        if target_y < y_ceiling:
            search_height = reward_obj.y - y_ceiling
            target_y = y_ceiling

        target_real_height = search_height + reward_obj.height * 0.5
        y_offset_val = target_y - reward_obj.y

        icon_search_box = reward_obj.copy(
            x_offset=x_offset_val,
            y_offset=y_offset_val,
            width_offset=search_width - reward_obj.width,
            height_offset=target_real_height - reward_obj.height
        )

        # boundary checks
        if icon_search_box.y < 0:
            icon_search_box.height += icon_search_box.y
            icon_search_box.y = 0
        if icon_search_box.x < 0:
            icon_search_box.width += icon_search_box.x
            icon_search_box.x = 0

        try:
            found_ticket = self.find_feature(ticket_types, box=icon_search_box)
            if found_ticket:
                return found_ticket[0] if isinstance(found_ticket, list) else found_ticket
        except Exception as e:
            self.log_debug(f"icon search box too small (possibly clipped), skipping: {e}")
            return None

        return None

    def _check_daily_commission_count(self) -> bool:
        """Check if today's accepted commission count is 3 (limit reached).

        Uses OCR to detect the number at box (0.80, 0.90, 0.83, 0.95).
        The red number shows today's accepted commission count (e.g., "3/3").

        Returns:
            bool: True if count is 3 (limit reached), False otherwise
        """
        try:
            self.log_info("checking daily commission count...")
            box = self.box_of_screen(0.80, 0.90, 0.83, 0.95)

            # Try OCR with red color filter first
            ocr_results = self.ocr(
                box=box,
                frame_processor=self.make_hsv_isolator(hR.RED_TEXT),
            )

            # If red filter didn't work, try without filter as fallback
            if not ocr_results:
                self.log_debug("no red number found with color filter, trying without filter...")
                ocr_results = self.ocr(box=box)

            if not ocr_results:
                self.log_debug("no OCR results found in commission count box")
                return False

            self.log_debug(f"OCR results in commission count box: {[t.name for t in ocr_results]}")

            # Extract the count number - look for any digit in results
            for text_obj in ocr_results:
                text = text_obj.name.strip()
                self.log_debug(f"checking OCR text: '{text}'")
                # Try to parse as integer, handling both "3" and "3/3" format
                for char in text:
                    if char.isdigit():
                        count = int(char)
                        self.log_info(f"daily commission count: {count}/3")
                        if count >= 3:
                            self.log_info("commission limit reached (3/3)")
                            return True
                        return False

            self.log_debug("could not find any digit in commission count box OCR results")
            return False
        except Exception as e:
            self.log_error(f"error checking commission count: {e}")
            return False

    def _accept_commission_order(self, area=None):
        """Open commission panel and accept a matching commission using TakeDeliveryTask approach.

        Args:
            area: Target area (AREA_WULING or AREA_VALLEY), defaults to AREA_WULING

        Returns:
            bool: True if order accepted successfully, None if limit reached
        """
        if area is None:
            area = AREA_WULING

        # Get commission filter config for the area
        if area not in COMMISSION_CONFIG:
            self.log_error(f"unknown area: {area}")
            return False

        area_config = COMMISSION_CONFIG[area]
        ticket_types = area_config["ticket_types"]
        filter_min = area_config["filter_min"]
        filter_max = area_config["filter_max"]

        self.ensure_main(time_out=120)
        self.log_info(f"opening commission panel for {area}")
        self.to_model_area(area, "仓储节点")
        delivery_box = self.wait_ocr(match="运送委托列表", time_out=5)
        if delivery_box:
            self.click(delivery_box[0], move_back=True, after_sleep=0.5)
        self.wait_ui_stable(refresh_interval=1)

        # check if first row has "查看任务" button (only check once at the beginning)
        self.log_info("checking first row for '查看任务'...")
        check_task_box = self.box_of_screen(0.79, 0.29, 0.97, 0.34)
        check_task_results = self.wait_ocr(match="查看任务", box=check_task_box, time_out=3)
        if check_task_results:
            self.log_info("first row has '查看任务' - clicking to open task panel")
            self.click(check_task_results[0], after_sleep=2)

            # click "停止追踪" to close task tracking
            if not self.wait_click_ocr(match="停止追踪", box="bottom_right", time_out=5, after_sleep=1):
                self.log_warning("failed to find '停止追踪' button, skipping")
            else:
                # click "开始追踪" to return to main world
                if not self.wait_click_ocr(match="开始追踪", box="bottom_right", time_out=5, after_sleep=2):
                    self.log_warning("failed to find '开始追踪' button, may not be in main world")

            self.log_info("returned to main world via task panel")
            self.ensure_main(time_out=10)
            return True

        # After first row check, check daily commission count limit
        self.log_info("checking daily commission count...")
        if self._check_daily_commission_count():
            self.log_info("daily commission limit reached, aborting")
            self.ensure_main(time_out=10)
            return None  # Return None to indicate limit reached, not failure

        # no "查看任务" in first row, scroll down and start accepting
        self.log_info("first row clean, scrolling down to find commissions")
        cx = int(self.width * 0.5)
        cy = int(self.height * 0.5)
        for _ in range(6):
            self.scroll(cx, cy, -8)
            self.sleep(0.2)
        self.wait_ui_stable(refresh_interval=1)

        reward_regex = r"(\d+\.?\d*)万"
        reward_pattern = re.compile(reward_regex, re.I)

        scroll_step = 0
        scroll_direction = -1
        refresh_not_found_count = 0

        while True:
            if not self.enabled:
                break

            try:
                full_texts = self.ocr(box=self.box_of_screen(0.05, 0.15, 0.95, 0.95))
                rewards, accept_btns, refresh_btn = self._process_ocr_results(
                    full_texts, filter_min, reward_pattern, filter_max
                )

                if refresh_btn:
                    self.last_refresh_box = refresh_btn
                    refresh_not_found_count = 0

                # sort rewards by Y coordinate (top to bottom)
                rewards.sort(key=lambda x: x[0].y)

                target_btn = None
                matched_msg = ""

                # initialize ceiling for first row
                current_ceiling = self.height * 0.15

                # iterate through rewards in visual order
                for reward_obj, val in rewards:
                    safe_ceiling = current_ceiling + 5

                    # match accept button by Y coordinate proximity
                    r_cy = reward_obj.y + reward_obj.height / 2
                    my_btn = None
                    for btn in accept_btns:
                        if abs(r_cy - (btn.y + btn.height / 2)) < btn.height * 0.8:
                            my_btn = btn
                            break

                    # update ceiling for next row
                    current_ceiling = reward_obj.y + reward_obj.height

                    if not my_btn:
                        continue

                    # detect ticket type with ceiling constraint
                    ticket_result = self._detect_ticket_type_with_ceiling(
                        reward_obj, ticket_types, safe_ceiling
                    )

                    if ticket_result and ticket_result.name == "ticket_wuling":
                        target_btn = my_btn
                        matched_msg = f"amount={val}万, type={ticket_result.name}"
                        self.log_info(f"matched: {matched_msg}")
                        break
                    else:
                        self.log_debug(f"amount matches ({val}万) but no ticket icon found")

                # execute accept if matched
                if target_btn:
                    self.log_info(f"accepting commission: {matched_msg}")
                    self.click(target_btn, after_sleep=1)

                    # Wait for "点击屏幕继续" with longer timeout (single click, no retry)
                    delivery_text = self.wait_ocr(
                        match="点击屏幕继续", time_out=5
                    )
                    if delivery_text:
                        self.log_info("accept succeeded, clicking to continue")
                        self.click_relative(0.5, 0.5, after_sleep=2)
                        self.ensure_main(time_out=10)
                        return True

                    # Check if already back to main world (clicked through by game)
                    if self.is_main():
                        self.log_info("accept succeeded (already in main world)")
                        return True

                    self.log_info("accept failed (possibly taken), waiting 4s before retry")
                    self.sleep(4)

                else:
                    self.log_info("no matching commission found")

                    # refresh logic (same as TakeDeliveryTask)
                    if scroll_step < 1:
                        scroll_step += 1
                        direction_str = "down" if scroll_direction == -1 else "up"
                        self.log_info(f"scroll step {scroll_step}/1 {direction_str}...")

                        self.scroll(cx, cy, scroll_direction * 3)
                        self.sleep(1.0)
                        continue

                    self.log_info("finished scanning current list, preparing refresh")

                    if hasattr(self, 'last_refresh_box') and self.last_refresh_box:
                        refresh_not_found_count = 0
                        last_click = getattr(self, 'last_refresh_time', 0)
                        elapsed = time.time() - last_click

                        if elapsed < 5.6:
                            self.log_debug(f"refresh CD ({elapsed:.1f}/5.6s), waiting...")
                            self.sleep(5.6 - elapsed)

                        self.log_info(f"executing refresh")
                        self.click(self.last_refresh_box, move_back=True)
                        self.last_refresh_time = time.time()

                        scroll_direction *= -1
                        scroll_step = 0

                        self.sleep(1.0)
                    else:
                        refresh_not_found_count += 1
                        self.log_info(
                            f"refresh button not located yet ({refresh_not_found_count}/10)"
                        )

                        if refresh_not_found_count >= 10:
                            self.log_info(
                                "unable to locate refresh for 10 iterations, aborting"
                            )
                            return False

                        self.log_info("waiting 1s before retry...")
                        self.sleep(1.0)
                        continue

            except Exception as e:
                self.log_error(f"commission accept error: {e}")
                if "SetCursorPos" in str(e) or "拒绝访问" in str(e):
                    self.log_warning(
                        "permission error detected, try running as administrator"
                    )
                time.sleep(2)
                continue

        return False

    def _is_fragile_order(self, reward_obj) -> bool:
        """Check if the order is for fragile goods (易损 but not 不易损).

        Args:
            reward_obj: OCRItem with the reward amount

        Returns:
            bool: True if fragile goods order
        """
        # scan nearby area for fragile markers
        search_box = reward_obj.copy(
            y_offset=reward_obj.height,
            height_offset=reward_obj.height * 2
        )
        try:
            results = self.ocr(match=re.compile("易损|不易损"), box=search_box)
            if not results:
                return False

            for result in results:
                name = result.name.strip()
                if "易损" in name and "不易损" not in name:
                    return True
            return False
        except:
            return False

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

            # Ensure we're back in main screen before opening map
            self.ensure_main(time_out=2)

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
        """Execute a single delivery cycle with retry logic.

        Wraps _do_single_delivery with up to 3 retry attempts.

        Args:
            order_type: ORDER_COMMISSION or ORDER_LOCAL
            area: area name, required for ORDER_LOCAL

        Returns:
            bool | None: True if completed, False if failed, None if no local orders
        """
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                result = self._do_single_delivery(order_type, area=area)
                if result is not None:  # True or False, not None (no orders)
                    return result
                else:
                    return None  # no orders available
            except Exception as e:
                self.log_error(f"delivery attempt {attempt}/{max_retries} failed: {e}")
                if attempt < max_retries:
                    self.log_info(f"retrying delivery (attempt {attempt + 1}/{max_retries})")
                    self.ensure_main(time_out=5)
                else:
                    self.log_error(f"all {max_retries} delivery attempts failed")
                    return False
        return False

    def _do_single_delivery(self, order_type, area=None):
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
            result = self._accept_commission_order(area=area)
            if result is None:
                return None  # daily limit reached (3/3 commissions)
            elif not result:
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

        # Determine which areas to process based on filter
        if area_filter == AREA_ALL:
            areas = [AREA_WULING, AREA_VALLEY]
        else:
            areas = [area_filter]

        if order_type == ORDER_LOCAL:
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
            # Ensure back to main world after finishing all local deliveries
            self.ensure_main()
            return True
        else:
            # Loop accepting commission orders until daily limit reached
            # Note: For commissions, we cycle through areas unless a specific area is selected
            current_area_idx = 0
            while True:
                area = areas[current_area_idx % len(areas)]
                result = self._run_single_delivery(ORDER_COMMISSION, area=area)
                if result is None:
                    # Limit reached (3/3 commissions today)
                    self.log_info("daily commission limit reached, stopping loop")
                    return True
                if not result:
                    # Error during delivery, try next area
                    current_area_idx += 1
                    if current_area_idx >= len(areas):
                        # Tried all areas, all failed
                        return False
                else:
                    # Success, continue with same area or move to next
                    # Keep trying same area as long as we keep getting commissions
                    pass

    def run(self):
        return self.execute()
