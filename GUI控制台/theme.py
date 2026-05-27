QSS_THEME = """
QMainWindow {
    background-color: #121212;
}

QWidget {
    font-family: "Microsoft YaHei", "Segoe UI", "PingFang SC", sans-serif;
    font-size: 13px;
    color: #e0e0e0;
}

/* Left Navigation Menu styling */
QListWidget#nav_menu {
    background-color: #1a1a1a;
    border: none;
    border-right: 1px solid #2d2d2d;
    padding-top: 10px;
}

QListWidget#nav_menu::item {
    padding: 12px 20px;
    color: #a0a0a0;
    border-radius: 4px;
    margin: 4px 8px;
}

QListWidget#nav_menu::item:hover {
    background-color: #2b2b2b;
    color: #e0e0e0;
}

QListWidget#nav_menu::item:selected {
    background-color: #1f4e78;
    color: #ffffff;
    font-weight: bold;
}

/* Right Working Area View styling */
QStackedWidget {
    background-color: #121212;
    padding: 15px;
}

/* Parameter and Log Cards */
QFrame.card {
    background-color: #1e1e1e;
    border: 1px solid #2d2d2d;
    border-radius: 6px;
    padding: 10px;
}

/* Titles */
QLabel#view_title {
    font-size: 18px;
    font-weight: bold;
    color: #3498db;
    margin-bottom: 10px;
}

QLabel#section_title {
    font-size: 13px;
    font-weight: bold;
    color: #e0e0e0;
    margin-top: 8px;
    margin-bottom: 4px;
}

/* Buttons */
QPushButton {
    background-color: #2c3e50;
    border: 1px solid #34495e;
    border-radius: 4px;
    padding: 6px 14px;
    color: #ffffff;
    font-weight: bold;
    min-height: 20px;
}

QPushButton:hover {
    background-color: #34495e;
    border: 1px solid #3498db;
}

QPushButton:pressed {
    background-color: #1a252f;
}

QPushButton#run_btn {
    background-color: #1f4e78;
    border: 1px solid #2980b9;
    font-size: 14px;
    padding: 8px 20px;
}

QPushButton#run_btn:hover {
    background-color: #2980b9;
    border: 1px solid #3498db;
}

QPushButton#run_btn:disabled {
    background-color: #2d2d2d;
    border: 1px solid #3d3d3d;
    color: #666666;
}

/* Form inputs & LineEdits */
QLineEdit {
    background-color: #2b2b2b;
    border: 1px solid #3d3d3d;
    border-radius: 4px;
    padding: 5px;
    color: #ffffff;
}

QLineEdit:focus {
    border: 1px solid #3498db;
}

QComboBox {
    background-color: #2b2b2b;
    border: 1px solid #3d3d3d;
    border-radius: 4px;
    padding: 5px;
    color: #ffffff;
    min-width: 100px;
}

QComboBox:on {
    border: 1px solid #3498db;
}

QComboBox QAbstractItemView {
    background-color: #1e1e1e;
    border: 1px solid #2d2d2d;
    selection-background-color: #1f4e78;
    color: #e0e0e0;
}

/* Drop Zone Widget styling */
QFrame#drop_zone {
    background-color: #1e1e1e;
    border: 2px dashed #3a6073;
    border-radius: 8px;
    min-height: 100px;
}

QFrame#drop_zone[hover="true"] {
    background-color: #2c3e50;
    border: 2px dashed #1abc9c;
}

/* Text Scroll Areas & Terminal output */
QPlainTextEdit#log_console {
    background-color: #0b0b0b;
    border: 1px solid #2d2d2d;
    border-radius: 4px;
    font-family: "Consolas", "Courier New", monospace;
    font-size: 11px;
    color: #2ecc71;  /* Terminal green */
}

/* Validation items list */
QListWidget#file_list_widget {
    background-color: #1e1e1e;
    border: 1px solid #2d2d2d;
    border-radius: 4px;
}

/* ScrollBars */
QScrollBar:vertical {
    border: none;
    background-color: #121212;
    width: 10px;
    margin: 0px;
}

QScrollBar::handle:vertical {
    background-color: #2d2d2d;
    min-height: 20px;
    border-radius: 5px;
}

QScrollBar::handle:vertical:hover {
    background-color: #3498db;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    border: none;
    background: none;
}
"""
