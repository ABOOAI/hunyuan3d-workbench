# v0.2.1 · 混元 3D 网页工作台 CLI / MCP

首个公开打包版本。使用自己的网页登录与网页额度，让本地常驻 Chrome 连续完成上传、生成提交、任务监控和成品下载。

## 包含内容

- CLI 与 19 个 stdio MCP 工具，共用本地任务账本。
- 三视图输入、JSON 功能描述、批量登记、去重和一次提交保护。
- 后台监控、完成后自动下载、文件校验、额外格式归档和明确的异常恢复。
- Blender 独立后台导入脚本。
- 中文 README、八项 Studio 功能调研、验证说明和五份 JSON 示例。
- 安装路径修复：状态存入用户数据目录；首次下载自动建立元数据目录。

## 下载与安装

推荐下载 `hunyuan3d_workbench-0.2.1-py3-none-any.whl`，在 Python 3.11+ 虚拟环境中执行：

```powershell
python -m pip install .\hunyuan3d_workbench-0.2.1-py3-none-any.whl
hunyuan-workbench doctor
hunyuan-workbench web-start
```

需要本机安装 Google Chrome。首次在工具打开的浏览器中登录混元 3D。源码 ZIP / tar.gz 用于查看和修改代码；`SHA256SUMS.txt` 用于检查三个安装/源码文件的完整性。

## 验证与边界

已在独立虚拟环境中验证 wheel 安装、27 项离线测试和 MCP 19 个工具。三视图几何与多视图纹理有真实生成到下载记录；GLB、STL、FBX 有真实导出记录。其余功能以代表性表单验证为主，不代表全站全部功能端到端完成；详情见仓库 `VALIDATION.md`。世界生成不在范围内。

本项目为独立的非官方工具。当前验证平台为 Windows，不包含 Chrome、登录资料、任务记录、生成素材或腾讯云 API 密钥。网页改版可能需要调整适配器。
