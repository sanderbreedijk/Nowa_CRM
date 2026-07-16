THEME = """
QMainWindow, QWidget {
    background-color: #F3F6FA;
    color: #182235;
    font-family: "Segoe UI";
    font-size: 14px;
}
QLabel {
    background-color: transparent;
    color: #182235;
}
QFrame#Sidebar {
    background-color: #102643;
    border: none;
}
QLabel#Brand {
    background-color: transparent;
    color: #FFFFFF;
    font-size: 23px;
    font-weight: 700;
    padding: 24px 18px 28px 18px;
}
QPushButton#Nav {
    background-color: transparent;
    color: #D9E5F3;
    text-align: left;
    padding: 13px 18px;
    border: none;
    border-left: 4px solid transparent;
    border-radius: 0px;
    font-weight: 600;
}
QPushButton#Nav:hover {
    background-color: #18385F;
    color: #FFFFFF;
}
QPushButton#Nav:checked {
    background-color: #1D4776;
    color: #FFFFFF;
    border-left: 4px solid #45A3FF;
}
QLabel#Title {
    color: #0B2342;
    font-size: 30px;
    font-weight: 700;
}
QLabel#Subtitle {
    color: #53657D;
    font-size: 14px;
    padding-bottom: 10px;
}
QFrame#Card {
    background-color: #FFFFFF;
    border: 1px solid #D8E1EC;
    border-radius: 12px;
    padding: 16px;
}
QFrame#Card QLabel {
    background-color: transparent;
    color: #26364D;
}
QFrame#Card QLabel#Kpi {
    color: #0B2342;
    font-size: 34px;
    font-weight: 700;
}
QLineEdit, QComboBox, QTextEdit {
    background-color: #FFFFFF;
    color: #172033;
    selection-background-color: #1677FF;
    selection-color: #FFFFFF;
    border: 1px solid #B8C6D8;
    border-radius: 8px;
    padding: 9px;
}
QLineEdit:focus, QComboBox:focus, QTextEdit:focus {
    border: 2px solid #1677FF;
}
QTableWidget {
    background-color: #FFFFFF;
    alternate-background-color: #F6F8FB;
    color: #172033;
    border: 1px solid #D5DFEA;
    border-radius: 10px;
    gridline-color: #E6ECF3;
    selection-background-color: #D7E9FF;
    selection-color: #0B2342;
}
QHeaderView::section {
    background-color: #E7EEF7;
    color: #26364D;
    border: none;
    border-bottom: 1px solid #C9D5E3;
    padding: 10px;
    font-weight: 700;
}
QPushButton {
    background-color: #FFFFFF;
    color: #17304F;
    border: 1px solid #AEBED1;
    border-radius: 8px;
    padding: 9px 14px;
    font-weight: 600;
}
QPushButton:hover {
    background-color: #EDF5FF;
    border-color: #1677FF;
}
QPushButton#Primary {
    background-color: #126FD6;
    color: #FFFFFF;
    border: 1px solid #126FD6;
    padding: 10px 16px;
}
QPushButton#Primary:hover {
    background-color: #0C5FB9;
    border-color: #0C5FB9;
}
QDialog {
    background-color: #F3F6FA;
}
QMessageBox QLabel {
    color: #172033;
    background-color: transparent;
}
"""
