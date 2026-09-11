# nonebot-plugin-cave-rebuilt

面向 NoneBot2 / OneBot V11 的回声洞插件重构版。保留原项目的主要体验：群友投稿文字或图片，经白名单 B 私聊审核后进入全局内容池；群聊可随机抽取，各群分别维护冷却时间、白名单 A 和处理动态。

## 安装

```bash
pip install .
```

在 NoneBot 项目的 `pyproject.toml` 中加载 `nonebot_plugin_cave`。

## 配置

```dotenv
# 审核白名单 B 的管理者；未设置时使用 SUPERUSERS
WHITE_B_OWNER=["123456"]

# 以下均可选
CAVE_DATA_DIR=data/cave
CAVE_DEFAULT_COOLDOWN=1
CAVE_DEFAULT_COOLDOWN_UNIT=sec
CAVE_DOWNLOAD_TIMEOUT=15
CAVE_MAX_IMAGE_BYTES=10485760
```

若数据目录中存在旧版 `data.json` 与 `cave.json`，首次启动会自动导入 SQLite，且不会删除旧文件。

## 命令

| 群聊命令 | 功能 | 权限 |
| --- | --- | --- |
| `cave` | 随机抽取已审核内容 | 所有人；白名单 A 跳过冷却 |
| `cave -a 内容` / 回复后 `cave -a` | 投稿 | 所有人 |
| `cave -g ID` / `cave -r ID` | 查看 / 删除 | 白名单 A |
| `cave -m` | 查看本群未读处理动态 | 所有人 |
| `cave -c 数值 sec|min|hour` | 设置本群冷却 | SUPERUSER |
| `cave -wAa/-wAr/-wAg` | 增删查本群白名单 A | SUPERUSER |
| `cave -wBa/-wBr/-wBg` | 增删查全局白名单 B | 管理者或 SUPERUSER |

私聊审核命令：`setcave -t ID|all`、`-f ID|all`、`-e ID`、`-l`。权限为白名单 B、管理者或 SUPERUSER。

数据使用 SQLite WAL 模式和事务写入；图片异步下载到数据目录。被拒绝或删除的记录会保留状态，便于审核查询和动态展示。

## 开发

```bash
pip install -e ".[test]"
pytest
```

本项目依据 MIT 许可证发布，并基于 hmzz804 的原始 `nonebot_plugin_cave` 行为重新实现。
