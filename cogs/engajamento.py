import discord
from discord.ext import commands, tasks
import contextlib
from datetime import date, datetime
import time
import random
import asyncio

# Lista de mensagens de engajamento
MENSAGENS_ENGAJAMENTO = [
    {
        "titulo": " sabia que a sua presença vale ouro? (ou melhor, moedas!)",
        "texto": "Só por estar ativo em nossos canais de voz e texto, você já acumula moedas. Participe, converse e veja seu saldo crescer!"
    },
    {
        "titulo": " está de olho na loja?",
        "texto": "Novos itens podem surgir a qualquer momento! Acumule moedas participando dos eventos e esteja pronto para comprar aquele equipamento que você tanto quer."
    },
    {
        "titulo": " precisa de consumíveis para a próxima batalha?",
        "texto": "Use suas moedas na `!loja`! Poções, comidas e muito mais. Sua participação na guilda financia seus equipamentos."
    },
    {
        "titulo": ", um recado do Arauto Bank!",
        "texto": "Cada evento que você participa, cada anúncio que você lê... tudo isso te recompensa! A economia da guilda é feita por você e para você."
    },
    {
        "titulo": " quer dominar a economia?",
        "texto": "Fique de olho nos `!listareventos`. As maiores recompensas estão lá! Junte-se aos seus companheiros e encha o bolso de moedas."
    }
]

class Engajamento(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.user_chat_timestamps = {}
        self.recompensar_voz.start()
        self.enviar_mensagem_engajamento.start()

    def cog_unload(self):
        self.recompensar_voz.cancel()
        self.enviar_mensagem_engajamento.cancel()

    @contextlib.contextmanager
    def get_db_connection(self):
        conn = None
        try:
            conn = self.bot.db_pool.getconn()
            yield conn
        finally:
            if conn: self.bot.db_pool.putconn(conn)

    @tasks.loop(minutes=5)
    async def recompensar_voz(self):
        # ... (código existente)
        pass

    @recompensar_voz.before_loop
    async def before_recompensar_voz(self):
        await self.bot.wait_until_ready()
        print("Módulo de Engajamento pronto. A iniciar tarefas de renda passiva.")

    @tasks.loop(hours=3)
    async def enviar_mensagem_engajamento(self):
        try:
            admin_cog = self.bot.get_cog('Admin')
            if not admin_cog: return

            canal_id_str = admin_cog.get_config_value('canal_batepapo', '0')
            if canal_id_str == '0': return

            canal = self.bot.get_channel(int(canal_id_str))
            if not canal: return

            membros_online = [m for m in canal.guild.members if m.status != discord.Status.offline and not m.bot]
            if not membros_online: return

            membro_sorteado = random.choice(membros_online)
            mensagem_escolhida = random.choice(MENSAGENS_ENGAJAMENTO)

            embed = discord.Embed(
                title=f"Ei {membro_sorteado.display_name},{mensagem_escolhida['titulo']}",
                description=mensagem_escolhida['texto'],
                color=discord.Color.gold()
            )
            embed.set_footer(text="Arauto Bank | Sua participação é nossa maior riqueza.")
            
            await canal.send(embed=embed)

        except Exception as e:
            print(f"Erro na tarefa de mensagem de engajamento: {e}")
            
    @enviar_mensagem_engajamento.before_loop
    async def before_enviar_mensagem_engajamento(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(random.randint(60, 300))
        print("Tarefa de mensagens de engajamento iniciada.")

    @commands.Cog.listener()
    async def on_message(self, message):
        # ... (código existente)
        pass

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        # ... (código existente)
        pass

async def setup(bot):
    await bot.add_cog(Engajamento(bot))

