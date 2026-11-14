import sys
import json
import os
import datetime
import winreg
import shutil
import ctypes
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QTabWidget, QListWidget, QListWidgetItem,
                             QCheckBox, QMessageBox, QDateTimeEdit,
                             QInputDialog, QMenu, QAction, QSplitter, QStyle,
                             QSystemTrayIcon, QMenu, QDialog, QTextBrowser,
                             QComboBox, QGraphicsOpacityEffect)
from PyQt5.QtCore import Qt, QDateTime, QTimer, QPoint, QThread, pyqtSignal, QCoreApplication
from PyQt5.QtGui import QFont, QIcon, QColor


def format_task_time(task):
    try:
        task_datetime = datetime.datetime.strptime(task.datetime_str, "%Y年%m月%d日%H时%M分")
        current_time = datetime.datetime.now()
        delta = task_datetime - current_time

        if delta.total_seconds() <= 0:
            return "(已到期)"

        total_seconds = int(delta.total_seconds())

        if total_seconds < 60:
            return f"剩余: {total_seconds}秒"
        else:
            days, remainder = divmod(total_seconds, 86400)
            hours, remainder = divmod(remainder, 3600)
            minutes, _ = divmod(remainder, 60)

            if days > 0:
                return f"剩余: {days}天"
            elif hours > 0:
                return f"剩余: {hours}小时{minutes}分钟"
            else:
                return f"剩余: {minutes}分钟"
    except Exception as e:
        print(f"格式化任务时间出错: {e}")
        return ""


class ReminderThread(QThread):
    reminder_triggered = pyqtSignal(str, str)
    expired_tasks_alert = pyqtSignal(list)

    def __init__(self, task_manager):
        super().__init__()
        self.task_manager = task_manager
        self.running = True
        self.triggered_tasks = set()
        self.later_time = 5 * 60
        self.viewed_expired_tasks = []

    def set_later_time(self, minutes):
        self.later_time = minutes * 60

    def check_expired_tasks(self):
        current_time = datetime.datetime.now()
        self.expired_tasks = []
        for task in self.task_manager.get_tasks('pending'):
            try:
                task_time = datetime.datetime.strptime(task.datetime_str, "%Y年%m月%d日%H时%M分")
                if task_time < current_time:
                    self.expired_tasks.append(task)
            except Exception as e:
                print(f"解析任务时间出错: {e}")

        for task in self.expired_tasks:
            if task not in self.triggered_tasks:
                self.reminder_triggered.emit(task.note, task.datetime_str)
                self.triggered_tasks.add(task)

    def run(self):
        while self.running:
            current_time = datetime.datetime.now()
            print(f"\n当前检查时间: {current_time.strftime('%Y-%m-%d %H:%M:%S')}")

            current_tasks = self.task_manager.get_tasks('pending')
            print(f"待检查任务数量: {len(current_tasks)}")

            for task in current_tasks:
                try:
                    task_time = datetime.datetime.strptime(task.datetime_str, "%Y年%m月%d日%H时%M分")
                    task_id = (task.datetime_str, task.note)
                    print(f"检查任务: {task.note} 时间: {task_time} ID: {task_id}")

                    if task_time <= current_time and task_id not in self.triggered_tasks:
                        print(f"触发提醒: {task.note}")
                        self.reminder_triggered.emit(task.note, task.datetime_str)
                        self.triggered_tasks.add(task_id)

                except Exception as e:
                    print(f"处理任务时出错: {e}")

            self.sleep(10)


