import discord
from discord.ext import commands
import contextlib
from utils.permissions import check_permission_level

ID_TESOURO_GUILDA = 1

class Utilidades(commands.Cog):
    """
    Cog para comandos de utilidade geral e gestão económica de alto nível
    (lastro, airdrops, etc.).
    """
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

    # =================================================================================
    # Comandos para Membros
    # =================================================================================

    @commands.command(name='extrato')
    async def extrato(self, ctx, page: int = 1):
        """Mostra as suas últimas 10 transações."""
        if page < 1: page = 1
        offset = (page - 1) * 10

        with self.get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT tipo, valor, descricao, data FROM transacoes WHERE user_id = %s ORDER BY data DESC LIMIT 10 OFFSET %s",
                    (ctx.author.id, offset)
                )
                transacoes = cursor.fetchall()
                
                cursor.execute("SELECT COUNT(id) FROM transacoes WHERE user_id = %s", (ctx.author.id,))
                total_transacoes = cursor.fetchone()[0]

        if not transacoes:
            return await ctx.send("Você não tem nenhuma transação registada.")

        total_pages = (total_transacoes + 9) // 10
        
        embed = discord.Embed(
            title=f"📜 Extrato de {ctx.author.display_name}",
            description=f"A mostrar as suas últimas transações. Página {page}/{total_pages}",
            color=discord.Color.blue()
        )

        for tipo, valor, descricao, data in transacoes:
            timestamp = int(data.timestamp())
            emoji = "📥" if valor > 0 else "📤"
            valor_formatado = f"{valor:,}".replace(',', '.')
            embed.add_field(
                name=f"{emoji} {valor_formatado} GC - <t:{timestamp}:f>",
                value=f"**Tipo:** `{tipo}`\n**Descrição:** *{descricao or 'N/A'}*",
                inline=False
            )
        
        embed.set_footer(text=f"Para ver outras páginas, use !extrato <número_da_página>.")
        await ctx.send(embed=embed)

    @commands.command(name='info-moeda', aliases=['lastro'])
    async def info_moeda(self, ctx):
        """Mostra as estatísticas vitais da economia da guilda."""
        admin_cog = self.bot.get_cog('Admin')
        
        try:
            lastro_prata = int(admin_cog.get_config_value('lastro_prata', '1000'))
        except (ValueError, TypeError):
            lastro_prata = 1000

        with self.get_db_connection() as conn:
            with conn.cursor() as cursor:
                # Soma o saldo de todos os usuários, exceto o tesouro
                cursor.execute("SELECT SUM(saldo) FROM banco WHERE user_id != %s", (ID_TESOURO_GUILDA,))
                total_moedas_circulacao = cursor.fetchone()[0] or 0
        
        taxa_conversao = total_moedas_circulacao / lastro_prata if lastro_prata > 0 else 0

        embed = discord.Embed(
            title="📈 Informação da Moeda - Arauto Bank",
            description="Dados económicos da nossa guilda.",
            color=0x1abc9c
        )
        embed.add_field(name="🥈 Lastro Total em Prata", value=f"`{lastro_prata:,}`".replace(',', '.'), inline=True)
        embed.add_field(name="💰 GuildCoins em Circulação", value=f"`{total_moedas_circulacao:,}`".replace(',', '.'), inline=True)
        embed.add_field(name="💱 Taxa de Conversão", value=f"`1 GC ≈ {taxa_conversao:,.2f} Prata`".replace(',', '.'), inline=False)
        embed.set_footer(text="A taxa de conversão é uma estimativa baseada no lastro e no total de moedas.")

        await ctx.send(embed=embed)

    # =================================================================================
    # Comandos de Administração
    # =================================================================================
    
    @commands.command(name='ajustar-lastro')
    @check_permission_level(4)
    async def ajustar_lastro(self, ctx, novo_total_prata: int):
        """(Nível 4+) Atualiza o total de prata que lastreia a moeda."""
        if novo_total_prata < 0:
            return await ctx.send("O valor do lastro não pode ser negativo.")
            
        self.bot.get_cog('Admin').set_config_value('lastro_prata', str(novo_total_prata))
        await ctx.send(f"✅ O lastro da moeda foi ajustado para `{novo_total_prata:,} Prata`.".replace(',', '.'))


    @commands.command(name='resgatar')
    @check_permission_level(3)
    async def resgatar(self, ctx, membro: discord.Member, valor: int):
        """(Nível 3+) Converte GC de um membro em prata, movendo o valor para o tesouro."""
        if valor <= 0:
            return await ctx.send("O valor do resgate deve ser positivo.")

        economia_cog = self.bot.get_cog('Economia')
        saldo_membro = await economia_cog.get_saldo(membro.id)

        if saldo_membro < valor:
            return await ctx.send(f"O membro {membro.mention} não tem saldo suficiente para resgatar `{valor} GC`.")

        await economia_cog.update_saldo(membro.id, -valor, "resgate_prata", f"Resgate aprovado por {ctx.author.name}")
        await economia_cog.update_saldo(ID_TESOURO_GUILDA, valor, "entrada_resgate", f"Resgate de {membro.name}")

        await ctx.send(f"✅ Resgate de `{valor:,} GC` para {membro.mention} processado com sucesso.".replace(',', '.'))


    @commands.command(name='airdrop')
    @check_permission_level(3)
    async def airdrop(self, ctx, valor: int, cargo: discord.Role = None):
        """(Nível 3+) Distribui GC para todos os membros ou para um cargo específico."""
        if valor <= 0:
            return await ctx.send("O valor do airdrop deve ser positivo.")
            
        membros_alvo = cargo.members if cargo else [m for m in ctx.guild.members if not m.bot]
        if not membros_alvo:
            return await ctx.send("Nenhum membro encontrado para o airdrop.")

        economia_cog = self.bot.get_cog('Economia')
        saldo_tesouro = await economia_cog.get_saldo(ID_TESOURO_GUILDA)
        custo_total = valor * len(membros_alvo)

        if saldo_tesouro < custo_total:
            return await ctx.send(f"O tesouro não tem saldo suficiente. Necessário: `{custo_total:,} GC`. Saldo do tesouro: `{saldo_tesouro:,} GC`.".replace(',', '.'))

        msg = await ctx.send(f"A iniciar airdrop de `{valor} GC` para {len(membros_alvo)} membros... Isso pode levar algum tempo.")

        for membro in membros_alvo:
            await economia_cog.update_saldo(membro.id, valor, "airdrop", f"Airdrop executado por {ctx.author.name}")
            await economia_cog.update_saldo(ID_TESOURO_GUILDA, -valor, "saida_airdrop", f"Airdrop para {membro.name}")

        await msg.edit(content=f"✅ Airdrop concluído! `{custo_total:,} GC` foram distribuídos com sucesso.".replace(',', '.'))


async def setup(bot):
    await bot.add_cog(Utilidades(bot))
