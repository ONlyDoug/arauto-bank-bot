import discord
from discord.ext import commands, tasks
import psycopg2
import psycopg2.extras
from psycopg2 import pool
import os
import contextlib
from datetime import datetime, date
import time
import random

# Funções auxiliares de BD
DATABASE_URL = os.getenv('DATABASE_URL')
db_connection_pool = None
ID_TESOURO_GUILDA = 1

def initialize_cog_connection_pool():
    global db_connection_pool
    if not db_connection_pool:
        try:
            db_connection_pool = psycopg2.pool.SimpleConnectionPool(1, 10, dsn=DATABASE_URL)
        except Exception as e:
            print(f"Erro ao inicializar pool em 'economia': {e}")

@contextlib.contextmanager
def get_db_connection():
    if db_connection_pool is None: raise Exception("Pool não inicializado.")
    conn = None
    try:
        conn = db_connection_pool.getconn()
        yield conn
    finally:
        if conn: db_connection_pool.putconn(conn)

def get_config_value(chave: str, default: str = None):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT valor FROM configuracoes WHERE chave = %s", (chave,)); resultado = cursor.fetchone()
    return resultado[0] if resultado else default

def get_account(user_id: int):
     with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1 FROM banco WHERE user_id = %s", (user_id,))
            if cursor.fetchone() is None:
                cursor.execute("INSERT INTO banco (user_id, saldo) VALUES (%s, 0) ON CONFLICT (user_id) DO NOTHING", (user_id,)); conn.commit()

def registrar_transacao(user_id: int, tipo: str, valor: int, descricao: str):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("INSERT INTO transacoes (user_id, tipo, valor, descricao) VALUES (%s, %s, %s, %s)", (user_id, tipo, valor, descricao)); conn.commit()

def get_or_create_daily_activity(user_id: int, target_date: date):
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            cursor.execute("SELECT * FROM atividade_diaria WHERE user_id = %s AND data = %s", (user_id, target_date))
            activity = cursor.fetchone()
            if activity is None:
                cursor.execute("INSERT INTO atividade_diaria (user_id, data) VALUES (%s, %s) ON CONFLICT (user_id, data) DO NOTHING", (user_id, target_date)); conn.commit()
                cursor.execute("SELECT * FROM atividade_diaria WHERE user_id = %s AND data = %s", (user_id, target_date)); activity = cursor.fetchone()
    return activity

