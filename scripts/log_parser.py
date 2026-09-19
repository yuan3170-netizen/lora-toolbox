# -*- coding: utf-8 -*-
# LoRA 前后期工具箱
# 作者：翡翠珍珠排骨 (B站 UID: 3923028)
# 主页：https://space.bilibili.com/3923028
# 协议：MIT License
"""
日志解析模块
- 扫描 lora-scripts 的 logs 目录，建立索引（快速）
- 按需读取指定日志的完整 loss 曲线（懒加载）
- 自动匹配 LoRA 组 ↔ 日志目录
"""
import os
import json
import datetime

# ---- 便携包路径 ----
import hashlib
from paths import get_log_root, LOSS_CURVE_CACHE_DIR

try:
    from tensorboard.backend.event_processing.event_file_loader import (
        EventFileLoader)
    from tensorboard.util import tensor_util
    HAS_TB = True
except ImportError:
    HAS_TB = False


# 默认日志根目录（可被外部覆盖）
DEFAULT_LOG_ROOT = get_log_root()

# 索引缓存文件名
INDEX_FILENAME = ".log_index.json"

# 大文件跳过阈值
MAX_FILE_SIZE = 100 * 1024 * 1024
CACHE_VERSION = 1


def _extract_value(value):
    """兼容新旧两种 tensorboard 数据格式"""
    if value.HasField('simple_value'):
        return float(value.simple_value)
    if value.HasField('tensor'):
        try:
            arr = tensor_util.make_ndarray(value.tensor)
            if arr.size == 0:
                return None
            return float(arr.flatten()[0])
        except Exception:
            return None
    return None


def _find_latest_events_file(dir_path):
    """找一个目录下最新的一个 events 文件"""
    candidates = []
    for root, _, files in os.walk(dir_path):
        for f in files:
            if f.startswith('events.out.tfevents'):
                p = os.path.join(root, f)
                try:
                    candidates.append(
                        (os.path.getmtime(p), os.path.getsize(p), p))
                except OSError:
                    pass
    if not candidates:
        return None, 0
    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return candidates[0][2], candidates[0][1]


def _quick_peek_events(events_file):
    """
    快速窥探：只读前 5 个事件，找 loss/current 和 first_wall_time。
    返回 (first_wall_time, has_loss, n_sample_pts)
    """
    loader = EventFileLoader(events_file)
    first_wall = None
    has_loss = False
    n = 0
    max_iter = 5
    try:
        for i, event in enumerate(loader.Load()):
            if first_wall is None and event.wall_time:
                first_wall = event.wall_time
            if event.HasField('summary'):
                for value in event.summary.value:
                    if value.tag == 'loss/current':
                        has_loss = True
            n += 1
            if i >= max_iter:
                break
    except Exception:
        pass
    return first_wall, has_loss, n


def scan_logs_index(log_root=DEFAULT_LOG_ROOT, force=False, on_progress=None):
    """
    扫日志目录，建索引。
    - 若缓存存在且不强制刷新，直接读缓存。
    - on_progress: 回调 (done, total, name)
    返回 dict: {timestamp_str: {...}}
    """
    if not HAS_TB:
        return {}

    if not os.path.isdir(log_root):
        return {}

    index_path = os.path.join(log_root, INDEX_FILENAME)

    # 尝试读缓存
    if not force and os.path.isfile(index_path):
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            if cached.get("_version") == 2:
                return cached.get("entries", {})
        except Exception:
            pass

    # 全量扫描
    names = sorted(n for n in os.listdir(log_root)
                   if os.path.isdir(os.path.join(log_root, n)))
    total = len(names)
    entries = {}

    for i, name in enumerate(names, 1):
        if on_progress:
            on_progress(i, total, name)

        dir_path = os.path.join(log_root, name)
        ev_file, ev_size = _find_latest_events_file(dir_path)

        # 时间戳解析
        ts_str = ""
        if len(name) == 14 and name.isdigit():
            try:
                ts_str = datetime.datetime.strptime(
                    name, "%Y%m%d%H%M%S").strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                ts_str = name

        if not ev_file:
            entries[name] = {
                "events_file": "",
                "size_kb": 0,
                "time_str": ts_str,
                "first_wall_time": 0,
                "has_loss": False,
                "reason": "no_events",
            }
            continue

        if ev_size > MAX_FILE_SIZE:
            entries[name] = {
                "events_file": ev_file,
                "size_kb": ev_size // 1024,
                "time_str": ts_str,
                "first_wall_time": 0,
                "has_loss": False,
                "reason": "too_large",
            }
            continue

        first_wall, has_loss, _ = _quick_peek_events(ev_file)

        entries[name] = {
            "events_file": ev_file,
            "size_kb": ev_size // 1024,
            "time_str": ts_str,
            "first_wall_time": first_wall or 0,
            "has_loss": has_loss,
            "reason": "" if has_loss else "no_loss",
        }

    # 写缓存
    try:
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump({"_version": 2, "entries": entries}, f,
                      ensure_ascii=False, indent=2)
    except Exception:
        pass

    return entries


