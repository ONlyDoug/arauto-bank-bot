import discord
from discord.ext import commands
import contextlib
from utils.permissions import check_permission_level
from datetime import datetime, date

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
        latency = round(self.bot.latency * 1000)
        await ctx.send(f"Pong! Latência: `{latency}ms`. O Arauto Bank está operacional.")

    @commands.command(name='extrato')
    async def extrato(self, ctx, data_str: str = None):
        """Mostra o extrato de um dia específico, incluindo um resumo de ganhos passivos."""
        target_date = None
        if data_str:
            try:
                # Tenta analisar a data no formato AAAA-MM-DD
                target_date = datetime.strptime(data_str, '%Y-%m-%d').date()
            except ValueError:
                return await ctx.send("Formato de data inválido. Use `AAAA-MM-DD` ou deixe em branco para ver o dia de hoje.")
        else:
            # Se nenhuma data for fornecida, usa a data atual
            target_date = date.today()

        with self.get_db_connection() as conn:
            with conn.cursor() as cursor:
                # 1. Buscar o resumo de ganhos passivos para o dia
                cursor.execute(
                    "SELECT minutos_voz, moedas_chat FROM atividade_diaria WHERE user_id = %s AND data = %s",
                    (ctx.author.id, target_date)
                )
                ganhos_passivos = cursor.fetchone()
                
                # 2. Buscar todas as outras transações para o dia
                start_of_day = datetime.combine(target_date, datetime.min.time())
                end_of_day = datetime.combine(target_date, datetime.max.time())
                cursor.execute(
                    "SELECT tipo, valor, descricao, data FROM transacoes WHERE user_id = %s AND data BETWEEN %s AND %s ORDER BY data DESC",
                    (ctx.author.id, start_of_day, end_of_day)
                )
                transacoes = cursor.fetchall()

        if not ganhos_passivos and not transacoes:
            return await ctx.send(f"Não há nenhuma atividade registada para o dia {target_date.strftime('%d/%m/%Y')}.")

        embed = discord.Embed(
            title=f"📜 Extrato de {ctx.author.display_name}",
            description=f"Atividade do dia: **{target_date.strftime('%d de %B de %Y')}**",
            color=discord.Color.blue()
        )

        # 3. Adicionar o campo de resumo de ganhos passivos
        if ganhos_passivos:
            minutos_voz, moedas_chat = ganhos_passivos
            admin_cog = self.bot.get_cog('Admin')
            recompensa_voz_por_ciclo = int(admin_cog.get_config_value('recompensa_voz', '0'))
            
            moedas_voz = (minutos_voz // 5) * recompensa_voz_por_ciclo
            
            resumo_passivo = []
            if moedas_voz > 0:
                resumo_passivo.append(f"🎙️ **Voz:** `{moedas_voz}`")
            if moedas_chat > 0:
                resumo_passivo.append(f"💬 **Chat:** `{moedas_chat}`")
            
            if resumo_passivo:
                 embed.add_field(
                    name="Resumo de Ganhos Passivos do Dia",
                    value=" | ".join(resumo_passivo),
                    inline=False
                )

        # 4. Adicionar as transações individuais
        if transacoes:
            lista_transacoes = []
            for tipo, valor, descricao, data in transacoes:
                timestamp = int(data.timestamp())
                emoji = "📥" if valor > 0 else "📤"
                valor_formatado = f"{valor:,}".replace(',', '.')
                # Omite descrição se for genérica de renda passiva
                desc_final = f"*({descricao})*" if descricao and "passiva" not in tipo else ""
                lista_transacoes.append(f"{emoji} **{valor_formatado} GC** às <t:{timestamp}:T> | `{tipo}` {desc_final}")
            
            if lista_transacoes:
                embed.add_field(name="\nTransações do Dia", value="\n".join(lista_transacoes), inline=False)
        
        # Se não houver transações mas houver ganhos passivos, informa.
        elif not transacoes and ganhos_passivos:
            embed.add_field(name="\nTransações do Dia", value="Nenhuma transação ativa registada.", inline=False)

        await ctx.send(embed=embed)


    @commands.command(name='info-moeda', aliases=['infomoeda', 'lastro'])
    async def info_moeda(self, ctx):
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
        embed.add_field(name="🥈 Lastro Total de Prata", value=f"**{lastro_total_prata:,}**".replace(',', '.'), inline=False)
        embed.add_field(name="💱 Taxa de Conversão", value=f"`1 🪙 = {taxa_conversao:,} 🥈`".replace(',', '.'), inline=False)
        embed.add_field(name="🏦 Suprimento Máximo de Moedas", value=f"{suprimento_maximo:,}".replace(',', '.'), inline=True)
        embed.add_field(name="💰 Moedas no Tesouro", value=f"{moedas_tesouro:,}".replace(',', '.'), inline=True)
        embed.add_field(name="💸 Moedas em Circulação", value=f"{moedas_em_circulacao:,}".replace(',', '.'), inline=True)
        
        await ctx.send(embed=embed)
    
    @commands.command(name='definir-lastro')
    @check_permission_level(4)
    async def definir_lastro(self, ctx, total_prata: int):
        if total_prata < 0:
            return await ctx.send("O valor do lastro não pode ser negativo.")
            
        self.bot.get_cog('Admin').set_config_value('lastro_total_prata', str(total_prata))
        await ctx.send(f"✅ O lastro total de prata foi definido para **{total_prata:,}**.".replace(',', '.'))

async def setup(bot):
    await bot.add_cog(Utilidades(bot))

