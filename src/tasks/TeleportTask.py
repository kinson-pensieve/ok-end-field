from qfluentwidgets import FluentIcon
from src.tasks.BaseNavTask import BaseNavTask
from src.navigation.Teleporter import Teleporter


class TeleportTask(BaseNavTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "传送"
        self.description = "传送到指定传送点"
        self.icon = FluentIcon.SYNC

        self.map_teleporter = Teleporter(self)

        sorted_points = sorted(
            self.map_teleporter.teleport_points,
            key=lambda p: (p.get("world", ""), p.get("region", ""), p.get("area") or "", p.get("name", ""))
        )

        display_names = []
        self.name_mapping = {}

        for point in sorted_points:
            world = point.get("world", "")
            area = point.get("area", "")
            region = point.get("region", "")
            name = point.get("name", "")

            # 对于帝江号(无region/area): "[帝江号]传送点名"
            # 对于塔卫二带area: "[area]传送点名"
            # 对于塔卫二无area: "[region]传送点名"
            if world == "帝江号":
                display_name = f"[帝江号]{name}"
            elif area:
                display_name = f"[{area}]{name}"
            elif region:
                display_name = f"[{region}]{name}"
            else:
                display_name = name

            display_names.append(display_name)
            self.name_mapping[display_name] = point

        self.default_config.update({
            "传送点": display_names[0] if display_names else "[区域]传送点",
        })

        self.config_type["传送点"] = {
            'type': "drop_down",
            'options': display_names
        }

    def run(self):
        selected_display_name = self.config.get("传送点")
        selected_point = self.name_mapping.get(selected_display_name)

        if not selected_point:
            self.log_error(f"未找到传送点: {selected_display_name}")
            return False

        return self.map_teleporter.teleport_to(selected_point['name'])
