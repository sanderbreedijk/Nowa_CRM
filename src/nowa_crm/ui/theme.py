THEME = """
QMainWindow, QWidget { background-color: #F3F6FA; color: #172238; font-family: "Segoe UI"; font-size: 13px; }
QLabel { background-color: transparent; color: #1B2940; }
QFrame#Sidebar { background-color: #0C213B; border: none; }
QLabel#BrandIcon { min-width: 44px; max-width: 44px; min-height: 44px; max-height: 44px; border-radius: 13px; background-color: #1677FF; color: white; font-size: 22px; font-weight: 800; qproperty-alignment: AlignCenter; }
QLabel#Brand { color: #FFFFFF; font-size: 17px; line-height: 90%; font-weight: 750; padding-left: 7px; }
QLabel#BrandCaption { color: #6F8BAA; font-size: 10px; font-weight: 700; letter-spacing: 2px; padding: 12px 7px 8px 7px; }
QLabel#SidebarFooter { color: #7790AB; font-size: 11px; padding: 10px 8px 2px 8px; }
QWidget#ContentStack { border: none; }
QPushButton#Nav { background-color: transparent; color: #D8E6F5; text-align: left; padding: 7px 10px; border: none; border-radius: 10px; font-weight: 600; }
QPushButton#Nav:hover { background-color: #163553; color: #FFFFFF; }
QPushButton#Nav:checked { background-color: #1B4269; color: #FFFFFF; border: 1px solid #2C5D8B; }
QPushButton#NavSection { background-color: transparent; color: #829AB4; text-align: left; padding: 9px 8px 5px 8px; border: none; border-radius: 7px; font-size: 10px; font-weight: 750; letter-spacing: 1px; }
QPushButton#NavSection:hover { color: #FFFFFF; background-color: #132E4B; }
QWidget#NavSectionContent { background-color: transparent; }
QLabel#Title { color: #102A4C; font-size: 28px; font-weight: 750; }
QLabel#Subtitle { color: #66758A; font-size: 13px; padding-bottom: 5px; }
QLabel#SearchHint { background-color: #FFFFFF; color: #6C7A8D; border: 1px solid #D8E1EB; border-radius: 8px; padding: 7px 12px; }
QFrame#Card, QGroupBox { background-color: #FFFFFF; border: 1px solid #DDE4EC; border-radius: 12px; padding: 14px; }
QGroupBox { margin-top: 10px; font-weight: 700; color: #203550; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; }
QFrame#Card QLabel { background-color: transparent; color: #344259; }
QFrame#Card QLabel#Kpi { color: #102A4C; font-size: 31px; font-weight: 750; }
QLineEdit, QComboBox, QTextEdit, QSpinBox, QDoubleSpinBox, QDateEdit { background-color: #FFFFFF; color: #172238; selection-background-color: #1677FF; selection-color: white; border: 1px solid #C8D3E0; border-radius: 8px; padding: 8px; min-height: 18px; }
QLineEdit:focus, QComboBox:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateEdit:focus { border: 1px solid #1677FF; }
QTableWidget { background-color: #FFFFFF; alternate-background-color: #F7F9FC; color: #172238; border: 1px solid #DCE4ED; border-radius: 10px; gridline-color: #EDF1F5; selection-background-color: #DDEEFF; selection-color: #102A4C; }
QHeaderView::section { background-color: #EAF0F7; color: #29415D; border: none; border-bottom: 1px solid #D5DFE9; padding: 9px; font-weight: 700; }
QPushButton { background-color: #FFFFFF; color: #203B5C; border: 1px solid #C2CFDD; border-radius: 8px; padding: 8px 13px; font-weight: 600; }
QPushButton:hover { background-color: #EFF6FF; border-color: #4A98F4; color: #0C5FB9; }
QPushButton:pressed { background-color: #DCEBFA; }
QPushButton#Primary { background-color: #1677E8; color: #FFFFFF; border-color: #1677E8; padding: 9px 15px; }
QPushButton#Primary:hover { background-color: #0D65C8; border-color: #0D65C8; color: #FFFFFF; }
QPushButton:disabled { background-color: #E8EDF3; color: #8A96A5; border-color: #D7DEE7; }
QTabWidget::pane { background-color: #FFFFFF; border: 1px solid #DCE4ED; border-radius: 10px; top: -1px; }
QTabBar::tab { background-color: transparent; color: #65758A; padding: 10px 16px; margin-right: 2px; border-bottom: 2px solid transparent; font-weight: 600; }
QTabBar::tab:hover { color: #1677E8; }
QTabBar::tab:selected { background-color: #FFFFFF; color: #0D65C8; border-bottom: 2px solid #1677E8; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #BBC8D6; border-radius: 5px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QToolTip { background-color: #0C213B; color: #FFFFFF; border: 1px solid #3477B7; padding: 6px; }
QDialog { background-color: #F3F6FA; }
QMessageBox QLabel { color: #172238; background-color: transparent; }
"""
