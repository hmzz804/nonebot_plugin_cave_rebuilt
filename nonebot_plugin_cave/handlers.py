from collections.abc import Iterable
from typing import Any

import httpx
from nonebot import get_driver, on_command, require
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupMessageEvent,
    Message,
    MessageSegment,
    PrivateMessageEvent,
)
from nonebot.exception import ActionFailed
from nonebot.log import logger
from nonebot.params import CommandArg

from . import __version__
from .config import CaveConfig
from .media import MediaStore
from .models import CaveEntry, CaveNotFound, CaveState, CooldownActive, InvalidState
from .storage import CaveRepository

require("nonebot_plugin_localstore")

import nonebot_plugin_localstore as localstore  # noqa: E402

config = CaveConfig.model_validate(get_driver().config.model_dump())
superusers = {str(user_id) for user_id in get_driver().config.superusers}
owners = config.cave_reviewers or superusers
repository = CaveRepository(
    config.cave_data_dir or localstore.get_plugin_data_dir(),
    owners,
    config.cave_default_cooldown,
    config.cave_default_cooldown_unit,
)
media_store = MediaStore(
    repository.image_dir, config.cave_download_timeout, config.cave_max_image_bytes
)

cave = on_command("cave", priority=10, block=True)
setcave = on_command("setcave", priority=10, block=True)


def _message_from_stored(segments: list[dict[str, Any]]) -> Message:
    message = Message()
    for segment in segments:
        if segment.get("type") == "text":
            data = segment.get("data", {})
            message += MessageSegment.text(data.get("text", segment.get("text", "")))
        elif segment.get("type") == "image":
            data = segment.get("data", {})
            file = data.get("file") or segment.get("path")
            if file:
                message += MessageSegment.image(file)
    return message


