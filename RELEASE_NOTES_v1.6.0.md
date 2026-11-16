# CodeProof 1.6.0

本版本在桌面智能体后台上增加微信内置浏览器可用的响应式 H5，不复制业务逻辑，也不
使用演示用假数据。

## 新增

- 手机、平板和桌面三档响应式布局，移动端底部切换文件、对话和执行轨迹。
- DeepSeek、MCP、工作区状态，任务输入，停止任务，新对话和 SSE 实时工具轨迹。
- 工具参数、结果、错误、测试 Hook 摘要和代码 diff 展示。
- 桌面窗口右上角“手机 H5”入口，一键启动局域网服务并生成一次性访问令牌。
- HttpOnly 会话 Cookie、严格同源 CSP、非 loopback 强制访问令牌。
- 公网 HTTPS 隧道与同一 Wi-Fi 演示说明：`docs/wechat-h5.md`。

## 验证

```text
python scripts\check.py
Ran 87 tests - OK
source hygiene: PASS
sensitive files: PASS
embedded secrets: PASS
```

H5 是网页入口，不是原生微信小程序，不需要小程序 AppID；模型调用和
read/write/edit/bash 仍由当前电脑上的 CodeProof 后端执行。

## 安装

```text
dist\PyCursor-Setup-1.6.0.exe
dist\PyCursor-Windows-x64.zip
```
