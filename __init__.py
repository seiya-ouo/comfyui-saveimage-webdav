# -*- coding: utf-8 -*-
"""SaveImageWebDAV —— 出图后直接传到 WebDAV，不在 output 里留文件。

与内置 SaveImage 的区别：
  1. 图片写到 ComfyUI 的 **temp** 目录（仅供界面预览），**不写 output**；
  2. 立即 PUT 到 WebDAV，路径按日期分目录，例如 /Aimg/2026-11-07/xxx.png；
  3. 上传成功后（可选）延迟删除 temp 文件，磁盘上不残留。

依赖：仅标准库 + ComfyUI 自带依赖（Pillow / numpy）。
"""

from __future__ import annotations

import json
import os
import random
import string
import threading
from datetime import datetime

import numpy as np
from PIL import Image
from PIL.PngImagePlugin import PngInfo

import folder_paths

try:  # 作为包被 ComfyUI 加载
    from .webdav_client import WebDAV, WebDAVError
except ImportError:  # 作为独立脚本/测试导入
    from webdav_client import WebDAV, WebDAVError

NODE_NAME = "SaveImageWebDAV"
CONFIG_FILE = "webdav_save.json"   # 放在 ComfyUI/user/default/ 下可覆盖节点上的账号密码


def _load_config_override() -> dict:
    """可选：user/default/webdav_save.json 覆盖节点参数（避免账号密码出现在工作流里）。"""
    try:
        p = os.path.join(folder_paths.get_user_directory(), "default", CONFIG_FILE)
        if os.path.isfile(p):
            with open(p, "r", encoding="utf-8") as fh:
                return json.load(fh) or {}
    except Exception:
        pass
    return {}


def _dict_to_pnginfo(info: dict) -> PngInfo:
    meta = PngInfo()
    for k, v in info.items():
        meta.add_text(k, v if isinstance(v, str) else json.dumps(v, ensure_ascii=False))
    return meta


def _schedule_delete(path: str, delay: int):
    def _job():
        try:
            if os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass

    if delay <= 0:
        _job()
    else:
        t = threading.Timer(delay, _job)
        t.daemon = True
        t.start()


class SaveImageWebDAV:
    def __init__(self):
        self.temp_dir = folder_paths.get_temp_directory()
        self.type = "temp"
        self.prefix_append = "_" + "".join(random.choice(string.ascii_letters) for _ in range(6))
        self._used_remote: set[str] = set()   # 进程内已用过的远端路径，防同秒覆盖

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "filename_prefix": ("STRING", {"default": "anima"}),
                "webdav_url": ("STRING", {"default": "https://pan.seiya.ink/dav"}),
                "username": ("STRING", {"default": "seiya"}),
                "password": ("STRING", {"default": ""}),
                "root_path": ("STRING", {"default": "/Aimg"}),
                "date_format": ("STRING", {"default": "%Y-%m-%d"}),
                "cleanup_after_upload": ("BOOLEAN", {"default": True}),
                "cleanup_delay_sec": ("INT", {"default": 60, "min": 0, "max": 3600, "step": 5}),
            },
            "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"},
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    FUNCTION = "save_and_upload"
    OUTPUT_NODE = True
    CATEGORY = "image/webdav"
    DESCRIPTION = ("出图直接上传 WebDAV（按日期分目录），本地只写 temp 供界面预览，"
                   "不在 output 留文件。")

    def save_and_upload(self, images, filename_prefix, webdav_url, username, password,
                        root_path, date_format, cleanup_after_upload, cleanup_delay_sec,
                        prompt=None, extra_pnginfo=None):
        override = _load_config_override()
        webdav_url = override.get("url", webdav_url) or webdav_url
        username = override.get("username", username) or username
        password = override.get("password", password) or password
        root_path = override.get("root", root_path) or root_path
        date_format = override.get("date_format", date_format) or date_format
        cleanup_after_upload = bool(override.get("cleanup_after_upload", cleanup_after_upload))
        cleanup_delay_sec = int(override.get("cleanup_delay_sec", cleanup_delay_sec))

        results = []
        errors = []
        day = datetime.now().strftime(date_format)
        remote_dir = "/" + "/".join(x.strip("/") for x in (root_path, day) if x and x.strip("/"))

        dav = WebDAV(webdav_url, username, password)
        try:
            dav.ensure_dir(remote_dir)
        except WebDAVError as e:
            errors.append(f"创建远端目录失败：{e}")

        for image in images:
            # 1) 写入 temp（仅预览，不进 output）
            arr = (image.cpu().numpy() * 255.0).clip(0, 255).astype(np.uint8)
            pil = Image.fromarray(arr)
            meta = _dict_to_pnginfo({"prompt": prompt or {}, "workflow": extra_pnginfo or {}})
            full_dir, name, counter, subfolder, _ = folder_paths.get_save_image_path(
                filename_prefix + self.prefix_append, self.temp_dir, pil.width, pil.height)
            os.makedirs(full_dir, exist_ok=True)
            file_name = f"{name}_{counter:05}_.png"
            local_path = os.path.join(full_dir, file_name)
            pil.save(local_path, pnginfo=meta, compress_level=4)

            # 2) 上传 WebDAV
            # 远端文件名带时间戳：temp 文件被清理后本地计数器会重置，
            # 若沿用原名会覆盖上一张图，这里保证每次运行都是新文件。
            stem, suffix = os.path.splitext(file_name)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            remote_name = f"{stem}_{ts}{suffix}"
            n = 2
            while f"{remote_dir}/{remote_name}" in self._used_remote:
                remote_name = f"{stem}_{ts}_{n}{suffix}"
                n += 1
            self._used_remote.add(f"{remote_dir}/{remote_name}")
            remote_path = f"{remote_dir}/{remote_name}"
            uploaded = False
            try:
                status = dav.put_file(remote_path, local_path, content_type="image/png")
                uploaded = True
                print(f"[SaveImageWebDAV] 上传成功 [{status}] {remote_path}")
            except WebDAVError as e:
                errors.append(f"{file_name} 上传失败：{e}")
                print(f"[SaveImageWebDAV] 上传失败 {file_name}: {e}")

            # 3) 仅在上传成功后清理本地 temp
            if uploaded and cleanup_after_upload:
                _schedule_delete(local_path, cleanup_delay_sec)

            results.append({"filename": file_name, "subfolder": subfolder, "type": self.type})
            print(f"[SaveImageWebDAV] 本地 temp：{local_path}  "
                  f"(是否清理={uploaded and cleanup_after_upload})")

        dav.close()
        ui = {"images": results}
        if errors:
            ui["text"] = ["上传失败：" + e for e in errors]
        return {"ui": ui, "result": (images,)}


NODE_CLASS_MAPPINGS = {NODE_NAME: SaveImageWebDAV}
NODE_DISPLAY_NAME_MAPPINGS = {NODE_NAME: "保存图像到 WebDAV (不落 output)"}
