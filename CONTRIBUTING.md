# Contributing

感谢提交 Issue 或 Pull Request。请先运行：

```bash
pip install -e ".[test]"
ruff check .
pytest
```

行为变更应补充测试，并在 `CHANGELOG.md` 中记录。提交信息请使用清晰的英文动词开头；不要提交 `data/cave/`、数据库、图片或凭据。

