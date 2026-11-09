# PyCursor 1.2.0

这是增量作业的交付版本，保留 v1.0 的桌面界面、四个编码工具、MCP、事件流与
Windows 安装方式，并加入技能和定制层。

## 增量内容

- `skills/` 目录与渐进披露加载器，目录 158 估算 tokens、全文 1080，披露比为
  6.835，9 条触发试验误触发为 0。
- `run-tests`、`review-diff`、`fetch-issue` 三种技能形态。
- 分层 `AGENTS.md` 注入。
- `PreToolUse` 拒绝写入 `.env` 与危险命令，并给出替代方案。
- `PostToolUse` 在改代码后运行测试并回注简短摘要。
- 独立只读 reviewer，只向主上下文回传最终判定。
- 可由 `app.inspect` 程序化生成 `skill_report.json` 与 `custom_report.json`。

## 验证

```text
python -m unittest discover
Ran 70 tests - OK
```

`custom_report.json` 记录了 2 次拒绝、1 次红灯到绿灯、30 个字符的 reviewer
主上下文回传。reviewer 探针使用脚本化模型，不调用外部 API。

## 安装

下载并双击：

```text
PyCursor-Setup-1.2.0.exe
```

免安装目录包为 `PyCursor-Windows-x64.zip`。安装后的电脑不需要 Python、Tk 或
WinRAR。首次启动后进入“设置”，填写 DeepSeek API Key；默认 Base URL 为
`https://api.deepseek.com/v1`，默认模型为 `deepseek-chat`。

安装包未做商业代码签名，Windows SmartScreen 可能显示“未知发布者”。
