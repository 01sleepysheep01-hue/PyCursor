# 在微信中打开 CodeProof H5

CodeProof 现在自带一个移动端 H5 入口。它复用桌面版相同的 Python 后端、DeepSeek
模型、四个编码工具、MCP、SSE 事件流和 diff 报告，不是另做一套假界面。

H5 与原生微信小程序的区别：H5 通过微信内置浏览器打开，不需要小程序 AppID、
审核或安装包；但运行它的电脑必须保持开机并启动 CodeProof 服务。

## 一、安装版：同一 Wi-Fi 演示

1. 打开 CodeProof 桌面窗口，在右上角点击“手机 H5”。
2. 手机与电脑连接同一个 Wi-Fi。把弹窗里的局域网地址发到微信文件传输助手。
3. 在手机微信中打开链接，输入弹窗里的访问令牌。
4. Windows 防火墙第一次询问时，只允许 CodeProof/Python 在“专用网络”通信。
5. 演示结束点击“停止 H5”，访问令牌会立即失效。

如果电脑没有安装版，再使用下面的源码启动方式。

## 二、源码方式：同一 Wi-Fi 演示

1. 在项目根目录复制并填写 `.env`：

   ```powershell
   Copy-Item .env.example .env
   ```

   至少填写 `CODEPROOF_API_KEY`。如果服务商的模型名不同，同时修改
   `CODEPROOF_MODEL`。

2. 启动 H5 和局域网监听：

   ```powershell
   .\scripts\start_web.ps1 -Lan
   ```

3. 终端会打印两类地址和一个随机访问令牌，例如：

   ```text
   CodeProof H5 (本机): http://127.0.0.1:8765/
   CodeProof H5 (同一 Wi-Fi): http://192.168.1.25:8765/
   本次访问令牌: xxxxxxxxxxxxxxxxxxxxxxxx
   ```

4. Windows 防火墙第一次询问时，允许 Python 在“专用网络”通信。不要开放公用网络。

5. 确保手机与电脑连接同一个 Wi-Fi。把“同一 Wi-Fi”地址发送到微信文件传输助手，
   在手机上点击链接。

6. H5 页面会要求输入访问令牌，输入终端显示的值即可。令牌验证后会建立 HttpOnly
   会话 Cookie，不会写入浏览器 localStorage。

7. 任务完成后按 `Ctrl+C` 停止服务，访问令牌同时失效。

如果页面无法打开，依次检查：手机与电脑是否在同一 Wi-Fi、路由器是否开启了访客网络
隔离、Windows 防火墙是否允许 Python、地址端口是否仍是 `8765`。

## 三、发给不在同一 Wi-Fi 的人

本地 HTTP 地址不能直接从外网访问。可把本机 `8765` 端口通过 HTTPS 反向代理或内网
穿透工具发布，例如 Cloudflare Tunnel、frp 或学校提供的 HTTPS 网关。配置原则：

```text
微信 H5 -> HTTPS 域名 -> 隧道/反向代理 -> 本机 127.0.0.1:8765
```

必须同时设置长随机令牌：

```powershell
$env:CODEPROOF_WEB_TOKEN = "请替换为至少12位的随机令牌"
.\scripts\start_web.ps1
```

再把隧道服务转发到 `http://127.0.0.1:8765`。公网入口必须是 HTTPS；微信对公网 HTTP
页面可能拦截或提示不安全。隧道地址和令牌不要提交到 Git。

## 四、安全边界

H5 与桌面版拥有同样的本地执行能力。任何拿到链接和令牌的人，都可以让智能体读取、
修改或执行所配置工作区中的内容。

- 只把工作区设置为允许展示的目录，不要选择整个用户目录。
- 不要公开 `.env`、API Key、访问令牌或带令牌的截图。
- 演示结束后停止服务；随机令牌每次启动都会重新生成。
- 使用公网隧道时，演示结束立即关闭隧道和服务。
- 不要向不可信 MCP server 提供真实工作区权限。

## 五、验证命令

```powershell
python scripts\check.py
python -m unittest tests.test_server -v
```

服务端测试会验证 H5 静态页面、未登录 401、Cookie 登录、健康状态和非本机监听强制
令牌保护。
