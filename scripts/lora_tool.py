# -*- coding: utf-8 -*-
# LoRA 前后期工具箱
# 作者：翡翠珍珠排骨 (B站 UID: 3923028)
# 主页：https://space.bilibili.com/3923028
# 协议：MIT License
"""
LoRA 前后期工具箱
====================

一句话说明：一套基于 SDXL 的 LoRA 前后期处理脚本
（数据准备、打标、查重、LoRA 管理、Loss 曲线分析）

包含 Tab：
  🚀 一键流水线     尺寸统一 + 统一命名 + 查重 + WD 打标 + Tag 精修
  🖼️ 尺寸统一       单步缩放 / 画布填充
  🏷️ WD 打标        WD Tagger 批量打标
  ✏️ Tag 编辑器     标签批量替换 / 删除
  📦 LoRA 管理器     分组 / 元数据 / 批次 / Loss 曲线 / 标记 / 清理 / 归档
  🛠️ 图片工具        标签统计 / 相似查找 / 手动分类

说明：本工具箱主要面向 SDXL LoRA 的处理流程，但大部分功能
（尺寸统一 / 打标 / Tag 编辑 / LoRA 管理 / Loss 分析）同样适用 SD1.5。
"""
import os
import sys
import gc
import json
import shutil
import subprocess
import threading
import queue
import datetime
import hashlib
import re
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image, ImageOps
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser


# ---- 引入 LoRA 管理器作为第 5 个 Tab ----
from lora_manager import (
    LoRAManagerTab,
    enable_dpi_awareness,
    apply_dpi_scaling,
    calc_window_size,
    center_on_screen,
)

# ---- 引入图片工具 Tab ----
from image_tools_tab import ImageToolsTab
from dataset_tab import DatasetTab
from thumb_grid import ThumbCache, ThumbGrid

# ---- 便携包路径 ----
from paths import (
    WD_MODEL_DIR,
    LORA_TOOL_CFG,
    THUMB_CACHE_DIR,
    get_log_root,
    set_log_root,
)
from file_utils import open_path, reveal_path, copy_text

try:
    from PIL import ImageTk
    HAS_PILTK = True
except ImportError:
    HAS_PILTK = False

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    np = None

try:
    import torch
    import torch.nn.functional as F
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False
    torch = None
    F = None

try:
    import onnxruntime as ort
    import pandas as pd
    HAS_ORT = True
except ImportError:
    HAS_ORT = False

try:
    import imagehash
    HAS_IMAGEHASH = True
except ImportError:
    HAS_IMAGEHASH = False
def detect_torch_cuda():
    """
    检测 PyTorch 的 CUDA 是否可用（用于尺寸统一的 GPU 加速）。
    返回 (是否可用, 提示信息)
    """
    if not HAS_TORCH:
        return False, "未安装 PyTorch"

    try:
        if not torch.cuda.is_available():
            return False, "未检测到 CUDA 或 NVIDIA 驱动"
    except Exception as e:
        return False, f"检测失败：{e}"

    return True, "已检测到 CUDA，可启用 GPU 加速"
def detect_cuda_support():
    """
    检测当前环境能否使用 GPU 加速（CUDA）。
    返回 (是否可用, 提示信息)
    """
    if not HAS_ORT:
        return False, "未安装 onnxruntime"

    try:
        providers = ort.get_available_providers()
    except Exception as e:
        return False, f"检测失败：{e}"

    if "CUDAExecutionProvider" not in providers:
        return False, "未安装 onnxruntime-gpu，只能用 CPU"

    try:
        r = subprocess.run(["nvidia-smi"],
                           capture_output=True, timeout=5)
        if r.returncode != 0:
            return False, "未检测到 NVIDIA 驱动，只能用 CPU"
    except FileNotFoundError:
        return False, "未安装 NVIDIA 驱动，只能用 CPU"
    except Exception:
        return False, "无法确认 CUDA 环境，默认 CPU"

    return True, "已检测到 CUDA，可启用 GPU 加速"

# ================= 常量 / 配色 =================
SUPPORTED_INPUT_FORMATS = (".jpg", ".jpeg", ".png", ".bmp", ".gif",
                           ".webp", ".tiff", ".tif")
WD_MODEL_FILENAME = "model.onnx"
WD_LABEL_FILENAME = "selected_tags.csv"
WD_MODEL_INPUT_SIZE = 448
WD_LOCAL_MODEL_DIR = WD_MODEL_DIR
THUMB_SIZE = (140, 140)
MAX_THUMBNAILS = 200
THUMB_CACHE_LIMIT = 800

COLOR = {
    "bg":        "#f7f8fa",
    "card":      "#ffffff",
    "border":    "#e5e7eb",
    "primary":   "#3b82f6",
    "primary_h": "#2563eb",
    "success":   "#10b981",
    "danger":    "#ef4444",
    "text":      "#111827",
    "muted":     "#6b7280",
    "log_bg":    "#0f172a",
    "log_fg":    "#e2e8f0",
}

CONFIG_FILE = LORA_TOOL_CFG
GLOBAL_CFG = {}


def generate_app_icon(root):
    """
    程序图标：代码生成，无需外部 .ico 文件。
    画一个蓝底白字"L"的图标，作为窗口 + 任务栏图标。
    """
    try:
        from PIL import Image as _Image, ImageDraw, ImageTk
        size = 64
        img = _Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        # 圆角方形蓝底
        d.rounded_rectangle([2, 2, size - 3, size - 3], radius=14,
                            fill=(59, 130, 246, 255))
        # 白色字母 "L"
        d.rectangle([18, 16, 27, 48], fill="white")
        d.rectangle([18, 39, 46, 48], fill="white")
        photo = ImageTk.PhotoImage(img)
        root.iconphoto(True, photo)
        root._app_icon_ref = photo   # 保存引用，防被 GC 回收
    except Exception:
        pass


# ================= 配置持久化 =================
def load_global_config():
    global GLOBAL_CFG
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            GLOBAL_CFG = json.load(f)
    except Exception:
        GLOBAL_CFG = {}


def save_global_config():
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(GLOBAL_CFG, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def pick_dir(var, key, title="选择文件夹"):
    init = var.get() or GLOBAL_CFG.get(key, "")
    d = filedialog.askdirectory(initialdir=init if init else None, title=title)
    if d:
        var.set(d)
        GLOBAL_CFG[key] = d
        save_global_config()
    return d


def pick_file(var, key, title="选择文件", filetypes=None):
    init = var.get() or GLOBAL_CFG.get(key, "")
    init_dir = os.path.dirname(init) if init else None
    f = filedialog.askopenfilename(initialdir=init_dir, title=title,
                                   filetypes=filetypes or [("所有文件", "*.*")])
    if f:
        var.set(f)
        GLOBAL_CFG[key] = f
        save_global_config()
    return f


# ================= 通用工具函数 =================
def unescape_tag(t):
    return (t.replace('\\(', '(').replace('\\)', ')')
             .replace('\\[', '[').replace('\\]', ']')
             .replace('\\_', '_').replace('\\:', ':'))


def parse_manifest(path):
    adds, removes = [], []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith('+'):
                t = unescape_tag(line[1:].strip())
                if t:
                    adds.append(t)
            elif line.startswith('-'):
                t = unescape_tag(line[1:].strip())
                if t:
                    removes.append(t)
    return adds, removes


def parse_manual_text(text):
    if not text or not text.strip():
        return []
    raw = text.replace('\r', '\n')
    parts = []
    for chunk in raw.split('\n'):
        parts.extend(chunk.split(','))
    out = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if p.startswith('+') or p.startswith('-'):
            p = p[1:].strip()
        if p:
            out.append(unescape_tag(p))
    return out


def read_tags(txt_path):
    with open(txt_path, 'r', encoding='utf-8') as f:
        content = f.read()
    raw = content.replace('\r', ',').replace('\n', ',')
    parts = [p.strip() for p in raw.split(',')]
    return [p for p in parts if p]


# ================= 备份逻辑 =================
def make_backup_cfg(enabled, mode, custom_dir, base_root):
    return {
        "enabled": bool(enabled),
        "mode": mode,
        "dir": custom_dir or "",
        "root": base_root or "",
    }


def _backup_path(txt_path, cfg):
    if cfg["mode"] == "custom" and cfg["dir"]:
        base_root = cfg.get("root") or ""
        rel = None
        if base_root:
            try:
                ap = os.path.abspath(txt_path)
                ar = os.path.abspath(base_root)
                if os.path.commonpath([ap, ar]) == ar:
                    rel = os.path.relpath(ap, ar)
            except Exception:
                rel = None
        if not rel:
            rel = os.path.basename(txt_path)
        return os.path.join(cfg["dir"], rel + ".bak")
    return txt_path + ".bak"


def write_tags(txt_path, tags, backup_cfg=None):
    if backup_cfg and backup_cfg.get("enabled") and os.path.isfile(txt_path):
        try:
            bak = _backup_path(txt_path, backup_cfg)
            os.makedirs(os.path.dirname(bak), exist_ok=True)
            shutil.copy2(txt_path, bak)
        except Exception:
            pass
    tmp = txt_path + ".tmp"
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(', '.join(tags))
    os.replace(tmp, txt_path)


def find_images(folder, recursive=True):
    result = []
    if recursive:
        for root, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs if not d.startswith('_')]
            for f in files:
                if f.lower().endswith(SUPPORTED_INPUT_FORMATS):
                    result.append(os.path.join(root, f))
    else:
        for f in os.listdir(folder):
            p = os.path.join(folder, f)
            if os.path.isfile(p) and f.lower().endswith(SUPPORTED_INPUT_FORMATS):
                result.append(p)
    return result


def find_txt_files(folder, recursive=True):
    result = []
    def _ok(f):
        lf = f.lower()
        return (lf.endswith('.txt')
                and not lf.endswith('.txt.bak')
                and not f.startswith('_'))
    if recursive:
        for root, _, files in os.walk(folder):
            for f in files:
                if _ok(f):
                    result.append(os.path.join(root, f))
    else:
        for f in os.listdir(folder):
            p = os.path.join(folder, f)
            if os.path.isfile(p) and _ok(f):
                result.append(p)
    return result


def find_image_for_txt(txt_path):
    base, _ = os.path.splitext(txt_path)
    for ext in SUPPORTED_INPUT_FORMATS:
        for e in (ext, ext.upper()):
            p = base + e
            if os.path.isfile(p):
                return p
    return None


def get_resampling():
    return getattr(Image, "Resampling", Image).LANCZOS


def _flatten_to_rgb(img, fill_color):
    if img.mode == "RGB":
        return img
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, fill_color)
        bg.paste(img, mask=img.split()[-1])
        return bg
    return img.convert("RGB")


def _compute_target_size(w, h, size_mode, max_side, canvas_w, canvas_h,
                         allow_upscale):
    if size_mode == "max_side":
        if not allow_upscale and max(w, h) <= max_side:
            return w, h, False
        if w >= h:
            tw = max_side
            th = max(1, int(round(h * max_side / w)))
        else:
            th = max_side
            tw = max(1, int(round(w * max_side / h)))
        return tw, th, (tw != w or th != h)
    else:
        scale = min(canvas_w / w, canvas_h / h)
        if not allow_upscale and scale > 1.0:
            scale = 1.0
        tw = max(1, int(round(w * scale)))
        th = max(1, int(round(h * scale)))
        return tw, th, True


def _save_image(pil_img, save_path, out_format, jpg_quality):
    if out_format.upper() == "JPG":
        pil_img.save(save_path, "JPEG", quality=jpg_quality)
    else:
        pil_img.save(save_path, "PNG")


def _interpolate_antialias(tensor, size):
    try:
        return F.interpolate(tensor, size=size, mode='bilinear',
                             align_corners=False, antialias=True)
    except TypeError:
        return F.interpolate(tensor, size=size, mode='bilinear',
                             align_corners=False)


