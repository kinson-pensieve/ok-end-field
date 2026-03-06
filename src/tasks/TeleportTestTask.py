import random
from qfluentwidgets import FluentIcon
from src.tasks.BaseNavTask import BaseNavTask
from src.navigation.Teleporter import Teleporter


class TeleportTestTask(BaseNavTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "传送测试"
        self.description = "调试用:随机传送点循环测试"
        self.icon = FluentIcon.SYNC

        self.default_config.update({
            "测试次数": 100,
        })

        self.teleporter = Teleporter(self)

    def run(self):
        self.log_info("开始随机传送测试...")

        test_count = self.config.get("测试次数", 10)

        if not self.teleporter.teleport_points:
            self.log_error("传送点列表为空")
            return False

        self.log_info(f"共加载 {len(self.teleporter.teleport_points)} 个传送点")

        # 循环测试
        last_point_name = "起始位置"
        for i in range(test_count):
            # 随机选择一个传送点
            selected_point = random.choice(self.teleporter.teleport_points)
            point_name = selected_point.get("name", "未知")
            world = selected_point.get("world", "")
            region = selected_point.get("region", "")
            area = selected_point.get("area", "")

            location_info = f"{world}"
            if region:
                location_info += f" - {region}"
            if area:
                location_info += f" - {area}"

            self.log_info(f"【{i+1}/{test_count}】{last_point_name} → {point_name} ({location_info})")

            success = self.teleporter.teleport_to(point_name)

            if not success:
                self.log_error(f"传送失败: {point_name}")
                # 继续下一次测试
            else:
                self.log_info("等待传送完成...")
                max_wait = 60
                check_interval = 0.5
                elapsed_time = 0

                while elapsed_time < max_wait:
                    self.next_frame()
                    if self.in_world():
                        self.log_info(f"传送完成: {point_name}")
                        last_point_name = point_name
                        break
                    self.sleep(check_interval)
                    elapsed_time += check_interval
                else:
                    self.log_warning(f"等待传送完成超时 ({max_wait}秒)，继续下一次测试")

            # 等待一段时间再进行下一次传送
            if i < test_count - 1:
                self.sleep(1)

        self.log_info(f"随机传送测试完成! 共测试 {test_count} 次", notify=True)
        return True
