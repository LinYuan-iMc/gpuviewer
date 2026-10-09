"""主题 v2：macOS 雅致——毛玻璃半透明表面、大圆角、无硬边框、字体层级。

语义色（normal/warning/error/offline）保持不变，测试与用户认知连续；
表面色改为带 alpha 的 rgba，让 Acrylic 模糊层从窗口背后透出。
"""
import sys

COLORS = {
    # 语义色（不变）
    "normal": "#3fb950", "warning": "#d29922", "error": "#f85149",
    "offline": "#6e7681", "accent": "#58a6ff",
    # 表面（rgb 值 + 各自 alpha 组装，见 SURFACE）
    "text": "#e8eaed", "sub": "#9aa4b2",
    "bg": "#14181f", "card": "#1d232e", "border": "#2b3340",
}

# 半透明表面：卡片=88% 不透明度深灰蓝；控件槽再深一档。
SURFACE = {
    "window": "rgba(16,19,25,232)",       # 窗体底（其上是系统 Acrylic）
    "card": "rgba(35,40,50,150)",         # 卡片（毛玻璃片）
    "card_hover": "rgba(45,52,64,170)",
    "slot": "rgba(10,12,16,140)",         # 进度槽/表格底
    "hairline": "rgba(255,255,255,26)",   # 发丝边框
}

FONT_STACK = ("'Segoe UI Variable Display','Segoe UI','Microsoft YaHei',"
              "'PingFang SC',sans-serif")
MONO_STACK = "'Cascadia Mono','Consolas',monospace"
RADIUS = 12

# tests/CI 无真实合成器时退回不透明底色，避免白闪
if sys.platform != "win32":
    SURFACE["window"] = COLORS["bg"]
    SURFACE["card"] = COLORS["card"]

DARK_QSS = f"""
QWidget {{ background: transparent; color: {COLORS['text']};
           font-family: {FONT_STACK}; font-size: 10pt; }}
QLabel#title {{ font-size: 13pt; font-weight: 600; }}
QLabel#sub {{ color: {COLORS['sub']}; font-size: 9pt; }}
QLabel#banner {{ background: {COLORS['error']}; color: white;
                 border-radius: 8px; padding: 6px 12px; }}
QListWidget#sidebar {{ background: transparent; border: none; font-size: 11pt; }}
QListWidget#sidebar::item {{ padding: 9px 14px; border-radius: 8px; margin: 1px 4px; }}
QListWidget#sidebar::item:selected {{ background: rgba(88,166,255,52);
                                      color: {COLORS['accent']}; font-weight: 600; }}
QListWidget#sidebar::item:hover {{ background: rgba(255,255,255,14); }}
QListWidget#picker {{ background: {SURFACE['slot']}; border: 1px solid {SURFACE['hairline']};
                     border-radius: 8px; font-size: 10pt; outline: none; }}
QListWidget#picker::item {{ padding: 8px 12px; border-radius: 6px; margin: 2px 4px; }}
QListWidget#picker::item:selected {{ background: rgba(88,166,255,52);
                                     color: {COLORS['accent']}; font-weight: 600; }}
QListWidget#picker::item:hover {{ background: rgba(255,255,255,14); }}
QPushButton {{ background: {SURFACE['card']}; border: 1px solid {SURFACE['hairline']};
               border-radius: 8px; padding: 5px 14px; }}
QPushButton:hover {{ border-color: rgba(88,166,255,120); }}
QPushButton:disabled {{ color: {COLORS['sub']}; border-color: transparent; }}
QPushButton:checked {{ background: rgba(88,166,255,42); color: {COLORS['accent']};
                       border-color: rgba(88,166,255,140); font-weight: 600; }}
QTableView {{ background: {SURFACE['card']}; border: 1px solid {SURFACE['hairline']};
              border-radius: {RADIUS}px; gridline-color: transparent;
              selection-background-color: rgba(88,166,255,52); }}
QTableView::item {{ padding: 2px 8px; border-bottom: 1px solid rgba(255,255,255,10); }}
QHeaderView::section {{ background: transparent; color: {COLORS['sub']};
               border: none; border-bottom: 1px solid {SURFACE['hairline']};
               padding: 5px 8px; font-size: 9pt; }}
QTableCornerButton::section {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: rgba(255,255,255,36);
                              border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: rgba(255,255,255,64); }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page,
QScrollBar::sub-page {{ background: none; border: none; height: 0; width: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: rgba(255,255,255,36); border-radius: 4px; }}
QComboBox {{ background: {SURFACE['card']}; border: 1px solid {SURFACE['hairline']};
             border-radius: 8px; padding: 4px 10px; }}
QSpinBox, QDoubleSpinBox, QLineEdit {{ background: {SURFACE['slot']};
             border: 1px solid {SURFACE['hairline']}; border-radius: 8px;
             padding: 4px 8px; color: {COLORS['text']}; }}
QPlainTextEdit {{ background: {SURFACE['slot']}; border: 1px solid {SURFACE['hairline']};
                  border-radius: 8px; padding: 6px; font-family: {MONO_STACK};
                  font-size: 9pt; color: {COLORS['sub']}; }}
QLabel#ok {{ color: {COLORS['normal']}; }}
QLabel#err {{ color: {COLORS['error']}; }}
QToolTip {{ background: #1c2128; color: {COLORS['text']};
            border: 1px solid rgba(240,246,252,40); border-radius: 6px;
            padding: 5px 9px; font-size: 10pt; }}
"""