# ================= 布局辅助组件 (NEW) =================
class ScrollableFrame(ttk.Frame):
    """
    竖向可滚动的容器：把子控件放进 self.inner 里即可。
    以后加新功能不用再操心溢出，滚动条自动兜底。
    """
    def __init__(self, parent, bg=None):
        super().__init__(parent)
        bg = bg or COLOR["bg"]

        self.canvas = tk.Canvas(self, highlightthickness=0, bd=0, bg=bg)
        self.vsb = ttk.Scrollbar(self, orient='vertical',
                                 command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.inner = ttk.Frame(self.canvas)
        self._win = self.canvas.create_window((0, 0), window=self.inner,
                                              anchor='nw')
        self.inner.bind('<Configure>', self._on_inner)
        self.canvas.bind('<Configure>', self._on_canvas)

        # 滚轮支持
        self.canvas.bind('<MouseWheel>', self._on_wheel)
        self.inner.bind('<MouseWheel>', self._on_wheel)

    def _on_inner(self, _):
        self.canvas.configure(scrollregion=self.canvas.bbox('all'))

    def _on_canvas(self, e):
        self.canvas.itemconfig(self._win, width=e.width)

    def _on_wheel(self, e):
        try:
            self.canvas.yview_scroll(int(-1 * (e.delta / 120)), 'units')
        except Exception:
            pass


def build_split_columns(parent, left_min=620, pad_x=15):
    """
    生成左右分栏的主体区域。
    返回 (left_inner, right_frame)
      left_inner  → 往这里加设置控件（自动可滚动）
      right_frame → 往这里加日志/预览等占满高度的控件
    """
    body = ttk.Frame(parent)
    body.pack(fill=tk.BOTH, expand=True, padx=pad_x, pady=(0, 6))
    body.columnconfigure(0, weight=3, minsize=left_min)
    body.columnconfigure(1, weight=2)
    body.rowconfigure(0, weight=1)

    left_scroll = ScrollableFrame(body)
    left_scroll.grid(row=0, column=0, sticky='nsew', padx=(0, 8))

    right = ttk.Frame(body)
    right.grid(row=0, column=1, sticky='nsew', padx=(8, 0))

    return left_scroll.inner, right


def build_footer(parent, pad_x=15):
    """
    生成底部按钮 + 状态栏 + 进度条区域。
    返回 (bar_frame, status_var)
    往 bar_frame 里 pack 按钮即可；status_var 用于显示进度文字。
    """
    # 先 pack 进度条到最底，再 pack bar 到进度条上方
    progress = ttk.Progressbar(parent, orient=tk.HORIZONTAL, mode='determinate')
    progress.pack(side=tk.BOTTOM, fill=tk.X, padx=pad_x, pady=(0, 10))

    bar = ttk.Frame(parent)
    bar.pack(side=tk.BOTTOM, fill=tk.X, padx=pad_x, pady=(0, 4))

    status_var = tk.StringVar(value="就绪")
    tk.Label(bar, textvariable=status_var, anchor=tk.E,
             bg=COLOR["bg"], fg=COLOR["muted"],
             font=('Microsoft YaHei UI', 9)).pack(side=tk.RIGHT)

    return bar, status_var, progress


# ================= 备份选项 UI 组件 =================
class BackupOptions(ttk.LabelFrame):
    def __init__(self, parent, base_root_getter=None, title=" 备份设置 "):
        super().__init__(parent, text=title, padding=8)
        self.base_root_getter = base_root_getter

        self.enabled = tk.BooleanVar(value=False)
        self.mode = tk.StringVar(value="same")
        self.custom_dir = tk.StringVar(
            value=GLOBAL_CFG.get("last_backup_dir", ""))

        row = ttk.Frame(self)
        row.pack(fill=tk.X)
        ttk.Checkbutton(row, text="写入前备份原 txt",
                        variable=self.enabled,
                        command=self._toggle).pack(side=tk.LEFT)

        self.opts = ttk.Frame(self)
        self.opts.pack(fill=tk.X, pady=(4, 0))

        ttk.Radiobutton(self.opts, text="原目录 (.bak)",
                        variable=self.mode, value="same",
                        command=self._toggle).pack(side=tk.LEFT)
        ttk.Radiobutton(self.opts, text="指定目录",
                        variable=self.mode, value="custom",
                        command=self._toggle).pack(side=tk.LEFT, padx=(10, 4))

        self.dir_entry = ttk.Entry(self.opts, textvariable=self.custom_dir)
        self.dir_entry.pack(side=tk.LEFT, fill=tk.X, expand=True,
                            padx=(4, 4))
        self.browse_btn = ttk.Button(self.opts, text="浏览", width=6,
                                     command=self._pick)
        self.browse_btn.pack(side=tk.LEFT)

        self.hint = tk.Label(self, text="",
                             font=('Microsoft YaHei UI', 8),
                             fg=COLOR["muted"], bg=COLOR["card"],
                             anchor='w', justify='left')
        self.hint.pack(fill=tk.X, pady=(4, 0))

        self._toggle()

    def _pick(self):
        d = pick_dir(self.custom_dir, "last_backup_dir", "选择备份目录")
        if d:
            self._toggle()

    def _toggle(self):
        enabled = self.enabled.get()
        custom = (self.mode.get() == "custom")
        state_entry = tk.NORMAL if (enabled and custom) else tk.DISABLED
        state_btn = tk.NORMAL if (enabled and custom) else tk.DISABLED
        self.dir_entry.config(state=state_entry)
        self.browse_btn.config(state=state_btn)
        for w in self.opts.winfo_children():
            if isinstance(w, ttk.Radiobutton):
                w.state(["!disabled"] if enabled else ["disabled"])
        if not enabled:
            self.hint.config(text="※ 关闭备份：直接覆盖原 txt，不留副本")
        elif custom:
            d = self.custom_dir.get().strip()
            if d:
                self.hint.config(
                    text=f"※ 备份目录：{d}\\<相对路径>.bak（保持目录结构）")
            else:
                self.hint.config(text="※ 请选择备份目录")
        else:
            self.hint.config(text="※ 备份到原目录：xxx.txt.bak")

    def get_cfg(self):
        base_root = ""
        if self.base_root_getter:
            try:
                base_root = self.base_root_getter() or ""
            except Exception:
                base_root = ""
        return make_backup_cfg(
            enabled=self.enabled.get(),
            mode=self.mode.get(),
            custom_dir=self.custom_dir.get().strip(),
            base_root=base_root,
        )


# ================= 样式 =================
def setup_styles():
    style = ttk.Style()
    try:
        style.theme_use('clam')
    except Exception:
        pass

    FONT = ('Microsoft YaHei UI', 10)
    FONT_BOLD = ('Microsoft YaHei UI', 10, 'bold')

    style.configure('.', font=FONT, background=COLOR["bg"])
    style.configure('TFrame', background=COLOR["bg"])
    style.configure('TLabel', background=COLOR["bg"], foreground=COLOR["text"])
    style.configure('TLabelframe', background=COLOR["card"],
                    bordercolor=COLOR["border"], relief='solid', borderwidth=1)
    style.configure('TLabelframe.Label', background=COLOR["card"],
                    foreground=COLOR["primary"], font=FONT_BOLD)
    style.configure('TCheckbutton', background=COLOR["card"])
    style.configure('TRadiobutton', background=COLOR["card"])

    style.configure('TButton', padding=(10, 5))
    style.map('TButton', background=[('active', '#eef2ff')])

    style.configure('Primary.TButton', font=FONT_BOLD, padding=(18, 8),
                    background=COLOR["primary"], foreground='white',
                    borderwidth=0, focusthickness=0)
    style.map('Primary.TButton',
              background=[('active', COLOR["primary_h"]),
                          ('disabled', '#9ca3af')],
              foreground=[('disabled', '#f3f4f6')])

    style.configure('TEntry', padding=4, fieldbackground='white')
    style.configure('TSpinbox', padding=4)
    style.configure('TCombobox', padding=4)

    style.configure('Treeview', rowheight=26, font=FONT,
                    fieldbackground='white', background='white', borderwidth=0)
    style.configure('Treeview.Heading', font=FONT_BOLD,
                    background='#eef2ff', foreground=COLOR["text"],
                    relief='flat')
    style.map('Treeview',
              background=[('selected', COLOR["primary"])],
              foreground=[('selected', 'white')])

    style.configure('TNotebook', background=COLOR["bg"], borderwidth=0)
    style.configure('TNotebook.Tab', padding=(18, 10), font=FONT_BOLD,
                    background='#e5e7eb', foreground=COLOR["muted"])
    style.map('TNotebook.Tab',
              background=[('selected', COLOR["card"])],
              foreground=[('selected', COLOR["primary"])])

    style.configure('TProgressbar', troughcolor='#e5e7eb',
                    background=COLOR["primary"], borderwidth=0, thickness=8)

    # ---- 补：LoRA 管理器用到的样式 ----
    style.configure('Small.TLabel',
                    font=('Microsoft YaHei UI', 9),
                    background=COLOR["bg"],
                    foreground=COLOR["muted"])
    style.configure('Danger.TButton',
                    font=FONT_BOLD, padding=(14, 6),
                    background=COLOR["danger"], foreground='white',
                    borderwidth=0, focusthickness=0)
    style.map('Danger.TButton',
              background=[('active', '#dc2626'),
                          ('disabled', '#9ca3af')],
              foreground=[('disabled', '#f3f4f6')])


# ================= 日志面板（不再包含状态栏） =================


class LogPanel:
    def __init__(self, parent, root, title=" 日志 "):
        self.root = root
        self.frame = ttk.LabelFrame(parent, text=title, padding=8)
        self.frame.pack(fill=tk.BOTH, expand=True)

        self.text = tk.Text(self.frame, wrap=tk.WORD, height=10,
                            font=('Consolas', 9),
                            bg=COLOR["log_bg"], fg=COLOR["log_fg"],
                            insertbackground='white', relief=tk.FLAT, bd=0,
                            padx=10, pady=8)
        self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(self.frame, command=self.text.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.text.config(yscrollcommand=sb.set)

        self.text.tag_config("ok", foreground="#34d399")
        self.text.tag_config("err", foreground="#f87171")
        self.text.tag_config("info", foreground="#60a5fa")
        self.text.tag_config("warn", foreground="#fbbf24")

    def log(self, msg):
        tag = None
        s = msg.lstrip()
        if s.startswith('✓'):
            tag = "ok"
        elif s.startswith('✗') or s.startswith('❌'):
            tag = "err"
        elif s.startswith('🔄') or s.startswith('====='):
            tag = "info"
        elif s.startswith('⚠') or s.startswith('⏹'):
            tag = "warn"
        if tag:
            self.text.insert(tk.END, msg + "\n", tag)
        else:
            self.text.insert(tk.END, msg + "\n")
        self.text.see(tk.END)

    def clear(self):
        self.text.delete(1.0, tk.END)


# ================= 基类：统一队列 / 按钮 / 状态 =================
class BaseWorkerTab:
    def __init__(self, parent, root):
        self.parent = parent
        self.root = root
        self.queue = queue.Queue()
        self.is_running = False
        self.stop_event = threading.Event()
        self.status = tk.StringVar(value="就绪")
        self.start_btn = None
        self.stop_btn = None
        self.progress = None
        self.log_panel = None
        self._queue_running = True

    def _begin(self, total=0):
        self.is_running = True
        self.stop_event.clear()
        if self.start_btn:
            self.start_btn.config(state=tk.DISABLED)
        if self.stop_btn:
            self.stop_btn.config(state=tk.NORMAL)
        if self.log_panel:
            self.log_panel.clear()
        self.status.set("运行中...")
        if self.progress is not None:
            self.progress['maximum'] = max(1, total)
            self.progress['value'] = 0

    def _finish(self, success, msg):
        self.is_running = False
        if self.start_btn:
            self.start_btn.config(state=tk.NORMAL)
        if self.stop_btn:
            self.stop_btn.config(state=tk.DISABLED)
        self.status.set(msg)
        if self.log_panel:
            self.log_panel.log(f"\n{msg}")
        if success:
            messagebox.showinfo("完成", msg)

    def stop(self):
        if self.is_running:
            self.stop_event.set()
            if self.log_panel:
                self.log_panel.log("⏹ 用户请求停止...")

    def _check_queue(self):
        if not self._queue_running:
            return
        try:
            while True:
                msg = self.queue.get_nowait()
                kind = msg[0]
                if kind == "log":
                    self.log_panel.log(msg[1])
                elif kind == "phase_total":
                    if self.progress is not None:
                        self.progress['maximum'] = max(1, msg[1])
                        self.progress['value'] = 0
                elif kind == "progress":
                    if self.progress is not None:
                        self.progress['value'] = msg[1]
                    self.status.set(f"进度: {msg[1]}/{msg[2]}")
                elif kind == "finished":
                    self._finish(msg[1], msg[2])
        except queue.Empty:
            pass
        if self._queue_running:
            self.root.after(100, self._check_queue)

    def _on_visibility_change(self, visible):
        """Tab 可见性变化时由 App 调用"""
        if visible:
            if not self._queue_running:
                self._queue_running = True
                self.root.after(100, self._check_queue)
        else:
            self._queue_running = False

# ================= 步骤 1：尺寸统一 =================
def resize_one_cpu(img_path, save_path, size_mode, max_side, canvas_w,
                   canvas_h, fill_color, out_format, jpg_quality,
                   allow_upscale):
    try:
        with Image.open(img_path) as img:
            img = _flatten_to_rgb(img, fill_color)
            w, h = img.size
            tw, th, need = _compute_target_size(
                w, h, size_mode, max_side, canvas_w, canvas_h, allow_upscale)
            if not need:
                _save_image(img, save_path, out_format, jpg_quality)
                return True, None
            if tw != w or th != h:
                resized = img.resize((tw, th), get_resampling())
            else:
                resized = img
            if size_mode == "canvas":
                canvas = Image.new("RGB", (canvas_w, canvas_h), fill_color)
                canvas.paste(resized, ((canvas_w - tw) // 2,
                                       (canvas_h - th) // 2))
                resized = canvas
            _save_image(resized, save_path, out_format, jpg_quality)
        return True, None
    except Exception as e:
        return False, str(e)


def resize_batch_gpu(items, size_mode, max_side, canvas_w, canvas_h,
                     fill_color, out_format, jpg_quality, allow_upscale):
    if not HAS_TORCH:
        return [(p, False, "PyTorch 未安装") for p, _ in items]
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    results = []
    for img_path, save_path in items:
        try:
            with Image.open(img_path) as raw:
                img = _flatten_to_rgb(raw, fill_color)
                w, h = img.size
                arr = np.array(img, copy=True)

            tw, th, need = _compute_target_size(
                w, h, size_mode, max_side, canvas_w, canvas_h, allow_upscale)

            if not need:
                _save_image(Image.fromarray(arr, 'RGB'), save_path,
                            out_format, jpg_quality)
                results.append((img_path, True, None))
                continue

            tensor = torch.from_numpy(arr).permute(2, 0, 1).float() \
                         .to(device).unsqueeze(0)

            if tw != w or th != h:
                tensor = _interpolate_antialias(tensor, (th, tw))

            if size_mode == "canvas":
                canvas_t = torch.zeros((1, 3, canvas_h, canvas_w), device=device)
                for i in range(3):
                    canvas_t[0, i].fill_(fill_color[i])
                oy = (canvas_h - th) // 2
                ox = (canvas_w - tw) // 2
                canvas_t[0, :, oy:oy + th, ox:ox + tw] = tensor[0]
                tensor = canvas_t

            out_np = tensor[0].permute(1, 2, 0).cpu().numpy().astype('uint8')
            _save_image(Image.fromarray(out_np, 'RGB'), save_path,
                        out_format, jpg_quality)
            results.append((img_path, True, None))
            del tensor, out_np
        except Exception as e:
            results.append((img_path, False, str(e)))
    return results

def run_resize_step(images, input_root, output_root, size_mode,
                    max_side, canvas_w, canvas_h, fill_color,
                    out_format, jpg_quality, use_gpu, batch_size,
                    allow_upscale, log, stop_event,
                    rename_prefix=None):
    total = len(images)
    success = 0
    fail = 0
    pairs = []

    ext = ".jpg" if out_format.upper() == "JPG" else ".png"

    if rename_prefix is not None:
        # 统一命名模式：按原路径排序，平铺到 output_root
        images_sorted = sorted(images, key=lambda x: x.lower())

        # ★ 检测输出目录已有的最大编号，从 max+1 续号
        start_num = 1
        if os.path.isdir(output_root):
            max_n = 0
            for f in os.listdir(output_root):
                full = os.path.join(output_root, f)
                if not os.path.isfile(full):
                    continue
                if f.startswith('_'):
                    continue
                if not f.lower().endswith(SUPPORTED_INPUT_FORMATS):
                    continue
                stem = os.path.splitext(f)[0]
                m = re.search(r'(\d+)$', stem)
                if m:
                    n = int(m.group(1))
                    if n > max_n:
                        max_n = n
            if max_n > 0:
                start_num = max_n + 1

        for i, p in enumerate(images_sorted, start_num):
            if rename_prefix:
                new_name = f"{rename_prefix}_{i:06d}{ext}"
            else:
                new_name = f"{i:06d}{ext}"
            dst = os.path.join(output_root, new_name)
            pairs.append((p, dst))
    else:
        # 保留原目录结构
        for p in images:
            rel = os.path.relpath(p, input_root)
            base = os.path.splitext(rel)[0]
            dst = os.path.join(output_root, base + ext)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            pairs.append((p, dst))

    # 源路径 → 目标路径 映射（用于日志显示）
    src_to_dst = dict(pairs)

    if use_gpu and HAS_TORCH and torch.cuda.is_available():
        chunks = [pairs[i:i + batch_size] for i in range(0, total, batch_size)]
        done = 0
        with ThreadPoolExecutor(max_workers=2) as ex:
            futs = {ex.submit(resize_batch_gpu, c, size_mode, max_side,
                              canvas_w, canvas_h, fill_color, out_format,
                              jpg_quality, allow_upscale): c for c in chunks}
            for fut in as_completed(futs):
                if stop_event.is_set():
                    for f in futs:
                        f.cancel()
                    break
                try:
                    for img_path, ok, err in fut.result():
                        done += 1
                        if ok:
                            success += 1
                            src_name = os.path.basename(img_path)
                            dst = src_to_dst.get(img_path)
                            if dst and os.path.basename(dst) != src_name:
                                log(f"✓ {src_name}  →  {os.path.basename(dst)}")
                            else:
                                log(f"✓ {src_name}")
                        else:
                            fail += 1
                            log(f"✗ {os.path.basename(img_path)} - {err}")
                        yield done, total
                except Exception as e:
                    for p in futs[fut]:
                        done += 1
                        fail += 1
                        log(f"✗ {os.path.basename(p[0])} - {e}")
                        yield done, total
    else:
        workers = min(8, (os.cpu_count() or 4))
        done = 0
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(resize_one_cpu, p, d, size_mode, max_side,
                              canvas_w, canvas_h, fill_color, out_format,
                              jpg_quality, allow_upscale): p
                    for p, d in pairs}
            for fut in as_completed(futs):
                if stop_event.is_set():
                    for f in futs:
                        f.cancel()
                    break
                img_path = futs[fut]
                ok, err = fut.result()
                done += 1
                if ok:
                    success += 1
                    src_name = os.path.basename(img_path)
                    dst = src_to_dst.get(img_path)
                    if dst and os.path.basename(dst) != src_name:
                        log(f"✓ {src_name}  →  {os.path.basename(dst)}")
                    else:
                        log(f"✓ {src_name}")
                else:
                    fail += 1
                    log(f"✗ {os.path.basename(img_path)} - {err}")
                yield done, total

    yield ("DONE", success, fail)


# ================= 步骤 1.5：查重 =================
def run_dedup_step(images, work_dir, visual_th, diff_th, log, stop_event,
                   renumber_prefix=None):
    """查重：MD5 完全相同的移走；pHash 相近的移走；其余记录到 txt"""
    if not HAS_IMAGEHASH:
        log("⚠ 未安装 imagehash，跳过查重（pip install imagehash）")
        yield ("DONE", 0, 0)
        return

    total = len(images)
    if total == 0:
        yield ("DONE", 0, 0)
        return

    dup_pixel_dir = os.path.join(work_dir, "_重复_像素级")
    dup_visual_dir = os.path.join(work_dir, "_重复_视觉级")
    dup_diff_dir = os.path.join(work_dir, "_差分_待确认")

    log(f"🔍 开始查重：{total} 张图")
    log(f"   视觉阈值 = {visual_th}，差分阈值 = {diff_th}")

    # ---- 第 1 步：MD5 分组 ----
    def calc_md5(path):
        try:
            h = hashlib.md5()
            with open(path, 'rb') as fp:
                for chunk in iter(lambda: fp.read(65536), b''):
                    h.update(chunk)
            return h.hexdigest()
        except Exception:
            return None

    md5_map = {}
    done = 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(calc_md5, p): p for p in images}
        for fut in as_completed(futs):
            if stop_event.is_set():
                yield ("DONE", 0, 0)
                return
            p = futs[fut]
            try:
                md5 = fut.result()
                if md5:
                    md5_map.setdefault(md5, []).append(p)
            except Exception:
                pass
            done += 1
            if done % 50 == 0 or done == total:
                yield (done, total)

    # ---- 第 2 步：像素级去重 ----
    os.makedirs(dup_pixel_dir, exist_ok=True)
    survived = []
    pixel_moved = 0
    for md5, paths in md5_map.items():
        survived.append(paths[0])
        for p in paths[1:]:
            try:
                dst = os.path.join(dup_pixel_dir, os.path.basename(p))
                if os.path.exists(dst):
                    base, ext = os.path.splitext(os.path.basename(p))
                    ts = datetime.datetime.now().strftime("%H%M%S")
                    dst = os.path.join(dup_pixel_dir, f"{base}_{ts}{ext}")
                shutil.move(p, dst)
                pixel_moved += 1
            except Exception as e:
                log(f"✗ 移动 {os.path.basename(p)} 失败：{e}")

    log(f"✓ 像素级重复：{pixel_moved} 张 → {dup_pixel_dir}/")

    if len(survived) < 2:
        log("ℹ️ 剩余图片不足 2 张，跳过视觉级查重")
        yield ("DONE", pixel_moved, 0)
        return

    # ---- 第 3 步：计算 pHash ----
    log(f"   计算 {len(survived)} 张图的 pHash...")

    def calc_phash(path):
        try:
            with Image.open(path) as img:
                return imagehash.phash(img)
        except Exception:
            return None

    phash_list = []
    done = 0
    n2 = len(survived)
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(calc_phash, p): p for p in survived}
        for fut in as_completed(futs):
            if stop_event.is_set():
                yield ("DONE", pixel_moved, 0)
                return
            p = futs[fut]
            try:
                h = fut.result()
                if h is not None:
                    phash_list.append((p, h))
            except Exception:
                pass
            done += 1
            if done % 50 == 0 or done == n2:
                yield (done, n2)

    # ---- 第 4 步：贪心分组 ----
    groups = []
    for p, h in phash_list:
        if stop_event.is_set():
            break
        placed = False
        for g in groups:
            if h - g["rep"] <= diff_th:
                g["members"].append((p, h))
                placed = True
                break
        if not placed:
            groups.append({"rep": h, "members": [(p, h)]})

    # ---- 第 5 步：分类处理 ----
    os.makedirs(dup_visual_dir, exist_ok=True)
    os.makedirs(dup_diff_dir, exist_ok=True)
    visual_moved = 0
    diff_groups = []  # [[path1, path2, ...], [path3, ...]]

    def _score(path):
        try:
            with Image.open(path) as im:
                w, h = im.size
                pixels = w * h
        except Exception:
            pixels = 0
        try:
            size = os.path.getsize(path)
        except Exception:
            size = 0
        return (pixels, size)

    for g in groups:
        members = g["members"]
        if len(members) <= 1:
            continue
        members_sorted = sorted(members, key=lambda x: _score(x[0]),
                                reverse=True)
        keeper_path, keeper_hash = members_sorted[0]

        visual_dups = []
        diffs = []
        for p, h in members_sorted[1:]:
            dist = h - keeper_hash
            if dist <= visual_th:
                visual_dups.append(p)
            else:
                diffs.append(p)

        if diffs:
            # 有差分图 → 整组（含 keeper）移到 _差分_待确认/
            diff_groups.append([keeper_path] + visual_dups + diffs)
        else:
            # 纯视觉级重复 → 移走多余
            for p in visual_dups:
                try:
                    dst = os.path.join(dup_visual_dir, os.path.basename(p))
                    if os.path.exists(dst):
                        base, ext = os.path.splitext(os.path.basename(p))
                        ts = datetime.datetime.now().strftime("%H%M%S")
                        dst = os.path.join(dup_visual_dir, f"{base}_{ts}{ext}")
                    shutil.move(p, dst)
                    visual_moved += 1
                except Exception as e:
                    log(f"✗ 移动 {os.path.basename(p)} 失败：{e}")

    log(f"✓ 视觉级重复：{visual_moved} 张 → {dup_visual_dir}/")

    # ---- 第 5.5 步：移动差分图（每组独立子文件夹，保留原名） ----
    diff_moved = 0
    diff_records = []  # [(gid, [原文件名, ...]), ...]
    for gid, paths in enumerate(diff_groups, 1):
        group_dir = os.path.join(dup_diff_dir, f"G{gid:03d}")
        os.makedirs(group_dir, exist_ok=True)
        original_names = []
        for p in paths:
            name = os.path.basename(p)
            original_names.append(name)
            dst = os.path.join(group_dir, name)
            if os.path.exists(dst):
                # 万一有同名（罕见），加时间戳
                base, ext = os.path.splitext(name)
                ts = datetime.datetime.now().strftime("%H%M%S")
                dst = os.path.join(group_dir, f"{base}_{ts}{ext}")
            try:
                shutil.move(p, dst)
                diff_moved += 1
            except Exception as e:
                log(f"✗ 移动 {name} 失败：{e}")
        diff_records.append((gid, original_names))

    if diff_moved:
        log(f"✓ 差分候选：{diff_moved} 张 → {dup_diff_dir}/")

    # ---- 第 6 步：差分重复报告（已被删除，功能并入重复图片分类中，无需报告文件） ----
    
    # ---- 第 7 步：重新编号（仅当传入 renumber_prefix 时） ----
    if renumber_prefix is not None:
        try:
            files = [f for f in os.listdir(work_dir)
                     if os.path.isfile(os.path.join(work_dir, f))
                     and f.lower().endswith(SUPPORTED_INPUT_FORMATS)
                     and not f.startswith('_')]
            files.sort()
            if files:
                log(f"🔢 重新编号：{len(files)} 张图")
                # 两步走，避免重命名冲突
                tmp_map = []
                for old in files:
                    ext = os.path.splitext(old)[1].lower()
                    tmp = os.path.join(work_dir,
                                       f"__ren_tmp_{len(tmp_map)}.tmp")
                    try:
                        os.rename(os.path.join(work_dir, old), tmp)
                        tmp_map.append((tmp, ext))
                    except Exception as e:
                        log(f"✗ 重命名 {old} 失败：{e}")

                for i, (tmp, ext) in enumerate(tmp_map, 1):
                    if renumber_prefix:
                        new = f"{renumber_prefix}_{i:06d}{ext}"
                    else:
                        new = f"{i:06d}{ext}"
                    try:
                        os.rename(tmp, os.path.join(work_dir, new))
                    except Exception as e:
                        log(f"✗ 重命名到 {new} 失败：{e}")
                log(f"✓ 重新编号完成：{len(tmp_map)} 张")
        except Exception as e:
            log(f"✗ 重新编号异常：{e}")

    yield ("DONE",
           pixel_moved + visual_moved + diff_moved,
           len(diff_records))


# ================= 步骤 2：WD 打标 =================
def wd_preprocess(image_path, size=WD_MODEL_INPUT_SIZE):
    try:
        with Image.open(image_path) as raw:
            img = raw.convert("RGBA")
        canvas = Image.new("RGBA", img.size, (255, 255, 255, 255))
        canvas.alpha_composite(img)
        img = canvas.convert("RGB")
        max_dim = max(img.size)
        pl = (max_dim - img.size[0]) // 2
        pt = (max_dim - img.size[1]) // 2
        pr = max_dim - img.size[0] - pl
        pb = max_dim - img.size[1] - pt
        padded = ImageOps.expand(img, (pl, pt, pr, pb), fill=(255, 255, 255))
        if max_dim != size:
            padded = padded.resize((size, size), Image.BICUBIC)
        arr = np.asarray(padded, dtype=np.float32)
        return arr[:, :, ::-1]
    except Exception as e:
        print(f"预处理失败 {image_path}: {e}")
        return None


def wd_load_labels(csv_path):
    df = pd.read_csv(csv_path)
    names = df["name"].str.replace("_", " ").tolist()
    char_idx = set(df[df["category"] == 4].index.tolist())
    return names, char_idx


def wd_load_model(log_func=None):
    def log(m):
        if log_func:
            log_func(m)
        print(m)
    local_model = os.path.join(WD_LOCAL_MODEL_DIR, WD_MODEL_FILENAME)
    local_label = os.path.join(WD_LOCAL_MODEL_DIR, WD_LABEL_FILENAME)
    if os.path.isfile(local_model) and os.path.isfile(local_label):
        log(f"✅ 使用本地模型：{WD_LOCAL_MODEL_DIR}")
        return local_model, local_label
    raise RuntimeError(f"未找到本地模型，请放入 {WD_LOCAL_MODEL_DIR}")


class WDTagger:
    def __init__(self, model_path, label_path, use_gpu=True):
        available = ort.get_available_providers()
        if use_gpu and "CUDAExecutionProvider" in available:
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        else:
            providers = ["CPUExecutionProvider"]
        self.session = ort.InferenceSession(model_path, providers=providers)
        self.input_name = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name
        self.tag_names, self.char_idx = wd_load_labels(label_path)
        self.active_providers = self.session.get_providers()

    def interrogate_batch(self, image_paths, gen_th, char_th):
        n = len(image_paths)
        results = [None] * n
        batch_arrs, idx_map = [], []
        for i, p in enumerate(image_paths):
            arr = wd_preprocess(p)
            if arr is None:
                results[i] = (p, [], False, "预处理失败")
            else:
                batch_arrs.append(arr)
                idx_map.append(i)

        if not batch_arrs:
            return results

        try:
            batch = np.stack(batch_arrs, axis=0)
        except Exception as e:
            for i in idx_map:
                results[i] = (image_paths[i], [], False, f"堆叠失败: {e}")
            return results

        try:
            scores = self.session.run([self.output_name],
                                      {self.input_name: batch})[0]
        except Exception as e:
            for i in idx_map:
                results[i] = (image_paths[i], [], False, f"推理失败: {e}")
            return results

        for i, pred in zip(idx_map, scores):
            tags = []
            for j, s in enumerate(pred):
                th = char_th if j in self.char_idx else gen_th
                if s >= th:
                    tags.append((self.tag_names[j], float(s)))
            tags.sort(key=lambda x: x[1], reverse=True)
            results[i] = (image_paths[i], tags, True, None)
        return results


def run_tagger_step(images, input_root, output_root, gen_th, char_th,
                    batch_size, use_gpu, underscore, skip_existing,
                    log, stop_event):
    try:
        log("🔄 正在加载 WD Tagger 模型...")
        model_path, label_path = wd_load_model(log_func=log)
        tagger = WDTagger(model_path, label_path, use_gpu=use_gpu)
        log(f"✅ 推理引擎：{', '.join(tagger.active_providers)}")
    except Exception as e:
        log(f"❌ 模型加载失败：{e}")
        yield ("DONE", 0, len(images))
        return

    pairs = []
    for p in images:
        rel = os.path.relpath(p, input_root)
        base = os.path.splitext(rel)[0]
        txt_path = os.path.join(output_root, base + ".txt")
        os.makedirs(os.path.dirname(txt_path), exist_ok=True)
        pairs.append((p, txt_path))

    if skip_existing:
        before = len(pairs)
        pairs = [(p, t) for p, t in pairs if not os.path.isfile(t)]
        skipped = before - len(pairs)
        if skipped > 0:
            log(f"⏭ 跳过 {skipped} 张已有 txt 的图片")
        if not pairs:
            log("所有图片都已有 txt，跳过。")
            yield ("DONE", 0, 0)
            return

    total = len(pairs)
    success = fail = done = 0
    for i in range(0, total, batch_size):
        if stop_event.is_set():
            break
        chunk = pairs[i:i + batch_size]
        try:
            results = tagger.interrogate_batch([c[0] for c in chunk],
                                               gen_th, char_th)
        except Exception as e:
            for p, _ in chunk:
                done += 1
                fail += 1
                log(f"✗ {os.path.basename(p)} - {e}")
                yield done, total
            continue
        for (p, txt_path), (_, tags, ok, err) in zip(chunk, results):
            done += 1
            if not ok:
                fail += 1
                log(f"✗ {os.path.basename(p)} - {err}")
            else:
                strs = [t[0].replace(" ", "_") if underscore else t[0]
                        for t in tags]
                try:
                    with open(txt_path, "w", encoding="utf-8") as f:
                        f.write(", ".join(strs))
                    success += 1
                    log(f"✓ {os.path.basename(p)}  ({len(tags)} tags)")
                except Exception as e:
                    fail += 1
                    log(f"✗ {os.path.basename(p)} - 保存失败: {e}")
            yield done, total
    yield ("DONE", success, fail)


# ================= 步骤 3：Tag 精修 =================
def apply_tag_changes(tags, adds, removes, insert_pos, insert_index):
    remove_set = {r.lower() for r in removes}
    tags = [t for t in tags if t.lower() not in remove_set]
    seen, uniq = set(), []
    for t in tags:
        k = t.lower()
        if k not in seen:
            seen.add(k)
            uniq.append(t)
    tags = uniq
    existing = {t.lower() for t in tags}
    to_add = [a for a in adds if a.lower() not in existing]
    if to_add:
        if insert_pos == 'start':
            tags = to_add + tags
        elif insert_pos == 'end':
            tags = tags + to_add
        else:
            idx = max(0, min(insert_index, len(tags)))
            tags = tags[:idx] + to_add + tags[idx:]
    return tags


def run_refine_step(txt_files, adds, removes, insert_pos, insert_index,
                    backup_cfg, log, stop_event):
    total = len(txt_files)
    success = fail = done = 0
    for p in txt_files:
        if stop_event.is_set():
            break
        try:
            tags = read_tags(p)
            original = list(tags)
            new_tags = apply_tag_changes(tags, adds, removes,
                                         insert_pos, insert_index)
            if new_tags != original:
                write_tags(p, new_tags, backup_cfg=backup_cfg)
                success += 1
                log(f"✓ {os.path.basename(p)}  ({len(original)} → {len(new_tags)})")
            else:
                log(f"· {os.path.basename(p)}  无变化")
        except Exception as e:
            fail += 1
            log(f"✗ {os.path.basename(p)} - {e}")
        done += 1
        yield done, total
    yield ("DONE", success, fail)


# ================= Tab 1：一键流水线（双列布局） =================
class PipelineTab(BaseWorkerTab):
    def __init__(self, parent, root):
        super().__init__(parent, root)

        self.input_dir = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.do_resize = tk.BooleanVar(value=True)
        self.do_tag = tk.BooleanVar(value=True)
        self.do_refine = tk.BooleanVar(value=False)

        self.size_mode = tk.StringVar(value="max_side")
        self.max_side = tk.IntVar(value=2048)
        self.canvas_w = tk.IntVar(value=1080)
        self.canvas_h = tk.IntVar(value=1080)
        self.fill_color = (255, 255, 255)
        self.out_format = tk.StringVar(value="PNG")
        self.jpg_quality = tk.IntVar(value=95)
        self.allow_upscale = tk.BooleanVar(value=False)
        self.resize_gpu = tk.BooleanVar(value=True)
        self.resize_batch = tk.IntVar(value=8)

        self.gen_th = tk.DoubleVar(value=0.35)
        self.char_th = tk.DoubleVar(value=0.85)
        self.tag_batch = tk.IntVar(value=8)
        self.tag_gpu = tk.BooleanVar(value=True)
        self.tag_underscore = tk.BooleanVar(value=False)
        self.skip_existing = tk.BooleanVar(value=True)
        self.cuda_ok, self.cuda_msg = detect_cuda_support()
        self.torch_cuda_ok, self.torch_cuda_msg = detect_torch_cuda()

        self.manifest_path = tk.StringVar()
        self.manual_add = tk.StringVar()
        self.manual_rm = tk.StringVar()
        self.refine_pos = tk.StringVar(value="末尾")

        # ---- 统一命名（步骤 1）----
        self.do_rename = tk.BooleanVar(value=False)
        self.rename_prefix = tk.StringVar(value="")

        # ---- 查重（步骤 1.5）----
        self.do_dedup = tk.BooleanVar(value=False)
        self.dedup_visual_th = tk.IntVar(value=2)
        self.dedup_diff_th = tk.IntVar(value=8)

        self._build_ui()
        self.root.after(100, self._check_queue)

    def _build_ui(self):
        # ---------- 顶部：路径 ----------
        top = ttk.LabelFrame(self.parent, text=" 路径 ", padding=12)
        top.pack(fill=tk.X, padx=15, pady=(12, 6))

        row = ttk.Frame(top)
        row.pack(fill=tk.X, pady=3)
        ttk.Label(row, text="输入文件夹", width=11).pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=self.input_dir).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        ttk.Button(row, text="浏览", width=8,
                   command=lambda: pick_dir(self.input_dir, "last_input")
                   ).pack(side=tk.LEFT)

        row = ttk.Frame(top)
        row.pack(fill=tk.X, pady=3)
        ttk.Label(row, text="输出文件夹", width=11).pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=self.output_dir).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        ttk.Button(row, text="浏览", width=8,
                   command=lambda: pick_dir(self.output_dir, "last_output")
                   ).pack(side=tk.LEFT)
        tk.Label(top, text="※ 缩放后图片和打标 txt 都会放到输出文件夹里",
                 font=('Microsoft YaHei UI', 8), fg=COLOR["muted"],
                 bg=COLOR["card"]).pack(anchor=tk.W, pady=(4, 0))

        # ---------- 中部：左设置 + 右日志 ----------
        left, right = build_split_columns(self.parent, left_min=620)
        self._build_steps(left)
        self._build_backup(left)
        self._build_log(right)

        # ---------- 底部：按钮 + 状态 + 进度条 ----------
        bar, status_var, progress = build_footer(self.parent)
        self.status = status_var
        self.progress = progress

        self.start_btn = ttk.Button(bar, text="▶  开始一键流水线",
                                    style='Primary.TButton', command=self.start)
        self.start_btn.pack(side=tk.LEFT)
        self.stop_btn = ttk.Button(bar, text="■  停止", command=self.stop,
                                   state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=8)

    def _build_steps(self, parent):
        steps = ttk.LabelFrame(parent, text=" 流水线步骤 ", padding=12)
        steps.pack(fill=tk.X, pady=(0, 6))

        # 步骤 1
        row = ttk.Frame(steps)
        row.pack(fill=tk.X, pady=3)
        ttk.Checkbutton(row, text="步骤 1 · 尺寸统一",
                        variable=self.do_resize).pack(side=tk.LEFT)
        ttk.Radiobutton(row, text="最长边", variable=self.size_mode,
                        value="max_side").pack(side=tk.LEFT, padx=(20, 4))
        ttk.Entry(row, textvariable=self.max_side, width=7).pack(side=tk.LEFT)
        ttk.Radiobutton(row, text="画布", variable=self.size_mode,
                        value="canvas").pack(side=tk.LEFT, padx=(12, 4))
        ttk.Entry(row, textvariable=self.canvas_w, width=6).pack(side=tk.LEFT)
        ttk.Label(row, text="×").pack(side=tk.LEFT, padx=2)
        ttk.Entry(row, textvariable=self.canvas_h, width=6).pack(side=tk.LEFT)
        ttk.Label(row, text="填充:").pack(side=tk.LEFT, padx=(10, 2))
        self.pipe_color_btn = tk.Button(row, bg='#ffffff', width=3,
                                        relief=tk.SOLID,
                                        command=self._choose_pipe_color)
        self.pipe_color_btn.pack(side=tk.LEFT)

        row = ttk.Frame(steps)
        row.pack(fill=tk.X, pady=3)
        ttk.Label(row, text="").pack(side=tk.LEFT, padx=(118, 0))
        ttk.Label(row, text="格式:").pack(side=tk.LEFT)
        ttk.Combobox(row, textvariable=self.out_format, values=["PNG", "JPG"],
                     width=5, state="readonly").pack(side=tk.LEFT, padx=(4, 12))
        ttk.Checkbutton(row, text="允许放大",
                        variable=self.allow_upscale).pack(side=tk.LEFT, padx=(0, 12))

        cb_resize_gpu = ttk.Checkbutton(row, text="GPU",
                                        variable=self.resize_gpu)
        cb_resize_gpu.pack(side=tk.LEFT)
        if not self.torch_cuda_ok:
            self.resize_gpu.set(False)
            cb_resize_gpu.state(["disabled"])
            ttk.Label(row, text=f"（{self.torch_cuda_msg}）",
                      foreground=COLOR["muted"],
                      font=('Microsoft YaHei UI', 8)
                      ).pack(side=tk.LEFT, padx=(4, 0))

        # 统一命名
        row = ttk.Frame(steps)
        row.pack(fill=tk.X, pady=3)
        ttk.Label(row, text="").pack(side=tk.LEFT, padx=(118, 0))
        ttk.Checkbutton(row, text="统一命名",
                        variable=self.do_rename).pack(side=tk.LEFT)
        ttk.Label(row, text="前缀:").pack(side=tk.LEFT, padx=(8, 2))
        ttk.Entry(row, textvariable=self.rename_prefix,
                  width=16).pack(side=tk.LEFT)
        ttk.Label(row, text="  (留空=纯序号 000001；填 lora=lora_000001)",
                  font=('Microsoft YaHei UI', 8),
                  foreground=COLOR["muted"]).pack(side=tk.LEFT, padx=(6, 0))

        # 步骤 1.5 · 查重
        row = ttk.Frame(steps)
        row.pack(fill=tk.X, pady=3)
        ttk.Checkbutton(row, text="步骤 1.5 · 查重",
                        variable=self.do_dedup).pack(side=tk.LEFT)
        ttk.Label(row, text="视觉阈值:").pack(side=tk.LEFT, padx=(20, 4))
        ttk.Spinbox(row, from_=0, to=10,
                    textvariable=self.dedup_visual_th,
                    width=5).pack(side=tk.LEFT)
        ttk.Label(row, text="差分阈值:").pack(side=tk.LEFT, padx=(8, 4))
        ttk.Spinbox(row, from_=0, to=20,
                    textvariable=self.dedup_diff_th,
                    width=5).pack(side=tk.LEFT)
        ttk.Label(row, text="  (≤视觉=自动移走 / 视觉~差分=写报告)",
                  font=('Microsoft YaHei UI', 8),
                  foreground=COLOR["muted"]).pack(side=tk.LEFT, padx=(8, 0))
        
        # 步骤 2
        row = ttk.Frame(steps)
        row.pack(fill=tk.X, pady=3)
        ttk.Checkbutton(row, text="步骤 2 · WD 打标",
                        variable=self.do_tag).pack(side=tk.LEFT)
        ttk.Label(row, text="通用:").pack(side=tk.LEFT, padx=(20, 4))
        ttk.Spinbox(row, from_=0, to=1, increment=0.05,
                    textvariable=self.gen_th, width=5).pack(side=tk.LEFT)
        ttk.Label(row, text="角色:").pack(side=tk.LEFT, padx=(8, 4))
        ttk.Spinbox(row, from_=0, to=1, increment=0.05,
                    textvariable=self.char_th, width=5).pack(side=tk.LEFT)
        ttk.Label(row, text="批:").pack(side=tk.LEFT, padx=(8, 4))
        ttk.Spinbox(row, from_=1, to=32,
                    textvariable=self.tag_batch, width=4).pack(side=tk.LEFT)
        cb_gpu = ttk.Checkbutton(row, text="GPU",
                                 variable=self.tag_gpu)
        cb_gpu.pack(side=tk.LEFT, padx=(10, 0))
        if not self.cuda_ok:
            self.tag_gpu.set(False)
            cb_gpu.state(["disabled"])
            ttk.Label(row, text=f"（{self.cuda_msg}）",
                      foreground=COLOR["muted"],
                      font=('Microsoft YaHei UI', 8)
                      ).pack(side=tk.LEFT, padx=(4, 0))

        ttk.Checkbutton(row, text="跳过已有",
                        variable=self.skip_existing).pack(side=tk.LEFT, padx=(6, 0))

        # 步骤 3
        row = ttk.Frame(steps)
        row.pack(fill=tk.X, pady=3)
        ttk.Checkbutton(row, text="步骤 3 · Tag 精修",
                        variable=self.do_refine).pack(side=tk.LEFT)
        ttk.Label(row, text="清单:").pack(side=tk.LEFT, padx=(20, 4))
        ttk.Entry(row, textvariable=self.manifest_path).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        ttk.Button(row, text="浏览", width=6,
                   command=lambda: pick_file(self.manifest_path, "last_manifest",
                                             filetypes=[("文本", "*.txt"),
                                                        ("所有", "*.*")])
                   ).pack(side=tk.LEFT)

        row = ttk.Frame(steps)
        row.pack(fill=tk.X, pady=3)
        ttk.Label(row, text="额外新增:").pack(side=tk.LEFT, padx=(128, 4))
        ttk.Entry(row, textvariable=self.manual_add).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 12))
        ttk.Label(row, text="额外删除:").pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=self.manual_rm).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))

        row = ttk.Frame(steps)
        row.pack(fill=tk.X, pady=3)
        ttk.Label(row, text="新增位置:").pack(side=tk.LEFT, padx=(128, 4))
        ttk.Combobox(row, textvariable=self.refine_pos,
                     values=["开头", "末尾"], width=6, state="readonly"
                     ).pack(side=tk.LEFT)

    def _build_backup(self, parent):
        self.backup_opts = BackupOptions(
            parent,
            base_root_getter=lambda: self.output_dir.get(),
            title=" 备份设置（仅步骤 3 生效） ")
        self.backup_opts.pack(fill=tk.X)

    def _build_log(self, parent):
        self.log_panel = LogPanel(parent, self.root)

        # 把 GPU 检测结果写到日志，方便用户排查
        if self.torch_cuda_ok:
            self.log_panel.log("✓ 尺寸统一：已检测到 CUDA，可使用 GPU 加速")
        else:
            self.log_panel.log(
                f"⚠ 尺寸统一：{self.torch_cuda_msg}（GPU 选项已禁用）")
            self.log_panel.log(
                "   → 想启用：安装 NVIDIA 驱动 + CUDA Toolkit，并确保 "
                "torch 是 GPU 版本")

        if self.cuda_ok:
            self.log_panel.log("✓ WD 打标：已检测到 CUDA，可使用 GPU 加速")
        else:
            self.log_panel.log(
                f"⚠ WD 打标：{self.cuda_msg}（GPU 选项已禁用）")
            self.log_panel.log(
                "   → 想启用：装 NVIDIA 驱动 + CUDA Toolkit + cuDNN，"
                "再 pip install onnxruntime-gpu")

    def _choose_pipe_color(self):
        c = colorchooser.askcolor(initialcolor=self.fill_color)
        if c[0]:
            self.fill_color = tuple(int(x) for x in c[0])
            self.pipe_color_btn.config(bg=c[1])

    def start(self):
        if self.is_running:
            return
        in_dir = self.input_dir.get().strip()
        out_dir = self.output_dir.get().strip()
        if not in_dir or not os.path.isdir(in_dir):
            messagebox.showerror("错误", "请选择有效的输入文件夹")
            return
        if not out_dir:
            messagebox.showerror("错误", "请选择输出文件夹")
            return
        if os.path.abspath(in_dir) == os.path.abspath(out_dir):
            messagebox.showerror("错误", "输入和输出不能是同一文件夹")
            return
                # ---- 流程安全检查 ----
        if self.do_dedup.get() and not self.do_resize.get():
            if not messagebox.askyesno(
                "⚠ 警告：未勾选步骤 1",
                "查重将直接在【输入文件夹】里操作！\n\n"
                "原文件可能会被移动到：\n"
                "    _重复_像素级/\n"
                "    _重复_视觉级/\n"
                "    _差分_待确认/\n\n"
                "强烈建议勾选【步骤 1 · 尺寸统一】让操作在输出文件夹进行。\n\n"
                "确定要继续吗？"):
                return
        if not (self.do_resize.get() or self.do_tag.get() or self.do_refine.get()):
            messagebox.showinfo("提示", "至少勾选一个步骤")
            return

        self._begin()
        t = threading.Thread(target=self._run, args=(in_dir, out_dir),
                             daemon=True)
        t.start()

    def _run(self, in_dir, out_dir):
        try:
            os.makedirs(out_dir, exist_ok=True)
            q = self.queue
            # ★ 记录本次流程开始时间（用于过滤精修范围）
            import time as _time
            run_start_ts = _time.time()

            if self.do_resize.get():
                q.put(("log", "\n========== 步骤 1：尺寸统一 =========="))
                images = find_images(in_dir, recursive=True)
                if not images:
                    q.put(("log", "未找到图片"))
                else:
                    q.put(("log", f"找到 {len(images)} 张图片"))
                    q.put(("phase_total", len(images)))
                    rename_prefix_arg = (
                        self.rename_prefix.get().strip()
                        if self.do_rename.get() else None
                    )
                    for item in run_resize_step(
                        images, in_dir, out_dir, self.size_mode.get(),
                        int(self.max_side.get()), int(self.canvas_w.get()),
                        int(self.canvas_h.get()), self.fill_color,
                        self.out_format.get(), int(self.jpg_quality.get()),
                        self.resize_gpu.get(), int(self.resize_batch.get()),
                        self.allow_upscale.get(),
                        lambda m: q.put(("log", m)), self.stop_event,
                        rename_prefix=rename_prefix_arg
                    ):
                        if item[0] == "DONE":
                            q.put(("log", f"步骤 1 完成：成功 {item[1]}，失败 {item[2]}"))
                        else:
                            q.put(("progress", item[0], item[1]))
                if self.stop_event.is_set():
                    raise InterruptedError
                if self.resize_gpu.get() and HAS_TORCH:
                    try:
                        torch.cuda.synchronize()
                        gc.collect()
                        torch.cuda.empty_cache()
                        q.put(("log", "🧹 已释放尺寸统一阶段显存"))
                    except Exception:
                        pass

            work_dir = out_dir if self.do_resize.get() else in_dir
            txt_dir = out_dir if (self.do_resize.get() or self.do_tag.get()) else in_dir

            # ---------- 步骤 1.5：查重 ----------
            if self.do_dedup.get():
                if not HAS_IMAGEHASH:
                    q.put(("log", "❌ 未安装 imagehash，跳过查重"
                                  "（pip install imagehash）"))
                else:
                    q.put(("log", "\n========== 步骤 1.5：查重 =========="))
                    dedup_images = find_images(work_dir, recursive=True)
                    if not dedup_images:
                        q.put(("log", "未找到图片"))
                    else:
                        q.put(("log", f"找到 {len(dedup_images)} 张图片"))
                        q.put(("phase_total", len(dedup_images)))
                        vth = int(self.dedup_visual_th.get())
                        dth = int(self.dedup_diff_th.get())
                        if vth >= dth:
                            q.put(("log",
                                   f"⚠ 视觉阈值({vth}) ≥ 差分阈值({dth})，"
                                   f"将无差分报告"))
                        renumber_prefix_arg = None
                        if self.do_resize.get() and self.do_rename.get():
                            renumber_prefix_arg = (
                                self.rename_prefix.get().strip())

                        for item in run_dedup_step(
                            dedup_images, work_dir, vth, dth,
                            lambda m: q.put(("log", m)), self.stop_event,
                            renumber_prefix=renumber_prefix_arg
                        ):
                            if item[0] == "DONE":
                                q.put(("log",
                                       f"步骤 1.5 完成：移走重复 {item[1]} 张，"
                                       f"差分候选 {item[2]} 对"))
                            else:
                                q.put(("progress", item[0], item[1]))
                    if self.stop_event.is_set():
                        raise InterruptedError
                    
            if self.do_tag.get():
                if not HAS_ORT:
                    q.put(("log", "❌ 未安装 onnxruntime/pandas，跳过打标"))
                else:
                    q.put(("log", "\n========== 步骤 2：WD 打标 =========="))
                    images = find_images(work_dir, recursive=True)
                    if not images:
                        q.put(("log", "未找到图片"))
                    else:
                        q.put(("log", f"找到 {len(images)} 张图片"))
                        q.put(("phase_total", len(images)))
                        for item in run_tagger_step(
                            images, work_dir, txt_dir,
                            float(self.gen_th.get()), float(self.char_th.get()),
                            int(self.tag_batch.get()), self.tag_gpu.get(),
                            self.tag_underscore.get(), self.skip_existing.get(),
                            lambda m: q.put(("log", m)), self.stop_event
                        ):
                            if item[0] == "DONE":
                                q.put(("log", f"步骤 2 完成：成功 {item[1]}，失败 {item[2]}"))
                            else:
                                q.put(("progress", item[0], item[1]))
                    if self.stop_event.is_set():
                        raise InterruptedError
                    if self.tag_gpu.get() and HAS_ORT:
                        gc.collect()
                        q.put(("log", "🧹 已释放打标阶段显存"))

            if self.do_refine.get():
                q.put(("log", "\n========== 步骤 3：Tag 精修 =========="))
                adds, removes = [], []
                mf = self.manifest_path.get().strip()
                if mf and os.path.isfile(mf):
                    try:
                        a, r = parse_manifest(mf)
                        adds.extend(a)
                        removes.extend(r)
                        q.put(("log", f"清单：+{len(a)}  -{len(r)}"))
                    except Exception as e:
                        q.put(("log", f"清单解析失败：{e}"))
                adds.extend(parse_manual_text(self.manual_add.get()))
                removes.extend(parse_manual_text(self.manual_rm.get()))

                def dedup(lst):
                    seen, out = set(), []
                    for x in lst:
                        k = x.lower()
                        if k not in seen:
                            seen.add(k)
                            out.append(x)
                    return out
                adds = dedup(adds)
                removes = dedup(removes)

                backup_cfg = self.backup_opts.get_cfg()
                if backup_cfg["enabled"]:
                    if backup_cfg["mode"] == "custom" and not backup_cfg["dir"]:
                        q.put(("log", "⚠ 备份目录为空，本次不备份"))
                        backup_cfg["enabled"] = False
                    else:
                        mode_txt = ("同目录" if backup_cfg["mode"] == "same"
                                    else f"指定目录 {backup_cfg['dir']}")
                        q.put(("log", f"💾 备份已开启：{mode_txt}"))

                if not adds and not removes:
                    q.put(("log", "没有要增删的 tag，跳过步骤 3"))
                else:
                    pos = "start" if self.refine_pos.get() == "开头" else "end"
                    q.put(("log", f"新增 {len(adds)}，删除 {len(removes)}，位置：{self.refine_pos.get()}"))
                    txt_files = find_txt_files(txt_dir, recursive=True)

                    # ★ 若本次流程做过 resize 或 tag，只精修本次新产生的 txt
                    if self.do_resize.get() or self.do_tag.get():
                        before = len(txt_files)
                        threshold = run_start_ts - 5
                        txt_files = [
                            p for p in txt_files
                            if os.path.getmtime(p) >= threshold
                        ]
                        skipped = before - len(txt_files)
                        if skipped > 0:
                            q.put(("log",
                                   f"⏭ 跳过 {skipped} 个旧 txt（非本次流程产生）"))

                    if not txt_files:
                        q.put(("log", "未找到任何 txt"))
                    else:
                        q.put(("log", f"找到 {len(txt_files)} 个 txt"))
                        q.put(("phase_total", len(txt_files)))
                        for item in run_refine_step(
                            txt_files, adds, removes, pos, 0,
                            backup_cfg,
                            lambda m: q.put(("log", m)), self.stop_event
                        ):
                            if item[0] == "DONE":
                                q.put(("log", f"步骤 3 完成：修改 {item[1]}，失败 {item[2]}"))
                            else:
                                q.put(("progress", item[0], item[1]))

            q.put(("finished", True, "流水线全部完成！"))
        except InterruptedError:
            q.put(("finished", False, "已被用户停止"))
        except Exception as e:
            import traceback
            q.put(("log", f"❌ 异常：{e}"))
            q.put(("log", traceback.format_exc()))
            q.put(("finished", False, f"出错：{e}"))