def _serialise_message(message: Message, strip_prefix: str | None = None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    stripped = False
    for segment in message:
        data = dict(segment.data)
        if segment.type == "text" and strip_prefix and not stripped:
            data["text"] = str(data.get("text", "")).lstrip()
            if data["text"].startswith(strip_prefix):
                data["text"] = data["text"][len(strip_prefix) :].lstrip()
            stripped = True
            if not data["text"]:
                continue
        if segment.type in {"text", "image"}:
            result.append({"type": segment.type, "data": data})
    return result


async def _nickname(bot: Bot, user_id: str) -> str:
    try:
        return str((await bot.get_stranger_info(user_id=int(user_id)))["nickname"])
    except ActionFailed:
        return user_id


async def _render_entry(bot: Bot, entry: CaveEntry, title: str = "回声洞") -> Message:
    name = await _nickname(bot, entry.contributor_id)
    return (
        Message(f"{title} —— ({entry.cave_id})\n\n")
        + _message_from_stored(entry.message)
        + Message(f"\n—— {name}")
    )


def _parse_target(message: Message, raw: str) -> str | None:
    for segment in message:
        if segment.type == "at" and segment.data.get("qq") != "all":
            return str(segment.data["qq"])
    digits = "".join(character for character in raw if character.isdigit())
    return digits or None


def _state_text(state: CaveState) -> str:
    return {
        CaveState.APPROVED: "审核通过，已加入回声洞",
        CaveState.PENDING: "收到投稿，等待审核",
        CaveState.REJECTED: "审核不通过",
        CaveState.DELETED: "已被删除",
    }[state]


async def _send_forward(
    bot: Bot,
    *,
    user_id: int | None = None,
    group_id: int | None = None,
    contents: Iterable[Message],
) -> None:
    nodes = [MessageSegment.node_custom(bot.self_id, "bot", content) for content in contents]
    if group_id is not None:
        await bot.send_group_forward_msg(group_id=group_id, messages=nodes)
    elif user_id is not None:
        await bot.send_private_forward_msg(user_id=user_id, messages=nodes)


@cave.handle()
async def handle_cave(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()) -> None:
    group_id, user_id = str(event.group_id), event.get_user_id()
    repository.ensure_group(group_id)
    raw = args.extract_plain_text().strip()
    if not raw:
        try:
            entry = repository.draw(group_id, repository.is_group_admin(group_id, user_id))
        except CaveNotFound:
            await cave.finish("库内暂无内容。")
        except CooldownActive as exc:
            await cave.finish(f"回声洞冷却中，请稍等 {exc.remaining_seconds:.0f} 秒。")
        await cave.finish(await _render_entry(bot, entry))

    command, _, value = raw.partition(" ")
    value = value.strip()
    if command == "-a":
        source = event.reply.message if event.reply else args
        contributor = str(event.reply.sender.user_id) if event.reply else user_id
        segments = _serialise_message(source, None if event.reply else "-a")
        if not segments:
            await cave.finish("请回复需要提交的内容，或在 -a 后添加需要提交的内容。")
        try:
            stored = await media_store.persist(segments)
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning(f"保存回声洞图片失败: {exc}")
            await cave.finish("图片保存失败，请稍后重试。")
        entry = repository.add(stored, contributor)
        notice = await _render_entry(bot, entry, "新的待审核回声洞") + Message(f" ({contributor})")
        for reviewer in repository.reviewers():
            try:
                await bot.send_private_msg(user_id=int(reviewer), message=notice)
            except ActionFailed:
                logger.warning(f"无法向审核员 {reviewer} 推送审核消息")
        await cave.finish(f"添加成功，序号为 {entry.cave_id}\n提交者: {contributor}")

    if command in {"-g", "-r"}:
        if not repository.is_group_admin(group_id, user_id):
            await cave.finish(f"无 {command} 权限。")
        try:
            cave_id = int(value)
            entry = repository.get(cave_id)
            if command == "-g":
                await cave.finish(await _render_entry(bot, entry))
            deleted = repository.delete(cave_id)
            media_store.delete_files(deleted.message)
            await cave.finish("删除成功。")
        except (ValueError, CaveNotFound):
            await cave.finish(f"索引为 {value or '?'} 的内容不存在或已被删除。")

    if command == "-c":
        if user_id not in superusers:
            await cave.finish("无 -c 权限。")
        parts = value.split()
        try:
            if len(parts) != 2:
                raise ValueError
            repository.set_cooldown(group_id, int(parts[0]), parts[1])
        except ValueError:
            await cave.finish("用法: cave -c <1-499> <sec|min|hour>")
        await cave.finish(f"成功修改本群回声洞冷却时间为 {parts[0]}{parts[1]}。")

    if command == "-m":
        if value:
            await cave.finish(f"多余的参数 {value}。")
        activities = repository.unread_activities(group_id)
        if not activities:
            await cave.finish("暂无新增的回声洞处理。")
        contents = [
            Message(
                f"回声洞 {item.cave_id}\n来自 {item.contributor_id}\n状态: {_state_text(item.state)}\n时间: {item.created_at.astimezone():%Y-%m-%d %H:%M:%S}"
            )
            for item in activities
        ]
        await _send_forward(bot, group_id=event.group_id, contents=contents)
        await cave.finish()

    if command.startswith("-w"):
        subcommand = command[2:].lower()
        if subcommand not in {"aa", "ar", "ag", "ba", "br", "bg"}:
            await cave.finish("无法识别白名单子命令。")
        list_name = subcommand[0]
        action = subcommand[1]
        allowed = (
            user_id in superusers
            if list_name == "a"
            else user_id in owners or user_id in superusers
        )
        if not allowed:
            await cave.finish("无白名单管理权限。")
        if action == "g":
            users = (
                repository.group_admins(group_id) if list_name == "a" else repository.reviewers()
            )
            await cave.finish(
                ("白名单 A" if list_name == "a" else "白名单 B")
                + ":\n"
                + ("\n".join(users) or "（空）")
            )
        target = _parse_target(args, value)
        if target is None:
            await cave.finish("请提供 QQ 号或 @ 用户。")
        enabled = action == "a"
        changed = (
            repository.set_group_admin(group_id, target, enabled)
            if list_name == "a"
            else repository.set_reviewer(target, enabled)
        )
        await cave.finish("操作成功。" if changed else "目标已处于该状态。")

    if command == "-h":
        await cave.finish(
            "cave: 随机抽取 | -a 投稿 | -g 查看 | -r 删除 | -m 动态 | -c 冷却 | -w 白名单"
        )
    if command == "-v":
        await cave.finish(f"nonebot-plugin-cave-rebuilt {__version__}")
    await cave.finish(f"无法将 {command} 识别为有效参数。")


@setcave.handle()
async def handle_setcave(
    bot: Bot, event: PrivateMessageEvent, args: Message = CommandArg()
) -> None:
    user_id = event.get_user_id()
    if not (repository.is_reviewer(user_id) or user_id in owners or user_id in superusers):
        await setcave.finish("无审核权限。")
    raw = args.extract_plain_text().strip()
    command, _, value = raw.partition(" ")
    value = value.strip()
    if command in {"-t", "-f"}:
        approved = command == "-t"
        if value == "all":
            count = repository.moderate_all(approved)
            await setcave.finish(f"已处理 {count} 条投稿。")
        try:
            entry = repository.moderate(int(value), approved)
        except ValueError:
            await setcave.finish("请提供有效序号或 all。")
        except (CaveNotFound, InvalidState):
            await setcave.finish("此序号不存在、已删除或已被审核。")
        await setcave.finish(
            f"操作成功，回声洞投稿 {entry.cave_id} {'通过' if approved else '未通过'}审核。"
        )
    if command == "-e":
        try:
            entry = repository.get(int(value))
        except (ValueError, CaveNotFound):
            await setcave.finish("此序号不存在。")
        await setcave.finish(f"回声洞投稿 {entry.cave_id}: {_state_text(entry.state)}。")
    if command == "-l":
        entries = repository.pending()
        if not entries:
            await setcave.finish("暂无待审核的回声洞投稿。")
        contents = [await _render_entry(bot, entry, "待审核回声洞") for entry in entries]
        await _send_forward(bot, user_id=event.user_id, contents=contents)
        await setcave.finish()
    await setcave.finish("用法: setcave -t <id|all> | -f <id|all> | -e <id> | -l")
