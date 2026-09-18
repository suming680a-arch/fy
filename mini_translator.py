# -*- coding: utf-8 -*-
"""
迷你翻译窗 v1.1 (优化版)
------------------------------------------------
一个常驻桌面、始终置顶的小窗口，用来快速翻译对话/弹窗里的文字。
用法：
  1) 手动：把文字粘到上面框里，按 Ctrl+Enter 或点【翻译】
  2) 一键：点【读剪贴板】（或按全局热键 Ctrl+Alt+T）
  3) 自动：勾选【监听剪贴板】，之后任何地方 Ctrl+C 复制都会自动翻译
依赖：只用 Python 标准库（tkinter 自带）
可选：pip install keyboard   # 启用全局热键 Ctrl+Alt+T
"""

import json
import queue
import sys
import threading
import tkinter as tk
from tkinter import ttk
import urllib.parse
import urllib.request

# ============ 可按需修改的配置 ============
ENGINE = "google"       # "google" 或 "mymemory"（google 质量好，mymemory 无需翻墙）
PROXY = None            # 例如 "http://127.0.0.1:7890"；不用代理就保持 None
HOTKEY = "ctrl+alt+t"   # 全局热键（需要安装 keyboard 库）
# =========================================

# Windows 高分屏适配
if sys.platform == "win32":
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

if sys.platform == "win32":
    UI_FONT = ("Microsoft YaHei UI", 10)
    UI_FONT_SMALL = ("Microsoft YaHei UI", 9)
elif sys.platform == "darwin":
    UI_FONT = ("PingFang SC", 12)
    UI_FONT_SMALL = ("PingFang SC", 10)
else:
    UI_FONT = ("Noto Sans CJK SC", 10)
    UI_FONT_SMALL = ("Noto Sans CJK SC", 9)

LANG_MAP = {
    "中文(简体)": "zh-CN",
    "中文(繁体)": "zh-TW",
    "English": "en",
    "日本語": "ja",
    "한국어": "ko",
    "Русский": "ru",
    "Français": "fr",
    "Deutsch": "de",
    "Español": "es",
}

# ---------------- 翻译引擎 ----------------
def _urlopen(url, timeout=10):
    req = urllib.request.Request(url, headers={
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0 Safari/537.36")
    })
    if PROXY:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))
    else:
        opener = urllib.request.build_opener()
    return opener.open(req, timeout=timeout)

def google_translate(text, target="zh-CN", source="auto"):
    params = {"client": "gtx", "sl": source, "tl": target, "dt": "t", "q": text}
    url = "https://translate.googleapis.com/translate_a/single?" + urllib.parse.urlencode(params)
    with _urlopen(url) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return "".join(seg[0] for seg in data[0] if seg and seg[0])

def mymemory_translate(text, target="zh-CN", source="auto"):
    sl = "Autodetect" if source == "auto" else source
    params = {"q": text, "langpair": f"{sl}|{target}"}
    url = "https://api.mymemory.translated.net/get?" + urllib.parse.urlencode(params)
    with _urlopen(url) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["responseData"]["translatedText"]

def translate(text, target="zh-CN", source="auto"):
    if ENGINE == "mymemory":
        return mymemory_translate(text, target, source)
    return google_translate(text, target, source)

