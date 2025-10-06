import discord
from discord.ext import commands
from datetime import datetime

class Economia(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def get_saldo(self, user_id: int):
        resultado = await self.bot.db_manager.execute_query(
            "SELECT saldo FROM banco WHERE user_id = %s",
            (user_id,),
            fetch="one"
        )
        if not resultado:
            await self.bot.db_manager.execute_query(
                "INSERT INTO banco (user_id, saldo) VALUES (%s, 0) ON CONFLICT (user_id) DO NOTHING",
                (user_id,)
            )
            return 0
        return resultado[0]

    async def depositar(self, user_id: int, valor: int, descricao: str):
        saldo_atual = await self.get_saldo(user_id)
        novo_saldo = saldo_atual + valor
        await self.bot.db_manager.execute_query(
            "UPDATE banco SET saldo = %s WHERE user_id = %s",
            (novo_saldo, user_id)
        )
        await self.bot.db_manager.execute_query(
            "INSERT INTO transacoes (user_id, tipo, valor, descricao) VALUES (%s, 'deposito', %s, %s)",
            (user_id, valor, descricao)
        )

    async def levantar(self, user_id: int, valor: int, descricao: str):
        saldo_atual = await self.get_saldo(user_id)
        if saldo_atual < valor:
            raise ValueError("Saldo insuficiente.")
        novo_saldo = saldo_atual - valor
        await self.bot.db_manager.execute_query(
            "UPDATE banco SET saldo = %s WHERE user_id = %s",
            (novo_saldo, user_id)
        )
        await self.bot.db_manager.execute_query(
            "INSERT INTO transacoes (user_id, tipo, valor, descricao) VALUES (%s, 'levantamento', %s, %s)",
            (user_id, valor, descricao)
        )

    @commands.command(name='saldo')
    async def saldo(self, ctx, target_user: discord.Member = None):
        target_user = target_user or ctx.author
        saldo_user = await self.get_saldo(target_user.id)
        
        embed = discord.Embed(
            color=discord.Color.gold(),
            timestamp=datetime.utcnow()
        )
        embed.set_author(name=f"Saldo de {target_user.display_name}", icon_url=target_user.display_avatar.url)
        embed.add_field(name="Moedas", value=f"**{saldo_user:,}** 🪙")
        
        await ctx.send(embed=embed)

    @commands.command(name='transferir')
    async def transferir(self, ctx, destinatario: discord.Member, valor: int):
        if valor <= 0:
            return await ctx.send("❌ O valor da transferência deve ser positivo.")
        if destinatario == ctx.author:
            return await ctx.send("❌ Você não pode transferir moedas para si mesmo.")

        try:
            await self.levantar(ctx.author.id, valor, f"Transferência para {destinatario.name}")
            await self.depositar(destinatario.id, valor, f"Transferência de {ctx.author.name}")

            embed = discord.Embed(
                title="✅ Transferência Realizada",
                color=discord.Color.green(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="Remetente", value=ctx.author.mention, inline=True)
            embed.add_field(name="Destinatário", value=destinatario.mention, inline=True)
            embed.add_field(name="Valor", value=f"**{valor:,}** 🪙", inline=False)
            
            await ctx.send(embed=embed)

        except ValueError as e:
            await ctx.send(f"❌ Erro: {e}")
        except Exception as e:
            await ctx.send("Ocorreu um erro inesperado ao realizar a transferência.")
            print(f"Erro no comando transferir: {e}")

async def setup(bot):
    await bot.add_cog(Economia(bot))
