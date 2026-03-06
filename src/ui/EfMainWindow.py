import threading

import pyappify
from PySide6.QtCore import QCoreApplication, QEvent, QSize, Qt
from PySide6.QtGui import QScreen
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QApplication
from qfluentwidgets import MSFluentWindow, FluentIcon, NavigationItemPosition, MessageBox, InfoBar, InfoBarPosition

from ok.gui.Communicate import communicate
from ok.gui.util.Alert import alert_error
from ok.gui.widget.StartLoadingDialog import StartLoadingDialog
from ok.util.GlobalConfig import basic_options
from ok.util.config import Config
from ok.util.logger import Logger
from ok.util.process import restart_as_admin, parse_arguments_to_map

logger = Logger.get_logger(__name__)


class EfMainWindow(MSFluentWindow):
    """ok-end-field 自定义主窗口，用 HomeTab 替代默认的 Capture/Tasks/Triggers 页面。"""

    def __init__(self, app, config, ok_config, icon, title, version, debug=False, about=None, exit_event=None,
                 global_config=None, executor=None, handler=None):
        super().__init__()
        logger.info('EfMainWindow __init__')
        self.app = app
        self.executor = executor
        self.handler = handler
        self.ok_config = ok_config
        self.basic_global_config = global_config.get_config(basic_options)
        self.main_window_config = Config('main_window', {'last_version': 'v0.0.0'})
        self.exit_event = exit_event
        self.onetime_tab = None
        self.trigger_tab = None
        self.version = version
        self.emulator_starting_dialog = None
        self.do_not_quit = False
        self.config = config
        self.shown = False

        # 设置自定义快捷键默认值
        start_key = config.get('start_key', 'F10')
        basic_options.default_config['Start/Stop'] = start_key

        communicate.restart_admin.connect(self.restart_admin)
        if config.get('show_update_copyright'):
            communicate.copyright.connect(self.show_update_copyright)

        # HomeTab 作为唯一首页
        from src.ui.HomeTab import HomeTab
        self.home_tab = HomeTab()
        self.home_tab.executor = executor
        self.addSubInterface(self.home_tab, self.home_tab.icon, self.home_tab.name)
        self.first_task_tab = self.home_tab

        if debug:
            from ok.gui.debug.DebugTab import DebugTab
            debug_tab = DebugTab(config, exit_event)
            self.addSubInterface(debug_tab, FluentIcon.DEVELOPER_TOOLS, self.tr('Debug'),
                                 position=NavigationItemPosition.BOTTOM)
            from ok.gui.debug.RunCodeTab import RunCodeTab
            run_code_tab = RunCodeTab(config, exit_event)
            self.addSubInterface(run_code_tab, FluentIcon.COMMAND_PROMPT, self.tr('Run Code'),
                                 position=NavigationItemPosition.BOTTOM)

        from ok.gui.about.AboutTab import AboutTab
        self.about_tab = AboutTab(config, self.app.updater)
        self.addSubInterface(self.about_tab, FluentIcon.QUESTION, self.tr('About'),
                             position=NavigationItemPosition.BOTTOM)

        from ok.gui.settings.SettingTab import SettingTab
        self.setting_tab = SettingTab()
        self.addSubInterface(self.setting_tab, FluentIcon.SETTING, self.tr('Settings'),
                             position=NavigationItemPosition.BOTTOM)

        dev = self.tr('Debug')
        profile = config.get('profile', "")
        self.setWindowTitle(f'{title} {version} {profile} {dev if debug else ""}')

        communicate.executor_paused.connect(self.executor_paused)
        communicate.tab.connect(self.navigate_tab)
        communicate.task_done.connect(self.activateWindow)
        communicate.must_update.connect(self.must_update)
        menu = QMenu()
        exit_action = menu.addAction(self.tr("Exit"))
        exit_action.triggered.connect(self.tray_quit)

        self.tray = QSystemTrayIcon(icon, parent=self)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.on_tray_icon_activated)
        self.tray.show()
        self.tray.setToolTip(title)

        communicate.capture_error.connect(self.capture_error)
        communicate.notification.connect(self.show_notification)
        communicate.config_validation.connect(self.config_validation)
        communicate.starting_emulator.connect(self.starting_emulator)
        communicate.global_config.connect(self.goto_global_config)

        logger.info('EfMainWindow __init__ done')

    # ---- 覆盖的方法 ----

    def navigate_tab(self, index):
        logger.debug(f'navigate_tab {index}')
        if index == "about" and self.about_tab is not None:
            self.switchTo(self.about_tab)
        elif index is not None:
            self.switchTo(self.home_tab)

    def executor_paused(self, paused):
        self.show_notification(
            self.tr("Start Success.") if not paused else self.tr("Pause Success."),
            tray=not paused
        )

    def showEvent(self, event):
        if event.type() == QEvent.Show and not self.shown:
            self.shown = True
            self.switchTo(self.home_tab)
            args = parse_arguments_to_map()
            pyappify.hide_pyappify()
            if update_pyappify := self.config.get("update_pyappify"):
                pyappify.upgrade(update_pyappify.get('to_version'), update_pyappify.get('sha256'),
                                 [update_pyappify.get('zip_url')], self.exit_event)
            logger.info(f"Window has fully displayed {args}")
            communicate.start_success.emit()
            if self.basic_global_config.get('Kill Launcher after Start'):
                logger.info(f'EfMainWindow showEvent Kill Launcher after Start')
                pyappify.kill_pyappify()
            if self.version != self.main_window_config.get('last_version'):
                self.main_window_config['last_version'] = self.version
                if not self.config.get('auth'):
                    logger.info('update success, show copyright')
                    self.handler.post(lambda: communicate.copyright.emit(), delay=1)
            if args.get('task') > 0:
                task_index = args.get('task') - 1
                logger.info(f'start with params {task_index} {args.get("exit")}')
                self.app.start_controller.start(args.get('task') - 1, exit_after=args.get('exit'))
            elif self.basic_global_config.get('Auto Start Game When App Starts'):
                self.app.start_controller.start()
        super().showEvent(event)

    # ---- 以下方法与父类 MainWindow 完全一致，直接复制 ----

    def restart_admin(self):
        w = MessageBox(QCoreApplication.translate("app", "Alert"),
                       QCoreApplication.translate("StartController",
                                                  "PC version requires admin privileges, Please restart this app with admin privileges!"),
                       self.window())
        if w.exec():
            logger.info('restart_admin Yes button is pressed')
            thread = threading.Thread(target=restart_as_admin)
            thread.start()
            self.app.quit()

    def on_tray_icon_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            logger.info('main window on_tray_icon_activated QSystemTrayIcon.ActivationReason.Trigger')
        elif reason == QSystemTrayIcon.ActivationReason.MiddleClick:
            logger.info('main window on_tray_icon_activated QSystemTrayIcon.ActivationReason.MiddleClick')
        elif reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            logger.info(
                f'main window on_tray_icon_activated QSystemTrayIcon.ActivationReason.DoubleClick self.isVisible():{self.isVisible()}')
            self.showNormal()
            self.raise_()
            self.activateWindow()

    def goto_global_config(self, key):
        self.switchTo(self.setting_tab)
        self.setting_tab.goto_config(key)

    def tray_quit(self):
        logger.info('main window tray_quit')
        self.app.quit()

    def must_update(self):
        logger.info('must_update show_window')
        title = self.tr('Update')
        content = QCoreApplication.translate('app', 'The current version {} must be updated').format(
            self.app.updater.starting_version)
        w = MessageBox(title, content, self.window())
        self.executor.pause()
        if w.exec():
            logger.info('Yes button is pressed')
            self.app.updater.run()
        else:
            logger.info('No button is pressed')
            self.app.quit()

    def show_update_copyright(self):
        title = self.tr('Info')
        content = self.tr(
            "This is a free software. If you purchased this anywhere, request a refund from the seller.")
        from qfluentwidgets import Dialog
        w = Dialog(title, content, self.window())
        w.cancelButton.setVisible(False)
        w.setContentCopyable(True)
        w.exec()
        self.switchTo(self.about_tab)

    def set_window_size(self, width, height, min_width, min_height):
        screen = QScreen.availableGeometry(self.screen())
        if (self.ok_config['window_width'] > 0 and self.ok_config['window_height'] > 0 and
                self.ok_config['window_y'] > 0 and self.ok_config['window_x'] > 0):
            x, y, width, height = (self.ok_config['window_x'], self.ok_config['window_y'],
                                   self.ok_config['window_width'], self.ok_config['window_height'])
            if self.ok_config['window_maximized']:
                self.setWindowState(Qt.WindowMaximized)
            else:
                self.setGeometry(x, y, width, height)
        else:
            x = int((screen.width() - width) / 2)
            y = int((screen.height() - height) / 2)
            self.setGeometry(x, y, width, height)
        self.setMinimumSize(QSize(min_width, min_height))

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Resize or event.type() == QEvent.Move:
            self.handler.post(self.update_ok_config, remove_existing=True, skip_if_running=True, delay=1)
        return super().eventFilter(obj, event)

    def update_ok_config(self):
        if self.isMaximized():
            self.ok_config['window_maximized'] = True
        else:
            self.ok_config['window_maximized'] = False
            geometry = self.geometry()
            self.ok_config['window_x'] = geometry.x()
            self.ok_config['window_y'] = geometry.y()
            self.ok_config['window_width'] = geometry.width()
            self.ok_config['window_height'] = geometry.height()
        logger.info(f'Window geometry updated in ok_config {self.ok_config}')

    def starting_emulator(self, done, error, seconds_left):
        if error:
            from ok.gui.start.StartTab import StartTab
            for i in range(self.stackedWidget.count()):
                widget = self.stackedWidget.widget(i)
                if isinstance(widget, StartTab):
                    self.switchTo(widget)
                    break
            alert_error(error, True)
        if done:
            if self.emulator_starting_dialog:
                self.emulator_starting_dialog.close()
        else:
            if self.emulator_starting_dialog is None:
                self.emulator_starting_dialog = StartLoadingDialog(seconds_left, self)
            else:
                self.emulator_starting_dialog.set_seconds_left(seconds_left)
            self.emulator_starting_dialog.show()

    def config_validation(self, message):
        title = self.tr('Error')
        InfoBar.error(
            title=title,
            content=message,
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=5000,
            parent=self.window()
        )
        self.tray.showMessage(title, message)

    def show_notification(self, message, title=None, error=False, tray=False, show_tab=None):
        from ok.gui.util.app import show_info_bar
        show_info_bar(self.window(), self.app.tr(message), self.app.tr(title), error)
        if tray:
            self.tray.showMessage(self.app.tr(title), self.app.tr(message),
                                  QSystemTrayIcon.Critical if error else QSystemTrayIcon.Information,
                                  5000)
            self.navigate_tab(show_tab)

    def capture_error(self):
        self.show_notification(self.tr('Please check whether the game window is selected correctly!'),
                               self.tr('Capture Error'), error=True)

    def closeEvent(self, event):
        if self.app.exit_event.is_set():
            logger.info("Window closed exit_event.is_set")
            event.accept()
            return
        else:
            logger.info(f"Window closed exit_event.is not set {self.do_not_quit}")
            to_tray = self.basic_global_config.get('Minimize Window to System Tray when Closing')
            if to_tray:
                event.ignore()
                self.hide()
                return
            if not self.do_not_quit:
                self.exit_event.set()
                self.executor.destroy()
            event.accept()
            if not self.do_not_quit:
                pyappify.kill_pyappify()
                QApplication.instance().exit()
