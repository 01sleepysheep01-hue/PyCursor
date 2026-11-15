# 自我代码评审

增量 F 新增 `review` 子命令：读取带标准答案的 PR diff 数据集，运行 correctness、
security、performance、quality 四类规则，并生成结构化结果和一条汇总评论。

```powershell
python -m pycursor review --dataset review_dataset --out review_report.json --comment-out review_comment.md
python -m pycursor review --diff-file change.diff --out single_review.json
```

固定档位：

- `approved`：没有发现问题；
- `with_comments`：只有 warning 或 suggestion；
- `request_changes`：至少有一条 critical。

每条 finding 使用 `path + line + rule_id + message` 计算稳定 ID，因此同一份 diff
两次运行得到相同结果。课程评测要求召回率不低于 60%，误报不超过 3 条。

为保证课堂结果可复现，数据集评测采用确定性的本地规则，不调用 API。生产环境仍可
使用现有 `review_diff` reviewer 工具进行 DeepSeek 语义审查，两者共享同一发现数据契约。
