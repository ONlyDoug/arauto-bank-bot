import discord
from discord.ext import commands, tasks
from utils.permissions import check_permission_level
from datetime import datetime, timedelta
from utils.views import TaxaPrataView # Importa a View do novo ficheiro

class Taxas(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.cobrar_taxa.start()
        print("Módulo de Taxas pronto. A iniciar a tarefa de cobrança.")

    def cog_unload(self):
        self.cobrar_taxa.cancel()

    async def regularizar_membro(self, membro):
        """Função auxiliar para remover o cargo de inadimplente e adicionar o de membro."""
        cargo_inadimplente_id = int(self.bot.db_manager.get_config_value('cargo_inadimplente', '0'))
        cargo_membro_id = int(self.bot.db_manager.get_config_value('cargo_membro', '0'))

        if not cargo_inadimplente_id or not cargo_membro_id:
            return

        cargo_inadimplente = membro.guild.get_role(cargo_inadimplente_id)
        cargo_membro = membro.guild.get_role(cargo_membro_id)

        if cargo_inadimplente and cargo_inadimplente in membro.roles:
            await membro.remove_roles(cargo_inadimplente)
        if cargo_membro and cargo_membro not in membro.roles:
            await membro.add_roles(cargo_membro)

    @tasks.loop(hours=24)
    async def cobrar_taxa(self):
        # A lógica da tarefa de cobrança...
        pass

    @cobrar_taxa.before_loop
    async def antes_de_cobrar_taxa(self):
        await self.bot.wait_until_ready()

    @commands.command(name="pagar-taxa")
    async def pagar_taxa(self, ctx):
        valor_taxa = int(self.bot.db_manager.get_config_value('taxa_semanal_valor', '0'))
        if valor_taxa == 0:
            return await ctx.send("O sistema de taxas não está configurado.")

        economia_cog = self.bot.get_cog('Economia')
        try:
            await economia_cog.levantar(ctx.author.id, valor_taxa, "Pagamento de taxa semanal")
            await self.regularizar_membro(ctx.author)
            await ctx.send("✅ Taxa paga com sucesso! O seu acesso foi restaurado.")
        except ValueError:
            await ctx.send("❌ Você não tem saldo suficiente para pagar a taxa.")

    @commands.command(name="paguei-prata")
    async def paguei_prata(self, ctx):
        if not ctx.message.attachments:
            return await ctx.send("❌ Você precisa de anexar um print (imagem) do comprovativo de pagamento.", delete_after=15)

        imagem = ctx.message.attachments[0]
        if not imagem.content_type.startswith('image/'):
            return await ctx.send("❌ O anexo precisa de ser uma imagem.", delete_after=15)

        canal_aprovacao_id = int(self.bot.db_manager.get_config_value('canal_aprovacao', '0'))
        canal_aprovacao = self.bot.get_channel(canal_aprovacao_id)

        if not canal_aprovacao:
            return await ctx.send("⚠️ O canal de aprovações não foi configurado. Contacte um administrador.")
        
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
            
            with self.bot.db_manager.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO submissoes_taxa (message_id, user_id, status, url_imagem) VALUES (%s, %s, %s, %s) ON CONFLICT (message_id) DO UPDATE SET user_id = EXCLUDED.user_id, status = EXCLUDED.status, url_imagem = EXCLUDED.url_imagem",
                        (msg_aprovacao.id, ctx.author.id, 'pendente', imagem.url)
                    )
                conn.commit()

            await ctx.message.add_reaction("✅")
            await ctx.send("✅ Comprovativo enviado para análise! A sua situação será regularizada assim que um staff aprovar.", delete_after=15)
        
        except Exception as e:
            await ctx.send("❌ Ocorreu um erro ao enviar o seu comprovativo.")
            print(f"Erro no comando paguei-prata: {e}")

    # Comandos de configuração (definir-taxa, etc.)
    @commands.command(name="definir-taxa")
    @check_permission_level(4)
    async def definir_taxa(self, ctx, valor: int):
        if valor < 0:
            return await ctx.send("O valor da taxa não pode ser negativo.")
        self.bot.db_manager.set_config_value('taxa_semanal_valor', str(valor))
        await ctx.send(f"✅ Valor da taxa semanal definido para **{valor}** moedas.")

async def setup(bot):
    await bot.add_cog(Taxas(bot))

