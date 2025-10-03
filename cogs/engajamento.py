import discord
from discord.ext import commands, tasks
import random
import asyncio
from datetime import date, datetime, timedelta

class Engajamento(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_manager = self.bot.db_manager
        self.user_chat_cooldowns = {}
        
        self.recompensar_voz.start()
        self.enviar_mensagem_engajamento.start()
        print("Módulo de Engajamento pronto. A iniciar tarefas de renda passiva.")
        
        self.mensagens_engajamento = [
            "Lembrete amigável: participar nos eventos é a melhor forma de juntar moedas para aquele item dos sonhos na `!loja`! 👀",
            "Sabia que você ganha moedas só por estar em call? Junte-se à conversa e veja seu `!saldo` a crescer! 💸",
            "Ficar de olho no canal de anúncios pode render umas moedas extras! Reaja às mensagens para não perder nada. 😉",
            "Alguém aí a pensar em comprar algo na `!loja`? Continuem a participar nas atividades para juntar moedas! 💪",
            "A economia da guilda é movida por vocês! Cada evento, cada call, cada mensagem ajuda a fortalecer a nossa comunidade (e a sua carteira!)."
        ]

    def cog_unload(self):
        self.recompensar_voz.cancel()
        self.enviar_mensagem_engajamento.cancel()

    @tasks.loop(minutes=5)
    async def recompensar_voz(self):
        recompensa_voz = int(self.db_manager.get_config_value('recompensa_voz', '0'))
        limite_minutos_voz = int(self.db_manager.get_config_value('limite_voz', '0'))
        
        if recompensa_voz == 0 or limite_minutos_voz == 0:
            return

        economia_cog = self.bot.get_cog('Economia')
        if not economia_cog:
            return

        hoje = date.today()

        with self.db_manager.get_connection() as conn:
            with conn.cursor() as cursor:
                for guild in self.bot.guilds:
                    for channel in guild.voice_channels:
                        for member in channel.members:
                            if not member.bot and not member.voice.self_mute and not member.voice.self_deaf:
                                cursor.execute("SELECT valor FROM renda_passiva_log WHERE user_id = %s AND tipo = 'voz' AND data = %s", (member.id, hoje))
                                tempo_acumulado = cursor.fetchone()
                                tempo_acumulado = tempo_acumulado[0] if tempo_acumulado else 0

                                if tempo_acumulado < limite_minutos_voz:
                                    novo_tempo = tempo_acumulado + 5
                                    cursor.execute(
                                        "INSERT INTO renda_passiva_log (user_id, tipo, data, valor) VALUES (%s, 'voz', %s, %s) ON CONFLICT (user_id, tipo, data) DO UPDATE SET valor = EXCLUDED.valor",
                                        (member.id, hoje, novo_tempo)
                                    )
                                    await economia_cog.depositar(member.id, recompensa_voz, "Renda Passiva (Voz)")
                conn.commit()
    
    @recompensar_voz.before_loop
    async def antes_recompensar_voz(self):
        await self.bot.wait_until_ready()

    @tasks.loop(hours=3)
    async def enviar_mensagem_engajamento(self):
        try:
            canal_id = int(self.db_manager.get_config_value('canal_batepapo', '0'))
            if canal_id == 0:
                return 

            canal = self.bot.get_channel(canal_id)
            if not canal:
                return

            membros_online = [m for m in canal.guild.members if m.status != discord.Status.offline and not m.bot]
            if not membros_online:
                return

            membro_sorteado = random.choice(membros_online)
            mensagem = random.choice(self.mensagens_engajamento)
            
            await canal.send(f"Ei, {membro_sorteado.mention}! {mensagem}")

        except Exception as e:
            print(f"Erro na tarefa de mensagem de engajamento: {e}")

    @enviar_mensagem_engajamento.before_loop
    async def antes_de_enviar_mensagem(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(random.randint(60, 300))

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or message.guild is None or message.content.startswith(self.bot.command_prefix):
            return

        recompensa_chat = int(self.db_manager.get_config_value('recompensa_chat', '0'))
        limite_chat = int(self.db_manager.get_config_value('limite_chat', '0'))
        cooldown_chat = int(self.db_manager.get_config_value('cooldown_chat', '60'))

        if recompensa_chat == 0 or limite_chat == 0:
            return

        user_id = message.author.id
        agora = datetime.now()
        
        if user_id in self.user_chat_cooldowns:
            if agora < self.user_chat_cooldowns[user_id]:
                return

        hoje = date.today()
        
        with self.db_manager.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT valor FROM renda_passiva_log WHERE user_id = %s AND tipo = 'chat' AND data = %s", (user_id, hoje))
                moedas_ganhas = cursor.fetchone()
                moedas_ganhas = moedas_ganhas[0] if moedas_ganhas else 0

                if moedas_ganhas < limite_chat:
                    nova_quantidade = moedas_ganhas + recompensa_chat
                    cursor.execute(
                        "INSERT INTO renda_passiva_log (user_id, tipo, data, valor) VALUES (%s, 'chat', %s, %s) ON CONFLICT (user_id, tipo, data) DO UPDATE SET valor = EXCLUDED.valor",
                        (user_id, hoje, nova_quantidade)
                    )
                    
                    economia_cog = self.bot.get_cog('Economia')
                    await economia_cog.depositar(user_id, recompensa_chat, "Renda Passiva (Chat)")
                    
                    self.user_chat_cooldowns[user_id] = agora + timedelta(seconds=cooldown_chat)
            conn.commit()

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if not payload.guild_id or payload.member.bot:
            return

        recompensa_reacao = int(self.db_manager.get_config_value('recompensa_reacao', '0'))
        canal_anuncios_id = int(self.db_manager.get_config_value('canal_anuncios', '0'))

        if recompensa_reacao == 0 or canal_anuncios_id == 0 or payload.channel_id != canal_anuncios_id:
            return
        
        user_id = payload.member.id
        message_id = payload.message_id
        chave_transacao = f"Reação Anúncio {message_id}"

        with self.db_manager.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT id FROM transacoes WHERE user_id = %s AND descricao = %s", (user_id, chave_transacao))
                if cursor.fetchone():
                    return # Já foi recompensado por esta reação
                
                economia_cog = self.bot.get_cog('Economia')
                await economia_cog.depositar(user_id, recompensa_reacao, chave_transacao)
            conn.commit()


async def setup(bot):
    await bot.add_cog(Engajamento(bot))

