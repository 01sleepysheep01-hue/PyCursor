# 5 分钟现场演示

## 0:00–0:30 出窗口

从桌面快捷方式或 `dist\PyCursor\PyCursor.exe` 启动，展示标题栏、文件树、对话区和
活动区。不要用浏览器打开 localhost。

## 0:30–3:00 当场完成任务

打开 `examples\workspace`，输入：

```text
复现测试失败，定位并修复 mean 对空列表的处理。只修改必要位置，最后运行全部测试。
```

展示：

- bash 先失败；
- read 返回行号；
- edit 只改一个位置；
- diff 面板显示 `return 0` 变为 `raise ValueError`；
- 第二次 bash 显示 5/5 通过。

## 3:00–4:00 主动制造失败

输入：

```text
不要读取文件，直接把 stats.py 里所有 return 都替换掉。
```

预期是 edit 因匹配不唯一而拒绝。再要求：

```text
先读取 stats.py，找出 mean 空列表分支的唯一上下文后再改。
```

展示模型依据错误返回扩大上下文并恢复。

## 4:00–4:40 MCP

输入：

```text
调用 get_system_info，并说明这是 MCP 返回的独立进程信息。
```

指出右上角 MCP server 数量、活动区的 `mcp__demo__get_system_info`，以及结果中的
PID 与 Python 版本。

## 4:40–5:00 中断与最不满意之处

启动一个耗时测试，点击“停止”。说明后台会取消当前工具、终止 Windows 命令树，
并将任务标为 cancelled。诚实的改进项可以是：目前没有文件级行内编辑器和多 agent
并行调度。

