import discord
from discord.ext import commands, tasks
import contextlib
from datetime import date, datetime, timedelta

class Engajamento(commands.Cog):
    """Cog para gerir as fontes de renda passiva e de engajamento."""
    def __init__(self, bot):
        self.bot = bot
        self.recompensar_voz.start()

    def cog_unload(self):
        self.recompensar_voz.cancel()

    @contextlib.contextmanager
    def get_db_connection(self):
        conn = None
        try:
            conn = self.bot.db_pool.getconn()
            yield conn
        finally:
            if conn: self.bot.db_pool.putconn(conn)
            
    async def get_atividade_diaria(self, user_id: int):
        hoje = date.today()
        with self.get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT minutos_voz, moedas_chat FROM atividade_diaria WHERE user_id = %s AND data = %s", (user_id, hoje))
                return cursor.fetchone() or (0, 0)

    async def update_atividade_diaria(self, user_id: int, minutos_voz: int = 0, moedas_chat: int = 0):
        hoje = date.today()
        with self.get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO atividade_diaria (user_id, data, minutos_voz, moedas_chat)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (user_id, data) DO UPDATE SET
                    minutos_voz = atividade_diaria.minutos_voz + EXCLUDED.minutos_voz,
                    moedas_chat = atividade_diaria.moedas_chat + EXCLUDED.moedas_chat;
                """, (user_id, hoje, minutos_voz, moedas_chat))
            conn.commit()

    @tasks.loop(minutes=5.0)
    async def recompensar_voz(self):
        await self.bot.wait_until_ready()
        admin_cog = self.bot.get_cog('Admin')
        economia_cog = self.bot.get_cog('Economia')
        if not admin_cog or not economia_cog: return

        recompensa_voz = int(admin_cog.get_config_value('recompensa_voz', '0'))
        limite_voz = int(admin_cog.get_config_value('limite_voz', '0'))
        if recompensa_voz == 0 or limite_voz == 0: return

        for guild in self.bot.guilds:
            for member in guild.members:
                if member.bot or not member.voice or member.voice.self_mute or member.voice.self_deaf:
                    continue
                
                minutos_ja_ganhos, _ = await self.get_atividade_diaria(member.id)
                if minutos_ja_ganhos < limite_voz:
                    await economia_cog.update_saldo(member.id, recompensa_voz, "renda_passiva_voz", "Atividade em canal de voz")
                    await self.update_atividade_diaria(member.id, minutos_voz=5)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or message.content.startswith(self.bot.command_prefix):
            return

        user_id = message.author.id
        cache_key = f"chat_cooldown:{user_id}"
        
        if self.bot.get_cog('Admin')._cache.get(cache_key): return
            
        admin_cog = self.bot.get_cog('Admin')
        economia_cog = self.bot.get_cog('Economia')

        recompensa_chat = int(admin_cog.get_config_value('recompensa_chat', '0'))
        limite_chat = int(admin_cog.get_config_value('limite_chat', '0'))
        if recompensa_chat == 0 or limite_chat == 0: return

        _, moedas_ja_ganhas = await self.get_atividade_diaria(user_id)
        if moedas_ja_ganhas < limite_chat:
            await economia_cog.update_saldo(user_id, recompensa_chat, "renda_passiva_chat", "Atividade no chat")
            await self.update_atividade_diaria(user_id, moedas_chat=recompensa_chat)
            
            self.bot.get_cog('Admin')._cache[cache_key] = True
            await asyncio.sleep(60)
            self.bot.get_cog('Admin')._cache.pop(cache_key, None)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if payload.member.bot: return

        admin_cog = self.bot.get_cog('Admin')
        canal_anuncios_id = int(admin_cog.get_config_value('canal_anuncios', '0'))
        if payload.channel_id != canal_anuncios_id: return

        recompensa_reacao = int(admin_cog.get_config_value('recompensa_reacao', '0'))
        if recompensa_reacao == 0: return

        with self.get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1 FROM reacoes_recompensadas WHERE message_id = %s AND user_id = %s", (payload.message_id, payload.user_id))
                if cursor.fetchone(): return
                
                cursor.execute("INSERT INTO reacoes_recompensadas (message_id, user_id) VALUES (%s, %s)", (payload.message_id, payload.user_id))
            conn.commit()

        economia_cog = self.bot.get_cog('Economia')
        await economia_cog.update_saldo(payload.user_id, recompensa_reacao, "recompensa_reacao", "Leitura de anúncio")

async def setup(bot):
    # Adiciona um cache simples ao Admin cog se não existir
    admin_cog = bot.get_cog('Admin')
    if admin_cog and not hasattr(admin_cog, '_cache'):
        admin_cog._cache = {}
    await bot.add_cog(Engajamento(bot))

