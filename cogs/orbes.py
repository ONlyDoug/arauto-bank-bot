import discord
from discord.ext import commands
from utils.permissions import check_permission_level
from utils.views import OrbeAprovacaoView # Importa a View do novo ficheiro

class Orbes(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_manager = self.bot.db_manager
        self.cores_orbe = {
            "verde": {"nome": "Verde", "cor": discord.Color.green()},
            "azul": {"nome": "Azul", "cor": discord.Color.blue()},
            "roxa": {"nome": "Roxa", "cor": discord.Color.purple()},
            "dourada": {"nome": "Dourada", "cor": discord.Color.gold()}
        }

    @commands.command(name="config-orbe")
    @check_permission_level(4)
    async def config_orbe(self, ctx, cor: str, valor: int):
        cor_lower = cor.lower()
        if cor_lower not in self.cores_orbe:
            await ctx.send(f"❌ Cor de orbe inválida. Use uma das seguintes: {', '.join(self.cores_orbe.keys())}.")
            return
        
        with self.db_manager.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO configuracoes (chave, valor) VALUES (%s, %s) ON CONFLICT (chave) DO UPDATE SET valor = EXCLUDED.valor",
                    (f"orbe_{cor_lower}", str(valor))
                )
            conn.commit()
        
        await ctx.send(f"✅ Recompensa para a orbe **{self.cores_orbe[cor_lower]['nome']}** definida para **{valor}** moedas.")

    @commands.command(name="orbe")
    async def orbe(self, ctx, cor: str, membros: commands.Greedy[discord.Member]):
        cor_lower = cor.lower()
        if cor_lower not in self.cores_orbe:
            await ctx.send(f"❌ Cor de orbe inválida. Use uma das seguintes: {', '.join(self.cores_orbe.keys())}.")
            return

        if not ctx.message.attachments:
            await ctx.send("❌ Você precisa de anexar um print (imagem) da captura da orbe.")
            return

        imagem = ctx.message.attachments[0]
        if not imagem.content_type.startswith('image/'):
            await ctx.send("❌ O anexo precisa de ser uma imagem.")
            return

        todos_membros = [ctx.author] + membros
        membros_unicos = sorted(list(set(todos_membros)), key=lambda m: m.id)
        membros_ids_str = ",".join(str(m.id) for m in membros_unicos)
        membros_mencoes = "\n".join(f"• {m.mention}" for m in membros_unicos)

        valor_total = int(self.bot.db_manager.get_config_value(f'orbe_{cor_lower}', '0'))
        if valor_total == 0:
            await ctx.send(f"⚠️ A recompensa para a orbe {cor} ainda não foi configurada pela administração.")
            return

        recompensa_individual = valor_total // len(membros_unicos)

        canal_aprovacao_id = int(self.bot.db_manager.get_config_value('canal_aprovacao', '0'))
        canal_aprovacao = self.bot.get_channel(canal_aprovacao_id)

        if not canal_aprovacao:
            await ctx.send("⚠️ O canal de aprovações não foi configurado. Contacte um administrador.")
            return

        embed = discord.Embed(
            title=f"🔮 Submissão de Orbe {self.cores_orbe[cor_lower]['nome']}",
            description=f"**Enviado por:** {ctx.author.mention}\n\n"
                        f"**Membros no Grupo ({len(membros_unicos)}):**\n{membros_mencoes}\n\n"
                        f"**Valor Total:** {valor_total} moedas\n"
                        f"**Valor por Membro:** {recompensa_individual} moedas",
            color=self.cores_orbe[cor_lower]['cor']
        )
        embed.set_image(url=imagem.url)
        embed.set_footer(text="Aguardando aprovação da Staff...")

        view = OrbeAprovacaoView(self.bot)
        
        try:
            msg_aprovacao = await canal_aprovacao.send(embed=embed, view=view)
            
            with self.db_manager.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO submissoes_orbe (message_id, cor, valor_total, autor_id, membros, status) VALUES (%s, %s, %s, %s, %s, %s)",
                        (msg_aprovacao.id, cor_lower, valor_total, ctx.author.id, membros_ids_str, 'pendente')
                    )
                conn.commit()

            await ctx.message.add_reaction("✅")
            await ctx.send("✅ Submissão enviada para análise!", delete_after=10)

        except Exception as e:
            await ctx.send("❌ Ocorreu um erro ao enviar a sua submissão. Tente novamente.")
            print(f"Erro no comando orbe: {e}")


async def setup(bot):
    await bot.add_cog(Orbes(bot))

