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
- [ ] 创建 `v1.5.0` tag
- [ ] 创建 GitHub Release 并上传 `dist/PyCursor-Setup-1.5.0.exe`
- [ ] 将仓库链接与 Release 链接填写到课程表格
- [ ] 按 `docs/demo.md` 用自己的电脑完成 5 分钟现场演示

公开仓库和 Release 需要账户授权，且提交历史不能由打包工具伪造。

## 本单元验收数据

- D 可验证性：L3，97.1 分，一条命令测试为真，报告见 `readiness_report.json`。
- E 并行：2 个 worker 均通过测试，合并冲突 0 个，报告见 `parallel_report.json`。
- F 评审：已知 bug 命中 8/8，召回率 100%，误报 0 条，见 `review_report.json`。
- 当前源码版本为 1.5.0；发布前仍需用最终源码重新构建安装包，不能沿用旧版 dist。

## 现场演示前检查

1. 关闭旧版 PyCursor。
2. 用最终源码构建并重新安装 `dist/PyCursor-Setup-1.5.0.exe`。
3. 打开设置，确认 Base URL 为 `https://api.deepseek.com/v1`。
4. 确认模型为服务商实际开放的 `deepseek-chat` 或 `deepseek-v4-flash`。
5. 用“设置”选择演示工作区。
6. 打开 `docs/demo.md`，按 5 分钟流程练习。

