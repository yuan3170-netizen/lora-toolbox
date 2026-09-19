# -*- coding: utf-8 -*-
# LoRA 前后期工具箱
# 作者：翡翠珍珠排骨 (B站 UID: 3923028)
# 主页：https://space.bilibili.com/3923028
# 协议：MIT License
"""
图片工具合集 Tab
- 面板 1：标签频率统计（排序 / 搜索 / 进度 / 取消 / 右键）
- 面板 2：相似图片查找（多线程哈希 / 进度 / 批量选优 / 右键）
- 面板 3：手动分类（焦点隔离键盘 / 多步撤销 / 只缩不放 / 进度）
"""
import os
import shutil
import threading
import queue
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from file_utils import open_path, reveal_path, copy_text

# ---------- 依赖检测 ----------
try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import imagehash
    HAS_IMAGEHASH = True
except ImportError:
    HAS_IMAGEHASH = False

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False


COLOR = {
    "bg":    "#f7f8fa",
    "card":  "#ffffff",
    "muted": "#6b7280",
}

IMG_EXTS = ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff', '.webp')


# ================================================================
# ==================== 通用 helper ===============================
# ================================================================
def make_right_click_menu(root, items):
    """
    items: [(label, callback), ...]  — callback 无参数
    返回一个 tk.Menu
    """
    m = tk.Menu(root, tearoff=0)
    for label, cb in items:
        if label == "---":
            m.add_separator()
        else:
            m.add_command(label=label, command=cb)
    return m


def make_status_bar(parent, var):
    """统一的底部状态栏"""
    lbl = tk.Label(parent, textvariable=var, anchor=tk.W,
                   bg='#eef2f7', fg=COLOR["muted"], padx=14, pady=6,
                   font=('Microsoft YaHei UI', 9))
    lbl.pack(side=tk.BOTTOM, fill=tk.X)
    return lbl


def make_progress_bar(parent):
    """统一的进度条（隐藏时高度为 0）"""
    p = ttk.Progressbar(parent, orient=tk.HORIZONTAL, mode='determinate')
    p.pack(side=tk.BOTTOM, fill=tk.X, padx=12, pady=(0, 4))
    return p


