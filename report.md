# PyCursor 大作业报告

## 1. 目标与结果

项目按课程第 35 页实现一个本地桌面编码智能体。启动后显示原生窗口，左侧为
工作区文件，中央为对话，右侧为工具活动、diff 和 trace。后端可脱离界面单独运行，
因此循环、工具和 MCP 不依赖 UI 进程。

核心链路已经完成并通过测试：

- 模型提出结构化工具调用。
- 本地白名单执行 read/write/edit/bash 或 MCP 工具。
- 观察结果原样回灌模型。
- 工具活动和 diff 实时进入 SSE 事件流。
- 用户可停止任务，bash 子进程树会被终止。
- 测试失败、读取、精确修改、再次测试构成真实恢复链路。

## 2. 架构

```text
Tkinter 桌面 UI
       |
       | HTTP + SSE
       v
本地 HTTP API -> TaskManager -> AgentRunner -> LLM
                                  |             |
                                  |             +-- DeepSeek Chat Completions
                                  |
                                  +-- four native tools
                                  +-- MCPManager -> stdio MCP servers
```

选择本地 HTTP 层而不是在 UI 线程直接调用智能体的原因有两个：

1. 后端能用 `curl -N` 独立验收，符合大作业要求。
2. UI 只是事件消费者，后续替换成 pywebview、Electron 或 Tauri 时，循环不用重写。

## 3. 四个工具的取舍

### read

文本读取保留真实行号和剩余行数，模型不需要自己数字符偏移。超过一页时返回下一次
应使用的 `offset`。图片转成标准多模态内容块，而不是把 base64 塞进普通字符串。

### write

先写同目录临时文件，执行 `flush` 与 `fsync`，最后 `os.replace`。这避免写到一半
留下损坏文件；返回值同时报告旧、新行数和 unified diff。

### edit

要求 `old` 精确出现且只出现一次。出现多次时返回发生次数，并提示模型扩大上下文。
这一条比“模糊匹配”多一次往返，但挡住了改错分支和整文件重排。

### bash

这是唯一的通用动作工具。搜索、Git、依赖和测试都走它，避免几十个细接口提高模型
选错工具的概率。实现包含超时、取消、进程树终止和 30,000 字符输出上限。

## 4. 上下文与循环

系统提示明确“先读再改、失败后扩上下文、完成后必须验证”。循环有最大步数限制；
同一工具参数连续重复三次时会插入提醒。上下文超过预算后，保留最近六条工具
观察，先压缩更早的大型输出，同时维持 assistant tool call 与 tool result 的结构。

会话每轮保存用户和最终答复，历史在下一轮启动时加载。工具完整结果保存在 trace，
避免把无限增长的历史反复发送给模型。

## 5. MCP

MCP 客户端在独立进程中启动 server，通过 JSON-RPC over stdio 完成握手、工具发现
和调用。stdout 只处理协议帧，stderr 转为日志。仓库自带一个独立 server 作为可复现
示例，提供 `get_system_info` 和 `project_snapshot`。

打包后，内置 server 通过同一个 PyCursor 可执行文件的 `--mcp-demo` 子模式运行；
开发模式则直接使用当前 Python 解释器。外部 server 继续使用自己的 command、args
和 env。

## 6. 失败与恢复

`docs/trace.md` 记录真实执行：

1. `bash` 运行测试，退出码 1。
2. `read` 获取带行号的源码。
3. `edit` 精确修改唯一匹配。
4. 第二次 `bash` 运行测试，退出码 0，5/5 通过。

模型回复在复现脚本中预先编排，用于离线验收；工具执行和测试结果是真实的。

## 7. 打包与分发

`scripts/build_windows.ps1` 使用 PyInstaller 生成带桌面入口的 Windows 目录构建，
并压缩为 `PyCursor-Windows-x64.zip`；解压后双击 `PyCursor.exe` 即可运行，不需要
用户已安装 Python。`scripts/build_sfx_setup.ps1` 再把这个目录构建封装为
`PyCursor-Setup-1.0.0.exe`，安装到当前用户目录并创建快捷方式。
`scripts/installer.iss` 保留为 Inno Setup 6 的替代路径。
`scripts/package_portable.ps1` 可生成源码便携包。

运行时不需要第三方 Python 库，因此安装包的主要体积来自 Python 与 GUI 运行时。

## 8. 如果只能再加一个工具

我会加 `glob`：按路径模式列出文件，并返回大小、类型和忽略规则。它不能替代
`bash`，但能低成本完成“项目里有哪些相关文件”的 discovery，减少模型猜测路径和
向上下文回灌整段目录命令输出的次数。当前版本继续保持四个工具，符合作业约束。

## 9. 已知限制

- `bash` 跟随应用用户权限。路径校验只约束 read/write/edit，命令自身仍可访问
  操作系统允许的资源；生产环境应配合容器、低权限账户或额外策略。
- UI 只面向 Windows 验证。后端与工具路径逻辑兼容 POSIX，但未在本机验证
  macOS / Linux 打包。
- 默认模型是 DeepSeek `deepseek-chat`。切换到其他兼容服务时，对方必须支持
  Chat Completions 的 function calling。
- 演示也可以把模型改成服务商实际开放的 `deepseek-v4-flash`；若该变体不支持工具
  调用，PyCursor 只能对话，不能执行 read/write/edit/bash。
- 仓库公开、至少 15 次跨 7 天 commit、GitHub Release 属于账号和外部发布操作，
  需要提交者在自己的仓库中完成；本交付没有伪造提交历史。