# ================= Tab 2：尺寸统一（双列布局） =================
class ResizeTab(BaseWorkerTab):
    def __init__(self, parent, root):
        super().__init__(parent, root)

        self.input_dir = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.size_mode = tk.StringVar(value="max_side")
        self.max_side = tk.IntVar(value=2048)
        self.canvas_w = tk.IntVar(value=1080)
        self.canvas_h = tk.IntVar(value=1080)
        self.fill_color = (255, 255, 255)
        self.out_format = tk.StringVar(value="PNG")
        self.jpg_quality = tk.IntVar(value=95)
        self.allow_upscale = tk.BooleanVar(value=False)
        self.use_gpu = tk.BooleanVar(value=True)
        self.batch_size = tk.IntVar(value=8)
        self.torch_cuda_ok, self.torch_cuda_msg = detect_torch_cuda()

        self._build_ui()
        self.root.after(100, self._check_queue)

    def _build_ui(self):
        # 路径
        top = ttk.LabelFrame(self.parent, text=" 路径 ", padding=12)
        top.pack(fill=tk.X, padx=15, pady=(12, 6))

        row = ttk.Frame(top)
        row.pack(fill=tk.X, pady=3)
        ttk.Label(row, text="输入文件夹", width=11).pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=self.input_dir).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        ttk.Button(row, text="浏览", width=8,
                   command=lambda: pick_dir(self.input_dir, "last_input")
                   ).pack(side=tk.LEFT)

        row = ttk.Frame(top)
        row.pack(fill=tk.X, pady=3)
        ttk.Label(row, text="输出文件夹", width=11).pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=self.output_dir).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        ttk.Button(row, text="浏览", width=8,
                   command=lambda: pick_dir(self.output_dir, "last_output")
                   ).pack(side=tk.LEFT)

        # 双列
        left, right = build_split_columns(self.parent, left_min=620)
        self._build_options(left)
        self.log_panel = LogPanel(right, self.root)

        # 底部
        bar, status_var, progress = build_footer(self.parent)
        self.status = status_var
        self.progress = progress

        self.start_btn = ttk.Button(bar, text="▶  开始",
                                    style='Primary.TButton', command=self.start)
        self.start_btn.pack(side=tk.LEFT)
        self.stop_btn = ttk.Button(bar, text="■  停止", state=tk.DISABLED,
                                   command=self.stop)
        self.stop_btn.pack(side=tk.LEFT, padx=8)

    def _build_options(self, parent):
        opt = ttk.LabelFrame(parent, text=" 模式与参数 ", padding=12)
        opt.pack(fill=tk.X)

        row = ttk.Frame(opt)
        row.pack(fill=tk.X, pady=3)
        ttk.Radiobutton(row, text="最长边缩放（保持比例）",
                        variable=self.size_mode, value="max_side").pack(side=tk.LEFT)
        ttk.Label(row, text="最长边:").pack(side=tk.LEFT, padx=(16, 4))
        ttk.Entry(row, textvariable=self.max_side, width=8).pack(side=tk.LEFT)

        row = ttk.Frame(opt)
        row.pack(fill=tk.X, pady=3)
        ttk.Radiobutton(row, text="固定画布 + 填充背景",
                        variable=self.size_mode, value="canvas").pack(side=tk.LEFT)
        ttk.Label(row, text="画布宽:").pack(side=tk.LEFT, padx=(16, 4))
        ttk.Entry(row, textvariable=self.canvas_w, width=7).pack(side=tk.LEFT)
        ttk.Label(row, text="×").pack(side=tk.LEFT, padx=3)
        ttk.Entry(row, textvariable=self.canvas_h, width=7).pack(side=tk.LEFT)
        ttk.Label(row, text="填充:").pack(side=tk.LEFT, padx=(10, 4))
        self.color_btn = tk.Button(row, bg="#ffffff", width=4, relief=tk.SOLID,
                                   command=self._choose_color)
        self.color_btn.pack(side=tk.LEFT)

        row = ttk.Frame(opt)
        row.pack(fill=tk.X, pady=3)
        ttk.Label(row, text="格式:").pack(side=tk.LEFT)
        ttk.Combobox(row, textvariable=self.out_format, values=["PNG", "JPG"],
                     width=6, state="readonly").pack(side=tk.LEFT, padx=(4, 12))
        ttk.Label(row, text="JPG 质量:").pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=self.jpg_quality, width=6).pack(
            side=tk.LEFT, padx=(4, 12))
        ttk.Label(row, text="批大小:").pack(side=tk.LEFT)
        ttk.Spinbox(row, from_=1, to=32, textvariable=self.batch_size,
                    width=5).pack(side=tk.LEFT, padx=(4, 12))

        cb_gpu = ttk.Checkbutton(row, text="使用 GPU",
                                 variable=self.use_gpu)
        cb_gpu.pack(side=tk.LEFT, padx=(0, 6))
        if not self.torch_cuda_ok:
            self.use_gpu.set(False)
            cb_gpu.state(["disabled"])
            ttk.Label(row, text=f"（{self.torch_cuda_msg}）",
                      foreground=COLOR["muted"],
                      font=('Microsoft YaHei UI', 8)
                      ).pack(side=tk.LEFT, padx=(0, 10))
        else:
            ttk.Label(row, text=f"（{self.torch_cuda_msg}）",
                      foreground=COLOR["success"],
                      font=('Microsoft YaHei UI', 8)
                      ).pack(side=tk.LEFT, padx=(0, 10))

        # ---- 新增一行：把"允许放大"单独放这里 ----
        row2 = ttk.Frame(opt)
        row2.pack(fill=tk.X, pady=3)
        ttk.Checkbutton(row2, text="允许放大",
                        variable=self.allow_upscale).pack(side=tk.LEFT)

    def _choose_color(self):
        c = colorchooser.askcolor(initialcolor=self.fill_color)
        if c[0]:
            self.fill_color = tuple(int(x) for x in c[0])
            self.color_btn.config(bg=c[1])

    def start(self):
        if self.is_running:
            return
        in_dir = self.input_dir.get().strip()
        out_dir = self.output_dir.get().strip()
        if not in_dir or not os.path.isdir(in_dir):
            messagebox.showerror("错误", "请选择有效的输入文件夹")
            return
        if not out_dir:
            messagebox.showerror("错误", "请选择输出文件夹")
            return
        images = find_images(in_dir, recursive=True)
        if not images:
            messagebox.showinfo("提示", "没有找到任何图片")
            return

        self._begin(len(images))
        t = threading.Thread(target=self._run, args=(images, in_dir, out_dir),
                             daemon=True)
        t.start()

    def _run(self, images, in_dir, out_dir):
        try:
            for item in run_resize_step(
                images, in_dir, out_dir, self.size_mode.get(),
                int(self.max_side.get()), int(self.canvas_w.get()),
                int(self.canvas_h.get()), self.fill_color,
                self.out_format.get(), int(self.jpg_quality.get()),
                self.use_gpu.get(), int(self.batch_size.get()),
                self.allow_upscale.get(),
                lambda m: self.queue.put(("log", m)), self.stop_event
            ):
                if item[0] == "DONE":
                    self.queue.put(("finished", True,
                                    f"完成！成功 {item[1]}，失败 {item[2]}"))
                else:
                    self.queue.put(("progress", item[0], item[1]))
        except Exception as e:
            self.queue.put(("finished", False, f"异常：{e}"))