# ---------------- 主窗口 ----------------
class MiniTranslator:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.req_id = 0
        self.last_clip = ""
        self.ignore_clip = None
        self.task_q = queue.Queue()

        root.title("迷你翻译窗")
        root.geometry("460x400")
        root.minsize(360, 300)
        root.attributes("-topmost", True)
        
        # 设置主题样式
        self.style = ttk.Style()
        if sys.platform == "win32":
            self.style.theme_use('vista')

        self._build_ui()
        self._bind_keys()
        self._setup_hotkey()

        self.root.after(80, self._poll_queue)
        self.root.after(1000, self._poll_clipboard) # 稍微降低轮询频率，节省资源

    def _build_ui(self):
        # 顶部控制栏
        top = ttk.Frame(self.root, padding=(10, 8, 10, 4))
        top.pack(fill="x")

        ttk.Label(top, text="译为:").pack(side="left")
        self.lang_var = tk.StringVar(value="中文(简体)")
        self.lang_box = ttk.Combobox(top, textvariable=self.lang_var,
                                     values=list(LANG_MAP.keys()),
                                     width=10, state="readonly")
        self.lang_box.pack(side="left", padx=(4, 15))
        self.lang_box.bind("<<ComboboxSelected>>", self._on_lang_change)

        self.auto_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="监听剪贴板", variable=self.auto_var,
                        command=self._on_toggle_auto).pack(side="left")

        # 原文框
        src_frame = ttk.LabelFrame(self.root, text=" 原文 ", padding=5)
        src_frame.pack(fill="both", expand=True, padx=10, pady=(4, 4))
        self.src_text = tk.Text(src_frame, height=4, wrap="word",
                                font=UI_FONT, relief="flat", undo=True,
                                highlightthickness=0, padx=4, pady=4)
        sb1 = ttk.Scrollbar(src_frame, command=self.src_text.yview)
        self.src_text.configure(yscrollcommand=sb1.set)
        sb1.pack(side="right", fill="y")
        self.src_text.pack(side="left", fill="both", expand=True)

        # 译文框
        dst_frame = ttk.LabelFrame(self.root, text=" 译文 ", padding=5)
        dst_frame.pack(fill="both", expand=True, padx=10, pady=(0, 4))
        self.dst_text = tk.Text(dst_frame, height=5, wrap="word",
                                font=UI_FONT, relief="flat",
                                highlightthickness=0, padx=4, pady=4)
        sb2 = ttk.Scrollbar(dst_frame, command=self.dst_text.yview)
        self.dst_text.configure(yscrollcommand=sb2.set)
        sb2.pack(side="right", fill="y")
        self.dst_text.pack(side="left", fill="both", expand=True)

        # 按钮栏
        btns = ttk.Frame(self.root, padding=(10, 0, 10, 6))
        btns.pack(fill="x")
        ttk.Button(btns, text="翻译 (Ctrl+Enter)", command=self.do_translate).pack(side="left")
        ttk.Button(btns, text="读剪贴板", command=self.translate_clipboard).pack(side="left", padx=6)
        ttk.Button(btns, text="复制译文", command=self.copy_result).pack(side="left")
        ttk.Button(btns, text="清空", command=self.clear_all).pack(side="right")

        # 状态栏
        self.status = tk.StringVar(value="就绪")
        ttk.Label(self.root, textvariable=self.status, anchor="w",
                  foreground="#555555", font=UI_FONT_SMALL,
                  padding=(12, 0, 0, 8)).pack(fill="x")

    def _bind_keys(self):
        self.root.bind("<Control-Return>", lambda e: (self.do_translate(), "break"))
        self.src_text.bind("<Control-Return>", lambda e: (self.do_translate(), "break"))

    def _setup_hotkey(self):
        try:
            import keyboard
            keyboard.add_hotkey(HOTKEY, lambda: self.task_q.put(self.translate_clipboard))
            self.status.set(f"就绪 · 全局热键 {HOTKEY} 已启用")
        except Exception:
            self.status.set("就绪 · 未装 keyboard 库或权限不足，全局热键不可用")

    def _poll_queue(self):
        try:
            while True:
                fn = self.task_q.get_nowait()
                try:
                    fn()
                except Exception:
                    pass
        except queue.Empty:
            pass
        self.root.after(80, self._poll_queue)

    def _poll_clipboard(self):
        try:
            cur = self.root.clipboard_get()
        except tk.TclError:
            cur = ""

        if cur and cur != self.last_clip:
            self.last_clip = cur
            if self.auto_var.get() and cur != self.ignore_clip and len(cur) < 5000:
                self._set_text(self.src_text, cur)
                self.do_translate(cur)

        self.root.after(1000, self._poll_clipboard)

    def _on_toggle_auto(self):
        if self.auto_var.get():
            try:
                self.last_clip = self.root.clipboard_get()
            except tk.TclError:
                self.last_clip = ""
            self.status.set("已开启监听：复制任意文字即自动翻译")
        else:
            self.status.set("已关闭监听")

    def do_translate(self, text=None):
        if text is None:
            text = self.src_text.get("1.0", "end").strip()
        if not text:
            self.status.set("没有可翻译的内容")
            return

        target = LANG_MAP[self.lang_var.get()]
        self.req_id += 1
        rid = self.req_id
        self.status.set("翻译中…")

        def worker():
            try:
                res, err = translate(text, target), None
            except Exception as ex:
                res, err = "", str(ex)
            self.task_q.put(lambda r=res, m=err, i=rid: self._show_result(r, m, i))

        threading.Thread(target=worker, daemon=True).start()

    def _show_result(self, result, err, rid):
        if rid != self.req_id:
            return
        if err:
            self.status.set("翻译失败：网络错误或接口受限")
            self._set_text(self.dst_text, f"⚠️ 翻译失败：\n{err}")
            return
        self._set_text(self.dst_text, result)
        self.status.set(f"翻译完成 · {self.lang_var.get()}")

    def translate_clipboard(self):
        try:
            text = self.root.clipboard_get().strip()
        except tk.TclError:
            text = ""
        if not text:
            self.status.set("剪贴板为空")
            return
        self._set_text(self.src_text, text)
        self.do_translate(text)

    def copy_result(self):
        text = self.dst_text.get("1.0", "end").strip()
        if not text:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.ignore_clip = text
        self.last_clip = text
        self.status.set("译文已复制到剪贴板")

    def clear_all(self):
        self._set_text(self.src_text, "")
        self._set_text(self.dst_text, "")
        self.status.set("已清空")

    def _on_lang_change(self, event=None):
        if self.src_text.get("1.0", "end").strip():
            self.do_translate()

    @staticmethod
    def _set_text(widget, content):
        widget.delete("1.0", "end")
        widget.insert("1.0", content)

def main():
    root = tk.Tk()
    MiniTranslator(root)
    root.mainloop()

if __name__ == "__main__":
    main()
