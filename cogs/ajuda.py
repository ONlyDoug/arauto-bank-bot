import discord
from discord.ext import commands

class Ajuda(commands.Cog):
    """Um sistema de ajuda personalizado e inteligente."""
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='ajuda')
    async def ajuda(self, ctx, *, comando_nome: str = None):
        if not comando_nome:
            # Se nenhum comando for especificado, mostra a ajuda geral.
            embed = discord.Embed(
                title="📖 Central de Ajuda do Arauto Bank",
                description="Olá! Sou o Arauto Bank, o bot que gere a economia da guilda. Abaixo estão as minhas principais categorias de comandos.\nPara obter detalhes sobre um comando específico, use `!ajuda <nome_do_comando>`.",
                color=discord.Color.blurple()
            )

            # Agrupa os comandos por Cogs para uma melhor organização
            cogs_comandos = {
                "Economia": ["saldo", "extrato", "transferir", "info-moeda"],
                "Loja": ["loja", "comprar"],
                "Eventos": ["listareventos", "participar"],
                "Taxas": ["pagar-taxa", "paguei-prata"],
                "Orbes": ["orbe"]
            }

            for categoria, lista_comandos in cogs_comandos.items():
                # Formata a lista de comandos para exibição
                comandos_formatados = [f"`!{cmd}`" for cmd in lista_comandos]
                embed.add_field(
                    name=f"**{categoria}**",
                    value=' | '.join(comandos_formatados),
                    inline=False
                )

            embed.set_footer(text="Exemplo: !ajuda saldo")
            await ctx.send(embed=embed)
        else:
            # Se um comando foi especificado, mostra a ajuda detalhada.
            comando = self.bot.get_command(comando_nome.lower())

            if not comando or comando.hidden:
                await ctx.send(f"🤔 Humm, `!{comando_nome}`... esse feitiço não consta no meu livro de magias. Tens a certeza de que escreveste bem? Tenta `!ajuda` para ver a lista completa.")
                return

            # Constrói o embed de ajuda detalhada
            embed = discord.Embed(
                title=f"Comando: `!{comando.name}`",
                description=comando.help or "Este comando parece ser autoexplicativo, porque quem o fez esqueceu-se de o descrever.",
                color=discord.Color.green()
            )

            # Adiciona sinónimos (aliases) se existirem
            if comando.aliases:
                aliases_formatados = [f"`!{alias}`" for alias in comando.aliases]
                embed.add_field(name="Sinónimos", value=', '.join(aliases_formatados), inline=False)

            # Adiciona a sintaxe de uso
            sintaxe = f"`!{comando.name} {comando.signature}`"
            embed.add_field(name="Como Usar (Sintaxe)", value=sintaxe, inline=False)

            # Adiciona um exemplo prático (se definido no comando)
            # Usaremos o atributo 'usage' que adicionaremos nos outros ficheiros.
            if comando.usage:
                embed.add_field(name="Exemplo Prático", value=f"`{comando.usage}`", inline=False)

            await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Ajuda(bot))