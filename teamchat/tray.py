"""Windows notification-area (tray) icon: shows that Crewroom is running, and lets you open or stop it.

Closing the Crewroom window leaves the server running so agents can finish their work. This icon makes that
visible: hover for what's going on, left-click to open the window, right-click for Open / Stop. Standard library
only (ctypes); on macOS and Linux the window's bottom-left corner plays this role instead.
"""
import ctypes
import threading
import time
from ctypes import wintypes

user32 = ctypes.WinDLL('user32', use_last_error=True)
shell32 = ctypes.WinDLL('shell32', use_last_error=True)
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

WM_DESTROY, WM_CLOSE, WM_COMMAND, WM_TIMER, WM_NULL = 0x0002, 0x0010, 0x0111, 0x0113, 0x0000
WM_LBUTTONUP, WM_RBUTTONUP, WM_APP = 0x0202, 0x0205, 0x8000
CALLBACK = WM_APP + 1
NIN_BALLOONUSERCLICK = 0x0405
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x01, 0x02, 0x04, 0x10
MF_STRING, MF_GRAYED, MF_SEPARATOR = 0x0, 0x1, 0x800
TPM_RIGHTBUTTON, TPM_RETURNCMD = 0x2, 0x100
IMAGE_ICON, LR_LOADFROMFILE, LR_DEFAULTSIZE = 1, 0x10, 0x40
OPEN, STOP = 1, 2


class GUID(ctypes.Structure):
    _fields_ = [('a', ctypes.c_ulong), ('b', ctypes.c_ushort), ('c', ctypes.c_ushort), ('d', ctypes.c_ubyte * 8)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.DWORD), ('hWnd', wintypes.HWND), ('uID', wintypes.UINT), ('uFlags', wintypes.UINT),
                ('uCallbackMessage', wintypes.UINT), ('hIcon', wintypes.HICON), ('szTip', wintypes.WCHAR * 128),
                ('dwState', wintypes.DWORD), ('dwStateMask', wintypes.DWORD), ('szInfo', wintypes.WCHAR * 256),
                ('uVersion', wintypes.UINT), ('szInfoTitle', wintypes.WCHAR * 64), ('dwInfoFlags', wintypes.DWORD),
                ('guidItem', GUID), ('hBalloonIcon', wintypes.HICON)]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [('style', wintypes.UINT), ('lpfnWndProc', WNDPROC), ('cbClsExtra', ctypes.c_int), ('cbWndExtra', ctypes.c_int),
                ('hInstance', wintypes.HINSTANCE), ('hIcon', wintypes.HICON), ('hCursor', wintypes.HANDLE),
                ('hbrBackground', wintypes.HBRUSH), ('lpszMenuName', wintypes.LPCWSTR), ('lpszClassName', wintypes.LPCWSTR)]


user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
user32.CreateWindowExW.restype = wintypes.HWND
user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.LoadImageW.restype = wintypes.HANDLE
user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.LPVOID]
user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, wintypes.LPVOID]
shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE


class Tray:
    """status() -> (tooltip, [menu info lines], working count). seen() -> time the window last asked for news."""

    def __init__(self, icon, open_window, stop, status, seen):
        self.icon_path, self.open_window, self.stop, self.status, self.seen = str(icon), open_window, stop, status, seen
        self.hwnd = None
        self.ready = threading.Event()
        self.told_closed = False
        self._proc = WNDPROC(self._wndproc)  # kept on self so it is never garbage-collected

    def start(self):
        threading.Thread(target=self._run, name='tray', daemon=True).start()
        return self.ready.wait(5)

    def close(self):
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)

    # --- the icon --------------------------------------------------------------------
    def _data(self, flags=0):
        d = NOTIFYICONDATAW()
        d.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        d.hWnd, d.uID, d.uFlags = self.hwnd, 1, flags
        return d

    def _add(self):
        d = self._data(NIF_MESSAGE | NIF_ICON | NIF_TIP)
        d.uCallbackMessage, d.hIcon = CALLBACK, self.hicon
        d.szTip = self._tooltip()
        self.added = bool(shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(d)))

    def _tooltip(self):
        try:
            return self.status()[0][:127]
        except Exception:  # the mailbox is busy; keep the icon alive
            return 'Crewroom is running'

    def balloon(self, title, text):
        d = self._data(NIF_INFO)
        d.szInfoTitle, d.szInfo = title[:63], text[:255]
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(d))

    def _tick(self):
        d = self._data(NIF_TIP)
        d.szTip = self._tooltip()
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(d))
        last = self.seen()
        if last and time.time() - last > 12 and not self.told_closed:  # the window was closed: say we're still here
            self.told_closed = True
            self.balloon('Crewroom is still running',
                         'It keeps running here so your team can finish their work. Right-click this icon to stop it.')

    def _menu(self):
        try:
            _, lines, working = self.status()
        except Exception:
            lines, working = ['Crewroom is running'], 0
        menu = user32.CreatePopupMenu()
        for line in lines:
            user32.AppendMenuW(menu, MF_STRING | MF_GRAYED, 0, line)
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, OPEN, 'Open Crewroom')
        user32.AppendMenuW(menu, MF_STRING, STOP, 'Stop Crewroom' + (' (running requests keep going)' if working else ''))
        user32.SetMenuDefaultItem(menu, OPEN, 0)
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        user32.SetForegroundWindow(self.hwnd)  # without this the menu never closes when you click elsewhere
        choice = user32.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_RETURNCMD, pt.x, pt.y, 0, self.hwnd, None)
        user32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
        user32.DestroyMenu(menu)
        self._command(choice)

    def _command(self, choice):
        if choice == OPEN:
            self.told_closed = False
            self.open_window()
        elif choice == STOP:
            self.stop()

    # --- the hidden window that receives the icon's clicks -----------------------------
    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == CALLBACK:
            event = lparam & 0xFFFF
            if event == WM_LBUTTONUP or event == NIN_BALLOONUSERCLICK:
                self._command(OPEN)
            elif event == WM_RBUTTONUP:
                self._menu()
            return 0
        if msg == WM_COMMAND:  # also lets tests and other code drive the menu: PostMessage(hwnd, WM_COMMAND, OPEN/STOP)
            self._command(wparam & 0xFFFF)
            return 0
        if msg == WM_TIMER:
            self._tick()
            return 0
        if msg == self.taskbar_created:  # Explorer restarted: put the icon back
            self._add()
            return 0
        if msg == WM_CLOSE:
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._data()))
            user32.DestroyWindow(hwnd)
            return 0
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _run(self):
        inst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSW()
        wc.lpfnWndProc, wc.hInstance, wc.lpszClassName = self._proc, inst, 'CrewroomTray'
        user32.RegisterClassW(ctypes.byref(wc))
        self.taskbar_created = user32.RegisterWindowMessageW('TaskbarCreated')
        self.hwnd = user32.CreateWindowExW(0, 'CrewroomTray', 'Crewroom', 0, 0, 0, 0, 0, None, None, inst, None)
        self.hicon = user32.LoadImageW(None, self.icon_path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE)
        self._add()
        user32.SetTimer(self.hwnd, 1, 5000, None)
        self.ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        self.hwnd = None