class Task:
    def __init__(self, datetime_str, note, completed=False, cycle_type='none', day_type=None):
        self.datetime_str = datetime_str
        self.note = note
        self.completed = completed
        self.cycle_type = cycle_type          # 'none','daily','weekly','monthly','yearly'
        self.day_type = day_type              # 'first' or 'last' or None

    def to_dict(self):
        return {
            'datetime': self.datetime_str,
            'note': self.note,
            'completed': self.completed,
            'cycle_type': self.cycle_type,
            'day_type': self.day_type
        }

    @staticmethod
    def from_dict(data):
        return Task(
            data['datetime'],
            data['note'],
            data.get('completed', False),
            data.get('cycle_type', 'none'),
            data.get('day_type', None)        # 兼容旧数据
        )

    def get_next_time(self):
        if self.cycle_type == 'none':
            return None

        try:
            current_time = datetime.datetime.strptime(self.datetime_str, "%Y年%m月%d日%H时%M分")
        except Exception as e:
            print(f"解析任务时间出错: {e}")
            return None

        if self.cycle_type == 'daily':
            return current_time + datetime.timedelta(days=1)
        elif self.cycle_type == 'weekly':
            return current_time + datetime.timedelta(weeks=1)
        elif self.cycle_type == 'monthly':
            if self.day_type == 'first':
                # 下个月的第一天
                year = current_time.year
                month = current_time.month + 1
                if month > 12:
                    year += 1
                    month = 1
                return current_time.replace(year=year, month=month, day=1,
                                            hour=current_time.hour, minute=current_time.minute)
            elif self.day_type == 'last':
                # 下个月的最后一天
                year = current_time.year
                month = current_time.month + 1
                if month > 12:
                    year += 1
                    month = 1
                # 计算该月的最后一天
                if month == 12:
                    next_year = year + 1
                    next_month = 1
                else:
                    next_year = year
                    next_month = month + 1
                last_day = (datetime.datetime(next_year, next_month, 1) - datetime.timedelta(days=1)).day
                return current_time.replace(year=year, month=month, day=last_day,
                                            hour=current_time.hour, minute=current_time.minute)
            else:
                return Task.add_months(current_time, 1)
        elif self.cycle_type == 'yearly':
            if self.day_type == 'first':
                # 下一年的1月1日
                return current_time.replace(year=current_time.year + 1, month=1, day=1,
                                            hour=current_time.hour, minute=current_time.minute)
            elif self.day_type == 'last':
                # 下一年的12月31日
                return current_time.replace(year=current_time.year + 1, month=12, day=31,
                                            hour=current_time.hour, minute=current_time.minute)
            else:
                return current_time.replace(year=current_time.year + 1)
        return None

    @staticmethod
    def add_months(source_date, months):
        month = source_date.month - 1 + months
        year = source_date.year + month // 12
        month = month % 12 + 1
        day = source_date.day
        try:
            return source_date.replace(year=year, month=month, day=day)
        except ValueError:
            next_month = month + 1 if month < 12 else 1
            next_year = year if month < 12 else year + 1
            last_day = (datetime.datetime(next_year, next_month, 1) - datetime.timedelta(days=1)).day
            return source_date.replace(year=year, month=month, day=last_day)

    def get_next_occurrence(self, base_datetime=None):
        """根据基准时间（默认为当前时间）计算下一次周期发生的时间（≥基准时间）"""
        if base_datetime is None:
            base_datetime = datetime.datetime.now()
        # 原任务的时间（时分）
        orig_time = datetime.datetime.strptime(self.datetime_str, "%Y年%m月%d日%H时%M分")
        hour, minute = orig_time.hour, orig_time.minute

        if self.cycle_type == 'daily':
            candidate = base_datetime.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate < base_datetime:
                candidate += datetime.timedelta(days=1)
            return candidate

        elif self.cycle_type == 'weekly':
            target_weekday = orig_time.weekday()  # 原任务星期几
            days_ahead = target_weekday - base_datetime.weekday()
            if days_ahead < 0 or (days_ahead == 0 and base_datetime.time() >= orig_time.time()):
                days_ahead += 7
            candidate = base_datetime.replace(hour=hour, minute=minute, second=0, microsecond=0)
            candidate += datetime.timedelta(days=days_ahead)
            return candidate

        elif self.cycle_type == 'monthly':
            if self.day_type == 'first':
                candidate = base_datetime.replace(day=1, hour=hour, minute=minute, second=0, microsecond=0)
                if candidate < base_datetime:
                    # 下个月第一天
                    if candidate.month == 12:
                        candidate = candidate.replace(year=candidate.year + 1, month=1)
                    else:
                        candidate = candidate.replace(month=candidate.month + 1)
                return candidate
            elif self.day_type == 'last':
                # 当前月最后一天
                if base_datetime.month == 12:
                    next_year, next_month = base_datetime.year + 1, 1
                else:
                    next_year, next_month = base_datetime.year, base_datetime.month + 1
                last_day = (datetime.datetime(next_year, next_month, 1) - datetime.timedelta(days=1)).day
                candidate = base_datetime.replace(day=last_day, hour=hour, minute=minute, second=0, microsecond=0)
                if candidate < base_datetime:
                    # 下个月最后一天
                    if base_datetime.month == 12:
                        next_year2, next_month2 = base_datetime.year + 1, 1
                    else:
                        next_year2, next_month2 = base_datetime.year, base_datetime.month + 1
                    if next_month2 == 12:
                        temp = datetime.datetime(next_year2, next_month2, 1)
                    else:
                        temp = datetime.datetime(next_year2, next_month2, 1)
                    last_day_next = (temp + datetime.timedelta(days=32)).replace(day=1) - datetime.timedelta(days=1)
                    candidate = temp.replace(day=last_day_next.day, hour=hour, minute=minute, second=0, microsecond=0)
                return candidate
            else:
                target_day = orig_time.day
                # 当前月的该日
                try:
                    candidate = base_datetime.replace(day=target_day, hour=hour, minute=minute, second=0, microsecond=0)
                except ValueError:
                    # 该月无此日，取最后一天
                    if base_datetime.month == 12:
                        next_year, next_month = base_datetime.year + 1, 1
                    else:
                        next_year, next_month = base_datetime.year, base_datetime.month + 1
                    last_day = (datetime.datetime(next_year, next_month, 1) - datetime.timedelta(days=1)).day
                    candidate = base_datetime.replace(day=last_day, hour=hour, minute=minute, second=0, microsecond=0)
                if candidate < base_datetime:
                    # 下个月同一天
                    if base_datetime.month == 12:
                        next_year, next_month = base_datetime.year + 1, 1
                    else:
                        next_year, next_month = base_datetime.year, base_datetime.month + 1
                    try:
                        candidate = datetime.datetime(next_year, next_month, target_day, hour, minute)
                    except ValueError:
                        if next_month == 12:
                            next_year2, next_month2 = next_year + 1, 1
                        else:
                            next_year2, next_month2 = next_year, next_month + 1
                        last_day = (datetime.datetime(next_year2, next_month2, 1) - datetime.timedelta(days=1)).day
                        candidate = datetime.datetime(next_year, next_month, last_day, hour, minute)
                return candidate

        elif self.cycle_type == 'yearly':
            if self.day_type == 'first':
                candidate = base_datetime.replace(month=1, day=1, hour=hour, minute=minute, second=0, microsecond=0)
                if candidate < base_datetime:
                    candidate = candidate.replace(year=candidate.year + 1)
                return candidate
            elif self.day_type == 'last':
                candidate = base_datetime.replace(month=12, day=31, hour=hour, minute=minute, second=0, microsecond=0)
                if candidate < base_datetime:
                    candidate = candidate.replace(year=candidate.year + 1)
                return candidate
            else:
                target_month, target_day = orig_time.month, orig_time.day
                try:
                    candidate = base_datetime.replace(month=target_month, day=target_day, hour=hour, minute=minute,
                                                      second=0, microsecond=0)
                except ValueError:
                    if target_month == 12:
                        next_year, next_month = base_datetime.year + 1, 1
                    else:
                        next_year, next_month = base_datetime.year, target_month + 1
                    last_day = (datetime.datetime(next_year, next_month, 1) - datetime.timedelta(days=1)).day
                    candidate = base_datetime.replace(month=target_month, day=last_day, hour=hour, minute=minute,
                                                      second=0, microsecond=0)
                if candidate < base_datetime:
                    candidate = candidate.replace(year=candidate.year + 1)
                return candidate
        return None

