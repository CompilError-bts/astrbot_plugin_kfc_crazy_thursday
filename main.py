import re
import time
import random
import asyncio
import urllib.request
from datetime import datetime

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

# 秦始皇专属话术库
QIN_RESPONSES = [
    "朕扫六合统天下，国库充盈，准了！\U0001f4b0",
    "大胆刁民，竟敢向朕讨要钱财？不过看你有趣，赏你50！",
    "朕乃始皇帝，岂会缺这50？拿去！",
    "长城还在修，军费紧张，但朕破例赐你50！",
    "徐福寻药未归，暂且先给你50应急！",
    "焚书坑儒朕都干了，这50又算得了什么？准了！",
    "李斯！去国库取50钱赏此人！",
    "朕今日心情不错，统一度量衡之余，再统一一下你的钱包！赏50！",
    "兵马俑都听朕指挥，区区50钱，何足挂齿？拿去！",
    "你可知罪？念你态度诚恳，朕网开一面，赐你50！",
    "朕修阿房宫花了不少，但50钱还是出得起的。准了！",
    "蒙恬！护送此人去取50钱，不得有误！",
    "赵高！传朕旨意，今日破例赏此人50钱！",
    "朕驾崩前最后一条旨意：V他50！",
    "朕已长生不老，但你的50还是要给的。准了！",
    "天命不可违，朕算了一卦，今日宜V你50！",
    "朕的版图东至大海、西至流沙，难道还差你50？赏！",
    "咸阳宫的砖都比你命硬，但你这50朕认了。拿去！",
    "朕一生征战无数，今天再战一次——为你V50！",
    "天下一统，四海归心，朕的心也归你了……的50。准了！",
]

# 疯狂星期四关键词匹配正则
CRAZY_THURSDAY_REGEX_STR = (
    r"(疯狂星期四|v我50|V我50|v50|V50|微我50|微信转账50|转我50|"
    r"肯德基.*星期四|星期四.*肯德基|KFC.*星期四|crazy.*thursday|"
    r"今天是星期四|又到星期四|过星期四|疯狂星期|星期四.*v我|"
    r"v我.*50|转.*50.*块|打.*50)"
)

API_URL = "https://vme.im/api/random?format=text"

# API 返回文本最大长度限制
MAX_RESPONSE_LENGTH = 500

# 同步 HTTP 请求函数（将在线程池中执行，避免阻塞事件循环）
def _do_fetch_api_copy() -> str:
    try:
        req = urllib.request.Request(API_URL, headers={
            "User-Agent": "Mozilla/5.0 AstrBot/1.0",
            "Accept": "text/plain",
        })
        with urllib.request.urlopen(req, timeout=5) as resp:
            text = resp.read().decode("utf-8", errors="replace").strip()
            return text
    except Exception as e:
        logger.warning(f"[疯狂星期四] API 获取文案失败: {e}")
        return ""


def _sanitize_text(text: str, max_length: int = MAX_RESPONSE_LENGTH) -> str:
    """对 API 返回文本进行安全过滤：长度截断 + 控制字符清理"""
    if not text:
        return ""
    # 移除控制字符（保留换行和制表符）
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    # 截断过长文本
    if len(text) > max_length:
        text = text[:max_length].rstrip() + "..."
    return text


def _parse_bool(value) -> bool:
    """安全的布尔值解析，兼容字符串/布尔/数值等类型"""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on")
    return False


def _parse_list(raw) -> list[str]:
    """安全的列表解析，兼容字符串和列表类型"""
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    if isinstance(raw, str):
        if not raw.strip():
            return []
        return [item.strip() for item in re.split(r'[;；,\n，]', raw) if item.strip()]
    return []


@register("kfc_crazy_thursday", "Compilerror", "疯狂星期四秦始皇马甲回复", "1.3.0")
class KFCCrazyThursdayPlugin(Star):
    """检测UMO白名单会话的疯狂星期四话术，以秦始皇口吻随机回复。"""

    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.config = config if config else {}
        self._cooldowns: dict[str, float] = {}

    def _get_whitelist(self) -> list[str]:
        return _parse_list(self.config.get("whitelist", ""))

    def _get_cooldown(self) -> int:
        try:
            return max(0, int(self.config.get("cooldown_seconds", 120)))
        except (ValueError, TypeError):
            return 120

    def _is_only_thursday(self) -> bool:
        return _parse_bool(self.config.get("only_thursday", False))

    def _is_api_enabled(self) -> bool:
        return _parse_bool(self.config.get("enable_api", False))

    def _is_cooldown_ok(self, cooldown_key: str) -> bool:
        cooldown = self._get_cooldown()
        if cooldown <= 0:
            return True
        now = time.time()
        if now - self._cooldowns.get(cooldown_key, 0) >= cooldown:
            self._cooldowns[cooldown_key] = now
            return True
        return False

    def _is_thursday(self) -> bool:
        return datetime.now().weekday() == 3

    async def _fetch_api_copy_async(self) -> str:
        """在线程池中执行同步 HTTP 请求，避免阻塞事件循环"""
        text = await asyncio.to_thread(_do_fetch_api_copy)
        return _sanitize_text(text)

    async def _get_response(self) -> str:
        """获取回复文案"""
        if self._is_api_enabled() and random.random() < 0.5:
            api_text = await self._fetch_api_copy_async()
            if api_text:
                logger.debug("[疯狂星期四] 使用 API 在线文案")
                return api_text
            logger.debug("[疯狂星期四] API 获取失败，回退到秦始皇马甲话术")
        return random.choice(QIN_RESPONSES)

    @filter.regex(CRAZY_THURSDAY_REGEX_STR)
    async def on_crazy_thursday(self, event: AstrMessageEvent):
        try:
            sender_id = event.get_sender_id()
            sender_name = event.get_sender_name()
            umo = event.unified_msg_origin
            msg_text = event.get_message_str()

            logger.debug(
                f"[疯狂星期四] 命中关键词 | umo={umo} | "
                f"sender={sender_name}({sender_id}) | "
                f"msg={msg_text[:50] if msg_text else ''}"
            )

            if self._is_only_thursday() and not self._is_thursday():
                return

            whitelist = self._get_whitelist()
            if not whitelist:
                return

            if umo not in whitelist:
                logger.debug(f"[疯狂星期四] 未命中白名单，跳过 (umo={umo})")
                return

            # 按 (umo, sender_id) 组合做冷却，避免跨会话互相影响
            cooldown_key = f"{umo}:{sender_id}"
            if not self._is_cooldown_ok(cooldown_key):
                return

            response = await self._get_response()
            event.should_call_llm(False)
            event.stop_event()

            logger.info(f"[疯狂星期四] 已回复 {sender_name}({sender_id}) {umo}")
            yield event.plain_result(response)

        except Exception as e:
            logger.error(f"[疯狂星期四] 异常: {e}", exc_info=True)
