import discord
from discord.ext import commands

class Ajuda(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='ajuda')
    async def help_command(self, ctx):
        """Mostra uma lista de comandos disponíveis com base nas permissões do utilizador."""
        embed = discord.Embed(title="Ajuda do Arauto Bank", description="Aqui estão os comandos que você pode usar:", color=discord.Color.purple())

        # Comandos para todos
        embed.add_field(name="🪙 Comandos Gerais", value="`!saldo`, `!extrato`, `!rank`, `!loja`, `!comprar`, `!transferir`, `!listareventos`, `!participar`, `!meuprogresso`", inline=False)

        # Comandos para Nível 1+
        if await commands.check(check_permission_level(1)).predicate(ctx):
             embed.add_field(name="🛠️ Comandos de Puxador (Nível 1+)", value="`!puxar`, `!confirmar-todos`, `!confirmar`, `!finalizarevento`, `!cancelarevento`", inline=False)

        # Adicionar mais verificações para outros níveis de permissão (Nível 3, Nível 4)
        if await commands.check(check_permission_level(4)).predicate(ctx):
            embed.add_field(name="👑 Comandos de Admin (Nível 4)", value="`!setup`, `!config-bot`, `!ajustar-lastro`, ... (lista completa)", inline=False)
            
        await ctx.author.send(embed=embed)
        await ctx.send("Enviei-lhe uma mensagem privada com os seus comandos disponíveis!")

async def setup(bot):
    await bot.add_cog(Ajuda(bot))

# (A função check_permission_level precisa de ser importada ou definida aqui também)
