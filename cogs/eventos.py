import discord
from discord.ext import commands
import psycopg2
import psycopg2.extras
from psycopg2 import pool
import os
import contextlib

# Funções auxiliares
DATABASE_URL = os.getenv('DATABASE_URL')
db_connection_pool = None

def initialize_cog_connection_pool():
    global db_connection_pool
    if not db_connection_pool:
        try:
            db_connection_pool = psycopg2.pool.SimpleConnectionPool(1, 10, dsn=DATABASE_URL)
        except Exception as e:
            print(f"Erro ao inicializar pool em 'eventos': {e}")

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

def check_permission_level(level: int):
    async def predicate(ctx):
        if ctx.author.guild_permissions.administrator: return True
        author_roles_ids = {str(role.id) for role in ctx.author.roles}
        for i in range(level, 5):
            perm_key = f'perm_nivel_{i}'
            role_id_str = get_config_value(perm_key, '0')
            if role_id_str in author_roles_ids: return True
        return False
    return commands.check(predicate)

class Eventos(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        initialize_cog_connection_pool()

    @commands.command(name='puxar')
    @check_permission_level(1)
    async def pull_event(self, ctx, tier: str, *, nome_evento: str):
        tier = tier.lower()
        if tier not in ['bronze', 'prata', 'ouro']: return await ctx.send("Tier inválido. Use `bronze`, `prata` ou `ouro`.")
        recompensa = int(get_config_value(f'recompensa_tier_{tier}', '0'))
        if recompensa == 0: return await ctx.send(f"O tier `{tier}` não tem um valor configurado.")
        embed = discord.Embed(title=f"📢 Evento Rápido: {nome_evento}", description=f"Organizado por {ctx.author.mention}", color=discord.Color.blue())
        embed.add_field(name="Recompensa", value=f"**{recompensa:,}** 🪙 (Tier: {tier.capitalize()})")
        embed.set_footer(text="Reaja com ✅ para confirmar sua presença!")
        sent_message = await ctx.send(embed=embed)
        await sent_message.add_reaction("✅")
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("INSERT INTO eventos (nome, recompensa, meta_participacao, criador_id, message_id) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                               (nome_evento, recompensa, 1, ctx.author.id, sent_message.id)); evento_id = cursor.fetchone()[0]; conn.commit()
        await ctx.send(f"Evento rápido `{nome_evento}` (ID: {evento_id}) criado. Use `!confirmar-todos {evento_id}` para pagar.")
    
    # (Resto dos comandos de eventos)

async def setup(bot):
    await bot.add_cog(Eventos(bot))