class TaskManager:
    def __init__(self, file_path=None):
        if getattr(sys, 'frozen', False):
            self.base_dir = os.path.dirname(sys.executable)
        else:
            self.base_dir = os.path.dirname(os.path.abspath(__file__))

        self.file_path = file_path or os.path.join(self.base_dir, "tasks.json")
        self.tasks = []
        self.migrate_old_data()
        self.load_tasks()

    def migrate_old_data(self):
        old_path_cwd = os.path.join(os.getcwd(), "tasks.json")
        old_path_prog = os.path.join(self.base_dir, "tasks.json")

        if not os.path.exists(self.file_path):
            if os.path.exists(old_path_cwd):
                self.copy_data(old_path_cwd)
            elif os.path.exists(old_path_prog):
                self.copy_data(old_path_prog)

    def copy_data(self, source_path):
        try:
            shutil.copy2(source_path, self.file_path)
            print(f"迁移任务数据: {source_path} -> {self.file_path}")
        except Exception as e:
            print(f"迁移任务数据失败: {e}")

    def load_tasks(self):
        try:
            if os.path.exists(self.file_path):
                with open(self.file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.tasks = [Task.from_dict(task) for task in data]
                    print(f"从 {self.file_path} 加载了 {len(self.tasks)} 个任务")
                    self.sort_tasks()
        except Exception as e:
            print(f"加载任务出错: {e}")
            self.tasks = []

    def save_tasks(self):
        try:
            self.sort_tasks()
            with open(self.file_path, 'w', encoding='utf-8') as f:
                data = [task.to_dict() for task in self.tasks]
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存任务出错: {e}")

    def add_task(self, task):
        self.tasks.append(task)
        self.sort_tasks()
        self.save_tasks()

    def update_task(self, index, task):
        if 0 <= index < len(self.tasks):
            self.tasks[index] = task
            self.sort_tasks()
            self.save_tasks()

    def delete_task(self, index):
        if 0 <= index < len(self.tasks):
            del self.tasks[index]
            self.save_tasks()

    def toggle_task_status(self, index):
        if 0 <= index < len(self.tasks):
            self.tasks[index].completed = not self.tasks[index].completed
            self.sort_tasks()
            self.save_tasks()

    def get_tasks(self, filter_type='all'):
        if filter_type == 'pending':
            return [task for task in self.tasks if not task.completed]
        elif filter_type == 'completed':
            return [task for task in self.tasks if task.completed]
        return self.tasks

    def sort_tasks(self):
        self.tasks.sort(key=lambda x: (
            0 if not x.completed else 1,
            datetime.datetime.strptime(x.datetime_str, "%Y年%m月%d日%H时%M分") if x.datetime_str else datetime.datetime.max
        ))


class TaskWidget(QWidget):
    def __init__(self, task, index, parent=None):
        super().__init__(parent)
        self.task = task
        self.index = index
        self.init_ui()
        self.update_remaining_time()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_remaining_time)
        self.timer.start(1000)

    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        self.checkbox = QCheckBox()
        self.checkbox.setChecked(self.task.completed)
        self.checkbox.stateChanged.connect(self.on_checkbox_changed)

        main_content = QVBoxLayout()
        main_content.setSpacing(2)

        top_info = QHBoxLayout()
        top_info.setContentsMargins(0, 0, 0, 0)

        note_label = QLabel(self.task.note)
        note_label.setWordWrap(True)

        # 显示循环类型及 day_type
        if self.task.cycle_type != 'none':
            cycle_map = {
                'daily': "每天",
                'weekly': "每周",
                'monthly': "每月",
                'yearly': "每年"
            }
            cycle_text = cycle_map.get(self.task.cycle_type, "")
            if self.task.day_type == 'first':
                cycle_text += "(第一天)"
            elif self.task.day_type == 'last':
                cycle_text += "(最后一天)"
            cycle_label = QLabel(cycle_text)
            cycle_label.setStyleSheet("color: #666; font-size: 10px; margin-left: 5px;")
            top_info.addWidget(note_label)
            top_info.addWidget(cycle_label)
        else:
            top_info.addWidget(note_label)

        bottom_info = QHBoxLayout()
        datetime_label = QLabel(self.task.datetime_str)
        datetime_label.setStyleSheet("color: #666; font-size: 12px;")

        self.remaining_time_label = QLabel("")
        self.remaining_time_label.setStyleSheet("color: #006400; font-size: 12px;")

        if not self.task.completed:
            time_text = format_task_time(self.task)
            if "已到期" in time_text:
                note_label.setStyleSheet("color: red; font-weight: bold;")
                self.remaining_time_label.setStyleSheet("color: red; font-size: 12px;")
            self.remaining_time_label.setText(f"({time_text})")

        bottom_info.addWidget(datetime_label)
        bottom_info.addWidget(self.remaining_time_label)

        main_content.addLayout(top_info)
        main_content.addLayout(bottom_info)

        layout.addWidget(self.checkbox, 0)
        layout.addLayout(main_content, 1)

        self.setLayout(layout)

    def update_remaining_time(self):
        if not self.task.completed:
            time_text = format_task_time(self.task)
            if "已到期" in time_text:
                self.remaining_time_label.setStyleSheet("color: red; font-size: 12px;")
            else:
                self.remaining_time_label.setStyleSheet("color: #006400; font-size: 12px;")
            self.remaining_time_label.setText(f"({time_text})")

    def on_checkbox_changed(self, state):
        self.task.completed = state == Qt.Checked
        if self.parentWidget() and hasattr(self.parentWidget(), 'task_status_changed'):
            self.parentWidget().task_status_changed(self.index, self.task.completed)


