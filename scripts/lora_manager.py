# -*- coding: utf-8 -*-
# LoRA 前后期工具箱
# 作者：翡翠珍珠排骨 (B站 UID: 3923028)
# 主页：https://space.bilibili.com/3923028
# 协议：MIT License
"""
LoRA 管理器 v3（Loss 曲线版）
- 详情面板 5 Tab：详情 / 日志 / 参数 / 批次 / Loss
- Loss 曲线：自动匹配 + 手动指定训练日志
"""
import os
import sys
import csv
import json
import uuid
import queue
import ctypes
import shutil
import subprocess
import threading
import datetime
import bisect
import re
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# ---- 便携包路径 ----
from paths import (
    LORA_CONFIG_DIR as _PATHS_LORA_CFG,
    LORA_DB_FILE as _PATHS_LORA_DB,
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
    from send2trash import send2trash
    HAS_TRASH = True
except ImportError:
    HAS_TRASH = False

# ---- 日志解析模块 ----
try:
    import log_parser
    HAS_LOG_PARSER = True
except ImportError:
    HAS_LOG_PARSER = False

# ---- matplotlib ----
try:
    import matplotlib
    matplotlib.rcParams['font.sans-serif'] = [
        'Microsoft YaHei', 'SimHei', 'SimSun', 'DejaVu Sans'
    ]
    matplotlib.rcParams['axes.unicode_minus'] = False
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    HAS_MPL = True
except ImportError:
    HAS_MPL = False


# ================= DPI 处理 =================
def enable_dpi_awareness():
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)
        return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def get_system_dpi():
    if sys.platform != "win32":
        return 96
    try:
        hdc = ctypes.windll.user32.GetDC(0)
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)
        ctypes.windll.user32.ReleaseDC(0, hdc)
        return int(dpi) if dpi > 0 else 96
    except Exception:
        return 96


def apply_dpi_scaling(root):
    dpi = get_system_dpi()
    try:
        root.tk.call("tk", "scaling", dpi / 72.0)
    except Exception:
        pass


def calc_window_size(root, max_w=1800, max_h=1000,
                     min_w=1000, min_h=650,
                     w_ratio=0.88, h_ratio=0.85):
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    w = min(max_w, int(sw * w_ratio), sw - 40)
    h = min(max_h, int(sh * h_ratio), sh - 80)
    w = max(w, min(min_w, sw - 20))
    h = max(h, min(min_h, sh - 60))
    return int(w), int(h)


def center_on_screen(win, w, h):
    try:
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 3)
        win.geometry(f"{w}x{h}+{x}+{y}")
    except Exception:
        win.geometry(f"{w}x{h}")


