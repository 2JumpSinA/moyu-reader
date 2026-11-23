import os, subprocess, sys, time, ctypes
from ctypes import wintypes as wt
sys.path.insert(0, r"D:\moyu-reader")
import main as M

app = M.ReaderApp()
u = ctypes.windll.user32
res = []

def windows():
    found = []
    P = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(h, l):
        n = u.GetWindowTextLengthW(h)
        if n:
            b = ctypes.create_unicode_buffer(n+1); u.GetWindowTextW(h, b, n+1)
            if b.value == "会议记录": found.append(h)
        return True
    found.clear(); u.EnumWindows(P(cb), 0)
    return found

def step():
    app.root.geometry("500x300+300+250"); app.root.update()
    # Esc 隐身（普通模式 withdraw）
    app._on_boss_key(); app.root.update()
    res.append(("Esc 隐身 withdraw", app.root.state() == "withdrawn", app.root.state()))
    # 双击启动器 → 第二实例发激活事件 → 本实例唤回
    subprocess.Popen([os.path.join(os.path.dirname(sys.executable), "pythonw.exe"),
                      os.path.abspath("main.py")], cwd=r"D:\moyu-reader")
    app.root.after(2500, check_restore)

def check_restore():
    app.root.update()
    res.append(("双击唤回（withdraw 解除）", app.root.state() != "withdrawn", app.root.state()))
    # 阅读模式老板键 alpha 0 → 激活唤回
    app._toggle_reading_mode(); app.root.update()
    app._on_boss_key(); app.root.update()
    hidden = float(app.root.attributes("-alpha")) == 0.0
    subprocess.Popen([os.path.join(os.path.dirname(sys.executable), "pythonw.exe"),
                      os.path.abspath("main.py")], cwd=r"D:\moyu-reader")
    app.root.after(2500, check_restore2)

def check_restore2():
    app.root.update()
    alpha = float(app.root.attributes("-alpha"))
    res.append(("隐身(阅读模式)激活唤回", alpha > 0.9 and not app._boss_hidden, f"alpha={alpha} boss={app._boss_hidden}"))
    res.append(("窗口数仍为 1", len(windows()) == 1, str(len(windows()))))
    for n, ok, d in res: print(("PASS" if ok else "FAIL"), n, d)
    print("OVERALL:", "PASS" if all(r[1] for r in res) else "FAIL")
    app._force_exit()

app.root.after(600, step)
app.run()
