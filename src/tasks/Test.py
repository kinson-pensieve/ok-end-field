from src.tasks.BaseEfTask import BaseEfTask
from src.interaction.Mouse import active_and_send_mouse_delta
import pyautogui
class Test(BaseEfTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "测试"
    def run(self):
        active_and_send_mouse_delta(self.hwnd.hwnd, dx=100, dy=100, activate=True, only_activate=True, delay=0.02, steps=3)
        self.sleep(5)
        for _ in range(12):
            pyautogui.scroll(500)  # 向上滚
        # count = 0
        # while True:
        #     if count >=30:
        #         break
        #     self.find_feature(
        #         feature_name="chat_icon",
        #         box=self.box_of_screen(
        #             1260 / 1920, 699 / 1080, (1260 + 41) / 1920, 699 + 273 / 1080
        #         ),
        #     )
        #     self.sleep(1)
        #     count += 1
