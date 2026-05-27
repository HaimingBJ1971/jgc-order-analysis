import os
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QComboBox, QLineEdit, QPushButton, QFileDialog
from PySide6.QtCore import Signal

from widgets.drop_zone import DropZone
from widgets.file_list import FileListWidget
from widgets.validation_panel import ValidationPanel
from widgets.log_panel import LogPanel
from validators import scan_files, classify_files, validate_order_zhuofang

class OrderZhuofangView(QWidget):
    run_requested = Signal(dict) # Emits TaskSpec dict
    
    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.pos_files = []
        self.table_csv = None
        
        main_layout = QVBoxLayout(self)
        
        # View Title
        title_lbl = QLabel("订单与桌访数据合并分析", self)
        title_lbl.setObjectName("view_title")
        main_layout.addWidget(title_lbl)
        
        # Drop Zone
        self.drop_zone = DropZone("拖拽 POS 订单 Excel 和 桌访 CSV 到此处", self)
        self.drop_zone.files_dropped.connect(self.handle_files_dropped)
        main_layout.addWidget(self.drop_zone)
        
        # Selected File List
        self.file_list = FileListWidget(filter_exts=['.xlsx', '.xls', '.csv'], parent=self)
        self.file_list.files_updated.connect(self.handle_files_updated)
        main_layout.addWidget(self.file_list)
        
        # Parameters Card
        param_card = QWidget(self)
        param_card.setObjectName("param_card")
        param_card.setStyleSheet("background-color: #1e1e1e; border: 1px solid #2d2d2d; border-radius: 4px; padding: 8px;")
        param_layout = QGridLayout(param_card)
        
        # Store Preference
        param_layout.addWidget(QLabel("选择门店:", param_card), 0, 0)
        self.store_combo = QComboBox(param_card)
        self.store_combo.addItems(["自动推断", "万荷店", "保利店", "湾里店"])
        self.store_combo.setCurrentText(self.app_state.get("recent_store", "万荷店"))
        self.store_combo.currentTextChanged.connect(self.save_preferences)
        param_layout.addWidget(self.store_combo, 0, 1)
        
        # Output Dir
        param_layout.addWidget(QLabel("输出目录:", param_card), 1, 0)
        self.output_dir_edit = QLineEdit(param_card)
        default_out = self.app_state.get("default_output_dir")
        if not default_out:
            default_out = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "订单桌访合并", "output"))
        self.output_dir_edit.setText(default_out)
        self.output_dir_edit.textChanged.connect(self.save_preferences)
        param_layout.addWidget(self.output_dir_edit, 1, 1)
        
        self.browse_btn = QPushButton("📁 浏览", param_card)
        self.browse_btn.clicked.connect(self.choose_output_dir)
        param_layout.addWidget(self.browse_btn, 1, 2)
        
        main_layout.addWidget(param_card)
        
        # Validation Panel
        self.val_panel = ValidationPanel(self)
        main_layout.addWidget(self.val_panel)
        
        # Run Controls Layout
        controls_layout = QHBoxLayout()
        self.run_btn = QPushButton("▶️ 生成订单桌访报告", self)
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
        # Classify the files
        classified = classify_files(paths)
        self.pos_files = classified.get("pos_excel", [])
        
        csvs = classified.get("table_csv", [])
        if csvs:
            self.table_csv = csvs[0]
        else:
            self.table_csv = None
            
        self.run_validation()

    def run_validation(self):
        output_dir = self.output_dir_edit.text().strip()
        is_valid, messages = validate_order_zhuofang(self.pos_files, [self.table_csv] if self.table_csv else [], output_dir)
        
        self.val_panel.set_messages(messages)
        self.run_btn.setEnabled(is_valid)

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
        self.app_state.set("default_output_dir", self.output_dir_edit.text().strip())
        self.app_state.set("recent_store", self.store_combo.currentText())
        self.run_validation()

    def trigger_run(self):
        store = self.store_combo.currentText()
        if store == "自动推断":
            store = None
            
        spec = {
            "feature": "order_zhuofang",
            "inputs": {
                "pos_files": self.pos_files,
                "zhuofang_csv": self.table_csv
            },
            "params": {
                "store": store,
                "output_dir": self.output_dir_edit.text().strip()
            }
        }
        self.run_requested.emit(spec)
