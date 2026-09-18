---
name: xmind-to-testcase
description: 将 XMind 思维导图测试用例（.xmind）改写为标准书面测试用例，并生成/更新 Markdown 文件。当用户提供或引用 .xmind 文件，希望改写为结构化用例（用例描述/测试步骤/预期结果）并保存到 .md 文件时使用。适用于任意被测对象（App、Web、功能），不限于某个具体产品。
---

# XMind → 标准测试用例 → Markdown

封装完整流程：**读取 `.xmind` 文件 → 把 BDD 风格节点改写为标准测试用例 → 生成（或追加到）Markdown 文件。**

适用于任意被测对象。被测对象名称、输出文件、优先级均来自输入内容，不要写死为某个特定产品。

## 1. 读取 .xmind 文件

`.xmind` 本质是 ZIP 压缩包。先解压，再解析 `content.json`。

```powershell
$src = "<path\to\input.xmind>"
$dest = "C:\Users\lyc\AppData\Local\Temp\opencode\xmind_extract"
$zip  = "C:\Users\lyc\AppData\Local\Temp\opencode\xmind.zip"
if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
if (Test-Path $zip)  { Remove-Item $zip  -Force }
Copy-Item -LiteralPath $src -Destination $zip
Expand-Archive -LiteralPath $zip -DestinationPath $dest -Force
```

`Expand-Archive` 不支持 `.xmind` 扩展名，所以必须先复制为 `.zip` 再解压。

然后把主题树导出到 UTF-8 临时文件（PowerShell 5.1 控制台会乱码中文，所以先写入文件再用 Read 工具读取）：

```powershell
$bytes = [System.IO.File]::ReadAllBytes("$dest\content.json")
$text  = [System.Text.Encoding]::UTF8.GetString($bytes)
$json  = $text | ConvertFrom-Json
$out = New-Object System.Text.StringBuilder
function Append-Tree($node, $depth) {
  $indent = "  " * $depth
  $line = $indent + $node.title
  if ($node.labels) { $line += "  [" + ($node.labels -join ",") + "]" }
  [void]$out.AppendLine($line)
  if ($node.children -and $node.children.attached) {
    foreach ($c in $node.children.attached) { Append-Tree $c ($depth+1) }
  }
}
Append-Tree $json[0].rootTopic 0
[System.IO.File]::WriteAllText("C:\Users\lyc\AppData\Local\Temp\opencode\tree.txt", $out.ToString(), [System.Text.Encoding]::UTF8)
```

然后用 Read 工具打开 `tree.txt` 查看完整树结构。

## 2. 理解源结构

典型的节点角色（BDD 风格）：

- `Feature: ...` —— 分组层级（模块 / 子模块）。
- `Scenario: <名称>` —— 一条测试用例。标签（`labels`）携带优先级（`BVT`、`P0`、`P1` 等）。
- `Given: <前置条件>` —— 前提 / 前置条件。
- `When: <动作>` —— 一个操作步骤。
- `Then: <预期>` —— 一条预期结果（可能为空，也可能跨多行）。

## 3. 改写为标准格式

对每个 `Scenario` 生成一条用例，使用以下精确模板：

```markdown
## 用例描述：<标题>（<优先级，如 BVT / P0>）

测试步骤：
1、打开<被测应用>
2、<动作>
3、<动作>
预期结果：<关键验证结果>

---
```

### 格式规则（来自实际使用经验）

- **步骤 1 = 打开<被测应用>**。被测应用名称由调用方显式提供（CLI `--app-name`），不要从模块名自行推断；若调用方明确提供了应用名，请以该名称为准。如果源码从中间开始（如"点击我的"），先补上"打开应用"。即使源码中应用已处于打开状态，为保持一致，步骤 1 仍写"打开"。
- **步骤为纯动作**。不要把冗长验证内容塞进步骤里。
- **中间态 UI 反馈**（动作后屏幕立即显示的内容）可并入步骤，例如 `点击"其他"选项，展示"定时播放设置"选择面板`。
- **预期结果 = 简练的关键验证**。单一结果 → 一行短句。多个结果 → 用 `；` 连接。不要用 `1. 2.` 编号。
- **重复的参考信息**（如多条用例里相同的页面布局）不属于核心测试内容。抽出来放到 `知识：` 区（放在该用例的预期结果之后，只出现一次），步骤保持纯动作。做之前先询问用户。
- **空 `Then` 节点**：能推知意图就补全预期，无实际意义就删掉该空节点。
- **修复明显的复制粘贴笔误**（例如"30分"用例的预期结果误写成"15分钟后"）。并把改动告知用户。
- **前置条件**（如"已登录"）在步骤中简要括注，例如 `点击"我的"（已登录账号）`。
- **优先级**取自 Scenario 的 `labels`（如 `P0`、`BVT / P0`）。`P1`/`P2` 原样保留。

## 4. 生成 / 更新 Markdown 文件

- **先询问用户**：输出 `.md` 路径，以及每条新用例是追加到已有文件还是新建文件。
- **追加时匹配已有文件格式**：相同的标题样式、`测试步骤：` 用 `1、` 编号、单行 `预期结果：`、用例之间用 `---` 分隔。
- **用 Edit 工具追加**：匹配当前最后一条用例的结尾（`预期结果：...` 行及其后的 `---`），在其后追加新用例。每次都要先重新 Read 文件，防止用户在上次之后又做了修改。
- 保留步骤 1 要补写的被测应用名称。

## 5. 校验

写入后，用 `Read` 打开 Markdown 文件末尾，确认新用例已正确追加且分隔符完整。

## 备注

- 上面命令基于 Windows PowerShell 5.1。其他平台可用对应平台的解压工具解压 zip，再按同样方式读取 `content.json`。
- 部分 `.xmind` 文件同时包含 `content.xml`；存在 `content.json` 时优先用 `content.json`（新格式，更易解析）。
- 向 `.md` 文件写入中文没有问题，Write/Edit 工具支持 UTF-8。