from PySide6.QtWidgets import QFrame, QVBoxLayout, QLabel
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent

class DropZone(QFrame):
    files_dropped = Signal(list)
    
    def __init__(self, label_text="拖拽 POS 订单 Excel、桌访 CSV 或文件夹到此处", parent=None):
        super().__init__(parent)
        self.setObjectName("drop_zone")
        self.setAcceptDrops(True)
        
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        
        self.icon_label = QLabel("📥", self)
        self.icon_label.setStyleSheet("font-size: 32px;")
        self.icon_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.icon_label)
        
        self.text_label = QLabel(label_text, self)
        self.text_label.setStyleSheet("color: #a0a0a0; font-size: 13px; font-weight: bold;")
        self.text_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.text_label)
        
        self.setProperty("hover", "false")

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setProperty("hover", "true")
            self.style().unpolish(self)
            self.style().polish(self)

    def dragLeaveEvent(self, event: QDragLeaveEvent):
        self.setProperty("hover", "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def dropEvent(self, event: QDropEvent):
        self.setProperty("hover", "false")
        self.style().unpolish(self)
        self.style().polish(self)
        
        paths = []
        for url in event.mimeData().urls():
            paths.append(url.toLocalFile())
            
        if paths:
            self.files_dropped.emit(paths)
