"""Windows 전용 커스텀(프레임리스) 타이틀바 지원.  [찾기: WIN_CUSTOM_TITLEBAR]

네이티브 캡션(제목표시줄 줄)만 제거하고 **창의 리사이즈·Aero Snap·최대화·그림자는 유지**한다.
방식: Qt.FramelessWindowHint 를 쓰지 않고, 일반 top-level 창의 non-client 영역을 WM_NCCALCSIZE
로 0으로 만들어(=창 전체가 클라이언트) 캡션을 없앤다. 리사이즈/드래그는 WM_NCHITTEST 로 직접
반환한다. 캡션 드래그는 HTCAPTION(네이티브)이라 Aero Snap·더블클릭 최대화가 그대로 동작한다.

비-Windows에선 install() 이 no-op, handle_native_event() 는 None 을 돌려주므로 맥 영향 0.

사용법(창 쪽):
    from spectra.ui import win_titlebar
    win_titlebar.install(self, caption_height=38)   # show() 이후 (winId 필요)
    def nativeEvent(self, et, msg):
        r = win_titlebar.handle_native_event(self, et, msg)
        return r if r is not None else super().nativeEvent(et, msg)
캡션(드래그) 영역 판정은 win_titlebar 가 window.childAt() 로 위젯을 보고, 버튼/콤보 등 상호작용
위젯 위면 HTCLIENT(클릭 통과), 빈 툴바 배경이면 HTCAPTION(드래그)로 처리한다.
"""
import platform as _pl
from PyQt5.QtCore import Qt, QPoint
from PyQt5.QtWidgets import QAbstractButton, QComboBox, QLineEdit, QAbstractSpinBox, QSlider

_IS_WIN = (_pl.system() == 'Windows')

if _IS_WIN:
    import ctypes
    from ctypes import wintypes

    WM_NCCALCSIZE = 0x0083
    WM_NCHITTEST  = 0x0084
    GWL_STYLE      = -16
    WS_THICKFRAME  = 0x00040000
    WS_CAPTION     = 0x00C00000
    WS_MINIMIZEBOX = 0x00020000
    WS_MAXIMIZEBOX = 0x00010000
    WS_SYSMENU     = 0x00080000
    SM_CXFRAME       = 32
    SM_CYFRAME       = 33
    SM_CXPADDEDBORDER = 92
    # WM_NCHITTEST 반환값
    HTCLIENT=1; HTCAPTION=2
    HTLEFT=10; HTRIGHT=11; HTTOP=12; HTTOPLEFT=13; HTTOPRIGHT=14
    HTBOTTOM=15; HTBOTTOMLEFT=16; HTBOTTOMRIGHT=17

    class _MARGINS(ctypes.Structure):
        _fields_ = [("cxLeftWidth", ctypes.c_int), ("cxRightWidth", ctypes.c_int),
                    ("cyTopHeight", ctypes.c_int), ("cyBottomHeight", ctypes.c_int)]

    class _NCCALCSIZE_PARAMS(ctypes.Structure):
        _fields_ = [("rgrc", wintypes.RECT * 3), ("lppos", ctypes.c_void_p)]

    class _WINDOWPLACEMENT(ctypes.Structure):
        _fields_ = [("length", ctypes.c_uint), ("flags", ctypes.c_uint), ("showCmd", ctypes.c_uint),
                    ("ptMinPosition", wintypes.POINT), ("ptMaxPosition", wintypes.POINT),
                    ("rcNormalPosition", wintypes.RECT)]

    def _is_maximized(hwnd):
        wp = _WINDOWPLACEMENT(); wp.length = ctypes.sizeof(_WINDOWPLACEMENT)
        ctypes.windll.user32.GetWindowPlacement(hwnd, ctypes.byref(wp))
        return wp.showCmd == 3   # SW_SHOWMAXIMIZED