class Economia(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        initialize_cog_connection_pool()
        self.user_message_cooldowns = {}

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return

        ctx = await self.bot.get_context(message)
        if ctx.valid: return

        user_id = message.author.id
        current_time = time.time()
        cooldown_seconds = int(get_config_value('cooldown_chat', '60'))
        
        if user_id in self.user_message_cooldowns and current_time - self.user_message_cooldowns[user_id] < cooldown_seconds:
            return
        
        get_account(user_id)
        activity = get_or_create_daily_activity(user_id, date.today())
        limite_diario = int(get_config_value('limite_diario_chat', '100'))
        recompensa = int(get_config_value('recompensa_chat', '1'))
        
        if activity and activity['moedas_chat'] < limite_diario:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("UPDATE banco SET saldo = saldo + %s WHERE user_id = %s", (recompensa, user_id))
                    cursor.execute("UPDATE atividade_diaria SET moedas_chat = moedas_chat + %s WHERE user_id = %s AND data = %s", (recompensa, user_id, date.today())); conn.commit()
            self.user_message_cooldowns[user_id] = current_time

    @commands.command(name='saldo')
    async def balance(self, ctx):
        """Mostra o seu saldo atual em moedas."""
        get_account(ctx.author.id)
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT saldo FROM banco WHERE user_id = %s", (ctx.author.id,)); saldo = cursor.fetchone()[0]
        embed = discord.Embed(title=f"Saldo de {ctx.author.display_name}", description=f"Você possui **{saldo:,}** 🪙.", color=discord.Color.gold())
        await ctx.send(embed=embed)
    
    # (Resto dos comandos de economia)
    @commands.command(name='transferir')
    async def transfer(self, ctx, destinatario: discord.Member, quantidade: int):
        remetente_id = ctx.author.id; destinatario_id = destinatario.id
        if remetente_id == destinatario_id: return await ctx.send("Você não pode transferir para si mesmo.")
        if quantidade <= 0: return await ctx.send("A quantidade deve ser positiva.")
        get_account(remetente_id); get_account(destinatario_id)
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT saldo FROM banco WHERE user_id = %s FOR UPDATE", (remetente_id,)); saldo_remetente = cursor.fetchone()[0]
                if saldo_remetente < quantidade: return await ctx.send("Saldo insuficiente.")
                cursor.execute("UPDATE banco SET saldo = saldo - %s WHERE user_id = %s", (quantidade, remetente_id))
                cursor.execute("UPDATE banco SET saldo = saldo + %s WHERE user_id = %s", (quantidade, destinatario_id)); conn.commit()
        registrar_transacao(remetente_id, "Transferência Enviada", -quantidade, f"Para {destinatario.display_name}")
        registrar_transacao(destinatario_id, "Transferência Recebida", quantidade, f"De {ctx.author.display_name}")
        embed = discord.Embed(title="💸 Transferência Realizada", description=f"**{ctx.author.display_name}** transferiu **{quantidade:,}** 🪙 para **{destinatario.display_name}**.", color=discord.Color.green())
        await ctx.send(embed=embed)
    
    @commands.command(name='infomoeda')
    async def coin_info(self, ctx):
        taxa_conversao = int(get_config_value('lastro_prata', '1000')); lastro_total = int(get_config_value('lastro_total_prata', '0'))
        suprimento_maximo = lastro_total // taxa_conversao if taxa_conversao > 0 else 0
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT saldo FROM banco WHERE user_id = %s", (ID_TESOURO_GUILDA,)); saldo_tesouro = cursor.fetchone()[0]
        moedas_com_membros = suprimento_maximo - saldo_tesouro
        embed = discord.Embed(title="📈 Estatísticas do Arauto Bank", color=discord.Color.dark_blue())
        embed.add_field(name="Lastro Total de Prata", value=f"{lastro_total:,} 🥈", inline=False)
        embed.add_field(name="Taxa de Câmbio", value=f"1 🪙 = {taxa_conversao:,} 🥈", inline=False)
        embed.add_field(name="Suprimento Máximo", value=f"{suprimento_maximo:,} 🪙", inline=True)
        embed.add_field(name="Moedas no Tesouro", value=f"{saldo_tesouro:,} 🪙", inline=True)
        embed.add_field(name="Moedas com Membros", value=f"{moedas_com_membros:,} 🪙", inline=True)
        await ctx.send(embed=embed)
    
    @commands.command(name='loja')
    async def shop(self, ctx):
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
                cursor.execute("SELECT item_id, nome, preco, descricao FROM loja ORDER BY preco ASC"); itens = cursor.fetchall()
        if not itens: return await ctx.send("A loja está vazia no momento.")
        embed = discord.Embed(title="🎁 Loja de Recompensas", color=discord.Color.purple())
        for item in itens: embed.add_field(name=f"**{item['nome']}** (ID: {item['item_id']})", value=f"**Preço:** {item['preco']:,} 🪙\n*_{item['descricao']}_*", inline=False)
        await ctx.send(embed=embed)
    
    @commands.command(name='comprar')
    async def buy(self, ctx, item_id: str):
        comprador_id = ctx.author.id; get_account(comprador_id)
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
                cursor.execute("SELECT nome, preco FROM loja WHERE item_id = %s", (item_id,)); item = cursor.fetchone()
                if item is None: return await ctx.send(f"O item com ID `{item_id}` não foi encontrado.")
                cursor.execute("SELECT saldo FROM banco WHERE user_id = %s FOR UPDATE", (comprador_id,)); saldo_comprador = cursor.fetchone()['saldo']
                if saldo_comprador < item['preco']: return await ctx.send(f"Saldo insuficiente! Faltam **{item['preco'] - saldo_comprador:,}** 🪙.")
                cursor.execute("UPDATE banco SET saldo = saldo - %s WHERE user_id = %s", (item['preco'], comprador_id))
                cursor.execute("UPDATE banco SET saldo = saldo + %s WHERE user_id = %s", (item['preco'], ID_TESOURO_GUILDA)); conn.commit()
                registrar_transacao(comprador_id, "Compra na Loja", -item['preco'], f"Comprou '{item['nome']}'")
        await ctx.send(f"🎉 Parabéns, {ctx.author.mention}! Você comprou **{item['nome']}** por **{item['preco']:,}** 🪙.")
        # (Lógica de notificação da staff omitida por brevidade)

async def setup(bot):
    await bot.add_cog(Economia(bot))

