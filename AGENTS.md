# 项目地图

- `pycursor/`：后端、工具、模型客户端、桌面界面和技能系统。
- `pycursor/hooks.py`：工具前后的硬约束与测试摘要回注。
- `pycursor/reviewer.py`：独立上下文的只读 diff reviewer。
- `app/inspect.py`：独立生成作业报告，不依赖 UI。
- `skills/`：可带走的技能目录，每个子目录必须有 `SKILL.md`。
- `tests/`：标准库 `unittest` 测试；新增能力必须有开关和回归测试。
- `.githooks/`：提交前敏感文件扫描；仓库使用 `.githooks`。

# 构建与测试

- 全量测试：`python -m unittest discover`
- 技能报告：`python -m app.inspect skills --out skill_report.json`
- 启动桌面版：`python -m pycursor`

# 代码风格

- 只用标准库和现有依赖，不随意增加第三方包。
- 面向用户的错误要说明原因和替代方案，不要只写“失败”。
- 新能力默认可用，同时支持对应环境变量关闭。

# 坑

- Windows 下 Git 的 `sh` hook 可能触发信号管道错误；提交前仍须手工扫描密钥和敏感文件。
- `.env`、`*.pem`、`*.key` 和本地配置不能进入 Git。
- 工作区路径必须经过 `ToolContext.safe_path()`，不要自行拼接后直接读写。
- 技能正文按需加载；启动时只注入目录，不要把全部 `SKILL.md` 拼进 system prompt。
