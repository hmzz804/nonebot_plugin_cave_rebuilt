from nonebot.plugin import PluginMetadata

from .config import CaveConfig

__version__ = "2.0.1"

__plugin_meta__ = PluginMetadata(
    name="回声洞",
    description="群友投稿、审核并随机抽取的回声洞",
    usage="/cave -h",
    type="application",
    homepage="https://github.com/hmzz804/nonebot_plugin_cave_rebuilt",
    config=CaveConfig,
    supported_adapters={"~onebot.v11"},
)

from . import handlers as handlers  # noqa: E402,F401
