"""Win11 Acrylic 毛玻璃底座：系统级背景模糊（ctypes），macOS Vibrancy 质感。

原理：SetWindowCompositionAttribute(ACCENT_ENABLE_ACRYLICBLURBEHIND)
给窗口背后叠加系统 Acrylic 模糊层；配合 Qt WA_TranslucentBackground，
控件以半透明 rgba 绘制，模糊层从背后透出（QFluentWidgets 同款路径）。
失败自动静默降级为纯深色（不透明），不影响功能。
"""
import ctypes
import sys

GWLP_HWND = 0

# --- Windows 组合属性结构 ---
ACRYLIC = 4


class _ACCENT_POLICY(ctypes.Structure):
    _fields_ = [("AccentState", ctypes.c_uint),
                ("AccentFlags", ctypes.c_uint),
                ("GradientColor", ctypes.c_uint),   # ARGB 模糊层着色
                ("AnimationId", ctypes.c_uint)]


class _WCA_DATA(ctypes.Structure):
    _fields_ = [("Attribute", ctypes.c_int),        # 19 = WCA_ACCENT_POLICY
                ("Data", ctypes.POINTER(_ACCENT_POLICY)),
                ("SizeOfData", ctypes.c_int)]


def enable_acrylic(hwnd: int, tint_argb: int = 0xE6101319) -> bool:
    """给窗口启用 Acrylic 模糊；tint 的 alpha 决定模糊层上的暗色浓度。"""
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        policy = _ACCENT_POLICY(ACRYLIC, 0, tint_argb, 0)
        data = _WCA_DATA(19, ctypes.byref(policy), ctypes.sizeof(policy))
        ok = ctypes.windll.user32.SetWindowCompositionAttribute(
            int(hwnd), ctypes.byref(data))
        return bool(ok)
    except Exception:
        return False


def force_round_corners(hwnd: int) -> None:
    """Win11 DWM 圆角偏好（frameless 窗口默认方角，强制 8px 圆角）。"""
    if sys.platform != "win32" or not hwnd:
        return
    try:
        val = ctypes.c_int(2)   # DWMWCP_ROUND
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            int(hwnd), 33, ctypes.byref(val), ctypes.sizeof(val))
    except Exception:
        pass
