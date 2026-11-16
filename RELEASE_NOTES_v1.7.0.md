# CodeProof 1.7.0

本版本完成统一品牌重命名，并把微信 H5 入口纳入正式 Windows 交付物。

## 命名统一

- 桌面程序：`CodeProof.exe`
- Python 包与模块：`codeproof`
- 启动命令：`CodeProof.cmd`、`codeproof`、`codeproof-server`
- 配置变量：`CODEPROOF_API_KEY`、`CODEPROOF_MODEL`、`CODEPROOF_WEB_TOKEN`
- 本地状态目录：`%USERPROFILE%\.codeproof`
- 安装和压缩包：`CodeProof-Setup-1.7.0.exe`、`CodeProof-Windows-x64.zip`

## 功能

- 保留 read、write、edit、bash 四个工具、MCP、trace、diff 和中断能力。
- 桌面右上角“手机 H5”启动局域网服务并生成一次性访问令牌。
- 手机微信内置浏览器可提交真实任务、查看 SSE 工具轨迹和代码 diff。
- H5 使用 HttpOnly Cookie、同源 CSP，并拒绝无 Token 的非 loopback 监听。

## 验证

```text
python scripts\check.py
Ran 87 tests - OK
source hygiene: PASS
sensitive files: PASS
embedded secrets: PASS
```
