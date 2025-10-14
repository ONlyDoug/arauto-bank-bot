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
            "INSERT INTO renda_passiva_log (user_id, tipo, data, valor) VALUES ($1, $2, $3, $4) "
            "ON CONFLICT (user_id, tipo, data) DO UPDATE SET valor = renda_passiva_log.valor + EXCLUDED.valor",
            user_id, tipo, data_hoje, valor
        )

    async def get_total_renda_passiva_diaria(self, user_id, tipo):
        data_hoje = datetime.utcnow().date()
        total = await self.bot.db_manager.execute_query(
            "SELECT valor FROM renda_passiva_log WHERE user_id = $1 AND tipo = $2 AND data = $3",
            user_id, tipo, data_hoje,
            fetch="one"
        )
        return total['valor'] if total else 0

    @tasks.loop(minutes=5)
    async def recompensar_voz(self):
        try:
            configs = await self.bot.db_manager.get_all_configs(['recompensa_voz', 'limite_voz'])
            recompensa_voz = int(configs.get('recompensa_voz', '0'))
            limite_voz_minutos = int(configs.get('limite_voz', '0'))

            if recompensa_voz == 0 or limite_voz_minutos == 0:
                return

            economia_cog = self.bot.get_cog('Economia')

            for guild in self.bot.guilds:
                for channel in guild.voice_channels:
                    for member in channel.members:
                        if member.bot or not member.voice or member.voice.self_deaf or member.voice.self_mute:
                            continue
                        
                        try:
                            total_ganho_hoje = await self.get_total_renda_passiva_diaria(member.id, 'voz')
                            limite_diario_moedas = (limite_voz_minutos / 5) * recompensa_voz

                            if total_ganho_hoje < limite_diario_moedas:
                                await economia_cog.transferir_do_tesouro(member.id, recompensa_voz, "Renda passiva por atividade em voz")
                                await self.registrar_renda_passiva(member.id, 'voz', recompensa_voz)
                        except Exception as e:
                            print(f"Erro ao processar membro de voz {member.id}: {e}")
                        await asyncio.sleep(0)
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
        try:
            configs = await self.bot.db_manager.get_all_configs(['recompensa_chat', 'limite_chat', 'cooldown_chat'])
            recompensa_chat = int(configs.get('recompensa_chat', '0'))
            limite_chat = int(configs.get('limite_chat', '0'))
            cooldown_chat = int(configs.get('cooldown_chat', '60'))
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
            await economia_cog.transferir_do_tesouro(user_id, recompensa_chat, "Renda passiva por atividade no chat")
            await self.registrar_renda_passiva(user_id, 'chat', recompensa_chat)
        except Exception as e:
            print(f"Erro em on_message para {user_id}: {e}")

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if payload.member.bot:
            return

        try:
            configs = await self.bot.db_manager.get_all_configs(['canal_anuncios', 'recompensa_reacao'])
            canal_anuncios_id = configs.get('canal_anuncios', '0')
            recompensa_reacao = int(configs.get('recompensa_reacao', '0'))

            if recompensa_reacao == 0 or str(payload.channel_id) != canal_anuncios_id:
                return
            
            # --- LÓGICA DE CORREÇÃO DEFINITIVA ---
            # 1. VERIFICAR primeiro se a recompensa já foi atribuída.
            ja_reagiu = await self.bot.db_manager.execute_query(
                "SELECT 1 FROM reacoes_anuncios WHERE user_id = $1 AND message_id = $2",
                payload.user_id, payload.message_id,
                fetch="one"
            )
            
            if ja_reagiu:
                # Se a consulta retornar algo, o jogador já foi recompensado por esta reação.
                return

            # 2. Se não foi atribuída, INSERIR o registo e DEPOIS pagar.
            await self.bot.db_manager.execute_query(
                "INSERT INTO reacoes_anuncios (user_id, message_id) VALUES ($1, $2)",
                payload.user_id, payload.message_id
            )

            economia_cog = self.bot.get_cog('Economia')
            await economia_cog.transferir_do_tesouro(payload.user_id, recompensa_reacao, f"Recompensa por reagir ao anúncio {payload.message_id}")
            await self.registrar_renda_passiva(payload.user_id, 'reacao', recompensa_reacao)
        
        except Exception as e:
            print(f"Erro em on_raw_reaction_add para {payload.user_id}: {e}")

    # --- MELHORIA DE ENGAJAMENTO ---
    # A frequência foi aumentada para 2 horas para maior visibilidade.
    @tasks.loop(hours=2)
    async def enviar_mensagem_engajamento(self):
        try:
            canal_id_str = await self.bot.db_manager.get_config_value("canal_batepapo", '0')
            if not canal_id_str or canal_id_str == '0':
                return

            canal = self.bot.get_channel(int(canal_id_str))
            if not canal:
                print("AVISO: Canal de bate-papo para engajamento não encontrado.")
                return
            
            membros_online = [m for m in canal.guild.members if not m.bot and m.status != discord.Status.offline and m.status != discord.Status.dnd]
            if not membros_online:
                return

            membro_sorteado = random.choice(membros_online)
            
            # Mensagens foram diversificadas para aumentar o engajamento.
            mensagens = [
                f"Ei {membro_sorteado.mention}, sabia que pode usar as moedas que ganha para comprar itens na `!loja`?",
                f"A participação em eventos é a melhor forma de juntar moedas! Fique de olho com `!listareventos`, {membro_sorteado.mention}!",
                "Lembrem-se: cada moeda que vocês ganham é lastreada em prata de verdade! Use `!info-moeda` para ver a saúde da nossa economia.",
                f"{membro_sorteado.mention}, já viu o seu `!extrato` hoje? Acompanhe os seus ganhos e gastos!",
                "Quanto mais participamos, mais forte a guilda fica e mais recompensas todos ganham. Continuem com o bom trabalho!",
                f"Uma dica para {membro_sorteado.mention}: tempo em canais de voz gera renda passiva! Junte-se a um canal e veja a magia acontecer.",
                "Não sabe como um comando funciona? Use `!ajuda <nome_do_comando>` e eu explico tudo nos mínimos detalhes."
            ]
            
            embed = discord.Embed(description=random.choice(mensagens), color=discord.Color.random())
            await canal.send(embed=embed)

        except Exception as e:
            print(f"Erro na tarefa de mensagem de engajamento: {e}")

    @enviar_mensagem_engajamento.before_loop
    async def before_enviar_mensagem_engajamento(self):
        await self.bot.wait_until_ready()
        print("Tarefa de mensagens de engajamento iniciada.")
        # O tempo de espera inicial foi reduzido.
        await asyncio.sleep(random.randint(30, 120))


async def setup(bot):
    await bot.add_cog(Engajamento(bot))