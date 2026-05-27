import os
import sys
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QListWidget, QStackedWidget, QLabel, QFrame, QPushButton, QGridLayout
from PySide6.QtCore import Qt

# Add current dir and parent to path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)
sys.path.insert(0, os.path.abspath(os.path.join(current_dir, "..")))

from app_state import AppState
from theme import QSS_THEME
from task_runner import TaskRunner

# Import Views
from views.order_zhuofang_view import OrderZhuofangView
from views.long_term_view import LongTermView
from views.period_compare_view import PeriodCompareView
from views.takeaway_view import TakeawayView

class SettingsView(QWidget):
    """
    A simple View showing settings and history of recent runs.
    """
    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        
        layout = QVBoxLayout(self)
        
        title_lbl = QLabel("系统设置与最近归档偏好", self)
        title_lbl.setObjectName("view_title")
        layout.addWidget(title_lbl)
        
        card = QFrame(self)
        card.setFrameShape(QFrame.StyledPanel)
        card.setObjectName("param_card")
        card.setStyleSheet("background-color: #1e1e1e; border: 1px solid #2d2d2d; border-radius: 4px; padding: 15px;")
        
        grid = QGridLayout(card)
        grid.setSpacing(10)
        
        grid.addWidget(QLabel("<b>配置文件路径:</b>"), 0, 0)
        grid.addWidget(QLabel(self.app_state.config_path), 0, 1)
        
        grid.addWidget(QLabel("<b>最近所选门店:</b>"), 1, 0)
        self.lbl_store = QLabel(self.app_state.get("recent_store", "-"))
        grid.addWidget(self.lbl_store, 1, 1)
        
        grid.addWidget(QLabel("<b>默认输出目录:</b>"), 2, 0)
        self.lbl_out = QLabel(self.app_state.get("default_output_dir", "-"))
        self.lbl_out.setWordWrap(True)
        grid.addWidget(self.lbl_out, 2, 1)
        
        grid.addWidget(QLabel("<b>默认 SQLite 库:</b>"), 3, 0)
        self.lbl_db = QLabel(self.app_state.get("default_db_path", "-"))
        self.lbl_db.setWordWrap(True)
        grid.addWidget(self.lbl_db, 3, 1)
        
        layout.addWidget(card)
        
        # Reset Preferences
        reset_btn = QPushButton("🧹 重置所有保存的偏好设置", self)
        reset_btn.setStyleSheet("background-color: #c0392b; border-color: #d35400; max-width: 250px; margin-top: 15px;")
        reset_btn.clicked.connect(self.reset_preferences)
        layout.addWidget(reset_btn)
        
        layout.addStretch()

    def reset_preferences(self):
        self.app_state.set("recent_dir", "")
        self.app_state.set("default_output_dir", "")
        self.app_state.set("default_db_path", "")
        self.app_state.set("recent_store", "万荷店")
        self.app_state.set("recent_period_mode", "week")
        self.lbl_store.setText("万荷店")
        self.lbl_out.setText("-")
        self.lbl_db.setText("-")

    def refresh(self):
        self.lbl_store.setText(self.app_state.get("recent_store", "-"))
        self.lbl_out.setText(self.app_state.get("default_output_dir", "-"))
        self.lbl_db.setText(self.app_state.get("default_db_path", "-"))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("金谷仓餐厅日常经营数据分析系统 控制台 v1.0")
        self.resize(1080, 800)
        
        self.app_state = AppState()
        self.active_runners = {} # maps feature to TaskRunner
        
        # Central widget and base layout
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        
        base_layout = QHBoxLayout(central_widget)
        base_layout.setSpacing(0)
        base_layout.setContentsMargins(0, 0, 0, 0)
        
        # Left side panel for navigation
        left_panel = QWidget(central_widget)
        left_panel.setStyleSheet("background-color: #1a1a1a;")
        left_panel.setFixedWidth(200)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        # Banner/Logo Area
        logo_area = QFrame(left_panel)
        logo_area.setStyleSheet("background-color: #1a1a1a; border-bottom: 1px solid #2d2d2d; padding: 15px;")
        logo_layout = QVBoxLayout(logo_area)
        logo_lbl = QLabel("🌾 金谷仓餐厅", logo_area)
        logo_lbl.setStyleSheet("font-size: 15px; font-weight: bold; color: #ffffff;")
        logo_lbl.setAlignment(Qt.AlignCenter)
        logo_layout.addWidget(logo_lbl)
        
        logo_sub = QLabel("数据分析控制台", logo_area)
        logo_sub.setStyleSheet("font-size: 11px; color: #888888;")
        logo_sub.setAlignment(Qt.AlignCenter)
        logo_layout.addWidget(logo_sub)
        
        left_layout.addWidget(logo_area)
        
        # Navigation Menu List
        self.nav_menu = QListWidget(left_panel)
        self.nav_menu.setObjectName("nav_menu")
        self.nav_menu.addItems([
            "订单+桌访合并",
            "长期订单分析",
            "周期对比分析",
            "平台外卖统计",
            "设置与偏好"
        ])
        self.nav_menu.setCurrentRow(0)
        self.nav_menu.currentRowChanged.connect(self.handle_nav_change)
        left_layout.addWidget(self.nav_menu)
        
        base_layout.addWidget(left_panel)
        
        # Right working area stacked widget
        self.stacked_widget = QStackedWidget(central_widget)
        
        # Create View instances
        self.v_order_zhuofang = OrderZhuofangView(self.app_state, self.stacked_widget)
        self.v_long_term = LongTermView(self.app_state, self.stacked_widget)
        self.v_period_compare = PeriodCompareView(self.app_state, self.stacked_widget)
        self.v_takeaway = TakeawayView(self.app_state, self.stacked_widget)
        self.v_settings = SettingsView(self.app_state, self.stacked_widget)
        
        # Connect run requests to central launcher
        self.v_order_zhuofang.run_requested.connect(lambda spec: self.start_task("order_zhuofang", spec, self.v_order_zhuofang))
        self.v_long_term.run_requested.connect(lambda spec: self.start_task("long_term", spec, self.v_long_term))
        self.v_period_compare.run_requested.connect(lambda spec: self.start_task("period_compare", spec, self.v_period_compare))
        self.v_takeaway.run_requested.connect(lambda spec: self.start_task("takeaway", spec, self.v_takeaway))
        
        # Add Views to stack
        self.stacked_widget.addWidget(self.v_order_zhuofang)
        self.stacked_widget.addWidget(self.v_long_term)
        self.stacked_widget.addWidget(self.v_period_compare)
        self.stacked_widget.addWidget(self.v_takeaway)
        self.stacked_widget.addWidget(self.v_settings)
        
        base_layout.addWidget(self.stacked_widget)

    def handle_nav_change(self, idx):
        self.stacked_widget.setCurrentIndex(idx)
        # Refresh settings in case they updated in other views
        if idx == 4:
            self.v_settings.refresh()
            
        # Re-trigger validation for active view to ensure they display correct status
        active_w = self.stacked_widget.currentWidget()
        if hasattr(active_w, "run_validation"):
            active_w.run_validation()

    def start_task(self, feature, task_spec, view_widget):
        """
        Launches the TaskRunner in the background
        """
        runner = TaskRunner(task_spec)
        if runner.is_locked():
            # Database path is currently locked
            view_widget.val_panel.set_messages([{
                "level": "error",
                "code": "db_locked",
                "message": f"操作拒绝：数据库 {os.path.basename(runner.db_path)} 正在被另一个后台任务写入，请稍后再试。",
                "file": runner.db_path,
                "suggestion": "等待另一个任务运行结束，或者手动终止另一个页面中的任务。"
            }])
            return
            
        # Clear previous logs in view console
        view_widget.log_panel.clear_log()
        
        # Connect signals
        runner.log_received.connect(view_widget.log_panel.append_text)
        runner.task_started.connect(lambda: self.on_task_started(feature, runner, view_widget))
        runner.task_finished.connect(lambda code, msg: self.on_task_finished(feature, code, msg, view_widget))
        
        # Connect stop button
        try:
            view_widget.log_panel.stop_clicked.disconnect()
        except RuntimeError:
            pass
        view_widget.log_panel.stop_clicked.connect(runner.cancel)
        
        # Run
        runner.run()

    def on_task_started(self, feature, runner, view_widget):
        self.active_runners[feature] = runner
        view_widget.log_panel.set_running(True)
        view_widget.run_btn.setEnabled(False)
        view_widget.drop_zone.setAcceptDrops(False)

    def on_task_finished(self, feature, exit_code, message, view_widget):
        if feature in self.active_runners:
            del self.active_runners[feature]
            
        view_widget.log_panel.set_running(False)
        view_widget.drop_zone.setAcceptDrops(True)
        view_widget.log_panel.append_text(f"\n{message}\n")
        
        # Re-enable validation and run buttons
        view_widget.run_validation()

    def closeEvent(self, event):
        # Clean shutdown of all running subprocesses
        for feature, runner in list(self.active_runners.items()):
            runner.cancel()
        event.accept()

def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(QSS_THEME)
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
