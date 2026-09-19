# -*- coding: utf-8 -*-
# LoRA 前后期工具箱
# 作者：翡翠珍珠排骨 (B站 UID: 3923028)
# 主页：https://space.bilibili.com/3923028
# 协议：MIT License
"""
公共文件操作工具
- open_path: 用系统默认程序打开文件/文件夹
- reveal_path: 在资源管理器里定位到文件
- copy_text: 复制文本到剪贴板
"""
import os
import sys
import subprocess


def open_path(path):
    """用系统默认程序打开文件或文件夹"""
    try:
        if sys.platform.startswith('win'):
            os.startfile(path)
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', path])
        else:
            subprocess.Popen(['xdg-open', path])
    except Exception:
        pass


def reveal_path(path):
    """在文件资源管理器里定位到该文件"""
    try:
        if sys.platform.startswith('win'):
            subprocess.Popen(
                ['explorer', '/select,', os.path.normpath(path)])
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', '-R', path])
        else:
            subprocess.Popen(['xdg-open', os.path.dirname(path)])
    except Exception:
        pass


def copy_text(root, text):
    """复制文本到剪贴板"""
    try:
        root.clipboard_clear()
        root.clipboard_append(text)
    except Exception:
        pass