# ================= Tab 3：WD 打标（双列布局） =================
class TaggerTab(BaseWorkerTab):
    def __init__(self, parent, root):
        super().__init__(parent, root)
        self.input_dir = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.gen_th = tk.DoubleVar(value=0.35)
        self.char_th = tk.DoubleVar(value=0.85)
        self.batch_size = tk.IntVar(value=8)
        self.use_gpu = tk.BooleanVar(value=True)
        self.underscore = tk.BooleanVar(value=False)
        self.skip_existing = tk.BooleanVar(value=False)
        self.cuda_ok, self.cuda_msg = detect_cuda_support()
        self.torch_cuda_ok, self.torch_cuda_msg = detect_torch_cuda()
        self._build_ui()
        self.root.after(100, self._check_queue)

    def _build_ui(self):
        top = ttk.LabelFrame(self.parent, text=" 路径 ", padding=12)
        top.pack(fill=tk.X, padx=15, pady=(12, 6))

        row = ttk.Frame(top)
        row.pack(fill=tk.X, pady=3)
        ttk.Label(row, text="图片文件夹", width=11).pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=self.input_dir).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        ttk.Button(row, text="浏览", width=8,
                   command=lambda: pick_dir(self.input_dir, "last_input")
                   ).pack(side=tk.LEFT)

        row = ttk.Frame(top)
        row.pack(fill=tk.X, pady=3)
        ttk.Label(row, text="输出文件夹", width=11).pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=self.output_dir).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        ttk.Button(row, text="浏览", width=8,
                   command=lambda: pick_dir(self.output_dir, "last_output")
                   ).pack(side=tk.LEFT)
        tk.Label(top, text="※ 输出文件夹留空 = txt 与图片放一起",
                 font=('Microsoft YaHei UI', 8), fg=COLOR["muted"],
                 bg=COLOR["card"]).pack(anchor=tk.W, pady=(4, 0))

        left, right = build_split_columns(self.parent, left_min=620)
        self._build_options(left)
        self.log_panel = LogPanel(right, self.root)

        bar, status_var, progress = build_footer(self.parent)
        self.status = status_var
        self.progress = progress

        self.start_btn = ttk.Button(bar, text="▶  开始打标",
                                    style='Primary.TButton', command=self.start)
        self.start_btn.pack(side=tk.LEFT)
        self.stop_btn = ttk.Button(bar, text="■  停止", state=tk.DISABLED,
                                   command=self.stop)
        self.stop_btn.pack(side=tk.LEFT, padx=8)

        if not HAS_ORT:
            self.start_btn.config(state=tk.DISABLED)
            self.log_panel.log("⚠ 未安装 onnxruntime 或 pandas，打标不可用")

    def _build_options(self, parent):
        opt = ttk.LabelFrame(parent, text=" 参数 ", padding=12)
        opt.pack(fill=tk.X)

        row = ttk.Frame(opt)
        row.pack(fill=tk.X, pady=3)
        ttk.Label(row, text="通用阈值:").pack(side=tk.LEFT)
        ttk.Spinbox(row, from_=0, to=1, increment=0.05,
                    textvariable=self.gen_th, width=6).pack(side=tk.LEFT, padx=(6, 16))
        ttk.Label(row, text="角色阈值:").pack(side=tk.LEFT)
        ttk.Spinbox(row, from_=0, to=1, increment=0.05,
                    textvariable=self.char_th, width=6).pack(side=tk.LEFT, padx=(6, 16))
        ttk.Label(row, text="批大小:").pack(side=tk.LEFT)
        ttk.Spinbox(row, from_=1, to=32,
                    textvariable=self.batch_size, width=6).pack(side=tk.LEFT, padx=(6, 0))

        row = ttk.Frame(opt)
        row.pack(fill=tk.X, pady=3)

        cb_gpu = ttk.Checkbutton(row, text="使用 GPU",
                                 variable=self.use_gpu)
        cb_gpu.pack(side=tk.LEFT, padx=(0, 6))
        if not self.cuda_ok:
            self.use_gpu.set(False)
            cb_gpu.state(["disabled"])
            ttk.Label(row, text=f"（{self.cuda_msg}）",
                      foreground=COLOR["muted"],
                      font=('Microsoft YaHei UI', 8)
                      ).pack(side=tk.LEFT, padx=(0, 12))
        else:
            ttk.Label(row, text=f"（{self.cuda_msg}）",
                      foreground=COLOR["success"],
                      font=('Microsoft YaHei UI', 8)
                      ).pack(side=tk.LEFT, padx=(0, 12))

        ttk.Checkbutton(row, text="跳过已有 txt",
                        variable=self.skip_existing).pack(side=tk.LEFT, padx=(0, 18))
        ttk.Checkbutton(row, text="标签用下划线替换空格",
                        variable=self.underscore).pack(side=tk.LEFT)

    def start(self):
        if self.is_running:
            return
        in_dir = self.input_dir.get().strip()
        out_dir = self.output_dir.get().strip()
        if not in_dir or not os.path.isdir(in_dir):
            messagebox.showerror("错误", "请选择有效的图片文件夹")
            return
        images = find_images(in_dir, recursive=True)
        if not images:
            messagebox.showinfo("提示", "没有找到任何图片")
            return
        txt_root = out_dir if out_dir else in_dir
        self._begin(len(images))
        t = threading.Thread(target=self._run,
                             args=(images, in_dir, txt_root), daemon=True)
        t.start()

    def _run(self, images, in_dir, txt_root):
        try:
            for item in run_tagger_step(
                images, in_dir, txt_root,
                float(self.gen_th.get()), float(self.char_th.get()),
                int(self.batch_size.get()), self.use_gpu.get(),
                self.underscore.get(), self.skip_existing.get(),
                lambda m: self.queue.put(("log", m)), self.stop_event
            ):
                if item[0] == "DONE":
                    self.queue.put(("finished", True,
                                    f"完成！成功 {item[1]}，失败 {item[2]}"))
                else:
                    self.queue.put(("progress", item[0], item[1]))
        except Exception as e:
            self.queue.put(("finished", False, f"异常：{e}"))


