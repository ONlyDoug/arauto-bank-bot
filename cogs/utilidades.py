import discord
from discord.ext import commands
from utils.permissions import check_permission_level
from datetime import datetime, date

class Utilidades(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_manager = self.bot.db_manager
        self.ID_TESOURO_GUILDA = 1

    @commands.command(name="status")
    async def status(self, ctx):
        """Verifica a latência e o estado do bot."""
        latencia = round(self.bot.latency * 1000)
        await ctx.send(f"Pong! 🏓 Latência: **{latencia}ms**. O Arauto Bank está operacional.")

    @commands.command(name="info-moeda", aliases=["infomoeda"])
    async def info_moeda(self, ctx):
        """Mostra as estatísticas vitais da economia da guilda."""
        total_prata = int(self.db_manager.get_config_value('lastro_total_prata', '0'))
        taxa_conversao = int(self.db_manager.get_config_value('taxa_conversao_prata', '1000'))
        
        suprimento_maximo = total_prata // taxa_conversao if taxa_conversao > 0 else 0
        saldo_tesouro = 0
        
        with self.db_manager.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT saldo FROM banco WHERE user_id = %s", (self.ID_TESOURO_GUILDA,))
                resultado = cursor.fetchone()
                saldo_tesouro = resultado[0] if resultado else 0

        moedas_em_circulacao = suprimento_maximo - saldo_tesouro

        embed = discord.Embed(
            title="📈 Estatísticas do Arauto Bank",
            color=discord.Color.from_rgb(230, 230, 250) # Lilás claro
        )
        embed.add_field(name="Lastro Total de Prata", value=f"**{total_prata:,}** 🥈", inline=False)
        embed.add_field(name="Taxa de Conversão", value=f"1 🪙 = **{taxa_conversao:,}** 🥈", inline=False)
        embed.add_field(name="Suprimento Máximo de Moedas", value=f"**{suprimento_maximo:,}** 🪙", inline=True)
        embed.add_field(name="Moedas no Tesouro", value=f"**{saldo_tesouro:,}** 🪙", inline=True)
        embed.add_field(name="Moedas em Circulação", value=f"**{moedas_em_circulacao:,}** 🪙", inline=True)

        await ctx.send(embed=embed)

    @commands.command(name="extrato")
    async def extrato(self, ctx, data_str: str = None):
        """Mostra o seu extrato de transações para uma data específica (formato AAAA-MM-DD)."""
        if data_str:
            try:
                data_alvo = datetime.strptime(data_str, '%Y-%m-%d').date()
            except ValueError:
                await ctx.send("❌ Formato de data inválido. Por favor, use AAAA-MM-DD (ex: `!extrato 2025-10-03`).")
                return
        else:
            data_alvo = date.today()

        user_id = ctx.author.id
        
        with self.db_manager.get_connection() as conn:
            with conn.cursor() as cursor:
                # Busca transações normais
                cursor.execute(
                    "SELECT tipo, valor, descricao, data FROM transacoes WHERE user_id = %s AND DATE(data) = %s AND tipo NOT IN ('deposito_voz', 'deposito_chat', 'deposito_reacao') ORDER BY data DESC",
                    (user_id, data_alvo)
                )
                transacoes = cursor.fetchall()
                
                # Busca o total de renda passiva para o dia
                cursor.execute(
                    "SELECT tipo, SUM(valor) FROM renda_passiva_log WHERE user_id = %s AND data = %s GROUP BY tipo",
                    (user_id, data_alvo)
                )
                renda_passiva = cursor.fetchall()

        embed = discord.Embed(
            title=f"📜 Extrato de {ctx.author.display_name}",
            description=f"Transações para a data: **{data_alvo.strftime('%d/%m/%Y')}**",
            color=discord.Color.blue()
        )
        embed.set_thumbnail(url=ctx.author.display_avatar.url)

        # Adiciona o resumo de Renda Passiva
        if renda_passiva:
            renda_texto = ""
            for tipo, total in renda_passiva:
                if tipo == 'voz':
                    renda_texto += f"🎤 **Voz:** Ganhou **{total} minutos** de tempo de call.\n"
                elif tipo == 'chat':
                    renda_texto += f"💬 **Chat:** Ganhou **{total} moedas** por atividade no chat.\n"
            if renda_texto:
                embed.add_field(name="Resumo de Atividade Passiva", value=renda_texto, inline=False)

        # Adiciona as outras transações
        if transacoes:
            texto_transacoes = ""
            for tipo, valor, descricao, data in transacoes[:10]: # Limita a 10 transações
                emoji = "📥" if tipo == 'deposito' else "📤"
                sinal = "+" if tipo == 'deposito' else "-"
                texto_transacoes += f"{emoji} `{data.strftime('%H:%M')}`: **{sinal}{valor}** moedas ({descricao})\n"
            
            embed.add_field(name="Transações Principais", value=texto_transacoes, inline=False)
        
        if not renda_passiva and not transacoes:
            embed.description += "\n\nNenhuma atividade registada para esta data."

        await ctx.send(embed=embed)

    @commands.command(name="resgatar")
    @check_permission_level(3)
    async def resgatar(self, ctx, membro: discord.Member, valor: int):
        if valor <= 0:
            return await ctx.send("❌ O valor a resgatar deve ser positivo.")

        economia_cog = self.bot.get_cog('Economia')
        saldo_membro = await economia_cog.get_saldo(membro.id)

        if saldo_membro < valor:
            return await ctx.send(f"❌ O membro {membro.mention} não tem saldo suficiente. Saldo atual: **{saldo_membro}**.")

        await economia_cog.levantar(membro.id, valor, f"Resgate de moedas por {ctx.author.name}")

        canal_resgates_id = int(self.db_manager.get_config_value('canal_resgates', '0'))
        if canal_resgates_id != 0:
            canal = self.bot.get_channel(canal_resgates_id)
            if canal:
                taxa_conversao = int(self.db_manager.get_config_value('taxa_conversao_prata', '1000'))
                valor_prata = valor * taxa_conversao
                
                embed = discord.Embed(
                    title="🚨 Pedido de Resgate Processado",
                    description=f"O resgate de moedas para prata foi processado no bot. A equipa financeira deve agora realizar o pagamento no jogo.",
                    color=discord.Color.orange()
                )
                embed.add_field(name="Membro", value=membro.mention, inline=True)
                embed.add_field(name="Valor em Moedas", value=f"{valor:,} 🪙", inline=True)
                embed.add_field(name="Valor a Pagar em Prata", value=f"**{valor_prata:,}** 🥈", inline=True)
                embed.set_footer(text=f"Processado por: {ctx.author.display_name}")
                await canal.send(embed=embed)

        await ctx.send(f"✅ Resgate de **{valor}** moedas para {membro.mention} processado com sucesso. A notificação foi enviada à equipa financeira.")

    @commands.command(name="airdrop")
    @check_permission_level(3)
    async def airdrop(self, ctx, valor: int, cargo: discord.Role = None):
        if valor <= 0:
            return await ctx.send("❌ O valor do airdrop deve ser positivo.")

        membros_alvo = cargo.members if cargo else [m for m in ctx.guild.members if not m.bot]
        
        if not membros_alvo:
            return await ctx.send("❌ Nenhum membro encontrado para o airdrop.")

        economia_cog = self.bot.get_cog('Economia')
        
        msg_espera = await ctx.send(f"A iniciar o airdrop de **{valor}** moedas para **{len(membros_alvo)}** membros. Isto pode demorar um pouco...")

        for membro in membros_alvo:
            await economia_cog.depositar(membro.id, valor, "Airdrop da Administração")
            await asyncio.sleep(0.1) # Pequena pausa para não sobrecarregar

        await msg_espera.edit(content=f"✅ Airdrop concluído com sucesso para **{len(membros_alvo)}** membros!")


async def setup(bot):
    await bot.add_cog(Utilidades(bot))

