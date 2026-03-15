from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPainter, QPen, QColor
from PySide6.QtWidgets import QWidget

from ok import og
from ok.gui.Communicate import communicate


class RecordOverlay(QWidget):
    """录制专用 OCR 识别框叠加层

    独立于 ok-script 的 debug/overlay 系统，仅在录制时显示。
    通过 show_overlay() / hide_overlay() 从任意线程安全调用。
    """

    _instance = None

    def __init__(self):
        super().__init__()
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowTransparentForInput
        )

        self._repaint_timer = QTimer(self)
        self._repaint_timer.timeout.connect(self.update)
        self._repaint_timer.start(500)

    def _update_position(self, visible, x, y, window_width, window_height, width, height, scaling):
        if visible:
            self.setGeometry(x / scaling, y / scaling, width / scaling, height / scaling)
        if visible and not self.isVisible():
            self.show()
        elif not visible and self.isVisible():
            self.hide()

    def paintEvent(self, event):
        if not self.isVisible() or not og.ok or not og.ok.screenshot:
            return
        painter = QPainter(self)
        painter.setBrush(Qt.NoBrush)
        pen = QPen()
        pen.setWidth(2)

        frame_ratio = self.width() / og.device_manager.width if og.device_manager.width > 0 else 1

        for key, value in og.ok.screenshot.ui_dict.items():
            boxes = value[0]
            pen.setColor(value[2])
            painter.setPen(pen)
            for box in boxes:
                bw = box.width * frame_ratio
                bh = box.height * frame_ratio
                bx = box.x * frame_ratio
                by = box.y * frame_ratio
                painter.drawRect(bx, by, bw, bh)
                text = f"{box.name or key}_{round(box.confidence * 100)}"
                text_x = bx
                text_y = by + bh + 12
                painter.save()
                painter.setPen(QColor("black"))
                painter.drawText(text_x + 0.5, text_y + 0.5, text)
                painter.setPen(value[2])
                painter.drawText(text_x, text_y, text)
                painter.restore()
        painter.end()

    @classmethod
    def show_overlay(cls):
        """线程安全：在 GUI 线程创建并显示 overlay"""
        QTimer.singleShot(0, cls._do_show)

    @classmethod
    def hide_overlay(cls):
        """线程安全：在 GUI 线程隐藏并销毁 overlay"""
        QTimer.singleShot(0, cls._do_hide)

    @classmethod
    def _do_show(cls):
        if cls._instance is None:
            cls._instance = RecordOverlay()
        communicate.window.connect(cls._instance._update_position)
        # 立即用当前窗口位置初始化，不等待下次窗口变化信号
        hw = og.device_manager.hwnd_window
        if hw and hw.visible:
            cls._instance._update_position(
                hw.visible, hw.x + hw.real_x_offset, hw.y + hw.real_y_offset,
                hw.window_width, hw.window_height,
                hw.width, hw.height, hw.scaling,
            )

    @classmethod
    def _do_hide(cls):
        if cls._instance:
            try:
                communicate.window.disconnect(cls._instance._update_position)
            except RuntimeError:
                pass
            cls._instance._repaint_timer.stop()
            cls._instance.close()
            cls._instance.deleteLater()
            cls._instance = None