def install(window, caption_height=38):
    """창을 커스텀 타이틀바 모드로 전환(Windows 전용). show() 이후 호출(winId 필요).
    caption_height: 상단 드래그(캡션) 영역 높이(논리 px). 앱 헤더 툴바 높이와 맞춘다."""
    if not _IS_WIN:
        return
    window._wtb_caption_h = caption_height
    try:
        hwnd = int(window.winId())
        user32 = ctypes.windll.user32
        # 캡션은 WM_NCCALCSIZE로 지우되, 리사이즈/스냅/최대화/그림자를 위해 THICKFRAME 등 스타일 유지.
        style = user32.GetWindowLongW(hwnd, GWL_STYLE)
        style |= (WS_THICKFRAME | WS_CAPTION | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU)
        user32.SetWindowLongW(hwnd, GWL_STYLE, style)
        # DWM 그림자 — 1px 프레임을 클라이언트로 확장하면 창 그림자가 살아난다.
        m = _MARGINS(0, 0, 1, 0)
        ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(m))
        # 프레임 재계산 강제(SWP_FRAMECHANGED)
        user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0002 | 0x0001 | 0x0020 | 0x0004)
    except Exception:
        pass


def handle_native_event(window, event_type, message):
    """window.nativeEvent 에서 호출. 처리했으면 (True, result) 튜플, 아니면 None 반환.
    비-Windows/미해당 메시지는 None → 호출부가 super().nativeEvent 로 위임."""
    if not _IS_WIN:
        return None
    try:
        et = event_type
        if isinstance(et, bytes):
            et = et.decode(errors='ignore')
        if et != 'windows_generic_MSG':
            return None
        msg = wintypes.MSG.from_address(int(message))
        if msg.message == WM_NCCALCSIZE:
            if msg.wParam:
                # non-client 영역 제거 → 창 전체가 클라이언트(캡션 사라짐).
                # 최대화 시엔 프레임 두께만큼 안쪽으로 넣어 작업표시줄을 가리거나 내용이 잘리지 않게.
                if _is_maximized(msg.hWnd):
                    p = ctypes.cast(msg.lParam, ctypes.POINTER(_NCCALCSIZE_PARAMS)).contents
                    gsm = ctypes.windll.user32.GetSystemMetrics
                    cx = gsm(SM_CXFRAME) + gsm(SM_CXPADDEDBORDER)
                    cy = gsm(SM_CYFRAME) + gsm(SM_CXPADDEDBORDER)
                    p.rgrc[0].left += cx; p.rgrc[0].right -= cx
                    p.rgrc[0].top += cy;  p.rgrc[0].bottom -= cy
                return (True, 0)
            return None
        if msg.message == WM_NCHITTEST:
            x = ctypes.c_short(msg.lParam & 0xFFFF).value          # 화면 물리 px
            y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
            ht = _hit_test(window, msg.hWnd, x, y)
            if ht is not None:
                return (True, ht)
            return None
    except Exception:
        return None
    return None


if _IS_WIN:
    def _interactive_at(window, lx, ly):
        """(lx,ly)=창 로컬 논리좌표에 상호작용 위젯이 있으면 True(→ HTCLIENT로 클릭 통과)."""
        child = window.childAt(int(lx), int(ly))
        if child is None:
            return False
        return isinstance(child, (QAbstractButton, QComboBox, QLineEdit, QAbstractSpinBox, QSlider))

    def _hit_test(window, hwnd, sx, sy):
        rect = wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))   # 물리 px
        w = rect.right - rect.left; h = rect.bottom - rect.top
        px = sx - rect.left; py = sy - rect.top                        # 창 기준 물리 px
        dpr = float(window.devicePixelRatioF() or 1.0)
        bw = max(4, int(6 * dpr))                                      # 리사이즈 테두리 두께(물리 px)
        maximized = _is_maximized(hwnd)
        on_l = px < bw; on_r = px >= w - bw; on_t = py < bw; on_b = py >= h - bw
        if not maximized:
            if on_t and on_l: return HTTOPLEFT
            if on_t and on_r: return HTTOPRIGHT
            if on_b and on_l: return HTBOTTOMLEFT
            if on_b and on_r: return HTBOTTOMRIGHT
            if on_l: return HTLEFT
            if on_r: return HTRIGHT
            if on_t: return HTTOP
            if on_b: return HTBOTTOM
        # 캡션(드래그) 영역: 상단 caption_h 이내이고, 그 지점에 상호작용 위젯이 없을 때만 드래그.
        cap_h_phys = float(getattr(window, '_wtb_caption_h', 38)) * dpr
        if py < cap_h_phys:
            lx = px / dpr; ly = py / dpr                              # 로컬 논리좌표
            if not _interactive_at(window, lx, ly):
                return HTCAPTION
        return HTCLIENT