class TaskListWidget(QListWidget):
    def __init__(self, task_manager, filter_type, main_window, parent=None):
        super().__init__(parent)
        self.task_manager = task_manager
        self.filter_type = filter_type
        self.main_window = main_window
        self.update_tasks()

        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

    def update_tasks(self):
        self.clear()
        tasks = self.task_manager.get_tasks(self.filter_type)

        if not tasks:
            self.addItem("没有待办事项")
            return

        for i, task in enumerate(tasks):
            item = QListWidgetItem()
            item.setSizeHint(TaskWidget(task, i).sizeHint())
            self.addItem(item)
            self.setItemWidget(item, TaskWidget(task, i, self))

    def task_status_changed(self, index, completed):
        tasks = self.task_manager.get_tasks(self.filter_type)
        if 0 <= index < len(tasks):
            original_index = self.task_manager.tasks.index(tasks[index])
            self.task_manager.toggle_task_status(original_index)
            self.update_tasks()
            if self.filter_type != 'all':
                self.parentWidget().update_all_lists()

    def show_context_menu(self, position):
        index = self.indexAt(position)
        if not index.isValid():
            return

        item = self.itemAt(position)
        if not item:
            return

        widget = self.itemWidget(item)
        if not widget:
            return

        menu = QMenu()
        edit_action = QAction("编辑", self)
        delete_action = QAction("删除", self)

        edit_action.triggered.connect(lambda: self.edit_task(widget.index))
        delete_action.triggered.connect(lambda: self.delete_task(widget.index))

        menu.addAction(edit_action)
        menu.addAction(delete_action)
        menu.exec_(self.mapToGlobal(position))

    def edit_task(self, index):
        tasks = self.task_manager.get_tasks(self.filter_type)
        if 0 <= index < len(tasks):
            original_index = self.task_manager.tasks.index(tasks[index])
            task = tasks[index]

            dialog = QDialog(self)
            dialog.setWindowTitle("编辑待办事项")
            layout = QVBoxLayout(dialog)

            datetime_layout = QHBoxLayout()
            datetime_label = QLabel("待办时间:")
            datetime_edit = QDateTimeEdit()
            datetime_edit.setDisplayFormat("yyyy年MM月dd日HH时mm分")
            try:
                task_datetime = datetime.datetime.strptime(task.datetime_str, "%Y年%m月%d日%H时%M分")
                datetime_edit.setDateTime(QDateTime(task_datetime))
            except Exception as e:
                print(f"解析日期时间出错: {e}")
                datetime_edit.setDateTime(QDateTime.currentDateTime())
            datetime_layout.addWidget(datetime_label)
            datetime_layout.addWidget(datetime_edit)

            note_layout = QHBoxLayout()
            note_label = QLabel("待办备注:")
            note_edit = QLineEdit()
            note_edit.setText(task.note)
            note_layout.addWidget(note_label)
            note_layout.addWidget(note_edit)

            # 循环类型 + 第一天/最后一天下拉
            cycle_layout = QHBoxLayout()
            cycle_label = QLabel("重复类型:")
            cycle_combo = QComboBox()
            cycle_combo.addItems(["不重复", "每天", "每周", "每月", "每年"])

            cycle_mapping = {
                "none": "不重复",
                "daily": "每天",
                "weekly": "每周",
                "monthly": "每月",
                "yearly": "每年"
            }
            current_cycle = cycle_mapping.get(task.cycle_type, "不重复")
            cycle_combo.setCurrentText(current_cycle)

            # 第一天/最后一天下拉
            day_type_label = QLabel("日期选项:")
            day_type_combo = QComboBox()
            day_type_combo.addItems(["第一天", "最后一天"])
            # 根据 task.day_type 设置当前项
            if task.day_type == 'first':
                day_type_combo.setCurrentText("第一天")
            elif task.day_type == 'last':
                day_type_combo.setCurrentText("最后一天")
            else:
                day_type_combo.setCurrentIndex(0)  # 默认第一天，但实际对于非每月/每年会被忽略

            # 联动：仅当 cycle_type 为 每月或每年 时启用 day_type_combo
            def on_cycle_changed():
                is_monthly_or_yearly = cycle_combo.currentText() in ("每月", "每年")
                day_type_combo.setEnabled(is_monthly_or_yearly)
                day_type_label.setEnabled(is_monthly_or_yearly)
                if not is_monthly_or_yearly:
                    day_type_combo.setCurrentIndex(0)  # 重置，但值不会被使用

            cycle_combo.currentTextChanged.connect(on_cycle_changed)
            # 初始设置
            on_cycle_changed()

            cycle_layout.addWidget(cycle_label)
            cycle_layout.addWidget(cycle_combo)
            cycle_layout.addWidget(day_type_label)
            cycle_layout.addWidget(day_type_combo)

            button_layout = QHBoxLayout()
            save_button = QPushButton("保存")
            cancel_button = QPushButton("取消")
            button_layout.addWidget(save_button)
            button_layout.addWidget(cancel_button)

            layout.addLayout(datetime_layout)
            layout.addLayout(note_layout)
            layout.addLayout(cycle_layout)
            layout.addLayout(button_layout)

            save_button.clicked.connect(dialog.accept)
            cancel_button.clicked.connect(dialog.reject)

            if dialog.exec_() == QDialog.Accepted:
                try:
                    new_datetime = datetime_edit.dateTime().toString("yyyy年MM月dd日HH时mm分")
                    new_note = note_edit.text().strip()
                    cycle_type = {
                        "不重复": "none",
                        "每天": "daily",
                        "每周": "weekly",
                        "每月": "monthly",
                        "每年": "yearly"
                    }[cycle_combo.currentText()]

                    # 获取 day_type（仅当 cycle_type 为 monthly/yearly 时有效）
                    day_type = None
                    if cycle_type in ('monthly', 'yearly'):
                        day_type = 'first' if day_type_combo.currentText() == "第一天" else 'last'

                    if not new_note:
                        QMessageBox.warning(dialog, "警告", "待办备注不能为空!")
                        return

                    current_time = datetime.datetime.now().strftime("%Y年%m月%d日%H时%M分")
                    if new_datetime < current_time:
                        QMessageBox.warning(dialog, "警告", "不能设置过去的时间!")
                        return

                    updated_task = Task(
                        new_datetime,
                        new_note,
                        task.completed,
                        cycle_type=cycle_type,
                        day_type=day_type
                    )
                    self.task_manager.update_task(original_index, updated_task)
                    self.update_tasks()
                    self.main_window.statusBar().showMessage(f"已更新待办事项: {new_note}", 3000)
                except Exception as e:
                    QMessageBox.critical(dialog, "错误", f"更新待办事项时出错: {str(e)}")
                    print(f"更新待办事项时出错: {e}")

    def delete_task(self, index):
        tasks = self.task_manager.get_tasks(self.filter_type)
        if 0 <= index < len(tasks):
            original_index = self.task_manager.tasks.index(tasks[index])
            reply = QMessageBox.question(
                self, '确认删除',
                f'确定要删除"{tasks[index].note}"吗?',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                try:
                    self.task_manager.delete_task(original_index)
                    self.update_tasks()
                    if self.main_window:
                        self.main_window.statusBar().showMessage("待办事项已删除", 3000)
                except Exception as e:
                    QMessageBox.critical(self, "错误", f"删除待办事项时出错: {str(e)}")
                    print(f"删除待办事项时出错: {e}")


class TaskScheduler:
    def __init__(self, main_window):
        self.main_window = main_window
        self.task_manager = main_window.task_manager
        self.reminder_thread = ReminderThread(self.task_manager)
        self.reminder_thread.reminder_triggered.connect(self.show_reminder)
        self.reminder_thread.expired_tasks_alert.connect(self.show_expired_alert)
        # 不再自动启动，改为显式调用 start_reminder()
        self.active_reminders = {}
        self.temp_tasks = set()

    def start_reminder(self):
        """启动后台提醒线程"""
        self.reminder_thread.start()

    def show_reminder(self, note, datetime_str):
        key = (note, datetime_str)

        reminder = QMessageBox()
        reminder.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Dialog)

        if key in self.active_reminders:
            try:
                self.active_reminders[key].close()
            except:
                pass
            del self.active_reminders[key]

        if self.main_window.isVisible():
            self.main_window.hide()

        reminder = QMessageBox(self.main_window)
        self.active_reminders[key] = reminder

        reminder.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Dialog | Qt.CustomizeWindowHint)
        reminder.setWindowTitle("喵来提醒")
        reminder.setText(f"待办事项提醒\n\n{note}\n时间：{datetime_str}")
        reminder.setIcon(QMessageBox.Information)

        later_button = QPushButton(f"稍后提醒({self.reminder_thread.later_time // 60}分钟)")
        later_button.clicked.connect(lambda: self.set_later_reminder(note, datetime_str, reminder))
        ok_button = QPushButton("知道啦")
        ok_button.clicked.connect(lambda: self.handle_reminder_close(note, datetime_str, reminder))

        reminder.addButton(later_button, QMessageBox.ActionRole)
        reminder.addButton(ok_button, QMessageBox.AcceptRole)

        reminder.exec_()

    def handle_reminder_close(self, note, datetime_str, reminder):
        key = (note, datetime_str)
        if key in self.active_reminders:
            del self.active_reminders[key]
        reminder.close()

        for task in self.task_manager.get_tasks('pending'):
            if task.note == note and task.datetime_str == datetime_str:
                if (note, datetime_str) in self.temp_tasks:
                    self.task_manager.delete_task(self.task_manager.tasks.index(task))
                    self.temp_tasks.remove((note, datetime_str))
                else:
                    if task.cycle_type == 'none':
                        index = self.task_manager.tasks.index(task)
                        self.task_manager.toggle_task_status(index)
                    else:
                        next_time = task.get_next_time()
                        if next_time:
                            task.datetime_str = next_time.strftime("%Y年%m月%d日%H时%M分")
                            self.task_manager.save_tasks()

                self.main_window.update_all_lists()
                break

        task_id = (datetime_str, note)
        if task_id in self.reminder_thread.triggered_tasks:
            self.reminder_thread.triggered_tasks.remove(task_id)

    def mark_task_as_completed(self, note, datetime_str):
        for task in self.task_manager.get_tasks('pending'):
            if task.note == note and task.datetime_str == datetime_str:
                if task.cycle_type == 'none':
                    index = self.task_manager.tasks.index(task)
                    self.task_manager.toggle_task_status(index)
                else:
                    next_time = task.get_next_time()
                    if next_time:
                        task.datetime_str = next_time.strftime("%Y年%m月%d日%H时%M分")
                        self.task_manager.save_tasks()

                self.main_window.update_all_lists()
                break

        task_id = (datetime_str, note)
        if task_id in self.reminder_thread.triggered_tasks:
            self.reminder_thread.triggered_tasks.remove(task_id)

    def set_later_reminder(self, note, datetime_str, reminder):
        key = (note, datetime_str)
        if key in self.active_reminders:
            del self.active_reminders[key]
        reminder.close()

        QApplication.processEvents()

        dialog = QInputDialog(self.main_window)
        dialog.setWindowFlags(dialog.windowFlags() | Qt.WindowStaysOnTopHint)
        dialog.setInputMode(QInputDialog.IntInput)
        dialog.setIntMinimum(1)
        dialog.setIntMaximum(1440)
        dialog.setIntValue(self.reminder_thread.later_time // 60)
        dialog.setLabelText("请输入分钟数:")
        dialog.setWindowTitle("设置稍后提醒")

        self.main_window.activateWindow()
        self.main_window.raise_()

        ok = dialog.exec_()
        minutes = dialog.intValue() if ok else None

        if ok and minutes is not None:
            original_task = None
            for task in self.task_manager.get_tasks('pending'):
                if task.note == note and task.datetime_str == datetime_str:
                    original_task = task
                    break

            if original_task:
                new_time = datetime.datetime.now() + datetime.timedelta(minutes=minutes)
                new_datetime_str = new_time.strftime("%Y年%m月%d日%H时%M分")

                temp_task = Task(
                    new_datetime_str,
                    f"{note} (临时提醒)",
                    completed=False,
                    cycle_type='none'
                )
                self.task_manager.add_task(temp_task)
                self.temp_tasks.add((f"{note} (临时提醒)", new_datetime_str))

                if original_task.cycle_type != 'none':
                    next_time = original_task.get_next_time()
                    if next_time:
                        original_task.datetime_str = next_time.strftime("%Y年%m月%d日%H时%M分")
                        if (datetime_str, note) in self.reminder_thread.triggered_tasks:
                            self.reminder_thread.triggered_tasks.remove((datetime_str, note))
                        self.reminder_thread.triggered_tasks.add((original_task.datetime_str, note))

                self.task_manager.save_tasks()
                self.main_window.update_all_lists()
                self.main_window.statusBar().showMessage(f"已设置稍后提醒: {note}", 3000)

    def show_expired_alert(self, tasks):
        self.reminder_thread.viewed_expired_tasks.extend([task[1] for task in tasks])

        dialog = QDialog(self.main_window)
        dialog.setWindowTitle("过期待办事项提醒")
        layout = QVBoxLayout(dialog)

        text_browser = QTextBrowser()
        text = ""
        for note, time in tasks:
            text += f"• {note} ({time})\n"
        text_browser.setText("以下待办事项已过期：\n" + text)

        ok_button = QPushButton("确定")
        ok_button.clicked.connect(dialog.close)

        layout.addWidget(text_browser)
        layout.addWidget(ok_button)
        dialog.exec_()


class FloatingWindow(QWidget):
    def __init__(self, task_manager, parent=None):
        super().__init__(parent)
        self.task_manager = task_manager
        self.is_top = True
        self.setWindowTitle("待办事项悬浮窗")
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet("background-color: rgba(255, 255, 255, 220); border-radius: 10px;")
        self.setMinimumSize(300, 200)
        self.init_ui()
        self.update_tasks()

        self.opacity_effect = QGraphicsOpacityEffect()
        self.setGraphicsEffect(self.opacity_effect)
        self.opacity_effect.setOpacity(0.9)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_tasks)
        self.timer.start(1000)

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        title_layout = QHBoxLayout()
        title_label = QLabel("待办事项")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold;")

        self.top_button = QPushButton("置顶")
        self.top_button.setStyleSheet("""
            QPushButton {
                font-size: 12px;
                border: none;
                background-color: transparent;
                color: #666;
            }
            QPushButton:hover {
                color: #333;
            }
        """)
        self.top_button.clicked.connect(self.toggle_top)

        title_layout.addWidget(title_label)
        title_layout.addStretch()
        title_layout.addWidget(self.top_button)
        layout.addLayout(title_layout)

        self.task_list = QListWidget()
        self.task_list.setStyleSheet("""
            QListWidget {
                background-color: transparent;
                border: none;
                font-size: 14px;
            }
            QListWidget::item {
                padding: 6px;
                border-bottom: 1px solid rgba(0, 0, 0, 10);
            }
        """)
        layout.addWidget(self.task_list)

        close_button = QPushButton("×")
        close_button.setStyleSheet("""
            QPushButton {
                font-size: 20px;
                border: none;
                background-color: transparent;
                color: #666;
            }
            QPushButton:hover {
                color: #333;
            }
        """)
        close_button.clicked.connect(self.hide)
        layout.addWidget(close_button, alignment=Qt.AlignRight)

        self.setMouseTracking(True)

    def toggle_top(self):
        self.is_top = not self.is_top
        if self.is_top:
            self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
            self.top_button.setText("置顶")
        else:
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowStaysOnTopHint)
            self.top_button.setText("取消置顶")
        self.show()

    def update_tasks(self):
        self.task_list.clear()
        pending_tasks = self.task_manager.get_tasks('pending')

        if not pending_tasks:
            self.task_list.addItem("没有待办事项")
            return

        for task in pending_tasks:
            time_text = format_task_time(task)
            item_text = f"{task.note} - {time_text}"
            self.task_list.addItem(item_text)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton:
            self.move(event.globalPos() - self.drag_position)
            event.accept()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.task_manager = TaskManager()
        self.ensure_data_directory()

        self.floating_window = None
        self.task_scheduler = TaskScheduler(self)
        self.auto_start_enabled = self.check_auto_start()

        self.init_ui()
        self.init_tray()

        self.is_startup = len(sys.argv) > 1 and sys.argv[1] == "--startup"

        self.setWindowTitle("喵来提醒 - 版权所有 © 爱吃蟹黄先生")
        self.setGeometry(100, 100, 600, 500)

        if self.is_startup:
            self.hide()
            QTimer.singleShot(1000, self.show_startup_notification)
        else:
            self.show()

        icon_path = os.path.abspath("application-note.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            self.tray_icon.setIcon(QIcon(icon_path))
        else:
            print(f"警告: 找不到图标文件 {icon_path}")

        # 先处理开机合并提醒，再启动后台线程
        self.handle_startup_reminders()
        self.task_scheduler.start_reminder()

        # 原有的一次性过期检查（已过滤循环任务）
        self.check_expired_tasks_on_start()

    def show_startup_notification(self):
        self.tray_icon.showMessage(
            "喵来提醒",
            "程序已在后台运行",
            QSystemTrayIcon.Information,
            3000
        )

    def ensure_data_directory(self):
        data_dir = os.path.dirname(self.task_manager.file_path)
        if not os.path.exists(data_dir):
            try:
                os.makedirs(data_dir)
                print(f"创建数据目录: {data_dir}")
            except Exception as e:
                print(f"创建数据目录失败: {e}")

    def init_tray(self):
        icon_path = os.path.abspath("application-note.ico")
        if os.path.exists(icon_path):
            try:
                self.tray_icon = QSystemTrayIcon(QIcon(icon_path), self)
            except Exception as e:
                print(f"加载自定义图标出错: {e}")
                self.tray_icon = QSystemTrayIcon(self.style().standardIcon(QStyle.SP_ComputerIcon))
        else:
            self.tray_icon = QSystemTrayIcon(self.style().standardIcon(QStyle.SP_ComputerIcon))

        self.tray_icon.setToolTip("喵来提醒")
        self.tray_icon.activated.connect(self.on_tray_activated)

        tray_menu = QMenu()
        show_action = QAction("显示主窗口", self)
        quit_action = QAction("退出", self)
        settings_action = QAction("设置稍后提醒时间", self)

        show_action.triggered.connect(self.show_main_window)
        quit_action.triggered.connect(self.quit_app)
        settings_action.triggered.connect(self.settings_later_time)

        tray_menu.addAction(show_action)
        tray_menu.addAction(settings_action)
        tray_menu.addSeparator()
        tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(tray_menu)

        QTimer.singleShot(1000, self.tray_icon.show)

    def show_main_window(self):
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self.showNormal()

    def settings_later_time(self):
        minutes, ok = QInputDialog.getInt(self, "默认稍后提醒",
                                          "请设置默认稍后提醒分钟数:",
                                          self.task_scheduler.reminder_thread.later_time // 60, 1, 1440)
        if ok:
            self.task_scheduler.reminder_thread.set_later_time(minutes)

    def quit_app(self):
        self.task_scheduler.reminder_thread.running = False
        self.task_scheduler.reminder_thread.wait()
        self.tray_icon.hide()
        QCoreApplication.quit()

    def check_expired_tasks_on_start(self):
        current_time = datetime.datetime.now()
        expired_tasks = []
        for task in self.task_manager.get_tasks('pending'):
            if task.cycle_type != 'none':  # 循环任务由合并逻辑处理
                continue
            try:
                task_time = datetime.datetime.strptime(task.datetime_str, "%Y年%m月%d日%H时%M分")
                if task_time < current_time:
                    expired_tasks.append((task.note, task.datetime_str))
            except Exception as e:
                print(f"解析任务时间出错: {e}")
        if expired_tasks:
            self.task_scheduler.show_expired_alert(expired_tasks)

    def create_menu_bar(self):
        menubar = self.menuBar()
        settings_menu = menubar.addMenu("设置")

        self.auto_start_action = QAction("开机自启动", self, checkable=True)
        self.auto_start_action.setChecked(self.auto_start_enabled)
        self.auto_start_action.triggered.connect(self.toggle_auto_start)
        settings_menu.addAction(self.auto_start_action)

        settings_menu.addSeparator()
        settings_later_action = QAction("设置默认稍后提醒时间", self)
        settings_later_action.triggered.connect(self.settings_later_time)
        settings_menu.addAction(settings_later_action)

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)

        self.create_menu_bar()

        # 时间输入部分
        time_input_widget = QWidget()
        time_layout = QHBoxLayout(time_input_widget)
        time_layout.setContentsMargins(0, 0, 0, 0)

        datetime_label = QLabel("待办时间:")
        self.datetime_edit = QDateTimeEdit()
        self.datetime_edit.setDisplayFormat("yyyy年MM月dd日HH时mm分")
        self.datetime_edit.setDateTime(QDateTime.currentDateTime())
        self.current_time_button = QPushButton("获取当前时间")
        self.current_time_button.clicked.connect(self.set_current_time)

        # 悬浮窗按钮
        self.floating_button = QPushButton("显示悬浮窗")
        self.floating_button.clicked.connect(self.toggle_floating_window)
        self.floating_button.setStyleSheet("""
            QPushButton {
                background-color: #f0f0f0;
                border: 1px solid #ccc;
                padding: 5px;
            }
        """)

        time_layout.addWidget(datetime_label)
        time_layout.addWidget(self.datetime_edit, 1)
        time_layout.addWidget(self.current_time_button)
        time_layout.addWidget(self.floating_button)

        # 备注与添加部分（包含重复类型和第一天/最后一天）
        note_input_widget = QWidget()
        note_layout = QHBoxLayout(note_input_widget)
        note_layout.setContentsMargins(0, 0, 0, 0)

        note_label = QLabel("待办备注:")
        self.note_edit = QLineEdit()

        add_button = QPushButton("添加")
        add_button.clicked.connect(self.add_task)

        cycle_label = QLabel("重复类型:")
        self.cycle_combo = QComboBox()
        self.cycle_combo.addItems(["不重复", "每天", "每周", "每月", "每年"])

        # 新增：第一天/最后一天下拉
        day_type_label = QLabel("日期选项:")
        self.day_type_combo = QComboBox()
        self.day_type_combo.addItems(["第一天", "最后一天"])
        # 仅当月/年时启用
        self.day_type_combo.setEnabled(False)
        day_type_label.setEnabled(False)

        # 联动：切换重复类型时启用/禁用 day_type_combo
        def on_cycle_changed(text):
            is_monthly_or_yearly = text in ("每月", "每年")
            self.day_type_combo.setEnabled(is_monthly_or_yearly)
            day_type_label.setEnabled(is_monthly_or_yearly)
            if not is_monthly_or_yearly:
                self.day_type_combo.setCurrentIndex(0)  # 重置，但值不会被使用

        self.cycle_combo.currentTextChanged.connect(on_cycle_changed)

        note_layout.addWidget(note_label)
        note_layout.addWidget(self.note_edit, 1)
        note_layout.addWidget(cycle_label)
        note_layout.addWidget(self.cycle_combo)
        note_layout.addWidget(day_type_label)
        note_layout.addWidget(self.day_type_combo)
        note_layout.addWidget(add_button)

        # 任务标签页
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabPosition(QTabWidget.West)

        self.pending_list = TaskListWidget(self.task_manager, 'pending', self)
        self.completed_list = TaskListWidget(self.task_manager, 'completed', self)
        self.all_list = TaskListWidget(self.task_manager, 'all', self)

        self.tab_widget.addTab(self.pending_list, "待处理")
        self.tab_widget.addTab(self.completed_list, "已完成")
        self.tab_widget.addTab(self.all_list, "全部事项")

        self.tab_widget.currentChanged.connect(self.tab_changed)

        main_layout.addWidget(time_input_widget)
        main_layout.addWidget(note_input_widget)
        main_layout.addWidget(self.tab_widget, 1)

        self.statusBar().showMessage("就绪")

    def toggle_auto_start(self, checked):
        self.auto_start_enabled = checked
        if checked:
            self.add_to_startup()
        else:
            self.remove_from_startup()
        self.save_auto_start_setting(checked)

    def check_auto_start(self):
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r"Software\Microsoft\Windows\CurrentVersion\Run",
                                 0, winreg.KEY_READ)
            value, _ = winreg.QueryValueEx(key, "MiaoReminder")
            winreg.CloseKey(key)
            return True
        except WindowsError:
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                     r"Software\MiaoReminder\Settings",
                                     0, winreg.KEY_READ)
                value, _ = winreg.QueryValueEx(key, "AutoStart")
                winreg.CloseKey(key)
                return bool(value)
            except WindowsError:
                self.save_auto_start_setting(True)
                return True

    def save_auto_start_setting(self, enabled):
        try:
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\MiaoReminder\Settings")
            winreg.SetValueEx(key, "AutoStart", 0, winreg.REG_DWORD, int(enabled))
            winreg.CloseKey(key)
        except WindowsError as e:
            print(f"保存开机自启动设置失败: {e}")

    def add_to_startup(self):
        try:
            if getattr(sys, 'frozen', False):
                exe_path = sys.executable
            else:
                exe_path = os.path.abspath(sys.argv[0])

            try:
                buf = ctypes.create_unicode_buffer(260)
                ctypes.windll.kernel32.GetShortPathNameW(exe_path, buf, 260)
                exe_path = buf.value
            except:
                pass

            startup_cmd = f'"{exe_path}" --startup'

            with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Run",
                    0,
                    winreg.KEY_ALL_ACCESS
            ) as key:
                winreg.SetValueEx(key, "MiaoReminder", 0, winreg.REG_SZ, startup_cmd)

            self.auto_start_action.setChecked(True)
            self.statusBar().showMessage("已设置开机自启动", 3000)
        except Exception as e:
            QMessageBox.warning(self, "警告", f"设置开机自启动失败: {str(e)}")
            print(f"设置开机自启动失败: {str(e)}")

    def remove_from_startup(self):
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_WRITE
            )
            try:
                winreg.DeleteValue(key, "MiaoReminder")
                self.auto_start_action.setChecked(False)
                self.statusBar().showMessage("已取消开机自启动", 3000)
            except WindowsError as e:
                if e.winerror == 2:
                    self.auto_start_action.setChecked(False)
                    self.statusBar().showMessage("开机自启动未设置", 3000)
                else:
                    raise e
            finally:
                winreg.CloseKey(key)
        except WindowsError as e:
            QMessageBox.warning(self, "警告", f"取消开机自启动失败: {str(e)}")

    def toggle_floating_window(self):
        if self.floating_window and self.floating_window.isVisible():
            self.floating_window.hide()
        else:
            if not self.floating_window:
                self.floating_window = FloatingWindow(self.task_manager)
                screen_geometry = QApplication.desktop().availableGeometry()
                x = screen_geometry.width() - self.floating_window.width() - 20
                y = screen_geometry.height() - self.floating_window.height() - 20
                self.floating_window.move(x, y)
            self.floating_window.show()

    def set_current_time(self):
        current_time = QDateTime.currentDateTime()
        self.datetime_edit.setDateTime(current_time)

    def add_task(self):
        datetime_str = self.datetime_edit.dateTime().toString("yyyy年MM月dd日HH时mm分")
        note = self.note_edit.text().strip()
        cycle_type = {
            "不重复": "none",
            "每天": "daily",
            "每周": "weekly",
            "每月": "monthly",
            "每年": "yearly"
        }[self.cycle_combo.currentText()]

        # 获取 day_type（仅当 cycle_type 为 monthly/yearly 时有效）
        day_type = None
        if cycle_type in ('monthly', 'yearly'):
            day_type = 'first' if self.day_type_combo.currentText() == "第一天" else 'last'

        if not note:
            QMessageBox.warning(self, "警告", "待办备注不能为空!")
            return

        current_time = datetime.datetime.now().strftime("%Y年%m月%d日%H时%M分")
        if datetime_str < current_time:
            QMessageBox.warning(self, "警告", "不能设置过去的时间!")
            return

        task = Task(datetime_str, note, cycle_type=cycle_type, day_type=day_type)
        self.task_manager.add_task(task)

        self.note_edit.clear()
        self.datetime_edit.setDateTime(QDateTime.currentDateTime())
        self.cycle_combo.setCurrentText("不重复")
        self.day_type_combo.setCurrentIndex(0)      # 重置为第一天

        self.update_all_lists()
        self.statusBar().showMessage(f"已添加待办事项: {note}", 3000)

    def tab_changed(self, index):
        self.update_all_lists()

    def update_all_lists(self):
        self.task_manager.sort_tasks()
        self.pending_list.update_tasks()
        self.completed_list.update_tasks()
        self.all_list.update_tasks()
        QApplication.processEvents()

    def closeEvent(self, event):
        if self.tray_icon.isVisible():
            self.hide()
            event.ignore()
        else:
            self.task_scheduler.reminder_thread.running = False
            self.task_scheduler.reminder_thread.quit()
            self.task_scheduler.reminder_thread.wait(1000)
            super().closeEvent(event)

    def handle_startup_reminders(self):
        """开机时处理所有过期的循环任务，合并提醒并更新下次时间"""
        current_time = datetime.datetime.now()
        expired_recurring = []
        for task in self.task_manager.get_tasks('pending'):
            if task.cycle_type != 'none':
                try:
                    task_time = datetime.datetime.strptime(task.datetime_str, "%Y年%m月%d日%H时%M分")
                    if task_time < current_time:
                        expired_recurring.append(task)
                except:
                    pass

        if not expired_recurring:
            return

        # 按 note 分组
        groups = {}
        for task in expired_recurring:
            groups.setdefault(task.note, []).append(task)

        # 准备汇总信息
        summary_lines = []
        for note, tasks in groups.items():
            expired_times = [t.datetime_str for t in tasks]
            # 更新每个任务至下一次发生时间
            for t in tasks:
                new_time = t.get_next_occurrence(current_time)
                if new_time:
                    t.datetime_str = new_time.strftime("%Y年%m月%d日%H时%M分")
            # 加入汇总
            summary_lines.append(f"• {note}：")
            summary_lines.extend(f"  {t}" for t in expired_times)

        self.task_manager.save_tasks()
        self.update_all_lists()

        # 显示合并提醒对话框
        if summary_lines:
            self.show_merged_reminder_dialog("\n".join(summary_lines))

    def show_merged_reminder_dialog(self, detail_text):
        """显示合并提醒对话框"""
        dialog = QDialog(self)
        dialog.setWindowTitle("喵来提醒 - 重复事项汇总")
        dialog.setWindowFlags(dialog.windowFlags() | Qt.WindowStaysOnTopHint)
        layout = QVBoxLayout(dialog)

        label = QLabel("以下重复事项在您关机期间多次到期，已自动更新为下一次提醒时间：")
        label.setWordWrap(True)
        layout.addWidget(label)

        text_browser = QTextBrowser()
        text_browser.setText(detail_text)
        layout.addWidget(text_browser)

        ok_button = QPushButton("确定")
        ok_button.clicked.connect(dialog.accept)
        layout.addWidget(ok_button)

        dialog.exec_()

if __name__ == "__main__":
    # 设置应用程序信息
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(u'MiaoReminder.App')

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("喵来提醒")
    app.setApplicationDisplayName("喵来提醒")
    app.setWindowIcon(QIcon("application-note.ico"))

    font = QFont("Microsoft YaHei", 9)
    app.setFont(font)

    # 确保只运行一个实例
    mutex_id = '喵来提醒_9f5b5d5c-7d7a-4dca-9b6a-8c15b4f3d9a1'
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, mutex_id)
    if mutex:
        last_error = ctypes.windll.kernel32.GetLastError()
        if last_error == 183:
            try:
                QMessageBox.information(None, "提示", "喵来提醒已经在运行中")
            except:
                pass
            sys.exit(0)

    app.setStyle('Fusion')

    window = MainWindow()
    sys.exit(app.exec_())