# -*- coding: utf-8 -*-
# LoRA 前后期工具箱
# 作者：翡翠珍珠排骨 (B站 UID: 3923028)
# 主页：https://space.bilibili.com/3923028
# 协议：MIT License
"""
数据集管理器 Tab
- 扫描训练数据集根目录，顶层每个文件夹 = 一个数据集
- 显示：数据集名 / 正样本 / 正则 / 触发词 / 大小 / 修改时间 / 关联 LoRA / 状态
- 详情面板：缩略图网格
- 手动/自动关联 LoRA / 状态标记
"""
import os
import sys
import threading
import queue
import datetime
import subprocess
import hashlib
from collections import Counter
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

from lora_manager import Database, parse_lora_filename
from file_utils import open_path, reveal_path, copy_text
from thumb_grid import ThumbCache, ThumbGrid


COLOR = {
    "bg":        "#f7f8fa",
    "card":      "#ffffff",
    "border":    "#e5e7eb",
    "primary":   "#3b82f6",
    "text":      "#111827",
    "muted":     "#6b7280",
    "success":   "#10b981",
    "danger":    "#ef4444",
}

IMG_EXTS = ('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif', '.tiff')

DATASET_KEEP    = "keep"
DATASET_DISCARD = "discard"
DATASET_ARCHIVE = "archive"

STATE_ICON = {
    DATASET_KEEP:    "⭐",
    DATASET_DISCARD: "🗑",
    DATASET_ARCHIVE: "📦",
    None: "·",
}
STATE_LABEL = {
    DATASET_KEEP:    "保留",
    DATASET_DISCARD: "废弃",
    DATASET_ARCHIVE: "归档",
    None: "未标记",
}

THUMB_SIZE = (140, 140)
MAX_THUMBS = 300


