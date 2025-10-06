import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta
import random
import asyncio

class Engajamento(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.chat_cooldowns = {}
        self.recompensar_voz.start()
        self.enviar_mensagem_engajamento.start()
        print("Módulo de Engajamento pronto. A iniciar tarefas de renda passiva.")

    def cog_unload(self):
        self.recompensar_voz.cancel()
        self.enviar_mensagem_engajamento.cancel()
        
    async def registrar_renda_passiva(self, user_id, tipo, valor):
        data_hoje = datetime.utcnow().date()
        await self.bot.db_manager.execute_query(
            "INSERT INTO renda_passiva_log (user_id, tipo, data, valor) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (user_id, tipo, data) DO UPDATE SET valor = renda_passiva_log.valor + EXCLUDED.valor",
            (user_id, tipo, data_hoje, valor)
        )

    async def get_total_renda_passiva_diaria(self, user_id, tipo):
        data_hoje = datetime.utcnow().date()
        total = await self.bot.db_manager.execute_query(
            "SELECT valor FROM renda_passiva_log WHERE user_id = %s AND tipo = %s AND data = %s",
            (user_id, tipo, data_hoje),
            fetch="one"
        )
        return total[0] if total else 0

    @tasks.loop(minutes=5)
    async def recompensar_voz(self):
        try:
            recompensa_voz = int(await self.bot.db_manager.get_config_value('recompensa_voz', '0'))
            limite_voz_minutos = int(await self.bot.db_manager.get_config_value('limite_voz', '0'))

            if recompensa_voz == 0 or limite_voz_minutos == 0:
                return

            economia_cog = self.bot.get_cog('Economia')

            for guild in self.bot.guilds:
                for channel in guild.voice_channels:
                    membros_ativos = [m for m in channel.members if not m.bot and not m.voice.self_deaf and not m.voice.self_mute]
                    for member in membros_ativos:
                        try:
                            total_ganho_hoje = await self.get_total_renda_passiva_diaria(member.id, 'voz')
                            limite_diario_moedas = (limite_voz_minutos / 5) * recompensa_voz

                            if total_ganho_hoje < limite_diario_moedas:
                                await economia_cog.depositar(member.id, recompensa_voz, "Renda passiva por atividade em voz")
                                await self.registrar_renda_passiva(member.id, 'voz', recompensa_voz)
                            
                            # **CORREÇÃO CRÍTICA**: Cede o controlo ao loop de eventos após cada membro.
                            # Isto impede que a tarefa bloqueie o heartbeat do bot.
                            await asyncio.sleep(0)

                        except Exception as e:
                            print(f"Erro ao processar membro de voz {member.id}: {e}")
                            await asyncio.sleep(0) # Garante que o loop continue mesmo se um membro falhar

        except Exception as e:
            print(f"Erro fatal na tarefa de recompensar_voz: {e}")

    @recompensar_voz.before_loop
    async def before_recompensar_voz(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or message.guild is None or message.content.startswith('!'):
            return

        user_id = message.author.id
        agora = datetime.utcnow()

        recompensa_chat = int(await self.bot.db_manager.get_config_value('recompensa_chat', '0'))
        limite_chat = int(await self.bot.db_manager.get_config_value('limite_chat', '0'))
        cooldown_chat = int(await self.bot.db_manager.get_config_value('cooldown_chat', '60'))

        if recompensa_chat == 0 or limite_chat == 0:
            return

        total_ganho_hoje = await self.get_total_renda_passiva_diaria(user_id, 'chat')
        if total_ganho_hoje >= limite_chat:
            return

        last_message_time = self.chat_cooldowns.get(user_id)
        if last_message_time and (agora - last_message_time).total_seconds() < cooldown_chat:
            return

        self.chat_cooldowns[user_id] = agora
        economia_cog = self.bot.get_cog('Economia')
        await economia_cog.depositar(user_id, recompensa_chat, "Renda passiva por atividade no chat")
        await self.registrar_renda_passiva(user_id, 'chat', recompensa_chat)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if payload.member.bot:
            return

        canal_anuncios_id = await self.bot.db_manager.get_config_value('canal_anuncios', '0')
        recompensa_reacao = int(await self.bot.db_manager.get_config_value('recompensa_reacao', '0'))

        if recompensa_reacao == 0 or str(payload.channel_id) != canal_anuncios_id:
            return
        
        # Evitar dupla recompensa
        transacao_existente = await self.bot.db_manager.execute_query(
            "SELECT 1 FROM transacoes WHERE user_id = %s AND descricao = %s",
            (payload.user_id, f"Recompensa por reagir ao anúncio {payload.message_id}"),
            fetch="one"
        )
        if transacao_existente:
            return
        
        economia_cog = self.bot.get_cog('Economia')
        await economia_cog.depositar(payload.user_id, recompensa_reacao, f"Recompensa por reagir ao anúncio {payload.message_id}")
        await self.registrar_renda_passiva(payload.user_id, 'reacao', recompensa_reacao)


    @tasks.loop(hours=4)
    async def enviar_mensagem_engajamento(self):
        try:
            canal_id_str = await self.bot.db_manager.get_config_value("canal_batepapo", '0')
            if not canal_id_str or canal_id_str == '0':
                return

            canal = self.bot.get_channel(int(canal_id_str))
            if not canal:
                return
            
            membros_online = [m for m in canal.guild.members if not m.bot and m.status != discord.Status.offline]
            if not membros_online:
                return

            membro_sorteado = random.choice(membros_online)
            
            mensagens = [
                f"Ei {membro_sorteado.mention}, sabia que pode usar as moedas que ganha para comprar itens na `!loja`?",
                f"A participação em eventos é a melhor forma de juntar moedas! Fique de olho no canal de eventos, {membro_sorteado.mention}!",
                "Lembrem-se: cada moeda que vocês ganham é lastreada em prata de verdade! Use `!info-moeda` para ver a saúde da nossa economia.",
                f"{membro_sorteado.mention}, já viu o seu `!extrato` hoje? Acompanhe os seus ganhos!",
                "Quanto mais participamos, mais forte a guilda fica e mais recompensas todos ganham. Continuem com o bom trabalho!"
            ]
            
            embed = discord.Embed(
                description=random.choice(mensagens),
                color=discord.Color.random()
            )
            await canal.send(embed=embed)

        except Exception as e:
            print(f"Erro na tarefa de mensagem de engajamento: {e}")

    @enviar_mensagem_engajamento.before_loop
    async def before_enviar_mensagem_engajamento(self):
        await self.bot.wait_until_ready()
        print("Tarefa de mensagens de engajamento iniciada.")
        await asyncio.sleep(random.randint(60, 300))

async def setup(bot):
    await bot.add_cog(Engajamento(bot))

