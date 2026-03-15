from PySide6.QtWidgets import QMenu, QSystemTrayIcon
from qfluentwidgets import MSFluentWindow, FluentIcon, NavigationItemPosition

from ok.gui.Communicate import communicate
from ok.gui.MainWindow import MainWindow
from ok.gui.util.Alert import alert_error
from ok.gui.widget.StartLoadingDialog import StartLoadingDialog
from ok.util.GlobalConfig import basic_options
from ok.util.clazz import init_class_by_name
from ok.util.config import Config
from ok.util.logger import Logger

logger = Logger.get_logger(__name__)


class EfMainWindow(MainWindow):
    """ok-end-field 自定义主窗口，用 HomeTab 替代默认的 StartTab/OneTimeTaskTab/TriggerTaskTab。"""

    def __init__(self, app, config, ok_config, icon, title, version, debug=False, about=None, exit_event=None,
                 global_config=None, executor=None, handler=None):
        # 跳过 MainWindow.__init__ 的 tab 加载逻辑，直接调用 MSFluentWindow.__init__
        MSFluentWindow.__init__(self)
        logger.info('EfMainWindow __init__')

        # 属性初始化
        self.app = app
        self.executor = executor
        self.handler = handler
        self.ok_config = ok_config
        self.basic_global_config = global_config.get_config(basic_options)
        self.main_window_config = Config('main_window', {'last_version': 'v0.0.0'})
        self.exit_event = exit_event
        self.onetime_tab = None
        self.trigger_tab = None
        self.schedule_tab = None
        self.version = version
        self.emulator_starting_dialog = None
        self.do_not_quit = False
        self.config = config
        self.shown = False

        communicate.restart_admin.connect(self.restart_admin)
        if config.get('show_update_copyright'):
            communicate.copyright.connect(self.show_update_copyright)

        # HomeTab 作为首页
        from src.ui.HomeTab import HomeTab
        self.home_tab = HomeTab()
        self.home_tab.executor = executor
        self.addSubInterface(self.home_tab, self.home_tab.icon, self.home_tab.name)
        self.first_task_tab = self.home_tab

        # 动态加载 custom_tabs
        if custom_tabs := config.get('custom_tabs'):
            for tab in custom_tabs:
                tab_obj = init_class_by_name(tab[0], tab[1])
                tab_obj.executor = executor
                self.addSubInterface(tab_obj, tab_obj.icon, tab_obj.name, position=tab_obj.position)

        # 计划任务Tab
        any_support_schedule = any(task.support_schedule_task for task in executor.onetime_tasks)
        if any_support_schedule:
            from ok.gui.tasks.ScheduleTaskTab import ScheduleTaskTab
            self.schedule_tab = ScheduleTaskTab(config=self.config)
            self.addSubInterface(self.schedule_tab, FluentIcon.CALENDAR, self.tr('Schedule'))

        # debug tabs
        if debug:
            from ok.gui.debug.DebugTab import DebugTab
            debug_tab = DebugTab(config, exit_event)
            self.addSubInterface(debug_tab, FluentIcon.DEVELOPER_TOOLS, self.tr('Debug'),
                                 position=NavigationItemPosition.BOTTOM)
            from ok.gui.debug.RunCodeTab import RunCodeTab
            run_code_tab = RunCodeTab(config, exit_event)
            self.addSubInterface(run_code_tab, FluentIcon.COMMAND_PROMPT, self.tr('Run Code'),
                                 position=NavigationItemPosition.BOTTOM)

        # about & settings
        from ok.gui.about.AboutTab import AboutTab
        self.about_tab = AboutTab(config, self.app.updater)
        self.addSubInterface(self.about_tab, FluentIcon.QUESTION, self.tr('About'),
                             position=NavigationItemPosition.BOTTOM)

        from ok.gui.settings.SettingTab import SettingTab
        self.setting_tab = SettingTab()
        self.addSubInterface(self.setting_tab, FluentIcon.SETTING, self.tr('Settings'),
                             position=NavigationItemPosition.BOTTOM)

        # 窗口标题
        dev = self.tr('Debug')
        profile = config.get('profile', "")
        self.setWindowTitle(f'{title} {version} {profile} {dev if debug else ""}')

        # 信号连接
        communicate.executor_paused.connect(self.executor_paused)
        communicate.tab.connect(self.navigate_tab)
        communicate.task_done.connect(self.activateWindow)
        communicate.must_update.connect(self.must_update)
        communicate.capture_error.connect(self.capture_error)
        communicate.notification.connect(self.show_notification)
        communicate.config_validation.connect(self.config_validation)
        communicate.starting_emulator.connect(self.starting_emulator)
        communicate.global_config.connect(self.goto_global_config)

        # 系统托盘
        menu = QMenu()
        exit_action = menu.addAction(self.tr("Exit"))
        exit_action.triggered.connect(self.tray_quit)
        self.tray = QSystemTrayIcon(icon, parent=self)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.on_tray_icon_activated)
        self.tray.show()
        self.tray.setToolTip(title)

        logger.info('EfMainWindow __init__ done')

    # ---- 以下方法覆写 MainWindow 中行为不同的部分 ----

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

    def starting_emulator(self, done, error, seconds_left):
        if error:
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
