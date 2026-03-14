from src.tasks.BaseEfTask import BaseEfTask


class MapMixin(BaseEfTask):
    def task_to_transfer_point(self,test_target_box=None):
        """传送到运输委托的出发传送点

        Returns:
            bool: 成功返回True，失败返回False
        """
        if test_target_box is None:
            test_target_box=self.box.top
        self.ensure_main()
        self.send_key("j", after_sleep=2)

        result = self.find_feature(
            feature_name="one_task_to_map", threshold=0.8, box=self.box.bottom_right
        )
        if not result:
            return False
        self.click(result, after_sleep=2)

        if not self.wait_click_ocr(
                match="标记显示管理", box=self.box.bottom_left, time_out=10, log=True, after_sleep=2
        ):
            return False

        if not self.wait_click_ocr(
                match="清空选中", box=self.box.bottom_left, time_out=10, log=True, after_sleep=2
        ):
            return False

        self.back(after_sleep=2)
        result = None
        for _ in range(8):
            result = self.find_feature(feature_name="transfer_point", box=test_target_box,
                                       threshold=0.8)
            if result:
                break
            self.next_frame()
            self.scroll_relative(0.5, 0.5, -5)
        if not result:
            return False
        self.click(result, after_sleep=2)

        result = self.wait_ocr(match="传送", box=self.box.bottom_right, time_out=10, log=True)
        if not result:
            return False

        self.click(result, after_sleep=2)
        return True