# ================================================================
# ================== 面板 1：标签频率统计 ========================
# ================================================================
class TagStatsPanel:
    def __init__(self, parent, root):
        self.parent = parent
        self.root = root
        self.is_running = False
        self.cancel_flag = False
        self.counter = Counter()
        self.all_items = []           # [(tag, cnt), ...] 原始数据
        self.sort_mode = tk.StringVar(master=parent, value="频率 ↓")
        self.search_var = tk.StringVar(master=parent)

        self.input_dir = tk.StringVar(master=parent)
        self.output_dir = tk.StringVar(master=parent)
        self.output_filename = tk.StringVar(master=parent,
                                            value="tag_frequencies.txt")
        self.status = tk.StringVar(master=parent, value="就绪 · 请选择文件夹")

        self._build_ui()
        self.search_var.trace_add("write", lambda *a: self._render())
        self.sort_mode.trace_add("write", lambda *a: self._render())

    def _build_ui(self):
        # --- 底部：状态 + 进度 ---
        self.progress = make_progress_bar(self.parent)
        self.progress.pack_forget()  # 初始隐藏
        make_status_bar(self.parent, self.status)

        # --- 顶部路径 ---
        top = ttk.LabelFrame(self.parent, text=" 输入输出 ", padding=10)
        top.pack(fill=tk.X, padx=12, pady=(12, 6))

        r = ttk.Frame(top); r.pack(fill=tk.X, pady=3)
        ttk.Label(r, text="输入文件夹", width=10).pack(side=tk.LEFT)
        ttk.Entry(r, textvariable=self.input_dir).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        ttk.Button(r, text="浏览", width=7,
                   command=lambda: self._pick(self.input_dir)).pack(side=tk.LEFT)

        r = ttk.Frame(top); r.pack(fill=tk.X, pady=3)
        ttk.Label(r, text="输出文件夹", width=10).pack(side=tk.LEFT)
        ttk.Entry(r, textvariable=self.output_dir).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        ttk.Button(r, text="浏览", width=7,
                   command=lambda: self._pick(self.output_dir)).pack(side=tk.LEFT)
        ttk.Label(r, text=" (留空=输入文件夹)", foreground=COLOR["muted"],
                  font=('Microsoft YaHei UI', 8)).pack(side=tk.LEFT)

        r = ttk.Frame(top); r.pack(fill=tk.X, pady=3)
        ttk.Label(r, text="输出文件名", width=10).pack(side=tk.LEFT)
        ttk.Entry(r, textvariable=self.output_filename).pack(
            side=tk.LEFT, fill=tk.X, expand=True)

        # --- 按钮栏 ---
        btns = ttk.Frame(self.parent)
        btns.pack(fill=tk.X, padx=12, pady=(0, 6))
        self.start_btn = ttk.Button(btns, text="▶  开始统计",
                                    style='Primary.TButton', command=self.start)
        self.start_btn.pack(side=tk.LEFT)
        self.cancel_btn = ttk.Button(btns, text="■  取消", state=tk.DISABLED,
                                     command=self.cancel)
        self.cancel_btn.pack(side=tk.LEFT, padx=8)
        self.save_btn = ttk.Button(btns, text="💾  保存结果",
                                   state=tk.DISABLED, command=self.save)
        self.save_btn.pack(side=tk.LEFT, padx=8)

        # --- 搜索 + 排序 ---
        filt = ttk.Frame(self.parent)
        filt.pack(fill=tk.X, padx=12, pady=(0, 4))
        ttk.Label(filt, text="🔎 搜索:").pack(side=tk.LEFT)
        ttk.Entry(filt, textvariable=self.search_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 12))
        ttk.Label(filt, text="排序:").pack(side=tk.LEFT)
        ttk.Combobox(filt, textvariable=self.sort_mode,
                     values=["频率 ↓", "频率 ↑", "字母 A-Z", "长度 ↓"],
                     width=12, state="readonly").pack(side=tk.LEFT, padx=4)

        # --- 结果表 ---
        box = ttk.LabelFrame(self.parent, text=" 标签频率 ", padding=6)
        box.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 6))

        cols = ("tag", "count")
        self.tree = ttk.Treeview(box, columns=cols, show="headings",
                                 selectmode="extended")
        self.tree.heading("tag", text="标签")
        self.tree.heading("count", text="频率")
        self.tree.column("tag", width=400, anchor=tk.W)
        self.tree.column("count", width=80, anchor=tk.CENTER)
        self.tree.tag_configure("odd", background="#fafbfc")

        vsb = ttk.Scrollbar(box, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # 右键菜单
        self.tree_menu = make_right_click_menu(self.root, [
            ("复制标签", self._copy_tags),
            ("复制「标签: 频率」", self._copy_tag_freq),
            ("---", None),
            ("把选中标签设为搜索内容", self._set_search_from_sel),
        ])
        self.tree.bind("<Button-3>", self._on_tree_rclick)
        self.tree.bind("<Double-1>", lambda e: self._set_search_from_sel())

    # ---------- 交互 ----------
    def _pick(self, var):
        init = var.get() or None
        d = filedialog.askdirectory(initialdir=init, title="选择文件夹")
        if d:
            var.set(d)

    def _on_tree_rclick(self, event):
        iid = self.tree.identify_row(event.y)
        if iid:
            if iid not in self.tree.selection():
                self.tree.selection_set(iid)
            self.tree_menu.tk_popup(event.x_root, event.y_root)

    def _sel_tags(self):
        return [self.tree.item(i, "values")[0] for i in self.tree.selection()]

    def _copy_tags(self):
        tags = self._sel_tags()
        if tags:
            copy_text(self.root, ", ".join(tags))

    def _copy_tag_freq(self):
        rows = []
        for i in self.tree.selection():
            v = self.tree.item(i, "values")
            rows.append(f"{v[0]}: {v[1]}")
        if rows:
            copy_text(self.root, "\n".join(rows))

    def _set_search_from_sel(self):
        sel = self.tree.selection()
        if sel:
            v = self.tree.item(sel[0], "values")
            if v:
                self.search_var.set(v[0])

    # ---------- 统计 ----------
    def start(self):
        if self.is_running:
            return
        folder = self.input_dir.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showerror("错误", "请选择有效的输入文件夹")
            return

        self.is_running = True
        self.cancel_flag = False
        self.start_btn.config(state=tk.DISABLED)
        self.cancel_btn.config(state=tk.NORMAL)
        self.save_btn.config(state=tk.DISABLED)
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self.status.set("扫描文件...")

        # 显示进度条
        self.progress.pack(side=tk.BOTTOM, fill=tk.X, padx=12, pady=(0, 4))
        self.progress["value"] = 0
        self.progress["maximum"] = 1

        threading.Thread(target=self._run, args=(folder,), daemon=True).start()

    def cancel(self):
        self.cancel_flag = True
        self.status.set("正在取消...")

    def _run(self, folder):
        # 1) 收集 txt 文件
        files = []
        try:
            for r, _, fs in os.walk(folder):
                if self.cancel_flag:
                    break
                for f in fs:
                    lf = f.lower()
                    if lf.endswith('.txt') and not lf.endswith('.txt.bak'):
                        files.append(os.path.join(r, f))
        except Exception as e:
            self.root.after(0, self._finish_error, str(e))
            return

        total = len(files)
        self.root.after(0, lambda: self._set_progress_max(total))
        counter = Counter()
        done = 0

        for p in files:
            if self.cancel_flag:
                break
            try:
                with open(p, 'r', encoding='utf-8') as fp:
                    content = fp.read()
                parts = [t.strip() for t in content.split(',')]
                tags = [t for t in parts if t]
                if tags:
                    counter.update(tags)
            except Exception:
                pass
            done += 1
            if done % 20 == 0 or done == total:
                self.root.after(0, lambda d=done, t=total:
                                self._set_progress(d, t))

        self.counter = counter
        self.root.after(0, lambda d=done, t=total:
                        self._finish(d, t))

    def _set_progress_max(self, mx):
        self.progress["maximum"] = max(1, mx)

    def _set_progress(self, cur, total):
        self.progress["value"] = cur
        self.status.set(f"统计中... {cur}/{total}")

    def _finish_error(self, err):
        self.is_running = False
        self.start_btn.config(state=tk.NORMAL)
        self.cancel_btn.config(state=tk.DISABLED)
        self.progress.pack_forget()
        self.status.set(f"错误: {err}")

    def _finish(self, done, total):
        self.is_running = False
        self.start_btn.config(state=tk.NORMAL)
        self.cancel_btn.config(state=tk.DISABLED)
        self.progress.pack_forget()

        self.all_items = sorted(self.counter.items(),
                                key=lambda x: (-x[1], x[0]))
        self._render()

        if self.all_items:
            self.save_btn.config(state=tk.NORMAL)
            self.status.set(
                f"完成 · 处理 {done} 个 txt · {len(self.counter)} 个标签"
                + ("（已取消）" if self.cancel_flag else ""))
        else:
            self.status.set("未找到任何标签")

    def _render(self):
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        kw = self.search_var.get().strip().lower()
        items = [x for x in self.all_items
                 if not kw or kw in x[0].lower()]

        mode = self.sort_mode.get()
        if mode == "频率 ↓":
            items.sort(key=lambda x: (-x[1], x[0]))
        elif mode == "频率 ↑":
            items.sort(key=lambda x: (x[1], x[0]))
        elif mode == "字母 A-Z":
            items.sort(key=lambda x: x[0].lower())
        elif mode == "长度 ↓":
            items.sort(key=lambda x: (-len(x[0]), x[0]))

        for i, (tag, cnt) in enumerate(items):
            self.tree.insert("", tk.END, values=(tag, cnt),
                             tags=("odd",) if i % 2 else ())

    def save(self):
        if not self.counter:
            return
        out_dir = (self.output_dir.get().strip()
                   or self.input_dir.get().strip())
        filename = (self.output_filename.get().strip()
                    or "tag_frequencies.txt")
        if not out_dir:
            messagebox.showerror("错误", "请选择输出文件夹")
            return
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, filename)
        items = sorted(self.counter.items(), key=lambda x: (-x[1], x[0]))
        try:
            with open(out_path, 'w', encoding='utf-8') as f:
                f.write(f"# 总计 {len(items)} 个不同标签\n")
                for tag, cnt in items:
                    f.write(f"{tag}: {cnt}\n")
            messagebox.showinfo("完成", f"已保存到：\n{out_path}")
            self.status.set(f"已保存：{out_path}")
        except Exception as e:
            messagebox.showerror("保存失败", str(e))


