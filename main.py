import re
import time
import random
from datetime import datetime

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

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

CRAZY_THURSDAY_REGEX_STR = (
    r"(疯狂星期四|v我50|V我50|v50|V50|微我50|微信转账50|转我50|"
    r"肯德基.*星期四|星期四.*肯德基|KFC.*星期四|crazy.*thursday|"
    r"今天是星期四|又到星期四|过星期四|疯狂星期|星期四.*v我|"
    r"v我.*50|转.*50.*块|打.*50)"
)


@register("kfc_crazy_thursday", "YourName", "疯狂星期四秦始皇马甲回复", "1.0.0")
class KFCCrazyThursdayPlugin(Star):
    """检测UMO白名单内会话的疯狂星期四话术，以秦始皇口吻随机回复。"""

    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.config = config if config else {}
        self._cooldowns: dict[str, float] = {}

    def _parse_list(self, raw: str) -> list[str]:
        if not raw or not raw.strip():
            return []
        return [item.strip() for item in re.split(r'[;；,\n，]', raw) if item.strip()]

    def _get_whitelist(self) -> list[str]:
        return self._parse_list(self.config.get("whitelist", ""))

    def _get_cooldown(self) -> int:
        try:
            return max(0, int(self.config.get("cooldown_seconds", 120)))
        except (ValueError, TypeError):
            return 120

    def _is_only_thursday(self) -> bool:
        return bool(self.config.get("only_thursday", False))

    def _is_cooldown_ok(self, sender_id: str) -> bool:
        cooldown = self._get_cooldown()
        if cooldown <= 0:
            return True
        now = time.time()
        if now - self._cooldowns.get(sender_id, 0) >= cooldown:
            self._cooldowns[sender_id] = now
            return True
        return False

    def _is_thursday(self) -> bool:
        return datetime.now().weekday() == 3

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

            if not self._is_cooldown_ok(sender_id):
                return

            response = random.choice(QIN_RESPONSES)
            event.should_call_llm(False)
            event.stop_event()

            logger.info(f"[疯狂星期四] 已回复 {sender_name}({sender_id}) {umo}")
            yield event.plain_result(response)

        except Exception as e:
            logger.error(f"[疯狂星期四] 异常: {e}", exc_info=True)
