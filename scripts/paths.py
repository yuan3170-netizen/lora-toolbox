# -*- coding: utf-8 -*-
# LoRA 前后期工具箱
# 作者：翡翠珍珠排骨 (B站 UID: 3923028)
# 主页：https://space.bilibili.com/3923028
# 协议：MIT License
"""
路径配置 —— 所有路径都相对于包根目录

包结构：
  包根\
  ├── python\      便携 Python
  ├── scripts\     脚本（本文件所在）
  ├── models\      模型
  ├── config\      配置
  └── 启动.bat
"""
import os

# 本文件在 scripts\ 里，上一级是包根
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 便携 Python
PYTHON_EXE = os.path.join(BASE_DIR, "python", "python.exe")
PYTHON_DIR = os.path.join(BASE_DIR, "python")

# 模型目录
WD_MODEL_DIR = os.path.join(BASE_DIR, "models", "wd-eva02-large-tagger-v3")

# 配置目录
CONFIG_DIR = os.path.join(BASE_DIR, "config")
LORA_CONFIG_DIR = os.path.join(CONFIG_DIR, ".lora_manager")
LORA_DB_FILE = os.path.join(LORA_CONFIG_DIR, "db.json")
LORA_TOOL_CFG = os.path.join(CONFIG_DIR, ".lora_tool_config.json")
LOG_ROOT_CFG = os.path.join(CONFIG_DIR, "log_root.txt")
THUMB_CACHE_DIR = os.path.join(CONFIG_DIR, ".thumb_cache")
LOSS_CURVE_CACHE_DIR = os.path.join(CONFIG_DIR, ".loss_curve_cache")

# 首次运行自动建目录
for d in (CONFIG_DIR, LORA_CONFIG_DIR, THUMB_CACHE_DIR, LOSS_CURVE_CACHE_DIR):
    os.makedirs(d, exist_ok=True)


def get_log_root():
    """从配置文件读 Loss 日志根目录，未设置返回空字符串"""
    try:
        if os.path.isfile(LOG_ROOT_CFG):
            with open(LOG_ROOT_CFG, "r", encoding="utf-8") as f:
                return f.read().strip()
    except Exception:
        pass
    return ""


def set_log_root(path):
    """写入 Loss 日志根目录"""
    try:
        with open(LOG_ROOT_CFG, "w", encoding="utf-8") as f:
            f.write(path or "")
        return True
    except Exception:
        return False