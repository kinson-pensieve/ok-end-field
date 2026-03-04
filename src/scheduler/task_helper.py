"""
任务计划助手 - 将普通任务添加到 Windows 任务计划程序

该类用于自定义侧边栏，提供将游戏自动化任务添加到
Windows 任务计划程序的功能，实现定时自动执行。
"""

import subprocess
import logging
from pathlib import Path
import xml.etree.ElementTree as ET
from ok import BaseTask
from src.tasks.BaseEfTask import BaseEfTask
from src.tasks.TaskAccessMixin import TaskAccessMixin


class TaskSchedulerHelper(BaseTask, TaskAccessMixin):
    """任务计划助手
    
    继承自 BaseEfTask 以获得框架提供的完整任务上下文和能力，
    同时通过 TaskAccessMixin 访问已实例化的框架任务对象。
    
    用于将 ok-ef 的自动化任务添加到 Windows 任务计划程序，
    实现定时自动执行任务的功能。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "任务计划助手"
        self.description = "将任务添加到 Windows 任务计划程序"
        self.task_folder = "ok-ef"  # Windows 任务计划中的文件夹名
    
    def create_scheduled_task(self, task_name: str, game_exe: str, task_command: str, trigger_time: str):
        """创建 Windows 计划任务
        
        Args:
            task_name: 任务名称（如 "日常任务", "副本扫荡"）
            game_exe: 游戏执行文件路径（如 "D:\\Games\\Endfield.exe"）
            task_command: 要执行的命令（如 "python main.py --task DailyTask"）
            trigger_time: 触发时间（如 "09:00"）
        
        Returns:
            tuple: (success: bool, message: str)
        """
        try:
            # 获取项目根目录
            project_root = Path(__file__).parent.parent.parent
            
            # 创建 XML 任务定义
            task_xml = self._create_task_xml(
                task_name=task_name,
                game_exe=game_exe,
                task_command=str(project_root / task_command),
                trigger_time=trigger_time
            )
            
            # 保存临时 XML 文件
            temp_xml = project_root / f"temp_task_{task_name}.xml"
            try:
                with open(temp_xml, 'w', encoding='utf-8') as f:
                    f.write(task_xml)
                
                # 使用 schtasks 导入任务
                full_task_name = f"{self.task_folder}\\{task_name}"
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
        try:
            full_task_name = f"{self.task_folder}\\{task_name}"
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
        
        Returns:
            tuple: (task_list: list, message: str)
        """
        try:
            cmd = ['schtasks', '/Query', '/TN', self.task_folder, '/FO', 'LIST', '/V']
            result = subprocess.run(cmd, capture_output=True, text=True, encoding='gbk')
            
            if result.returncode == 0:
                tasks = self._parse_task_list(result.stdout)
                if tasks:
                    msg = f"✓ 找到 {len(tasks)} 个任务"
                    return tasks, msg
                else:
                    return [], "✓ 暂无计划任务"
            else:
                return [], "✓ 暂无计划任务"
        except Exception as e:
            self.logger.error(f"查询计划任务异常: {e}")
            return [], f"✗ 查询失败: {str(e)}"
    
    def enable_scheduled_task(self, task_name: str):
        """启用计划任务
        
        Args:
            task_name: 任务名称
        
        Returns:
            tuple: (success: bool, message: str)
        """
        try:
            full_task_name = f"{self.task_folder}\\{task_name}"
            cmd = ['schtasks', '/Change', '/TN', full_task_name, '/ENABLE']
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                self.logger.info(f"成功启用任务: {full_task_name}")
                return True, f"✓ 任务 '{task_name}' 已启用"
            else:
                return False, f"✗ 启用失败: {result.stderr}"
        except Exception as e:
            return False, f"✗ 异常: {str(e)}"
    
    def disable_scheduled_task(self, task_name: str):
        """禁用计划任务
        
        Args:
            task_name: 任务名称
        
        Returns:
            tuple: (success: bool, message: str)
        """
        try:
            full_task_name = f"{self.task_folder}\\{task_name}"
            cmd = ['schtasks', '/Change', '/TN', full_task_name, '/DISABLE']
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                self.logger.info(f"成功禁用任务: {full_task_name}")
                return True, f"✓ 任务 '{task_name}' 已禁用"
            else:
                return False, f"✗ 禁用失败: {result.stderr}"
        except Exception as e:
            return False, f"✗ 异常: {str(e)}"
    
    def _create_task_xml(self, task_name: str, game_exe: str, task_command: str, trigger_time: str) -> str:
        """生成 Windows 任务计划的 XML 定义
        
        Args:
            task_name: 任务名称
            game_exe: 游戏执行文件路径
            task_command: 要执行的命令
            trigger_time: 触发时间（HH:MM 格式）
        
        Returns:
            str: XML 字符串
        """
        # 解析触发时间
        hours, minutes = trigger_time.split(':')
        
        xml_template = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Date>2026-03-04T00:00:00.0000000</Date>
    <Author>ok-end-field</Author>
    <Description>{task_name}</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <Repetition>
        <Interval>PT1D</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
      <StartBoundary>2026-03-04T{hours}:{minutes}:00</StartBoundary>
      <ExecutionTimeLimit>PT6H</ExecutionTimeLimit>
      <Enabled>true</Enabled>
      <ScheduleByDay>
        <DaysInterval>1</DaysInterval>
      </ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>S-1-5-21-0-0-0-1000</UserId>
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
    <IdleSettings>
      <Duration>PT10M</Duration>
      <WaitTimeout>PT1H</WaitTimeout>
      <StopOnIdleEnd>true</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT6H</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{game_exe}</Command>
      <Arguments></Arguments>
      <WorkingDirectory></WorkingDirectory>
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
