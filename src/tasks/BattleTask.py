from src.data.world_map import stages_list
from qfluentwidgets import FluentIcon
from src.tasks.BaseEfTask import BaseEfTask
from src.tasks.daily.battle_mixin import DailyBattleMixin
import re
class BattleTask(DailyBattleMixin,BaseEfTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "刷体力"
        self.description = "刷体力任务"
        self.stages_list = stages_list
        self.icon = FluentIcon.BRIGHTNESS
        self.default_config = {
            "体力本": "干员经验",
            "技能释放": "123",
            "启动技能点数": 2,
            "后台结束战斗通知": True,
            "无数字操作间隔": 6,
            "进入战斗后的初始等待时间": 3
        }
        self.config_type["体力本"] = {"type": "drop_down", "options": self.stages_list}

    def run(self):
        if self.battle():
            self.log_info("刷体力结束!", notify=self.config.get("后台结束战斗通知") and self.in_bg())
        else:
            self.log_info("未检测到刷体力正常结束,可能未进入战斗或战斗异常,请检查")
