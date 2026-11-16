## CodeProof review

判定：`request_changes`
数据集：12 个 PR，8 条已知 bug。
召回：8/8（100%）。
误报：0 条。

逐条结果：
- `BUG-001/hardcoded-password`：命中，app/settings.py:3，明文密码会随源码进入仓库。
- `BUG-002/swallowed-exception`：命中，app/parser.py:4，异常被吞掉，调用方无法区分成功和失败。
- `BUG-003/dynamic-code-execution`：命中，app/expression.py:2，攻击者可以提交任意 Python 表达式。
- `BUG-004/sql-injection`：命中，app/users.py:2，用户输入直接进入 SQL，应使用参数化查询。
- `BUG-005/debug-output`：命中，app/store.py:3，调试输出绕过日志级别和脱敏流程。
- `BUG-006/missing-input-validation`：命中，app/http.py:2，缺少参数时直接抛出未处理异常。
- `BUG-007/shell-injection`：命中，app/runner.py:2，命令字符串可能被 shell 解释为额外指令。
- `BUG-008/n-plus-one-query`：命中，app/user_list.py:3，循环内执行查询，请求数会随数据量线性增长。
