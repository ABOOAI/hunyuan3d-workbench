# 混元 3D 网页工作台 CLI / MCP

**把参考图和模型交给本地命令，连续完成上传、生成提交、任务监控和成品下载。**

`hunyuan3d-workbench` 是面向腾讯混元 3D 网页工作台的独立工具，提供命令行和 stdio MCP 两种入口。它用常驻的本机 Chrome 执行网页操作，使用你自己的**网页登录与网页额度**，适合道具、角色和 VR 资产的重复生产流程。

当前版本：**0.2.1**。本项目不是腾讯官方 CLI，也不接入腾讯云混元 3D API；无需填写腾讯云 API 密钥。首次需要在工具打开的 Chrome 中登录，后续复用这份独立的浏览器配置。

[官方工作台](https://3d.hunyuan.tencent.com/) · [功能调研](RESEARCH.md) · [验收范围](VALIDATION.md) · [更新记录](CHANGELOG.md) · [版本下载](https://github.com/ABOOAI/hunyuan3d-workbench/releases)

维护发布版本时，同时更新 `pyproject.toml` 与 `hunyuan_workbench.py` 的版本号，再更新 [RELEASE_NOTES.md](RELEASE_NOTES.md)。将版本说明提交到 `main` 会触发测试、构建和 GitHub Release 发布；也可在 Actions 手动运行“构建并发布版本”。流程拒绝覆盖已经存在的版本。

## 适合解决什么问题

- **减少重复操作：** 一次本地执行完成选页面、传文件、填参数和提交，避免逐步让模型点浏览器。
- **批量处理输入：** 校验参考图和模型，保存输入副本与哈希，按参数和版本复用已登记任务。
- **本地持续监控：** 提交后由 worker 定时检查对应资产，完成后自动下载；不需要模型不断读取页面。
- **保留生成记录：** 保存任务参数、状态、原始下载和文件校验结果，额外导出格式单独保留。
- **衔接 Blender：** 生成独立的后台导入脚本，设置米制单位、目标高度和落地位置，保存 `.blend`。
- **接入智能体：** CLI 和 19 个 MCP 工具共用同一套任务账本和浏览器 worker。

它减少的是本地操作和模型调用开销。官网的生成排队、计算时间、可用功能和额度消耗仍由服务端决定。

```text
参考图 / 模型 + JSON 参数
          ↓
校验、复制、去重 → 本地任务账本
          ↓
常驻 Chrome：上传 → 设置 → 提交一次
          ↓
本地监控 → 匹配具体成品 → 官方菜单下载
          ↓
文件校验与归档 → Blender 后处理 → 项目资产库
```

## 当前功能覆盖

**八个 Studio 功能的代表性表单已经真实验证；几何生成和多视图纹理已完成真实生成、监控、下载。** “表单已验证”表示能完成对应页面的输入准备，不代表该功能的最终产物、所有参数和所有导出格式都已验收。

| 功能 | 当前可以调用的流程 | 验证程度 |
|---|---|---|
| 概念设计 | 文字生成表单、人物参考图生成多视图表单 | 代表性表单已验证；概念图生成与完整下载待验收 |
| 几何生成 | 单图、3–8 张多视图、V3.1、面数选择 | 三视图几何生成 → 监控 → 下载已验证 |
| 组件拆分 | 上传模型、准备预分割 | 表单已验证；预分割后的部件调整、确认与分件导出待完善 |
| 低模生成 | 上传模型、低/中/高档、三角面/四边面 | 表单已验证；最终拓扑和结果下载待验收 |
| UV 展开 | 上传模型、智能展开 UV | 表单已验证；UV 质量和产物下载待验收 |
| 纹理绘制 | 文字、单图、多视图；笔刷辅助入口 | 多视图纹理生成 → 自动下载 GLB 已验证；笔刷区域操作需人工 |
| 绑骨蒙皮 | 上传模型、准备自动绑骨 | 表单已验证；真实人物的骨骼、权重和变形质量待验收 |
| 动画生成 | 选择可见角色、匹配动作模板 | 表单已验证；实际动画生成和导出待验收 |
| 成品下载 | 按资产实际菜单选择格式、归档和校验 | GLB / STL / FBX 有真实成功记录；USDZ / MP4 / GIF 仅发现入口 |

**世界生成不在本项目范围内。** 普通首页的图/文生 3D、全景图、世界重建尚未接入当前 Studio 任务流程。详见 [调研与功能边界](RESEARCH.md)。

## 安装

运行环境：**Python 3.11+、已安装的 Google Chrome、可登录的混元 3D 网页账号**。当前生产流程在 Windows 上验证；其他操作系统尚未完成同等验收。Blender 仅在导入和后处理时需要。

### 从源码安装

在 PowerShell 中执行：

```powershell
git clone https://github.com/ABOOAI/hunyuan3d-workbench.git
cd hunyuan3d-workbench
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install .

$Workbench = (Resolve-Path .\.venv\Scripts\hunyuan-workbench.exe).Path
& $Workbench doctor
& $Workbench capabilities
```

开发时可将安装命令改为 `python -m pip install -e .`。

### 从发行包安装

从 [Releases](https://github.com/ABOOAI/hunyuan3d-workbench/releases) 下载 wheel，在自己的工具目录建立虚拟环境后安装：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .\hunyuan3d_workbench-0.2.1-py3-none-any.whl
$Workbench = (Resolve-Path .\.venv\Scripts\hunyuan-workbench.exe).Path
& $Workbench doctor
```

wheel 安装仍需获取 Python 依赖。Chrome 需要单独安装；发布包不包含浏览器、登录资料、生成素材或运行中的任务数据。后续示例沿用本节的 `$Workbench` 变量；若已激活虚拟环境，也可直接使用 `hunyuan-workbench`。

## 第一次生成三视图道具

### 1. 启动浏览器并登录

```powershell
& $Workbench web-start
```

在新打开的 Chrome 中完成混元 3D 登录。工具使用独立的持久浏览器配置，不自动继承其他 Chrome 窗口或内置浏览器的登录资料。登录、验证码等需要人工操作时，工具会报告需要处理。

### 2. 登记三张参考图

将自己的正面、右侧、背面图片放到当前目录的 `inputs/prop/` 下：

```powershell
& $Workbench prepare --name "陶罐" --front .\inputs\prop\front.png --right .\inputs\prop\right.png --back .\inputs\prop\back.png --faces 50000 --height 0.34
```

返回 JSON 中的 `id` 是本地任务号。把后续命令中的 `JOB_ID` 替换成它。此步只校验并保存本地输入，不上传、不生成。

多视图预设要求 **3–8 张、必须含正面、不同方向不能使用完全相同的文件**。支持 PNG/JPEG/WEBP，每边 128–4096 像素，每张不超过 10 MiB。这些是当前工具的输入预设；例如“三图起步”比当时网页的最少两图要求更严格。

### 3. 上传、生成、自动下载

```powershell
& $Workbench web-run JOB_ID --submit --wait 15
& $Workbench status JOB_ID
& $Workbench watches
```

**`--submit` 会点击官网生成，可能消耗网页额度，并自动开启完成后下载。** 只想检查上传后的表单时，先运行 `web-run JOB_ID`，检查后再运行 `submit JOB_ID`。

`--wait` 表示 CLI 等待这次本地请求的秒数，上限 60 秒，**不是服务端生成超时**。命令返回 `request_id` 时，本地执行还可能继续；用 `web-poll REQUEST_ID` 获取这次执行结果。生成状态由 worker 后台检查，无需不断调用 `web-inspect`。

`status JOB_ID` 读取本地记录；需要主动刷新官网状态时：

```powershell
& $Workbench status JOB_ID --refresh --wait 10
& $Workbench download JOB_ID --format auto --wait 15
```

重复下载同一格式会先核对文件哈希，再复用已归档文件。请求另一种可用格式会保留额外导出，不覆盖原始成品。

## 用 JSON 调用不同功能

```powershell
& $Workbench prepare-spec .\examples\multiview-geometry.json
& $Workbench web-run JOB_ID --submit
```

示例只包含参数，**不附带参考图和模型**。修改路径或准备自己的输入后再执行。JSON 内的相对路径按命令的**当前工作目录**解析，不按 JSON 所在目录解析。

| 字段 / 功能 | 参数约定 |
|---|---|
| 通用字段 | `feature`、`name` 必填；`revision` 默认 `v001`；`height_m` 为可选目标米制高度 |
| `concept` | `mode: text` + `prompt`，或 `mode: multiview` + `image`；可选 `a_pose`；图生多视图限人物 |
| `geometry` | `mode: single` + `image`，或 `mode: multiview` + `views`；`face_count`: 50000 / 500000 / 1000000 / 1500000 |
| `components` | `mode: presegment` + `model` |
| `retopology` | `mode: retopology` + `model`；`level`: low / medium / high；`polygon`: triangle / quad |
| `uv` | `mode: unwrap` + `model` |
| `texture` | `model` + `mode: text` / `image` / `multiview`，分别搭配 `prompt` / `image` / `views`；`brush` 仅辅助入口 |
| `rig` | `mode: auto` + `model`；GLB 声明三角面数超过 500000 时先拦截 |
| `animation` | `mode: template` + `character` + `motion`；前者是角色选择器中的实际 HTTPS 缩略图 URL，后者是准确的可见动作名 |

文字模式的 `prompt` 为 1–150 字。`views` 支持 `front`、`right`、`back`、`left`、`top`、`bottom`、`left_front`、`right_front`。模型通常接受 GLB/FBX/OBJ，组件拆分额外接受 STL；带外部材质的 OBJ 需先打包为 GLB，以免漏传依赖。

自定义角色应先完成绑骨，再从动画页面的角色选择器选取；该页面没有直接上传本地模型的入口。动作名称出现歧义时工具会停止，不会任意选取。

可用示例：[三视图几何](examples/multiview-geometry.json)、[三视图纹理](examples/multiview-texture.json)、[低模](examples/retopology.json)、[绑骨](examples/rig.json)、[批量道具](examples/batch-props.json)。

```powershell
# 默认只登记本地任务；每批 1–8 份描述。
& $Workbench batch .\examples\batch-props.json

# 明确提交时需要 worker 已启动，并会使用官网额度。
& $Workbench batch .\examples\batch-props.json --submit
```

相同输入、参数和版本会复用本地任务，防止误重复提交。确实要生成新版本时修改 `revision`。批量命令用于登记和提交任务，不是具备上下游依赖的流水线：例如纹理任务需要先取得几何文件，再单独准备。

## 监控、异常和恢复

```powershell
& $Workbench watch JOB_ID --interval 20 --format auto
& $Workbench watch JOB_ID --no-download
& $Workbench watch JOB_ID --stop
& $Workbench assets JOB_ID --wait 10
& $Workbench doctor
```

检查间隔接受 5–300 秒，默认 20 秒，异常时会退避。停止监控不会取消官网生成。保持电脑运行及 worker 存活才能持续监控和下载；它不是 Windows 系统服务，关机或退出 worker 后不会自行继续执行。

任务状态通常为：

```text
PREPARED → UPLOADING → READY → SUBMITTING
                                    ↓
                         SUBMITTED / RUNNING
                                    ↓
                         SUCCEEDED → DOWNLOADED
```

提交结果不确定时记录 `UNCERTAIN`；只有对应官网卡片明确报告失败，才记为 `FAILED`。浏览器超时不能直接证明任务生成失败。已提交或不确定的任务不会自动重发。

当前页面资产卡不提供可直接读取的稳定官网任务号。生成时工具绑定这次提交后唯一新增的卡片元素，完成后保存唯一缩略图身份。如果浏览器在稳定身份形成前中断，工具会停止该任务的监控并报告 `TASK_IDENTITY_REQUIRED`，需要核对成品。

确认某张**已完成且当前选中的**卡片确实属于该任务后，可使用 `assets` 返回的缩略图地址恢复绑定：

```powershell
& $Workbench recover JOB_ID --thumbnail "已核对的完整缩略图URL" --evidence "参考图、提交时间和结果外观的核对依据" --wait 10
& $Workbench watch JOB_ID
```

不要把第一个卡片或相似缩略图当成恢复依据。未提交的 `READY` 表单若被修改或浏览器重启，需要重新 `web-run` 准备；出现页面改版或控件不匹配时，用 `web-inspect --job-id JOB_ID` 辅助诊断。

## 下载、数据目录与 Blender

`auto` 只从该资产实际提供的格式中选择。几何优先 GLB、其次 STL；纹理、绑骨和动画流程优先 GLB、其次 FBX。显式请求不可用格式时会报告可用项，不会生成一个虚假的成功结果。

Windows 默认数据目录为 `%LOCALAPPDATA%\hunyuan-workbench`。使用全局参数 `--root` 或环境变量 `HUNYUAN_WORKBENCH_ROOT` 可指定其他位置：

```powershell
# --root 放在子命令之前；同一组任务的后续调用使用同一个目录。
& $Workbench --root .\local-data doctor

# 或在当前 PowerShell 会话统一设置；MCP 可在宿主配置的 env 中设置。
$env:HUNYUAN_WORKBENCH_ROOT = Join-Path $env:LOCALAPPDATA 'hunyuan-workbench'
```

```text
数据目录/
  jobs.sqlite3                 任务账本与状态事件
  jobs/JOB_ID/manifest.json     输入信息和参数
  jobs/JOB_ID/references/       输入副本
  jobs/JOB_ID/browser/          页面证据和结果身份
  jobs/JOB_ID/output/           下载原件、校验报告、额外格式、Blender 脚本
  watches/                     监控配置及结果
  queue/                       本地执行请求和结果
  chrome-profile/              持久浏览器配置，包括登录资料
```

**不要把数据目录提交到 GitHub。** 它可能包含登录状态、作品、参考图、账号相关页面和临时下载地址。分享问题记录前请先脱敏；仓库和发行包仅包含工具源代码、文档、示例参数及离线测试。

完成下载后：

```powershell
& $Workbench inspect-asset .\my-model.glb
& $Workbench blender-script JOB_ID

# 替换成自己的 Blender 程序，以及上一条命令返回的脚本绝对路径。
& 'C:\Path\To\Blender\blender.exe' --background --factory-startup --python 'C:\Path\To\import_in_background.py'
```

该脚本会清空它所在进程的场景，必须在**独立后台 Blender 进程**运行。它导入并保留模型层级、按目标高度缩放、落地、打包资源并保存 `.blend`；不负责自动减面、修复拓扑或生成 Unity 交互。GLB/FBX 轴信息由导入器处理，仍需逐个检查朝向、比例和材质。

文件检查覆盖容器、签名、压缩包完整性及声明信息，不等同于视觉、拓扑、骨骼或 VR 性能验收。进入 Unity 前仍需检查材质、面数、贴图大小、LOD、碰撞和角色变形。

## MCP 接入

安装包提供 `hunyuan-workbench-mcp` 和 `hunyuan-workbench mcp` 两种 stdio 启动方式。[mcp-config.example.json](mcp-config.example.json) 是通用示例：

```json
{
  "mcpServers": {
    "hunyuan-workbench": {
      "command": "hunyuan-workbench-mcp",
      "args": []
    }
  }
}
```

宿主需要能够从 PATH 找到这个命令。使用虚拟环境安装时，通常应把 `command` 改为该环境中 `Scripts/hunyuan-workbench-mcp.exe` 的**绝对路径**。不同宿主的配置格式不同，按其 MCP 配置入口填写；复制样例文件不等于宿主已注册或加载服务。

| 工具分组 | MCP 工具 |
|---|---|
| 能力与诊断 | `workbench_capabilities`、`workbench_doctor` |
| 本地任务 | `workbench_prepare`、`workbench_prepare_feature`、`workbench_list`、`workbench_get` |
| 浏览器与提交 | `workbench_browser_start`、`workbench_browser_run`、`workbench_submit` |
| 监控 | `workbench_status`、`workbench_watch`、`workbench_watches` |
| 成品与恢复 | `workbench_download`、`workbench_assets`、`workbench_recover` |
| 排错 | `workbench_browser_inspect`、`workbench_browser_result` |
| 本地导入 | `workbench_ingest`、`workbench_blender_script` |

智能体应先读能力状态、准备任务，再按用户授权提交。`workbench_browser_run(submit=True)` 和 `workbench_submit` 都可能消耗网页额度；不要重发处于 `SUBMITTING`、`UNCERTAIN` 或 `RUNNING` 的任务。

## 开发、验证和限制

在源码目录及已安装依赖的环境中运行：

```powershell
.\.venv\Scripts\python.exe -m unittest test_workbench test_lifecycle -v
.\.venv\Scripts\python.exe smoke_mcp.py
```

发布准备中的 **27 项离线测试通过**，MCP 初始化、19 个工具枚举和能力查询通过。离线浏览器测试会启动本机 Chrome，但拦截页面请求，不访问官网、不消耗生成额度。真实生成记录、离线测试覆盖及未完成项见 [VALIDATION.md](VALIDATION.md)。

这是依赖可见网页结构的适配器。官网改版、登录失效、导出故障或资产尚未加载，都可能需要恢复或更新适配器。曾观察到 FBX 导出时 Chrome 崩溃；恢复同一成品后导出成功，但这不是所有导出故障已解决的保证。

项目公开可见，代码许可证尚未指定。第三方依赖与混元服务分别遵循各自条款。
