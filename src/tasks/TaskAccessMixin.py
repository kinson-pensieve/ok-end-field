from typing import Any
import logging


class TaskAccessMixin:
    """可访问基类：统一提供对框架任务实例的访问能力。
    
    当继承 BaseTask 时，可以通过框架提供的上下文直接访问已实例化的任务对象。
    """

    def get_framework_task_instances(self) -> list[Any]:
        """从 ok-script 框架中获取已实例化的一次性任务对象列表。
        
        优先通过 BaseTask 继承获得的上下文来访问框架的任务管理器。
        如果当前对象本身不是 BaseTask 的实例，则尝试从 __main__.ok 获取。
        """
        logger = getattr(self, 'logger', logging.getLogger(self.__class__.__name__))
        
        try:
            # 方式 1: 如果当前对象本身是 BaseTask，直接访问框架的任务列表
            # BaseTask 通过 app 或 handler 应该能访问到所有已实例化的任务
            if hasattr(self, 'app'):
                app = self.app
                logger.debug(f"✓ 找到 self.app: {app}")
                for attr_name in ('_onetime_tasks', 'onetime_tasks', 'onetime_task_instances'):
                    if hasattr(app, attr_name):
                        value = getattr(app, attr_name, None)
                        if isinstance(value, list) and len(value) > 0:
                            logger.info(f"✓ 从 self.app.{attr_name} 获取到 {len(value)} 个任务实例")
                            return value
            
            if hasattr(self, 'handler'):
                handler = self.handler
                logger.debug(f"✓ 找到 self.handler: {handler}")
                for attr_name in ('_onetime_tasks', 'onetime_tasks', '_task_instances'):
                    if hasattr(handler, attr_name):
                        value = getattr(handler, attr_name, None)
                        if isinstance(value, list) and len(value) > 0:
                            logger.info(f"✓ 从 self.handler.{attr_name} 获取到 {len(value)} 个任务实例")
                            return value
            
            # 方式 2: 从 __main__ 模块的 ok 对象直接获取
            import sys
            main_module = sys.modules.get('__main__')
            if main_module and hasattr(main_module, 'ok'):
                main_ok = getattr(main_module, 'ok')
                logger.debug(f"✓ 找到 __main__.ok: {main_ok}")
                
                # 检查所有可能的内部属性和方法
                logger.debug(f"  __main__.ok 的属性: {[a for a in dir(main_ok) if not a.startswith('_')][:30]}")
                
                # 尝试获取 onetime_tasks
                for attr_name in ('_onetime_tasks', 'onetime_tasks', 'onetime_task_instances'):
                    if hasattr(main_ok, attr_name):
                        value = getattr(main_ok, attr_name, None)
                        if isinstance(value, list) and len(value) > 0:
                            logger.info(f"✓ 从 __main__.ok.{attr_name} 获取到 {len(value)} 个任务实例")
                            return value
                
                # 尝试通过 handler 获取
                if hasattr(main_ok, 'handler'):
                    handler = main_ok.handler
                    logger.debug(f"  __main__.ok.handler: {handler}")
                    if handler:
                        logger.debug(f"    handler 的属性: {[a for a in dir(handler) if not a.startswith('_')][:30]}")
                        for attr_name in ('_onetime_tasks', 'onetime_tasks', '_task_instances'):
                            if hasattr(handler, attr_name):
                                value = getattr(handler, attr_name, None)
                                if isinstance(value, list) and len(value) > 0:
                                    logger.info(f"✓ 从 __main__.ok.handler.{attr_name} 获取到 {len(value)} 个任务实例")
                                    return value
                
                # 尝试通过 app 获取
                if hasattr(main_ok, 'app'):
                    app = main_ok.app
                    logger.debug(f"  __main__.ok.app: {app}")
                    if app:
                        logger.debug(f"    app 的属性: {[a for a in dir(app) if not a.startswith('_') and 'task' in a.lower()]}")
                        for attr_name in ('_onetime_tasks', 'onetime_tasks', '_task_instances', 'onetime_task_instances'):
                            if hasattr(app, attr_name):
                                value = getattr(app, attr_name, None)
                                if isinstance(value, list) and len(value) > 0:
                                    logger.info(f"✓ 从 __main__.ok.app.{attr_name} 获取到 {len(value)} 个任务实例")
                                    return value
                
                # 尝试通过容器的私有属性获取
                logger.debug("  尝试搜索所有与任务相关的属性...")
                for attr_name in dir(main_ok):
                    if 'task' in attr_name.lower():
                        value = getattr(main_ok, attr_name, None)
                        if isinstance(value, list) and len(value) > 0 and hasattr(value[0], 'name'):
                            logger.info(f"✓ 从 __main__.ok.{attr_name} 获取到 {len(value)} 个任务实例")
                            return value
            
            logger.warning("✗ 未找到框架中已实例化的任务对象")
            
        except Exception as e:
            logger = getattr(self, 'logger', logging.getLogger(self.__class__.__name__))
            logger.debug(f"✗ 访问框架任务实例异常: {e}")
        
        return []
