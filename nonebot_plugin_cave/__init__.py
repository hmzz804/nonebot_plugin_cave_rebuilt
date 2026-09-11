from nonebot.plugin import PluginMetadata

from .config import CaveConfig

__plugin_meta__ = PluginMetadata(
    name="回声洞",
    description="群友投稿、审核并随机抽取的回声洞",
    usage="/cave -h",
    type="application",
    homepage="https://github.com/hmzz804/nonebot_plugin_cave",
    config=CaveConfig,
    supported_adapters={"~onebot.v11"},
)

from . import handlers as handlers  # noqa: E402,F401
