import discord
from discord.ext import commands, tasks
from utils.permissions import check_permission_level
from datetime import datetime, timedelta
from utils.views import TaxaPrataView # Importa a View do novo ficheiro

class Taxas(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_manager = self.bot.db_manager
        self.cobrar_taxa.start()
        print("Módulo de Taxas pronto. A iniciar a tarefa de cobrança.")

    def cog_unload(self):
        self.cobrar_taxa.cancel()

    @tasks.loop(hours=24)
    async def cobrar_taxa(self):
        # A lógica da tarefa permanece a mesma...
        pass

    @cobrar_taxa.before_loop
    async def antes_de_cobrar_taxa(self):
        await self.bot.wait_until_ready()

    @commands.command(name="pagar-taxa")
    async def pagar_taxa(self, ctx):
        # A lógica do comando permanece a mesma...
        pass

    @commands.command(name="paguei-prata")
    async def paguei_prata(self, ctx):
        if not ctx.message.attachments:
            await ctx.send("❌ Você precisa de anexar um print (imagem) do comprovativo de pagamento.", ephemeral=True)
            return

        imagem = ctx.message.attachments[0]
        if not imagem.content_type.startswith('image/'):
            await ctx.send("❌ O anexo precisa de ser uma imagem.", ephemeral=True)
            return

        canal_aprovacao_id = int(self.bot.db_manager.get_config_value('canal_aprovacao', '0'))
        canal_aprovacao = self.bot.get_channel(canal_aprovacao_id)

        if not canal_aprovacao:
            await ctx.send("⚠️ O canal de aprovações não foi configurado. Contacte um administrador.", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="🧾 Pagamento de Taxa em Prata",
            description=f"**Membro:** {ctx.author.mention} (`{ctx.author.id}`)\n"
                        f"Enviou um comprovativo de pagamento da taxa em prata.",
            color=discord.Color.orange()
        )
        embed.set_image(url=imagem.url)
        embed.set_footer(text="Aguardando aprovação da Staff...")
        
        view = TaxaPrataView(self.bot)

        try:
            msg_aprovacao = await canal_aprovacao.send(embed=embed, view=view)
            
            with self.db_manager.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO submissoes_taxa (message_id, user_id, status, url_imagem) VALUES (%s, %s, %s, %s) ON CONFLICT (message_id) DO UPDATE SET user_id = EXCLUDED.user_id, status = EXCLUDED.status, url_imagem = EXCLUDED.url_imagem",
                        (msg_aprovacao.id, ctx.author.id, 'pendente', imagem.url)
                    )
                conn.commit()

            await ctx.message.add_reaction("✅")
            await ctx.send("✅ Comprovativo enviado para análise! A sua situação será regularizada assim que um staff aprovar.", ephemeral=True, delete_after=15)
        
        except Exception as e:
            await ctx.send("❌ Ocorreu um erro ao enviar o seu comprovativo.", ephemeral=True)
            print(f"Erro no comando paguei-prata: {e}")

    # ... outros comandos de configuração ...

async def setup(bot):
    await bot.add_cog(Taxas(bot))