# ================================================================
# =============== 面板 2：相似图片查找与选择 =====================
# ================================================================
class SimilarFinderPanel:
    def __init__(self, parent, root):
        self.parent = parent
        self.root = root
        self.is_running = False
        self.cancel_flag = False

        self.folder_path = tk.StringVar(master=parent)
        self.threshold = tk.IntVar(master=parent, value=5)
        self.status = tk.StringVar(master=parent, value="就绪 · 请选择文件夹")

        self.groups = []
        self.group_vars = []
        self.current_group_index = None
        self.thumbnails = {}
        self._queue = queue.Queue()

        self._build_ui()
        self.root.after(100, self._drain_queue)

    def _build_ui(self):
        if not (HAS_PIL and HAS_IMAGEHASH):
            tk.Label(self.parent,
                     text="⚠ 相似图片查找需要：\n\n"
                          "    pip install imagehash opencv-python\n\n"
                          "装好后重启程序",
                     bg='#1e1e2e', fg='#f59e0b',
                     font=('Microsoft YaHei UI', 11),
                     justify='center').pack(expand=True, fill=tk.BOTH)
            return

        # 底部
        self.progress = make_progress_bar(self.parent)
        self.progress.pack_forget()
        make_status_bar(self.parent, self.status)

        # 顶部
        top = ttk.LabelFrame(self.parent, text=" 输入 ", padding=10)
        top.pack(fill=tk.X, padx=12, pady=(12, 6))

        r = ttk.Frame(top); r.pack(fill=tk.X, pady=3)
        ttk.Label(r, text="目标文件夹", width=10).pack(side=tk.LEFT)
        ttk.Entry(r, textvariable=self.folder_path).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        ttk.Button(r, text="浏览", width=7, command=self._pick).pack(side=tk.LEFT)

        r = ttk.Frame(top); r.pack(fill=tk.X, pady=3)
        ttk.Label(r, text="相似阈值", width=10).pack(side=tk.LEFT)
        ttk.Spinbox(r, from_=1, to=20, textvariable=self.threshold,
                    width=6).pack(side=tk.LEFT)
        ttk.Label(r, text="  (汉明距离 ≤ 阈值 = 相似)",
                  foreground=COLOR["muted"],
                  font=('Microsoft YaHei UI', 8)).pack(side=tk.LEFT)

        # 按钮
        btns = ttk.Frame(self.parent)
        btns.pack(fill=tk.X, padx=12, pady=(0, 6))
        self.scan_btn = ttk.Button(btns, text="🔎  扫描",
                                   style='Primary.TButton', command=self.scan)
        self.scan_btn.pack(side=tk.LEFT)
        self.cancel_btn = ttk.Button(btns, text="■  取消", state=tk.DISABLED,
                                     command=self.cancel)
        self.cancel_btn.pack(side=tk.LEFT, padx=8)
        self.batch_btn = ttk.Button(btns, text="⭐ 全部选最优",
                                    state=tk.DISABLED, command=self.select_best_all)
        self.batch_btn.pack(side=tk.LEFT, padx=8)
        self.execute_btn = ttk.Button(btns, text="📦  移动未保留",
                                      state=tk.DISABLED, command=self.execute_move)
        self.execute_btn.pack(side=tk.LEFT, padx=8)

        # 中部：左 + 右
        body = ttk.Frame(self.parent)
        body.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 6))
        body.columnconfigure(0, weight=1, minsize=180)
        body.columnconfigure(1, weight=4)
        body.rowconfigure(0, weight=1)

        left = ttk.LabelFrame(body, text=" 相似组 ", padding=4)
        left.grid(row=0, column=0, sticky='nsew', padx=(0, 6))
        self.group_listbox = tk.Listbox(left, selectmode=tk.SINGLE,
                                        font=('Microsoft YaHei UI', 10))
        self.group_listbox.pack(fill=tk.BOTH, expand=True)
        self.group_listbox.bind('<<ListboxSelect>>', self.on_group_select)

        right = ttk.LabelFrame(body, text=" 组内图片 ", padding=4)
        right.grid(row=0, column=1, sticky='nsew')
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        self.preview_canvas = tk.Canvas(right, bg='#f0f0f0',
                                        highlightthickness=0, bd=0)
        vsb = ttk.Scrollbar(right, orient='vertical',
                            command=self.preview_canvas.yview)
        self.preview_canvas.configure(yscrollcommand=vsb.set)
        self.preview_canvas.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')

        self.preview_inner = tk.Frame(self.preview_canvas, bg='#f0f0f0')
        self._win_id = self.preview_canvas.create_window(
            (0, 0), window=self.preview_inner, anchor='nw')
        self.preview_inner.bind('<Configure>', self._on_inner_configure)
        self.preview_canvas.bind(
            '<MouseWheel>',
            lambda e: self.preview_canvas.yview_scroll(
                int(-1 * (e.delta / 120)), 'units'))

        # 图片右键菜单（动态绑定）
        self.img_menu = make_right_click_menu(self.root, [
            ("打开图片", lambda: self._open_image(self._rclick_file)),
            ("打开所在文件夹",
             lambda: reveal_path(
                 os.path.join(self.folder_path.get(), self._rclick_file))),
            ("复制路径",
             lambda: copy_text(
                 self.root,
                 os.path.join(self.folder_path.get(), self._rclick_file))),
        ])
        self._rclick_file = None

    # ---------- 队列轮询 ----------
    def _drain_queue(self):
        try:
            while True:
                msg = self._queue.get_nowait()
                kind = msg[0]
                if kind == "progress":
                    _, cur, total = msg
                    self.progress["maximum"] = max(1, total)
                    self.progress["value"] = cur
                    self.status.set(f"计算哈希 {cur}/{total}")
                elif kind == "done":
                    _, hashes = msg
                    self._on_hash_done(hashes)
                elif kind == "error":
                    self._on_hash_error(msg[1])
        except queue.Empty:
            pass
        self.root.after(100, self._drain_queue)

    # ---------- 交互 ----------
    def _pick(self):
        init = self.folder_path.get() or None
        d = filedialog.askdirectory(initialdir=init, title="选择文件夹")
        if d:
            self.folder_path.set(d)

    def _on_inner_configure(self, _):
        self.preview_canvas.configure(
            scrollregion=self.preview_canvas.bbox('all'))

    def _open_image(self, filename):
        if filename:
            open_path(os.path.join(self.folder_path.get(), filename))

    # ---------- 扫描 ----------
    def scan(self):
        if self.is_running:
            return
        folder = self.folder_path.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showerror("错误", "请选择有效的文件夹")
            return

        self.groups = []
        self.group_vars = []
        self.group_listbox.delete(0, tk.END)
        self.clear_preview()
        self.execute_btn.config(state='disabled')
        self.batch_btn.config(state='disabled')
        self.is_running = True
        self.cancel_flag = False
        self.scan_btn.config(state=tk.DISABLED)
        self.cancel_btn.config(state=tk.NORMAL)
        self.status.set("扫描文件...")
        self.progress.pack(side=tk.BOTTOM, fill=tk.X, padx=12, pady=(0, 4))
        self.progress["value"] = 0

        exts = IMG_EXTS
        try:
            files = [f for f in os.listdir(folder) if f.lower().endswith(exts)]
        except Exception as e:
            self._reset_scan_state()
            messagebox.showerror("错误", str(e))
            return

        if len(files) < 2:
            self._reset_scan_state()
            messagebox.showinfo("提示", "图片数量不足，无法比较。")
            return

        threading.Thread(target=self._hash_worker,
                         args=(folder, files), daemon=True).start()

    def cancel(self):
        self.cancel_flag = True
        self.status.set("正在取消...")

    def _hash_worker(self, folder, files):
        """多线程计算哈希，结果通过队列发回主线程"""
        total = len(files)
        results = {}
        done = 0
        try:
            with ThreadPoolExecutor(max_workers=4) as ex:
                fut_map = {}
                for f in files:
                    if self.cancel_flag:
                        break
                    fut = ex.submit(self._hash_one,
                                    os.path.join(folder, f))
                    fut_map[fut] = f
                for fut in as_completed(fut_map):
                    if self.cancel_flag:
                        break
                    f = fut_map[fut]
                    try:
                        h = fut.result()
                        if h is not None:
                            results[f] = h
                    except Exception:
                        pass
                    done += 1
                    if done % 10 == 0 or done == total:
                        self._queue.put(("progress", done, total))
        except Exception as e:
            self._queue.put(("error", str(e)))
            return
        self._queue.put(("done", results))

    @staticmethod
    def _hash_one(path):
        try:
            with Image.open(path) as img:
                return imagehash.phash(img)
        except Exception:
            return None

    def _on_hash_error(self, err):
        self._reset_scan_state()
        messagebox.showerror("错误", err)

    def _on_hash_done(self, hashes):
        self._reset_scan_state()
        if self.cancel_flag:
            self.status.set("已取消")
            return
        if len(hashes) < 2:
            messagebox.showinfo("提示", "有效图片不足。")
            return

        threshold = self.threshold.get()
        grouped = []
        processed = set()
        for name1, h1 in hashes.items():
            if name1 in processed:
                continue
            group = [name1]
            for name2, h2 in hashes.items():
                if name2 not in processed and name1 != name2:
                    if h1 - h2 < threshold:
                        group.append(name2)
                        processed.add(name2)
            if len(group) > 1:
                grouped.append(group)
            processed.add(name1)

        if not grouped:
            messagebox.showinfo("结果", "未找到相似的图片。")
            self.status.set("未找到相似图片")
            return

        self.groups = grouped
        self.status.set(f"找到 {len(grouped)} 组相似图片")

        folder = self.folder_path.get()
        for i, group in enumerate(grouped, 1):
            self.group_listbox.insert(tk.END, f"组 {i} ({len(group)}张)")
        for group in grouped:
            var = tk.StringVar(master=self.parent)
            var.set(self.pick_best_by_quality(folder, group))
            self.group_vars.append(var)

        self.execute_btn.config(state='normal')
        self.batch_btn.config(state='normal')
        if self.group_listbox.size() > 0:
            self.group_listbox.selection_set(0)
            self.on_group_select(None)

    def _reset_scan_state(self):
        self.is_running = False
        self.scan_btn.config(state=tk.NORMAL)
        self.cancel_btn.config(state=tk.DISABLED)
        self.progress.pack_forget()

    def pick_best_by_quality(self, folder, group):
        """基于拉普拉斯方差挑最清晰的一张"""
        if not HAS_CV2:
            return group[0]
        best_score = -1
        best_name = group[0]
        for name in group:
            try:
                img = cv2.imread(os.path.join(folder, name))
                if img is None:
                    continue
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                score = cv2.Laplacian(gray, cv2.CV_64F).var()
                if score > best_score:
                    best_score = score
                    best_name = name
            except Exception:
                pass
        return best_name

    def select_best_all(self):
        """一键把所有组都选为最清晰的那张"""
        if not self.groups:
            return
        folder = self.folder_path.get()
        for idx, group in enumerate(self.groups):
            best = self.pick_best_by_quality(folder, group)
            self.group_vars[idx].set(best)
        # 刷新显示
        if self.current_group_index is not None:
            self.display_group(self.current_group_index)
        self.status.set(f"已为 {len(self.groups)} 组选择最佳图")

    # ---------- 预览 ----------
    def clear_preview(self):
        for w in self.preview_inner.winfo_children():
            w.destroy()
        self.thumbnails.clear()

    def on_group_select(self, event):
        sel = self.group_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx >= len(self.groups):
            return
        self.current_group_index = idx
        self.display_group(idx)

    def display_group(self, index):
        self.clear_preview()
        group = self.groups[index]
        var = self.group_vars[index]
        folder = self.folder_path.get()
        if not folder:
            return

        cols = 4
        for i, filename in enumerate(group):
            frame = tk.Frame(self.preview_inner, bd=2, relief=tk.RIDGE,
                             bg='white')
            frame.grid(row=i // cols, column=i % cols,
                       padx=8, pady=8, sticky='n')

            tk_img = None
            try:
                with Image.open(os.path.join(folder, filename)) as pil_img:
                    pil = pil_img.copy()
                pil.thumbnail((200, 200), Image.LANCZOS)
                tk_img = ImageTk.PhotoImage(pil)
                self.thumbnails[filename] = tk_img
            except Exception:
                pass

            if tk_img:
                lbl = tk.Label(frame, image=tk_img, bg='white')
                lbl.pack(pady=4)
            else:
                lbl = tk.Label(frame, text="(无法预览)", bg='white')
                lbl.pack(pady=4)

            info = f"{filename}\n"
            if HAS_CV2:
                try:
                    img = cv2.imread(os.path.join(folder, filename))
                    if img is not None:
                        h, w = img.shape[:2]
                        info += f"{w}×{h}\n"
                        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                        cl = cv2.Laplacian(gray, cv2.CV_64F).var()
                        info += f"清晰度: {cl:.0f}\n"
                except Exception:
                    pass
            try:
                size_kb = os.path.getsize(os.path.join(folder, filename)) / 1024
                info += f"{size_kb:.0f} KB"
            except Exception:
                pass

            tk.Label(frame, text=info, bg='white', justify=tk.LEFT,
                     font=('Microsoft YaHei UI', 8)).pack(pady=2)
            tk.Radiobutton(frame, text="✅ 保留", variable=var, value=filename,
                           bg='white',
                           font=('Microsoft YaHei UI', 9, 'bold')).pack(pady=4)

            # 右键菜单：只对图片 Label 绑定
            for widget in frame.winfo_children():
                widget.bind("<Button-3>",
                            lambda e, fn=filename: self._on_img_rclick(e, fn))

        self.preview_inner.update_idletasks()
        self.preview_canvas.configure(
            scrollregion=self.preview_canvas.bbox('all'))

    def _on_img_rclick(self, event, filename):
        self._rclick_file = filename
        self.img_menu.tk_popup(event.x_root, event.y_root)

    # ---------- 执行移动 ----------
    def execute_move(self):
        if not self.groups:
            messagebox.showinfo("提示", "没有可处理的相似组。")
            return
        folder = self.folder_path.get()
        if not folder:
            return

        to_move = []
        for idx, group in enumerate(self.groups):
            selected = self.group_vars[idx].get()
            for f in group:
                if f != selected:
                    to_move.append(f)

        if not to_move:
            messagebox.showinfo("提示", "每组都已选择保留，无需移动。")
            return

        dest_dir = os.path.join(folder, "_similar_removed")
        if not messagebox.askyesno(
                "确认移动",
                f"将移动 {len(to_move)} 张未保留图片到：\n{dest_dir}\n\n确定？"):
            return

        os.makedirs(dest_dir, exist_ok=True)
        moved = 0
        for f in to_move:
            src = os.path.join(folder, f)
            dst = os.path.join(dest_dir, f)
            if os.path.exists(dst):
                base, ext = os.path.splitext(f)
                cnt = 1
                while os.path.exists(os.path.join(dest_dir,
                                                  f"{base}_{cnt}{ext}")):
                    cnt += 1
                dst = os.path.join(dest_dir, f"{base}_{cnt}{ext}")
            try:
                shutil.move(src, dst)
                moved += 1
            except Exception:
                pass

        self.status.set(f"✅ 已移动 {moved} 张图片到 {dest_dir}")
        messagebox.showinfo("完成",
                            f"已移动 {moved} 张图片。\n\n目标目录：{dest_dir}")
        self.execute_btn.config(state='disabled')