def _human_size(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{int(n)} B" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


# ================= 数据模型 =================
class DatasetItem:
    __slots__ = ("path", "name", "n_positive", "n_reg", "n_total",
                 "trigger", "trigger_from_user",
                 "size", "mtime",
                 "lora_group", "state", "comment")

    def __init__(self, path, db):
        self.path = path
        self.name = os.path.basename(path)
        self.n_positive = 0
        self.n_reg = 0
        self.n_total = 0
        self.trigger = db.get_dataset_trigger(self.name) or ""
        self.trigger_from_user = bool(self.trigger)
        self.size = 0
        self.mtime = 0
        self.lora_group = db.get_dataset_lora(self.name)
        entry = db.get_dataset_state(self.path)
        self.state = entry.get("state")
        self.comment = entry.get("comment", "")


# ================= 扫描器 =================
class DatasetScanner:
    def __init__(self, root_dir, db, on_progress=None, on_done=None):
        self.root_dir = root_dir
        self.db = db
        self.on_progress = on_progress
        self.on_done = on_done
        self.stop_event = threading.Event()

    def stop(self):
        self.stop_event.set()

    def run(self):
        try:
            entries = [e for e in os.listdir(self.root_dir)
                       if os.path.isdir(os.path.join(self.root_dir, e))]
        except Exception as e:
            if self.on_done:
                self.on_done([], str(e))
            return

        entries.sort(reverse=True)
        total = len(entries)
        items = []

        for i, name in enumerate(entries, 1):
            if self.stop_event.is_set():
                break
            if self.on_progress:
                self.on_progress(i, total, name)
            try:
                item = self._scan_one(os.path.join(self.root_dir, name))
                items.append(item)
            except Exception:
                continue

        if self.on_done:
            self.on_done(items, None)

    def _scan_one(self, path):
        item = DatasetItem(path, self.db)
        try:
            item.mtime = os.path.getmtime(path)
        except Exception:
            item.mtime = 0

        trigger_candidates = []
        total_size = 0

        def _is_reg_dir(segment):
            sl = segment.lower()
            return (sl == 'reg' or sl == 'regularization'
                    or sl == 'regular'
                    or sl.startswith('reg_')
                    or sl.endswith('_reg'))

        for root, dirs, files in os.walk(path):
            if self.stop_event.is_set():
                break

            # 判断当前路径是否为正则路径
            rel = os.path.relpath(root, path)
            parts = rel.replace('\\', '/').split('/')
            is_reg = any(_is_reg_dir(p) for p in parts if p and p != '.')

            # 注意：不要在这里剔除 dirs，要让 os.walk 走进 reg 目录数文件
            pass

            # 从 N_tag 格式目录名提触发词（只在非正则路径）
            if not is_reg:
                for d in dirs:
                    if '_' in d:
                        prefix, _, tag = d.partition('_')
                        if prefix.isdigit() and tag:
                            tl = tag.lower()
                            if _is_reg_dir(tl):
                                continue
                            trigger_candidates.append(tag)

            for f in files:
                fl = f.lower()
                fpath = os.path.join(root, f)
                try:
                    total_size += os.path.getsize(fpath)
                except Exception:
                    pass

                if fl.endswith(IMG_EXTS):
                    if is_reg:
                        item.n_reg += 1
                    else:
                        item.n_positive += 1
                    item.n_total += 1

        if not item.trigger_from_user:
            if trigger_candidates:
                item.trigger = Counter(trigger_candidates).most_common(1)[0][0]
            else:
                item.trigger = self._find_trigger_from_txt(path)

        item.size = total_size
        return item

    def _find_trigger_from_txt(self, path):
        def _is_reg_dir(segment):
            sl = segment.lower()
            return (sl == 'reg' or sl == 'regularization'
                    or sl == 'regular'
                    or sl.startswith('reg_')
                    or sl.endswith('_reg'))

        for root, dirs, files in os.walk(path):
            rel = os.path.relpath(root, path)
            parts = rel.replace('\\', '/').split('/')
            is_reg = any(_is_reg_dir(p) for p in parts if p and p != '.')

            dirs[:] = [d for d in dirs if not _is_reg_dir(d)]
            if is_reg:
                continue

            for f in sorted(files):
                if f.lower().endswith('.txt'):
                    try:
                        with open(os.path.join(root, f),
                                  'r', encoding='utf-8') as fp:
                            content = fp.read()
                        tags = [t.strip() for t in content.split(',')]
                        for t in tags:
                            if t:
                                return t
                    except Exception:
                        continue
        return ""


# ================= 主 Tab =================
class DatasetTab:
    def __init__(self, parent, root):
        self.parent = parent
        self.root = root
        self.db = Database()
        self.queue = queue.Queue()
        self.scanner = None
        self.items = []
        self.iid_to_item = {}
        self.current_item = None

        self.root_dir = tk.StringVar()
        self.status_var = tk.StringVar(
            value="就绪 · 请选择数据集根目录后点扫描")
        self.filter_var = tk.StringVar(value="全部")
        self.mark_state = tk.StringVar(value="none")
        self.mark_comment = tk.StringVar()
        self._queue_running = True

        self._build_ui()
        self.root.after(80, self._check_queue)
        self.root.after(200, self._refresh_cache_info)

    def _build_ui(self):
        tk.Label(self.parent, textvariable=self.status_var,
                 anchor=tk.W, bg='#eef2f7', fg=COLOR["muted"],
                 padx=14, pady=5,
                 font=('Microsoft YaHei UI', 9)).pack(
                     side=tk.BOTTOM, fill=tk.X)

        batch = ttk.Frame(self.parent)
        batch.pack(side=tk.BOTTOM, fill=tk.X, padx=12, pady=(2, 4))
        self._build_batch_bar(batch)

        top = ttk.Frame(self.parent)
        top.pack(side=tk.TOP, fill=tk.X, padx=12, pady=(10, 4))
        self._build_top(top)

        body = ttk.Frame(self.parent)
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True,
                  padx=12, pady=(0, 4))
        body.columnconfigure(0, weight=3, minsize=560)
        body.columnconfigure(1, weight=2, minsize=380)
        body.rowconfigure(0, weight=1)

        left = ttk.Frame(body)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self._build_left(left)

        right = ttk.Frame(body)
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        self._build_right(right)

    def _build_top(self, top):
        row1 = ttk.Frame(top)
        row1.pack(fill=tk.X, pady=(0, 3))

        self.scan_btn = ttk.Button(row1, text="🔍 扫描",
                                   style='Primary.TButton',
                                   command=self.start_scan)
        self.scan_btn.pack(side=tk.LEFT)
        self.stop_btn = ttk.Button(row1, text="■ 停止",
                                   state=tk.DISABLED,
                                   command=self.stop_scan)
        self.stop_btn.pack(side=tk.LEFT, padx=(4, 8))

        ttk.Button(row1, text="📂 根目录",
                   command=self._open_root).pack(side=tk.LEFT)
        ttk.Button(row1, text="🔗 自动匹配",
                   command=self._auto_match_all).pack(side=tk.LEFT, padx=3)

        ttk.Label(row1, text="根目录:").pack(side=tk.LEFT, padx=(16, 2))
        ttk.Entry(row1, textvariable=self.root_dir).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        ttk.Button(row1, text="浏览", width=6,
                   command=self._pick_dir).pack(side=tk.LEFT)

        row2 = ttk.Frame(top)
        row2.pack(fill=tk.X, pady=(3, 0))

        ttk.Label(row2, text="筛选:").pack(side=tk.LEFT)
        fcb = ttk.Combobox(row2, textvariable=self.filter_var,
                           values=["全部", "保留", "废弃", "归档", "未标记"],
                           width=8, state="readonly")
        fcb.pack(side=tk.LEFT, padx=(4, 0))
        fcb.bind("<<ComboboxSelected>>", lambda e: self.refresh_tree())

        self.progress = ttk.Progressbar(row2, orient=tk.HORIZONTAL,
                                        mode='determinate')
        self.progress.pack(side=tk.LEFT, fill=tk.X, expand=True,
                           padx=(16, 0))

    def _build_batch_bar(self, bar):
        ttk.Label(bar, text="批量:").pack(side=tk.LEFT)
        ttk.Button(bar, text="⭐ 保留", width=8,
                   command=lambda: self.batch_mark(DATASET_KEEP)
                   ).pack(side=tk.LEFT, padx=1)
        ttk.Button(bar, text="🗑 废弃", width=8,
                   command=lambda: self.batch_mark(DATASET_DISCARD)
                   ).pack(side=tk.LEFT, padx=1)
        ttk.Button(bar, text="📦 归档", width=7,
                   command=lambda: self.batch_mark(DATASET_ARCHIVE)
                   ).pack(side=tk.LEFT, padx=1)
        ttk.Button(bar, text="· 清除", width=7,
                   command=lambda: self.batch_mark(None)
                   ).pack(side=tk.LEFT, padx=1)

        ttk.Separator(bar, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=8)

        ttk.Button(bar, text="📂 打开",
                   command=self._open_selected).pack(side=tk.LEFT, padx=1)
        ttk.Button(bar, text="🔗 关联 LoRA",
                   command=self._manual_link_lora).pack(
                       side=tk.LEFT, padx=1)

        ttk.Separator(bar, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=8)

        self.cache_info_var = tk.StringVar(value="")
        ttk.Button(bar, text="🧹 清除缩略图缓存",
                   command=self._clear_thumb_cache).pack(
                       side=tk.LEFT, padx=1)
        ttk.Label(bar, textvariable=self.cache_info_var,
                  foreground=COLOR["muted"],
                  font=('Microsoft YaHei UI', 8)).pack(
                      side=tk.LEFT, padx=(6, 0))

    def _refresh_cache_info(self):
        if not hasattr(self, "cache_info_var"):
            return
        if not self.thumb_panel:
            return
        c = self.thumb_panel.disk_cache
        n = c.count()
        s = c.size()
        self.cache_info_var.set(f"（{n} 张 / {_human_size(s)}）")

    def _clear_thumb_cache(self):
        if not self.thumb_panel:
            return
        c = self.thumb_panel.disk_cache
        n = c.count()
        if n == 0:
            messagebox.showinfo("提示", "缓存已经是空的")
            return
        s = c.size()
        if not messagebox.askyesno(
            "确认清除",
            f"将删除 {n} 张缩略图缓存（{_human_size(s)}）\n\n"
            f"清除后下次打开会重新生成（较慢）。\n\n继续？"):
            return
        c.clear()
        # 顺便清掉内存缓存
        self.thumb_panel.thumb_cache.clear()
        self._refresh_cache_info()
        self.status_var.set(f"已清除缓存：{n} 张")

    def _build_left(self, left):
        box = ttk.LabelFrame(left, text=" 数据集列表 ", padding=4)
        box.pack(fill=tk.BOTH, expand=True)

        cols = ("pos", "reg", "trigger", "size", "mtime",
                "lora", "state")
        self.tree = ttk.Treeview(box, columns=cols,
                                 show="tree headings",
                                 selectmode="extended")
        self.tree.heading("#0", text="数据集")
        self.tree.heading("pos", text="图片")
        self.tree.heading("reg", text="正则")
        self.tree.heading("trigger", text="触发词")
        self.tree.heading("size", text="大小")
        self.tree.heading("mtime", text="修改时间")
        self.tree.heading("lora", text="关联 LoRA")
        self.tree.heading("state", text="状态")

        self.tree.column("#0", width=200, anchor=tk.W)
        self.tree.column("pos", width=55, anchor=tk.CENTER)
        self.tree.column("reg", width=55, anchor=tk.CENTER)
        self.tree.column("trigger", width=100, anchor=tk.W)
        self.tree.column("size", width=70, anchor=tk.E)
        self.tree.column("mtime", width=115, anchor=tk.CENTER)
        self.tree.column("lora", width=130, anchor=tk.W)
        self.tree.column("state", width=60, anchor=tk.CENTER)
        self.tree.tag_configure("odd", background="#fafbfc")

        vsb = ttk.Scrollbar(box, orient="vertical",
                            command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<Button-3>", self._on_rclick)

        self.tree_menu = tk.Menu(self.root, tearoff=0)
        self.tree_menu.add_command(
            label="⭐ 保留",
            command=lambda: self.batch_mark(DATASET_KEEP))
        self.tree_menu.add_command(
            label="🗑 废弃",
            command=lambda: self.batch_mark(DATASET_DISCARD))
        self.tree_menu.add_command(
            label="📦 归档",
            command=lambda: self.batch_mark(DATASET_ARCHIVE))
        self.tree_menu.add_command(
            label="· 清除标记",
            command=lambda: self.batch_mark(None))
        self.tree_menu.add_separator()
        self.tree_menu.add_command(label="打开文件夹",
                                   command=self._open_selected)
        self.tree_menu.add_command(label="✏ 编辑触发词",
                                   command=self._edit_trigger)
        self.tree_menu.add_command(label="↺ 恢复自动触发词",
                                   command=self._reset_trigger)
        self.tree_menu.add_command(label="🔗 关联 LoRA",
                                   command=self._manual_link_lora)
        self.tree_menu.add_command(label="取消关联",
                                   command=self._unlink_lora)
        self.tree_menu.add_separator()
        self.tree_menu.add_command(label="复制路径",
                                   command=self._copy_path)

    def _build_right(self, right):
        self.info_var = tk.StringVar(value="")
        tk.Label(right, textvariable=self.info_var, anchor=tk.W,
                 bg=COLOR["card"], fg=COLOR["muted"],
                 font=('Microsoft YaHei UI', 9), padx=6, pady=4
                 ).pack(side=tk.TOP, fill=tk.X)

        mark_box = ttk.LabelFrame(right, text=" 标记 ", padding=6)
        mark_box.pack(side=tk.TOP, fill=tk.X, pady=(4, 0))

        r = ttk.Frame(mark_box)
        r.pack(fill=tk.X)
        for val, label in [("none", "· 无"), ("keep", "⭐ 保留"),
                           ("discard", "🗑 废弃"), ("archive", "📦 归档")]:
            ttk.Radiobutton(r, text=label, variable=self.mark_state,
                            value=val).pack(side=tk.LEFT, padx=(0, 6))

        r = ttk.Frame(mark_box)
        r.pack(fill=tk.X, pady=(4, 0))
        ttk.Label(r, text="注释:").pack(side=tk.LEFT)
        ttk.Entry(r, textvariable=self.mark_comment).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 4))
        ttk.Button(r, text="应用",
                   command=self.apply_mark).pack(side=tk.LEFT)

        thumb_box = ttk.LabelFrame(right, text=" 图片预览 ", padding=4)
        thumb_box.pack(side=tk.TOP, fill=tk.BOTH, expand=True, pady=(4, 0))
        if not HAS_PIL:
            tk.Label(thumb_box, text="⚠ 未安装 Pillow，无法预览",
                     bg='#1e1e2e', fg='#f59e0b',
                     font=('Microsoft YaHei UI', 10)).pack(
                         expand=True, fill=tk.BOTH)
            self.thumb_panel = None
        else:
            self.thumb_panel = ThumbGrid(
                thumb_box, self.root, open_path,
                empty_hint="👉 在左侧选择一个数据集\n即可在此处预览图片")

    # ---------- 队列 ----------
    def _check_queue(self):
        if not self._queue_running:
            return
        try:
            while True:
                msg = self.queue.get_nowait()
                kind = msg[0]
                if kind == "progress":
                    _, a, b, name = msg
                    self.progress["maximum"] = max(1, b)
                    self.progress["value"] = a
                    self.status_var.set(f"扫描 {a}/{b}: {name}")
                elif kind == "done":
                    _, items, err = msg
                    self.scanner = None
                    self.scan_btn.config(state=tk.NORMAL)
                    self.stop_btn.config(state=tk.DISABLED)
                    self.progress["value"] = 0
                    if err:
                        messagebox.showerror("扫描失败", err)
                        continue
                    self.items = items
                    self.refresh_tree()
                    self.status_var.set(
                        f"扫描完成：{len(items)} 个数据集")
                    self._auto_match_all(silent=True)
        except queue.Empty:
            pass
        if self._queue_running:
            self.root.after(80, self._check_queue)

    def _on_visibility_change(self, visible):
        if visible:
            if not self._queue_running:
                self._queue_running = True
                self.root.after(80, self._check_queue)
        else:
            self._queue_running = False

    # ---------- 交互 ----------
    def _pick_dir(self):
        init = self.root_dir.get() or None
        d = filedialog.askdirectory(initialdir=init,
                                    title="选择数据集根目录")
        if d:
            self.root_dir.set(d)

    def _open_root(self):
        d = self.root_dir.get().strip()
        if d and os.path.isdir(d):
            open_path(d)

    def _edit_trigger(self):
        its = self._selected_items()
        if not its:
            messagebox.showinfo("提示", "请先选中数据集")
            return
        item = its[0]
        TriggerEditDialog(self.root, item.name,
                          item.trigger or "",
                          lambda t: self._on_trigger_edited(t))

    def _on_trigger_edited(self, trigger):
        its = self._selected_items()
        if not its:
            return
        for item in its:
            item.trigger = trigger
            item.trigger_from_user = bool(trigger)
            self.db.set_dataset_trigger(item.name, trigger)
        self.refresh_tree()
        self.status_var.set(f"已更新触发词：{trigger or '（空）'}")

    def _reset_trigger(self):
        its = self._selected_items()
        if not its:
            return
        # 构造一个临时 Scanner 用于重新提取触发词
        tmp_scanner = DatasetScanner(
            self.root_dir.get() or "", self.db)

        for item in its:
            self.db.del_dataset_trigger(item.name)
            item.trigger_from_user = False
            # 立刻重新提取
            try:
                new_item = tmp_scanner._scan_one(item.path)
                item.trigger = new_item.trigger
            except Exception:
                item.trigger = ""

        self.refresh_tree()
        self.status_var.set(
            f"已恢复自动触发词：{its[0].trigger or '（未提取到）'}")

    def _open_selected(self):
        its = self._selected_items()
        if its:
            open_path(its[0].path)

    def _copy_path(self):
        its = self._selected_items()
        if its:
            self.root.clipboard_clear()
            self.root.clipboard_append(its[0].path)
            self.status_var.set("已复制路径")

    def _on_rclick(self, event):
        iid = self.tree.identify_row(event.y)
        if iid:
            if iid not in self.tree.selection():
                self.tree.selection_set(iid)
            self.tree_menu.tk_popup(event.x_root, event.y_root)

    def _selected_items(self):
        return [self.iid_to_item[i] for i in self.tree.selection()
                if i in self.iid_to_item]

    def _on_double_click(self, event):
        # 双击触发词列，弹出编辑；否则打开文件夹
        region = self.tree.identify_region(event.x, event.y)
        col = self.tree.identify_column(event.x)
        if region == "cell" and col == "#3":   # 触发词列
            self._edit_trigger()
        else:
            self._open_selected()

    def _on_select(self, event=None):
        its = self._selected_items()
        if not its:
            self.current_item = None
            self.info_var.set("")
            if self.thumb_panel:
                self.thumb_panel.set_images([])
            return
        item = its[0]
        # 已经是同一个数据集 → 不重复加载
        if (self.current_item is not None
                and self.current_item.path == item.path):
            return
        self.current_item = item
        self._show_detail(item)

    def _show_detail(self, item):
        try:
            ts = datetime.datetime.fromtimestamp(item.mtime).strftime(
                "%Y-%m-%d %H:%M")
        except Exception:
            ts = "-"
        lora = item.lora_group or "未关联"
        self.info_var.set(
            f"📁 {item.name}  ·  正 {item.n_positive} / 正则 {item.n_reg}"
            f"  ·  {_human_size(item.size)}  ·  {ts}  ·  LoRA: {lora}")
        self.mark_state.set(item.state or "none")
        self.mark_comment.set(item.comment or "")

        if self.thumb_panel:
            paths = self._collect_images(item.path)
            items = [(p, os.path.basename(p), None, p) for p in paths]
            self.thumb_panel.set_images(items)

    def _collect_images(self, path):
        def _is_reg_dir(segment):
            sl = segment.lower()
            return (sl == 'reg' or sl == 'regularization'
                    or sl == 'regular'
                    or sl.startswith('reg_')
                    or sl.endswith('_reg'))

        out = []
        for root, dirs, files in os.walk(path):
            rel = os.path.relpath(root, path)
            parts = rel.replace('\\', '/').split('/')
            is_reg = any(_is_reg_dir(p) for p in parts if p and p != '.')

            # 排除正则目录，不再递归进去
            dirs[:] = [d for d in dirs if not _is_reg_dir(d)]
            if is_reg:
                continue

            for f in files:
                if f.lower().endswith(IMG_EXTS):
                    out.append(os.path.join(root, f))
        out.sort()
        return out

    # ---------- 扫描 ----------
    def start_scan(self):
        d = self.root_dir.get().strip()
        if not d or not os.path.isdir(d):
            messagebox.showerror("错误", "请选择有效的数据集根目录")
            return
        if self.scanner is not None:
            return
        self.scan_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.progress["value"] = 0
        self.progress["maximum"] = 1
        self.status_var.set("扫描中...")

        self.scanner = DatasetScanner(
            d, self.db,
            on_progress=lambda a, b, n:
                self.queue.put(("progress", a, b, n)),
            on_done=lambda items, err:
                self.queue.put(("done", items, err)))
        threading.Thread(target=self.scanner.run, daemon=True).start()

    def stop_scan(self):
        if self.scanner:
            self.scanner.stop()
        self.status_var.set("停止中...")

    # ---------- 列表刷新 ----------
    def refresh_tree(self):
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self.iid_to_item.clear()

        flt = self.filter_var.get()
        flt_key = {
            "全部": None,
            "保留": DATASET_KEEP,
            "废弃": DATASET_DISCARD,
            "归档": DATASET_ARCHIVE,
            "未标记": "none",
        }.get(flt)

        shown = 0
        for i, item in enumerate(self.items):
            cur = item.state or "none"
            if flt_key is not None and cur != flt_key:
                continue

            try:
                ts = datetime.datetime.fromtimestamp(
                    item.mtime).strftime("%Y-%m-%d %H:%M")
            except Exception:
                ts = "-"

            icon = STATE_ICON.get(item.state, "·")
            values = (
                item.n_positive,
                item.n_reg,
                item.trigger or "-",
                _human_size(item.size),
                ts,
                item.lora_group or "-",
                STATE_LABEL.get(item.state, "未标记"),
            )
            iid = self.tree.insert(
                "", tk.END,
                text=f"{icon}  {item.name}",
                values=values,
                tags=("odd",) if i % 2 else ())
            self.iid_to_item[iid] = item
            shown += 1

        self.status_var.set(
            f"显示 {shown}/{len(self.items)} 个数据集")

    # ---------- 标记 ----------
    def apply_mark(self):
        its = self._selected_items()
        if not its:
            return
        val = self.mark_state.get()
        state = None if val == "none" else val
        comment = self.mark_comment.get().strip()
        for item in its:
            item.state = state
            item.comment = comment
            self.db.set_dataset_state(item.path, state=state,
                                      comment=comment)
        self.refresh_tree()
        self.status_var.set(f"已更新 {len(its)} 个数据集的标记")

    def batch_mark(self, state):
        its = self._selected_items()
        if not its:
            messagebox.showinfo("提示", "请先选中数据集")
            return
        for item in its:
            item.state = state
            self.db.set_dataset_state(item.path, state=state)
        self.refresh_tree()
        self.status_var.set(
            f"已批量标记 {len(its)} 个 → "
            f"{STATE_LABEL.get(state, '未标记')}")

    # ---------- LoRA 关联 ----------
    def _get_all_lora_groups(self):
        groups = set()
        for path in self.db.data.get("files", {}).keys():
            stem = os.path.splitext(os.path.basename(path))[0]
            g, _, _ = parse_lora_filename(stem)
            groups.add(g)
        return sorted(groups)

    def _auto_match_all(self, silent=False):
        groups = self._get_all_lora_groups()
        if not groups:
            if not silent:
                messagebox.showinfo(
                    "提示",
                    "数据库里还没有 LoRA 记录。\n\n"
                    "请先在【LoRA 管理器】扫描一次，再回来匹配。")
            return
        matched = 0
        for item in self.items:
            if item.lora_group:
                continue
            trig = item.trigger
            if not trig:
                continue
            for g in groups:
                if g == trig or trig in g or g in trig:
                    item.lora_group = g
                    self.db.set_dataset_lora(item.name, g, source="auto")
                    matched += 1
                    break
        self.refresh_tree()
        self.status_var.set(
            f"自动匹配完成：{matched} 个数据集已关联 LoRA")

    def _manual_link_lora(self):
        its = self._selected_items()
        if not its:
            messagebox.showinfo("提示", "请先选中数据集")
            return
        groups = self._get_all_lora_groups()
        if not groups:
            messagebox.showinfo(
                "提示",
                "数据库里还没有 LoRA 记录。\n\n"
                "请先在【LoRA 管理器】扫描一次。")
            return
        LoRAPickerDialog(self.root, groups, self._on_lora_picked)

    def _on_lora_picked(self, group_name):
        its = self._selected_items()
        if not its:
            return
        for item in its:
            item.lora_group = group_name
            self.db.set_dataset_lora(item.name, group_name,
                                     source="manual")
        self.refresh_tree()
        self.status_var.set(f"已关联：{group_name}")

    def _unlink_lora(self):
        its = self._selected_items()
        if not its:
            return
        for item in its:
            item.lora_group = None
            self.db.del_dataset_lora(item.name)
        self.refresh_tree()
        self.status_var.set("已取消关联")


