from PySide6.QtCore import QEvent, QThread, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    FluentIcon,
    PrimaryPushButton,
    PushButton,
    ComboBox,
    CheckBox,
    isDarkTheme,
)

from ok import Config
from ok.gui.widget.CustomTab import CustomTab


class TaskWorker(QThread):
    """后台任务执行工作线程"""
    finished = Signal(bool, str)  # (success, message)
    
    def __init__(self, command, logger=None):
        super().__init__()
        self.command = command
        self.logger = logger
    
    def run(self):
        """在后台线程中执行命令"""
        import subprocess
        try:
            result = subprocess.run(self.command, capture_output=True, text=True, timeout=30)
            success = result.returncode == 0
            message = result.stdout.strip() if success else (result.stderr.strip() or "未知错误")
            self.finished.emit(success, message)
        except subprocess.TimeoutExpired:
            self.finished.emit(False, "命令执行超时（30秒）")
        except Exception as e:
            self.finished.emit(False, f"执行异常: {str(e)}")


class TaskSchedulerTab(CustomTab):
    """任务计划管理页面
    
    从已实例化的任务对象中读取任务名称，配置执行时间和命令行参数。
    支持命令行参数: -t N（执行第N个任务）-e（执行完后退出）
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger.info(f'{self.__class__.__name__} 初始化')

        # 配置管理
        self.config = Config(self.__class__.__name__, {
            'selected_task_index': 0,
            'trigger_time': '09:00',
            'auto_exit': False,
            'trigger_type': '每天',  # 触发类型
            'repeat_interval': 1,  # 重复间隔
            'repeat_duration': 24,  # 重复持续时间（小时）
        })
        # 所有可选项本地化存储（用于渲染下拉）
        self.ui_options = Config('TaskSchedulerUiOptions', {
            'time_options': [f"{h:02d}:{m:02d}" for h in range(24) for m in range(0, 60, 5)],
            'trigger_types': ["每天", "每周", "每月"],
            'repeat_intervals': ["每次运行后", "每小时", "每2小时", "每4小时", "每8小时", "每12小时"],
            'timeout_options': ["1小时 (默认)", "2小时", "4小时", "6小时", "8小时", "12小时", "无限制"],
        })
        self.task_option_cache = Config('TaskSchedulerTaskOptions', {
            'task_names': [],
        })
        self.task_cache = Config('TaskScheduleCache', {
            'tasks': [],
            'last_sync': '',
        })
        # 初始化任务计划助手功能
        self._init_scheduler_helper()
        # 任务数据（延迟加载）
        self.onetime_tasks = []
        self.task_names = []
        self.tasks_loaded = False
        self.manage_task_items = []

        # 设置侧边栏图标
        self.icon = FluentIcon.CALENDAR

        # ========== 标题区域 ==========
        title = BodyLabel("任务计划管理")
        base_text_color = "#fff" if isDarkTheme() else "#000"
        title.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {base_text_color};")
        self.add_widget(title)

        description = BodyLabel("为游戏任务创建 Windows 计划任务，配置定时自动执行")
        self.add_widget(description)

        # 添加分隔线
        separator1 = QFrame()
        separator1.setFrameShape(QFrame.Shape.HLine)
        separator1.setStyleSheet("background-color: rgba(0, 0, 0, 0.1);")
        self.add_widget(separator1)

        # ========== 任务选择区域 ==========
        task_label = BodyLabel("选择任务:")
        task_label.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {base_text_color};")
        self.add_widget(task_label)

        self.task_combo = ComboBox()
        self.task_combo.currentIndexChanged.connect(self.on_task_selected)
        self.add_widget(self.task_combo)

        # 触发时间输入（分离小时和分钟）
        time_label = BodyLabel("触发时间:")
        time_label.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {base_text_color};")
        self.add_widget(time_label)

        # 创建时间容器
        time_container = QWidget()
        time_layout = QHBoxLayout()
        time_layout.setContentsMargins(0, 0, 0, 0)
        time_layout.setSpacing(8)
        
        # 小时下拉框
        hour_label = BodyLabel("小时:")
        hour_label.setStyleSheet(f"font-size: 11px; color: {base_text_color};")
        time_layout.addWidget(hour_label)
        
        self.hour_combo = ComboBox()
        self.hour_combo.addItems([f"{h:02d}" for h in range(24)])
        self.hour_combo.setCurrentIndex(9)  # 默认09
        self.hour_combo.currentIndexChanged.connect(self.on_options_changed)
        time_layout.addWidget(self.hour_combo)
        
        # 分钟下拉框
        minute_label = BodyLabel("分钟:")
        minute_label.setStyleSheet(f"font-size: 11px; color: {base_text_color};")
        time_layout.addWidget(minute_label)
        
        self.minute_combo = ComboBox()
        self.minute_combo.addItems([f"{m:02d}" for m in range(0, 60, 5)])
        self.minute_combo.setCurrentIndex(0)  # 默认00
        self.minute_combo.currentIndexChanged.connect(self.on_options_changed)
        time_layout.addWidget(self.minute_combo)
        
        time_layout.addStretch()
        time_container.setLayout(time_layout)
        self.add_widget(time_container)
        
        # 从配置加载默认时间
        default_time_str = self.config.get('trigger_time', '09:00')
        try:
            h, m = map(int, default_time_str.split(':'))
            h_idx = self.hour_combo.findText(f"{h:02d}")
            m_idx = self.minute_combo.findText(f"{m:02d}")
            if h_idx >= 0:
                self.hour_combo.setCurrentIndex(h_idx)
            if m_idx >= 0:
                self.minute_combo.setCurrentIndex(m_idx)
        except:
            self.hour_combo.setCurrentIndex(9)
            self.minute_combo.setCurrentIndex(0)

        # 添加分隔线
        separator2 = QFrame()
        separator2.setFrameShape(QFrame.Shape.HLine)
        separator2.setStyleSheet("background-color: rgba(0, 0, 0, 0.1);")
        self.add_widget(separator2)

        # ========== 命令行参数显示 ==========
        param_label = BodyLabel("启动参数:")
        param_label.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {base_text_color};")
        self.add_widget(param_label)

        self.param_display = BodyLabel("")
        param_color = "#5af" if isDarkTheme() else "#07f"
        self.param_display.setStyleSheet(f"color: {param_color}; font-family: Consolas;")
        self.add_widget(self.param_display)

        # ========== 选项区域 ==========
        options_label = BodyLabel("启动选项:")
        options_label.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {base_text_color};")
        self.add_widget(options_label)

        self.auto_exit_check = CheckBox("执行完成后自动退出程序 (-e)")
        self.auto_exit_check.setChecked(self.config.get('auto_exit', False))
        self.auto_exit_check.stateChanged.connect(self.on_options_changed)
        self.add_widget(self.auto_exit_check)

        # 添加分隔线
        separator3 = QFrame()
        separator3.setFrameShape(QFrame.Shape.HLine)
        separator3.setStyleSheet("background-color: rgba(0, 0, 0, 0.1);")
        self.add_widget(separator3)

        # ========== 高级选项区域 ==========
        advanced_label = BodyLabel("高级选项:")
        advanced_label.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {base_text_color};")
        self.add_widget(advanced_label)

        # 触发类型选择
        trigger_type_label = BodyLabel("触发类型:")
        trigger_type_label.setStyleSheet(f"font-size: 11px; color: {base_text_color};")
        self.add_widget(trigger_type_label)

        self.trigger_type_combo = ComboBox()
        trigger_types = self.ui_options.get('trigger_types', []) or ["每天", "每周", "每月"]
        self.trigger_type_combo.addItems(trigger_types)
        default_trigger = self.config.get('trigger_type', '每天')
        idx = self.trigger_type_combo.findText(default_trigger)
        if idx >= 0:
            self.trigger_type_combo.setCurrentIndex(idx)
        self.trigger_type_combo.currentIndexChanged.connect(self.on_trigger_type_changed)
        self.add_widget(self.trigger_type_combo)

        # 重复间隔设置
        repeat_label = BodyLabel("重复间隔:")
        repeat_label.setStyleSheet(f"font-size: 11px; color: {base_text_color};")
        self.add_widget(repeat_label)

        self.repeat_interval_combo = ComboBox()
        repeat_intervals = self.ui_options.get('repeat_intervals', []) or ["每次运行后", "每小时", "每2小时", "每4小时", "每8小时", "每12小时"]
        self.repeat_interval_combo.addItems(repeat_intervals)
        default_repeat = self.config.get('repeat_interval', 1)
        self.repeat_interval_combo.setCurrentIndex(0)  # 默认"每次运行后"
        self.repeat_interval_combo.currentIndexChanged.connect(self.on_options_changed)
        self.add_widget(self.repeat_interval_combo)

        # 执行时长限制
        timeout_label = BodyLabel("执行超时限制:")
        timeout_label.setStyleSheet(f"font-size: 11px; color: {base_text_color};")
        self.add_widget(timeout_label)

        self.timeout_combo = ComboBox()
        timeout_options = self.ui_options.get('timeout_options', []) or ["1小时 (默认)", "2小时", "4小时", "6小时", "8小时", "12小时", "无限制"]
        # 兼容旧缓存：将“6小时 (默认)”迁移为“6小时”，并将默认标记移动到 1 小时
        timeout_options = ["6小时" if x == "6小时 (默认)" else x for x in timeout_options]
        if "1小时 (默认)" not in timeout_options:
            timeout_options = ["1小时 (默认)" if x == "1小时" else x for x in timeout_options]
            if "1小时 (默认)" not in timeout_options:
                timeout_options.insert(0, "1小时 (默认)")
        # 回写本地，确保后续渲染一致
        self.ui_options['timeout_options'] = timeout_options
        self.timeout_combo.addItems(timeout_options)
        default_timeout_idx = self.timeout_combo.findText("1小时 (默认)")
        if default_timeout_idx < 0:
            default_timeout_idx = self.timeout_combo.findText("1小时")
        self.timeout_combo.setCurrentIndex(default_timeout_idx if default_timeout_idx >= 0 else 0)
        self.timeout_combo.currentIndexChanged.connect(self.on_options_changed)
        self.add_widget(self.timeout_combo)

        # 添加分隔线
        separator3 = QFrame()
        separator3.setFrameShape(QFrame.Shape.HLine)
        separator3.setStyleSheet("background-color: rgba(0, 0, 0, 0.1);")
        self.add_widget(separator3)

        # ========== 操作区域（同页分区） ==========
        button_label = BodyLabel("操作")
        button_label.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {base_text_color};")
        self.add_widget(button_label)

        # 创建区
        create_section_label = BodyLabel("创建区")
        create_section_label.setStyleSheet(f"font-size: 11px; font-weight: bold; color: {base_text_color};")
        self.add_widget(create_section_label)

        self.create_button = PrimaryPushButton("✓ 创建计划任务")
        self.create_button.clicked.connect(self.on_create_task)
        self.add_widget(self.create_button)

        # 创建区与管理区分隔
        action_separator = QFrame()
        action_separator.setFrameShape(QFrame.Shape.HLine)
        action_separator.setStyleSheet("background-color: rgba(0, 0, 0, 0.1);")
        self.add_widget(action_separator)

        # 管理区
        manage_section_label = BodyLabel("管理区")
        manage_section_label.setStyleSheet(f"font-size: 11px; font-weight: bold; color: {base_text_color};")
        self.add_widget(manage_section_label)

        manage_task_label = BodyLabel("管理任务选择:")
        manage_task_label.setStyleSheet(f"font-size: 11px; color: {base_text_color};")
        self.add_widget(manage_task_label)

        self.manage_task_combo = ComboBox()
        self.manage_task_combo.currentIndexChanged.connect(self.on_manage_task_selected)
        self.add_widget(self.manage_task_combo)

        self.manage_status_label = BodyLabel("管理任务状态: -")
        self.add_widget(self.manage_status_label)

        self.manage_trigger_label = BodyLabel("触发器信息: -")
        self.add_widget(self.manage_trigger_label)

        self.manage_advanced_label = BodyLabel("高级信息: -")
        self.add_widget(self.manage_advanced_label)

        # 强制同步按钮（从 Windows 读取并写入本地缓存）
        self.sync_button = PushButton("↻ 强制从 Windows 同步")
        self.sync_button.clicked.connect(self.on_list_tasks)
        self.add_widget(self.sync_button)

        self.enable_button = PushButton("✓ 启用任务")
        self.enable_button.clicked.connect(self.on_enable_task)
        self.add_widget(self.enable_button)

        self.disable_button = PushButton("⏸ 禁用任务")
        self.disable_button.clicked.connect(self.on_disable_task)
        self.add_widget(self.disable_button)

        self.delete_button = PushButton("✗ 删除任务")
        self.delete_button.clicked.connect(self.on_delete_task)
        self.add_widget(self.delete_button)

        # 添加分隔线
        separator4 = QFrame()
        separator4.setFrameShape(QFrame.Shape.HLine)
        separator4.setStyleSheet("background-color: rgba(0, 0, 0, 0.1);")
        self.add_widget(separator4)

        # ========== 结果显示 ==========
        self.result_label = BodyLabel("")
        self.add_widget(self.result_label)

    @property
    def name(self):
        """侧边栏显示的名称"""
        return "任务计划"

    def _load_onetime_tasks(self):
        """从已实例化的任务对象中读取 self.name 属性值"""
        tasks = []

        try:
            # 方式 1: 尝试从框架中获取已实例化的任务对象
            onetime_task_instances = self._get_task_instances_from_framework()

            if onetime_task_instances:
                self.logger.info(f"✓ 从框架获取 {len(onetime_task_instances)} 个已实例化的任务对象")

                for idx, task_instance in enumerate(onetime_task_instances, 1):
                    task_name = getattr(task_instance, 'name', task_instance.__class__.__name__)
                    class_name = task_instance.__class__.__name__

                    tasks.append({
                        'name': task_name,
                        'class': class_name,
                        'module': f"{task_instance.__class__.__module__}.{class_name}",
                        'instance': task_instance,  # 保存实例引用
                    })

                    self.logger.info(f"  [{idx}] {class_name} -> {task_name}")
            else:
                self.logger.warning("⚠ 未找到已实例化的任务对象，使用降级方案")
                tasks = self._load_onetime_tasks_fallback()

        except Exception as e:
            self.logger.warning(f"✗ 获取已实例化任务失败: {e}，使用降级方案")
            tasks = self._load_onetime_tasks_fallback()

        return tasks

    def _get_task_instances_from_framework(self):
        """从 ok-script 框架中获取已实例化的任务对象"""
        tasks = self.get_framework_task_instances()
        if tasks:
            return tasks

        self.logger.debug("未在 ok 框架中找到任务实例")
        return None

    def _load_onetime_tasks_fallback(self):
        """降级方案：从源代码读取任务名称（仅源代码读取）"""
        import re
        import os

        tasks = []

        # 定义需要加载的任务（排除诊断任务）
        task_configs = [
            ["src.tasks.DailyTask", "DailyTask"],
            ["src.tasks.TakeDeliveryTask", "TakeDeliveryTask"],
            ["src.tasks.WarehouseTransferTask", "WarehouseTransferTask"],
            ["src.tasks.DeliveryTask", "DeliveryTask"],
            ["src.tasks.EssenceScanTask", "EssenceScanTask"],
            ["src.tasks.Test", "Test"],
        ]

        for module_path, class_name in task_configs:
            task_name = class_name  # 默认使用类名

            try:
                # 仅从源代码读取任务名称
                self.logger.debug(f"从源代码读取 {class_name}...")

                file_path = module_path.replace('.', os.sep) + '.py'
                with open(file_path, 'r', encoding='utf-8') as f:
                    source_code = f.read()

                # 尝试匹配 self.name = "..." 或 self.name = '...'
                match = re.search(r'self\.name\s*=\s*["\']([^"\']+)["\']', source_code)
                if match:
                    task_name = match.group(1)
                    self.logger.info(f"✓ 从源代码读取: {class_name} -> {task_name}")
                else:
                    self.logger.warning(f"⚠ 未找到 {class_name} 的 self.name，使用默认类名")

            except FileNotFoundError:
                self.logger.warning(f"✗ 找不到源文件: {file_path}，使用默认类名")
            except Exception as e:
                self.logger.warning(f"✗ 读取源代码失败 {class_name}: {e}，使用默认类名")

            tasks.append({
                'name': task_name,
                'class': class_name,
                'module': module_path,
            })

        return tasks

    def on_task_selected(self, index: int):
        """任务选择改变"""
        if index >= 0 and index < len(self.onetime_tasks):
            self.config['selected_task_index'] = index
            self._update_params_display()
            self.logger.info(f"选择任务: {self.onetime_tasks[index]} (index: {index + 1})")
        elif index >= 0 and index < len(self.task_names):
            self.config['selected_task_index'] = index
            self._update_params_display()
            self.logger.info(f"选择任务: {self.task_names[index]} (index: {index + 1})")

    def on_trigger_type_changed(self):
        """触发类型改变"""
        trigger_type = self.trigger_type_combo.currentText()
        self.config['trigger_type'] = trigger_type
        self.logger.debug(f"触发类型改变: {trigger_type}")

    def on_options_changed(self):
        """选项改变"""
        auto_exit = self.auto_exit_check.isChecked()
        self.config['auto_exit'] = auto_exit
        self._update_params_display()

    def _get_working_directory(self):
        """获取工作路径（项目根目录）"""
        from pathlib import Path
        return str(Path(__file__).parent.parent.parent)
    
    def _build_command_params(self):
        """构建命令行参数
        
        Returns:
            dict: 包含 params、command、working_dir 的字典
        """
        from pathlib import Path
        
        task_index = self.task_combo.currentIndex() + 1  # 任务从 1 开始编号
        auto_exit = self.auto_exit_check.isChecked()

        # 构建启动参数
        params = f"-t {task_index}"
        if auto_exit:
            params += " -e"

        # 获取工作路径
        working_dir = self._get_working_directory()

        # 显示完整命令行（支持 EXE 和源码两种模式）
        command_exe = f"ok-ef.exe {params}"
        command_src = f"python main.py {params}"

        return {
            'params': params,
            'params_list': params.split(),  # 参数列表
            'command_exe': command_exe,
            'command_src': command_src,
            'working_dir': working_dir,
        }

    def _update_params_display(self):
        """更新参数显示"""
        trigger_time = f"{self.hour_combo.currentText()}:{self.minute_combo.currentText()}"
        
        # 获取完整的命令信息
        cmd_info = self._build_command_params()

        # 简化显示：只显示源码模式命令
        display_text = cmd_info['command_src']

        self.param_display.setText(display_text)
        self.logger.debug(f"参数更新 - 触发时间: {trigger_time}, 参数: {cmd_info['params']}")

    def on_create_task(self):
        """创建计划任务"""
        task_index = self.task_combo.currentIndex()
        if task_index < 0 or task_index >= len(self.task_names):
            self.result_label.setText("✗ 请选择有效的任务")
            self.result_label.setStyleSheet("color: #f66;" if isDarkTheme() else "color: #d00;")
            return

        task_name = self.task_names[task_index]
        trigger_time = f"{self.hour_combo.currentText()}:{self.minute_combo.currentText()}"
        trigger_type = self.trigger_type_combo.currentText()
        timeout_text = self.timeout_combo.currentText()

        # 获取动态参数信息
        cmd_info = self._build_command_params()

        self.logger.info(f"创建任务: {task_name}, 触发时间: {trigger_time}, 参数: {cmd_info['params']}")
        self.logger.debug(f"完整命令: {cmd_info['command_src']}, 工作路径: {cmd_info['working_dir']}")
        self.logger.debug(f"触发类型: {trigger_type}, 执行超时: {timeout_text}")

        try:
            success, message = self.create_scheduled_task(
                task_name=task_name,
                game_exe="D:\\GAMES\\Endfield Game\\Endfield.exe",
                task_command=cmd_info['params'],  # 只传递参数部分：-t 1 -e
                working_directory=cmd_info['working_dir'],
                trigger_time=trigger_time,
                trigger_type=trigger_type,
                timeout_hours=self._parse_timeout(timeout_text),
            )

            self.result_label.setText(message)
            if success:
                self.result_label.setStyleSheet("color: #0f6;" if isDarkTheme() else "color: #0a0;")
                # 保存设置
                self.config['trigger_time'] = trigger_time
                # 写入本地任务缓存（避免每次都读取 Windows 任务计划）
                self._upsert_task_cache(task_name, "已创建", trigger_time)
                # 创建后立即刷新管理区下拉
                self._refresh_manage_task_combo()
            else:
                self.result_label.setStyleSheet("color: #f66;" if isDarkTheme() else "color: #d00;")
        except Exception as e:
            self.result_label.setText(f"✗ 异常: {str(e)}")
            self.result_label.setStyleSheet("color: #f66;" if isDarkTheme() else "color: #d00;")
            self.logger.error(f"创建任务失败: {e}")

    def on_list_tasks(self):
        """强制从 Windows 同步任务并写入本地缓存"""
        self.logger.info("强制从 Windows 同步任务")
        self.result_label.setText("正在从 Windows 任务计划读取...")
        self.result_label.setStyleSheet("color: #fff;" if isDarkTheme() else "color: #000;")

        try:
            tasks, message = self.list_scheduled_tasks()

            if tasks:
                # 写入本地缓存
                self.task_cache['tasks'] = tasks
                from datetime import datetime
                self.task_cache['last_sync'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                self._refresh_manage_task_combo()

                task_list = "\n".join([
                    f"  • {t.get('name', '未知')} | 启用:{t.get('enabled', '未知')} | 状态:{t.get('status', '未知')}"
                    for t in tasks
                ])
                self.result_label.setText(f"{message}\n{task_list}")
                self.result_label.setStyleSheet("color: #fff;" if isDarkTheme() else "color: #000;")
            else:
                # 同步为空时清空本地缓存
                self.task_cache['tasks'] = []
                self._refresh_manage_task_combo()
                self.result_label.setText(message)
                # message 可能是失败或为空提示，按前缀设置颜色
                if message.startswith("✗"):
                    self.result_label.setStyleSheet("color: #f66;" if isDarkTheme() else "color: #d00;")
                else:
                    self.result_label.setStyleSheet("color: #fff;" if isDarkTheme() else "color: #000;")
        except Exception as e:
            self.result_label.setText(f"✗ 查询失败: {str(e)}")
            self.result_label.setStyleSheet("color: #f66;" if isDarkTheme() else "color: #d00;")
            self.logger.error(f"查询任务失败: {e}")

    def on_delete_task(self):
        """删除计划任务（异步执行）"""
        task_index = self.manage_task_combo.currentIndex()
        if task_index < 0 or task_index >= len(self.manage_task_items):
            self.result_label.setText("✗ 请选择要管理的任务")
            self.result_label.setStyleSheet("color: #f66;" if isDarkTheme() else "color: #d00;")
            return

        full_task_name = self.manage_task_items[task_index].get('name', '')
        task_name = full_task_name.replace(f"\\{self.task_folder}\\", "", 1)
        
        # 显示正在处理
        self.result_label.setText("⟳ 正在删除任务...")
        self.result_label.setStyleSheet("color: #fff;" if isDarkTheme() else "color: #000;")
        
        # 异步执行
        cmd = ['schtasks', '/Delete', '/TN', full_task_name, '/F']
        worker = TaskWorker(cmd, self.logger)
        worker.finished.connect(lambda success, msg: self._on_delete_task_finished(success, full_task_name, task_name, msg))
        self._delete_worker = worker  # 保持引用避免垃圾回收
        worker.start()

    def _on_delete_task_finished(self, success, full_task_name, task_name, message):
        """删除任务完成回调"""
        if success:
            self.result_label.setText(f"✓ 任务 '{task_name}' 已删除")
            self.result_label.setStyleSheet("color: #0f6;" if isDarkTheme() else "color: #0a0;")
            # 本地缓存同步删除
            tasks = self.task_cache.get('tasks', []) or []
            self.task_cache['tasks'] = [t for t in tasks if t.get('name') != full_task_name]
            self._refresh_manage_task_combo()
        else:
            self.result_label.setText(f"✗ 删除失败: {message}")
            self.result_label.setStyleSheet("color: #f66;" if isDarkTheme() else "color: #d00;")

    def on_enable_task(self):
        """启用计划任务（异步执行）"""
        task_index = self.manage_task_combo.currentIndex()
        if task_index < 0 or task_index >= len(self.manage_task_items):
            self.result_label.setText("✗ 请选择要管理的任务")
            self.result_label.setStyleSheet("color: #f66;" if isDarkTheme() else "color: #d00;")
            return

        full_task_name = self.manage_task_items[task_index].get('name', '')
        task_name = full_task_name.replace(f"\\{self.task_folder}\\", "", 1)
        
        # 显示正在处理
        self.result_label.setText("⟳ 正在启用任务...")
        self.result_label.setStyleSheet("color: #fff;" if isDarkTheme() else "color: #000;")
        
        # 异步执行
        cmd = ['schtasks', '/Change', '/TN', full_task_name, '/ENABLE']
        worker = TaskWorker(cmd, self.logger)
        worker.finished.connect(lambda success, msg: self._on_enable_task_finished(success, task_name, msg))
        self._enable_worker = worker  # 保持引用避免垃圾回收
        worker.start()

    def _on_enable_task_finished(self, success, task_name, message):
        """启用任务完成回调"""
        if success:
            self.result_label.setText(f"✓ 任务 '{task_name}' 已启用")
            self.result_label.setStyleSheet("color: #0f6;" if isDarkTheme() else "color: #0a0;")
            self._upsert_task_cache(task_name, "已启用")
            self._refresh_manage_task_combo()
        else:
            self.result_label.setText(f"✗ 启用失败: {message}")
            self.result_label.setStyleSheet("color: #f66;" if isDarkTheme() else "color: #d00;")

    def on_disable_task(self):
        """禁用计划任务（异步执行）"""
        task_index = self.manage_task_combo.currentIndex()
        if task_index < 0 or task_index >= len(self.manage_task_items):
            self.result_label.setText("✗ 请选择要管理的任务")
            self.result_label.setStyleSheet("color: #f66;" if isDarkTheme() else "color: #d00;")
            return

        full_task_name = self.manage_task_items[task_index].get('name', '')
        task_name = full_task_name.replace(f"\\{self.task_folder}\\", "", 1)
        
        # 显示正在处理
        self.result_label.setText("⟳ 正在禁用任务...")
        self.result_label.setStyleSheet("color: #fff;" if isDarkTheme() else "color: #000;")
        
        # 异步执行
        cmd = ['schtasks', '/Change', '/TN', full_task_name, '/DISABLE']
        worker = TaskWorker(cmd, self.logger)
        worker.finished.connect(lambda success, msg: self._on_disable_task_finished(success, task_name, msg))
        self._disable_worker = worker  # 保持引用避免垃圾回收
        worker.start()

    def _on_disable_task_finished(self, success, task_name, message):
        """禁用任务完成回调"""
        if success:
            self.result_label.setText(f"✓ 任务 '{task_name}' 已禁用")
            self.result_label.setStyleSheet("color: #0f6;" if isDarkTheme() else "color: #0a0;")
            self._upsert_task_cache(task_name, "已禁用")
            self._refresh_manage_task_combo()
        else:
            self.result_label.setText(f"✗ 禁用失败: {message}")
            self.result_label.setStyleSheet("color: #f66;" if isDarkTheme() else "color: #d00;")

    def showEvent(self, event):
        super().showEvent(event)
        if event.type() == QEvent.Show:
            self.logger.info(f'{self.__class__.__name__} 页面已显示')

            # 首次显示时加载任务名称（此时游戏进程已初始化）
            if not self.tasks_loaded:
                self.logger.info("开始从本地加载任务可选项...")
                local_task_names = self.task_option_cache.get('task_names', []) or []

                if local_task_names:
                    self.task_names = local_task_names
                    self.logger.info(f"✓ 从本地读取任务可选项 {len(self.task_names)} 个")
                else:
                    # 本地为空时回退动态加载，并写入本地
                    self.logger.info("本地无任务可选项，回退动态加载并写入本地")
                    self.onetime_tasks = self._load_onetime_tasks()
                    self.task_names = [task.get('name', '未知') for task in self.onetime_tasks]
                    self.task_option_cache['task_names'] = self.task_names

                # 更新下拉菜单
                self.task_combo.addItems(self.task_names)
                self.task_combo.setCurrentIndex(self.config.get('selected_task_index', 0))

                self.tasks_loaded = True
                self.logger.info(f"✓ 任务加载完成，共 {len(self.task_names)} 个")

                # 初始化参数显示
                if self.task_combo.currentIndex() >= 0:
                    self.on_task_selected(self.task_combo.currentIndex())

            # 每次显示都刷新管理区下拉（读取本地缓存）
            self._refresh_manage_task_combo()

    def hideEvent(self, event: QEvent):
        super().hideEvent(event)
        self.logger.info(f'{self.__class__.__name__} 页面已隐藏')

    # ========== TaskSchedulerHelper 方法集成 ==========
    
    def _init_scheduler_helper(self):
        """初始化任务计划助手功能"""
        self.task_folder = "ok-ef"  # Windows 任务计划中的文件夹名
    
    def create_scheduled_task(self, task_name: str, game_exe: str, task_command: str, working_directory: str, trigger_time: str, trigger_type: str = "每天", timeout_hours: int = 6):
        """创建 Windows 计划任务
        
        Args:
            task_name: 任务名称（如 "日常任务", "副本扫荡"）
            game_exe: 游戏执行文件路径（如 "D:\\Games\\Endfield.exe"）
            task_command: 任务参数（如 "-t 1 -e"）
            working_directory: 工作路径（如 "D:\\project\\ok-end-field"）
            trigger_time: 触发时间（如 "09:00"）
            trigger_type: 触发类型（"每天", "每周", "每月"）
            timeout_hours: 执行超时限制（小时），0 表示无限制
        
        Returns:
            tuple: (success: bool, message: str)
        """
        import subprocess
        from pathlib import Path
        
        try:
            # 获取项目根目录
            project_root = Path(working_directory)
            
            # 创建 XML 任务定义
            task_xml = self._create_task_xml(
                task_name=task_name,
                game_exe=game_exe,
                task_command=task_command,
                working_directory=working_directory,
                trigger_time=trigger_time,
                trigger_type=trigger_type,
                timeout_hours=timeout_hours,
            )
            
            # 保存临时 XML 文件（UTF-16 编码以符合 Windows 任务计划要求）
            temp_xml = project_root / f"temp_task_{task_name}.xml"
            try:
                # Windows 任务计划需要 UTF-16 编码，且需要 BOM
                with open(temp_xml, 'w', encoding='utf-16') as f:
                    f.write(task_xml)
                
                # 使用 schtasks 导入任务
                full_task_name = f"\\{self.task_folder}\\{task_name}"
                cmd = [
                    'schtasks', '/Create',
                    '/TN', full_task_name,
                    '/XML', str(temp_xml),
                    '/F'
                ]
                
                result = subprocess.run(cmd, capture_output=True, text=True)
                
                if result.returncode == 0:
                    self.logger.info(f"成功创建计划任务: {full_task_name}")
                    return True, f"✓ 任务 '{task_name}' 创建成功，将在 {trigger_time} 自动执行"
                else:
                    error_msg = result.stderr if result.stderr else "未知错误"
                    self.logger.error(f"创建计划任务失败: {error_msg}")
                    return False, f"✗ 创建失败: {error_msg}"
            finally:
                # 清理临时文件
                if temp_xml.exists():
                    temp_xml.unlink()
                    
        except Exception as e:
            self.logger.error(f"创建计划任务异常: {e}")
            return False, f"✗ 异常: {str(e)}"
    
    def delete_scheduled_task(self, task_name: str):
        """删除 Windows 计划任务
        
        Args:
            task_name: 任务名称
        
        Returns:
            tuple: (success: bool, message: str)
        """
        import subprocess
        
        try:
            full_task_name = f"\\{self.task_folder}\\{task_name}"
            cmd = ['schtasks', '/Delete', '/TN', full_task_name, '/F']
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                self.logger.info(f"成功删除计划任务: {full_task_name}")
                return True, f"✓ 任务 '{task_name}' 已删除"
            else:
                error_msg = result.stderr if result.stderr else "任务不存在"
                self.logger.error(f"删除计划任务失败: {error_msg}")
                return False, f"✗ 删除失败: {error_msg}"
        except Exception as e:
            self.logger.error(f"删除计划任务异常: {e}")
            return False, f"✗ 异常: {str(e)}"
    
    def list_scheduled_tasks(self):
        """列出所有 ok-ef 相关的计划任务
        
        优先使用 Windows COM API 获取，失败则回退到 CSV 解析
        
        Returns:
            tuple: (task_list: list, message: str)
        """
        import csv
        import io
        import subprocess

        def _pick_value(row, exact_keys, fuzzy_keys):
            for key in exact_keys:
                val = row.get(key)
                if val is not None and str(val).strip() != "":
                    return str(val).strip()

            for raw_key, raw_val in row.items():
                key = str(raw_key).replace('\ufeff', '').strip().lower()
                for fuzzy in fuzzy_keys:
                    if fuzzy in key and str(raw_val).strip() != "":
                        return str(raw_val).strip()
            return ""

        # ==================== 尝试 COM API 方式 ====================
        try:
            import win32com.client
            
            self.logger.info("尝试使用 COM API 获取任务...")
            service = win32com.client.Dispatch("Schedule.Service")
            service.Connect()
            root_folder = service.GetFolder("\\")
            
            # 尝试获取 "ok-ef" 文件夹
            try:
                ok_folder = root_folder.GetFolder(self.task_folder)
            except Exception as e:
                self.logger.info(f"COM API: '{self.task_folder}' 文件夹不存在 ({e})，尝试 CSV 解析")
                return self._list_tasks_csv()
            
            tasks = []
            task_collection = ok_folder.GetTasks(0)  # 0 = include all tasks
            
            for task in task_collection:
                task_name = task.Name
                full_task_name = f"\\{self.task_folder}\\{task_name}"
                definition = task.Definition
                
                # 获取状态（1=禁用, 3=准备就绪, 4=运行中）
                state_map = {
                    0: "Unknown",
                    1: "Disabled",
                    2: "Queued",
                    3: "Ready",
                    4: "Running"
                }
                state = state_map.get(task.State, "Unknown")
                status = "禁用" if state == "Disabled" else "就绪"
                enabled = "是" if state != "Disabled" else "否"
                
                # 提取触发器信息
                trigger_info = "无"
                if definition.Triggers.Count > 0:
                    trigger = definition.Triggers.Item(1)  # 取第一个触发器
                    trigger_type_map = {
                        1: "计时器",
                        2: "日程",           # 系统中类型2是日程触发器（有StartBoundary）
                        3: "时间",
                        4: "启动",
                        5: "登录",
                        6: "空闲",
                        7: "会话状态",
                        8: "注册"
                    }
                    
                    # 根据触发器类型提取详细信息
                    try:
                        if trigger.Type == 1:  # 计时器
                            repeat_interval = trigger.Repetition.Interval
                            if repeat_interval:
                                trigger_info = f"计时器 - {repeat_interval}"
                            else:
                                trigger_info = "计时器"
                        elif trigger.Type == 2:  # 日程/日期和时间触发
                            # 日程触发器有 StartBoundary、DaysInterval 等属性
                            try:
                                start_boundary = trigger.StartBoundary
                                days_interval = trigger.DaysInterval
                                if start_boundary:
                                    # 提取时间部分
                                    time_part = start_boundary.split('T')[-1] if 'T' in start_boundary else start_boundary
                                    if days_interval and days_interval > 1:
                                        trigger_info = f"日程 - 每{days_interval}天 {time_part}"
                                    else:
                                        trigger_info = f"日程 - 每天 {time_part}"
                                else:
                                    trigger_info = "日程"
                            except:
                                trigger_info = "日程"
                        elif trigger.Type == 3:  # 时间
                            # 尝试获取时间触发的开始时间
                            try:
                                start_boundary = trigger.StartBoundary
                                if start_boundary:
                                    time_part = start_boundary.split('T')[-1] if 'T' in start_boundary else start_boundary
                                    trigger_info = f"时间 - {time_part}"
                                else:
                                    trigger_info = "时间"
                            except:
                                trigger_info = "时间"
                        elif trigger.Type == 4:  # 启动
                            trigger_info = "启动"
                        elif trigger.Type == 5:  # 登录
                            trigger_info = "登录"
                        elif trigger.Type == 6:  # 空闲
                            # 尝试获取空闲时间
                            try:
                                idle_duration = trigger.IdleDuration
                                if idle_duration:
                                    trigger_info = f"空闲 - {idle_duration}"
                                else:
                                    trigger_info = "空闲"
                            except:
                                trigger_info = "空闲"
                        else:
                            trigger_type = trigger_type_map.get(trigger.Type, f"类型{trigger.Type}")
                            trigger_info = trigger_type
                    except Exception as e:
                        # 如果提取详细信息失败，使用基础类型名
                        trigger_type_base = trigger_type_map.get(trigger.Type, f"类型{trigger.Type}")
                        trigger_info = trigger_type_base
                        self.logger.debug(f"提取触发器详情失败: {e}")
                
                # 提取高级信息（运行用户、下次运行等）
                advanced_info_parts = []
                
                # 获取运行用户
                if definition.Principal:
                    try:
                        run_user = definition.Principal.UserID
                        if run_user:
                            advanced_info_parts.append(f"运行用户:{run_user}")
                    except:
                        pass
                
                # 获取下次运行时间（从任务对象）
                try:
                    next_run = task.NextRunTime
                    if next_run:
                        advanced_info_parts.append(f"下次运行:{next_run}")
                except:
                    pass
                
                # 获取上次结果
                try:
                    last_result = task.LastTaskResult
                    if last_result:
                        advanced_info_parts.append(f"上次结果:0x{last_result:X}")
                except:
                    pass
                
                advanced_info = " / ".join(advanced_info_parts) if advanced_info_parts else "无"
                
                tasks.append({
                    'name': full_task_name,
                    'status': status,
                    'enabled': enabled,
                    'trigger_info': trigger_info,
                    'advanced_info': advanced_info,
                })
                
                self.logger.info(f"COM API 获取任务: {task_name} - 状态:{status} - 触发:{trigger_info}")
            
            self.logger.info(f"COM API 成功获取 {len(tasks)} 个任务")
            
            if tasks:
                return tasks, f"✓ 找到 {len(tasks)} 个任务（COM API）"
            else:
                return [], f"✓ 暂无计划任务（COM API）"
                
        except ImportError as e:
            self.logger.info(f"COM API: win32com.client 未安装 ({e})，回退到 CSV 解析")
        except Exception as e:
            self.logger.warning(f"COM API 失败: {e}，回退到 CSV 解析")
            import traceback
            self.logger.debug(f"COM API 异常堆栈: {traceback.format_exc()}")
        
        # ==================== 回退：CSV 解析方式 ====================
        return self._list_tasks_csv()
    
    def _list_tasks_csv(self):
        """通过 schtasks CSV 输出解析任务列表（后备方案）"""
        import csv
        import io
        import subprocess
        
        def _pick_value(row, exact_keys, fuzzy_keys):
            for key in exact_keys:
                val = row.get(key)
                if val is not None and str(val).strip() != "":
                    return str(val).strip()

            for raw_key, raw_val in row.items():
                key = str(raw_key).replace('\ufeff', '').strip().lower()
                for fuzzy in fuzzy_keys:
                    if fuzzy in key and str(raw_val).strip() != "":
                        return str(raw_val).strip()
            return ""
        
        try:
            # 直接查询全部任务，避免 /TN 文件夹不存在或本地化差异导致失败
            cmd = ['schtasks', '/Query', '/FO', 'CSV', '/V']
            result = subprocess.run(cmd, capture_output=True)

            # schtasks 在不同系统可能返回不同编码，这里做多编码兼容
            stdout_text = ""
            stderr_text = ""
            used_encoding = "unknown"
            for enc in ('utf-8-sig', 'gbk', 'cp936', 'utf-16le'):
                try:
                    candidate = result.stdout.decode(enc)
                    if candidate.strip():
                        stdout_text = candidate
                        used_encoding = enc
                        break
                except Exception:
                    continue

            for enc in ('utf-8-sig', 'gbk', 'cp936', 'utf-16le'):
                try:
                    candidate = result.stderr.decode(enc)
                    if candidate.strip():
                        stderr_text = candidate
                        break
                except Exception:
                    continue

            if result.returncode != 0:
                error_msg = stderr_text.strip() if stderr_text else "未知错误"
                self.logger.error(f"CSV 查询计划任务失败: {error_msg}")
                return [], f"✗ 查询失败: {error_msg}"

            if not stdout_text.strip():
                self.logger.error("CSV 查询计划任务失败: 输出为空")
                return [], "✗ 查询失败: 未获取到任务计划输出"

            # 自动识别 CSV 分隔符（部分区域设置可能不是逗号）
            try:
                dialect = csv.Sniffer().sniff(stdout_text[:2048], delimiters=",;")
                delimiter = dialect.delimiter
            except Exception:
                delimiter = ','

            tasks = []
            total_rows = 0
            matched_rows = 0
            folder_prefix = f"\\{self.task_folder}\\".lower()
            reader = csv.DictReader(io.StringIO(stdout_text), delimiter=delimiter)

            for row in reader:
                total_rows += 1
                task_name = _pick_value(
                    row,
                    ['TaskName', '任务名', '任务名称'],
                    ['taskname', '任务名', '任务名称']
                )
                if not task_name:
                    continue

                if task_name.lower().startswith(folder_prefix):
                    matched_rows += 1
                    status = _pick_value(
                        row,
                        ['Status', '状态'],
                        ['status', '状态', 'state']
                    ) or '未知'

                    schedule_type = _pick_value(
                        row,
                        ['Schedule Type', '计划类型', '计划任务类型'],
                        ['schedule type', '计划类型', '计划任务类型']
                    )
                    start_time = _pick_value(
                        row,
                        ['Start Time', '开始时间'],
                        ['start time', '开始时间']
                    )
                    start_date = _pick_value(
                        row,
                        ['Start Date', '开始日期'],
                        ['start date', '开始日期']
                    )
                    repeat_every = _pick_value(
                        row,
                        ['Repeat: Every', '重复间隔'],
                        ['repeat: every', '重复间隔', '每隔']
                    )

                    run_as_user = _pick_value(
                        row,
                        ['Run As User', '运行用户'],
                        ['run as user', '运行用户']
                    )
                    next_run_time = _pick_value(
                        row,
                        ['Next Run Time', '下次运行时间'],
                        ['next run time', '下次运行时间']
                    )
                    last_result = _pick_value(
                        row,
                        ['Last Result', '上次运行结果'],
                        ['last result', '上次运行结果']
                    )

                    enabled = '否' if ('禁用' in status or 'disabled' in status.lower()) else '是'
                    
                    # 构建更详细的触发器信息
                    trigger_parts = []
                    if schedule_type:
                        trigger_parts.append(schedule_type)
                    if start_time:
                        trigger_parts.append(f"时间:{start_time}")
                    if start_date:
                        trigger_parts.append(f"日期:{start_date}")
                    if repeat_every:
                        trigger_parts.append(f"重复:{repeat_every}")
                    
                    trigger_info = " | ".join(trigger_parts) if trigger_parts else '未知'
                    
                    self.logger.debug(f"CSV 任务 {task_name}: schedule_type={schedule_type}, start_time={start_time}, start_date={start_date}, repeat_every={repeat_every} => trigger_info={trigger_info}")
                    
                    advanced_info = " / ".join([
                        x for x in [
                            f"运行用户:{run_as_user}" if run_as_user else '',
                            f"下次运行:{next_run_time}" if next_run_time else '',
                            f"上次结果:{last_result}" if last_result else ''
                        ] if x
                    ]) or '未知'

                    tasks.append({
                        'name': task_name,
                        'status': status,
                        'enabled': enabled,
                        'trigger_info': trigger_info,
                        'advanced_info': advanced_info,
                    })

            self.logger.info(f"CSV 解析状态: encoding={used_encoding}, delimiter='{delimiter}', total_rows={total_rows}, matched_rows={matched_rows}")

            if tasks:
                return tasks, f"✓ 找到 {len(tasks)} 个任务（编码:{used_encoding}，分隔符:{delimiter}）"

            # 没有匹配到时给出更明确提示，便于排查
            return [], f"✓ 暂无计划任务（编码:{used_encoding}，分隔符:{delimiter}，扫描:{total_rows} 行，匹配:{matched_rows} 行）"
        except Exception as e:
            self.logger.error(f"CSV 查询计划任务异常: {e}")
            return [], f"✗ 查询失败: {str(e)}"
    
    def _parse_timeout(self, timeout_text: str) -> int:
        """解析超时文本为小时数"""
        timeout_map = {
            "1小时": 1,
            "1小时 (默认)": 1,
            "2小时": 2,
            "4小时": 4,
            "6小时": 6,
            "8小时": 8,
            "12小时": 12,
            "无限制": 0,
        }
        return timeout_map.get(timeout_text, 1)

    def _get_trigger_type_days(self, trigger_type: str) -> int:
        """获取触发类型对应的天数"""
        trigger_map = {
            "每天": 1,
            "每周": 7,
            "每月": 30,
        }
        return trigger_map.get(trigger_type, 1)

    def _get_python_executable(self):
        """获取当前 Python 可执行文件路径"""
        import sys
        return sys.executable

    def _create_task_xml(self, task_name: str, game_exe: str, task_command: str, working_directory: str, trigger_time: str, trigger_type: str = "每天", timeout_hours: int = 1) -> str:
        """生成 Windows 任务计划的 XML 定义"""
        from datetime import datetime
        import html

        hours, minutes = trigger_time.split(':')
        now = datetime.now().isoformat()
        today = now.split("T")[0]
        days_interval = self._get_trigger_type_days(trigger_type)

        python_exe = html.escape(self._get_python_executable())
        working_dir_escaped = html.escape(working_directory)
        arguments_escaped = html.escape(f"main.py {task_command}")
        timeout_xml = "" if timeout_hours == 0 else f"<ExecutionTimeLimit>PT{timeout_hours}H</ExecutionTimeLimit>"

        xml_template = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
    <RegistrationInfo>
        <Date>{now}</Date>
        <Author>ok-end-field</Author>
        <Description>{task_name}</Description>
    </RegistrationInfo>
    <Triggers>
        <CalendarTrigger>
            <StartBoundary>{today}T{hours}:{minutes}:00</StartBoundary>
            <Enabled>true</Enabled>
            <ScheduleByDay>
                <DaysInterval>{days_interval}</DaysInterval>
            </ScheduleByDay>
        </CalendarTrigger>
    </Triggers>
    <Principals>
        <Principal id="Author">
            <LogonType>InteractiveToken</LogonType>
            <RunLevel>HighestAvailable</RunLevel>
        </Principal>
    </Principals>
    <Settings>
        <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
        <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
        <StopIfGoingOnBatteries>true</StopIfGoingOnBatteries>
        <AllowHardTerminate>true</AllowHardTerminate>
        <StartWhenAvailable>true</StartWhenAvailable>
        <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
        <AllowStartOnDemand>true</AllowStartOnDemand>
        <Enabled>true</Enabled>
        <Hidden>false</Hidden>
        {timeout_xml}
        <Priority>7</Priority>
    </Settings>
    <Actions Context="Author">
        <Exec>
            <Command>{python_exe}</Command>
            <Arguments>{arguments_escaped}</Arguments>
            <WorkingDirectory>{working_dir_escaped}</WorkingDirectory>
        </Exec>
    </Actions>
</Task>
"""
        return xml_template
    
    def _parse_task_list(self, output: str) -> list:
        """解析任务列表输出
        
        Args:
            output: schtasks 命令的输出
        
        Returns:
            list: 任务信息列表
        """
        tasks = []
        lines = output.split('\n')
        
        current_task = {}
        for line in lines:
            if line.startswith('任务名称:') or line.startswith('HostName:'):
                if current_task:
                    tasks.append(current_task)
                current_task = {}
            
            if ':' in line:
                key, value = line.split(':', 1)
                current_task[key.strip()] = value.strip()
        
        if current_task:
            tasks.append(current_task)
        
        return tasks

    def _upsert_task_cache(self, task_name: str, status: str, trigger_time: str = ""):
        """更新本地缓存中的任务信息"""
        from datetime import datetime

        full_name = f"\\{self.task_folder}\\{task_name}"
        tasks = self.task_cache.get('tasks', []) or []
        now_text = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        updated = False
        for item in tasks:
            if item.get('name') == full_name:
                item['status'] = status
                item['enabled'] = '否' if ('禁用' in status or 'disabled' in status.lower()) else '是'
                if trigger_time:
                    item['trigger_time'] = trigger_time
                    item['trigger_info'] = f"开始时间:{trigger_time}"
                elif not item.get('trigger_info'):
                    item['trigger_info'] = '未知'
                if not item.get('advanced_info'):
                    item['advanced_info'] = '本地创建缓存'
                item['updated_at'] = now_text
                updated = True
                break
        if not updated:
            tasks.append({
                'name': full_name,
                'status': status,
                'enabled': '否' if ('禁用' in status or 'disabled' in status.lower()) else '是',
                'trigger_time': trigger_time,
                'trigger_info': f"开始时间:{trigger_time}" if trigger_time else '未知',
                'advanced_info': '本地创建缓存',
                'updated_at': now_text,
            })

        self.task_cache['tasks'] = tasks
        self.task_cache['last_sync'] = now_text

    def _refresh_manage_task_combo(self):
        """刷新管理区任务下拉（来自本地缓存）"""
        tasks = self.task_cache.get('tasks', []) or []
        self.manage_task_items = tasks
        self.manage_task_combo.clear()

        if not tasks:
            self.manage_status_label.setText("管理任务状态: -")
            self.manage_trigger_label.setText("触发器信息: -")
            self.manage_advanced_label.setText("高级信息: -")
            return

        self.manage_task_combo.addItems([t.get('name', '未知任务') for t in tasks])
        self.manage_task_combo.setCurrentIndex(0)
        self.on_manage_task_selected(0)

    def on_manage_task_selected(self, index: int):
        """管理区下拉选择变化"""
        if index < 0 or index >= len(self.manage_task_items):
            self.manage_status_label.setText("管理任务状态: -")
            self.manage_trigger_label.setText("触发器信息: -")
            self.manage_advanced_label.setText("高级信息: -")
            return

        item = self.manage_task_items[index]
        status = item.get('status', '未知')
        enabled = item.get('enabled', '未知')
        trigger_info = item.get('trigger_info') or item.get('trigger_time') or '未知'
        advanced_info = item.get('advanced_info', '未知')

        self.manage_status_label.setText(f"管理任务状态: {status} | 启用: {enabled}")
        self.manage_trigger_label.setText(f"触发器信息: {trigger_info}")
        self.manage_advanced_label.setText(f"高级信息: {advanced_info}")


