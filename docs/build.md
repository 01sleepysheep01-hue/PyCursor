# 构建与发布

## 1. 本地验证

```powershell
python scripts\check.py
python -m app.readiness --out readiness_report.json
python scripts\replay_demo.py
```

## 2. 生成 Windows 目录构建

```powershell
.\scripts\build_windows.ps1
```

产物：

```text
dist\PyCursor\PyCursor.exe
dist\PyCursor-Windows-x64.zip
```

解压 `PyCursor-Windows-x64.zip` 后双击 `PyCursor.exe`，确认窗口能打开，并能选择
工作区、保存设置、调用四个工具。

## 3. 生成安装程序

构建机安装 WinRAR 后执行：

```powershell
.\scripts\build_sfx_setup.ps1
```

产物：

```text
dist\PyCursor-Setup-1.0.0.exe
```

脚本会把目录构建封装成自解压安装器。安装到
`%LOCALAPPDATA%\Programs\PyCursor`，创建桌面与开始菜单快捷方式，并立即启动。
安装后的用户不需要 Python 或 WinRAR。

如构建机没有 WinRAR，也可安装 Inno Setup 6 并执行：

```powershell
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" .\scripts\installer.iss
```

在新目录或第二台机器安装，确认无需运行 `python app.py`。

## 4. GitHub Release

1. 创建 public 仓库并提交源码。
2. 确保 `.env`、`.pycursor`、构建环境和缓存没有入库。
3. 创建 `v1.0.0` tag。
4. 发布 Release，并附加安装程序。
5. 在 README 的“三步启动”中替换为当前 Release 链接。

不要把 API Key 放入任何 commit。如果曾经提交，立即吊销并更换 Key；仅删除文件
不能清除 Git 历史中的密钥。

