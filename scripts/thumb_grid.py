# -*- coding: utf-8 -*-
# LoRA 前后期工具箱
# 作者：翡翠珍珠排骨 (B站 UID: 3923028)
# 主页：https://space.bilibili.com/3923028
# 协议：MIT License
"""
统一的缩略图网格组件
- ThumbCache: 磁盘缓存
- ThumbGrid:  缩略图网格面板（先建空框，后分批填图）
"""
import os
import hashlib
import tkinter as tk
from tkinter import ttk

try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

from file_utils import open_path, reveal_path, copy_text
from paths import THUMB_CACHE_DIR


DEFAULT_COLOR = {
    "border": "#e5e7eb",
    "text":   "#111827",
    "muted":  "#6b7280",
    "canvas": "#1e1e2e",
}


# ================= 磁盘缓存 =================
class ThumbCache:
    def __init__(self, cache_dir):
        self.cache_dir = cache_dir
        try:
            os.makedirs(cache_dir, exist_ok=True)
        except Exception:
            pass

    def _key(self, path):
        try:
            mtime = int(os.path.getmtime(path))
        except Exception:
            mtime = 0
        try:
            abspath = os.path.abspath(path)
        except Exception:
            abspath = path
        s = f"{abspath}|{mtime}"
        return hashlib.md5(s.encode('utf-8')).hexdigest()

    def get(self, path):
        if not HAS_PIL:
            return None
        key = self._key(path)
        cp = os.path.join(self.cache_dir, key + '.png')
        if not os.path.isfile(cp):
            return None
        try:
            img = Image.open(cp)
            img.load()
            return img
        except Exception:
            try:
                os.remove(cp)
            except Exception:
                pass
            return None

    def put(self, path, pil_img):
        if not HAS_PIL:
            return
        key = self._key(path)
        cp = os.path.join(self.cache_dir, key + '.png')
        try:
            pil_img.save(cp, 'PNG', optimize=True)
        except Exception:
            pass

    def clear(self):
        count = 0
        try:
            for f in os.listdir(self.cache_dir):
                try:
                    os.remove(os.path.join(self.cache_dir, f))
                    count += 1
                except Exception:
                    pass
        except Exception:
            pass
        return count

    def size(self):
        total = 0
        try:
            for f in os.listdir(self.cache_dir):
                try:
                    total += os.path.getsize(os.path.join(self.cache_dir, f))
                except Exception:
                    pass
        except Exception:
            pass
        return total

    def count(self):
        try:
            return len([f for f in os.listdir(self.cache_dir)
                        if f.endswith('.png')])
        except Exception:
            return 0