def load_loss_curve(events_file, tag="loss/current"):
    """
    读取指定 events 文件的完整曲线（去重）。
    返回 [(step, value), ...]
    """
    if not events_file or not os.path.isfile(events_file):
        return []

    seen = {}
    try:
        loader = EventFileLoader(events_file)
        for event in loader.Load():
            if not event.HasField('summary'):
                continue
            for value in event.summary.value:
                if value.tag != tag:
                    continue
                v = _extract_value(value)
                if v is not None:
                    seen[event.step] = v
    except Exception:
        return []

    return sorted(seen.items())


def load_multi_curves(events_file):
    """一次读全部常用曲线"""
    result = {
        'loss/current': [],
        'loss/average': [],
        'loss/epoch': [],
        'lr/unet': [],
    }
    if not events_file or not os.path.isfile(events_file):
        return result

    buckets = {k: {} for k in result.keys()}
    try:
        loader = EventFileLoader(events_file)
        for event in loader.Load():
            if not event.HasField('summary'):
                continue
            for value in event.summary.value:
                if value.tag not in buckets:
                    continue
                v = _extract_value(value)
                if v is not None:
                    buckets[value.tag][event.step] = v
    except Exception:
        return result

    for k, d in buckets.items():
        result[k] = sorted(d.items())
    return result


def _loss_cache_key(events_file):
    """根据 events 文件路径 + mtime + size 生成缓存 key"""
    try:
        st = os.stat(events_file)
        mtime = int(st.st_mtime)
        size = st.st_size
    except Exception:
        mtime = 0
        size = 0
    try:
        abspath = os.path.abspath(events_file)
    except Exception:
        abspath = events_file
    s = f"{abspath}|{mtime}|{size}|v{CACHE_VERSION}"
    return hashlib.md5(s.encode('utf-8')).hexdigest()


def load_multi_curves_cached(events_file):
    """带磁盘缓存的 load_multi_curves（同一 events 文件只读一次）"""
    empty = {
        'loss/current': [],
        'loss/average': [],
        'loss/epoch': [],
        'lr/unet': [],
    }
    if not events_file or not os.path.isfile(events_file):
        return empty

    key = _loss_cache_key(events_file)
    cache_path = os.path.join(LOSS_CURVE_CACHE_DIR, key + ".json")

    # 1. 尝试读缓存
    if os.path.isfile(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            if cached.get("_version") == CACHE_VERSION:
                return cached.get("curves", empty)
        except Exception:
            pass

    # 2. 缓存未命中 → 读原始 events
    curves = load_multi_curves(events_file)

    # 3. 写缓存
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({
                "_version": CACHE_VERSION,
                "events_file": events_file,
                "curves": curves,
            }, f, ensure_ascii=False)
    except Exception:
        pass

    return curves


def loss_cache_size():
    """返回 (文件数, 总字节数)"""
    try:
        files = [f for f in os.listdir(LOSS_CURVE_CACHE_DIR)
                 if f.endswith(".json")]
    except Exception:
        return 0, 0

    total = 0
    for f in files:
        try:
            total += os.path.getsize(os.path.join(LOSS_CURVE_CACHE_DIR, f))
        except Exception:
            pass
    return len(files), total


def clear_loss_cache():
    """清空曲线缓存，返回 (删除文件数, 释放字节数)"""
    count = 0
    total = 0
    try:
        for f in os.listdir(LOSS_CURVE_CACHE_DIR):
            fp = os.path.join(LOSS_CURVE_CACHE_DIR, f)
            try:
                total += os.path.getsize(fp)
                os.remove(fp)
                count += 1
            except Exception:
                pass
    except Exception:
        pass
    return count, total

def downsample(points, max_points=500):
    """
    降采样：保留首尾 + 均匀抽稀。
    画图用，避免几千个点让 matplotlib 卡。
    """
    if len(points) <= max_points:
        return points

    n = len(points)
    step = n / max_points
    out = []
    for i in range(max_points):
        idx = int(round(i * step))
        if idx >= n:
            idx = n - 1
        out.append(points[idx])

    # 保证最后一个点被包含
    if out[-1] != points[-1]:
        out.append(points[-1])

    return out


def match_lora_to_log(lora_group_mtime, log_entries, tolerance_seconds=600):
    """
    根据 LoRA 组的最早文件 mtime，找时间最接近的日志。
    返回 (log_name, entry_dict) 或 (None, None)
    """
    best_name = None
    best_diff = None

    for name, entry in log_entries.items():
        fw = entry.get("first_wall_time", 0)
        if not fw:
            continue
        diff = abs(fw - lora_group_mtime)
        if diff <= tolerance_seconds:
            if best_diff is None or diff < best_diff:
                best_diff = diff
                best_name = name

    if best_name:
        return best_name, log_entries[best_name]
    return None, None