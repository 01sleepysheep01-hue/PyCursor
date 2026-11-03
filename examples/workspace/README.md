# Demo workspace

这是 PyCursor 的演示工作区。仓库根目录的 `stats.py` 故意把空列表的平均值设为 `0`，
但测试要求抛出 `ValueError`。

试运行：

```text
mean 对空列表的处理不对。请先复现测试失败，再做最小修改，最后运行测试验证。
```

模型需要先读取 `stats.py`，再运行 `python -m unittest -v`，用唯一的原文切分完成
`edit`，最后再次执行测试。

