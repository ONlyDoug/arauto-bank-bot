import discord
from discord.ext import commands
from utils.permissions import check_permission_level

class Economia(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_manager = self.bot.db_manager # Usa o gestor central
        self.ID_TESOURO_GUILDA = 1

    # --- Funções Internas ---
    async def get_saldo(self, user_id: int):
        """Busca o saldo de um usuário de forma segura."""
        with self.db_manager.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT saldo FROM banco WHERE user_id = %s", (user_id,))
                resultado = cursor.fetchone()
                if not resultado:
                    # Cria a conta se não existir
                    cursor.execute("INSERT INTO banco (user_id, saldo) VALUES (%s, 0) ON CONFLICT (user_id) DO NOTHING", (user_id,))
                    conn.commit()
                    return 0
                return resultado[0]

    async def depositar(self, user_id: int, valor: int, descricao: str):
        """Deposita moedas na conta de um usuário e regista a transação."""
        if valor <= 0: return
        with self.db_manager.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("UPDATE banco SET saldo = saldo + %s WHERE user_id = %s", (valor, user_id))
                cursor.execute("INSERT INTO transacoes (user_id, tipo, valor, descricao) VALUES (%s, 'deposito', %s, %s)", (user_id, valor, descricao))
            conn.commit()

    async def levantar(self, user_id: int, valor: int, descricao: str):
        """Levanta moedas da conta de um usuário e regista a transação."""
        if valor <= 0: return
        with self.db_manager.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("UPDATE banco SET saldo = saldo - %s WHERE user_id = %s", (valor, user_id))
                cursor.execute("INSERT INTO transacoes (user_id, tipo, valor, descricao) VALUES (%s, 'levantamento', %s, %s)", (user_id, valor, descricao))
            conn.commit()
    
    # --- Comandos para Membros ---
    @commands.command(name="saldo")
    async def saldo(self, ctx, membro: discord.Member = None):
        target_user = membro or ctx.author
        
        # Garante que a conta existe antes de buscar o saldo
        await self.get_saldo(target_user.id)
        
        saldo_user = await self.get_saldo(target_user.id)
        
        embed = discord.Embed(
            color=discord.Color.gold(),
        )
        embed.set_author(name=f"Saldo de {target_user.display_name}", icon_url=target_user.display_avatar.url)
        embed.description = f"Você possui **{saldo_user:,}** moedas. 🪙"
        
        await ctx.send(embed=embed)

    @commands.command(name="transferir")
    async def transferir(self, ctx, membro: discord.Member, valor: int):
        if valor <= 0:
            await ctx.send("❌ O valor da transferência deve ser positivo.")
            return
        if membro == ctx.author:
            await ctx.send("❌ Você não pode transferir moedas para si mesmo.")
            return
        
        saldo_autor = await self.get_saldo(ctx.author.id)
        if saldo_autor < valor:
            await ctx.send(f"❌ Você não tem saldo suficiente. O seu saldo é de **{saldo_autor}** moedas.")
            return

        # Garante que a conta do destinatário existe
        await self.get_saldo(membro.id)

        await self.levantar(ctx.author.id, valor, f"Transferência para {membro.name}")
        await self.depositar(membro.id, valor, f"Transferência de {ctx.author.name}")

        embed = discord.Embed(
            title="💸 Transferência Realizada com Sucesso",
            color=discord.Color.green(),
            description=f"**{valor:,}** moedas foram transferidas."
        )
        embed.add_field(name="De", value=ctx.author.mention, inline=True)
        embed.add_field(name="Para", value=membro.mention, inline=True)

        await ctx.send(embed=embed)

    # --- Comandos de Administração ---
    @commands.command(name="emitir")
    @check_permission_level(3)
    async def emitir(self, ctx, membro: discord.Member, valor: int):
        if valor <= 0:
            await ctx.send("❌ O valor a emitir deve ser positivo.")
            return

        saldo_tesouro = await self.get_saldo(self.ID_TESOURO_GUILDA)
        if saldo_tesouro < valor:
            await ctx.send(f"❌ O Tesouro da Guilda não tem saldo suficiente. Saldo atual: **{saldo_tesouro}** moedas.")
            return

        # Garante que a conta do membro existe
        await self.get_saldo(membro.id)

        await self.levantar(self.ID_TESOURO_GUILDA, valor, f"Emissão para {membro.name}")
        await self.depositar(membro.id, valor, "Emissão de moedas pela Administração")

        await ctx.send(f"✅ **{valor}** moedas foram emitidas do Tesouro para {membro.mention} com sucesso.")

async def setup(bot):
    await bot.add_cog(Economia(bot))

