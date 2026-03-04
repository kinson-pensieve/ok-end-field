from src.tasks.BaseEfTask import BaseEfTask
from src.data.FeatureList import FeatureList as fL
import re

class Test(BaseEfTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "测试"

    def test_ocr(self):
        box1 = self.box_of_screen(1749 / 1920, 107 / 1080, 1789 / 1920, 134 / 1080)
        box2 = self.box_of_screen(
            (1749 + (1832 - 1750)) / 1920,
            107 / 1080,
            (1789 + (1832 - 1750)) / 1920,
            134 / 1080,
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

    def run(self):
        self.log_info(str(self.get_framework_task_instances()))