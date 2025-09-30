import discord
from discord.ext import commands
import psycopg2
import psycopg2.extras
from psycopg2 import pool
import os
import contextlib

# --- Funções Auxiliares (copiadas para autonomia do Cog) ---
DATABASE_URL = os.getenv('DATABASE_URL')
db_connection_pool = None

def initialize_cog_connection_pool():
    global db_connection_pool
    if not db_connection_pool:
        try:
            db_connection_pool = psycopg2.pool.SimpleConnectionPool(1, 5, dsn=DATABASE_URL)
        except Exception as e:
            print(f"Erro ao inicializar pool em 'ajuda': {e}")

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
    """Função de verificação de permissão para ser usada dentro do Cog."""
    async def predicate(ctx):
        if ctx.author.guild_permissions.administrator: return True
        author_roles_ids = {str(role.id) for role in ctx.author.roles}
        for i in range(level, 5):
            perm_key = f'perm_nivel_{i}'
            role_id_str = get_config_value(perm_key, '0')
            if role_id_str in author_roles_ids: return True
        return False
    return commands.check(predicate)

class Ajuda(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        initialize_cog_connection_pool()

    @commands.command(name='ajuda')
    async def help_command(self, ctx):
        """Mostra uma lista de comandos disponíveis com base nas permissões do utilizador."""
        embed = discord.Embed(
            title="Ajuda do Arauto Bank",
            description=f"Olá {ctx.author.mention}, aqui estão os comandos que você pode usar:",
            color=discord.Color.purple()
        )

        # Comandos para todos
        embed.add_field(
            name="🪙 Comandos de Membro (Todos)",
            value="`!saldo`, `!extrato`, `!transferir`, `!loja`, `!comprar`, `!infomoeda`, `!listareventos`, `!participar`, `!meuprogresso`, `!orbe`, `!pagar-taxa`, `!paguei-prata`",
            inline=False
        )

        # Comandos para Nível 1+ (Puxadores/Oficiais)
        if await check_permission_level(1).predicate(ctx):
             embed.add_field(
                 name="🛠️ Comandos de Puxador (Nível 1+)",
                 value="`!puxar`, `!confirmar-todos`, `!confirmar`, `!finalizarevento`, `!cancelarevento`",
                 inline=False
             )

        # Comandos para Nível 2+ (Supervisão)
        if await check_permission_level(2).predicate(ctx):
            embed.add_field(
                name="📋 Comandos de Supervisão (Nível 2+)",
                value="*(Aprovações de orbes e taxas via reação)*",
                inline=False
            )
        
        # Comandos para Nível 3+ (Gestão)
        if await check_permission_level(3).predicate(ctx):
            embed.add_field(
                name="💸 Comandos de Gestão (Nível 3+)",
                value="`!emitir`, `!airdrop`, `!perdoar-taxa`",
                inline=False
            )

        # Comandos para Nível 4 (Liderança)
        if await check_permission_level(4).predicate(ctx):
            embed.add_field(
                name="👑 Comandos de Admin (Nível 4)",
                value="`!ajustar-lastro`, `!config-bot`, `!config-recompensa`, `!config-orbe`, `!config-taxa`",
                inline=False
            )
        
        try:
            await ctx.author.send(embed=embed)
            await ctx.message.add_reaction('✅')
            await ctx.send("Enviei-lhe uma mensagem privada com os seus comandos disponíveis!", delete_after=10)
        except discord.Forbidden:
            await ctx.send("Não consigo enviar-lhe uma mensagem privada. Por favor, verifique as suas configurações de privacidade.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Ajuda(bot))