def center_on_parent(win, parent, w, h):
    try:
        parent.update_idletasks()
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        x = px + max(0, (pw - w) // 2)
        y = py + max(0, (ph - h) // 3)
        win.geometry(f"{w}x{h}+{x}+{y}")
    except Exception:
        win.geometry(f"{w}x{h}")


# ================= 常量 =================
COLOR = {
    "bg":        "#f7f8fa",
    "card":      "#ffffff",
    "border":    "#e5e7eb",
    "primary":   "#3b82f6",
    "primary_h": "#2563eb",
    "success":   "#10b981",
    "danger":    "#ef4444",
    "warning":   "#f59e0b",
    "text":      "#111827",
    "muted":     "#6b7280",
    "log_bg":    "#0f172a",
    "log_fg":    "#e2e8f0",
}

STATE_KEEP    = "keep"
STATE_CLEAN   = "clean"
STATE_ARCHIVE = "archive"
STATE_NONE    = None

STATE_ICON = {
    STATE_KEEP:    "⭐",
    STATE_CLEAN:   "🗑",
    STATE_ARCHIVE: "📦",
    STATE_NONE:    "·",
}
STATE_LABEL = {
    STATE_KEEP:    "保留",
    STATE_CLEAN:   "待清理",
    STATE_ARCHIVE: "归档",
    STATE_NONE:    "未标记",
}

SAFETENSORS_EXT = (".safetensors",)
PREVIEW_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")
MAX_PREVIEW = (280, 280)
MAX_ST_HEADER = 200_000_000

CONFIG_DIR = _PATHS_LORA_CFG
DB_FILE = _PATHS_LORA_DB
SPECIAL_DIR_NAMES = {"_archive", "_pending_delete", "_recycle", ".lora_manager"}

META_LABELS = {
    "ss_output_name":        "输出名",
    "ss_network_module":     "网络类型",
    "ss_network_dim":        "网络维度",
    "ss_network_alpha":      "Alpha",
    "ss_learning_rate":      "学习率",
    "ss_text_encoder_lr":    "TE 学习率",
    "ss_unet_lr":            "UNet 学习率",
    "ss_num_train_images":   "训练图片数",
    "ss_num_reg_images":     "正则图片数",
    "ss_num_epochs":         "训练轮数",
    "ss_epoch":              "完成轮数",
    "ss_steps":              "训练步数",
    "ss_max_train_steps":    "目标步数",
    "ss_base_model_version": "底模版本",
    "ss_sd_model_name":      "SD 底模名",
    "ss_clip_skip":          "CLIP Skip",
    "ss_seed":               "种子",
    "ss_optimizer":          "优化器",
    "ss_lr_scheduler":       "调度器",
    "ss_resolution":         "训练分辨率",
}


# ================= 文件名解析 =================
def parse_lora_filename(stem):
    if not stem:
        return "(未命名)", None, None
    parts = stem.split("-")
    n = len(parts)
    last = parts[-1]
    if len(last) == 6 and last.isdigit():
        name = "-".join(parts[:-1]) if n > 1 else ""
        return (name or "(未命名)"), last, None
    if n >= 2:
        second_last = parts[-2]
        if len(second_last) == 6 and second_last.isdigit():
            tag = last
            if 1 <= len(tag) <= 4 and tag.isalnum():
                name = "-".join(parts[:-2])
                return (name or "(未命名)"), second_last, tag
    return stem, None, None


# ================= 配置管理 =================
class Config:
    def __init__(self):
        self.data = {
            "last_dir": "",
            "recent_dirs": [],
            "recursive": True,
            "archive_dir": "",
            "pending_delete_dir": "",
        }
        self.load()

    def load(self):
        try:
            p = os.path.join(CONFIG_DIR, "config.json")
            if os.path.isfile(p):
                with open(p, "r", encoding="utf-8") as f:
                    self.data.update(json.load(f))
        except Exception:
            pass

    def save(self):
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(os.path.join(CONFIG_DIR, "config.json"),
                      "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def remember_dir(self, d):
        if not d:
            return
        self.data["last_dir"] = d
        recent = self.data.get("recent_dirs", [])
        recent = [x for x in recent if x != d]
        recent.insert(0, d)
        self.data["recent_dirs"] = recent[:8]
        self.save()


# ================= 数据库 =================
class Database:
    def __init__(self):
        self.data = {
            "version": 1,
            "files": {},
            "history": [],
            "group_log_mapping": {},
            "dataset_states": {},
            "dataset_lora_mapping": {},
            "dataset_triggers": {},
        }
        self.load()

    @staticmethod
    def key(path):
        return os.path.normcase(os.path.abspath(path))

    def load(self):
        try:
            if os.path.isfile(DB_FILE):
                with open(DB_FILE, "r", encoding="utf-8") as f:
                    self.data.update(json.load(f))
        except Exception:
            pass

    def save(self):
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(DB_FILE, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def get(self, path):
        return self.data["files"].get(self.key(path),
                                      {"state": STATE_NONE, "comment": ""})

    def set(self, path, state=None, comment=None):
        k = self.key(path)
        entry = self.data["files"].get(k, {"state": STATE_NONE, "comment": ""})
        if state is not None:
            entry["state"] = state if state != STATE_NONE else None
            if entry["state"] is None:
                entry.pop("state", None)
        if comment is not None:
            entry["comment"] = comment
        entry["updated"] = datetime.datetime.now().isoformat(timespec="seconds")
        if not entry.get("state") and not entry.get("comment"):
            self.data["files"].pop(k, None)
        else:
            self.data["files"][k] = entry

    def add_history(self, op, moves):
        entry = {
            "id": uuid.uuid4().hex[:12],
            "ts": datetime.datetime.now().isoformat(timespec="seconds"),
            "op": op,
            "moves": moves,
            "undone": False,
        }
        self.data["history"].insert(0, entry)
        self.data["history"] = self.data["history"][:50]
        self.save()
        return entry

    def mark_undone(self, entry_id):
        for h in self.data["history"]:
            if h["id"] == entry_id:
                h["undone"] = True
                break
        self.save()

    def histories(self, include_undone=False):
        if include_undone:
            return self.data["history"]
        return [h for h in self.data["history"] if not h["undone"]]

    # ---- 组 ↔ 日志 关联 ----
    def get_group_log(self, group_name):
        m = self.data.get("group_log_mapping", {})
        return m.get(group_name, {}).get("log_name")

    def set_group_log(self, group_name, log_name, source="manual"):
        if "group_log_mapping" not in self.data:
            self.data["group_log_mapping"] = {}
        self.data["group_log_mapping"][group_name] = {
            "log_name": log_name,
            "source": source,
            "updated": datetime.datetime.now().isoformat(timespec="seconds"),
        }
        self.save()

    def del_group_log(self, group_name):
        m = self.data.get("group_log_mapping", {})
        if group_name in m:
            del m[group_name]
            self.save()


    # ---- 数据集相关 ----
    def get_dataset_state(self, path):
        k = self.key(path)
        return self.data.get("dataset_states", {}).get(
            k, {"state": None, "comment": ""})

    def set_dataset_state(self, path, state=None, comment=None):
        k = self.key(path)
        m = self.data.setdefault("dataset_states", {})
        entry = m.get(k, {"state": None, "comment": ""})
        if state is not None:
            entry["state"] = state if state else None
        if comment is not None:
            entry["comment"] = comment
        if not entry.get("state") and not entry.get("comment"):
            m.pop(k, None)
        else:
            m[k] = entry
        self.save()

    def get_dataset_lora(self, dataset_name):
        m = self.data.get("dataset_lora_mapping", {})
        return m.get(dataset_name, {}).get("lora_group")

    def set_dataset_lora(self, dataset_name, lora_group, source="manual"):
        m = self.data.setdefault("dataset_lora_mapping", {})
        if lora_group:
            m[dataset_name] = {
                "lora_group": lora_group,
                "source": source,
            }
        else:
            m.pop(dataset_name, None)
        self.save()

    def del_dataset_lora(self, dataset_name):
        m = self.data.get("dataset_lora_mapping", {})
        if dataset_name in m:
            del m[dataset_name]
            self.save()

    def get_dataset_trigger(self, dataset_name):
        m = self.data.get("dataset_triggers", {})
        return m.get(dataset_name, "")

    def set_dataset_trigger(self, dataset_name, trigger):
        m = self.data.setdefault("dataset_triggers", {})
        if trigger:
            m[dataset_name] = trigger
        else:
            m.pop(dataset_name, None)
        self.save()

    def del_dataset_trigger(self, dataset_name):
        m = self.data.get("dataset_triggers", {})
        if dataset_name in m:
            del m[dataset_name]
            self.save()

# ================= safetensors 元数据 =================
def read_st_metadata(path):
    try:
        with open(path, "rb") as f:
            n_bytes = f.read(8)
            if len(n_bytes) != 8:
                return {}
            n = int.from_bytes(n_bytes, "little")
            if n <= 0 or n > MAX_ST_HEADER:
                return {}
            data = f.read(n)
            if len(data) != n:
                return {}
        header = json.loads(data.decode("utf-8"))
        return header.get("__metadata__", {}) or {}
    except Exception:
        return {}


def extract_triggers(meta, top_n=30):
    raw = meta.get("ss_tag_frequency", "")
    if not raw:
        return []
    try:
        tf = json.loads(raw)
    except Exception:
        return []
    counts = Counter()
    for tags in tf.values():
        if isinstance(tags, dict):
            for tag, cnt in tags.items():
                try:
                    counts[tag] += int(cnt)
                except Exception:
                    counts[tag] += 1
    return [t for t, _ in counts.most_common(top_n)]


def find_previews(lora_path):
    """返回所有预览图路径（按序号排序），没有就返回 []"""
    base, _ = os.path.splitext(lora_path)
    found = []

    # 1) 单张格式：XXX.png
    for ext in PREVIEW_EXTS:
        for suffix in ("", ".preview", ".Preview", ".PREVIEW"):
            c = base + suffix + ext
            if os.path.isfile(c):
                found.append(c)
                break

    # 2) 多张格式：XXX_01.png, XXX_02.png, ...
    import re
    for f in os.listdir(os.path.dirname(lora_path) or "."):
        m = re.match(
            r'^' + re.escape(os.path.basename(base)) + r'_(\d+)\.(\w+)$',
            f, re.IGNORECASE)
        if m:
            ext = "." + m.group(2).lower()
            if ext in PREVIEW_EXTS:
                found.append(os.path.join(
                    os.path.dirname(lora_path), f))

    # 排序：单图排前，多图按序号
    def _sort_key(p):
        name = os.path.basename(p)
        m = re.search(r'_(\d+)\.\w+$', name)
        return (1, int(m.group(1))) if m else (0, 0)

    found.sort(key=_sort_key)
    return found


def find_previews(lora_path):
    """返回所有预览图路径（按序号排序），没有就返回 []"""
    base, _ = os.path.splitext(lora_path)
    folder = os.path.dirname(lora_path) or "."
    found = []

    # 1) 单张格式：XXX.png
    for ext in PREVIEW_EXTS:
        for suffix in ("", ".preview", ".Preview", ".PREVIEW"):
            c = base + suffix + ext
            if os.path.isfile(c):
                found.append(c)
                break

    # 2) 多张格式：XXX_01.png, XXX_02.png, ...
    try:
        for f in os.listdir(folder):
            m = re.match(
                r'^' + re.escape(os.path.basename(base)) + r'_(\d+)\.(\w+)$',
                f, re.IGNORECASE)
            if m:
                ext = "." + m.group(2).lower()
                if ext in PREVIEW_EXTS:
                    found.append(os.path.join(folder, f))
    except Exception:
        pass

    def _sort_key(p):
        name = os.path.basename(p)
        m = re.search(r'_(\d+)\.\w+$', name)
        return (1, int(m.group(1))) if m else (0, 0)

    found.sort(key=_sort_key)
    return found


def find_preview(lora_path):
    """兼容旧接口：返回第一张"""
    lst = find_previews(lora_path)
    return lst[0] if lst else None


def human_size(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{int(n)} B" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


# ================= 数据模型 =================
class LoRAItem:
    __slots__ = ("path", "stem", "group", "batch", "tag",
                 "size", "mtime", "preview", "previews",
                 "meta", "triggers",
                 "state", "comment")

    def __init__(self, path, db):
        self.path = path
        self.stem = os.path.splitext(os.path.basename(path))[0]
        self.group, self.batch, self.tag = parse_lora_filename(self.stem)
        try:
            st = os.stat(path)
            self.size = st.st_size
            self.mtime = st.st_mtime
        except Exception:
            self.size = 0
            self.mtime = 0
        self.preview = None
        self.previews = []
        self.meta = None
        self.triggers = None
        entry = db.get(path)
        self.state = entry.get("state", STATE_NONE)
        self.comment = entry.get("comment", "")

    def ensure_meta(self):
        if self.meta is None:
            self.meta = read_st_metadata(self.path)
            self.triggers = extract_triggers(self.meta)

    def ensure_preview(self):
        if self.preview is None:
            lst = find_previews(self.path)
            self.preview = lst[0] if lst else None
            self.previews = lst


# ================= 扫描器 =================
class LoraScanner:
    def __init__(self, root_dir, recursive, db,
                 on_progress=None, on_done=None,
                 exclude_dirs=None):
        self.root_dir = root_dir
        self.recursive = recursive
        self.db = db
        self.on_progress = on_progress
        self.on_done = on_done
        self.stop_event = threading.Event()
        self.exclude_dirs = []
        for p in (exclude_dirs or []):
            if not p:
                continue
            try:
                self.exclude_dirs.append(
                    os.path.normcase(os.path.abspath(p)))
            except Exception:
                pass

    def _is_excluded(self, dirpath):
        try:
            ap = os.path.normcase(os.path.abspath(dirpath))
        except Exception:
            return False
        for t in self.exclude_dirs:
            if ap == t or ap.startswith(t + os.sep):
                return True
        return False

    def stop(self):
        self.stop_event.set()

    def run(self):
        paths = []
        try:
            if self.recursive:
                for root, dirs, files in os.walk(self.root_dir):
                    if self.stop_event.is_set():
                        break
                    dirs[:] = [d for d in dirs
                               if d not in SPECIAL_DIR_NAMES
                               and not self._is_excluded(
                                   os.path.join(root, d))]
                    for f in files:
                        if f.lower().endswith(SAFETENSORS_EXT):
                            paths.append(os.path.join(root, f))
            else:
                for f in os.listdir(self.root_dir):
                    p = os.path.join(self.root_dir, f)
                    if os.path.isfile(p) and f.lower().endswith(SAFETENSORS_EXT):
                        paths.append(p)
        except Exception as e:
            if self.on_done:
                self.on_done([], str(e))
            return

        total = len(paths)
        if self.on_progress:
            self.on_progress(0, total, "读取元数据...")

        items = [LoRAItem(p, self.db) for p in paths]
        done = 0
        with ThreadPoolExecutor(max_workers=8) as ex:
            futs = {ex.submit(self._read_one, it): it for it in items}
            for fut in as_completed(futs):
                if self.stop_event.is_set():
                    break
                done += 1
                if self.on_progress and done % 10 == 0:
                    self.on_progress(done, total, f"读取 {done}/{total}")

        if self.on_done:
            self.on_done(items, None)

    def run_sync(self):
        """同步执行扫描，返回 (items, err)，供多区域扫描用"""
        paths = []
        try:
            if self.recursive:
                for root, dirs, files in os.walk(self.root_dir):
                    if self.stop_event.is_set():
                        break
                    dirs[:] = [d for d in dirs
                               if d not in SPECIAL_DIR_NAMES
                               and not self._is_excluded(
                                   os.path.join(root, d))]
                    for f in files:
                        if f.lower().endswith(SAFETENSORS_EXT):
                            paths.append(os.path.join(root, f))
            else:
                for f in os.listdir(self.root_dir):
                    p = os.path.join(self.root_dir, f)
                    if os.path.isfile(p) and f.lower().endswith(SAFETENSORS_EXT):
                        paths.append(p)
        except Exception as e:
            return [], str(e)

        total = len(paths)
        if self.on_progress:
            self.on_progress(0, total, f"读取元数据...")

        items = [LoRAItem(p, self.db) for p in paths]
        done = 0
        with ThreadPoolExecutor(max_workers=8) as ex:
            futs = {ex.submit(self._read_one, it): it for it in items}
            for fut in as_completed(futs):
                if self.stop_event.is_set():
                    break
                done += 1
                if self.on_progress and done % 10 == 0:
                    self.on_progress(done, total, f"读取 {done}/{total}")

        return items, None
    
    @staticmethod
    def _read_one(item):
        try:
            item.ensure_meta()
            item.ensure_preview()
        except Exception:
            pass
        return item


# ================= 移动工具 =================
def move_file(src, dst_dir, root_dir=None):
    try:
        if root_dir:
            try:
                rel = os.path.relpath(src, root_dir)
            except Exception:
                rel = os.path.basename(src)
        else:
            rel = os.path.basename(src)
        dst = os.path.join(dst_dir, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.exists(dst):
            base, ext = os.path.splitext(dst)
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            dst = f"{base}_{ts}{ext}"

        # 找所有预览图
        previews_src = find_previews(src)

        # 移动主文件
        shutil.move(src, dst)

        # 移动所有预览图
        if previews_src:
            src_stem = os.path.splitext(os.path.basename(src))[0]
            dst_stem = os.path.splitext(os.path.basename(dst))[0]
            dst_dir_actual = os.path.dirname(dst)

            for preview_src in previews_src:
                try:
                    prev_name = os.path.basename(preview_src)
                    extra = prev_name[len(src_stem):]

                    preview_dst = os.path.join(
                        dst_dir_actual, dst_stem + extra)

                    if os.path.exists(preview_dst):
                        pb, pe = os.path.splitext(preview_dst)
                        ts = datetime.datetime.now().strftime(
                            "%Y%m%d_%H%M%S")
                        preview_dst = f"{pb}_{ts}{pe}"

                    shutil.move(preview_src, preview_dst)
                except Exception:
                    pass

        return True, dst
    except Exception as e:
        return False, str(e)


def try_send_to_trash(paths):
    """
    尝试把文件移入系统回收站。
    返回 (成功数, [(失败路径, 失败原因), ...])
    """
    if not paths:
        return 0, []

    # 非 Windows 系统：用 send2trash 原逻辑
    if os.name != 'nt':
        if not HAS_TRASH:
            return 0, [(p, "未安装 send2trash") for p in paths]
        ok = 0
        errs = []
        for p in paths:
            try:
                send2trash(p)
                ok += 1
            except Exception as e:
                errs.append((p, str(e)))
        return ok, errs

    # Windows 系统：调 PowerShell + VisualBasic API（更稳）
    ok = 0
    errs = []
    for p in paths:
        try:
            p_norm = os.path.normpath(os.path.abspath(p))
            # 单引号包裹，内部单引号转义
            p_quoted = "'" + p_norm.replace("'", "''") + "'"
            ps_cmd = (
                "Add-Type -AssemblyName Microsoft.VisualBasic; "
                "[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile("
                + p_quoted + ", 'OnlyErrorDialogs', 'SendToRecycleBin')"
            )
            result = subprocess.run(
                ['powershell', '-NoProfile', '-NonInteractive',
                 '-WindowStyle', 'Hidden',
                 '-Command', ps_cmd],
                capture_output=True, text=True, timeout=30,
                encoding='utf-8', errors='replace',
                creationflags=0x08000000
            )
            if result.returncode == 0:
                ok += 1
            else:
                err = (result.stderr or result.stdout or '未知错误').strip()
                errs.append((p, err))
        except subprocess.TimeoutExpired:
            errs.append((p, '操作超时'))
        except Exception as e:
            errs.append((p, str(e)))
    return ok, errs


# ================= 样式 =================
def setup_styles():
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except Exception:
        pass

    FONT = ('Microsoft YaHei UI', 10)
    FONT_BOLD = ('Microsoft YaHei UI', 10, 'bold')
    FONT_SMALL = ('Microsoft YaHei UI', 9)

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
    style.configure('Primary.TButton', font=FONT_BOLD, padding=(16, 7),
                    background=COLOR["primary"], foreground='white',
                    borderwidth=0, focusthickness=0)
    style.map('Primary.TButton',
              background=[('active', COLOR["primary_h"]),
                          ('disabled', '#9ca3af')],
              foreground=[('disabled', '#f3f4f6')])
    style.configure('Danger.TButton', font=FONT_BOLD, padding=(16, 7),
                    background=COLOR["danger"], foreground='white',
                    borderwidth=0)
    style.map('Danger.TButton',
              background=[('active', '#dc2626'),
                          ('disabled', '#9ca3af')])
    style.configure('TEntry', padding=5, fieldbackground='white')
    style.configure('TCombobox', padding=5)
    style.configure('Treeview', rowheight=28, font=FONT,
                    fieldbackground='white', background='white', borderwidth=0)
    style.configure('Treeview.Heading', font=FONT_BOLD,
                    background='#eef2ff', foreground=COLOR["text"],
                    relief='flat', padding=(6, 6))
    style.map('Treeview',
              background=[('selected', COLOR["primary"])],
              foreground=[('selected', 'white')])
    style.configure('TProgressbar', troughcolor='#e5e7eb',
                    background=COLOR["primary"], borderwidth=0, thickness=8)
    style.configure('Small.TLabel', font=FONT_SMALL,
                    background=COLOR["bg"], foreground=COLOR["muted"])


# ================= 主 Tab =================
class LoRAManagerTab:
    def __init__(self, parent, root):
        self.parent = parent
        self.root = root

        self.cfg = Config()
        self.db = Database()

        self.queue = queue.Queue()
        self.scanner = None
        self.items = []
        self.iid_to_item = {}
        self.iid_to_group = {}
        self.thumb_cache = {}
        self.preview_ref = None
        self._previews_list = []
        self._preview_index = 0
        self._nav_var = None
        self._preview_resize_id = None

        # ---- Loss 相关 ----
        self._log_index = None       # 日志索引（懒加载）
        self._current_group = None   # 当前选中组（用于 Loss 展示）
        self._loss_figure = None
        self._loss_canvas = None
        self._loss_info_var = None
        self._hover_value_var = None
        self._hover_series_var = None
        self._last_hover_x = None
        self._curve_cache = {}
        self._hover_data = {}
        self._loss_load_token = 0

        self.root_dir = tk.StringVar(master=parent,
                                     value=self.cfg.data.get("last_dir", ""))
        self.recent_dirs = list(self.cfg.data.get("recent_dirs", []))
        self.recursive = tk.BooleanVar(master=parent,
                                       value=self.cfg.data.get("recursive", True))
        self.search_var = tk.StringVar(master=parent)
        self.status_var = tk.StringVar(master=parent,
                                       value="就绪 · 请选择目录后点击扫描")

        self.mark_state = tk.StringVar(master=parent, value="none")
        self.mark_comment = tk.StringVar(master=parent)
        self.view_mode = tk.StringVar(master=parent, value="work")
        self._last_view = "work"
        self._view_items = {"work": [], "archive": [], "pending": []}
        self._view_root = {"work": "", "archive": "", "pending": ""}
        self._auto_match_running = False
        self._match_fingerprints = {}
        self._preheat_running = False
        self._scan_stop_event = threading.Event()
        self._scan_targets = {}
        self._queue_running = True

        self._build_ui()
        self.search_var.trace_add("write", lambda *a: self.refresh_tree())
        self.root.after(80, self._check_queue)

    # ---------- 布局 ----------
    def _build_ui(self):
        # 状态栏（最底）
        status_bar = tk.Label(self.parent, textvariable=self.status_var,
                              anchor=tk.W, bg='#eef2f7', fg=COLOR["muted"],
                              padx=14, pady=5,
                              font=('Microsoft YaHei UI', 9))
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        # 批量操作栏（紧凑）
        batch_bar = ttk.Frame(self.parent)
        batch_bar.pack(side=tk.BOTTOM, fill=tk.X, padx=12, pady=(2, 4))
        self._build_batch_bar(batch_bar)

        # 顶部控制区（两行，无 LabelFrame）
        top = ttk.Frame(self.parent)
        top.pack(side=tk.TOP, fill=tk.X, padx=12, pady=(10, 4))
        self._build_top_compact(top)

        # 主体
        body = ttk.Frame(self.parent)
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True,
                  padx=12, pady=(0, 4))
        body.columnconfigure(0, weight=3, minsize=560)
        body.columnconfigure(1, weight=2, minsize=380)
        body.rowconfigure(0, weight=1)

        left = ttk.Frame(body)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self._build_left_column(left)

        right = ttk.Frame(body)
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        self._build_right_column(right)

    def _build_top_compact(self, top):
        # ---- 第一行：操作按钮 + 根目录 ----
        row1 = ttk.Frame(top)
        row1.pack(fill=tk.X, pady=(0, 3))

        self.scan_btn = ttk.Button(row1, text="🔍 扫描",
                                   style='Primary.TButton',
                                   command=self.start_scan)
        self.scan_btn.pack(side=tk.LEFT)
        self.stop_btn = ttk.Button(row1, text="■ 停止", state=tk.DISABLED,
                                   command=self.stop_scan)
        self.stop_btn.pack(side=tk.LEFT, padx=(4, 8))

        ttk.Button(row1, text="⚙ 设置",
                   command=self.open_settings).pack(side=tk.LEFT)
        ttk.Button(row1, text="📤 导出",
                   command=self.export_csv).pack(side=tk.LEFT, padx=3)
        ttk.Button(row1, text="↻ 刷新",
                   command=self.reload_meta).pack(side=tk.LEFT)

        ttk.Label(row1, text="根目录:", width=6).pack(side=tk.LEFT, padx=(16, 2))
        self.root_entry = ttk.Entry(row1, textvariable=self.root_dir)
        self.root_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        ttk.Button(row1, text="浏览", width=6, command=self._pick_dir
                   ).pack(side=tk.LEFT)

        self.recent_var = tk.StringVar(master=row1, value="最近")
        self.recent_cb = ttk.Combobox(row1, textvariable=self.recent_var,
                                      values=["最近"] + self.recent_dirs,
                                      width=8, state="readonly")
        self.recent_cb.pack(side=tk.LEFT, padx=(4, 0))
        self.recent_cb.bind("<<ComboboxSelected>>", self._pick_recent)

        self.recursive_cb = ttk.Checkbutton(row1, text="递归",
                                            variable=self.recursive)
        self.recursive_cb.pack(side=tk.LEFT, padx=(4, 0))

        # ---- 第二行：视图切换 + 进度条 ----
        row2 = ttk.Frame(top)
        row2.pack(fill=tk.X, pady=(3, 0))

        ttk.Label(row2, text="视图:").pack(side=tk.LEFT)
        ttk.Radiobutton(row2, text="📁 工作区", value="work",
                        variable=self.view_mode,
                        command=self._on_view_change
                        ).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Radiobutton(row2, text="📦 归档区", value="archive",
                        variable=self.view_mode,
                        command=self._on_view_change
                        ).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Radiobutton(row2, text="🗑 待删区", value="pending",
                        variable=self.view_mode,
                        command=self._on_view_change
                        ).pack(side=tk.LEFT, padx=(6, 0))

        self.progress = ttk.Progressbar(row2, orient=tk.HORIZONTAL,
                                        mode='determinate')
        self.progress.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(16, 0))

    def _build_left_column(self, left):
        search_row = ttk.Frame(left)
        search_row.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(search_row, text="🔎 搜索:").pack(side=tk.LEFT)
        ttk.Entry(search_row, textvariable=self.search_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0))
        ttk.Label(search_row, text="排序:").pack(side=tk.LEFT, padx=(8, 2))

        self.sort_var = tk.StringVar(master=search_row, value="名称")
        sort_cb = ttk.Combobox(search_row, textvariable=self.sort_var,
                               values=["名称", "时间 ↓", "大小 ↓"],
                               width=8, state="readonly")
        sort_cb.pack(side=tk.LEFT)
        sort_cb.bind("<<ComboboxSelected>>", lambda e: self.refresh_tree())

        tree_box = ttk.LabelFrame(left, text=" LoRA 列表 ", padding=4)
        tree_box.pack(fill=tk.BOTH, expand=True)

        cols = ("state", "batch", "size", "mtime", "comment")
        self.tree = ttk.Treeview(tree_box, columns=cols,
                                 show="tree headings",
                                 selectmode="extended")
        self.tree.heading("#0", text="名称 / 分组")
        self.tree.heading("state", text="状态")
        self.tree.heading("batch", text="批次")
        self.tree.heading("size", text="大小")
        self.tree.heading("mtime", text="修改时间")
        self.tree.heading("comment", text="注释")

        self.tree.column("#0", width=300, anchor=tk.W)
        self.tree.column("state", width=60, anchor=tk.CENTER)
        self.tree.column("batch", width=70, anchor=tk.CENTER)
        self.tree.column("size", width=80, anchor=tk.E)
        self.tree.column("mtime", width=120, anchor=tk.CENTER)
        self.tree.column("comment", width=140, anchor=tk.W)

        vsb = ttk.Scrollbar(tree_box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.tag_configure("latest", foreground="#d97706")
        self.tree.tag_configure("final", foreground="#059669")

        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<Button-3>", self._on_rclick)
        self._build_tree_menu()

    def _build_right_column(self, right):
        self.right_nb = ttk.Notebook(right)
        self.right_nb.pack(fill=tk.BOTH, expand=True)

        tab_detail = ttk.Frame(self.right_nb)
        tab_log = ttk.Frame(self.right_nb)
        tab_param = ttk.Frame(self.right_nb)
        tab_batch = ttk.Frame(self.right_nb)
        tab_loss = ttk.Frame(self.right_nb)

        self.right_nb.add(tab_detail, text="  详情  ")
        self.right_nb.add(tab_log, text="  日志  ")
        self.right_nb.add(tab_param, text="  📋 参数  ")
        self.right_nb.add(tab_batch, text="  📊 批次  ")
        self.right_nb.add(tab_loss, text="  📈 Loss  ")

        self._build_detail(tab_detail)
        self._build_log(tab_log)
        self._build_param_tab(tab_param)
        self._build_batch_tab(tab_batch)
        self._build_loss_tab(tab_loss)

        self.right_nb.bind("<<NotebookTabChanged>>",
                           self._on_right_tab_changed)

    def _build_batch_bar(self, bar):
        ttk.Label(bar, text="批量:").pack(side=tk.LEFT)
        ttk.Button(bar, text="⭐ 保留", width=8,
                   command=lambda: self.batch_mark(STATE_KEEP)
                   ).pack(side=tk.LEFT, padx=1)
        ttk.Button(bar, text="🗑 待清理", width=8,
                   command=lambda: self.batch_mark(STATE_CLEAN)
                   ).pack(side=tk.LEFT, padx=1)
        ttk.Button(bar, text="📦 归档", width=7,
                   command=lambda: self.batch_mark(STATE_ARCHIVE)
                   ).pack(side=tk.LEFT, padx=1)
        ttk.Button(bar, text="· 清除", width=7,
                   command=lambda: self.batch_mark(STATE_NONE)
                   ).pack(side=tk.LEFT, padx=1)

        ttk.Separator(bar, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=8)

        ttk.Button(bar, text="🧹 执行清理",
                   command=self.execute_clean).pack(side=tk.LEFT, padx=1)
        ttk.Button(bar, text="📦 执行归档",
                   command=self.execute_archive).pack(side=tk.LEFT, padx=1)
        ttk.Button(bar, text="↩ 撤销",
                   command=self.open_history).pack(side=tk.LEFT, padx=1)

        ttk.Button(bar, text="🗑 清空待删目录",
                   style='Danger.TButton',
                   command=self.empty_pending).pack(side=tk.RIGHT)

    # ========== 详情 Tab ==========
    def _build_detail(self, parent):
        row_btn = ttk.Frame(parent)
        row_btn.pack(side=tk.BOTTOM, fill=tk.X, pady=(6, 0))
        ttk.Button(row_btn, text="打开", command=self.open_file
                   ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))
        ttk.Button(row_btn, text="定位", command=self.reveal_file
                   ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        ttk.Button(row_btn, text="复制路径", command=self.copy_path
                   ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 0))
        ttk.Button(row_btn, text="➕ 预览图", command=self.add_preview
                   ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 0))
        ttk.Button(row_btn, text="📁 全部", command=self.show_all_previews
                   ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 0))

        mark_box = ttk.LabelFrame(parent, text=" 标记 ", padding=8)
        mark_box.pack(side=tk.BOTTOM, fill=tk.X, pady=(6, 0))

        row = ttk.Frame(mark_box)
        row.pack(fill=tk.X)
        for val, label in [("none", "· 无"), ("keep", "⭐ 保留"),
                           ("clean", "🗑 待清理"), ("archive", "📦 归档")]:
            ttk.Radiobutton(row, text=label, variable=self.mark_state,
                            value=val).pack(side=tk.LEFT, padx=(0, 6))

        row = ttk.Frame(mark_box)
        row.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(row, text="注释:").pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=self.mark_comment).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 4))
        ttk.Button(row, text="应用",
                   command=self.apply_marks).pack(side=tk.LEFT)

        self.preview_frame = tk.Frame(parent, bg="#1e1e2e")
        self.preview_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # 底部导航条
        nav = tk.Frame(self.preview_frame, bg="#1e1e2e")
        nav.pack(side=tk.BOTTOM, fill=tk.X)
        self._nav_var = tk.StringVar(value="")

        ttk.Button(nav, text="◀", width=3, command=self._prev_preview
                   ).pack(side=tk.LEFT, padx=(4, 2), pady=3)
        tk.Label(nav, textvariable=self._nav_var,
                 bg="#1e1e2e", fg="#9ca3af",
                 font=('Microsoft YaHei UI', 9)
                 ).pack(side=tk.LEFT, expand=True)
        ttk.Button(nav, text="▶", width=3, command=self._next_preview
                   ).pack(side=tk.RIGHT, padx=(2, 4), pady=3)

        self.preview_label = tk.Label(self.preview_frame,
                                      text="未选中",
                                      bg="#1e1e2e", fg="#6b7280",
                                      font=('Microsoft YaHei UI', 11),
                                      cursor="hand2")
        self.preview_label.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.preview_label.bind("<Configure>", self._on_preview_resize)
        self.preview_label.bind("<Button-1>", lambda e: self.open_preview())

    def _build_param_tab(self, parent):
        box = ttk.Frame(parent)
        box.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        cols = ("key", "value")
        self.param_tree = ttk.Treeview(box, columns=cols, show="headings")
        self.param_tree.heading("key", text="字段")
        self.param_tree.heading("value", text="值")
        self.param_tree.column("key", width=110, anchor=tk.W)
        self.param_tree.column("value", width=250, anchor=tk.W)
        self.param_tree.tag_configure("odd", background="#fafbfc")

        vsb = ttk.Scrollbar(box, orient="vertical",
                            command=self.param_tree.yview)
        self.param_tree.configure(yscrollcommand=vsb.set)
        self.param_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

    def _build_batch_tab(self, parent):
        box = ttk.Frame(parent)
        box.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        cols = ("batch", "epoch", "steps", "size", "mtime")
        self.batch_tree = ttk.Treeview(box, columns=cols, show="headings",
                                       selectmode="browse")
        self.batch_tree.heading("batch", text="批次")
        self.batch_tree.heading("epoch", text="轮数")
        self.batch_tree.heading("steps", text="步数")
        self.batch_tree.heading("size", text="大小")
        self.batch_tree.heading("mtime", text="修改时间")
        self.batch_tree.column("batch", width=70, anchor=tk.CENTER)
        self.batch_tree.column("epoch", width=60, anchor=tk.CENTER)
        self.batch_tree.column("steps", width=60, anchor=tk.CENTER)
        self.batch_tree.column("size", width=75, anchor=tk.E)
        self.batch_tree.column("mtime", width=125, anchor=tk.CENTER)
        self.batch_tree.tag_configure("odd", background="#fafbfc")
        self.batch_tree.tag_configure("latest", foreground="#d97706")
        self.batch_tree.tag_configure("final", foreground="#059669")

        vsb = ttk.Scrollbar(box, orient="vertical",
                            command=self.batch_tree.yview)
        self.batch_tree.configure(yscrollcommand=vsb.set)
        self.batch_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

    def _build_loss_tab(self, parent):
        if not HAS_MPL:
            tk.Label(parent,
                     text="⚠ 需要 matplotlib\n\n"
                          "pip install matplotlib",
                     bg=COLOR["bg"], fg=COLOR["danger"],
                     font=('Microsoft YaHei UI', 11),
                     justify='center').pack(expand=True, fill=tk.BOTH)
            return
        if not HAS_LOG_PARSER:
            tk.Label(parent,
                     text="⚠ 未找到 log_parser.py\n\n"
                          "请把 log_parser.py 放在同目录",
                     bg=COLOR["bg"], fg=COLOR["danger"],
                     font=('Microsoft YaHei UI', 11),
                     justify='center').pack(expand=True, fill=tk.BOTH)
            return

        # 底部按钮
        btn_row = ttk.Frame(parent)
        btn_row.pack(side=tk.BOTTOM, fill=tk.X, pady=(4, 0))
        ttk.Button(btn_row, text="🔍 自动匹配",
                   command=self._auto_match_log).pack(side=tk.LEFT)
        ttk.Button(btn_row, text="📂 手动指定",
                   command=self._manual_pick_log).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(btn_row, text="✕ 解除关联",
                   command=self._unlink_log).pack(side=tk.LEFT, padx=(6, 0))        
        ttk.Button(btn_row, text="⚙ 日志目录",
                   command=self._pick_log_root).pack(side=tk.RIGHT)

        self._loss_cache_info_var = tk.StringVar(master=parent, value="")
        ttk.Label(btn_row, textvariable=self._loss_cache_info_var,
                  foreground=COLOR["muted"],
                  font=('Microsoft YaHei UI', 8)
                  ).pack(side=tk.RIGHT, padx=(0, 6))
        ttk.Button(btn_row, text="🧹 清曲线缓存",
                   command=self._clear_loss_cache
                   ).pack(side=tk.RIGHT, padx=(0, 4))

        self.root.after(500, self._refresh_loss_cache_info)

        # 顶部信息
        self._loss_info_var = tk.StringVar(master=parent, value="")
        tk.Label(parent, textvariable=self._loss_info_var, anchor=tk.W,
                 bg=COLOR["card"], fg=COLOR["muted"],
                 font=('Microsoft YaHei UI', 9), padx=6, pady=4
                 ).pack(side=tk.TOP, fill=tk.X)

        # ★ 固定数值条（图表下方，鼠标悬停时更新）
        self._hover_value_var = tk.StringVar(
            master=parent, value="🖱  将鼠标移到曲线上可查看数值")
        self._hover_series_var = tk.StringVar(master=parent, value="全部")

        hover_bar = tk.Frame(parent, bg="#fef3c7",
                             highlightbackground="#f59e0b",
                             highlightthickness=1)
        hover_bar.pack(side=tk.BOTTOM, fill=tk.X, padx=4, pady=(0, 2))

        # 右侧：下拉切换
        cb = ttk.Combobox(hover_bar,
                          textvariable=self._hover_series_var,
                          values=["全部", "loss/current",
                                  "loss/average", "loss/epoch"],
                          width=14, state="readonly")
        cb.pack(side=tk.RIGHT, padx=(4, 6), pady=2)
        cb.bind("<<ComboboxSelected>>",
                lambda e: self._on_hover_refresh())

        ttk.Label(hover_bar, text="显示:",
                  background="#fef3c7",
                  foreground="#92400e").pack(side=tk.RIGHT,
                                            padx=(4, 2), pady=2)

        # 左侧：数值显示（占满剩余空间）
        tk.Label(hover_bar, textvariable=self._hover_value_var,
                 anchor=tk.W, bg="#fef3c7", fg="#92400e",
                 font=('Consolas', 10, 'bold'),
                 padx=8, pady=4).pack(side=tk.LEFT,
                                      fill=tk.X, expand=True)

        # 画布（先建好，稍后 pack）
        self._loss_figure = Figure(figsize=(4, 3), dpi=100,
                                   facecolor=COLOR["card"])
        self._loss_canvas = FigureCanvasTkAgg(self._loss_figure, master=parent)

        # ★ 工具栏容器（先 pack 到 BOTTOM）
        tb_frame = ttk.Frame(parent)
        tb_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=4, pady=(2, 4))

        self._loss_toolbar = None
        try:
            from matplotlib.backends.backend_tkagg import NavigationToolbar2Tk

            # 隐藏的容器：只为了让 toolbar 对象能正常初始化
            hidden = ttk.Frame(tb_frame)

            try:
                self._loss_toolbar = NavigationToolbar2Tk(
                    self._loss_canvas, hidden, pack_toolbar=False)
                self._loss_toolbar.update()
            except TypeError:
                self._loss_toolbar = NavigationToolbar2Tk(
                    self._loss_canvas, hidden)

            # 隐藏原始 toolbar（不 pack hidden）
            hidden.pack_forget()

            # 自建中文按钮行
            visible = ttk.Frame(tb_frame)
            visible.pack(fill=tk.X)

            tb = self._loss_toolbar

            def _mk_btn(icon, label, cmd, width=8):
                b = ttk.Button(visible, text=f"{icon} {label}",
                               command=cmd, width=width)
                b.pack(side=tk.LEFT, padx=1)
                return b

            _mk_btn("🏠", "重置", tb.home, 7)
            _mk_btn("◀", "后退", tb.back, 7)
            _mk_btn("▶", "前进", tb.forward, 7)
            _mk_btn("✥", "平移", tb.pan, 7)
            _mk_btn("🔍", "放大", tb.zoom, 7)
            _mk_btn("💾", "保存", tb.save_figure, 7)

            # 提示文字
            ttk.Label(visible,
                      text="  (「放大」→ 拖框选中区域；「重置」→ 返回全景)",
                      foreground=COLOR["muted"],
                      font=('Microsoft YaHei UI', 8)).pack(side=tk.LEFT, padx=(8, 0))

        except Exception as e:
            print(f"[Loss 工具栏] 创建失败：{e}")
            self._loss_toolbar = None
            tk.Label(tb_frame, text="(工具栏不可用)",
                     fg=COLOR["muted"]).pack(side=tk.LEFT)

        # ★ canvas 最后 pack，占满中间剩余空间
        self._loss_canvas.get_tk_widget().pack(
            side=tk.TOP, fill=tk.BOTH, expand=True, padx=4, pady=(4, 0))

        # 悬停事件
        self._loss_canvas.mpl_connect('motion_notify_event', self._on_hover)

        self._draw_empty_axes("未选中组")

    def _build_log(self, parent):
        self.log_text = tk.Text(parent, wrap=tk.WORD,
                                font=('Consolas', 9),
                                bg=COLOR["log_bg"], fg=COLOR["log_fg"],
                                relief=tk.FLAT, bd=0, padx=8, pady=6)
        vsb = ttk.Scrollbar(parent, orient="vertical",
                            command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=vsb.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.tag_config("ok", foreground="#34d399")
        self.log_text.tag_config("err", foreground="#f87171")
        self.log_text.tag_config("info", foreground="#60a5fa")
        self.log_text.tag_config("warn", foreground="#fbbf24")

    def _build_tree_menu(self):
        self.tree_menu = tk.Menu(self.parent, tearoff=0)
        self.tree_menu.add_command(label="⭐ 标记为保留",
                                   command=lambda: self.batch_mark(STATE_KEEP))
        self.tree_menu.add_command(label="🗑 标记为待清理",
                                   command=lambda: self.batch_mark(STATE_CLEAN))
        self.tree_menu.add_command(label="📦 标记为归档",
                                   command=lambda: self.batch_mark(STATE_ARCHIVE))
        self.tree_menu.add_command(label="· 清除标记",
                                   command=lambda: self.batch_mark(STATE_NONE))
        self.tree_menu.add_separator()
        self.tree_menu.add_command(label="打开文件", command=self.open_file)
        self.tree_menu.add_command(label="打开所在文件夹", command=self.reveal_file)
        self.tree_menu.add_command(label="复制完整路径", command=self.copy_path)

    def log(self, msg, tag=None):
        self.log_text.insert(tk.END, msg + "\n", tag or "")
        self.log_text.see(tk.END)

    # ---------- 目录 ----------
    def _pick_dir(self):
        init = self.root_dir.get() or None
        d = filedialog.askdirectory(initialdir=init,
                                    title="选择 LoRA 根目录")
        if d:
            self.root_dir.set(d)
            self.cfg.remember_dir(d)
            self.recent_dirs = list(self.cfg.data.get("recent_dirs", []))
            self.recent_cb["values"] = ["最近"] + self.recent_dirs
            self.recent_var.set("最近")

    def _on_view_change(self):
        new_mode = self.view_mode.get()
        old_mode = self._last_view
        if new_mode == old_mode:
            return

        # 保存旧视图的数据
        self._view_items[old_mode] = list(self.items)
        self._view_root[old_mode] = self.root_dir.get()

        # 加载新视图的缓存数据
        self.items = list(self._view_items.get(new_mode, []))
        cached_root = self._view_root.get(new_mode, "")
        if cached_root:
            self.root_dir.set(cached_root)

        self._last_view = new_mode

        # UI 状态切换
        if new_mode == "work":
            self.root_entry.config(state=tk.NORMAL)
            self.recursive_cb.state(["!disabled"])
            self.recent_cb.config(state="readonly")
            name = "工作区"
        else:
            self.root_entry.config(state=tk.DISABLED)
            self.recursive_cb.state(["disabled"])
            self.recent_cb.config(state="disabled")
            name = "归档区" if new_mode == "archive" else "待删区"

        if self.items:
            self.status_var.set(
                f"已切换到【{name}】，共 {len(self.items)} 个（缓存）")
            self.refresh_tree()
        else:
            self.status_var.set(
                f"已切换到【{name}】，点【扫描】加载数据")
            for iid in self.tree.get_children():
                self.tree.delete(iid)
            self.iid_to_item.clear()
            self.iid_to_group.clear()
            self._show_empty_detail()

    def _pick_recent(self, event=None):
        v = self.recent_var.get()
        if v and v != "最近":
            self.root_dir.set(v)
            self.cfg.remember_dir(v)

    def open_settings(self):
        SettingsDialog(self.root, self.cfg, on_close=self._on_settings_close)

    def _on_settings_close(self):
        self.log("⚙ 目录设置已更新", "info")

    # ---------- 事件 ----------
    def _selected_items(self):
        sels = self.tree.selection()
        return [self.iid_to_item[i] for i in sels if i in self.iid_to_item]

    def _selected_item(self):
        items = self._selected_items()
        return items[0] if items else None

    def _on_select(self, event=None):
        sel = self.tree.selection()
        if not sel:
            self._show_empty_detail()
            self._try_refresh_loss()
            return

        iid = sel[0]
        if iid in self.iid_to_group:
            self._show_group(self.iid_to_group[iid])
            self._try_refresh_loss()
            return

        items = self._selected_items()
        if len(items) == 1:
            self._show_detail(items[0])
        elif len(items) > 1:
            self._show_multi(items)
        else:
            self._show_empty_detail()
        self._try_refresh_loss()

    def _on_double_click(self, event):
        iid = self.tree.identify_row(event.y)
        if iid in self.iid_to_item:
            self.open_file()

    def _on_rclick(self, event):
        iid = self.tree.identify_row(event.y)
        if iid:
            if iid not in self.tree.selection():
                self.tree.selection_set(iid)
            self.tree_menu.tk_popup(event.x_root, event.y_root)

    def _try_refresh_loss(self):
        """如果当前正在看 Loss Tab，就立刻刷新图表"""
        if self._loss_figure is None:
            return
        try:
            idx = self.right_nb.index("current")
        except Exception:
            return
        if idx == 4:   # Loss Tab 的下标
            self._refresh_loss_view()

    def _on_right_tab_changed(self, event=None):
        try:
            idx = self.right_nb.index("current")
        except Exception:
            return
        if idx == 4:  # Loss Tab
            self._refresh_loss_view()

    # ---------- 展示 ----------
    def _show_empty_detail(self):
        self.preview_label.config(image="", text="未选中\n\n单击左侧条目查看详情",
                                  bg="#1e1e2e", fg="#6b7280")
        self.preview_ref = None
        for t in (self.param_tree, self.batch_tree):
            for iid in t.get_children():
                t.delete(iid)
        self.mark_state.set("none")
        self.mark_comment.set("")

    def _show_multi(self, items):
        self.preview_label.config(image="", text=f"已选 {len(items)} 个文件",
                                  bg="#1e1e2e", fg="#6b7280")
        self.preview_ref = None
        if items:
            self._current_group = items[0].group
        self._fill_param_table(None, summary=f"已选中 {len(items)} 个文件")
        self._fill_batch_table(items)
        self.mark_state.set(items[0].state or "none")
        self.mark_comment.set("")

    def _show_detail(self, item):
        self._current_group = item.group
        self._update_preview(item)
        item.ensure_meta()
        self._fill_param_table(item.meta)
        self._fill_batch_table([item])
        self.mark_state.set(item.state or "none")
        self.mark_comment.set(item.comment or "")

    def _show_group(self, group_name):
        self._current_group = group_name
        group_items = [it for it in self.items if it.group == group_name]
        if not group_items:
            self._show_empty_detail()
            return
        group_items.sort(key=lambda x: x.batch or "zzzzzz")
        preview_item = next((it for it in group_items
                             if it.batch is None), group_items[-1])
        self._update_preview(preview_item)
        base_item = group_items[-1]
        base_item.ensure_meta()
        self._fill_param_table(base_item.meta,
                               summary=f"共 {len(group_items)} 个文件")
        self._fill_batch_table(group_items)
        self.mark_state.set("none")
        self.mark_comment.set("")

    def _fill_param_table(self, meta, summary=None):
        tree = self.param_tree
        for iid in tree.get_children():
            tree.delete(iid)
        if summary:
            tree.insert("", tk.END, values=("概要", summary))
        if not meta:
            if not summary:
                tree.insert("", tk.END, values=("（无元数据）", ""))
            return
        for key, label in META_LABELS.items():
            if key in meta:
                v = meta[key]
                if isinstance(v, str) and len(v) > 80:
                    v = v[:80] + "..."
                tree.insert("", tk.END, values=(label, v))

    def _fill_batch_table(self, items):
        tree = self.batch_tree
        for iid in tree.get_children():
            tree.delete(iid)
        if not items:
            return
        batch_items = [x for x in items if x.batch]
        latest = max(batch_items, key=lambda x: x.batch) if batch_items else None
        for i, it in enumerate(items):
            it.ensure_meta()
            meta = it.meta or {}
            epoch_done = meta.get("ss_epoch", "")
            epoch_total = meta.get("ss_num_epochs", "")
            steps = meta.get("ss_steps", "")
            if epoch_done and epoch_total:
                epoch_str = f"{epoch_done}/{epoch_total}"
            else:
                epoch_str = str(epoch_done or "-")
            batch_disp = it.batch if it.batch else "最终"
            ts = datetime.datetime.fromtimestamp(it.mtime).strftime(
                "%Y-%m-%d %H:%M")
            tags = []
            if it is latest:
                tags.append("latest")
            if it.batch is None:
                tags.append("final")
            if i % 2:
                tags.append("odd")
            tree.insert("", tk.END, values=(
                batch_disp, epoch_str, str(steps or "-"),
                human_size(it.size), ts),
                tags=tuple(tags))

    def _update_preview(self, item):
        if not HAS_PILTK:
            self.preview_label.config(image="", text="(ImageTk 不可用)")
            self.preview_ref = None
            return

        # 保存这个 LoRA 的预览图列表
        self._previews_list = list(getattr(item, "previews", []) or [])
        if not self._previews_list and item.preview:
            self._previews_list = [item.preview]

        self._preview_index = 0
        self._show_preview_at(0)

    def _on_preview_resize(self, event=None):
        """预览区尺寸变化时：延迟 200ms 再重绘（拖动时不重绘）"""
        if self._preview_resize_id is not None:
            try:
                self.root.after_cancel(self._preview_resize_id)
            except Exception:
                pass
        self._preview_resize_id = self.root.after(
            200, self._do_preview_resize)

    def _do_preview_resize(self):
        self._preview_resize_id = None
        if self._previews_list:
            self._show_preview_at(self._preview_index)
            
    def _show_preview_at(self, idx):
        if not self._previews_list:
            self.preview_label.config(image="", text="(无预览图)",
                                      bg="#1e1e2e", fg="#6b7280")
            self.preview_ref = None
            if self._nav_var is not None:
                self._nav_var.set("")
            return

        idx = max(0, min(idx, len(self._previews_list) - 1))
        self._preview_index = idx
        path = self._previews_list[idx]

        if not os.path.isfile(path):
            self.preview_label.config(image="", text="(文件不存在)",
                                      bg="#1e1e2e", fg="#6b7280")
            self.preview_ref = None
            return

        try:
            key = (path, os.path.getmtime(path))
            photo = self.thumb_cache.get(key)

            if photo is None:
                # 缓存没命中 → 生成缩略图
                with Image.open(path) as raw:
                    img = raw.convert("RGBA")
                bg = Image.new("RGB", img.size, (30, 30, 46))
                bg.paste(img, mask=img.split()[-1])

                # 用 frame 尺寸减去导航栏高度
                frm_w = self.preview_frame.winfo_width()
                frm_h = self.preview_frame.winfo_height()
                if frm_w < 50 or frm_h < 50:
                    max_w, max_h = MAX_PREVIEW
                else:
                    max_w = max(1, frm_w - 20)
                    max_h = max(1, frm_h - 50)
                bg.thumbnail((max_w, max_h), Image.LANCZOS)

                photo = ImageTk.PhotoImage(bg)

                if len(self.thumb_cache) > 200:
                    self.thumb_cache.clear()
                self.thumb_cache[key] = photo

            self.preview_label.config(image=photo, text="", bg="#1e1e2e")
            self.preview_ref = photo

            # 更新导航条
            if self._nav_var is not None:
                total = len(self._previews_list)
                if total > 1:
                    self._nav_var.set(f"{idx + 1} / {total}")
                else:
                    self._nav_var.set("")
        except Exception as e:
            import traceback
            print(f"[预览图失败] {path}")
            print(traceback.format_exc())
            self.preview_label.config(
                image="",
                text=f"(读取失败：{os.path.basename(path)})",
                bg="#1e1e2e", fg="#6b7280")
            self.preview_ref = None

    def _prev_preview(self):
        if not self._previews_list:
            return
        n = len(self._previews_list)
        self._show_preview_at((self._preview_index - 1) % n)

    def _next_preview(self):
        if not self._previews_list:
            return
        n = len(self._previews_list)
        self._show_preview_at((self._preview_index + 1) % n)

    # ---------- Loss 相关 ----------
    def _ensure_log_index(self, force=False):
        if not HAS_LOG_PARSER:
            return None
        if self._log_index is None or force:
            try:
                self._log_index = log_parser.scan_logs_index(force=force)
            except Exception as e:
                messagebox.showerror("错误", f"扫描日志失败：{e}")
                return None
        return self._log_index

    def _calc_log_signature(self):
        """日志索引的指纹：用于判断"日志环境是否变化" """
        if not self._log_index:
            return (0, 0)
        n = len(self._log_index)
        latest = 0
        for e in self._log_index.values():
            t = e.get("first_wall_time", 0)
            if t > latest:
                latest = t
        return (n, round(latest))
    
    def _preheat_loss_cache(self):
        """后台预读所有已关联日志的曲线，填进 _curve_cache"""
        if not HAS_LOG_PARSER:
            return
        if self._preheat_running:
            return
        if not self._log_index:
            return

        # 收集待预读的 events_file
        targets = {}   # ev_path -> (log_name, entry)
        mapping = self.db.data.get("group_log_mapping", {})
        for gname, info in mapping.items():
            log_name = info.get("log_name")
            if not log_name:
                continue
            entry = self._log_index.get(log_name)
            if not entry:
                continue
            if not entry.get("has_loss"):
                continue
            ev = entry.get("events_file", "")
            if not ev or ev in self._curve_cache:
                continue
            targets[ev] = (log_name, entry)

        if not targets:
            return

        self._preheat_running = True
        self.log(f"⏳ 正在预加载 {len(targets)} 个日志的曲线...", "info")

        def worker():
            try:
                for ev, (log_name, entry) in targets.items():
                    try:
                        curves = log_parser.load_multi_curves_cached(ev)
                        self._curve_cache[ev] = curves
                    except Exception:
                        pass
            finally:
                self.queue.put(("preheat_done", len(targets)))

        threading.Thread(target=worker, daemon=True).start()

    def _start_auto_match_all(self):
        """后台线程：对所有已扫描的 LoRA 组自动匹配日志（带指纹缓存）"""
        if not HAS_LOG_PARSER:
            return
        if self._auto_match_running:
            return

        # 收集所有组的最早 mtime
        group_earliest = {}
        pools = list(self._view_items.values()) + [self.items]
        for pool in pools:
            for it in pool:
                g = it.group
                if g not in group_earliest or it.mtime < group_earliest[g]:
                    group_earliest[g] = it.mtime

        # 过滤掉已关联的
        unmatched = [(g, t) for g, t in group_earliest.items()
                     if not self.db.get_group_log(g)]

        if not unmatched:
            # 全都关联过了：直接进入预热
            self._preheat_loss_cache()
            return

        # 加载日志索引（提前，用于指纹）
        if self._log_index is None:
            try:
                self._log_index = log_parser.scan_logs_index(force=False)
            except Exception as e:
                self.log(f"⚠ 日志索引加载失败：{e}", "warn")
                return

        if not self._log_index:
            self.log("⚠ 日志索引为空，未配置日志根目录？", "warn")
            return

        # 计算日志索引指纹
        log_sig = self._calc_log_signature()

        # 过滤掉指纹未变的组
        to_match = []
        for g, t in unmatched:
            fp = (round(t), log_sig)
            if self._match_fingerprints.get(g) == fp:
                continue
            to_match.append((g, t, fp))

        skipped = len(unmatched) - len(to_match)
        if not to_match:
            if skipped > 0:
                self.log(
                    f"· 日志环境未变，跳过 {skipped} 个组的重复匹配",
                    "info")
            return

        self._auto_match_running = True
        msg = f"🔍 开始自动匹配 {len(to_match)} 个未关联的 LoRA 组"
        if skipped > 0:
            msg += f"（跳过 {skipped} 个未变的）"
        self.log(msg, "info")

        def worker():
            matched = 0
            for g, earliest, fp in to_match:
                try:
                    name, _entry = log_parser.match_lora_to_log(
                        earliest, self._log_index,
                        tolerance_seconds=1800)
                    self._match_fingerprints[g] = fp
                    if name:
                        self.db.set_group_log(g, name, source="auto")
                        matched += 1
                        self.queue.put(
                            ("log", (f"✓ {g} → {name}", "ok")))
                except Exception as e:
                    self.queue.put(
                        ("log", (f"✗ {g}: {e}", "err")))

            self.queue.put(("auto_match_done", matched, len(to_match)))
            # 触发日志预加载
            self._preheat_loss_cache()

        threading.Thread(target=worker, daemon=True).start()

    def _auto_match_log(self):
        if not HAS_LOG_PARSER:
            messagebox.showinfo("提示", "未找到 log_parser.py 模块")
            return
        if not self._current_group:
            messagebox.showinfo("提示", "请先在左侧选中一个 LoRA 组")
            return
        index = self._ensure_log_index()
        if index is None:
            return

        group_items = [it for it in self.items
                       if it.group == self._current_group]
        if not group_items:
            return
        earliest = min(it.mtime for it in group_items)

        name, entry = log_parser.match_lora_to_log(earliest, index,
                                                    tolerance_seconds=1800)
        if not name:
            if messagebox.askyesno(
                "未找到匹配",
                "自动匹配没找到时间接近的日志。\n\n"
                "是否手动指定？"):
                self._manual_pick_log()
            return

        self.db.set_group_log(self._current_group, name, source="auto")
        self._render_loss(name)
        self.log(f"🔍 自动匹配：{self._current_group} → {name}", "info")

    def _manual_pick_log(self):
        if not HAS_LOG_PARSER:
            return
        if not self._current_group:
            messagebox.showinfo("提示", "请先在左侧选中一个 LoRA 组")
            return

        init = log_parser.DEFAULT_LOG_ROOT
        d = filedialog.askdirectory(
            initialdir=init if os.path.isdir(init) else None,
            title="选择训练日志目录（时间戳目录）")
        if not d:
            return

        parent_name = os.path.basename(os.path.normpath(d))
        if not (len(parent_name) == 14 and parent_name.isdigit()):
            if not messagebox.askyesno(
                "名字看起来不对",
                f"选择的目录名 {parent_name}\n"
                f"不像日志时间戳目录（应为 14 位数字）。\n\n"
                f"仍要继续吗？"):
                return

        self.db.set_group_log(self._current_group, parent_name,
                              source="manual")
        self._render_loss(parent_name)
        self.log(f"📂 手动指定：{self._current_group} → {parent_name}", "info")

    def _refresh_loss_cache_info(self):
        if not HAS_LOG_PARSER:
            return
        if not hasattr(self, "_loss_cache_info_var"):
            return
        try:
            n, size = log_parser.loss_cache_size()
        except Exception:
            n, size = 0, 0
        s = human_size(size) if size > 0 else "0 B"
        self._loss_cache_info_var.set(f"（{n} 个 / {s}）")

    def _clear_loss_cache(self):
        if not HAS_LOG_PARSER:
            return
        try:
            n, size = log_parser.loss_cache_size()
        except Exception:
            n, size = 0, 0
        if n == 0:
            messagebox.showinfo("提示", "曲线缓存已经是空的")
            return
        if not messagebox.askyesno(
            "确认清除",
            f"将删除 {n} 个曲线缓存（{human_size(size)}）。\n\n"
            f"清除后下次打开会重新读取 events（较慢）。\n\n继续？"):
            return
        cnt, freed = log_parser.clear_loss_cache()
        self._curve_cache.clear()  # 内存缓存也清掉
        self._refresh_loss_cache_info()
        self.log(f"🧹 已清除曲线缓存：{cnt} 个，"
                 f"释放 {human_size(freed)}", "ok")

    def _pick_log_root(self):
        """设置 lora-scripts 日志根目录"""
        from paths import get_log_root, set_log_root
        current = get_log_root()
        d = filedialog.askdirectory(
            initialdir=current if os.path.isdir(current) else None,
            title="选择 lora-scripts 的 logs 目录")
        if not d:
            return
        if set_log_root(d):
            self._log_index = None
            self._curve_cache.clear()
            self.log(f"⚙ 日志目录已设为：{d}", "info")
            messagebox.showinfo(
                "成功",
                f"日志根目录已设置：\n\n{d}\n\n"
                f"下次点【自动匹配】会从这个目录找日志。")
            self._refresh_loss_view()
        else:
            messagebox.showerror("失败", "写入配置失败")

    def _unlink_log(self):
        if not self._current_group:
            return
        self.db.del_group_log(self._current_group)
        self._draw_empty_axes(f"'{self._current_group}' 已解除关联")
        if self._loss_info_var is not None:
            self._loss_info_var.set("")

    def _refresh_loss_view(self):
        if not HAS_MPL:
            return
        if self._loss_figure is None:
            return
        if not self._current_group:
            self._draw_empty_axes("未选中组")
            if self._loss_info_var is not None:
                self._loss_info_var.set("")
            return
        log_name = self.db.get_group_log(self._current_group)
        if not log_name:
            self._draw_empty_axes(
                f"'{self._current_group}'\n还没有关联日志\n"
                f"点下方按钮自动匹配或手动指定")
            if self._loss_info_var is not None:
                self._loss_info_var.set(f"组：{self._current_group}  ·  未关联")
            return
        self._render_loss(log_name)

    def _render_loss(self, log_name):
        if not HAS_LOG_PARSER or self._loss_figure is None:
            return
        index = self._log_index or {}
        entry = index.get(log_name)
        if not entry:
            self._draw_empty_axes(f"日志 {log_name} 不在索引里")
            return

        if not entry.get("has_loss"):
            reason = entry.get("reason", "")
            self._draw_empty_axes(f"该日志无 loss 数据（{reason}）")
            if self._loss_info_var is not None:
                self._loss_info_var.set(f"日志：{log_name}")
            return

        ev = entry.get("events_file", "")

        # 已缓存 → 立刻画
        if ev in self._curve_cache:
            self._draw_curves(self._curve_cache[ev], log_name, entry)
            return

        # 未缓存 → 先画"加载中"，后台线程读
        self._draw_empty_axes(f"正在读取日志 {log_name}...")
        if self._loss_info_var is not None:
            ts = entry.get("time_str", "")
            size_kb = entry.get("size_kb", 0)
            self._loss_info_var.set(
                f"日志 {log_name}  ·  开始 {ts}  ·  {size_kb} KB"
                f"  ·  正在加载...")

        self._loss_load_token += 1
        token = self._loss_load_token

        def worker():
            try:
                curves = log_parser.load_multi_curves_cached(ev)
                err = None
            except Exception as e:
                curves = None
                err = str(e)
            self.queue.put(
                ("curve_loaded", token, ev, log_name, entry, curves, err))

        threading.Thread(target=worker, daemon=True).start()

    def _draw_curves(self, curves, log_name, entry):
        fig = self._loss_figure
        fig.clear()
        ax = fig.add_subplot(111)
        ax.set_facecolor(COLOR["card"])

        avg = curves.get('loss/average', [])
        cur = curves.get('loss/current', [])
        ep = curves.get('loss/epoch', [])

        # 悬停用完整数据；绘制用降采样
        self._hover_data = {}

        if not avg and not cur and not ep:
            ax.text(0.5, 0.5, "无 loss 数据", ha='center', va='center',
                    transform=ax.transAxes, fontsize=12,
                    color=COLOR["muted"])
        else:
            if cur:
                d = log_parser.downsample(cur, 600)
                ax.plot([s for s, _ in d], [v for _, v in d],
                        color='#cbd5e1', linewidth=0.6,
                        label='loss/current', alpha=0.5)
                self._hover_data['loss/current'] = cur
            if avg:
                d = log_parser.downsample(avg, 600)
                ax.plot([s for s, _ in d], [v for _, v in d],
                        color='#3b82f6', linewidth=1.6,
                        label='loss/average')
                self._hover_data['loss/average'] = avg
            if ep:
                ax.plot([s for s, _ in ep], [v for _, v in ep],
                        color='#10b981', linewidth=1.2,
                        marker='o', markersize=3, label='loss/epoch')
                self._hover_data['loss/epoch'] = ep
            ax.legend(loc='upper right', fontsize=8)
            ax.set_xlabel('Step', fontsize=9)
            ax.set_ylabel('Loss', fontsize=9)
            ax.grid(True, linestyle='--', alpha=0.3)
            ax.tick_params(labelsize=8)

        fig.tight_layout()
        self._loss_canvas.draw()

        if self._loss_info_var is not None:
            ts = entry.get("time_str", "")
            size_kb = entry.get("size_kb", 0)
            info = f"日志 {log_name}  ·  开始 {ts}  ·  {size_kb} KB"
            if cur:
                info += f"  ·  步数 {cur[-1][0]}"
            info += "  ·  悬停鼠标查看数值，工具栏可放大"
            self._loss_info_var.set(info)

    def _on_hover(self, event):
        if self._hover_value_var is None:
            return
        if event.inaxes is None:
            self._last_hover_x = None
            self._hover_value_var.set(
                "🖱  将鼠标移到曲线上可查看数值")
            return
        x = event.xdata
        if x is None:
            return
        self._last_hover_x = x
        self._update_hover_value(x)

    def _on_hover_refresh(self):
        """下拉切换时，用上次鼠标位置重新计算"""
        if self._last_hover_x is None:
            return
        self._update_hover_value(self._last_hover_x)

    def _update_hover_value(self, x):
        if not self._hover_data:
            self._hover_value_var.set(
                "🖱  将鼠标移到曲线上可查看数值")
            return

        # 每个系列各找最近点
        nearest = {}
        for series_name, pts in self._hover_data.items():
            if not pts:
                continue
            steps = [s for s, _ in pts]
            i = bisect.bisect_left(steps, x)
            best = None
            best_d = None
            for j in (i - 1, i):
                if 0 <= j < len(pts):
                    s, v = pts[j]
                    d = abs(s - x)
                    if best_d is None or d < best_d:
                        best_d = d
                        best = (s, v)
            if best:
                nearest[series_name] = best

        if not nearest:
            self._hover_value_var.set(
                "🖱  将鼠标移到曲线上可查看数值")
            return

        mode = (self._hover_series_var.get()
                if self._hover_series_var else "全部")

        if mode == "全部":
            # 显示三个系列在各自最近 step 的值
            # 以 current 的 step 为主显示
            main_s = None
            for n in ("loss/current", "loss/average", "loss/epoch"):
                if n in nearest:
                    main_s = nearest[n][0]
                    break
            parts = []
            for n in ("loss/current", "loss/average", "loss/epoch"):
                if n in nearest:
                    s, v = nearest[n]
                    short = {"loss/current": "cur",
                             "loss/average": "avg",
                             "loss/epoch": "ep"}[n]
                    parts.append(f"{short}={v:.4f}")
            if main_s is not None:
                self._hover_value_var.set(
                    f"📍 step≈{main_s}   " + "   ".join(parts))
            else:
                self._hover_value_var.set(
                    "📍  " + "   ".join(parts))
        else:
            if mode in nearest:
                s, v = nearest[mode]
                self._hover_value_var.set(
                    f"📍 {mode}   step={s}   loss={v:.4f}")
            else:
                self._hover_value_var.set(f"📍 {mode}   (无数据)")

    def _draw_empty_axes(self, msg):
        if self._loss_figure is None:
            return

        # ★ 清空悬停残留
        self._hover_data = {}
        self._last_hover_x = None
        if self._hover_value_var is not None:
            self._hover_value_var.set(
                "🖱  将鼠标移到曲线上可查看数值")

        fig = self._loss_figure
        fig.clear()
        ax = fig.add_subplot(111)
        ax.text(0.5, 0.5, msg, ha='center', va='center',
                transform=ax.transAxes, fontsize=11, color=COLOR["muted"])
        ax.set_xticks([])
        ax.set_yticks([])
        for s in ax.spines.values():
            s.set_color(COLOR["border"])
        fig.tight_layout()
        self._loss_canvas.draw()

    # ---------- 标记 ----------
    def apply_marks(self):
        items = self._selected_items()
        if not items:
            return
        state_val = self.mark_state.get()
        state = None if state_val == "none" else state_val
        comment = self.mark_comment.get().strip()
        for it in items:
            it.state = state
            it.comment = comment
            self.db.set(it.path, state=state, comment=comment)
        self.db.save()
        self.refresh_tree(preserve_selection=True)
        self.log(f"✓ 已标记 {len(items)} 个文件为 "
                 f"{STATE_LABEL.get(state, '未标记')}", "ok")

    def batch_mark(self, state):
        items = self._selected_items()
        if not items:
            messagebox.showinfo("提示", "请先选中文件")
            return
        for it in items:
            it.state = state
            self.db.set(it.path, state=state)
        self.db.save()
        self.refresh_tree(preserve_selection=True)
        label = STATE_LABEL.get(state, "未标记")
        self.log(f"✓ 已批量标记 {len(items)} 个文件为 {label}", "ok")

    # ---------- 树刷新 ----------
    def refresh_tree(self, preserve_selection=False):
        old_sel = set()
        if preserve_selection:
            for iid in self.tree.selection():
                it = self.iid_to_item.get(iid)
                if it:
                    old_sel.add(it.path)

        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self.iid_to_item.clear()
        self.iid_to_group.clear()

        if not self.items:
            self._show_empty_detail()
            return

        groups = defaultdict(list)
        for it in self.items:
            groups[it.group].append(it)

        keyword = self.search_var.get().strip().lower()
        sort_mode = self.sort_var.get() if hasattr(self, "sort_var") else "名称"

        total_shown = 0
        for gname in sorted(groups.keys(), key=lambda x: x.lower()):
            g_items = groups[gname]

            if keyword:
                matched = [it for it in g_items
                           if keyword in it.stem.lower()
                           or keyword in (it.comment or "").lower()]
                if not matched:
                    continue
                g_items = matched

            g_items = sorted(g_items, key=lambda x: (x.batch is not None,
                                                     x.batch or ""))

            if sort_mode == "时间 ↓":
                g_items = sorted(g_items, key=lambda x: -x.mtime)
            elif sort_mode == "大小 ↓":
                g_items = sorted(g_items, key=lambda x: -x.size)

            batch_items = [x for x in g_items if x.batch]
            latest = max(batch_items, key=lambda x: x.batch) if batch_items else None

            total_size = sum(it.size for it in g_items)
            parent_iid = self.tree.insert(
                "", tk.END,
                text=f"📁 {gname}",
                values=("", "", human_size(total_size),
                        "", f"{len(g_items)} 个"),
                open=(len(g_items) > 1 and not keyword) or bool(keyword))
            self.iid_to_group[parent_iid] = gname

            for it in g_items:
                icon = STATE_ICON.get(it.state, "·")
                is_latest = (it is latest)
                is_final = (it.batch is None)
                name_text = it.stem
                if is_final:
                    name_text = f"{name_text}  [最终]"
                elif is_latest:
                    name_text = f"{name_text}  [最新]"

                batch_disp = it.batch if it.batch else "最终"
                ts = datetime.datetime.fromtimestamp(it.mtime).strftime("%Y-%m-%d %H:%M")
                comment_disp = (it.comment or "")[:40]

                tags = []
                if is_final:
                    tags.append("final")
                elif is_latest:
                    tags.append("latest")

                child = self.tree.insert(
                    parent_iid, tk.END,
                    text=f"{icon}  {name_text}",
                    values=(STATE_LABEL.get(it.state, "·"),
                            batch_disp,
                            human_size(it.size),
                            ts,
                            comment_disp),
                    tags=tuple(tags))
                self.iid_to_item[child] = it
                total_shown += 1

                if it.path in old_sel:
                    self.tree.selection_add(child)

        n_groups = len(groups)
        total_size_all = sum(it.size for it in self.items)
        msg = (f"共 {len(self.items)} 个 LoRA · {n_groups} 组 · "
               f"总计 {human_size(total_size_all)}")
        if keyword:
            msg += f" · 当前显示 {total_shown} 个"
        self.status_var.set(msg)

    # ---------- 扫描 ----------
    def start_scan(self):
        mode = self.view_mode.get()
        work_dir = self.root_dir.get().strip()
        archive_dir = self.cfg.data.get("archive_dir", "")
        pending_dir = self.cfg.data.get("pending_delete_dir", "")

        # 校验当前视图的目录
        if mode == "work":
            if not work_dir or not os.path.isdir(work_dir):
                messagebox.showerror("错误", "请选择有效的工作区目录")
                return
        elif mode == "archive":
            if not archive_dir or not os.path.isdir(archive_dir):
                messagebox.showerror(
                    "错误",
                    "归档目录未设置或不存在。\n\n"
                    "请点击【设置】按钮指定归档目录。")
                return
        else:  # pending
            if not pending_dir or not os.path.isdir(pending_dir):
                messagebox.showerror(
                    "错误",
                    "待删目录未设置或不存在。\n\n"
                    "请点击【设置】按钮指定待删目录。")
                return

        if self.scanner is not None:
            return

        # 重复扫描检查
        cached = self._view_items.get(mode)
        last_root = self._view_root.get(mode, "")
        cur_root = work_dir if mode == "work" else (
            archive_dir if mode == "archive" else pending_dir)
        if cached and last_root == cur_root:
            answer = messagebox.askyesnocancel(
                "重复扫描？",
                f"根目录未变：{cur_root}\n"
                f"已有缓存 {len(cached)} 个 LoRA。\n\n"
                f"【是】  重新扫描（较慢，但能发现新文件）\n"
                f"【否】  跳过扫描，只做日志自动匹配（较快）\n"
                f"【取消】什么都不做")
            if answer is None:
                return
            if answer is False:
                self.status_var.set("跳过扫描，仅做日志自动匹配...")
                self._start_auto_match_all()
                return

        if mode == "work":
            self.cfg.remember_dir(work_dir)

        # 构造三区域扫描目标
        self._scan_targets = {
            "work": work_dir if work_dir and os.path.isdir(work_dir) else None,
            "archive": archive_dir if archive_dir and os.path.isdir(archive_dir) else None,
            "pending": pending_dir if pending_dir and os.path.isdir(pending_dir) else None,
        }

        # 启动
        self.scan_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.progress["value"] = 0
        self.progress["maximum"] = 1
        self.status_var.set("扫描中...")
        self.log("🔍 开始三区域扫描...", "info")

        self._scan_stop_event.clear()
        threading.Thread(
            target=self._multi_scan_worker, daemon=True).start()

    def _multi_scan_worker(self):
        """串行扫三个区域，各存各的缓存"""
        for region, root in self._scan_targets.items():
            if self._scan_stop_event.is_set():
                break
            if not root:
                self.queue.put(("region_done", region, []))
                continue

            self.queue.put(("log", (f"📂 [{region}] {root}", "info")))

            # 工作区要排除归档/待删
            exclude = []
            if region == "work":
                ad = self.cfg.data.get("archive_dir", "")
                pd = self.cfg.data.get("pending_delete_dir", "")
                if ad:
                    exclude.append(ad)
                if pd:
                    exclude.append(pd)

            scanner = LoraScanner(
                root, True, self.db,
                on_progress=lambda a, b, m:
                    self.queue.put(("progress", a, b, m)),
                on_done=None,
                exclude_dirs=exclude)
            scanner.stop_event = self._scan_stop_event

            try:
                items, err = scanner.run_sync()
            except Exception as e:
                items, err = [], str(e)

            if err:
                self.queue.put(("log",
                                (f"✗ [{region}] 失败：{err}", "err")))
                items = []

            self.queue.put(("region_done", region, items))

        self.queue.put(("all_regions_done",))

    def stop_scan(self):
        if self.scanner:
            self.scanner.stop()
            self.status_var.set("停止中...")

    def reload_meta(self):
        for it in self.items:
            it.meta = None
            it.triggers = None
            it.preview = None
        self.thumb_cache.clear()

        def worker():
            total = len(self.items)
            for i, it in enumerate(self.items):
                it.ensure_meta()
                it.ensure_preview()
                if i % 10 == 0:
                    self.queue.put(("progress", i, total, f"重载 {i}/{total}"))
            self.queue.put(("reloaded",))

        threading.Thread(target=worker, daemon=True).start()

    def _check_queue(self):
        if not self._queue_running:
            return
        try:
            while True:
                msg = self.queue.get_nowait()
                kind = msg[0]
                if kind == "progress":
                    _, a, b, m = msg
                    self.progress["maximum"] = max(1, b)
                    self.progress["value"] = a
                    self.status_var.set(m)
                elif kind == "done":
                    _, items, err = msg
                    self.scanner = None
                    self.scan_btn.config(state=tk.NORMAL)
                    self.stop_btn.config(state=tk.DISABLED)
                    if err:
                        messagebox.showerror("扫描失败", err)
                        self.log(f"✗ 扫描失败: {err}", "err")
                        continue
                    self.items = items
                    self._view_items[self.view_mode.get()] = list(items)
                    self._view_root[self.view_mode.get()] = (
                        self.root_dir.get())
                    self.refresh_tree()
                    # ★ 扫描完成后自动匹配日志
                    self._start_auto_match_all()
                    if not items:
                        self.status_var.set("扫描完成：未找到任何 safetensors 文件")
                        self.log("扫描完成：未找到任何文件", "warn")
                    else:
                        self.status_var.set(f"扫描完成：{len(items)} 个文件")
                        self.log(f"✓ 扫描完成：{len(items)} 个文件", "ok")
                elif kind == "reloaded":
                    self.refresh_tree()
                    self.status_var.set("元数据已重载")
                    self.log("✓ 元数据已重载", "ok")
                elif kind == "preheat_done":
                    _, n = msg
                    self._preheat_running = False
                    self.log(f"✓ 日志预加载完成：{n} 个", "ok")
                    self._refresh_loss_cache_info()    
                elif kind == "auto_match_done":
                    _, matched, total = msg
                    self._auto_match_running = False
                    if total > 0:
                        self.log(
                            f"✓ 日志自动匹配完成：{matched}/{total} 个组已关联",
                            "ok")
                        self.status_var.set(
                            f"日志自动匹配：{matched}/{total} 个组已关联")
                elif kind == "region_done":
                    _, region, items = msg
                    self._view_items[region] = list(items)
                    if region == "work":
                        self._view_root[region] = self.root_dir.get()
                    elif region == "archive":
                        self._view_root[region] = self.cfg.data.get(
                            "archive_dir", "")
                    else:
                        self._view_root[region] = self.cfg.data.get(
                            "pending_delete_dir", "")
                    self.log(f"  ✓ [{region}] {len(items)} 个文件", "ok")
                elif kind == "all_regions_done":
                    self.scanner = None
                    self.scan_btn.config(state=tk.NORMAL)
                    self.stop_btn.config(state=tk.DISABLED)
                    cur = self.view_mode.get()
                    self.items = list(self._view_items.get(cur, []))
                    self.refresh_tree()
                    total = sum(
                        len(v) for v in self._view_items.values())
                    self.status_var.set(
                        f"扫描完成：三区域共 {total} 个文件（当前视图 {len(self.items)} 个）")
                    # 自动匹配日志（它内部会决定是否预加载）
                    self._start_auto_match_all()
                elif kind == "curve_loaded":
                    _, token, ev, log_name, entry, curves, err = msg
                    if token != self._loss_load_token:
                        continue   # 已过期，丢弃，继续处理队列
                    if err:
                        self._draw_empty_axes(f"读取失败：{err}")
                        continue
                    self._curve_cache[ev] = curves
                    self._draw_curves(curves, log_name, entry)    
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

    # ---------- 清理 / 归档 ----------
    def execute_clean(self):
        pending_dir = self.cfg.data.get("pending_delete_dir", "")
        if not pending_dir:
            messagebox.showerror("未配置", "请先在【目录设置】里指定待删目录")
            return
        targets = [it for it in self.items if it.state == STATE_CLEAN]
        if not targets:
            messagebox.showinfo("提示", "没有标记为【待清理】的文件")
            return
        if not messagebox.askyesno(
            "确认清理",
            f"将把 {len(targets)} 个文件移动到：\n\n{pending_dir}\n\n"
            f"（稍后可在该目录确认后清空到系统回收站）\n\n继续？"):
            return
        root_dir = self.root_dir.get().strip()
        moves = []
        ok_count = 0
        errs = []
        for it in targets:
            ok, res = move_file(it.path, pending_dir, root_dir)
            if ok:
                moves.append({"from": it.path, "to": res})
                self.db.set(it.path, state=None)
                ok_count += 1
            else:
                errs.append((it.stem, res))
        if moves:
            self.db.add_history("clean", moves)
            self.db.save()
        moved_paths = {m["from"] for m in moves}
        self.items = [it for it in self.items if it.path not in moved_paths]
        self.refresh_tree()
        self.log(f"✓ 清理完成：{ok_count} 个文件已移动到 {pending_dir}", "ok")
        for name, err in errs:
            self.log(f"✗ {name} - {err}", "err")
        if ok_count:
            messagebox.showinfo("完成",
                f"{ok_count} 个文件已移动到待删目录\n\n{pending_dir}")

    def empty_pending(self):
        pending_dir = self.cfg.data.get("pending_delete_dir", "")
        if not pending_dir or not os.path.isdir(pending_dir):
            messagebox.showerror("未配置", "待删目录不存在，请先在目录设置中指定")
            return
        files = []
        for root, _, fs in os.walk(pending_dir):
            for f in fs:
                files.append(os.path.join(root, f))
        if not files:
            messagebox.showinfo("提示", "待删目录为空")
            return

        if not messagebox.askyesno(
            "确认清空",
            f"将把待删目录里的 {len(files)} 个文件移到系统回收站。\n\n"
            f"目录：{pending_dir}\n\n"
            f"（移入回收站后仍可从回收站恢复）\n\n继续？"):
            return

        if HAS_TRASH:
            ok, errs = try_send_to_trash(files)
            self.log(f"🗑 已移入回收站：{ok} 个", "ok")
            for p, e in errs:
                self.log(f"✗ {os.path.basename(p)} - {e}", "err")

            if errs and ok == 0:
                # 全部失败：问是否永久删除
                if messagebox.askyesno(
                    "回收站不可用",
                    f"全部 {len(errs)} 个文件都无法移入回收站。\n\n"
                    f"原因示例：{errs[0][1][:100]}\n\n"
                    f"是否改为【永久删除】？\n\n"
                    f"⚠ 永久删除后无法从回收站恢复！"):
                    cnt = 0
                    for p, _ in errs:
                        try:
                            os.remove(p)
                            cnt += 1
                        except Exception:
                            pass
                    self.log(f"🗑 已永久删除：{cnt} 个", "warn")
                    messagebox.showinfo("完成", f"已永久删除 {cnt} 个文件")
                else:
                    messagebox.showinfo(
                        "已取消",
                        "未删除任何文件。\n\n"
                        "提示：可以手动到待删目录里\n"
                        "选中文件后按 Shift+Delete 直接删除。")
            elif errs:
                # 部分失败
                if messagebox.askyesno(
                    "部分文件失败",
                    f"成功 {ok} 个，失败 {len(errs)} 个。\n\n"
                    f"是否对失败的 {len(errs)} 个改为永久删除？\n\n"
                    f"⚠ 永久删除后无法从回收站恢复！"):
                    cnt = 0
                    for p, _ in errs:
                        try:
                            os.remove(p)
                            cnt += 1
                        except Exception:
                            pass
                    self.log(f"🗑 已永久删除：{cnt} 个", "warn")
                    messagebox.showinfo(
                        "完成",
                        f"已移入回收站 {ok} 个，永久删除 {cnt} 个")
                else:
                    messagebox.showinfo(
                        "完成",
                        f"已将 {ok} 个文件移入系统回收站")
            else:
                messagebox.showinfo(
                    "完成", f"已将 {ok} 个文件移入系统回收站")
        else:
            if not messagebox.askyesno(
                "缺少 send2trash",
                "未安装 send2trash，无法移入系统回收站。\n\n"
                "是否改为永久删除？此操作不可撤销！"):
                return
            cnt = 0
            for p in files:
                try:
                    os.remove(p)
                    cnt += 1
                except Exception:
                    pass
            self.log(f"🗑 已永久删除：{cnt} 个", "warn")
            messagebox.showinfo("完成", f"已永久删除 {cnt} 个文件") 

    def execute_archive(self):
        archive_dir = self.cfg.data.get("archive_dir", "")
        if not archive_dir:
            messagebox.showerror("未配置", "请先在【目录设置】里指定归档目录")
            return
        targets = [it for it in self.items if it.state == STATE_ARCHIVE]
        if not targets:
            messagebox.showinfo("提示", "没有标记为【归档】的文件")
            return
        if not messagebox.askyesno(
            "确认归档",
            f"将把 {len(targets)} 个文件移动到：\n\n{archive_dir}\n\n"
            f"（状态和注释会一起搬到新位置）\n\n继续？"):
            return
        root_dir = self.root_dir.get().strip()
        moves = []
        ok_count = 0
        errs = []
        for it in targets:
            # ---- 归档前先读出旧状态和注释 ----
            old_key = self.db.key(it.path)
            old_entry = self.db.data["files"].get(old_key, {}).copy()
            keep_state = old_entry.get("state")
            keep_comment = old_entry.get("comment", "")

            ok, res = move_file(it.path, archive_dir, root_dir)
            if ok:
                moves.append({"from": it.path, "to": res})

                # ---- 把状态和注释写进新路径 ----
                if keep_state or keep_comment:
                    self.db.set(res, state=keep_state,
                                comment=keep_comment)

                # ---- 清除旧路径记录 ----
                self.db.set(it.path, state=None, comment=None)
                ok_count += 1
            else:
                errs.append((it.stem, res))
        if moves:
            self.db.add_history("archive", moves)
            self.db.save()
        moved_paths = {m["from"] for m in moves}
        self.items = [it for it in self.items if it.path not in moved_paths]
        self.refresh_tree()
        self.log(f"✓ 归档完成：{ok_count} 个文件已移动到 {archive_dir}", "ok")
        for name, err in errs:
            self.log(f"✗ {name} - {err}", "err")
        if ok_count:
            messagebox.showinfo(
                "完成",
                f"{ok_count} 个文件已归档\n\n"
                f"状态和注释已一同迁移到：\n{archive_dir}")

    def open_history(self):
        HistoryDialog(self.root, self.db, on_undo_done=self._on_undo_done)

    def _on_undo_done(self, n):
        if n > 0:
            self.log(f"↩ 已撤销 {n} 个文件", "info")
            self.start_scan()

    # ---------- 文件操作 ----------
    def open_file(self):
        it = self._selected_item()
        if it:
            open_path(it.path)

    def open_preview(self):
        # 优先打开当前显示的那张
        if self._previews_list:
            idx = self._preview_index
            if 0 <= idx < len(self._previews_list):
                open_path(self._previews_list[idx])
                return
        it = self._selected_item()
        if it and it.preview:
            open_path(it.preview)

    def reveal_file(self):
        it = self._selected_item()
        if it:
            reveal_path(it.path)

    def add_preview(self):
        """给选中 LoRA 添加一张预览图（自动编号，可多张）"""
        it = self._selected_item()
        if not it:
            messagebox.showinfo("提示", "请先选中一个 LoRA")
            return

        f = filedialog.askopenfilename(
            title="选择预览图",
            filetypes=[
                ("图片", "*.png *.jpg *.jpeg *.webp *.gif *.bmp"),
                ("所有文件", "*.*"),
            ])
        if not f:
            return

        try:
            lora_base, _ = os.path.splitext(it.path)
            src_ext = os.path.splitext(f)[1].lower()

            existing = find_previews(it.path)

            # 情况 1：还没有预览图 → 用单张命名
            if not existing:
                dst = lora_base + src_ext
                if os.path.isfile(dst):
                    if not messagebox.askyesno(
                        "已存在",
                        f"预览图已存在：\n{dst}\n\n覆盖吗？"):
                        return
                shutil.copy2(f, dst)
            else:
                # 情况 2：只有单张 → 升级为多张（原图改 _01）
                is_single = (
                    len(existing) == 1
                    and os.path.basename(existing[0]).startswith(
                        os.path.basename(lora_base) + "."))
                if is_single:
                    old = existing[0]
                    old_ext = os.path.splitext(old)[1].lower()
                    new_first = lora_base + "_01" + old_ext
                    os.rename(old, new_first)
                    existing = [new_first]

                # 找当前最大编号
                max_n = 0
                for p in existing:
                    mm = re.search(r'_(\d+)\.\w+$', os.path.basename(p))
                    if mm:
                        max_n = max(max_n, int(mm.group(1)))

                nxt = max_n + 1
                dst = f"{lora_base}_{nxt:02d}{src_ext}"
                shutil.copy2(f, dst)

            # 刷新显示
            it.preview = None
            it.previews = []
            self.thumb_cache.clear()
            it.ensure_preview()
            self._update_preview(it)

            count = len(it.previews)
            self.status_var.set(f"✓ 预览图已添加（共 {count} 张）")
        except Exception as e:
            messagebox.showerror("失败", str(e))

    def show_all_previews(self):
        """打开 LoRA 所在文件夹，方便查看全部预览图"""
        it = self._selected_item()
        if not it:
            messagebox.showinfo("提示", "请先选中一个 LoRA")
            return
        reveal_path(it.path)

    def copy_path(self):
        it = self._selected_item()
        if it:
            copy_text(self.root, it.path)
            self.status_var.set("已复制路径")

    def export_csv(self):
        if not self.items:
            messagebox.showinfo("提示", "列表为空")
            return
        f = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
            initialfile="lora_list.csv",
            title="导出 LoRA 清单")
        if not f:
            return
        try:
            with open(f, "w", encoding="utf-8-sig", newline="") as fp:
                w = csv.writer(fp)
                w.writerow(["分组", "批次", "标记", "文件名", "大小(B)",
                            "状态", "注释", "底模", "维度", "训练步数",
                            "触发词", "路径"])
                for it in self.items:
                    it.ensure_meta()
                    meta = it.meta or {}
                    w.writerow([
                        it.group, it.batch or "最终", it.tag or "",
                        it.stem, it.size,
                        STATE_LABEL.get(it.state, "未标记"),
                        it.comment or "",
                        meta.get("ss_base_model_version", ""),
                        meta.get("ss_network_dim", ""),
                        meta.get("ss_steps", "") or meta.get("ss_max_train_steps", ""),
                        ", ".join((it.triggers or [])[:10]),
                        it.path,
                    ])
            self.log(f"✓ 已导出: {os.path.basename(f)}", "ok")
            messagebox.showinfo("完成", f"已导出 {len(self.items)} 条记录")
        except Exception as e:
            messagebox.showerror("导出失败", str(e))


