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


class Globals(QObject):

    def __init__(self, exit_event):
        super().__init__()

