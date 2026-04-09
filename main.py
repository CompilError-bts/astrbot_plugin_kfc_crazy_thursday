import re
import time
import random
import asyncio
import json
import urllib.request
from datetime import datetime
from typing import Optional, Tuple, List

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

# 秦始皇专属话术库
QIN_RESPONSES = [
    "朕扫六合统天下，国库充盈，准了！💰",
    "大胆刁民，竟敢向朕讨要钱财？不过看你有趣，赏你50！",
    "朕乃始皇帝，岂会缺你50？拿去！",
    "长城还在修，军费紧张，但朕破例赏你50！",
    "徐福寻药未归，暂且先给你50应急！",
    "焚书坑儒朕都干了，区区50又算得了什么？准了！",
    "李斯！去国库取50钱赏此人！",
    "朕今日心情不错，统一度量衡之余，再统一一下你的钱包！赏50！",
    "兵马俑都听朕指挥，区区50钱，何足挂齿？拿去！",
    "你可知罪？念你态度诚恳，朕网开一面，赏你50！",
    "朕修阿房宫花了不少，这50钱还是出得起的。准了！",
    "蒙恬！护送此人去取50钱，不得有误！",
    "赵高！传朕旨意，今日破例赏此人50钱！",
    "朕驾崩前最后一条旨意：V我50！",
    "朕已长生不老，但你的50还是要给的。准了！",
    "天命不可违，朕算了一卦，今日宜V我50！",
    "朕的版图东至大海、西至流沙，难道还差你50？赏！",
    "咸阳宫的砖都比你的命硬，但你50朕认了。拿去！",
    "朕一生征战无数，今天再战一次——为你V50！",
    "天下一统，四海归心，朕的心也归你了……的50。准了！",
]

# 疯狂星期四关键词匹配正则
CRAZY_THURSDAY_REGEX_STR = (
    r"(疯狂星期四|v我50|V我50|v50|V50|微我50|微信转我50|转我50|"
    r"肯德基|KFC|kfc|crazy.*thursday|"
    r"今天是星期四|又到星期四|过星期四|疯狂星期|星期四.*v我|"
    r"v我.*50|转.*50.*块|打.*50)"
)

API_URL = "https://vme.im/api/random"

# API 返回文本最大长度限制
MAX_RESPONSE_LENGTH = 500

# 图片检测正则
IMAGE_PATTERN = r'!\[[^\]]*\]\(([^)]+)\)'

# 冷却字典最大容量（防止内存泄漏）
MAX_COOLDOWN_ENTRIES = 1000
COOLDOWN_CLEANUP_THRESHOLD = 200  # 当条目数超过此值时触发清理


def _do_fetch_api_json() -> Optional[dict]:
    """同步 HTTP 请求获取 JSON 数据（将在线程池中执行）"""
    try:
        req = urllib.request.Request(API_URL, headers={
            "User-Agent": "Mozilla/5.0 AstrBot/1.0",
            "Accept": "application/json",
        })
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = resp.read().decode("utf-8", errors="replace")
            return json.loads(data)
    except Exception as e:
        logger.warning(f"[疯狂星期四] API 获取文案失败: {e}")
        return None


def _sanitize_text(text: str, max_length: int = MAX_RESPONSE_LENGTH) -> str:
    """对 API 返回文本进行安全过滤：长度截断 + 控制字符清理"""
    if not text:
        return ""
    # 移除控制字符（保留换行和制表符）
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    # 截断过长文本
    if len(text) > max_length:
        text = text[:max_length].rstrip() + "..."
    return text


def _extract_images_from_body(body: str) -> List[str]:
    """从 Markdown 格式的 body 中提取图片 URL"""
    if not body:
        return []
    return re.findall(IMAGE_PATTERN, body)


def _parse_bool(value) -> bool:
    """安全的布尔值解析，兼容字符串/布尔/数值等类型"""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on")
    return False


def _parse_list(raw) -> List[str]:
    """安全的列表解析，兼容字符串和列表类型"""
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    if isinstance(raw, str):
        if not raw.strip():
            return []
        return [item.strip() for item in re.split(r'[;；,，]', raw) if item.strip()]
    return []


