import discord
from discord.ext import commands
import contextlib
from utils.permissions import check_permission_level

ID_TESOURO_GUILDA = 1

class Utilidades(commands.Cog):
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
    
    @commands.command(name='status')
    async def status(self, ctx):
        """Verifica a latência e o estado operacional do bot."""
        latency = round(self.bot.latency * 1000)
        await ctx.send(f"Pong! Latência: `{latency}ms`. O Arauto Bank está operacional.")

    @commands.command(name='extrato')
    async def extrato(self, ctx, page: int = 1):
        """Mostra as suas transações mais relevantes."""
        if page < 1: page = 1
        offset = (page - 1) * 10

        # Tipos de transação a serem omitidos do extrato do membro
        tipos_irrelevantes = (
            'renda_passiva_voz', 'renda_passiva_chat', 'recompensa_reacao',
            'saida_airdrop', 'entrada_resgate'
        )

        with self.get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT tipo, valor, descricao, data FROM transacoes WHERE user_id = %s AND tipo NOT IN %s ORDER BY data DESC LIMIT 10 OFFSET %s",
                    (ctx.author.id, tipos_irrelevantes, offset)
                )
                transacoes = cursor.fetchall()
                
                cursor.execute("SELECT COUNT(id) FROM transacoes WHERE user_id = %s AND tipo NOT IN %s", (ctx.author.id, tipos_irrelevantes))
                total_transacoes = cursor.fetchone()[0]

        if not transacoes:
            return await ctx.send("Você não tem nenhuma transação relevante para exibir.")

        total_pages = (total_transacoes + 9) // 10
        
        embed = discord.Embed(
            title=f"📜 Extrato de {ctx.author.display_name}",
            description=f"A exibir apenas transações relevantes. Página {page}/{total_pages}",
            color=discord.Color.blue()
        )

        for tipo, valor, descricao, data in transacoes:
            timestamp = int(data.timestamp())
            emoji = "📥" if valor > 0 else "📤"
            valor_formatado = f"{valor:,}".replace(',', '.')
            embed.add_field(
                name=f"{emoji} {valor_formatado} GC - <t:{timestamp}:f>",
                value=f"**Tipo:** `{tipo}` | **Descrição:** *{descricao or 'N/A'}*",
                inline=False
            )
        
        embed.set_footer(text=f"Use !extrato <página> para ver mais. Ganhos passivos não são exibidos.")
        await ctx.send(embed=embed)

    @commands.command(name='info-moeda', aliases=['infomoeda', 'lastro'])
    async def info_moeda(self, ctx):
        """Mostra as estatísticas vitais da economia da guilda com o novo sistema de lastro."""
        admin_cog = self.bot.get_cog('Admin')
        lastro_total_prata = int(admin_cog.get_config_value('lastro_total_prata', '0'))
        taxa_conversao = int(admin_cog.get_config_value('taxa_conversao_prata', '1000'))
        
        suprimento_maximo = lastro_total_prata // taxa_conversao if taxa_conversao > 0 else 0

        with self.get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT saldo FROM banco WHERE user_id = %s", (ID_TESOURO_GUILDA,))
                moedas_tesouro = (cursor.fetchone() or [0])[0]

                cursor.execute("SELECT SUM(saldo) FROM banco WHERE user_id != %s", (ID_TESOURO_GUILDA,))
                moedas_em_circulacao = (cursor.fetchone() or [0])[0]
        
        embed = discord.Embed(title="📈 Estatísticas do Arauto Bank", color=0x1abc9c)
        embed.add_field(name="<:silver:12345> Lastro Total de Prata", value=f"**{lastro_total_prata:,}**".replace(',', '.'), inline=False)
        embed.add_field(name="<:coin:12345> Taxa de Conversão", value=f"`1 🪙 = {taxa_conversao:,} 🥈`".replace(',', '.'), inline=False)
        embed.add_field(name="<:chest:12345> Suprimento Máximo de Moedas", value=f"{suprimento_maximo:,}".replace(',', '.'), inline=True)
        embed.add_field(name="<:treasure:12345> Moedas no Tesouro", value=f"{moedas_tesouro:,}".replace(',', '.'), inline=True)
        embed.add_field(name="<:users:12345> Moedas em Circulação", value=f"{moedas_em_circulacao:,}".replace(',', '.'), inline=True)
        embed.set_footer(text="Use emojis personalizados para uma melhor estética.")
        
        await ctx.send(embed=embed)
    
    @commands.command(name='definir-lastro')
    @check_permission_level(4)
    async def definir_lastro(self, ctx, total_prata: int):
        """(Nível 4+) Define o total de prata que a guilda possui, que serve como base para a economia."""
        if total_prata < 0:
            return await ctx.send("O valor do lastro não pode ser negativo.")
            
        self.bot.get_cog('Admin').set_config_value('lastro_total_prata', str(total_prata))
        await ctx.send(f"✅ O lastro total de prata foi definido para **{total_prata:,}**.".replace(',', '.'))

async def setup(bot):
    await bot.add_cog(Utilidades(bot))