# ================================================================
# =============== 面板 3：手动挑选分类图片 =======================
# ================================================================
class ManualSorterPanel:
    def __init__(self, parent, root):
        self.parent = parent
        self.root = root

        self.source_dir = None
        self.good_dir = None
        self.bad_dir = None
        self.image_files = []
        self.current_index = 0
        self.current_pil_img = None
        self.history = []          # 多步撤销栈
        self._active = False       # 键盘是否激活（鼠标悬停在图片区）

        self.src_var = tk.StringVar(master=parent, value="（未选择）")
        self.good_var = tk.StringVar(master=parent, value="（未选择）")
        self.bad_var = tk.StringVar(master=parent, value="（未选择）")
        self.progress_var = tk.StringVar(
            master=parent, value="请先选择 3 个文件夹，然后点「开始整理」")

        self._build_ui()

    def _build_ui(self):
        if not HAS_PIL:
            tk.Label(self.parent, text="⚠ 需要 Pillow：pip install pillow",
                     bg='#1e1e2e', fg='#f59e0b',
                     font=('Microsoft YaHei UI', 11)).pack(
                         expand=True, fill=tk.BOTH)
            return

        # 底部状态栏（横跨整宽）
        make_status_bar(self.parent, self.progress_var)

        # ============ 左右分栏主体 ============
        body = ttk.Frame(self.parent)
        body.pack(fill=tk.BOTH, expand=True, padx=12, pady=(12, 6))
        body.columnconfigure(0, weight=0, minsize=420)   # 左栏固定最小宽
        body.columnconfigure(1, weight=1)                 # 右栏吃剩余空间
        body.rowconfigure(0, weight=1)

        # ---------------- 左栏 ----------------
        left = ttk.Frame(body)
        left.grid(row=0, column=0, sticky='nsew', padx=(0, 10))

        # 文件夹选择
        top = ttk.LabelFrame(left, text=" 文件夹选择 ", padding=10)
        top.pack(fill=tk.X, pady=(0, 8))
        top.columnconfigure(1, weight=1)

        rows = [
            ("📂 待整理:", self.src_var, self._pick_src),
            ("❤️ 喜欢(1):", self.good_var, self._pick_good),
            ("💔 不喜欢(2):", self.bad_var, self._pick_bad),
        ]
        for i, (label, var, cmd) in enumerate(rows):
            ttk.Label(top, text=label, width=12).grid(
                row=i, column=0, sticky='w', pady=3)
            ttk.Entry(top, textvariable=var).grid(
                row=i, column=1, sticky='ew', padx=(4, 4))
            ttk.Button(top, text="浏览", width=6,
                       command=cmd).grid(row=i, column=2)

        # 按钮区
        bar = ttk.Frame(left)
        bar.pack(fill=tk.X, pady=(0, 8))
        self.start_btn = ttk.Button(bar, text="▶  开始整理",
                                    style='Primary.TButton',
                                    command=self.start_sorting)
        self.start_btn.pack(fill=tk.X, pady=(0, 4))
        self.undo_btn = ttk.Button(bar, text="↩️  撤销上一步",
                                   state=tk.DISABLED,
                                   command=self.undo_last_action)
        self.undo_btn.pack(fill=tk.X)

        # 快捷键说明（竖排，左栏）
        tip = ttk.LabelFrame(left, text=" 快捷键（鼠标移到右侧图上才生效） ",
                             padding=8)
        tip.pack(fill=tk.X, pady=(0, 8))
        for k, v in [
            ("1", "❤️  喜欢（移到喜欢文件夹）"),
            ("2", "💔  不喜欢（移到不喜欢文件夹）"),
            ("空格 / S", "⏭️  跳过这张"),
            ("3", "↩️  撤销上一步"),
            ("Q", "退出整理"),
        ]:
            row = ttk.Frame(tip)
            row.pack(fill=tk.X, pady=2)
            ttk.Label(row, text=f"[{k}]", width=8, anchor='w',
                      foreground="#3b82f6",
                      font=('Microsoft YaHei UI', 9, 'bold')).pack(side=tk.LEFT)
            ttk.Label(row, text=v,
                      font=('Microsoft YaHei UI', 9)).pack(side=tk.LEFT)

        # 当前进度显示
        prog_box = ttk.LabelFrame(left, text=" 当前进度 ", padding=8)
        prog_box.pack(fill=tk.X)
        tk.Label(prog_box, textvariable=self.progress_var,
                 anchor='w', justify='left', wraplength=380,
                 bg=COLOR["card"], fg=COLOR["muted"],
                 font=('Microsoft YaHei UI', 9)).pack(fill=tk.X)

        # ---------------- 右栏：图片 ----------------
        right = ttk.LabelFrame(body, text=" 图片预览 ", padding=4)
        right.grid(row=0, column=1, sticky='nsew')
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        self.image_frame = tk.Frame(right, bg='#222222',
                                    highlightthickness=0)
        self.image_frame.grid(row=0, column=0, sticky='nsew')

        self.img_label = tk.Label(self.image_frame, bg='#222222')
        self.img_label.pack(fill=tk.BOTH, expand=True)

        # 鼠标进入/离开图片区 → 切换键盘激活状态（蓝框提示）
        for w in (self.image_frame, self.img_label):
            w.bind('<Enter>', lambda e: self._set_active(True))
            w.bind('<Leave>', lambda e: self._set_active(False))

        # 图片区尺寸变化 → 重绘
        self.image_frame.bind('<Configure>', self._on_resize)

        # 键盘绑定到顶层窗口，但只在 _active 时响应
        self.root.bind('<Key>', self._on_key, add='+')

    def _set_active(self, flag):
        self._active = flag
        if flag:
            self.image_frame.config(highlightthickness=2,
                                    highlightbackground="#3b82f6")
        else:
            self.image_frame.config(highlightthickness=0)

    def _pick_src(self):
        d = filedialog.askdirectory(title="选择待整理文件夹")
        if d:
            self.source_dir = d
            self.src_var.set(d)

    def _pick_good(self):
        d = filedialog.askdirectory(title="选择「喜欢」保存文件夹")
        if d:
            self.good_dir = d
            self.good_var.set(d)

    def _pick_bad(self):
        d = filedialog.askdirectory(title="选择「不喜欢」保存文件夹")
        if d:
            self.bad_dir = d
            self.bad_var.set(d)

    # ---------- 开始 ----------
    def start_sorting(self):
        if not all([self.source_dir, self.good_dir, self.bad_dir]):
            messagebox.showwarning("提示", "请先完成三个文件夹的选择！")
            return
        if not os.path.isdir(self.source_dir):
            messagebox.showerror("错误", "源文件夹不存在！")
            return

        os.makedirs(self.good_dir, exist_ok=True)
        os.makedirs(self.bad_dir, exist_ok=True)

        files = sorted(f for f in os.listdir(self.source_dir)
                       if f.lower().endswith(IMG_EXTS))
        if not files:
            messagebox.showinfo("提示", "文件夹里没有图片")
            return

        self.image_files = files
        self.current_index = 0
        self.history = []
        self.undo_btn.config(state='disabled')
        self.start_btn.config(state=tk.DISABLED, text="整理中...")
        self._show_current()

    def _show_current(self):
        if self.current_index >= len(self.image_files):
            self._finish()
            return
        name = self.image_files[self.current_index]
        path = os.path.join(self.source_dir, name)
        if not os.path.exists(path):
            self.current_index += 1
            self._show_current()
            return
        try:
            self.current_pil_img = Image.open(path)
        except Exception:
            self.progress_var.set(f"⚠ 无法读取 {name}，跳过")
            self.current_index += 1
            self.root.after(300, self._show_current)
            return
        total = len(self.image_files)
        self.progress_var.set(
            f"[{self.current_index+1}/{total}] {name}")
        self._update_display()

    def _update_display(self):
        if self.current_pil_img is None:
            return
        fw = self.image_frame.winfo_width()
        fh = self.image_frame.winfo_height()
        if fw <= 10 or fh <= 10:
            fw, fh = 800, 500

        # 关键：只缩不放
        img = self.current_pil_img.copy()
        iw, ih = img.size
        if iw > fw or ih > fh:
            ratio = min(fw / iw, fh / ih)
            new_size = (max(1, int(iw * ratio)), max(1, int(ih * ratio)))
            img = img.resize(new_size, Image.LANCZOS)

        photo = ImageTk.PhotoImage(img)
        self.img_label.config(image=photo)
        self.img_label.image = photo

    def _on_resize(self, _):
        if self.current_pil_img is not None:
            self._update_display()

    # ---------- 撤销（支持多步） ----------
    def undo_last_action(self):
        if not self.history:
            self.progress_var.set("没有可以撤销的操作")
            return
        action = self.history.pop()
        src = action['src']
        dst = action['dst']
        name = action['name']

        if not os.path.exists(dst):
            messagebox.showerror("撤销失败", f"'{name}' 已不存在")
            self.undo_btn.config(
                state='normal' if self.history else 'disabled')
            return

        if os.path.exists(src):
            base, ext = os.path.splitext(name)
            src = os.path.join(self.source_dir, f"{base}_恢复{ext}")
        try:
            shutil.move(dst, src)
            self.progress_var.set(
                f"↩️ 已撤销: {os.path.basename(src)} "
                f"(剩余 {len(self.history)} 步)")
        except Exception as e:
            messagebox.showerror("撤销失败", str(e))
            return

        self.undo_btn.config(state='normal' if self.history else 'disabled')
        if self.current_index > 0:
            self.current_index -= 1
        self._show_current()

    # ---------- 键盘（只在鼠标悬停图片区时生效） ----------
    def _on_key(self, event):
        if not self._active:
            return
        if event.state & 0x4:      # Ctrl 组合忽略
            return
        if not self.image_files:
            return
        if self.current_index >= len(self.image_files):
            return
        if not self.source_dir:
            return

        key = event.char
        current = self.image_files[self.current_index]
        src = os.path.join(self.source_dir, current)
        if not os.path.exists(src):
            self.current_index += 1
            self._show_current()
            return

        if key == '1':
            target_dir, label = self.good_dir, "❤️ 喜欢"
        elif key == '2':
            target_dir, label = self.bad_dir, "💔 不喜欢"
        elif key == '3':
            self.undo_last_action()
            return
        elif key in (' ', 's'):
            self.progress_var.set(f"⏭️ 跳过: {current}")
            self.current_index += 1
            self._show_current()
            return
        elif key.lower() == 'q':
            if messagebox.askyesno("退出", "确定退出整理？进度不会丢。"):
                self.start_btn.config(state=tk.NORMAL, text="▶  开始整理")
                self.image_files = []
                self.img_label.config(image='')
            return
        else:
            return

        try:
            dst = os.path.join(target_dir, current)
            if os.path.exists(dst):
                base, ext = os.path.splitext(current)
                cnt = 1
                while os.path.exists(os.path.join(target_dir,
                                                  f"{base}_{cnt}{ext}")):
                    cnt += 1
                dst = os.path.join(target_dir, f"{base}_{cnt}{ext}")

            self.history.append({'src': src, 'dst': dst, 'name': current})
            self.undo_btn.config(state='normal')
            shutil.move(src, dst)
            self.progress_var.set(
                f"✅ {label} → {os.path.basename(dst)}")
        except Exception as e:
            messagebox.showerror("移动失败", str(e))
            self.history.pop()
            self.undo_btn.config(state='normal' if self.history else 'disabled')
            self.current_index += 1
            self._show_current()
            return

        self.current_index += 1
        self._show_current()

    def _finish(self):
        self.progress_var.set("🎉 所有图片已整理完毕！")
        self.img_label.config(image='')
        self.current_pil_img = None
        self.start_btn.config(state=tk.NORMAL, text="▶  重新整理")
        self.undo_btn.config(state='disabled')
        self.history = []
        self.image_files = []
        messagebox.showinfo("完成", "所有图片已处理完毕！")


# ================================================================
# =================== 外层 Tab：图片工具 =========================
# ================================================================
class ImageToolsTab:
    def __init__(self, parent, root):
        self.parent = parent
        self.root = root

        nb = ttk.Notebook(parent)
        nb.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        t1 = ttk.Frame(nb)
        nb.add(t1, text="  📊  标签统计  ")
        TagStatsPanel(t1, root)

        t2 = ttk.Frame(nb)
        nb.add(t2, text="  🔍  相似查找  ")
        SimilarFinderPanel(t2, root)

        t3 = ttk.Frame(nb)
        nb.add(t3, text="  🖼️  手动分类  ")
        ManualSorterPanel(t3, root)