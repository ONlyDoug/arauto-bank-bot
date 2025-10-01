import discord
from discord.ext import commands, tasks
import contextlib
from datetime import date, datetime, timedelta
from utils.permissions import check_permission_level

class Engajamento(commands.Cog):
    """
    Cog para gerir recompensas de atividade (voz, chat, reações)
    e os comandos de configuração associados.
    """
    def __init__(self, bot):
        self.bot = bot
        # Cooldown de 60 segundos por membro para recompensas de chat
        self._chat_cooldown = commands.CooldownMapping.from_cooldown(1, 60.0, commands.BucketType.user)

    def cog_unload(self):
        self.recompensar_voz.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        print("Módulo de Engajamento pronto. A iniciar tarefas.")
        self.recompensar_voz.start()

    # =================================================================================
    # Funções Auxiliares
    # =================================================================================

    @contextlib.contextmanager
    def get_db_connection(self):
        conn = None
        try:
            conn = self.bot.db_pool.getconn()
            yield conn
        finally:
            if conn: self.bot.db_pool.putconn(conn)
    
    async def get_atividade_diaria(self, user_id: int):
        """Obtém ou cria o registo de atividade diária para um usuário."""
        today = date.today()
        with self.get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT minutos_voz, moedas_chat FROM atividade_diaria WHERE user_id = %s AND data = %s",
                    (user_id, today)
                )
                result = cursor.fetchone()
                if result:
                    return result
                else:
                    cursor.execute(
                        "INSERT INTO atividade_diaria (user_id, data) VALUES (%s, %s) ON CONFLICT (user_id, data) DO NOTHING",
                        (user_id, today)
                    )
                    conn.commit()
                    return 0, 0 # (minutos_voz, moedas_chat)
    
    # =================================================================================
    # Tarefa de Renda Passiva por Voz
    # =================================================================================

    @tasks.loop(minutes=5)
    async def recompensar_voz(self):
        if not self.bot.guilds: return
        guild = self.bot.guilds[0]
        
        admin_cog = self.bot.get_cog('Admin')
        economia_cog = self.bot.get_cog('Economia')
        if not admin_cog or not economia_cog: return

        try:
            recompensa_voz = int(admin_cog.get_config_value('recompensa_voz', '0'))
            limite_voz_minutos = int(admin_cog.get_config_value('limite_voz', '0'))
        except (ValueError, TypeError): return
        
        if not recompensa_voz or not limite_voz_minutos: return

        for channel in guild.voice_channels:
            for member in channel.members:
                if member.bot or member.voice.self_mute or member.voice.self_deaf:
                    continue

                minutos_voz_hoje, _ = await self.get_atividade_diaria(member.id)
                
                if minutos_voz_hoje < limite_voz_minutos:
                    await economia_cog.update_saldo(member.id, recompensa_voz, "renda_passiva_voz", "Atividade em canal de voz")
                    
                    with self.get_db_connection() as conn:
                        with conn.cursor() as cursor:
                            cursor.execute(
                                "UPDATE atividade_diaria SET minutos_voz = minutos_voz + 5 WHERE user_id = %s AND data = %s",
                                (member.id, date.today())
                            )
                        conn.commit()

    @recompensar_voz.before_loop
    async def before_recompensar_voz(self):
        await self.bot.wait_until_ready()

    # =================================================================================
    # Eventos de Renda (Chat e Reações)
    # =================================================================================

    @commands.Cog.listener('on_message')
    async def on_message(self, message):
        if message.author.bot or not message.guild or message.content.startswith(self.bot.command_prefix):
            return

        bucket = self._chat_cooldown.get_bucket(message)
        retry_after = bucket.update_rate_limit()
        if retry_after: return # Ignora se estiver em cooldown

        admin_cog = self.bot.get_cog('Admin')
        economia_cog = self.bot.get_cog('Economia')
        
        try:
            recompensa_chat = int(admin_cog.get_config_value('recompensa_chat', '0'))
            limite_chat_moedas = int(admin_cog.get_config_value('limite_chat', '0'))
        except (ValueError, TypeError): return

        if not recompensa_chat or not limite_chat_moedas: return

        _, moedas_chat_hoje = await self.get_atividade_diaria(message.author.id)

        if moedas_chat_hoje < limite_chat_moedas:
            # Garante que não ultrapassa o limite
            recompensa_final = min(recompensa_chat, limite_chat_moedas - moedas_chat_hoje)
            
            await economia_cog.update_saldo(message.author.id, recompensa_final, "renda_passiva_chat", "Atividade no chat")
            
            with self.get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "UPDATE atividade_diaria SET moedas_chat = moedas_chat + %s WHERE user_id = %s AND data = %s",
                        (recompensa_final, message.author.id, date.today())
                    )
                conn.commit()

    @commands.Cog.listener('on_raw_reaction_add')
    async def on_raw_reaction_add(self, payload):
        if not payload.guild_id or payload.member.bot:
            return
            
        admin_cog = self.bot.get_cog('Admin')
        economia_cog = self.bot.get_cog('Economia')

        try:
            canal_anuncios_id = int(admin_cog.get_config_value('canal_anuncios', '0'))
            recompensa_reacao = int(admin_cog.get_config_value('recompensa_reacao', '0'))
        except (ValueError, TypeError): return
        
        if not canal_anuncios_id or not recompensa_reacao or payload.channel_id != canal_anuncios_id:
            return

        with self.get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT 1 FROM reacoes_recompensadas WHERE message_id = %s AND user_id = %s",
                    (payload.message_id, payload.user_id)
                )
                if cursor.fetchone(): return # Já foi recompensado

                await economia_cog.update_saldo(payload.user_id, recompensa_reacao, "engajamento_reacao", f"Reação em anúncio ({payload.message_id})")
                
                cursor.execute(
                    "INSERT INTO reacoes_recompensadas (message_id, user_id) VALUES (%s, %s)",
                    (payload.message_id, payload.user_id)
                )
                conn.commit()
    
    # =================================================================================
    # Comandos de Configuração
    # =================================================================================
    
    @commands.group(name='config-engajamento', invoke_without_command=True)
    @check_permission_level(4)
    async def config_engajamento(self, ctx):
        """Grupo de comandos para configurar recompensas e limites de atividade. (Nível 4+)"""
        await ctx.send("Use `!config-engajamento recompensa <tipo> <valor>`, `... limite <tipo> <valor>`, ou `... canal anuncios <#canal>`.")
    
    @config_engajamento.command(name='recompensa')
    @check_permission_level(4)
    async def config_recompensa(self, ctx, tipo: str, valor: int):
        """Define o valor da recompensa. Tipos: voz, chat, reacao."""
        tipo = tipo.lower()
        if tipo not in ['voz', 'chat', 'reacao']:
            return await ctx.send("Tipo inválido. Use `voz`, `chat` ou `reacao`.")
        if valor < 0: return

        self.bot.get_cog('Admin').set_config_value(f'recompensa_{tipo}', str(valor))
        await ctx.send(f"✅ Recompensa de `{tipo}` definida para `{valor} GC`.")

    @config_engajamento.command(name='limite')
    @check_permission_level(4)
    async def config_limite(self, ctx, tipo: str, valor: int):
        """Define o limite diário. Tipos: voz (em minutos), chat (em moedas)."""
        tipo = tipo.lower()
        if tipo not in ['voz', 'chat']:
            return await ctx.send("Tipo inválido. Use `voz` (em minutos) ou `chat` (em moedas).")
        if valor < 0: return
        
        self.bot.get_cog('Admin').set_config_value(f'limite_{tipo}', str(valor))
        await ctx.send(f"✅ Limite diário de `{tipo}` definido para `{valor}`.")

    @config_engajamento.command(name='canal')
    @check_permission_level(4)
    async def config_canal(self, ctx, tipo: str, canal: discord.TextChannel):
        """Define um canal para uma função. Tipos: anuncios."""
        if tipo.lower() != 'anuncios':
            return await ctx.send("Tipo inválido. Use `anuncios`.")
            
        self.bot.get_cog('Admin').set_config_value('canal_anuncios', str(canal.id))
        await ctx.send(f"✅ O canal de anúncios foi definido como {canal.mention}.")


async def setup(bot):
    await bot.add_cog(Engajamento(bot))
