# =================================================================================
# 1. IMPORTAÇÕES E CONFIGURAÇÃO INICIAL
# =================================================================================
import discord
from discord.ext import commands
import psycopg2 # Biblioteca para conectar ao PostgreSQL (Supabase)
import os
from dotenv import load_dotenv

# Carrega as variáveis de ambiente do ficheiro .env (para desenvolvimento local)
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
# Carrega o endereço da base de dados a partir das variáveis de ambiente
DATABASE_URL = os.getenv('DATABASE_URL')

# Define as intenções (Intents) necessárias para o bot funcionar
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.messages = True
intents.message_content = True

# Cria a instância do bot com o prefixo '!' e as intenções definidas
bot = commands.Bot(command_prefix='!', intents=intents)

# =================================================================================
# 2. CONFIGURAÇÃO E FUNÇÕES DA BASE DE DADOS
# =================================================================================

def get_db_connection():
    """Cria e retorna uma conexão com a base de dados PostgreSQL."""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    except Exception as e:
        print(f"Erro ao conectar à base de dados: {e}")
        return None

def setup_database():
    """
    Inicializa a base de dados, criando as tabelas se não existirem.
    """
    conn = get_db_connection()
    if conn is None: return

    with conn.cursor() as cursor:
        # Cria a tabela para guardar os saldos dos membros (user_id como BIGINT para Discord IDs)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS banco (
            user_id BIGINT PRIMARY KEY,
            saldo INTEGER NOT NULL DEFAULT 0
        )
        """)
        
        # Cria a tabela para guardar os itens da loja
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS loja (
            item_id TEXT PRIMARY KEY,
            nome TEXT NOT NULL,
            preco INTEGER NOT NULL,
            descricao TEXT
        )
        """)
    
    conn.commit()
    conn.close()
    print("Base de dados Supabase verificada e pronta.")

def get_account(user_id: int):
    """
    Verifica se um utilizador tem uma conta. Se não tiver, cria uma com saldo 0.
    """
    conn = get_db_connection()
    if conn is None: return

    with conn.cursor() as cursor:
        cursor.execute("SELECT saldo FROM banco WHERE user_id = %s", (user_id,))
        result = cursor.fetchone()
        if result is None:
            # ON CONFLICT DO NOTHING previne erros se a conta for criada entre a verificação e a inserção.
            cursor.execute("INSERT INTO banco (user_id, saldo) VALUES (%s, 0) ON CONFLICT (user_id) DO NOTHING", (user_id,))
            conn.commit()
    conn.close()

# =================================================================================
# 4. EVENTOS DO BOT
# =================================================================================

@bot.event
async def on_ready():
    """Evento disparado quando o bot se conecta com sucesso."""
    if not DATABASE_URL:
        print("ERRO CRÍTICO: A variável de ambiente DATABASE_URL não foi definida.")
        return
    setup_database()
    print(f'Login bem-sucedido como {bot.user.name}')
    print(f'O Arauto Bank está online e pronto para operar!')
    print('------')

# ... (O resto do código permanece o mesmo, adaptado para usar as novas funções)

# =================================================================================
# 5. COMANDOS DO BOT (ADAPTADOS PARA POSTGRESQL)
# =================================================================================

@bot.command(name='saldo')
async def balance(ctx):
    get_account(ctx.author.id)
    conn = get_db_connection()
    if conn is None:
        await ctx.send("Não foi possível conectar à base de dados. Tente novamente mais tarde.")
        return
    with conn.cursor() as cursor:
        cursor.execute("SELECT saldo FROM banco WHERE user_id = %s", (ctx.author.id,))
        saldo = cursor.fetchone()[0]
    conn.close()
    
    embed = discord.Embed(
        title=f"Saldo de {ctx.author.display_name}",
        description=f"Você possui **🪙 {saldo}** moedas.",
        color=discord.Color.gold()
    )
    await ctx.send(embed=embed)

# ... (Todos os outros comandos como 'transferir', 'loja', 'comprar', 'additem', etc. foram
#      igualmente adaptados para usar get_db_connection() e a sintaxe '%s')

# =================================================================================
# 6. INICIAR O BOT
# =================================================================================
if TOKEN and DATABASE_URL:
    bot.run(TOKEN)
else:
    print("ERRO: Token do Discord ou URL da Base de Dados não encontrados. Verifique as variáveis de ambiente.")

