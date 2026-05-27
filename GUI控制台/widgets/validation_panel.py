from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QScrollArea, QFrame
from PySide6.QtCore import Qt

class ValidationPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        self.title_label = QLabel("数据预校验与风险评估", self)
        self.title_label.setStyleSheet("font-weight: bold; color: #a0a0a0; margin-bottom: 4px;")
        main_layout.addWidget(self.title_label)
        
        # Scroll Area for messages
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea { border: 1px solid #2d2d2d; border-radius: 4px; background-color: #1a1a1a; }")
        
        self.container = QWidget()
        self.container.setStyleSheet("background-color: #1a1a1a;")
        self.layout = QVBoxLayout(self.container)
        self.layout.setAlignment(Qt.AlignTop)
        self.layout.setSpacing(6)
        self.layout.setContentsMargins(6, 6, 6, 6)
        
        self.scroll.setWidget(self.container)
        main_layout.addWidget(self.scroll)
        
        # Initial empty state
        self.set_messages([])

    def set_messages(self, messages):
        """
        messages: list of ValidationMessage dicts:
        { "level": "error"|"warning"|"info", "message": "...", "suggestion": "..." }
        """
        # Clear layout
        while self.layout.count():
            item = self.layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
                
        if not messages:
            lbl = QLabel("✅ 所有前置依赖和文件均就绪，无校验风险。")
            lbl.setStyleSheet("color: #2ecc71; font-weight: bold; padding: 10px;")
            self.layout.addWidget(lbl)
            self.title_label.setText("数据预校验与风险评估 (就绪)")
            return
            
        errs = sum(1 for m in messages if m["level"] == "error")
        warns = sum(1 for m in messages if m["level"] == "warning")
        infos = sum(1 for m in messages if m["level"] == "info")
        self.title_label.setText(f"数据预校验 (Error: {errs}  |  Warning: {warns}  |  Info: {infos})")
        
        for msg in messages:
            level = msg.get("level", "info")
            content = msg.get("message", "")
            suggestion = msg.get("suggestion", "")
            file_name = msg.get("file", "")
            
            card = QFrame()
            card.setFrameShape(QFrame.StyledPanel)
            
            # Select background/text colors based on severity
            if level == "error":
                border_color = "#e74c3c"  # Red
                bg_color = "#2d1a1a"
                prefix = "🔴 <b>错误</b>"
            elif level == "warning":
                border_color = "#f1c40f"  # Yellow
                bg_color = "#2d2a1a"
                prefix = "🟡 <b>警告</b>"
            else:
                border_color = "#3498db"  # Blue
                bg_color = "#1a242d"
                prefix = "🔵 <b>信息</b>"
                
            card.setStyleSheet(f"""
                QFrame {{
                    background-color: {bg_color};
                    border: 1px solid {border_color};
                    border-radius: 4px;
                    padding: 6px;
                }}
            """)
            
            v_box = QVBoxLayout(card)
            v_box.setSpacing(2)
            v_box.setContentsMargins(6, 6, 6, 6)
            
            lbl_title = QLabel(f"{prefix}: {content}", card)
            lbl_title.setStyleSheet("font-size: 12px; color: #ffffff; border: none; background: transparent;")
            lbl_title.setWordWrap(True)
            v_box.addWidget(lbl_title)
            
            if file_name:
                lbl_file = QLabel(f"文件: {file_name}", card)
                lbl_file.setStyleSheet("font-size: 10px; color: #a0a0a0; border: none; background: transparent;")
                lbl_file.setWordWrap(True)
                v_box.addWidget(lbl_file)
                
            if suggestion:
                lbl_sug = QLabel(f"建议: {suggestion}", card)
                lbl_sug.setStyleSheet("font-size: 11px; color: #2ecc71; font-style: italic; border: none; background: transparent;")
                lbl_sug.setWordWrap(True)
                v_box.addWidget(lbl_sug)
                
            self.layout.addWidget(card)
