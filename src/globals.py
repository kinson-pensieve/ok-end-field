from PySide6.QtCore import QObject

from ok import Logger
from ok.util.config import Config

logger = Logger.get_logger(__name__)


# 给 Config 注入 add_listener 功能
def _config_add_listener(self, key, callback):
    """监听指定 key 的值变化，变化时调用 callback(new_value)"""
    if not hasattr(self, '_listeners'):
        self._listeners = {}
    self._listeners.setdefault(key, []).append(callback)


_original_setitem = Config.__setitem__


def _config_setitem_with_listener(self, key, value):
    old_value = self.get(key)
    _original_setitem(self, key, value)
    new_value = self.get(key)
    if old_value != new_value and hasattr(self, '_listeners') and key in self._listeners:
        for callback in self._listeners[key]:
            try:
                callback(value)
            except Exception as e:
                logger.error(f'Config listener error for key "{key}": {e}')


Config.add_listener = _config_add_listener
Config.__setitem__ = _config_setitem_with_listener

# 让框架的 config_widget 支持 custom_widget 类型（ConfigCard 也会调用，不能只在 HomeTab 里拦截）
import ok.gui.tasks.ConfigItemFactory as _factory
_original_config_widget = _factory.config_widget


def _patched_config_widget(config_type, config_desc, config, key, value, task):
    the_type = config_type.get(key) if config_type is not None else None
    if the_type and the_type.get('type') == 'custom_widget':
        factory = the_type.get('widget_factory')
        if factory:
            return factory()
        from PySide6.QtWidgets import QWidget
        return QWidget()
    return _original_config_widget(config_type, config_desc, config, key, value, task)


_factory.config_widget = _patched_config_widget


class Globals(QObject):

    def __init__(self, exit_event):
        super().__init__()

