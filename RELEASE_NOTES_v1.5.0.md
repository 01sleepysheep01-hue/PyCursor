# CodeProof 1.5.0

CodeProof 保留 PyCursor 包名和可执行文件以兼容旧环境，展示名改为 CodeProof。

## 本单元增量

- D 可验证性：九根柱子、五个等级，并提供一条命令统一检查。
- E 并行：两个真实 Git worktree 同时执行、测试和合并，保留完整 JSON 报告。
- F 评审：四类专科规则、稳定 finding ID、三个判定等级和单条汇总评论。

## 可复核结果

```text
python scripts\check.py
Ran 85 tests - OK

python -m app.readiness --out readiness_report.json
Level: L3 | Score: 97.1

python -m pycursor review --dataset review_dataset --out review_report.json
Recall: 8/8 | False positives: 0 | Pass: True
```

`parallel_report.json` 记录了 `pass: true`、两个 worker 测试通过、冲突文件为空，
以及合并后全量测试通过。评审数据集包含 8 个已知 bug 和 4 个干净对照，评测采用
确定性本地规则，不调用外部 API，也不读取 API Key。

## 安装

最终源码应先执行 `scripts\build_windows.ps1`，再执行
`scripts\build_sfx_setup.ps1`。产物为：

```text
dist\PyCursor-Setup-1.5.0.exe
dist\PyCursor-Windows-x64.zip
```

安装后的电脑不需要 Python 或 WinRAR。首次启动后进入“设置”，填写 DeepSeek API
Key；默认 Base URL 为 `https://api.deepseek.com/v1`，默认模型为 `deepseek-chat`。
