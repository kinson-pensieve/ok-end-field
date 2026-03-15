class Interactor:
    """目的地交互工具类，根据目的地类型执行对应交互操作

    用法:
        interactor = Interactor(self)  # self 为 BaseEfTask 实例
        interactor.execute("采集物", dest)
    """

    def __init__(self, task):
        """
        Args:
            task: BaseEfTask 实例，用于调用游戏交互方法
        """
        self.task = task
        self._handlers = {
            "采集物": self._noop,
            "矿物": self._noop,
            "资源回收站": self._recycle,
            "送货": self._deliver,
            "仓储节点": self._storage,
            "能量淤积点": self._energy,
        }

    def execute(self, dest_type, dest):
        """根据目的地类型执行对应交互

        Args:
            dest_type: str，目的地类型（采集物/矿物/资源回收站/送货/仓储节点/能量淤积点）
            dest: dict，完整的目的地配置
        """
        handler = self._handlers.get(dest_type)
        if handler:
            handler(dest)
        else:
            self.task.log_error(f"未知交互类型: {dest_type}")

    def _noop(self, dest):
        """采集物/矿物：到达即完成，无需额外交互"""
        pass

    def _recycle(self, dest):
        """资源回收站交互：OCR 检测"收取资源"后按 F 交互"""
        task = self.task
        task.log_info("执行资源回收站交互")
        if task.wait_ocr(match="收取资源", time_out=2):
            task.send_key("f", after_sleep=0.5)
            task.log_info("已收取资源")
        else:
            task.log_error("未检测到收取资源")

    def _storage(self, dest):
        """仓储节点交互：OCR 检测"取货"后按 F 交互"""
        task = self.task
        task.log_info("执行仓储节点交互")
        if task.wait_ocr(match="取货", time_out=2):
            task.send_key("f", after_sleep=0.5)
            task.log_info("已取货")
        else:
            task.log_error("未检测到取货")

    def _deliver(self, dest):
        """送货交互：区分 NPC 和资源回收站
        - 资源回收站：检测"交货" → 按 F → 直接返回大世界
        - NPC：按 F → 跳过对话 → 点确认 → 领取奖励 → 返回大世界
        """
        task = self.task
        name = dest.get("name", "")
        task.log_info(f"执行送货交互: {name}")

        # Check if this is a recycling station by detecting "交货" text
        delivery_text = task.wait_ocr(match="交货", time_out=2)
        if delivery_text:
            # Recycling station delivery
            task.log_info(f"检测到资源回收站送货，目标: {name}")
            task.press_key('f', after_sleep=1)
            task.sleep(3)
            # Click at (0.50, 0.80) to close the delivery UI and return to main world
            task.click(0.50, 0.80, after_sleep=1)
            task.sleep(1)
            task.click(0.50, 0.80, after_sleep=1)
            task.sleep(1)
            task.ensure_main()
            task.log_info(f"已完成资源回收站送货: {name}")
        else:
            # NPC delivery
            task.log_info(f"执行 NPC 送货，目标: {name}")
            task.press_key('f', after_sleep=2)
            if not task.find_feature(feature_name="reward_ok"):
                task.skip_dialog()
                task.wait_click_ocr(match="确认", settle_time=2, after_sleep=2)
            task.wait_pop_up(after_sleep=2)
            task.ensure_main()
            task.log_info(f"已完成 NPC 送货: {name}")

    def _energy(self, dest):
        """能量淤积点交互"""
        task = self.task
        task.log_info("执行能量淤积点交互")
        # TODO: 实现能量淤积点交互（检测并清除淤积点）