@register("kfc_crazy_thursday", "Compilerror", "疯狂星期四秦始皇马甲回复", "1.4.0")
class KFCCrazyThursdayPlugin(Star):
    """检测UMO白名单会话的疯狂星期四话术，以秦始皇口吻随机回复，支持图片发送。"""

    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.config = config if config else {}
        self._cooldowns: dict[str, float] = {}

    def _get_whitelist(self) -> List[str]:
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

    def _get_api_weight(self) -> float:
        """获取 API 调用权重（0.0-1.0），默认 0.5"""
        try:
            weight = float(self.config.get("api_weight", 0.5))
            return max(0.0, min(1.0, weight))
        except (ValueError, TypeError):
            return 0.5

    def _cleanup_expired_cooldowns(self):
        """清理过期的冷却条目"""
        cooldown = self._get_cooldown()
        if cooldown <= 0:
            return
        
        now = time.time()
        expired_keys = [
            key for key, timestamp in self._cooldowns.items()
            if now - timestamp >= cooldown
        ]
        for key in expired_keys:
            del self._cooldowns[key]
        
        # 如果条目数仍然过多，按时间戳清理最旧的
        if len(self._cooldowns) > MAX_COOLDOWN_ENTRIES:
            sorted_items = sorted(self._cooldowns.items(), key=lambda x: x[1])
            keys_to_remove = [k for k, _ in sorted_items[:len(self._cooldowns) - MAX_COOLDOWN_ENTRIES]]
            for key in keys_to_remove:
                del self._cooldowns[key]

    def _is_cooldown_ok(self, cooldown_key: str) -> bool:
        """检查冷却状态，自动清理过期条目"""
        cooldown = self._get_cooldown()
        if cooldown <= 0:
            return True
        
        # 惰性清理：当条目数过多时触发清理
        if len(self._cooldowns) > COOLDOWN_CLEANUP_THRESHOLD:
            self._cleanup_expired_cooldowns()
        
        now = time.time()
        if now - self._cooldowns.get(cooldown_key, 0) >= cooldown:
            self._cooldowns[cooldown_key] = now
            return True
        return False

    def _is_thursday(self) -> bool:
        return datetime.now().weekday() == 3

    async def _fetch_api_json_async(self) -> Optional[dict]:
        """在线程池中执行同步 HTTP 请求，避免阻塞事件循环"""
        return await asyncio.to_thread(_do_fetch_api_json)

    async def _get_response(self) -> Tuple[str, List[str]]:
        """
        获取回复内容
        返回: (文本内容, 图片URL列表)
        """
        if self._is_api_enabled() and random.random() < self._get_api_weight():
            api_data = await self._fetch_api_json_async()
            if api_data:
                body = api_data.get("body", "")
                if body:
                    # 提取图片
                    images = _extract_images_from_body(body)
                    if images:
                        logger.debug(f"[疯狂星期四] API 返回包含 {len(images)} 张图片")
                        # 清理 body 中的图片标记
                        text = re.sub(IMAGE_PATTERN, '', body).strip()
                        text = _sanitize_text(text)
                        return text, images
                    
                    # 纯文本
                    text = _sanitize_text(body)
                    if text:
                        logger.debug("[疯狂星期四] 使用 API 在线文案")
                        return text, []
            
            logger.debug("[疯狂星期四] API 获取失败，回退到秦始皇马甲话术")
        
        # 使用秦始皇话术
        return random.choice(QIN_RESPONSES), []

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

            # 星期四限定检查
            if self._is_only_thursday() and not self._is_thursday():
                return

            # 白名单检查
            whitelist = self._get_whitelist()
            if not whitelist:
                return

            if umo not in whitelist:
                logger.debug(f"[疯狂星期四] 未命中白名单，跳过 (umo={umo})")
                return

            # 冷却检查
            cooldown_key = f"{umo}:{sender_id}"
            if not self._is_cooldown_ok(cooldown_key):
                return

            # 获取回复
            text, images = await self._get_response()
            
            # 拦截 LLM 处理
            event.should_call_llm(False)
            event.stop_event()

            logger.info(f"[疯狂星期四] 已回复 {sender_name}({sender_id}) {umo}")

            # 发送消息
            if images:
                # 如果有图片，使用 chain_result 发送图文混合
                import astrbot.api.message_components as Comp
                chain = []
                if text:
                    chain.append(Comp.Plain(text))
                for img_url in images:
                    chain.append(Comp.Image.fromURL(img_url))
                yield event.chain_result(chain)
            else:
                # 纯文本
                yield event.plain_result(text)

        except Exception as e:
            logger.error(f"[疯狂星期四] 异常: {e}", exc_info=True)
