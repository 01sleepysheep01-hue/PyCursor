# 双 worktree 并行执行

增量 E 使用两个独立 Git worktree 同时完成互不相交的任务：

1. `findings-contract`：增加评审发现的稳定数据契约及测试。
2. `review-docs`：补充评审工作流和数据集说明。

两个分支从同一个 base commit 创建，在独立目录中并行执行；每个 worktree 先运行统一
检查，再提交自己的改动。之后主工作树依次使用 `git merge --no-ff` 合并两个分支。

运行：

```powershell
python -m app.parallel --out parallel_report.json
```

报告包含两个分支、各自任务和测试耗时、改动文件、提交哈希、合并冲突文件以及合并后
全量测试结果。临时 worktree 默认被清理，任务分支保留作为可审计证据。

本演示使用确定性的 scoped worker，避免 API Key、网络和模型随机性让课堂结果不可复现；
生产模式可以在 `scripts/parallel_worker.py` 中替换为真实的 DeepSeek agent 调用。
