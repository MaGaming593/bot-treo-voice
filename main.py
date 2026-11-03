import os
import sys
import asyncio
import logging
from typing import List, Set
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")

from aiohttp import web
import discord
from discord.ext import tasks

# Cấu hình logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("MultiVoice")

load_dotenv()

TOKEN_FILE = "tokens.txt"

# Cấu hình từ .env
admin_ids_str = os.getenv("ADMIN_IDS", "").strip()
ADMIN_IDS: Set[int] = {
    int(x.strip()) for x in admin_ids_str.split(",") if x.strip().isdigit()
}

PREFIX = os.getenv("COMMAND_PREFIX", "!").strip()
SELF_DEAF = os.getenv("SELF_DEAF", "True").strip().lower() in ("true", "1", "yes")
SELF_MUTE = os.getenv("SELF_MUTE", "True").strip().lower() in ("true", "1", "yes")
AUTO_JOIN = os.getenv("AUTO_JOIN_ON_START", "True").strip().lower() in ("true", "1", "yes")
DEFAULT_VOICE_ID = os.getenv("VOICE_CHANNEL_ID", "").strip()


def load_tokens() -> List[str]:
    """Đọc danh sách token từ tokens.txt hoặc từ .env."""
    tokens = []
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    tokens.append(line)

    if not tokens:
        env_tokens = os.getenv("BOT_TOKENS", "") or os.getenv("USER_TOKENS", "")
        if env_tokens:
            tokens = [
                t.strip()
                for t in env_tokens.split(",")
                if t.strip() and not t.strip().startswith("your_")
            ]

    return tokens


class UserVoiceClient(discord.Client):
    """Client đại diện cho từng tài khoản người dùng (User Account)."""

    def __init__(self, index: int, total: int, token: str):
        super().__init__()
        self.index = index
        self.total = total
        self.token = token
        self.target_channel_id: int | None = (
            int(DEFAULT_VOICE_ID) if DEFAULT_VOICE_ID.isdigit() else None
        )
        self._is_connecting = False

    async def on_ready(self):
        logger.info(
            f"[{self.index}/{self.total}] ✅ Đăng nhập thành công: {self.user.name}#{self.user.discriminator} (ID: {self.user.id})"
        )

        # Bật vòng lặp watchdog kiểm tra kết nối định kỳ
        if not self.voice_watchdog.is_running():
            self.voice_watchdog.start()

        # Tự động vào phòng voice khi khởi động (nếu bật AUTO_JOIN)
        if AUTO_JOIN and self.target_channel_id:
            # So le thời gian vào phòng: mỗi acc cách nhau 2.5s để trông tự nhiên
            stagger_delay = (self.index - 1) * 2.5
            if stagger_delay > 0:
                await asyncio.sleep(stagger_delay)
            await self.connect_target_voice()

    async def connect_target_voice(self, channel_id: int | None = None):
        """Kết nối vào phòng voice chỉ định."""
        if channel_id:
            self.target_channel_id = channel_id

        if not self.target_channel_id or self._is_connecting:
            return

        self._is_connecting = True
        try:
            channel = self.get_channel(self.target_channel_id)
            if channel is None:
                try:
                    channel = await self.fetch_channel(self.target_channel_id)
                except Exception as e:
                    logger.error(
                        f"[{self.index}/{self.total}] Không tìm thấy phòng voice ID {self.target_channel_id}: {e}"
                    )
                    return

            if not isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
                logger.error(
                    f"[{self.index}/{self.total}] Channel ID {self.target_channel_id} không phải là Voice Channel!"
                )
                return

            voice_client = channel.guild.voice_client

            if voice_client is None:
                logger.info(
                    f"[{self.index}/{self.total}] Đang kết nối vào #{channel.name} ({channel.guild.name})..."
                )
                await channel.connect(
                    reconnect=True,
                    self_deaf=SELF_DEAF,
                    self_mute=SELF_MUTE,
                )
                logger.info(
                    f"[{self.index}/{self.total}] -> Đã vào phòng: #{channel.name}!"
                )
            elif not voice_client.is_connected():
                try:
                    await voice_client.disconnect(force=True)
                except Exception:
                    pass
                await channel.connect(
                    reconnect=True,
                    self_deaf=SELF_DEAF,
                    self_mute=SELF_MUTE,
                )
            elif voice_client.channel.id != self.target_channel_id:
                logger.info(
                    f"[{self.index}/{self.total}] Đang chuyển sang phòng: #{channel.name}..."
                )
                await voice_client.move_to(channel)
        except Exception as e:
            logger.error(f"[{self.index}/{self.total}] Lỗi kết nối voice: {e}")
        finally:
            self._is_connecting = False

    async def disconnect_voice(self):
        """Rời khỏi phòng voice."""
        self.target_channel_id = None
        for vc in self.voice_clients:
            try:
                await vc.disconnect(force=True)
                logger.info(f"[{self.index}/{self.total}] Đã rời phòng voice.")
            except Exception:
                pass

    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        """Tự động xử lý khi chính tài khoản bị đẩy xuống phòng AFK hoặc bị disconnect."""
        if member.id == self.user.id and self.target_channel_id:
            # 1. Bị ngắt kết nối hoàn toàn
            if after.channel is None:
                logger.warning(
                    f"[{self.index}/{self.total}] Bị ngắt kết nối voice! Đang tự động kết nối lại sau 3s..."
                )
                await asyncio.sleep(3)
                await self.connect_target_voice()
            # 2. Bị chuyển sang phòng khác (ví dụ Discord tự động đẩy sang phòng AFK)
            elif after.channel.id != self.target_channel_id:
                logger.warning(
                    f"[{self.index}/{self.total}] Phát hiện bị đẩy sang phòng #{after.channel.name} (AFK)! Đang tự động nhảy về lại phòng chỉ định sau 2s..."
                )
                await asyncio.sleep(2)
                await self.connect_target_voice()

    async def on_message(self, message: discord.Message):
        # Không xử lý tin nhắn từ chính mình
        if message.author.id == self.user.id:
            return

        # Chỉ xử lý lệnh nếu người gửi là Admin
        if ADMIN_IDS and message.author.id not in ADMIN_IDS:
            return

        content = message.content.strip()

        # Lệnh !join
        if content.startswith(f"{PREFIX}join"):
            parts = content.split()
            target_chan = None

            if len(parts) > 1 and parts[1].isdigit():
                chan_id = int(parts[1])
                target_chan = self.get_channel(chan_id)
            elif message.author.voice and message.author.voice.channel:
                target_chan = message.author.voice.channel

            if target_chan and isinstance(
                target_chan, (discord.VoiceChannel, discord.StageChannel)
            ):
                # So le thời gian vào
                delay = (self.index - 1) * 2.0
                await asyncio.sleep(delay)
                await self.connect_target_voice(target_chan.id)
                if self.index == 1:
                    await message.add_reaction("✅")

        # Lệnh !leave
        elif content.startswith(f"{PREFIX}leave"):
            await self.disconnect_voice()
            if self.index == 1:
                await message.add_reaction("👋")

        # Lệnh !status
        elif content.startswith(f"{PREFIX}status"):
            for vc in self.voice_clients:
                if vc.is_connected() and vc.channel:
                    await message.channel.send(
                        f"👤 **{self.user.name}** đang treo tại: `#{vc.channel.name}`"
                    )
                    return
            await message.channel.send(
                f"👤 **{self.user.name}** hiện chưa vào phòng voice."
            )

    @tasks.loop(seconds=30)
    async def voice_watchdog(self):
        """Tự động kiểm tra và kết nối lại nếu bị ngắt kết nối hoặc bị văng sang phòng AFK."""
        if not self.is_ready() or not self.target_channel_id:
            return

        channel = self.get_channel(self.target_channel_id)
        if channel and isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
            voice_client = channel.guild.voice_client
            if (
                voice_client is None
                or not voice_client.is_connected()
                or voice_client.channel is None
                or voice_client.channel.id != self.target_channel_id
            ):
                logger.warning(
                    f"[{self.index}/{self.total}] Watchdog phát hiện tài khoản không ở đúng phòng target (bị đẩy sang AFK hoặc disconnect). Đang kết nối lại..."
                )
                await self.connect_target_voice()

    @voice_watchdog.before_loop
    async def before_voice_watchdog(self):
        await self.wait_until_ready()


