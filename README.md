# comfyui-saveimage-webdav

一个 ComfyUI 自定义节点：**出图后直接上传到 WebDAV，不在 `output/` 里留文件**。

## 它解决什么

ComfyUI 内置的 `SaveImage` 一定会把图写到 `output/`，导致磁盘上堆图。这个节点：

1. 把图写到 ComfyUI 的 **`temp/`** 目录（只为让界面预览能显示），**完全不碰 `output/`**；
2. 立即用 `PUT` 上传到 WebDAV，按日期自动分目录，例如 `/Aimg/2026-11-07/anima_00001_.png`；
3. 上传成功后（默认 60 秒后）删除 temp 文件，磁盘基本零残留；
4. 上传失败则**保留** temp 文件，不会丢图。

## 安装

### 方式一：手动拷贝（推荐）

把整个 `comfyui-saveimage-webdav` 文件夹放进：

```
ComfyUI/custom_nodes/comfyui-saveimage-webdav/
```

重启 ComfyUI。节点出现在右键菜单 **image/webdav → 保存图像到 WebDAV (不落 output)**。

### 方式二：ComfyUI-Manager

Manager → Install Custom Nodes → Install via URL，粘贴本仓库地址：

```
https://github.com/seiya-ouo/comfyui-saveimage-webdav
```

## 用法

把工作流里原来的 `保存图像`（SaveImage）替换成 `保存图像到 WebDAV`，参数：

| 参数 | 说明 |
|---|---|
| `images` | 接 `VAE解码` 的 IMAGE 输出 |
| `filename_prefix` | 文件名前缀，默认 `anima`，最终形如 `anima_ab12cd_00001_.png` |
| `webdav_url` | WebDAV 根地址，如 `https://pan.seiya.ink/dav` |
| `username` / `password` | WebDAV 账号（需有写权限） |
| `root_path` | 远端根目录，如 `/Aimg` |
| `date_format` | 日期目录格式，`strftime` 语法；`%Y-%m-%d` → `2026-11-07`，`%Y/%m/%d` → 多级目录 |
| `cleanup_after_upload` | 上传成功后是否删除本地 temp 文件（默认开） |
| `cleanup_delay_sec` | 删除延迟秒数（默认 60，留时间让界面预览） |

输出：透传 IMAGE，可继续接放大/后处理节点。

## 把账号密码从工作流里挪出去（可选）

如果不想让密码出现在工作流 JSON 里，在下面位置放一个配置文件：

```
ComfyUI/user/default/webdav_save.json
```

内容（存在时**覆盖**节点上的同名参数）：

```json
{
  "url": "https://pan.seiya.ink/dav",
  "username": "seiya",
  "password": "********",
  "root": "/Aimg",
  "date_format": "%Y-%m-%d",
  "cleanup_after_upload": true,
  "cleanup_delay_sec": 60
}
```

这样工作流里可以只留占位值，分享工作流也不泄露密码。

## 行为细节

- 上传失败会在节点 UI 上显示 `上传失败：...`，并在 ComfyUI 控制台打印原因；temp 文件保留以便重试；
- 目录不存在会自动 `MKCOL`（逐级创建，本进程内缓存，不重复请求）；
- HTTPS 连接在节点实例内复用，减少 TLS 握手开销；
- 打印的日志前缀统一为 `[SaveImageWebDAV]`，方便排查；
- 只依赖 Python 标准库 + ComfyUI 自带的 Pillow/numpy。

## 兼容性

在 ComfyUI 0.44（前端 1.58）上开发，使用经典 `NODE_CLASS_MAPPINGS` 接口，向前兼容较老版本。

## License

MIT
