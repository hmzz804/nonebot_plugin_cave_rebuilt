import nonebot

nonebot.init(driver="~none", localstore_use_cwd=True)
assert nonebot.load_plugin("nonebot_plugin_cave") is not None
