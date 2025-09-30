# =================================================================================
# 1. IMPORTAÇÕES E CONFIGURAÇÃO INICIAL
# =================================================================================
import discord
from discord.ext import commands, tasks
import psycopg2
import psycopg2.extras
from psycopg2 import pool
import os
from dotenv import load_dotenv
from datetime import datetime, date, timedelta
import time
import contextlib
import asyncio
import random

# Carrega as variáveis de ambiente
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')

# Define as intenções do bot
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.messages = True
intents.message_content = True
intents.voice_states = True
intents.reactions = True

# Cria a instância do bot
bot = commands.Bot(command_prefix='!', intents=intents, case_insensitive=True)

# Constantes e Variáveis Globais
ID_TESOURO_GUILDA = 1
db_connection_pool = None
user_message_cooldowns = {}

# =================================================================================
# 2. GESTÃO OTIMIZADA DA BASE DE DADOS
# =================================================================================

def initialize_connection_pool():
    """Inicializa o pool de conexões com a base de dados."""
    global db_connection_pool
    try:
        db_connection_pool = psycopg2.pool.SimpleConnectionPool(1, 20, dsn=DATABASE_URL)
        if db_connection_pool: print("Pool de conexões com a base de dados inicializado com sucesso.")
    except Exception as e:
        print(f"ERRO CRÍTICO ao inicializar o pool de conexões: {e}")

@contextlib.contextmanager
def get_db_connection():
    """Obtém uma conexão do pool e garante que ela é devolvida."""
    if db_connection_pool is None: raise Exception("O pool de conexões não foi inicializado.")
    conn = None
    try:
        conn = db_connection_pool.getconn()
        yield conn
    finally:
        if conn: db_connection_pool.putconn(conn)

def setup_database():
    """Inicializa a base de dados, criando todas as tabelas e configurações se não existirem."""
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            # Estrutura de tabelas
            cursor.execute("CREATE TABLE IF NOT EXISTS banco (user_id BIGINT PRIMARY KEY, saldo BIGINT NOT NULL DEFAULT 0)")
            cursor.execute("""CREATE TABLE IF NOT EXISTS transacoes (id SERIAL PRIMARY KEY, user_id BIGINT NOT NULL, tipo TEXT NOT NULL,
                valor BIGINT NOT NULL, descricao TEXT, data TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP)""")
            cursor.execute("""CREATE TABLE IF NOT EXISTS eventos (id SERIAL PRIMARY KEY, nome TEXT NOT NULL, recompensa INTEGER NOT NULL,
                meta_participacao INTEGER NOT NULL DEFAULT 1, ativo BOOLEAN DEFAULT TRUE, criador_id BIGINT NOT NULL, message_id BIGINT)""")
            cursor.execute("""CREATE TABLE IF NOT EXISTS participantes (evento_id INTEGER REFERENCES eventos(id) ON DELETE CASCADE,
                user_id BIGINT, progresso INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (evento_id, user_id))""")
            cursor.execute("CREATE TABLE IF NOT EXISTS configuracoes (chave TEXT PRIMARY KEY, valor TEXT NOT NULL)")
            cursor.execute("""CREATE TABLE IF NOT EXISTS taxas (user_id BIGINT PRIMARY KEY, data_vencimento DATE, status TEXT DEFAULT 'pago')""")
            cursor.execute("""CREATE TABLE IF NOT EXISTS submissoes_orbe (id SERIAL PRIMARY KEY, message_id BIGINT, cor TEXT NOT NULL, 
                valor_total INTEGER NOT NULL, autor_id BIGINT, membros TEXT, status TEXT DEFAULT 'pendente')""")

            default_configs = { 'lastro_total_prata': '0', 'lastro_prata': '1000', 'recompensa_tier_bronze': '50', 'recompensa_tier_prata': '100', 'recompensa_tier_ouro': '200', 'orbe_verde': '100', 'orbe_azul': '250', 'orbe_roxa': '500', 'orbe_dourada': '1000', 'taxa_semanal_valor': '500', 'cargo_membro': '0', 'cargo_inadimplente': '0', 'cargo_isento': '0', 'perm_nivel_1': '0', 'perm_nivel_2': '0', 'perm_nivel_3': '0', 'perm_nivel_4': '0', 'canal_aprovacao': '0', 'canal_mercado': '0', 'canal_orbes': '0', 'canal_taxas': '0' }
            for chave, valor in default_configs.items():
                cursor.execute("INSERT INTO configuracoes (chave, valor) VALUES (%s, %s) ON CONFLICT (chave) DO NOTHING", (chave, valor))
            
            cursor.execute("INSERT INTO banco (user_id, saldo) VALUES (%s, 0) ON CONFLICT (user_id) DO NOTHING", (ID_TESOURO_GUILDA,))
        conn.commit()
    print("Base de dados Supabase verificada e pronta.")

def get_config_value(chave: str, default: str = None):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT valor FROM configuracoes WHERE chave = %s", (chave,)); resultado = cursor.fetchone()
    return resultado[0] if resultado else default

def set_config_value(chave: str, valor: str):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("INSERT INTO configuracoes (chave, valor) VALUES (%s, %s) ON CONFLICT (chave) DO UPDATE SET valor = EXCLUDED.valor", (chave, valor)); conn.commit()

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
            
# =================================================================================
# 3. HIERARQUIA DE PERMISSÕES E EVENTOS
# =================================================================================
def check_permission_level(level: int):
    async def predicate(ctx):
        if ctx.author.guild_permissions.administrator: return True
        author_roles_ids = {str(role.id) for role in ctx.author.roles}
        for i in range(level, 5):
            perm_key = f'perm_nivel_{i}'
            role_id_str = get_config_value(perm_key, '0')
            if role_id_str in author_roles_ids: return True
        await ctx.send("Você não tem permissão para usar este comando.", ephemeral=True, delete_after=10)
        return False
    return commands.check(predicate)

@bot.event
async def on_ready():
    if not DATABASE_URL: print("ERRO CRÍTICO: DATABASE_URL não definida."); return
    initialize_connection_pool()
    setup_database()
    print(f'Login bem-sucedido como {bot.user.name}'); print('------')

# (Resto dos eventos e comandos omitidos por brevidade)

# =================================================================================
# 6. INICIAR O BOT
# =================================================================================
if TOKEN and DATABASE_URL:
    bot.run(TOKEN)
else:
    print("ERRO: Variáveis de ambiente essenciais não encontradas.")

