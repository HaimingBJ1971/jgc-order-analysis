import os
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem, QPushButton, QLabel, QFileDialog
from PySide6.QtCore import Signal, Qt

class FileListWidget(QWidget):
    files_updated = Signal(list)  # Emits complete list of absolute file paths
    
    def __init__(self, filter_exts=None, parent=None):
        """
        filter_exts: list of allowed extensions (e.g. ['.xlsx', '.csv', '.db'])
        """
        super().__init__(parent)
        self.filter_exts = filter_exts or []
        self.file_paths = []
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Header layout
        hdr_layout = QHBoxLayout()
        self.title_label = QLabel("已选文件列表", self)
        self.title_label.setStyleSheet("font-weight: bold; color: #a0a0a0;")
        hdr_layout.addWidget(self.title_label)
        
        hdr_layout.addStretch()
        
        self.select_btn = QPushButton("📂 手动选择", self)
        self.select_btn.clicked.connect(self.choose_files)
        hdr_layout.addWidget(self.select_btn)
        
        self.clear_btn = QPushButton("🗑 清空", self)
        self.clear_btn.setStyleSheet("background-color: #7f8c8d; border-color: #95a5a6;")
        self.clear_btn.clicked.connect(self.clear_files)
        hdr_layout.addWidget(self.clear_btn)
        
        layout.addLayout(hdr_layout)
        
        # List Widget
        self.list_widget = QListWidget(self)
        self.list_widget.setObjectName("file_list_widget")
        self.list_widget.setStyleSheet("""
            QListWidget {
                background-color: #1e1e1e;
                border: 1px solid #2d2d2d;
                border-radius: 4px;
                min-height: 80px;
                max-height: 150px;
            }
            QListWidget::item {
                border-bottom: 1px solid #2a2a2a;
                padding: 6px;
            }
        """)
        layout.addWidget(self.list_widget)

    def add_files(self, paths):
        for p in paths:
            p = os.path.abspath(p)
            if p not in self.file_paths:
                # Optional extension filter
                if self.filter_exts:
                    ext = os.path.splitext(p)[1].lower()
                    if ext not in self.filter_exts:
                        continue
                self.file_paths.append(p)
                
        self.refresh_list()
        self.files_updated.emit(self.file_paths)

    def clear_files(self):
        self.file_paths.clear()
        self.refresh_list()
        self.files_updated.emit(self.file_paths)

    def choose_files(self):
        filter_str = "All Files (*)"
        if self.filter_exts:
            ext_patterns = " ".join(f"*{e}" for e in self.filter_exts)
            filter_str = f"Allowed Files ({ext_patterns});;All Files (*)"
            
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择输入文件", "", filter_str
        )
        if files:
            self.add_files(files)

    def refresh_list(self):
        self.list_widget.clear()
        for p in self.file_paths:
            basename = os.path.basename(p)
            size_kb = os.path.getsize(p) / 1024.0 if os.path.exists(p) else 0.0
            
            # Subtitle or extra details
            item_text = f"{basename}  ({size_kb:.1f} KB)\n{p}"
            
            item = QListWidgetItem(item_text)
            item.setToolTip(p)
            self.list_widget.addItem(item)
            
        self.title_label.setText(f"已选文件列表 ({len(self.file_paths)}个)")
