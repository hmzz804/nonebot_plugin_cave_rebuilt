# Changelog

## 2.0.2 - 2026-09-28

- Load plugin settings through NoneBot's `get_plugin_config` API.
- Delegate all data directory configuration to `nonebot-plugin-localstore`.

## 2.0.1 - 2026-09-11

- Use `nonebot-plugin-localstore` for the default persistent data directory.
- Add the NB-CLI installation command and complete PyPI project metadata.
- Correct the plugin homepage and runtime version display.

## 2.0.0 - 2026-09-11

- Rebuilt the plugin around SQLite WAL transactions.
- Added isolated domain, storage, media, and NoneBot adapter layers.
- Added legacy `data.json` / `cave.json` migration.
- Added asynchronous image persistence with timeout and size limits.
- Preserved cave投稿、审核、分群冷却、白名单和动态查询命令。