async def run_single_client(client: UserVoiceClient):
    try:
        await client.start(client.token)
    except discord.LoginFailure:
        logger.error(f"[{client.index}/{client.total}] Token không hợp lệ hoặc đã hết hạn!")
    except Exception as e:
        logger.error(f"[{client.index}/{client.total}] Lỗi: {e}")


async def keep_alive_ping(request):
    """Phản hồi HTTP 200 OK cho UptimeRobot / Cloud Health Check."""
    return web.Response(text="Bot Discord Voice is Running 24/7!", status=200)


async def start_keep_alive_server():
    """Khởi chạy web server cổng 8080 (hoặc PORT do Cloud cung cấp) để chống ngủ đông."""
    port = int(os.getenv("PORT", 8080))
    app = web.Application()
    app.router.add_get("/", keep_alive_ping)
    app.router.add_get("/ping", keep_alive_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(
        f"🌐 Keep-Alive Web Server đang chạy tại cổng {port} (Sẵn sàng nhận ping từ UptimeRobot)"
    )


async def main():
    tokens = load_tokens()
    if not tokens:
        logger.error("❌ Không tìm thấy token nào!")
        logger.info(f"👉 Vui lòng dán danh sách token vào file '{TOKEN_FILE}' (mỗi token một dòng).")
        return

    # Khởi động Keep-Alive Web Server để Render / Koyeb không bị ngủ
    try:
        await start_keep_alive_server()
    except Exception as e:
        logger.warning(f"Không thể khởi động Web Server: {e}")

    logger.info("=" * 60)
    logger.info(f"🚀 KHỞI ĐỘNG HỆ THỐNG TREO VOICE CHO {len(tokens)} TÀI KHOẢN")
    logger.info("=" * 60)

    clients: List[UserVoiceClient] = []
    tasks = []

    for idx, token in enumerate(tokens, start=1):
        client = UserVoiceClient(index=idx, total=len(tokens), token=token)
        clients.append(client)
        tasks.append(run_single_client(client))

    try:
        await asyncio.gather(*tasks)
    finally:
        logger.info("Đang đóng các kết nối...")
        for c in clients:
            if not c.is_closed():
                await c.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[INFO] Đã nhận lệnh dừng. Đang thoát chương trình...")