# ================= 缩略图网格 =================
class ThumbGrid:
    """
    数据格式：items = [(img_path, display_name, subtitle, target), ...]
        img_path     —— 缩略图源（可以为 None）
        display_name —— 主标题
        subtitle     —— 次标题（可以为 None）
        target       —— 打开时用的路径
    """

    def __init__(self, parent, root, on_open,
                 empty_hint="未选中",
                 thumb_size=(140, 140),
                 max_thumbs=300,
                 colors=None):
        self.parent = parent
        self.root = root
        self.on_open = on_open
        self.empty_hint = empty_hint
        self.thumb_size = thumb_size
        self.max_thumbs = max_thumbs
        self.colors = colors or DEFAULT_COLOR

        self.thumb_refs = []
        self.thumb_cache = {}
        self.disk_cache = ThumbCache(THUMB_CACHE_DIR)
        self.items = []
        self._cell_data = []
        self._fill_index = 0
        self._fill_after_id = None
        self._resume_id = None
        self._resize_id = None
        self._current_cols = 0
        self._pending_width = None
        self._is_resizing = False
        self._build()

    def _build(self):
        bg = self.colors["canvas"]
        self.canvas = tk.Canvas(self.parent, bg=bg,
                                highlightthickness=0, bd=0)
        self.vsb = ttk.Scrollbar(self.parent, orient='vertical',
                                 command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self.inner = tk.Frame(self.canvas, bg=bg)
        self.inner_id = self.canvas.create_window(
            (0, 0), window=self.inner, anchor='nw')
        self.inner.bind('<Configure>',
                        lambda e: self.canvas.configure(
                            scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', self._on_canvas_configure)
        self.canvas.bind('<Enter>', self._enable_wheel)
        self.canvas.bind('<Leave>', self._disable_wheel)
        self.inner.bind('<Enter>', self._enable_wheel)
        self.inner.bind('<Leave>', self._disable_wheel)
        self.vsb.bind('<Enter>', self._enable_wheel)
        self.vsb.bind('<Leave>', self._disable_wheel)

        self._show_empty()

    def _show_empty(self):
        for w in self.inner.winfo_children():
            w.destroy()
        tk.Label(self.inner, text=self.empty_hint,
                 bg=self.colors["canvas"], fg=self.colors["muted"],
                 font=('Microsoft YaHei UI', 11),
                 justify='center').pack(pady=60)
        self.canvas.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox('all'))

    # ---------- 滚轮 ----------
    def _enable_wheel(self, event=None):
        try:
            self.canvas.bind_all('<MouseWheel>', self._on_wheel)
        except Exception:
            pass

    def _disable_wheel(self, event=None):
        try:
            x, y = self.canvas.winfo_pointerxy()
            cx = self.canvas.winfo_rootx()
            cy = self.canvas.winfo_rooty()
            cw = self.canvas.winfo_width()
            ch = self.canvas.winfo_height()
            if cx <= x < cx + cw and cy <= y < cy + ch:
                return
        except Exception:
            pass
        try:
            self.canvas.unbind_all('<MouseWheel>')
        except Exception:
            pass

    def _on_wheel(self, event):
        if self._fill_after_id is not None:
            try:
                self.root.after_cancel(self._fill_after_id)
            except Exception:
                pass
            self._fill_after_id = None
        try:
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), 'units')
        except Exception:
            pass
        if self._resume_id is not None:
            try:
                self.root.after_cancel(self._resume_id)
            except Exception:
                pass
        self._resume_id = self.root.after(200, self._resume_fill)

    def _resume_fill(self):
        self._resume_id = None
        if self._fill_after_id is None and \
           self._fill_index < len(self._cell_data):
            self._fill_next_batch()

    def _on_canvas_configure(self, event):
        # 拖动时：把 inner 藏起来，让 Tk 不用重绘几百个 cell
        if not self._is_resizing:
            self._is_resizing = True
            try:
                self.canvas.itemconfig(self.inner_id, state='hidden')
            except Exception:
                pass

        self._pending_width = event.width
        if self._resize_id is not None:
            try:
                self.root.after_cancel(self._resize_id)
            except Exception:
                pass
        self._resize_id = self.root.after(200, self._apply_resize)

    def _apply_resize(self):
        self._resize_id = None
        self._is_resizing = False
        if self._pending_width is None:
            return
        try:
            self.canvas.itemconfig(self.inner_id, width=self._pending_width)
            self.canvas.itemconfig(self.inner_id, state='normal')
        except Exception:
            pass
        self._rearrange()

    def _rearrange(self):
        """窗口尺寸变化时重新排列 cell（只改 grid 位置，不重建）"""
        self._resize_id = None
        if not self._cell_data:
            return
        canvas_w = self.canvas.winfo_width()
        if canvas_w < 100:
            return
        cols = max(1, canvas_w // (self.thumb_size[0] + 30))
        if cols == self._current_cols:
            return
        self._current_cols = cols
        for i, entry in enumerate(self._cell_data):
            cell = entry[0]
            row = i // cols
            col = i % cols
            cell.grid(row=row, column=col, padx=6, pady=6, sticky='n')
        self.canvas.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox('all'))

    # ---------- 设置图片 ----------
    def set_images(self, items):
        if self._fill_after_id is not None:
            try:
                self.root.after_cancel(self._fill_after_id)
            except Exception:
                pass
            self._fill_after_id = None
        if self._resume_id is not None:
            try:
                self.root.after_cancel(self._resume_id)
            except Exception:
                pass
            self._resume_id = None

        for w in self.inner.winfo_children():
            w.destroy()
        self.thumb_refs.clear()
        self.items = list(items or [])
        self._cell_data = []
        self._fill_index = 0

        if not self.items:
            self._show_empty()
            return

        shown = self.items[:self.max_thumbs]
        hidden = len(self.items) - len(shown)

        canvas_w = self.canvas.winfo_width()
        if canvas_w < 100:
            canvas_w = 700
        cols = max(1, canvas_w // (self.thumb_size[0] + 30))
        self._current_cols = cols

        grid = tk.Frame(self.inner, bg=self.colors["canvas"])
        grid.pack(fill=tk.BOTH, expand=True)

        for i, item in enumerate(shown):
            img_path, name, subtitle, target = item
            row = i // cols
            col = i % cols

            cell = tk.Frame(grid, bg='#ffffff', padx=5, pady=5,
                            highlightbackground=self.colors["border"],
                            highlightthickness=1)
            cell.grid(row=row, column=col, padx=6, pady=6, sticky='n')

            holder = tk.Frame(cell, bg='#ffffff',
                              width=self.thumb_size[0],
                              height=self.thumb_size[1])
            holder.pack()
            holder.pack_propagate(False)

            lbl = tk.Label(holder, bg='#ffffff', text="",
                           font=('Microsoft YaHei UI', 9),
                           anchor='center')
            lbl.place(x=0, y=0, relwidth=1, relheight=1)

            disp = name if len(name) <= 24 else \
                name[:11] + "…" + name[-10:]
            nm = tk.Label(cell, text=disp, bg='#ffffff',
                          fg=self.colors["text"],
                          font=('Microsoft YaHei UI', 8),
                          cursor='hand2',
                          wraplength=self.thumb_size[0])
            nm.pack()

            sub_lbl = None
            if subtitle:
                s = subtitle if len(subtitle) <= 26 else subtitle[:24] + "…"
                sub_lbl = tk.Label(cell, text=s, bg='#ffffff',
                                   fg=self.colors["muted"],
                                   font=('Microsoft YaHei UI', 7),
                                   cursor='hand2',
                                   wraplength=self.thumb_size[0])
                sub_lbl.pack()

            def on_click(e, p=target):
                self.on_open(p)

            def on_rclick(e, p=target):
                m = tk.Menu(self.root, tearoff=0)
                m.add_command(label="打开",
                              command=lambda p=p: open_path(p))
                m.add_command(label="打开所在文件夹",
                              command=lambda p=p: reveal_path(p))
                m.add_command(label="复制路径",
                              command=lambda p=p: copy_text(self.root, p))
                m.tk_popup(e.x_root, e.y_root)

            widgets = [cell, holder, lbl, nm]
            if sub_lbl:
                widgets.append(sub_lbl)
            for w in widgets:
                w.bind('<Button-1>', on_click)
                w.bind('<Button-3>', on_rclick)
                w.bind('<Enter>', self._enable_wheel, add='+')
                w.bind('<Leave>', self._disable_wheel, add='+')

            self._cell_data.append((cell, holder, lbl, img_path))

        if hidden > 0:
            tk.Label(self.inner,
                     text=f"... 还有 {hidden} 张未显示",
                     bg=self.colors["canvas"],
                     fg=self.colors["muted"],
                     font=('Microsoft YaHei UI', 9)).pack(pady=10)

        self.canvas.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox('all'))

        self._fill_next_batch()

    def _fill_next_batch(self):
        BATCH = 4
        end = min(self._fill_index + BATCH, len(self._cell_data))
        for i in range(self._fill_index, end):
            _, holder, lbl, img_path = self._cell_data[i]
            if not img_path:
                lbl.config(text="🖼\n(无预览)",
                           fg=self.colors["muted"])
                continue
            photo = self._get_thumb(img_path)
            if photo:
                self.thumb_refs.append(photo)
                lbl.config(image=photo, text="")
            else:
                lbl.config(text="(无预览)")
        self._fill_index = end

        if self._fill_index < len(self._cell_data):
            try:
                self.canvas.update_idletasks()
            except Exception:
                pass
            self._fill_after_id = self.root.after(
                1, self._fill_next_batch)
        else:
            self._fill_after_id = None

    def _get_thumb(self, path):
        if not HAS_PIL or not os.path.isfile(path):
            return None
        try:
            mtime = os.path.getmtime(path)
        except Exception:
            mtime = 0
        key = (path, mtime)

        if key in self.thumb_cache:
            return self.thumb_cache[key]
        if len(self.thumb_cache) > 500:
            self.thumb_cache.clear()

        pil_img = self.disk_cache.get(path)
        if pil_img is None:
            pil_img = self._make_pil_thumb(path)
            if pil_img is not None:
                self.disk_cache.put(path, pil_img)
        if pil_img is None:
            return None

        try:
            photo = ImageTk.PhotoImage(pil_img)
            self.thumb_cache[key] = photo
            return photo
        except Exception:
            return None

    def _make_pil_thumb(self, path):
        if not HAS_PIL:
            return None
        try:
            with Image.open(path) as raw:
                img = raw.convert("RGBA")
            bg = Image.new("RGB", img.size, (30, 30, 46))
            bg.paste(img, mask=img.split()[-1])
            bg.thumbnail(self.thumb_size, Image.LANCZOS)
            return bg
        except Exception:
            return None