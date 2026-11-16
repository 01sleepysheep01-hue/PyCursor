# CodeProof（PyCursor）作业提交清单

## 已完成

- [x] 桌面窗口与三栏界面
- [x] DeepSeek 默认配置
- [x] read / write / edit / bash 四个工具
- [x] MCP 独立 server 真实调用
- [x] 工具调用、diff 与 Trace 可见
- [x] 命令超时、截断和中断
- [x] 85 项自动测试
- [x] `README.md` 与三张以上界面截图
- [x] `report.md`
- [x] `docs/trace.md`
- [x] `docs/build.md`
- [x] Windows 安装包
- [x] Windows 免安装目录包
- [x] `demo.mp4`
- [x] 九根柱子仓库体检：`readiness_report.json`
- [x] 两个真实 worktree 并行与合并：`parallel_report.json`
- [x] 12 个样例、四条专科规则和单条汇总评论：`review_report.json`、`review_comment.md`

## 需要账号完成的步骤

- [x] 在 GitHub 创建 public 仓库
- [x] 按真实开发过程形成 45 次 commit，跨度 12 天（2026-11-03 至 11-15）
- [x] 创建并推送 annotated tag `v1.5.0`
- [x] 创建 GitHub Release 并上传安装程序、免安装包、源码包与 SHA256 清单
- [ ] 将仓库链接与 Release 链接填写到课程表格
- [ ] 按 `docs/demo.md` 用自己的电脑完成 5 分钟现场演示

公开仓库、tag 和 Release 均已完成。课程表格需要登录课程系统后手工粘贴；现场演示需
在你的电脑上完成。提交历史为真实开发记录，未伪造或回填日期。

## 本单元验收数据

- D 可验证性：L3，97.1 分，一条命令测试为真，报告见 `readiness_report.json`。
- E 并行：2 个 worker 均通过测试，合并冲突 0 个，报告见 `parallel_report.json`。
- F 评审：已知 bug 命中 8/8，召回率 100%，误报 0 条，见 `review_report.json`。
- 当前源码版本为 1.5.0；最终源码已重新构建，安装版和免安装版均完成窗口冒烟测试。

## 现场演示前检查

1. 关闭旧版 PyCursor。
2. 用最终源码构建并重新安装 `dist/PyCursor-Setup-1.5.0.exe`。
3. 打开设置，确认 Base URL 为 `https://api.deepseek.com/v1`。
4. 确认模型为服务商实际开放的 `deepseek-chat` 或 `deepseek-v4-flash`。
5. 用“设置”选择演示工作区。
6. 打开 `docs/demo.md`，按 5 分钟流程练习。

## 提交链接

- GitHub 仓库：https://github.com/01sleepysheep01-hue/PyCursor
- GitHub Release：https://github.com/01sleepysheep01-hue/PyCursor/releases/tag/v1.5.0
- 安装程序：https://github.com/01sleepysheep01-hue/PyCursor/releases/download/v1.5.0/PyCursor-Setup-1.5.0.exe

