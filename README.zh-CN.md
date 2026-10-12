# QuickCrop OCR

[English](README.md) | **简体中文**

QuickCrop OCR 是一款轻量级 Windows 桌面工具，可以识别屏幕截图选区中的文字并复制到剪贴板。

按下全局快捷键，拖动框选文字区域，识别结果便会自动复制，方便直接粘贴使用。

[项目演进：三个主要迭代阶段](#三个主要迭代阶段)

## 功能

- 全局快捷键：`Ctrl+Shift+X`
- 先冻结屏幕画面，再拖动框选
- 仅上传实际框选的截图区域
- 通过阿里云百炼 / DashScope 调用 Qwen 视觉模型进行 OCR
- 支持中文、英文、混合文本、软件界面截图和字幕识别
- 三种文本排版：保留原排版、单行文本、自然段文本
- 分步式命令行设置，支持返回修改和启动前确认
- 自动复制到剪贴板
- 持续显示识别进度、耗时和重试状态，支持取消
- 剪贴板备份与恢复，以及再次复制按钮
- 不复制被截断或被模型拒绝的回答
- 不永久保存截图

## Qwen OCR

QuickCrop OCR 仅使用 Qwen 视觉模型，不提供其他服务商选项，也不会自动切换到其他服务商。

OCR 需要联网，并使用 Qwen / DashScope API key。请求会将框选区域发送到所选地域的 Qwen 服务，可能产生 API 费用。

Qwen 的[视觉理解文档](https://www.alibabacloud.com/help/en/model-studio/vision/)介绍了如何向 DashScope 多模态生成接口传入图片 URL 或 Base64 图片数据。

## 环境要求

- Windows
- Python 3.10 或更高版本
- 在所选地域具有相应视觉模型调用权限的 Qwen / DashScope API key

本项目不使用，也不需要安装或配置 Tesseract、OpenAI 或 Gemini。**命令窗菜单和提示保持英文**，本文提供对应的中文说明。

## 安装

克隆 [JayJle/quickcrop-ocr](https://github.com/JayJle/quickcrop-ocr)，然后安装 Python 依赖。**请根据你使用的终端选择命令，不要混用路径写法。**

- **PowerShell**：提示符通常以 `PS` 开头，例如 `PS C:\quickcrop-ocr>`。
- **命令提示符（CMD）**：提示符通常类似 `C:\quickcrop-ocr>`。
- **Git Bash**：提示符中通常有 `MINGW64` 或 `MINGW32`，输入命令前显示 `$`。请使用正斜杠 `/`，不要照抄 PowerShell/CMD 示例中未加引号的反斜杠 `\`。

只复制命令本身，不要复制提示符中的 `$`、`>` 或 `(base)`。以下示例使用的是 Windows Python，不是 WSL/Linux Python。

### PowerShell / 命令提示符（CMD）

```powershell
git clone https://github.com/JayJle/quickcrop-ocr.git
cd quickcrop-ocr
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### Git Bash

```bash
git clone https://github.com/JayJle/quickcrop-ocr.git
cd quickcrop-ocr
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt
```

如果已经克隆了仓库，请进入项目目录，跳过 `git clone` 和 `cd quickcrop-ocr`。如果此前已经成功创建 `.venv`，也可以跳过 `python -m venv .venv`。两套命令都直接使用虚拟环境中的 Python，无需激活环境；即使提示符中显示 `(base)`，也可以直接运行。

## 启动

在克隆得到的项目目录中，根据终端选择对应命令。

**PowerShell / 命令提示符（CMD）：**

```powershell
.\.venv\Scripts\python.exe -m quickcrop_ocr
```

**Git Bash：**

```bash
./.venv/Scripts/python.exe -m quickcrop_ocr
```

如果已在当前 Python 或 Conda 环境中安装依赖，也可以运行 `python -m quickcrop_ocr`。

每次启动，命令窗都会依次询问四项设置。实际界面如下：

```text
QuickCrop OCR | Qwen
--------------------
Enter keeps the shown setting. B goes back. Q quits.
Settings apply to this run only; nothing is saved.

[1/4] API key
Qwen/DashScope API key (visible, not saved; Q quits):

[2/4] Vision model
Qwen vision model [qwen3-vl-plus] (B back, Q quit):

[3/4] Key region
Use the region where this API key was created.
  1. China / Beijing [Enter]
  2. International / Singapore

Choose 1-2 [1] (B back, Q quit):

[4/4] Text layout
  1. Preserve image layout
     Keep original line breaks, paragraphs, lists, and indentation.
  2. Single line [Enter]
     Merge all lines into one line of text.
  3. Natural paragraphs
     Merge wrapped lines; keep separate paragraphs and list items.

Choose 1-3 [2] (B back, Q quit):

Ready to start
--------------
1. API key     : Entered (not checked online)
2. Vision model: qwen3-vl-plus
3. Key region  : China / Beijing
4. Text layout : Single line
Punctuation: preserved in every layout.

Enter to start | 1-4 to edit | B to go back | Q to quit:
```

四项设置分别是：API key、视觉模型、密钥所属地域、文本排版。

API key 在输入或粘贴时可见，程序不会保存它。确认页不会重复显示密钥，但最初输入的内容可能仍留在终端滚动记录中。设置过程中不会发送网络请求，也不会向 Qwen 验证密钥是否有效。

输入密钥后，在后续各项提示和最后的确认页直接按回车，即可使用默认配置：**`qwen3-vl-plus`、北京、单行文本**。每次重新启动都会重新询问设置和密钥。

- 设置时输入 `B`，返回上一步。当前这次运行中已经选择的值会保留。
- 在确认页输入 `1` 至 `4`，只修改对应设置，修改后回到确认页。在确认页输入 `B` 会重新打开文本排版选项；修改某项时输入 `B` 则放弃此次修改，回到确认页。
- 再次进入 API key 输入步骤时，直接回车可保留本次已经输入的密钥。新启动程序时仍必须输入密钥。
- 输入 `Q` 或按 `Ctrl+C`，退出设置而不启动 OCR。输入无效时只会重新询问当前项，不会重复输出整组选项。

运行期间请保持命令窗打开。日志通过 `[Ready]`、`[OCR]`、`[Busy]`、`[Status]`、`[Error]` 区分就绪、识别、忙碌、一般状态和错误。在命令窗按 `Ctrl+C` 退出程序；只想取消当前识别时，请点击状态窗口中的 **Cancel**。

## 使用方法

1. 按 `Ctrl+Shift+X`，在本地冻结当前桌面画面。
2. 在冻结画面上拖动，框选需要识别的文字。
3. 松开鼠标，开始识别。
4. 识别并复制成功后，使用 `Ctrl+V` 粘贴结果。

框选过程中按 `Esc` 可取消。

OCR 运行期间，进度窗口会持续显示耗时和重试状态。点击 **Cancel** 会停止等待，并阻止迟到的结果写入剪贴板。处理中再次按 `Ctrl+Shift+X`，会重新显示进度窗口，而不是开始新的截图。

识别后，点击 **Copy again** 可再次复制最近一次成功识别的结果，不会重新调用 API。结果仅保留在内存中，直到被新的成功结果替换或程序退出。关闭状态窗口只会隐藏窗口，下次操作时会再次显示。

## 请求安全与重试

- 框选完成后，OCR 任务具有 **30 秒的总时间预算**。每次套接字操作的超时上限为 20 秒，或当前剩余时间，取两者中的较小值。
- 网络故障以及 HTTP 408、429、500、502、503、504 错误会在同一时间预算内重试，最多共尝试三次。程序遵守服务端的 `Retry-After` 等待时间，但不会因此延长总预算。认证错误不会重试。
- 取消或超时后，会丢弃迟到的结果并停止后续重试。已经发送给 Qwen 的请求仍可能完成并产生费用。阻塞的网络操作可能继续在后台等待结束；新请求会等待前一次网络操作释放资源，等待过程也计入新任务自己的时间预算，并显示状态。
- 仅接受已完成的 Qwen 回答。回答被截断、被拒绝、格式错误或内容为空时，会显示相应错误，不会直接复制，也不会误报为图片中没有文字。只有明确返回 `[NO_TEXT_DETECTED]` 时，才按未检测到可读文字处理。

完成状态检查依据 [DashScope 响应格式](https://help.aliyun.com/en/model-studio/qwen-api-via-dashscope)。它能检测 API 报告的输出截断，但不能发现正常完成的回答中所有的识别错误或遗漏。

## 剪贴板保护

替换剪贴板内容前，程序会先为新文本分配内存、锁定剪贴板，并尝试备份能够读取的格式。内存分配或锁定失败时，不会修改剪贴板。无法读取、不支持或无法复制备份的格式会被跳过，不再阻止正常复制。复制成功后，OCR 文本会替换原有剪贴板内容。

如果新内容写入失败，程序会在仍持有锁的情况下尝试恢复已有备份。恢复只能**尽力而为**：被跳过的格式无法恢复，Windows 也可能拒绝恢复写入。恢复不完整时会明确报告，不会误报为全部恢复成功。临时复制故障最多共尝试三次，但恢复不完整时不会自动重试。复制失败后，OCR 结果仍保留在内存中，供 **Copy again** 再次复制。

## 设置说明

Qwen 模型：

- 默认：`qwen3-vl-plus`。
- 可以输入所选地域中、当前密钥有权调用的其他 Qwen 视觉模型。纯文本模型无法处理截图。

Qwen 地域：

- `China / Beijing`：中国北京，使用 `https://dashscope.aliyuncs.com`。
- `International / Singapore`：国际新加坡，使用 `https://dashscope-intl.aliyuncs.com`。

请选择创建 Qwen / DashScope API key 时对应的地域。即使密钥本身正确，发送到错误地域的接口也可能被判定为无效。

文本排版，三种模式都保留标点：

- `preserve` / **Preserve image layout（保留原排版）**：要求 Qwen 保留图片中的换行、段落、列表、代码缩进和表格行。复制返回文本时不裁掉首尾空白。输出仍是纯文本，不会还原字体、颜色或精确像素位置。
- `single_line` / **Single line（单行文本，默认）**：使用同样的忠实转录要求，然后在本地将换行及其他连续空白合并成单个空格，得到一行文本。所有非空白字符均保留，原有连续空格和制表符也会被合并。
- `paragraphs` / **Natural paragraphs（自然段文本）**：要求 Qwen 合并仅因图片宽度不足产生的折行，同时保留真正的段落、标题、独立列表项、代码和表格行。无法确定是否应合并的换行应予以保留。返回结果直接复制，不再进行第二次文本重排。

自然段判断在同一次图片识别请求中完成，不会额外调用一次排版 API。程序也不会在得到文本后，仅凭标点猜测段落边界。模型仍可能误判排版，尤其是密集分栏和复杂列表；如果原始行结构很重要，请选择 **Preserve image layout**。

本项目没有删除标点的设置。所有模式都会要求 Qwen 保留原标点、符号、列表标记和行末连字符。本地排版处理不会删除标点，也不会在标点后额外补空格，但模型转录本身仍可能出错。

例如，选择 **Natural paragraphs**，可以要求将下面的宽度折行合并：

```text
图片中的文字：
这句话因为图片宽度不足
而分成了两行。

- 这是独立的列表项。

期望输出：
这句话因为图片宽度不足而分成了两行。

- 这是独立的列表项。
```

## 常见问题

如果 Git Bash 提示 `bash: ..venvScriptspython.exe: command not found`，说明使用了 PowerShell/CMD 的路径写法。Bash 把未加引号的反斜杠当成了转义符。请在项目目录中改用下面的命令：

```bash
./.venv/Scripts/python.exe -m pip install -r requirements.txt
./.venv/Scripts/python.exe -m quickcrop_ocr
```

这个错误本身不代表虚拟环境创建失败。已有的 `.venv` 不需要重新创建，也不需要激活。

如果提示 API key 无效，请先检查所选地域是否与创建密钥的地域一致，再检查是否复制错误，或密钥是否已被撤销。

如果识别很慢：

- 只框选需要的文字区域。
- 避免一次选择过大的屏幕区域。
- 查看进度窗口中的重试提示，或者取消后改用更小的选区。

如果识别不准确：

- 框选时在文字周围留少量边距，避免裁掉文字。
- 确保原图中的文字足够清晰，人眼也能正常辨认。

## 已知限制

- 有防截屏机制的窗口可能在截图中呈现黑屏。本程序不会绕过截屏保护；图片中没有捕获到的内容，OCR 无法恢复。
- Qwen 可能误识别字符、标点或段落边界。保留原排版指的是保留返回的纯文本结构，而不是还原图片的字体和样式。
- 上传前，截图会按比例缩小至宽高均不超过 1800 像素，并编码为 JPEG。选区过大时，小字可能变得难以识别，建议只框选需要的文字区域。
- 取消只会停止等待和复制，无法撤回已发送给 Qwen 的请求。如果 Windows 拒绝剪贴板写入或恢复操作，程序只能尽力恢复，无法作绝对保证。

## 隐私

- 完整桌面快照只保留在本地内存中，框选完成或取消后即释放。
- 只有框选区域会通过所选地域的 DashScope 接口发送给 Qwen。
- OCR 返回后，剪贴板内容保留在本地。
- 剪贴板备份和最近一次 OCR 结果仅保存在内存中，不写入日志或文件。
- 默认不会永久保存截图文件。

## 项目状态

这是一个面向个人使用的 MVP，主要用于在 Windows 上快速调用云端视觉模型进行 OCR。

## 三个主要迭代阶段

以下是依据 2026 年 6 月至 10 月的真实使用反馈与 Git 历史整理的开发阶段，**不是三个带版本标签的正式发行版**。这里区分功能行为的改善、使用中的观察和性能实测，不把它们包装成跨版本的严格速度或准确率对比。历史阶段中的服务商与设置不代表当前版本仍然支持。

### 第一阶段：先让屏幕文字能够复制（2026 年 6 月）

**为什么修改：** 最初需求是框选看到的文字，直接粘贴到其他地方，减少手工输入。实际使用时出现了“英文能识别，中文不行”，以及白底黑字可用、花色背景和低对比度文字效果差的问题。

**改了什么：** Windows 原型打通了全局快捷键、区域框选、Tesseract 识别与剪贴板复制，并提供可选的 OpenAI 视觉识别路径。通过中文语言包配置、中文优先的语言顺序，以及中英文词元拼接，处理本地识别的配置和空格问题。随后增加灰度、二值化、反色、彩色等候选预处理；当多候选识别导致等待过长时，又将默认本地路径缩减为单个预处理候选和单个页面分割设置。

**效果与优化价值：** 建立了适用于清晰中英文文字的“框选到复制”流程。减少重复调用 Tesseract，是直接减少常用路径上的计算，而不是让用户等待所有候选方案跑完。代价也很明确：本地识别没有网络等待，但堆叠预处理仍不能可靠解决复杂样式；速度、精度等选项越来越多，也提高了配置成本。这一阶段没有可用于证明具体提速百分比的历史基准。

对应历史：[初始原型](https://github.com/JayJle/quickcrop-ocr/commit/8db6928)、[扩展预处理](https://github.com/JayJle/quickcrop-ocr/commit/a9a1394)、[默认快速识别](https://github.com/JayJle/quickcrop-ocr/commit/3da5f11)。

### 第二阶段：转向云端视觉模型与交互式设置（2026 年 6 月）

**为什么修改：** 用户希望真实截图识别得更好，又不想反复调整本地模式。OpenAI 调用遇到额度不足后，流程改用 Gemini，后来加入由用户主动选择的 Qwen。这是在解决服务可用性和使用门槛问题，不代表已经证明某个服务商始终更快或更准确。

**改了什么：** 用云端视觉识别替代本地多种预处理流程，为 Gemini 网络/TLS 故障加入重试。修复 Tkinter 延迟回调引用已失效 `exc` 变量的问题，让界面能显示原始 OCR 错误，而不是再报一个回调异常。启动时改为在命令窗逐项询问服务商、模型、密钥、Qwen 地域和排版，不自动切换服务商；每次重新输入密钥，并应用户需求使用可见输入。增加北京/新加坡选择，以处理正确密钥发往错误地域的问题。

**效果与优化价值：** 用户不必记住不同终端设置环境变量的命令；临时断连不再总需要手动重新开始识别。保留排版与单行输出也适应了不同粘贴场景。但云端识别带来了网络等待、费用、服务可用性和选区上传的取舍；服务商选择与可选的“标点后加空格”又增加了复杂度，可见密钥也可能留在终端滚动记录中。这些实际问题推动了下一阶段的简化。

对应历史：[迁移 Gemini](https://github.com/JayJle/quickcrop-ocr/commit/3b5a974)、[网络故障重试](https://github.com/JayJle/quickcrop-ocr/commit/fe557e5)、[交互式服务商设置](https://github.com/JayJle/quickcrop-ocr/commit/508bca1)。

### 第三阶段：收敛到 Qwen，完善整个使用流程（2026 年 10 月，当前版本）

**为什么修改：** 能返回识别结果还不够。短暂提示消失后，慢请求看起来像卡死；动态字幕可能在真正截图前已经变化；复制失败可能丢失原剪贴板内容。用户同时希望减少选项，并忠实保留标点，而不是自动改写文字。

| 实际问题或反馈 | 修改 | 效果、优化价值与边界 |
|---|---|---|
| 服务商和格式选项太多 | 只保留 Qwen，默认 Plus、北京、单行；设置支持返回、单项修改和最终确认 | 减少决策，选错后容易修正；仍每次询问密钥，不暗中切换服务商 |
| 需要不同排版，而不是改写标点 | 保留原排版、单行、自然段三种布局；移除自动补标点空格 | 适应不同粘贴目标，不主动改变标点；自然段判断仍可能被模型误判 |
| 框选时看到的画面与识别画面不一致 | 先冻结桌面，再框选，只上传裁剪区域 | 识别用户选中的那一帧，尤其适合字幕；仍无法恢复防截屏造成的黑色像素 |
| 慢请求无持续反馈，重试可能拖很久 | 持续显示耗时和重试状态，支持取消、临时 HTTP 故障重试和 30 秒总预算 | 等待可见且有边界；这本身不等于模型推理更快，也不能撤销已发送请求的费用 |
| 复制失败可能丢失内容，或迫使用户重新识别 | 清空前分配新文本，尽力备份恢复，有限次数复制重试，保留结果供再次复制 | 再次复制不需要重新上传和调用模型；仍不能保证恢复所有剪贴板格式 |
| 新增备份保护反而因旧格式不可读而阻止复制 | 跳过不可读、不支持的备份格式，不再一律拒绝复制 | 修复实际出现的“Could not read previous clipboard data”回归；写入失败时，被跳过的格式无法恢复 |
| 工作线程回调和不完整回答可能造成误导 | 工作线程通过队列通知界面；拒绝过期、截断、拒答、格式错误和空回答 | 取消后的迟到结果不会覆盖剪贴板；完成状态检查仍不能发现所有错字漏字 |

英文命令窗引导、中英文 README 互相切换，以及分别说明 PowerShell/CMD 与 Git Bash 命令，也来自实际安装和使用中的问题。剪贴板修复基线已有 **115 项回归测试通过**，验证的是应用行为，不等同于真实模型准确率。

**性能实测，不是已经上线的优化：** 10 月 12 日另建独立实验，未修改正式代码。两张合成图片在当前请求方式下，Plus 分别耗时 2.81 秒、5.02 秒；复用客户端实验分别为 1.96 秒、4.71 秒，每种图片与客户端组合仅测一次。网络、服务端负载等因素意味着不能将差值全部归因于连接复用。图片编码调整只节省约 0.6–4 毫秒；Flash 返回模型不存在，未形成有效的 Plus/Flash 对比。因此，连接复用是下一步值得验证的方向，不是已经实现或可以承诺的提速。

对应历史：[Qwen 流程与可靠性完善](https://github.com/JayJle/quickcrop-ocr/commit/f114e0a)、[中文 README](https://github.com/JayJle/quickcrop-ocr/commit/554d05d)、[区分终端命令](https://github.com/JayJle/quickcrop-ocr/commit/588a45b)、[剪贴板回归修复](https://github.com/JayJle/quickcrop-ocr/commit/2237d0b)。

## 测试

在项目目录中运行离线回归测试。

**PowerShell / 命令提示符（CMD）：**

```powershell
.\.venv\Scripts\python.exe -m unittest discover -v
```

**Git Bash：**

```bash
./.venv/Scripts/python.exe -m unittest discover -v
```

如果当前 Python 环境已配置好，也可以运行 `python -m unittest discover -v`。测试不需要真实 API key，不会发起收费 OCR 请求。

测试使用合成图片、模拟 API 响应和模拟剪贴板。Windows 专用的内存测试会验证 Unicode 文本的分配和复制，不读取或修改系统剪贴板。覆盖范围包括：设置流程中的返回与确认、无效输入、密钥隐藏处理、真实命令行入口的退出行为、三种排版模式、标点保留、识别指令选择、截断或拒绝的回答、取消、总时间预算、计时器提前唤醒、HTTP 重试、迟到响应、剪贴板恢复、快捷键生命周期，以及包含负坐标显示器的冻结画面裁剪。

排版测试验证的是发给模型的指令和响应处理，并不代表模型在真实图片上的准确率。实际截图识别仍需使用你自己的 Qwen 密钥和桌面环境验证。
