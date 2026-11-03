# PyCursor 1.0.0

PyCursor 是一个面向本地工作区的桌面编码智能体，默认接入 DeepSeek。

## 功能

- 原生桌面窗口，无需浏览器
- DeepSeek Chat Completions 与 function calling
- `read`、`write`、`edit`、`bash` 四个内置工具
- 工具调用、diff 与 Trace 实时可见
- 命令超时、输出截断和中断
- 标准 MCP stdio 客户端与示例 server
- 本地会话持久化

## 安装

下载并双击：

```text
PyCursor-Setup-1.0.0.exe
```

也可以在解压 `PyCursor-Windows-x64.zip` 后运行 `PyCursor.exe`。

首次启动后进入“设置”，填写 DeepSeek API Key。默认配置：

```text
Base URL: https://api.deepseek.com/v1
Model: deepseek-chat
```

如果服务商明确提供 `deepseek-v4-flash` 或 `deepseek-flash`，可以按账户的模型列表
修改模型名；该模型必须支持工具调用。

## 演示

- 实时操作视频：`demo.mp4`
- 界面截图：`docs/screenshots/`
- 真实失败与恢复 trace：`docs/trace.md`

## 验证

```text
Ran 16 tests — OK
Demo workspace — 5/5 tests passed
```

## 限制

- 安装包未进行商业代码签名，Windows 可能显示“未知发布者”。
- `bash` 使用当前用户权限。处理不可信仓库时应使用低权限账户或受限容器。
- 图片读取需要所配置模型支持多模态输入。

