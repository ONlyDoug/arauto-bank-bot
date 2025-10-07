import discord
from discord.ext import commands
from utils.permissions import check_permission_level
from datetime import datetime, date
import asyncio

class Utilidades(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.ID_TESOURO_GUILDA = 1

    @commands.command(name="status")
    async def status(self, ctx):
        """Verifica a latência e o estado do bot."""
        latencia = round(self.bot.latency * 1000)
        await ctx.send(f"Pong! 🏓 Latência: **{latencia}ms**. O Arauto Bank está operacional.")

    @commands.command(name="info-moeda", aliases=["infomoeda"])
    async def info_moeda(self, ctx):
        """Mostra as estatísticas vitais da economia da guilda."""
        configs = await self.bot.db_manager.get_all_configs(['lastro_total_prata', 'taxa_conversao_prata'])
        total_prata = int(configs.get('lastro_total_prata', '0'))
        taxa_conversao = int(configs.get('taxa_conversao_prata', '1000'))
        
        suprimento_maximo = total_prata // taxa_conversao if taxa_conversao > 0 else 0
        
        economia_cog = self.bot.get_cog('Economia')
        saldo_tesouro = await economia_cog.get_saldo(self.ID_TESOURO_GUILDA)

        moedas_em_circulacao = suprimento_maximo - saldo_tesouro

        embed = discord.Embed(
            title="📈 Estatísticas do Arauto Bank",
            color=discord.Color.from_rgb(230, 230, 250)
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
        
        transacoes = await self.bot.db_manager.execute_query(
            "SELECT tipo, valor, descricao, data FROM transacoes WHERE user_id = $1 AND DATE(data AT TIME ZONE 'UTC') = $2 ORDER BY data DESC",
            user_id, data_alvo,
            fetch="all"
        )
        
        renda_passiva = await self.bot.db_manager.execute_query(
            "SELECT tipo, SUM(valor) as total FROM renda_passiva_log WHERE user_id = $1 AND data = $2 GROUP BY tipo",
            user_id, data_alvo,
            fetch="all"
        )

        embed = discord.Embed(
            title=f"📜 Extrato de {ctx.author.display_name}",
            description=f"Transações para a data: **{data_alvo.strftime('%d/%m/%Y')}**",
            color=discord.Color.blue()
        )
        embed.set_thumbnail(url=ctx.author.display_avatar.url)

        if renda_passiva:
            renda_texto = ""
            for item in renda_passiva:
                tipo, total = item['tipo'], item['total']
                if tipo == 'voz':
                    renda_texto += f"🎤 **Voz:** Ganhou **{total}** moedas por tempo em call.\n"
                elif tipo == 'chat':
                    renda_texto += f"💬 **Chat:** Ganhou **{total}** moedas por atividade no chat.\n"
                elif tipo == 'reacao':
                     renda_texto += f"👍 **Reação:** Ganhou **{total}** moedas por reagir a anúncios.\n"
            if renda_texto:
                embed.add_field(name="Resumo de Atividade Passiva", value=renda_texto, inline=False)

        if transacoes:
            texto_transacoes = ""
            transacoes_principais = [t for t in transacoes if t['descricao'] not in ["Renda passiva por atividade em voz", "Renda passiva por atividade no chat"] and not t['descricao'].startswith("Recompensa por reagir")]
            
            for t in transacoes_principais[:10]:
                emoji = "📥" if t['tipo'] == 'deposito' else "📤"
                sinal = "+" if t['tipo'] == 'deposito' else "-"
                texto_transacoes += f"{emoji} `{t['data'].strftime('%H:%M')}`: **{sinal}{t['valor']}** moedas ({t['descricao']})\n"
            
            if texto_transacoes:
                embed.add_field(name="Transações Principais", value=texto_transacoes, inline=False)
        
        if not renda_passiva and not any(t for t in transacoes if t['descricao'] not in ["Renda passiva por atividade em voz", "Renda passiva por atividade no chat"] and not t['descricao'].startswith("Recompensa por reagir")):
            embed.description += "\n\nNenhuma atividade registada para esta data."

        await ctx.send(embed=embed)

    @commands.command(name="resgatar")
    @check_permission_level(3)
    async def resgatar(self, ctx, membro: discord.Member, valor: int):
        if valor <= 0:
            return await ctx.send("❌ O valor a resgatar deve ser positivo.")

        economia_cog = self.bot.get_cog('Economia')
        
        try:
            await economia_cog.levantar(membro.id, valor, f"Resgate de moedas por {ctx.author.name}")

            configs = await self.bot.db_manager.get_all_configs(['canal_resgates', 'taxa_conversao_prata'])
            canal_resgates_id = int(configs.get('canal_resgates', '0'))

            if canal_resgates_id != 0:
                canal = self.bot.get_channel(canal_resgates_id)
                if canal:
                    taxa_conversao = int(configs.get('taxa_conversao_prata', '1000'))
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
        except ValueError as e:
             await ctx.send(f"❌ Erro: {e}")


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

        erros = 0
        sucessos = 0
        for membro in membros_alvo:
            try:
                await economia_cog.depositar(membro.id, valor, "Airdrop da Administração")
                sucessos += 1
            except Exception as e:
                print(f"Erro ao depositar airdrop para {membro.name}: {e}")
                erros += 1
            await asyncio.sleep(0.2) 

        await msg_espera.edit(content=f"✅ Airdrop concluído! **{sucessos}** membros receberam as moedas. Falhas: **{erros}**.")


async def setup(bot):
    await bot.add_cog(Utilidades(bot))
