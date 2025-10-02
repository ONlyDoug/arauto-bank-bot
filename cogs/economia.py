import discord
from discord.ext import commands
import contextlib
from utils.permissions import check_permission_level

# Constante para o ID do tesouro
ID_TESOURO_GUILDA = 1

class Economia(commands.Cog):
    """Cog para gerir a economia base do bot, como saldos e transferências."""
    def __init__(self, bot):
        self.bot = bot

    @contextlib.contextmanager
    def get_db_connection(self):
        conn = None
        try:
            conn = self.bot.db_pool.getconn()
            yield conn
        finally:
            if conn: self.bot.db_pool.putconn(conn)

    async def get_saldo(self, user_id: int):
        with self.get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT saldo FROM banco WHERE user_id = %s", (user_id,))
                resultado = cursor.fetchone()
                return resultado[0] if resultado else 0

    async def update_saldo(self, user_id: int, valor: int, tipo: str, descricao: str):
        with self.get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("INSERT INTO banco (user_id, saldo) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET saldo = banco.saldo + %s",
                               (user_id, valor, valor))
                cursor.execute("INSERT INTO transacoes (user_id, tipo, valor, descricao) VALUES (%s, %s, %s, %s)",
                               (user_id, tipo, valor, descricao))
            conn.commit()

    @commands.command(name='saldo')
    async def saldo(self, ctx, membro: discord.Member = None):
        """Mostra o seu saldo ou o de outro membro."""
        target_user = membro or ctx.author
        saldo_user = await self.get_saldo(target_user.id)
        await ctx.send(f"💰 O saldo de {target_user.mention} é de `{saldo_user:,} GuildCoins`.".replace(',', '.'))

    @commands.command(name='transferir')
    async def transferir(self, ctx, membro: discord.Member, valor: int):
        """Transfere uma quantidade de moedas para outro membro."""
        if membro.bot or membro == ctx.author:
            return await ctx.send("Transferência inválida.")
        if valor <= 0:
            return await ctx.send("O valor deve ser positivo.")

        saldo_autor = await self.get_saldo(ctx.author.id)
        if saldo_autor < valor:
            return await ctx.send("Você não tem saldo suficiente.")

        await self.update_saldo(ctx.author.id, -valor, "transferencia_enviada", f"Para {membro.name}")
        await self.update_saldo(membro.id, valor, "transferencia_recebida", f"De {ctx.author.name}")

        await ctx.send(f"✅ Você transferiu `{valor:,} GC` para {membro.mention}.".replace(',', '.'))

    @commands.command(name='emitir')
    @check_permission_level(3)
    async def emitir(self, ctx, membro: discord.Member, valor: int):
        """(Nível 3+) Emite moedas do tesouro da guilda para um membro."""
        if valor <= 0:
            return await ctx.send("O valor deve ser positivo.")
        
        saldo_tesouro = await self.get_saldo(ID_TESOURO_GUILDA)
        if saldo_tesouro < valor:
            return await ctx.send(f"O Tesouro da Guilda não tem saldo suficiente. Saldo atual: `{saldo_tesouro:,} GC`.".replace(',', '.'))

        await self.update_saldo(ID_TESOURO_GUILDA, -valor, "emissao_para_membro", f"Para {membro.name}")
        await self.update_saldo(membro.id, valor, "recebimento_tesouro", f"Emitido por {ctx.author.name}")

        await ctx.send(f"✅ Foram emitidos `{valor:,} GC` do tesouro para {membro.mention}.".replace(',', '.'))

async def setup(bot):
    await bot.add_cog(Economia(bot))

