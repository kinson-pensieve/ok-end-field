import json
import os
import re
import random
from difflib import get_close_matches
import win32gui
import win32api


class Teleporter:
    """传送工具类，封装地图传送相关操作，可被任意 Task 调用

    用法:
        helper = TeleportHelper(self)  # self 为任意 BaseEfTask 实例
        helper.teleport_to("传送点名称")
    """

    def __init__(self, task):
        """
        Args:
            task: BaseEfTask 实例，用于调用 OCR、点击、日志等方法
        """
        self.task = task
        self.teleport_points = self._load_teleport_points()
        self.area_coordinates = self._load_area_coordinates()

    @staticmethod
    def _load_teleport_points():
        json_path = os.path.join("assets", "teleport_points.json")
        if os.path.exists(json_path):
            with open(json_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return []

    @staticmethod
    def _load_area_coordinates():
        json_path = os.path.join("assets", "area_coordinates.json")
        if os.path.exists(json_path):
            with open(json_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    def _ensure_in_world(self, max_attempts=5) -> bool:
        """确保回到游戏世界，通过反复按 esc 关闭所有可能的 UI 层级

        Args:
            max_attempts: 最大尝试次数

        Returns:
            bool: 是否成功回到世界
        """
        task = self.task
        for i in range(max_attempts):
            task.next_frame()
            if task.in_world() or task.in_combat_world():
                task.log_debug(f"已在游戏世界中 (第{i + 1}次检测)")
                return True
            task.log_debug(f"未在游戏世界中，按 esc 尝试关闭 UI (第{i + 1}次)")
            task.send_key("esc", after_sleep=0.5)
        task.log_error("多次尝试后仍未回到游戏世界")
        return False

    def teleport_to(self, name: str, retry=3, stop_event=None) -> bool:
        """传送到指定传送点

        Args:
            name: 传送点名称（teleport_points.json 中的 name 字段）
            retry: 最大重试次数
            stop_event: 可选的 threading.Event，触发时中断传送

        Returns:
            bool: 传送是否成功
        """
        task = self.task

        selected_point = None
        for point in self.teleport_points:
            if point.get('name') == name:
                selected_point = point
                break

        if not selected_point:
            task.log_error(f"未找到传送点: {name}")
            return False

        for attempt in range(retry):
            if stop_event and stop_event.is_set():
                return False
            if attempt > 0:
                task.log_info(f"第 {attempt + 1}/{retry} 次重试传送到: {selected_point['name']}")
            else:
                task.log_info(f"开始传送到: {selected_point['name']}")

            # 确保从游戏世界开始，避免残留 UI 导致按 M 反而关闭地图
            if not self._ensure_in_world():
                continue

            if self._do_teleport(selected_point):
                task.log_info("传送完成!")
                return True

        task.log_error(f"传送到 {name} 失败，已重试 {retry} 次")
        return False

    def _do_teleport(self, selected_point) -> bool:
        """执行一次完整的传送流程"""
        task = self.task

        # 提取目标世界、区域和地区
        target_world = selected_point.get('world', '塔卫二')  # 向后兼容
        target_region = selected_point.get('region', '')
        target_area = selected_point.get('area', '')

        task.log_debug(f"目标世界: {target_world}, 区域: {target_region}, 地区: {target_area}")
        task.log_debug(f"方位: {selected_point['direction']}, 坐标: {selected_point['coordinates']}")

        task.send_key("m", after_sleep=1)

        task.log_debug("等待地图打开...")
        task.sleep(1)

        # 获取当前位置(带世界感知)
        current_world, current_region, current_area = self._get_current_map_location()

        if current_world:
            if current_area:
                task.log_info(f"当前位置 - 世界: {current_world}, 区域: {current_region}, 地区: {current_area}")
            elif current_region:
                task.log_info(f"当前位置 - 世界: {current_world}, 区域: {current_region}")
            else:
                task.log_info(f"当前位置 - 世界: {current_world}")
        else:
            task.log_info("无法识别当前位置")

        # 切换地图世界/区域/地区
        if not self._switch_map_region_area(current_world, current_region, current_area,
                                            target_world, target_region, target_area):
            return False

        # 执行传送操作
        if not self._execute_teleport(selected_point):
            return False

        return True

    def _click_region_overview(self) -> bool:
        """点击右下角的"地区总览"按钮"""
        task = self.task
        task.log_debug("点击地区总览按钮...")
        overview_button = task.wait_click_ocr(
            0.83, 0.89, 0.91, 0.94,
            match="地区总览",
            time_out=3,
            after_sleep=1
        )
        if not overview_button:
            task.log_error("未找到地区总览按钮")
            task.send_key("esc", after_sleep=0.5)
            return False
        return True

    def _select_region_from_list(self, target_region: str) -> bool:
        """从区域列表中选择目标区域(右下角)"""
        task = self.task
        task.log_debug(f"在右下角选择区域: {target_region}...")
        region_select = task.wait_click_ocr(
            match=target_region,
            box="bottom_right",
            time_out=3,
            after_sleep=2
        )
        if not region_select:
            task.log_error(f"未找到区域 {target_region}")
            task.send_key("esc", after_sleep=0.5)
            return False
        return True

    def _find_and_click_top_right_region_button(self) -> bool:
        """查找并点击右上角的区域按钮(当在帝江号时)"""
        task = self.task
        task.log_debug("查找右上角区域按钮...")
        top_right_ocr = task.ocr(0.89, 0.07, 0.99, 0.17)

        if not top_right_ocr:
            task.log_error("未能识别右上角区域")
            task.send_key("esc", after_sleep=0.5)
            return False

        task.log_debug(f"右上角OCR检测到 {len(top_right_ocr)} 个文字:")
        for item in top_right_ocr:
            text = str(getattr(item, "name", "")).strip()
            task.log_debug(f"  - {text}")

        # 查找区域名称
        found_region_button = None
        for item in top_right_ocr:
            region_name = str(getattr(item, "name", "")).strip()
            if "武陵" in region_name or "四号谷地" in region_name:
                task.log_debug(f"找到右上角区域按钮: {region_name}")
                found_region_button = item
                break

        if not found_region_button:
            task.log_error("右上角未找到武陵或四号谷地按钮")
            task.send_key("esc", after_sleep=0.5)
            return False

        task.log_debug("点击区域按钮...")
        task.click(found_region_button, after_sleep=1)
        return True

    def _click_top_right_dijianghao(self) -> bool:
        """点击右上角的帝江号按钮(当在塔卫二时)"""
        task = self.task
        task.log_debug("查找右上角帝江号按钮...")
        top_right_ocr = task.ocr(0.90, 0.13, 0.97, 0.16)

        if not top_right_ocr:
            task.log_error("未能识别右上角区域")
            task.send_key("esc", after_sleep=0.5)
            return False

        task.log_debug(f"右上角OCR检测到 {len(top_right_ocr)} 个文字:")
        for item in top_right_ocr:
            text = str(getattr(item, "name", "")).strip()
            task.log_debug(f"  - {text}")

        # 查找帝江号
        found_button = None
        for item in top_right_ocr:
            text = str(getattr(item, "name", "")).strip()
            if "帝江号" in text or "帝江" in text:
                task.log_debug(f"找到右上角帝江号按钮: {text}")
                found_button = item
                break

        if not found_button:
            task.log_error("右上角未找到帝江号按钮")
            task.send_key("esc", after_sleep=0.5)
            return False

        task.log_debug("点击帝江号按钮...")
        task.click(found_button, after_sleep=2)
        return True

    def _switch_map_region_area(self, current_world, current_region, current_area,
                                target_world, target_region, target_area):
        """切换地图世界、区域和地区"""
        task = self.task

        # Scenario 1: Same world, same region, same area - just zoom
        if (current_world == target_world and
            current_region == target_region and
            current_area == target_area):
            task.log_debug("Scenario 1: 当前已在目标位置，缩小地图...")
            cx, cy = int(task.width / 2), int(task.height / 2)
            task.scroll(cx, cy, -50)
            task.sleep(0.5)
            return True

        # Scenario 1.5: 帝江号内部传送（同world，无region/area）
        if (current_world == "帝江号" and target_world == "帝江号" and
            not current_region and not target_region and
            not current_area and not target_area):
            task.log_debug("Scenario 1.5: 帝江号内部传送，缩小地图...")
            cx, cy = int(task.width / 2), int(task.height / 2)
            task.scroll(cx, cy, -50)
            task.sleep(0.5)
            return True

        # Scenario 2: Same world, same region, different area
        if (current_world == target_world and
            current_region == target_region and
            current_area != target_area and
            target_area):
            task.log_debug(f"Scenario 2: 同世界同区域，切换地区到 {target_area}")
            if not self._click_region_overview():
                return False
            return self._switch_to_area(target_world, target_region, target_area)

        # Scenario 3: From 帝江号 to other world
        if current_world == "帝江号" and target_world != "帝江号":
            task.log_debug(f"Scenario 3: 从帝江号切换到 {target_world}")
            if not self._find_and_click_top_right_region_button():
                return False
            if not self._select_region_from_list(target_region):
                return False
            if target_area:
                return self._switch_to_area(target_world, target_region, target_area)
            return True

        # Scenario 4: From other world to 帝江号
        if current_world != "帝江号" and target_world == "帝江号":
            task.log_debug(f"Scenario 4: 从 {current_world} 切换到帝江号")
            return self._click_top_right_dijianghao()

        # Scenario 5: Same world, different region
        if current_world == target_world and current_region != target_region:
            task.log_debug(f"Scenario 5: 同世界，切换区域到 {target_region}")
            if not self._click_region_overview():
                return False
            if not self._select_region_from_list(target_region):
                return False
            if target_area:
                return self._switch_to_area(target_world, target_region, target_area)
            return True

        # Fallback: unsupported world transition
        task.log_error(f"不支持的世界切换: {current_world} → {target_world}")
        task.send_key("esc", after_sleep=0.5)
        return False

    def _switch_to_area(self, target_world, target_region, target_area):
        """切换到指定地区"""
        task = self.task
        task.log_debug(f"点击地区: {target_area}...")

        # 使用世界感知的坐标查找
        area_coord = None
        if target_world in self.area_coordinates:
            if target_region in self.area_coordinates[target_world]:
                area_coord = self.area_coordinates[target_world][target_region].get(target_area, "")

        if not area_coord:
            task.log_error(f"未配置地区坐标: {target_world} - {target_region} - {target_area}")
            task.send_key("esc", after_sleep=0.5)
            return False

        task.log_debug(f"使用坐标点击地区: {area_coord}")
        self._click_coordinates(area_coord)
        task.sleep(1)
        return True

    def _execute_teleport(self, selected_point):
        """执行传送操作：拖拽、点击传送"""
        task = self.task
        direction = selected_point.get('direction', '')
        if direction:
            task.log_debug(f"拖拽地图到{direction}...")
            self._drag_to_direction(direction)
            task.sleep(0.5)

        coordinates = selected_point.get('coordinates', '')
        if coordinates:
            task.log_debug(f"点击坐标: {coordinates}")
            self._click_coordinates(coordinates)

        task.log_debug("查找协议传送点按钮...")
        protocol_teleport = task.wait_click_ocr(match="协议传送点", box="bottom_right", time_out=3, after_sleep=1)
        if protocol_teleport:
            task.log_debug("找到并点击了协议传送点")
        else:
            task.log_debug("未找到协议传送点，跳过")

        task.log_debug("点击传送按钮...")
        teleport_button = task.wait_click_ocr(match="传送", box="bottom_right", time_out=3, after_sleep=1)
        if not teleport_button:
            task.log_error("未找到传送按钮")
            task.send_key("esc", after_sleep=0.5)
            return False

        # Close map after teleportation
        task.send_key("esc", after_sleep=1)
        return True

    def _get_current_map_location(self):
        """获取当前地图位置(世界、区域和地区)，包含OCR识别、标准化和模糊匹配"""
        task = self.task

        # 构建已知的world、region和area列表，用于模糊匹配
        known_worlds = set()
        world_regions = {}  # world -> set of regions
        region_areas = {}   # (world, region) -> set of areas

        for point in self.teleport_points:
            world = point.get("world", "")
            region = point.get("region", "")
            area = point.get("area", "")

            if world:
                known_worlds.add(world)
                if world not in world_regions:
                    world_regions[world] = set()
                if region:
                    world_regions[world].add(region)
                    key = (world, region)
                    if key not in region_areas:
                        region_areas[key] = set()
                    if area:
                        region_areas[key].add(area)

        # 匹配格式: // world 或 // region / area (area部分可选)
        result = task.ocr(0.02, 0.02, 0.20, 0.15, match=re.compile(r"//\s*([^/]+)(?:\s*/\s*(.+))?"), name='address')
        if result and len(result) > 0:
            text = str(getattr(result[0], "name", "")).strip()
            task.log_debug(f"左上角OCR结果: {text}")

            pattern = r'//\s*([^/]+)(?:\s*/\s*(.+))?'
            match = re.search(pattern, text)
            if match:
                first_part = match.group(1).strip()
                second_part = match.group(2).strip() if match.group(2) else None

                # 判断first_part是world还是region
                # "帝江号"始终是world
                if "帝江号" in first_part:
                    world = "帝江号"
                    region = None
                    area = None
                    # 应用模糊匹配
                    if world not in known_worlds:
                        matches = get_close_matches(world, known_worlds, n=1, cutoff=0.6)
                        if matches:
                            fuzzy_world = matches[0]
                            task.log_debug(f"模糊匹配 world: {world} → {fuzzy_world}")
                            world = fuzzy_world
                else:
                    # first_part是region，从region推断world
                    region = first_part
                    area = second_part

                    # 模糊匹配region
                    all_regions = set()
                    for regions in world_regions.values():
                        all_regions.update(regions)

                    if region not in all_regions:
                        matches = get_close_matches(region, all_regions, n=1, cutoff=0.6)
                        if matches:
                            fuzzy_region = matches[0]
                            task.log_debug(f"模糊匹配 region: {region} → {fuzzy_region}")
                            region = fuzzy_region

                    # 从region推断world
                    world = None
                    for w, regions in world_regions.items():
                        if region in regions:
                            world = w
                            break

                    if not world:
                        world = "塔卫二"  # 默认回退

                    # 模糊匹配area
                    if area and (world, region) in region_areas:
                        if area not in region_areas[(world, region)]:
                            matches = get_close_matches(area, region_areas[(world, region)], n=1, cutoff=0.6)
                            if matches:
                                fuzzy_area = matches[0]
                                task.log_debug(f"模糊匹配 area: {area} → {fuzzy_area}")
                                area = fuzzy_area

                if area:
                    task.log_debug(f"解析成功 - World: {world}, Region: {region}, Area: {area}")
                elif region:
                    task.log_debug(f"解析成功 - World: {world}, Region: {region} (无Area)")
                else:
                    task.log_debug(f"解析成功 - World: {world} (无Region/Area)")
                return world, region, area

        task.log_debug("无法识别当前地图位置")
        return None, None, None

    def _move_mouse_to(self, x, y):
        """只移动鼠标到指定位置，不点击"""
        task = self.task

        if isinstance(x, float) and 0 <= x <= 1:
            abs_x = int(x * task.width)
        else:
            abs_x = int(x)

        if isinstance(y, float) and 0 <= y <= 1:
            abs_y = int(y * task.height)
        else:
            abs_y = int(y)

        hwnd = task.hwnd.hwnd
        rect = win32gui.GetWindowRect(hwnd)
        window_x, window_y = rect[0], rect[1]

        screen_x = window_x + abs_x
        screen_y = window_y + abs_y

        win32api.SetCursorPos((screen_x, screen_y))

    def _drag_to_direction(self, direction, drag_count=3):
        """拖拽地图到指定方向"""
        task = self.task

        center_x = int(task.width / 2)
        center_y = int(task.height / 2)

        direction_map = {
            "right": (-task.width // 2, 0),
            "left": (task.width // 2, 0),
            "bottom": (0, -task.height // 2),
            "top": (0, task.height // 2),
            "bottom_right": (-task.width // 2, -task.height // 2),
            "top_right": (-task.width // 2, task.height // 2),
            "bottom_left": (task.width // 2, -task.height // 2),
            "top_left": (task.width // 2, task.height // 2),
        }

        # center类型特殊处理：先执行bottom_right，再往中心回拖一半屏幕距离
        if direction == "center":
            task.log_debug("执行center拖拽：先bottom_right再回拖...")

            self._drag_to_direction("bottom_right")
            task.sleep(0.15)

            self._move_mouse_to(center_x, center_y)
            task.sleep(0.05)
            task.drag_mouse(int(task.width / 2), int(task.height / 2))

            self._move_mouse_to(center_x, center_y)
            return

        offset = direction_map.get(direction)
        if offset:
            for i in range(drag_count):
                if drag_count > 1:
                    task.log_debug(f"拖拽第 {i+1}/{drag_count} 次...")

                self._move_mouse_to(
                    center_x + random.randint(-50, 50),
                    center_y + random.randint(-50, 50))
                task.sleep(0.05)

                task.drag_mouse(offset[0], offset[1])

                if i < drag_count - 1:
                    task.sleep(0.15)

            self._move_mouse_to(center_x, center_y)
        else:
            task.log_error(f"未知方位: {direction}")

    def _click_coordinates(self, coordinates):
        try:
            x, y = map(float, coordinates.split(","))
            self.task.click(x, y, after_sleep=0.5)
        except Exception as e:
            self.task.log_error(f"坐标格式错误: {coordinates}, 错误: {e}")