class TaskScheduleManageTab(CustomTab):
    """计划任务总览与管理"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger.info(f'{self.__class__.__name__} 初始化')
        self.config = Config(self.__class__.__name__, {
            'selected_task_name': '',
        })
        self.task_cache = Config('TaskScheduleCache', {
            'tasks': [],
            'last_sync': '',
        })
        self.task_folder = "ok-ef"
        self.task_items = []

        self.icon = FluentIcon.CALENDAR
        base_text_color = "#fff" if isDarkTheme() else "#000"

        title = BodyLabel("计划任务总览")
        title.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {base_text_color};")
        self.add_widget(title)

        description = BodyLabel("展示计划任务并提供启用/禁用/删除操作")
        self.add_widget(description)

        separator1 = QFrame()
        separator1.setFrameShape(QFrame.Shape.HLine)
        separator1.setStyleSheet("background-color: rgba(0, 0, 0, 0.1);")
        self.add_widget(separator1)

        task_label = BodyLabel("任务列表:")
        task_label.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {base_text_color};")
        self.add_widget(task_label)

        self.task_combo = ComboBox()
        self.task_combo.currentIndexChanged.connect(self.on_task_selected)
        self.add_widget(self.task_combo)

        self.status_label = BodyLabel("状态: -")
        self.add_widget(self.status_label)

        self.sync_button = PrimaryPushButton("↻ 强制从 Windows 同步")
        self.sync_button.clicked.connect(self.on_force_sync_tasks)
        self.add_widget(self.sync_button)

        self.enable_button = PushButton("✓ 启用任务")
        self.enable_button.clicked.connect(self.on_enable_task)
        self.add_widget(self.enable_button)

        self.disable_button = PushButton("⏸ 禁用任务")
        self.disable_button.clicked.connect(self.on_disable_task)
        self.add_widget(self.disable_button)

        self.delete_button = PushButton("✗ 删除任务")
        self.delete_button.clicked.connect(self.on_delete_task)
        self.add_widget(self.delete_button)

        separator2 = QFrame()
        separator2.setFrameShape(QFrame.Shape.HLine)
        separator2.setStyleSheet("background-color: rgba(0, 0, 0, 0.1);")
        self.add_widget(separator2)

        self.result_label = BodyLabel("")
        self.add_widget(self.result_label)

    @property
    def name(self):
        return "任务总览"

    def showEvent(self, event):
        super().showEvent(event)
        if event.type() == QEvent.Show:
            self.load_tasks_from_local_cache()

    def _normalize_task_name(self, task_name: str) -> str:
        if task_name.startswith(f"\\{self.task_folder}\\"):
            return task_name
        return f"\\{self.task_folder}\\{task_name}"

    def _save_local_cache(self, tasks: list):
        from datetime import datetime
        self.task_cache['tasks'] = tasks
        self.task_cache['last_sync'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    def load_tasks_from_local_cache(self):
        tasks = self.task_cache.get('tasks', []) or []
        last_sync = self.task_cache.get('last_sync', '')
        self.task_items = tasks
        self.task_combo.clear()
        if tasks:
            self.task_combo.addItems([t['name'] for t in tasks])
            selected_name = self.config.get('selected_task_name', '')
            idx = self.task_combo.findText(selected_name)
            self.task_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.on_task_selected(self.task_combo.currentIndex())
            msg = f"✓ 已加载本地缓存 {len(tasks)} 个任务"
            if last_sync:
                msg += f"（上次同步: {last_sync}）"
            self.result_label.setText(msg)
            self.result_label.setStyleSheet("color: #fff;" if isDarkTheme() else "color: #000;")
        else:
            self.status_label.setText("状态: -")
            self.result_label.setText("本地缓存为空，请点击“强制从 Windows 同步”")
            self.result_label.setStyleSheet("color: #f66;" if isDarkTheme() else "color: #d00;")

    def on_force_sync_tasks(self):
        tasks, message = self.list_scheduled_tasks()
        if tasks:
            self._save_local_cache(tasks)
        else:
            # 同步为空时也清空缓存，避免展示过期任务
            self._save_local_cache([])
        self.load_tasks_from_local_cache()
        if message.startswith("✗"):
            self.result_label.setText(message)
            self.result_label.setStyleSheet("color: #f66;" if isDarkTheme() else "color: #d00;")

    def on_task_selected(self, index: int):
        if index < 0 or index >= len(self.task_items):
            return
        task = self.task_items[index]
        self.config['selected_task_name'] = task['name']
        self.status_label.setText(f"状态: {task.get('status') or '未知'}")

    def _change_task_state(self, action: str):
        import subprocess

        index = self.task_combo.currentIndex()
        if index < 0 or index >= len(self.task_items):
            self.result_label.setText("✗ 请先选择任务")
            self.result_label.setStyleSheet("color: #f66;" if isDarkTheme() else "color: #d00;")
            return

        full_task_name = self._normalize_task_name(self.task_items[index]['name'])
        if action == 'ENABLE':
            cmd = ['schtasks', '/Change', '/TN', full_task_name, '/ENABLE']
        elif action == 'DISABLE':
            cmd = ['schtasks', '/Change', '/TN', full_task_name, '/DISABLE']
        elif action == 'DELETE':
            cmd = ['schtasks', '/Delete', '/TN', full_task_name, '/F']
        else:
            return

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            tips = {'ENABLE': '已启用', 'DISABLE': '已禁用', 'DELETE': '已删除'}
            self.result_label.setText(f"✓ 任务 {tips[action]}: {full_task_name}")
            self.result_label.setStyleSheet("color: #0f6;" if isDarkTheme() else "color: #0a0;")
            # 优先更新本地缓存，不强制读取 Windows
            if action == 'DELETE':
                self.task_items = [t for t in self.task_items if t.get('name') != full_task_name]
            else:
                new_status = '已启用' if action == 'ENABLE' else '已禁用'
                for t in self.task_items:
                    if t.get('name') == full_task_name:
                        t['status'] = new_status
                        break
            self._save_local_cache(self.task_items)
            self.load_tasks_from_local_cache()
        else:
            err = result.stderr.strip() if result.stderr else "未知错误"
            self.result_label.setText(f"✗ 操作失败: {err}")
            self.result_label.setStyleSheet("color: #f66;" if isDarkTheme() else "color: #d00;")

    def on_enable_task(self):
        self._change_task_state('ENABLE')

    def on_disable_task(self):
        self._change_task_state('DISABLE')

    def on_delete_task(self):
        self._change_task_state('DELETE')