# ================= 设置对话框 =================
class SettingsDialog(tk.Toplevel):
    def __init__(self, parent, cfg, on_close=None):
        super().__init__(parent)
        self.cfg = cfg
        self.on_close = on_close

        self.title("目录设置")
        self.configure(bg=COLOR["bg"])
        self.transient(parent)
        self.grab_set()

        parent.update_idletasks()
        pw = parent.winfo_width() or 1200
        ph = parent.winfo_height() or 800
        w = max(640, min(760, int(pw * 0.6)))
        h = max(420, min(500, int(ph * 0.55)))
        center_on_parent(self, parent, w, h)

        self.rowconfigure(0, weight=1)
        self.rowconfigure(1, weight=0)
        self.columnconfigure(0, weight=1)

        btn_bar = ttk.Frame(self, padding=(16, 10))
        btn_bar.grid(row=1, column=0, sticky="ew")
        ttk.Button(btn_bar, text="取消",
                   command=self.destroy).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(btn_bar, text="保存", style='Primary.TButton',
                   command=self._save).pack(side=tk.RIGHT)

        content = ttk.Frame(self, padding=(18, 16, 18, 8))
        content.grid(row=0, column=0, sticky="nsew")
        content.columnconfigure(0, weight=1)

        ttk.Label(content, text="📦 归档目录",
                  font=('Microsoft YaHei UI', 10, 'bold')
                  ).grid(row=0, column=0, sticky="w")
        row1 = ttk.Frame(content)
        row1.grid(row=1, column=0, sticky="ew", pady=(4, 4))
        row1.columnconfigure(0, weight=1)
        self.archive_var = tk.StringVar(master=self,
                                        value=cfg.data.get("archive_dir", ""))
        ttk.Entry(row1, textvariable=self.archive_var).grid(
            row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(row1, text="浏览", width=8,
                   command=self._pick_archive).grid(row=0, column=1)
        ttk.Label(content, text="标记为【归档】的文件将移动到此处",
                  font=('Microsoft YaHei UI', 8),
                  foreground=COLOR["muted"]
                  ).grid(row=2, column=0, sticky="w", pady=(0, 16))

        ttk.Label(content, text="🗑 待删目录",
                  font=('Microsoft YaHei UI', 10, 'bold')
                  ).grid(row=3, column=0, sticky="w")
        row2 = ttk.Frame(content)
        row2.grid(row=4, column=0, sticky="ew", pady=(4, 4))
        row2.columnconfigure(0, weight=1)
        self.pending_var = tk.StringVar(master=self,
                                        value=cfg.data.get("pending_delete_dir", ""))
        ttk.Entry(row2, textvariable=self.pending_var).grid(
            row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(row2, text="浏览", width=8,
                   command=self._pick_pending).grid(row=0, column=1)
        ttk.Label(content,
                  text="标记为【待清理】的文件先移动到这里；\n"
                       "再点主界面的【清空待删目录】移到系统回收站",
                  font=('Microsoft YaHei UI', 8),
                  foreground=COLOR["muted"], justify=tk.LEFT
                  ).grid(row=5, column=0, sticky="w")

        content.rowconfigure(6, weight=1)

    def _pick_archive(self):
        init = self.archive_var.get() or None
        d = filedialog.askdirectory(initialdir=init, title="选择归档目录")
        if d:
            self.archive_var.set(d)

    def _pick_pending(self):
        init = self.pending_var.get() or None
        d = filedialog.askdirectory(initialdir=init, title="选择待删目录")
        if d:
            self.pending_var.set(d)

    def _save(self):
        self.cfg.data["archive_dir"] = self.archive_var.get().strip()
        self.cfg.data["pending_delete_dir"] = self.pending_var.get().strip()
        self.cfg.save()
        if self.on_close:
            self.on_close()
        self.destroy()


# ================= 历史对话框 =================
class HistoryDialog(tk.Toplevel):
    def __init__(self, parent, db, on_undo_done=None):
        super().__init__(parent)
        self.db = db
        self.on_undo_done = on_undo_done

        self.title("操作历史")
        self.configure(bg=COLOR["bg"])
        self.transient(parent)

        parent.update_idletasks()
        pw = parent.winfo_width() or 1200
        ph = parent.winfo_height() or 800
        w = max(700, min(900, int(pw * 0.7)))
        h = max(420, min(600, int(ph * 0.65)))
        center_on_parent(self, parent, w, h)

        self.rowconfigure(0, weight=1)
        self.rowconfigure(1, weight=0)
        self.columnconfigure(0, weight=1)

        btn_bar = ttk.Frame(self, padding=(14, 10))
        btn_bar.grid(row=1, column=0, sticky="ew")
        ttk.Button(btn_bar, text="关闭",
                   command=self.destroy).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(btn_bar, text="↩ 撤销选中", style='Primary.TButton',
                   command=self._undo).pack(side=tk.RIGHT)

        content = ttk.Frame(self, padding=(14, 12, 14, 4))
        content.grid(row=0, column=0, sticky="nsew")
        content.rowconfigure(1, weight=1)
        content.columnconfigure(0, weight=1)

        ttk.Label(content, text="选择一条记录进行撤销（只显示未撤销的）",
                  font=('Microsoft YaHei UI', 9),
                  foreground=COLOR["muted"]
                  ).grid(row=0, column=0, sticky="w", pady=(0, 6))

        tree_box = ttk.Frame(content)
        tree_box.grid(row=1, column=0, sticky="nsew")
        tree_box.rowconfigure(0, weight=1)
        tree_box.columnconfigure(0, weight=1)

        cols = ("ts", "op", "count", "status")
        self.tree = ttk.Treeview(tree_box, columns=cols, show="headings",
                                 selectmode="browse")
        self.tree.heading("ts", text="时间")
        self.tree.heading("op", text="操作")
        self.tree.heading("count", text="文件数")
        self.tree.heading("status", text="状态")
        self.tree.column("ts", width=180)
        self.tree.column("op", width=100)
        self.tree.column("count", width=80, anchor=tk.CENTER)
        self.tree.column("status", width=100, anchor=tk.CENTER)

        vsb = ttk.Scrollbar(tree_box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        self.iid_to_h = {}
        self._load()

    def _load(self):
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self.iid_to_h = {}
        for h in self.db.histories(include_undone=False):
            op_label = {"clean": "清理", "archive": "归档"}.get(h["op"], h["op"])
            iid = self.tree.insert("", tk.END, values=(
                h["ts"], op_label, len(h["moves"]), "未撤销"))
            self.iid_to_h[iid] = h

    def _undo(self):
        sel = self.tree.selection()
        if not sel:
            return
        h = self.iid_to_h.get(sel[0])
        if not h:
            return

        op_label = {"clean": "清理", "archive": "归档"}.get(h["op"], h["op"])
        if not messagebox.askyesno(
            "确认撤销",
            f"将撤销这次操作（{op_label}，{len(h['moves'])} 个文件）？\n\n"
            f"文件将被移回原位置。"):
            return

        ok = 0
        errs = []
        for m in h["moves"]:
            src = m["to"]
            dst = m["from"]
            try:
                if not os.path.isfile(src):
                    errs.append((os.path.basename(src), "源文件不存在"))
                    continue
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                if os.path.exists(dst):
                    base, ext = os.path.splitext(dst)
                    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    dst = f"{base}_{ts}{ext}"
                shutil.move(src, dst)
                ok += 1
            except Exception as e:
                errs.append((os.path.basename(src), str(e)))

        self.db.mark_undone(h["id"])
        self._load()

        messagebox.showinfo("完成", f"已撤销 {ok} 个文件" +
                            (f"\n失败 {len(errs)} 个" if errs else ""))
        if self.on_undo_done:
            self.on_undo_done(ok)


# ================= 独立运行 =================
def main():
    enable_dpi_awareness()
    root = tk.Tk()
    root.title("LoRA 前后期工具箱 · by 翡翠珍珠排骨")
    root.configure(bg=COLOR["bg"])
    apply_dpi_scaling(root)
    w, h = calc_window_size(root, max_w=1800, max_h=1000,
                            min_w=1000, min_h=650)
    center_on_screen(root, w, h)
    root.minsize(960, 620)
    setup_styles()
    frame = ttk.Frame(root)
    frame.pack(fill=tk.BOTH, expand=True)
    LoRAManagerTab(frame, root)
    root.mainloop()


if __name__ == "__main__":
    main()