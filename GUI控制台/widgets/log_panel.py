from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QPlainTextEdit
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QTextCursor

class LogPanel(QWidget):
    stop_clicked = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Header controls
        hdr_layout = QHBoxLayout()
        self.title_label = QLabel("运行日志与控制台输出", self)
        self.title_label.setStyleSheet("font-weight: bold; color: #a0a0a0;")
        hdr_layout.addWidget(self.title_label)
        
        hdr_layout.addStretch()
        
        self.stop_btn = QPushButton("🛑 终止任务", self)
        self.stop_btn.setStyleSheet("background-color: #c0392b; border-color: #d35400;")
        self.stop_btn.clicked.connect(self.stop_clicked.emit)
        self.stop_btn.setEnabled(False)  # Disabled until a task starts
        hdr_layout.addWidget(self.stop_btn)
        
        self.clear_btn = QPushButton("🧹 清除日志", self)
        self.clear_btn.clicked.connect(self.clear_log)
        hdr_layout.addWidget(self.clear_btn)
        
        layout.addLayout(hdr_layout)
        
        # Terminal console text box
        self.console = QPlainTextEdit(self)
        self.console.setObjectName("log_console")
        self.console.setReadOnly(True)
        # Ensure scrollbar behavior
        self.console.setMaximumBlockCount(10000) # Prevents memory leaks
        layout.addWidget(self.console)

    def append_text(self, text):
        self.console.moveCursor(QTextCursor.End)
        self.console.insertPlainText(text)
        self.console.moveCursor(QTextCursor.End)

    def clear_log(self):
        self.console.clear()

    def set_running(self, running):
        self.stop_btn.setEnabled(running)
        if running:
            self.title_label.setText("运行日志与控制台输出 (正在执行...)")
        else:
            self.title_label.setText("运行日志与控制台输出 (已结束/闲置)")
