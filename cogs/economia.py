import discord
from discord.ext import commands
import contextlib
from datetime import datetime
from utils.permissions import check_permission_level

# Constante para o ID do tesouro, para evitar "números mágicos"
ID_TESOURO_GUILDA = 1

class Economia(commands.Cog):
    """Cog que agrupa todos os comandos relacionados à economia do bot."""
    def __init__(self, bot):
        self.bot = bot

    @contextlib.contextmanager
    def get_db_connection(self):
        """Obtém uma conexão do pool e garante que ela é devolvida."""
        conn = None
        try:
            conn = self.bot.db_pool.getconn()
            yield conn
        finally:
            if conn:
                self.bot.db_pool.putconn(conn)

    # =================================================================================
    # Funções Auxiliares de Base de Dados
    # =================================================================================

    async def get_saldo(self, user_id: int):
        """Obtém o saldo de um usuário."""
        with self.get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT saldo FROM banco WHERE user_id = %s", (user_id,))
                resultado = cursor.fetchone()
                if resultado:
                    return resultado[0]
                else:
                    # Cria a conta se não existir
                    cursor.execute("INSERT INTO banco (user_id, saldo) VALUES (%s, 0) ON CONFLICT (user_id) DO NOTHING", (user_id,))
                    conn.commit()
                    return 0

    async def update_saldo(self, user_id: int, valor: int, tipo: str, descricao: str):
        """Atualiza o saldo de um usuário e regista a transação."""
        with self.get_db_connection() as conn:
            with conn.cursor() as cursor:
                # Garante que a conta existe
                cursor.execute("INSERT INTO banco (user_id, saldo) VALUES (%s, 0) ON CONFLICT (user_id) DO NOTHING", (user_id,))
                
                # Atualiza o saldo
                cursor.execute("UPDATE banco SET saldo = saldo + %s WHERE user_id = %s RETURNING saldo", (valor, user_id))
                novo_saldo = cursor.fetchone()[0]

                # Regista a transação
                cursor.execute(
                    "INSERT INTO transacoes (user_id, tipo, valor, descricao) VALUES (%s, %s, %s, %s)",
                    (user_id, tipo, valor, descricao)
                )
            conn.commit()
        return novo_saldo

    # =================================================================================
    # Comandos para Membros
    # =================================================================================

    @commands.command(name='saldo')
    async def saldo(self, ctx, membro: discord.Member = None):
        """Mostra o seu saldo atual ou o de outro membro."""
        target_user = membro or ctx.author
        saldo_user = await self.get_saldo(target_user.id)
        
        embed = discord.Embed(
            title=f"💰 Saldo de {target_user.display_name}",
            description=f"**Saldo atual:** {saldo_user:,} GuildCoins (GC)".replace(',', '.'),
            color=discord.Color.gold()
        )
        embed.set_thumbnail(url=target_user.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.command(name='transferir')
    async def transferir(self, ctx, membro: discord.Member, valor: int):
        """Transfere uma quantidade de moedas para outro membro."""
        if valor <= 0:
            return await ctx.send("O valor da transferência deve ser positivo.")
        if membro == ctx.author or membro.bot:
            return await ctx.send("Você não pode transferir para si mesmo ou para um bot.")

        saldo_remetente = await self.get_saldo(ctx.author.id)

        if saldo_remetente < valor:
            return await ctx.send(f"Você não tem saldo suficiente. Seu saldo: {saldo_remetente} GC")

        # Realiza as transações
        await self.update_saldo(ctx.author.id, -valor, "transferencia_enviada", f"Transferência para {membro.name}")
        await self.update_saldo(membro.id, valor, "transferencia_recebida", f"Transferência de {ctx.author.name}")

        embed = discord.Embed(
            title="✅ Transferência Realizada com Sucesso!",
            description=f"**{ctx.author.mention}** transferiu **{valor:,} GC** para **{membro.mention}**.".replace(',', '.'),
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)

    @commands.command(name='extrato')
    async def extrato(self, ctx):
        """Mostra as suas últimas 5 transações."""
        with self.get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT tipo, valor, descricao, data FROM transacoes WHERE user_id = %s ORDER BY data DESC LIMIT 5",
                    (ctx.author.id,)
                )
                transacoes = cursor.fetchall()

        if not transacoes:
            return await ctx.send("Você ainda não tem transações registadas.")

        embed = discord.Embed(
            title=f"📜 Extrato Recente de {ctx.author.display_name}",
            color=discord.Color.blue()
        )
        
        for tipo, valor, descricao, data in transacoes:
            sinal = "+" if valor > 0 else ""
            timestamp = int(data.timestamp())
            embed.add_field(
                name=f"{sinal}{valor:,} GC - <t:{timestamp}:R>".replace(',', '.'),
                value=f"`{descricao or 'Sem descrição'}`",
                inline=False
            )
        
        await ctx.send(embed=embed)

    # =================================================================================
    # Comandos Administrativos
    # =================================================================================

    @commands.command(name='emitir')
    @check_permission_level(3)
    async def emitir(self, ctx, membro: discord.Member, valor: int, *, motivo: str = "Emissão administrativa"):
        """Emite moedas do tesouro da guilda para um membro. (Nível 3+)"""
        if valor <= 0:
            return await ctx.send("O valor da emissão deve ser positivo.")
        if membro.bot:
            return await ctx.send("Não é possível emitir moedas para um bot.")

        saldo_tesouro = await self.get_saldo(ID_TESOURO_GUILDA)

        if saldo_tesouro < valor:
            return await ctx.send(f"O Tesouro da Guilda não tem saldo suficiente. Saldo atual: {saldo_tesouro:,} GC".replace(',', '.'))

        # Realiza as transações (retira do tesouro, adiciona ao membro)
        await self.update_saldo(ID_TESOURO_GUILDA, -valor, "emissao_para_membro", f"Emissão para {membro.name}: {motivo}")
        novo_saldo_membro = await self.update_saldo(membro.id, valor, "recebimento_emissao", f"Recebido do Tesouro: {motivo}")

        embed = discord.Embed(
            title="🏦 Moedas Emitidas pelo Tesouro",
            description=f"**{valor:,} GC** foram emitidas para **{membro.mention}**.".replace(',', '.'),
            color=discord.Color.orange()
        )
        embed.add_field(name="Motivo", value=motivo, inline=False)
        embed.set_footer(text=f"Novo saldo de {membro.display_name}: {novo_saldo_membro:,} GC".replace(',', '.'))
        
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Economia(bot))

