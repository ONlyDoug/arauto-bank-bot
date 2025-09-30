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
from datetime import datetime, date
import time
import contextlib

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

# Cria a instância do bot
bot = commands.Bot(command_prefix='!', intents=intents)

# Constantes
ID_TESOURO_GUILDA = 1 # ID reservado para a conta do Tesouro da Guilda

# Variáveis de controlo em memória
user_message_cooldowns = {}
db_connection_pool = None

# =================================================================================
# 2. GESTÃO OTIMIZADA DA BASE DE DADOS
# =================================================================================

def initialize_connection_pool():
    """Inicializa o pool de conexões com a base de dados."""
    global db_connection_pool
    try:
        db_connection_pool = psycopg2.pool.SimpleConnectionPool(1, 10, dsn=DATABASE_URL)
        if db_connection_pool:
            print("Pool de conexões com a base de dados inicializado com sucesso.")
    except Exception as e:
        print(f"ERRO CRÍTICO ao inicializar o pool de conexões: {e}")

@contextlib.contextmanager
def get_db_connection():
    """Obtém uma conexão do pool e garante que ela é devolvida."""
    if db_connection_pool is None:
        raise Exception("O pool de conexões não foi inicializado.")
    conn = None
    try:
        conn = db_connection_pool.getconn()
        yield conn
    finally:
        if conn:
            db_connection_pool.putconn(conn)

