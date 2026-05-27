import os
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit, QPushButton, QFileDialog
from PySide6.QtCore import Signal

from widgets.drop_zone import DropZone
from widgets.file_list import FileListWidget
from widgets.validation_panel import ValidationPanel
from widgets.log_panel import LogPanel
from validators import scan_files, classify_files, validate_long_term

class LongTermView(QWidget):
    run_requested = Signal(dict)
    
    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.pos_files = []
        self.db_path = ""
        
        main_layout = QVBoxLayout(self)
        
        # View Title
        title_lbl = QLabel("长期订单趋势分析与归档", self)
        title_lbl.setObjectName("view_title")
        main_layout.addWidget(title_lbl)
        
        # Drop Zone
        self.drop_zone = DropZone("拖拽 多个 POS 订单 Excel 和 数据库到此处", self)
        self.drop_zone.files_dropped.connect(self.handle_files_dropped)
        main_layout.addWidget(self.drop_zone)
        
        # Selected File List
        self.file_list = FileListWidget(filter_exts=['.xlsx', '.xls', '.db', '.sqlite'], parent=self)
        self.file_list.files_updated.connect(self.handle_files_updated)
        main_layout.addWidget(self.file_list)
        
        # Parameters Card
        param_card = QWidget(self)
        param_card.setObjectName("param_card")
        param_card.setStyleSheet("background-color: #1e1e1e; border: 1px solid #2d2d2d; border-radius: 4px; padding: 8px;")
        param_layout = QGridLayout(param_card)
        
        # SQLite Database Path
        param_layout.addWidget(QLabel("SQLite 数据库路径:", param_card), 0, 0)
        self.db_path_edit = QLineEdit(param_card)
        default_db = self.app_state.get("default_db_path")
        if not default_db:
            default_db = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "长期订单分析", "output", "长期订单分析.db"))
        self.db_path_edit.setText(default_db)
        self.db_path_edit.textChanged.connect(self.save_preferences)
        param_layout.addWidget(self.db_path_edit, 0, 1)
        
        self.db_browse_btn = QPushButton("📁 选择数据库", param_card)
        self.db_browse_btn.clicked.connect(self.choose_db_file)
        param_layout.addWidget(self.db_browse_btn, 0, 2)
        
        # Output Dir
        param_layout.addWidget(QLabel("输出目录:", param_card), 1, 0)
        self.output_dir_edit = QLineEdit(param_card)
        default_out = self.app_state.get("default_output_dir")
        if not default_out:
            default_out = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "长期订单分析", "output"))
        self.output_dir_edit.setText(default_out)
        self.output_dir_edit.textChanged.connect(self.save_preferences)
        param_layout.addWidget(self.output_dir_edit, 1, 1)
        
        self.out_browse_btn = QPushButton("📁 浏览目录", param_card)
        self.out_browse_btn.clicked.connect(self.choose_output_dir)
        param_layout.addWidget(self.out_browse_btn, 1, 2)
        
        main_layout.addWidget(param_card)
        
        # Validation Panel
        self.val_panel = ValidationPanel(self)
        main_layout.addWidget(self.val_panel)
        
        # Run Controls Layout
        controls_layout = QHBoxLayout()
        self.run_btn = QPushButton("▶️ 生成长期趋势分析 Excel", self)
        self.run_btn.setObjectName("run_btn")
        self.run_btn.clicked.connect(self.trigger_run)
        controls_layout.addWidget(self.run_btn)
        
        self.open_output_btn = QPushButton("📂 打开输出目录", self)
        self.open_output_btn.clicked.connect(self.open_output_dir)
        controls_layout.addWidget(self.open_output_btn)
        
        controls_layout.addStretch()
        main_layout.addLayout(controls_layout)
        
        # Log Panel
        self.log_panel = LogPanel(self)
        main_layout.addWidget(self.log_panel)
        
        self.run_validation()

    def handle_files_dropped(self, paths):
        scanned = scan_files(paths)
        self.file_list.add_files(scanned)

    def handle_files_updated(self, paths):
        classified = classify_files(paths)
        self.pos_files = classified.get("pos_excel", [])
        
        dbs = classified.get("database", [])
        if dbs:
            self.db_path_edit.setText(dbs[0])
            
        self.run_validation()

    def run_validation(self):
        self.db_path = self.db_path_edit.text().strip()
        output_dir = self.output_dir_edit.text().strip()
        
        is_valid, messages = validate_long_term(self.pos_files, self.db_path, output_dir)
        
        # Additional Info
        if is_valid and self.pos_files:
            messages.append({
                "level": "info",
                "code": "lt_info",
                "message": f"预计导入 {len(self.pos_files)} 个 POS 文件进行批量增量写库并重新聚合趋势",
                "file": "",
                "suggestion": ""
            })
            
        self.val_panel.set_messages(messages)
        self.run_btn.setEnabled(is_valid)

    def choose_db_file(self):
        file_path, _ = QFileDialog.getSaveFileName(self, "选择 SQLite 数据库文件", self.db_path_edit.text(), "SQLite Databases (*.db *.sqlite)")
        if file_path:
            self.db_path_edit.setText(file_path)
            self.run_validation()

    def choose_output_dir(self):
        dir_path = QFileDialog.getExistingDirectory(self, "选择输出目录", self.output_dir_edit.text())
        if dir_path:
            self.output_dir_edit.setText(dir_path)
            self.run_validation()

    def open_output_dir(self):
        out_dir = self.output_dir_edit.text().strip()
        if os.path.exists(out_dir):
            os.system(f'open "{out_dir}"')

    def save_preferences(self):
        self.app_state.set("default_db_path", self.db_path_edit.text().strip())
        self.app_state.set("default_output_dir", self.output_dir_edit.text().strip())
        self.run_validation()

    def trigger_run(self):
        spec = {
            "feature": "long_term",
            "inputs": {
                "pos_files": self.pos_files,
                "db_path": self.db_path
            },
            "params": {
                "output_dir": self.output_dir_edit.text().strip()
            }
        }
        self.run_requested.emit(spec)
