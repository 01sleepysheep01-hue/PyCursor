# 仓库可验证性体检

增量 D 使用九根柱子和五个等级评估仓库，不根据文件是否存在“猜分”，而是执行统一
检查并记录命令、退出码、耗时和证据。

## 一条命令

```powershell
python scripts\check.py
```

该命令依次执行 Python 语法检查、空白与 Tab 检查、敏感文件检查、疑似密钥扫描和
完整单元测试。任何一项失败都会返回非零退出码，因此可以被 CI、Git hook 或人工
验收共同使用。

## 九项体检

```powershell
python -m app.readiness --out readiness_report.json
```

报告包含九根柱子的逐项得分和证据、L1 至 L5 的解锁情况、当前等级、最该补的三项，
以及一条命令检查的真实退出码、耗时和输出尾部。等级采用 80% 阈值逐级解锁。

当前课程及格线是 L3，并要求报告中的 `one_command_check.passed` 为 `true`。
