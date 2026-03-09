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
        """送货交互：OCR 检测目的地名称后按 F 交互"""
        task = self.task
        name = dest.get("name", "")
        task.log_info(f"执行送货交互: {name}")
        if task.wait_ocr(match=name, time_out=5):
            task.send_key("f", after_sleep=0.5)
            task.skip_dialog()
            task.log_info(f"已完成送货: {name}")
        else:
            task.log_error(f"未检测到送货目标: {name}")

    def _energy(self, dest):
        """能量淤积点交互"""
        task = self.task
        task.log_info("执行能量淤积点交互")
        # TODO: 实现能量淤积点交互（检测并清除淤积点）