# ================= LoRA 选择对话框 =================
class LoRAPickerDialog(tk.Toplevel):
    def __init__(self, parent, groups, on_pick):
        super().__init__(parent)
        self.withdraw()
        self.title("选择 LoRA 组")
        self.configure(bg=COLOR["bg"])
        self.transient(parent)
        self.grab_set()
        self.on_pick = on_pick

        parent.update_idletasks()
        pw = parent.winfo_width() or 1200
        ph = parent.winfo_height() or 800
        w = max(500, min(700, int(pw * 0.5)))
        h = max(400, min(600, int(ph * 0.65)))
        x = parent.winfo_rootx() + (pw - w) // 2
        y = parent.winfo_rooty() + (ph - h) // 3
        self.geometry(f"{w}x{h}+{x}+{y}")

        ttk.Label(self, text="选择一个 LoRA 组进行关联：",
                  background=COLOR["bg"]).pack(
                      side=tk.TOP, fill=tk.X, padx=10, pady=(10, 4))

        row = ttk.Frame(self)
        row.pack(side=tk.TOP, fill=tk.X, padx=10, pady=(0, 4))
        ttk.Label(row, text="🔎 搜索:").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        ttk.Entry(row, textvariable=self.search_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0))

        box = ttk.Frame(self)
        box.pack(side=tk.TOP, fill=tk.BOTH, expand=True,
                 padx=10, pady=(0, 6))
        self.listbox = tk.Listbox(box, font=('Microsoft YaHei UI', 10))
        vsb = ttk.Scrollbar(box, orient="vertical",
                            command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=vsb.set)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self._all = list(groups)
        for g in self._all:
            self.listbox.insert(tk.END, g)

        bar = ttk.Frame(self)
        bar.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=10)
        ttk.Button(bar, text="取消", command=self.destroy
                   ).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(bar, text="确定", style='Primary.TButton',
                   command=self._ok).pack(side=tk.RIGHT)

        self.listbox.bind("<Double-1>", lambda e: self._ok())
        self.search_var.trace_add("write", lambda *a: self._filter())

        self.deiconify()
        self.grab_set()

    def _filter(self):
        kw = self.search_var.get().strip().lower()
        self.listbox.delete(0, tk.END)
        for g in self._all:
            if not kw or kw in g.lower():
                self.listbox.insert(tk.END, g)

    def _ok(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        name = self.listbox.get(sel[0])
        self.on_pick(name)
        self.destroy()

# ================= 触发词编辑对话框 =================
class TriggerEditDialog(tk.Toplevel):
    def __init__(self, parent, dataset_name, current, on_ok):
        super().__init__(parent)
        self.withdraw()   # ← 关键：先隐藏
        self.title("编辑触发词")
        self.configure(bg=COLOR["bg"])
        self.transient(parent)
        self.on_ok = on_ok

        parent.update_idletasks()
        pw = parent.winfo_width() or 1200
        ph = parent.winfo_height() or 800
        w = 480
        h = 200
        x = parent.winfo_rootx() + (pw - w) // 2
        y = parent.winfo_rooty() + (ph - h) // 3
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.resizable(False, False)

        ttk.Label(self, text=f"数据集：{dataset_name}",
                  background=COLOR["bg"]).pack(
                      anchor=tk.W, padx=16, pady=(14, 4))

        ttk.Label(self, text="触发词（多个用逗号分隔）：",
                  background=COLOR["bg"]).pack(
                      anchor=tk.W, padx=16, pady=(4, 2))

        self.var = tk.StringVar(value=current)
        entry = ttk.Entry(self, textvariable=self.var)
        entry.pack(fill=tk.X, padx=16, pady=(0, 6))
        entry.focus_set()
        entry.select_range(0, tk.END)

        ttk.Label(self,
                  text="※ 修改后会保存到数据库，下次扫描仍生效",
                  foreground=COLOR["muted"],
                  font=('Microsoft YaHei UI', 8),
                  background=COLOR["bg"]).pack(
                      anchor=tk.W, padx=16)

        bar = ttk.Frame(self)
        bar.pack(side=tk.BOTTOM, fill=tk.X, padx=16, pady=12)
        ttk.Button(bar, text="取消", command=self.destroy
                   ).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(bar, text="确定", style='Primary.TButton',
                   command=self._ok).pack(side=tk.RIGHT)

        entry.bind('<Return>', lambda e: self._ok())

        # 所有控件都建好后，再一起显示
        self.deiconify()
        self.grab_set()
        entry.focus_set()

    def _ok(self):
        self.on_ok(self.var.get().strip())
        self.destroy()