def setup_database():
    """Inicializa a base de dados, criando todas as tabelas e configurações se não existirem."""
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            # (Criação de tabelas inalterada)
            cursor.execute("CREATE TABLE IF NOT EXISTS banco (user_id BIGINT PRIMARY KEY, saldo INTEGER NOT NULL DEFAULT 0)")
            cursor.execute("CREATE TABLE IF NOT EXISTS loja (item_id TEXT PRIMARY KEY, nome TEXT NOT NULL, preco INTEGER NOT NULL, descricao TEXT)")
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS transacoes (id SERIAL PRIMARY KEY, user_id BIGINT NOT NULL, tipo TEXT NOT NULL,
                valor INTEGER NOT NULL, descricao TEXT, data TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP)""")
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS eventos (id SERIAL PRIMARY KEY, nome TEXT NOT NULL, recompensa INTEGER NOT NULL,
                meta_participacao INTEGER NOT NULL DEFAULT 1, ativo BOOLEAN DEFAULT TRUE, criador_id BIGINT NOT NULL,
                data_criacao TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP)""")
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS participantes (evento_id INTEGER REFERENCES eventos(id) ON DELETE CASCADE,
                user_id BIGINT, progresso INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (evento_id, user_id))""")
            cursor.execute("CREATE TABLE IF NOT EXISTS configuracoes (chave TEXT PRIMARY KEY, valor TEXT NOT NULL)")
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS atividade_diaria (user_id BIGINT, data DATE, moedas_chat INTEGER DEFAULT 0, 
                minutos_voz INTEGER DEFAULT 0, PRIMARY KEY (user_id, data))""")
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS reacoes_recompensadas (message_id BIGINT, user_id BIGINT, 
                PRIMARY KEY (message_id, user_id))""")

            default_configs = {
                'lastro_prata': '1000', 'lastro_total_prata': '0', 'recompensa_voz': '10', 'recompensa_chat': '1', 
                'recompensa_reacao': '50', 'limite_diario_voz': '120', 'limite_diario_chat': '100', 
                'cooldown_chat': '60', 'canal_anuncios': '0', 'cargos_gerente_eventos': ''
            }
            for chave, valor in default_configs.items():
                cursor.execute("INSERT INTO configuracoes (chave, valor) VALUES (%s, %s) ON CONFLICT (chave) DO NOTHING", (chave, valor))
            
            # Garante que a conta do Tesouro da Guilda existe
            cursor.execute("INSERT INTO banco (user_id, saldo) VALUES (%s, 0) ON CONFLICT (user_id) DO NOTHING", (ID_TESOURO_GUILDA,))

        conn.commit()
    print("Base de dados Supabase verificada e pronta (com sistema de lastro 1:1).")

# (Funções get_config_value, set_config_value, etc., permanecem iguais)
def get_config_value(chave: str, default: str = None):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT valor FROM configuracoes WHERE chave = %s", (chave,))
            resultado = cursor.fetchone()
    return resultado[0] if resultado else default

def set_config_value(chave: str, valor: str):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("INSERT INTO configuracoes (chave, valor) VALUES (%s, %s) ON CONFLICT (chave) DO UPDATE SET valor = EXCLUDED.valor", (chave, valor))
            conn.commit()

def get_account(user_id: int):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1 FROM banco WHERE user_id = %s", (user_id,))
            if cursor.fetchone() is None:
                cursor.execute("INSERT INTO banco (user_id, saldo) VALUES (%s, 0) ON CONFLICT (user_id) DO NOTHING", (user_id,))
                conn.commit()

def registrar_transacao(user_id: int, tipo: str, valor: int, descricao: str):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("INSERT INTO transacoes (user_id, tipo, valor, descricao) VALUES (%s, %s, %s, %s)", (user_id, tipo, valor, descricao))
            conn.commit()
# (Resto das funções auxiliares inalteradas)
def get_or_create_daily_activity(user_id: int, target_date: date):
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            cursor.execute("SELECT * FROM atividade_diaria WHERE user_id = %s AND data = %s", (user_id, target_date))
            activity = cursor.fetchone()
            if activity is None:
                cursor.execute("INSERT INTO atividade_diaria (user_id, data) VALUES (%s, %s) ON CONFLICT (user_id, data) DO NOTHING", (user_id, target_date))
                conn.commit()
                cursor.execute("SELECT * FROM atividade_diaria WHERE user_id = %s AND data = %s", (user_id, target_date))
                activity = cursor.fetchone()
    return activity

# =================================================================================
# 3. VERIFICAÇÕES DE PERMISSÃO E EVENTOS
# =================================================================================
def can_manage_events():
    async def predicate(ctx):
        if ctx.author.guild_permissions.administrator: return True
        roles_id_str = get_config_value('cargos_gerente_eventos', '');
        if not roles_id_str: return False
        allowed_role_ids = {int(id_str) for id_str in roles_id_str.split(',') if id_str}
        author_role_ids = {role.id for role in ctx.author.roles}
        if not allowed_role_ids.isdisjoint(author_role_ids): return True
        return False
    return commands.check(predicate)

@bot.event
async def on_ready():
    if not DATABASE_URL: print("ERRO CRÍTICO: A variável de ambiente DATABASE_URL não foi definida."); return
    initialize_connection_pool()
    setup_database()
    print(f'Login bem-sucedido como {bot.user.name}')
    print(f'O Arauto Bank está online e pronto para operar!'); print('------')
# (Resto dos eventos e tarefas em background inalterados)
# =================================================================================
# 5. COMANDOS DO BOT
# =================================================================================

# --- Comandos de Economia (com novas funcionalidades) ---
@bot.command(name='saldo')
async def balance(ctx):
    get_account(ctx.author.id)
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT saldo FROM banco WHERE user_id = %s", (ctx.author.id,)); saldo = cursor.fetchone()[0]
    embed = discord.Embed(title=f"Saldo de {ctx.author.display_name}", description=f"Você possui **🪙 {saldo:,}** moedas.", color=discord.Color.gold())
    await ctx.send(embed=embed)

@bot.command(name='infomoeda')
async def coin_info(ctx):
    """Mostra as estatísticas da economia da guilda."""
    taxa_conversao = int(get_config_value('lastro_prata', '1000'))
    lastro_total = int(get_config_value('lastro_total_prata', '0'))
    
    suprimento_maximo = lastro_total // taxa_conversao if taxa_conversao > 0 else 0

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT saldo FROM banco WHERE user_id = %s", (ID_TESOURO_GUILDA,))
            saldo_tesouro = cursor.fetchone()[0]
    
    moedas_com_membros = suprimento_maximo - saldo_tesouro

    embed = discord.Embed(title="📈 Estatísticas do Arauto Bank", color=discord.Color.dark_blue())
    embed.add_field(name="Lastro Total de Prata", value=f"{lastro_total:,} 🥈", inline=False)
    embed.add_field(name="Taxa de Conversão", value=f"1 🪙 = {taxa_conversao:,} 🥈", inline=False)
    embed.add_field(name="Suprimento Máximo de Moedas", value=f"{suprimento_maximo:,} 🪙", inline=True)
    embed.add_field(name="Moedas no Tesouro", value=f"{saldo_tesouro:,} 🪙", inline=True)
    embed.add_field(name="Moedas em Circulação (com membros)", value=f"{moedas_com_membros:,} 🪙", inline=True)
    await ctx.send(embed=embed)

@bot.command(name='resgatar')
async def redeem(ctx, quantidade: int):
    """Troca as suas moedas por prata do lastro da guilda."""
    if quantidade <= 0: return await ctx.send("A quantidade deve ser um valor positivo.")
    get_account(ctx.author.id)
    taxa_conversao = int(get_config_value('lastro_prata', '1000'))
    
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT saldo FROM banco WHERE user_id = %s FOR UPDATE", (ctx.author.id,))
            saldo_membro = cursor.fetchone()[0]
            if saldo_membro < quantidade:
                return await ctx.send("Você não tem moedas suficientes para resgatar.")
            
            # Move as moedas do membro para o tesouro
            cursor.execute("UPDATE banco SET saldo = saldo - %s WHERE user_id = %s", (quantidade, ctx.author.id))
            cursor.execute("UPDATE banco SET saldo = saldo + %s WHERE user_id = %s", (quantidade, ID_TESOURO_GUILDA))
            conn.commit()

    prata_a_receber = quantidade * taxa_conversao
    registrar_transacao(ctx.author.id, "Resgate de Prata", -quantidade, f"Resgatou {prata_a_receber:,} de prata.")
    
    await ctx.send(f"✅ Resgate processado! Você trocou **{quantidade:,}** 🪙 por **{prata_a_receber:,}** 🥈.")
    
    canal_staff = discord.utils.get(ctx.guild.channels, name='🚨-staff-resgates')
    if canal_staff:
        await canal_staff.send(f"⚠️ **Pedido de Resgate!** O membro {ctx.author.mention} resgatou **{prata_a_receber:,}** de prata. Por favor, realize a entrega no jogo.")

# (Resto dos comandos como transferir, loja, eventos, etc., permanecem iguais)
# --- Comandos de Administração ---
@bot.command(name='ajustarlastro')
@commands.has_permissions(administrator=True)
async def adjust_backing(ctx, novo_total_prata: int):
    """Ajusta o valor total do lastro de prata e emite/recolhe moedas do tesouro."""
    if novo_total_prata < 0: return await ctx.send("O valor do lastro não pode ser negativo.")
    
    taxa_conversao = int(get_config_value('lastro_prata', '1000'))
    lastro_antigo = int(get_config_value('lastro_total_prata', '0'))

    suprimento_antigo = lastro_antigo // taxa_conversao if taxa_conversao > 0 else 0
    suprimento_novo = novo_total_prata // taxa_conversao if taxa_conversao > 0 else 0
    
    diferenca = suprimento_novo - suprimento_antigo
    
    set_config_value('lastro_total_prata', str(novo_total_prata))
    
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE banco SET saldo = saldo + %s WHERE user_id = %s", (diferenca, ID_TESOURO_GUILDA))
            conn.commit()
            
    if diferenca > 0:
        await ctx.send(f"✅ Lastro atualizado para **{novo_total_prata:,}** 🥈. Foram emitidas e adicionadas ao tesouro **{diferenca:,}** 🪙 moedas.")
    elif diferenca < 0:
        await ctx.send(f"✅ Lastro atualizado para **{novo_total_prata:,}** 🥈. Foram recolhidas do tesouro **{-diferenca:,}** 🪙 moedas.")
    else:
        await ctx.send(f"✅ Lastro atualizado para **{novo_total_prata:,}** 🥈. O suprimento de moedas não foi alterado.")

@bot.command(name='emitir')
@commands.has_permissions(administrator=True)
async def issue(ctx, membro: discord.Member, quantidade: int, *, razao: str):
    """Emite moedas do tesouro da guilda para um membro."""
    if quantidade <= 0: return await ctx.send("A quantidade deve ser um valor positivo.")
    get_account(membro.id)

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT saldo FROM banco WHERE user_id = %s FOR UPDATE", (ID_TESOURO_GUILDA,))
            saldo_tesouro = cursor.fetchone()[0]

            if saldo_tesouro < quantidade:
                return await ctx.send(f"❌ O tesouro não tem fundos suficientes! Faltam **{quantidade - saldo_tesouro:,}** 🪙. Aumente o lastro com `!ajustarlastro`.")
            
            # Transfere do tesouro para o membro
            cursor.execute("UPDATE banco SET saldo = saldo - %s WHERE user_id = %s", (quantidade, ID_TESOURO_GUILDA))
            cursor.execute("UPDATE banco SET saldo = saldo + %s WHERE user_id = %s RETURNING saldo", (quantidade, membro.id))
            novo_saldo = cursor.fetchone()[0]
            conn.commit()

    registrar_transacao(membro.id, "Emissão de Moedas", quantidade, f"Emitido por {ctx.author.display_name}: {razao}")
    await ctx.send(f"✅ **{quantidade:,}** 🪙 moedas foram emitidas para {membro.mention}. Novo saldo: **{novo_saldo:,}**.")

# (Resto dos comandos de admin permanecem iguais, exceto !addmoedas que foi removido)
# =================================================================================
# 6. INICIAR O BOT
# =================================================================================
if TOKEN and DATABASE_URL:
    bot.run(TOKEN)
else:
    print("ERRO: Token do Discord ou URL da Base de Dados não encontrados. Verifique as variáveis de ambiente.")