# ================= Tab 4：Tag 编辑器 =================
class TagEditorTab:
    def __init__(self, parent, root):
        self.parent = parent
        self.root = root
        self.txt_dir = tk.StringVar()
        self.recursive = tk.BooleanVar(value=True)
        self.search_var = tk.StringVar()
        self.sort_mode = tk.StringVar(value="frequency")
        self.find_var = tk.StringVar()
        self.replace_var = tk.StringVar()
        self.partial_match = tk.BooleanVar(value=False)
        self.all_files = []
        self.tag_counts = {}
        self.tag_files = {}

        self._build_ui()
        self.search_var.trace_add("write", lambda *a: self.refresh_tree())
        self.sort_mode.trace_add("write", lambda *a: self.refresh_tree())
        self.root.after(300, self._refresh_cache_info)

    def _build_ui(self):
        main_paned = ttk.PanedWindow(self.parent, orient=tk.HORIZONTAL)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 4))
        left = ttk.Frame(main_paned)
        right = ttk.Frame(main_paned)
        main_paned.add(left, weight=3)
        main_paned.add(right, weight=2)
        self._build_left(left)
        self._build_right(right)
        self.status = tk.StringVar(value="就绪 · 请先选择文件夹并点击【加载】")
        tk.Label(self.parent, textvariable=self.status, anchor=tk.W,
                 bg='#eef2f7', fg=COLOR["muted"], padx=15, pady=6,
                 font=('Microsoft YaHei UI', 9)).pack(fill=tk.X, side=tk.BOTTOM)

    def _build_left(self, parent):
        top = ttk.LabelFrame(parent, text=" 文件夹 ", padding=10)
        top.pack(fill=tk.X, pady=(0, 6))

        row = ttk.Frame(top)
        row.pack(fill=tk.X, pady=2)
        ttk.Label(row, text="Tag 文件夹", width=10).pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=self.txt_dir).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        ttk.Button(row, text="浏览", width=6,
                   command=lambda: pick_dir(self.txt_dir, "last_txt_dir")
                   ).pack(side=tk.LEFT)

        row = ttk.Frame(top)
        row.pack(fill=tk.X, pady=(4, 2))
        ttk.Button(row, text="📂  加载", command=self.load_tags).pack(side=tk.LEFT)
        ttk.Checkbutton(row, text="递归子文件夹",
                        variable=self.recursive).pack(side=tk.LEFT, padx=(12, 0))

        fs = ttk.LabelFrame(parent, text=" 搜索与排序 ", padding=10)
        fs.pack(fill=tk.X, pady=(0, 6))
        row = ttk.Frame(fs)
        row.pack(fill=tk.X, pady=2)
        ttk.Label(row, text="搜索:").pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=self.search_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0))
        row = ttk.Frame(fs)
        row.pack(fill=tk.X, pady=(6, 2))
        ttk.Label(row, text="排序:").pack(side=tk.LEFT)
        ttk.Radiobutton(row, text="频率", variable=self.sort_mode,
                        value="frequency").pack(side=tk.LEFT, padx=(6, 0))
        ttk.Radiobutton(row, text="字母", variable=self.sort_mode,
                        value="alpha").pack(side=tk.LEFT, padx=(6, 0))
        ttk.Radiobutton(row, text="长度", variable=self.sort_mode,
                        value="length").pack(side=tk.LEFT, padx=(6, 0))

        ops = ttk.LabelFrame(parent, text=" 操作 ", padding=10)
        ops.pack(fill=tk.X, side=tk.BOTTOM, pady=(6, 0))

        row1 = ttk.Frame(ops)
        row1.pack(fill=tk.X, pady=2)
        ttk.Button(row1, text="🗑 删除选中",
                   command=self.delete_selected).pack(side=tk.LEFT)
        ttk.Button(row1, text="📋 复制选中",
                   command=self.copy_selected).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(row1, text="↻ 刷新",
                   command=self.load_tags).pack(side=tk.LEFT, padx=(6, 0))

        row2 = ttk.Frame(ops)
        row2.pack(fill=tk.X, pady=(8, 2))
        ttk.Label(row2, text="查找:").pack(side=tk.LEFT)
        ttk.Entry(row2, textvariable=self.find_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 8))
        ttk.Label(row2, text="替换:").pack(side=tk.LEFT)
        ttk.Entry(row2, textvariable=self.replace_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))

        row3 = ttk.Frame(ops)
        row3.pack(fill=tk.X, pady=(6, 2))
        ttk.Checkbutton(row3, text="部分匹配（包含即命中）",
                        variable=self.partial_match).pack(side=tk.LEFT)

        row4 = ttk.Frame(ops)
        row4.pack(fill=tk.X, pady=(6, 2))
        ttk.Button(row4, text="🔄  执行替换", style='Primary.TButton',
                   command=self.replace_tags).pack(fill=tk.X)

        tag_box = ttk.LabelFrame(parent, text=" Tag 列表（Ctrl / Shift 多选） ",
                                 padding=6)
        tag_box.pack(fill=tk.BOTH, expand=True, pady=(0, 0))
        cols = ("tag", "count", "length")
        self.tree = ttk.Treeview(tag_box, columns=cols, show="headings",
                                 selectmode="extended")
        self.tree.heading("tag", text="Tag")
        self.tree.heading("count", text="频率")
        self.tree.heading("length", text="长度")
        self.tree.column("tag", width=260, anchor=tk.W)
        self.tree.column("count", width=55, anchor=tk.CENTER)
        self.tree.column("length", width=55, anchor=tk.CENTER)
        self.tree.tag_configure("odd", background="#fafbfc")
        vsb = ttk.Scrollbar(tag_box, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self.tag_menu = tk.Menu(self.parent, tearoff=0)
        self.tag_menu.add_command(label="复制选中 tag", command=self.copy_selected)
        self.tag_menu.add_command(label="删除选中 tag", command=self.delete_selected)
        self.tag_menu.add_separator()
        self.tag_menu.add_command(label="把它设为查找内容",
                                  command=self._set_find_from_sel)
        self.tree.bind("<Button-3>", self._show_tag_menu)
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.update_image_list())

        self.backup_opts = BackupOptions(
            parent,
            base_root_getter=lambda: self.txt_dir.get(),
            title=" 备份设置 ")
        self.backup_opts.pack(fill=tk.X, pady=(6, 0))

    def _build_right(self, parent):
        img_box = ttk.LabelFrame(parent, text=" 图片预览（单击打开） ", padding=6)
        img_box.pack(fill=tk.BOTH, expand=True)

        # 底部状态行 + 清缓存按钮
        status_row = ttk.Frame(img_box)
        status_row.pack(side=tk.BOTTOM, fill=tk.X, pady=(4, 0))

        self.img_status = tk.StringVar(value="未选中 tag")
        tk.Label(status_row, textvariable=self.img_status, anchor=tk.W,
                 font=('Microsoft YaHei UI', 8), fg=COLOR["muted"],
                 bg=COLOR["card"]).pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.cache_info_var = tk.StringVar(value="")
        ttk.Label(status_row, textvariable=self.cache_info_var,
                  foreground=COLOR["muted"],
                  font=('Microsoft YaHei UI', 8)).pack(
                      side=tk.RIGHT, padx=(0, 6))
        ttk.Button(status_row, text="🧹 清缓存",
                   command=self._clear_thumb_cache).pack(side=tk.RIGHT)

        thumb_container = ttk.Frame(img_box)
        thumb_container.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        if not HAS_PILTK:
            tk.Label(thumb_container,
                     text="⚠ 未检测到 Pillow.ImageTk，缩略图不可用",
                     bg='#1e1e2e', fg='#f59e0b',
                     font=('Microsoft YaHei UI', 10), justify='center').pack(pady=30)
            self.thumb_panel = None
            return
        self.thumb_panel = ThumbGrid(
            thumb_container, self.root, open_path,
            empty_hint="👉 在左侧选择一个 tag\n即可在此处预览对应图片")

    def _show_tag_menu(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            if item not in self.tree.selection():
                self.tree.selection_set(item)
            self.tag_menu.tk_popup(event.x_root, event.y_root)

    def _on_double_click(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            vals = self.tree.item(item, "values")
            if vals:
                self.find_var.set(vals[0])

    def _set_find_from_sel(self):
        sel = self.tree.selection()
        if sel:
            vals = self.tree.item(sel[0], "values")
            if vals:
                self.find_var.set(vals[0])

    def copy_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        tags = [self.tree.item(i, "values")[0] for i in sel]
        self.root.clipboard_clear()
        self.root.clipboard_append(", ".join(tags))
        self.status.set(f"已复制 {len(tags)} 个 tag")

    def _refresh_cache_info(self):
        if self.thumb_panel is None:
            return
        if not hasattr(self, "cache_info_var"):
            return
        c = self.thumb_panel.disk_cache
        n = c.count()
        s = c.size()

        def _human(n):
            for u in ("B", "KB", "MB", "GB"):
                if n < 1024 or u == "GB":
                    return f"{int(n)} B" if u == "B" else f"{n:.1f} {u}"
                n /= 1024

        self.cache_info_var.set(f"（{n} 张 / {_human(s)}）")

    def _clear_thumb_cache(self):
        if self.thumb_panel is None:
            return
        c = self.thumb_panel.disk_cache
        n = c.count()
        if n == 0:
            messagebox.showinfo("提示", "缓存已经是空的")
            return
        if not messagebox.askyesno(
            "确认清除",
            f"将删除 {n} 张缩略图缓存。\n\n"
            f"清除后下次打开 tag 会重新生成（较慢）。\n\n继续？"):
            return
        c.clear()
        self.thumb_panel.thumb_cache.clear()
        self._refresh_cache_info()
        self.status.set(f"已清除缓存：{n} 张")

    def update_image_list(self):
        if self.thumb_panel is None:
            return
        sel = self.tree.selection()
        if not sel:
            self.thumb_panel.set_images([])
            self.img_status.set("未选中 tag")
            return
        selected = [self.tree.item(i, "values")[0] for i in sel]
        file_to_tags = {}
        for t in selected:
            for path in self.tag_files.get(t, set()):
                file_to_tags.setdefault(path, []).append(t)
                images = []
        for txt_path, tags in file_to_tags.items():
            img_path = find_image_for_txt(txt_path)
            images.append((img_path, txt_path, tags))
        images.sort(key=lambda x: os.path.basename(x[0] or x[1]).lower())

        # 转成 ThumbGrid 需要的 4 元组格式
        grid_items = []
        for img_path, txt_path, tags in images:
            target = img_path if img_path else txt_path
            name = os.path.basename(target)
            subtitle = ", ".join(tags) if tags else None
            grid_items.append((img_path, name, subtitle, target))
        self.thumb_panel.set_images(grid_items)
        extra = f"（仅显示前 {MAX_THUMBNAILS} 张）" if len(images) > MAX_THUMBNAILS else ""
        self.img_status.set(
            f"选中 {len(selected)} 个 tag · 共 {len(images)} 张图片/文件{extra}")
        self._refresh_cache_info()

    def load_tags(self):
        folder = self.txt_dir.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showerror("错误", "请选择有效文件夹")
            return
        self.status.set("正在加载...")
        self.root.update_idletasks()
        files = find_txt_files(folder, self.recursive.get())
        self.all_files = files
        counts = Counter()
        tag_files = {}
        for path in files:
            try:
                tags = read_tags(path)
            except Exception:
                continue
            for t in tags:
                counts[t] += 1
                tag_files.setdefault(t, set()).add(path)
        self.tag_counts = dict(counts)
        self.tag_files = tag_files
        self.refresh_tree()
        if self.thumb_panel is not None:
            self.thumb_panel.set_images([])
        self.img_status.set("未选中 tag")

    def refresh_tree(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        search = self.search_var.get().strip().lower()
        items = []
        for tag, cnt in self.tag_counts.items():
            if search and search not in tag.lower():
                continue
            items.append((tag, cnt, len(tag)))
        mode = self.sort_mode.get()
        if mode == "frequency":
            items.sort(key=lambda x: (-x[1], x[0].lower()))
        elif mode == "alpha":
            items.sort(key=lambda x: x[0].lower())
        elif mode == "length":
            items.sort(key=lambda x: (-x[2], x[0].lower()))
        for i, (tag, cnt, length) in enumerate(items):
            self.tree.insert("", tk.END, values=(tag, cnt, length),
                             tags=("odd",) if i % 2 else ())
        self.status.set(
            f"共 {len(self.tag_counts)} 个 tag · 显示 {len(items)} 个 · "
            f"涉及 {len(self.all_files)} 个 txt 文件")

    def _get_backup_cfg(self):
        cfg = self.backup_opts.get_cfg()
        if cfg["enabled"] and cfg["mode"] == "custom" and not cfg["dir"]:
            return {**cfg, "enabled": False}
        return cfg

    def delete_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先选择要删除的 tag")
            return
        tags_to_del = [self.tree.item(i, "values")[0] for i in sel]
        preview = "、".join(tags_to_del[:5])
        if len(tags_to_del) > 5:
            preview += f" 等 {len(tags_to_del)} 个"
        if not messagebox.askyesno("确认删除",
                f"将从所有 txt 永久删除：\n\n{preview}\n\n是否继续？"):
            return
        backup_cfg = self._get_backup_cfg()
        del_set = {t.lower() for t in tags_to_del}
        modified = 0
        for path in self.all_files:
            try:
                tags = read_tags(path)
                new_tags = [t for t in tags if t.lower() not in del_set]
                if new_tags != tags:
                    write_tags(path, new_tags, backup_cfg=backup_cfg)
                    modified += 1
            except Exception:
                continue
        messagebox.showinfo("完成",
                            f"删除 {len(tags_to_del)} 个 tag\n涉及 {modified} 个文件")
        self.load_tags()

    def replace_tags(self):
        find = self.find_var.get().strip()
        replace = self.replace_var.get().strip()
        if not find:
            messagebox.showerror("错误", "请输入要查找的 tag")
            return
        partial = self.partial_match.get()
        if not replace:
            if not messagebox.askyesno("确认",
                    "替换内容为空，将删除匹配 tag。是否继续？"):
                return
        find_lower = find.lower()
        matched = []
        for t in self.tag_counts:
            if partial:
                if find_lower in t.lower():
                    matched.append(t)
            else:
                if t.lower() == find_lower:
                    matched.append(t)
        if not matched:
            messagebox.showinfo("提示", f"没有找到匹配的 tag：{find}")
            return
        preview = "、".join(matched[:5])
        if len(matched) > 5:
            preview += f" 等 {len(matched)} 个"
        if not messagebox.askyesno("确认替换",
                f"将替换为 [{replace or '空（即删除）'}]：\n\n{preview}\n\n是否继续？"):
            return
        backup_cfg = self._get_backup_cfg()
        total = 0
        files_changed = 0
        for path in self.all_files:
            try:
                tags = read_tags(path)
                new_tags = []
                changed = False
                for t in tags:
                    hit = (find_lower in t.lower()) if partial else \
                          (t.lower() == find_lower)
                    if hit:
                        if replace:
                            new_tags.append(replace)
                        changed = True
                        total += 1
                    else:
                        new_tags.append(t)
                if changed:
                    seen, uniq = set(), []
                    for x in new_tags:
                        k = x.lower()
                        if k not in seen:
                            seen.add(k)
                            uniq.append(x)
                    write_tags(path, uniq, backup_cfg=backup_cfg)
                    files_changed += 1
            except Exception:
                continue
        messagebox.showinfo("完成",
                            f"共替换 {total} 处\n涉及 {files_changed} 个文件")
        self.load_tags()


# ================= 主窗口 =================
class App:
    def __init__(self, root):
        self.root = root
        self.root.title("LoRA 前后期工具箱 · by 翡翠珍珠排骨")

        # 动态窗口尺寸（按屏幕算）
        w, h = calc_window_size(self.root, max_w=1900, max_h=1050,
                                min_w=1100, min_h=680)
        center_on_screen(self.root, w, h)
        self.root.minsize(1000, 680)

        self.root.configure(bg=COLOR["bg"])
        setup_styles()

        # ---- 占位层（拖动时显示）----
        self._placeholder = tk.Frame(root, bg="#1e1e2e")
        tk.Label(self._placeholder,
                 text="正在移动...",
                 bg="#1e1e2e", fg="#6b7280",
                 font=('Microsoft YaHei UI', 14)
                 ).pack(expand=True)

        # ---- 内容层（平时显示）----
        self._container = ttk.Frame(root)
        self._container.place(x=0, y=0, relwidth=1, relheight=1)

        nb = ttk.Notebook(self._container)
        nb.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        tabs = [
            ("🚀  一键流水线", PipelineTab),
            ("🖼️  尺寸统一",   ResizeTab),
            ("🏷️  WD 打标",    TaggerTab),
            ("✏️  Tag 编辑器", TagEditorTab),
            ("📦  LoRA 管理器", LoRAManagerTab),
            ("📚  数据集",      DatasetTab),
            ("🛠️  图片工具",    ImageToolsTab),
        ]
        self.tab_instances = []
        for title, cls in tabs:
            frame = ttk.Frame(nb)
            nb.add(frame, text=f"  {title}  ")
            inst = cls(frame, root)
            self.tab_instances.append(inst)

        # 通知每个 Tab "你是否可见"
        def on_tab_change(event=None):
            try:
                cur = nb.index(nb.select())
            except Exception:
                return
            for i, inst in enumerate(self.tab_instances):
                handler = getattr(inst, "_on_visibility_change", None)
                if handler is not None:
                    try:
                        handler(i == cur)
                    except Exception:
                        pass

        nb.bind("<<NotebookTabChanged>>", on_tab_change)

        # ---- 拖动窗口时的隐藏/滑入控制 ----
        self._is_moving = False
        self._move_timer = None
        self._slide_offset = 0
        self._app_ready = False
        self._last_geometry = None
        self._anchor_geometry = None
        self._is_sliding = False
        # 启动 500ms 内不触发动画（避免启动瞬间的 Configure 事件）
        self.root.after(500, self._set_app_ready)
        self.root.bind("<Configure>", self._on_root_configure, add='+')
        # F1 弹出"关于"
        self.root.bind("<F1>", lambda e: self._show_about())
        # 启动时：只有第一个 Tab 可见
        if self.tab_instances:
            for i, inst in enumerate(self.tab_instances):
                handler = getattr(inst, "_on_visibility_change", None)
                if handler is not None:
                    try:
                        handler(i == 0)
                    except Exception:
                        pass

    def _show_about(self):
        messagebox.showinfo(
            "关于",
            "LoRA 前后期工具箱\n\n"
            "作者：翡翠珍珠排骨\n"
            "B站 UID：3923028\n"
            "主页：https://space.bilibili.com/3923028\n"
            "协议：MIT License\n\n"
            "如果这个工具帮到了你，欢迎来B站点个关注 ⭐")

    def _set_app_ready(self):
        try:
            cur = (self.root.winfo_x(), self.root.winfo_y(),
                   self.root.winfo_width(), self.root.winfo_height())
            self._last_geometry = cur
            self._anchor_geometry = cur
        except Exception:
            pass
        self._app_ready = True

    def _on_root_configure(self, event):
        if event.widget is not self.root:
            return
        if not self._app_ready:
            return
        if self._is_sliding:
            return   # 滑入动画中，忽略一切 Configure

        try:
            cur = (self.root.winfo_x(), self.root.winfo_y(),
                   self.root.winfo_width(), self.root.winfo_height())
        except Exception:
            return

        if cur == self._last_geometry:
            return
        self._last_geometry = cur

        # 判断是否"真的变了"
        size_changed = False
        pos_delta = 0
        if self._anchor_geometry is not None:
            if (cur[2] != self._anchor_geometry[2]
                    or cur[3] != self._anchor_geometry[3]):
                size_changed = True
            pos_delta = max(abs(cur[0] - self._anchor_geometry[0]),
                            abs(cur[1] - self._anchor_geometry[1]))

        # 尺寸没变 且 位置变化 < 5 像素 → 视为抖动，忽略
        if not size_changed and pos_delta < 5:
            return

        # 开始隐藏
        if not self._is_moving:
            self._is_moving = True
            try:
                self._container.place_forget()
                self._placeholder.place(x=0, y=0,
                                        relwidth=1, relheight=1)
            except Exception:
                pass

        if self._move_timer is not None:
            try:
                self.root.after_cancel(self._move_timer)
            except Exception:
                pass
        self._move_timer = self.root.after(250, self._on_move_stop)

    def _on_move_stop(self):
        self._move_timer = None
        self._is_moving = False
        self._is_sliding = True

        try:
            self._placeholder.place_forget()
        except Exception:
            pass

        # 更新基准位置（拖动结束后的位置）
        try:
            self._anchor_geometry = (
                self.root.winfo_x(), self.root.winfo_y(),
                self.root.winfo_width(), self.root.winfo_height())
        except Exception:
            pass

        self._slide_offset = 20
        self._container.place(x=0, y=self._slide_offset,
                              relwidth=1, relheight=1)
        self._slide_in()

    def _slide_in(self):
        if not self._is_sliding:
            return
        self._slide_offset -= 2
        if self._slide_offset <= 0:
            self._is_sliding = False
            try:
                self._container.place(x=0, y=0,
                                      relwidth=1, relheight=1)
            except Exception:
                pass
        else:
            try:
                self._container.place(x=0, y=self._slide_offset,
                                      relwidth=1, relheight=1)
            except Exception:
                pass
            self.root.after(16, self._slide_in)


def main():
    # DPI 感知必须最先调用，且在 tk.Tk() 之前
    enable_dpi_awareness()

    load_global_config()

    warnings = []
    if not HAS_TORCH:
        warnings.append("未装 PyTorch（GPU 加速不可用）")
    if not HAS_ORT:
        warnings.append("未装 onnxruntime/pandas（WD 打标不可用）")
    if not HAS_PILTK:
        warnings.append("未装 Pillow.ImageTk（缩略图不可用）")
    if warnings:
        print("[提示] " + " | ".join(warnings))

    root = tk.Tk()

    # 让字体随 DPI 正确显示
    apply_dpi_scaling(root)

    # 设置程序图标
    generate_app_icon(root)

    App(root)

    # 底部一行署名
    credit = tk.Label(root,
                      text="by 翡翠珍珠排骨  ·  B站 UID 3923028  ·  "
                           "按 F1 查看关于",
                      bg="#f7f8fa", fg="#9ca3af",
                      font=('Microsoft YaHei UI', 8))
    credit.pack(side=tk.BOTTOM, fill=tk.X, pady=(0, 2))

    root.mainloop()


if __name__ == "__main__":
    main()