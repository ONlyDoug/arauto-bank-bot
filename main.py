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

            default_configs = {
                'lastro_total_prata': '0', 'lastro_prata': '1000',
                'recompensa_tier_bronze': '50', 'recompensa_tier_prata': '100', 'recompensa_tier_ouro': '200',
                'orbe_verde': '100', 'orbe_azul': '250', 'orbe_roxa': '500', 'orbe_dourada': '1000',
                'taxa_semanal_valor': '500', 'cargo_membro': '0', 'cargo_inadimplente': '0', 'cargo_isento': '0',
                'perm_nivel_1': '0', 'perm_nivel_2': '0', 'perm_nivel_3': '0', 'perm_nivel_4': '0',
                'canal_aprovacao': '0', 'canal_mercado': '0', 'canal_orbes': '0'
            }
            for chave, valor in default_configs.items():
                cursor.execute("INSERT INTO configuracoes (chave, valor) VALUES (%s, %s) ON CONFLICT (chave) DO NOTHING", (chave, valor))
            
            cursor.execute("INSERT INTO banco (user_id, saldo) VALUES (%s, 0) ON CONFLICT (user_id) DO NOTHING", (ID_TESOURO_GUILDA,))
        conn.commit()
    print("Base de dados Supabase verificada e pronta.")

# (Funções auxiliares de BD)
def get_config_value(chave: str, default: str = None):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT valor FROM configuracoes WHERE chave = %s", (chave,)); resultado = cursor.fetchone()
    return resultado[0] if resultado else default

def set_config_value(chave: str, valor: str):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("INSERT INTO configuracoes (chave, valor) VALUES (%s, %s) ON CONFLICT (chave) DO UPDATE SET valor = EXCLUDED.valor", (chave, valor)); conn.commit()
# (Resto das funções auxiliares de BD)
# ...

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
    # (Tarefas em background)
    print(f'Login bem-sucedido como {bot.user.name}'); print('------')

# =================================================================================
# 5. COMANDOS DO BOT
# =================================================================================

# --- COMANDO !SETUP v3.1 (ESTRUTURA FINAL) ---
@bot.command(name='setup')
@commands.has_permissions(administrator=True)
async def setup_server(ctx):
    """Apaga a estrutura antiga e cria a estrutura de canais final para o bot."""
    guild = ctx.guild
    await ctx.send("⚠️ **AVISO:** Este comando irá apagar e recriar as categorias do Arauto Bank. A ação é irreversível.\nDigite `confirmar wipe` para prosseguir.")
    
    def check(m): return m.author == ctx.author and m.channel == ctx.channel and m.content.lower() == 'confirmar wipe'
    
    try: await bot.wait_for('message', timeout=30.0, check=check)
    except asyncio.TimeoutError: return await ctx.send("Comando cancelado.")

    msg_progresso = await ctx.send("🔥 Confirmado! A iniciar a reconstrução... (0/3)")

    # --- Apaga a estrutura antiga ---
    category_names_to_delete = ["🏦 ARAUTO BANK", "💸 TAXA SEMANAL", "⚙️ ADMINISTRAÇÃO"]
    for cat_name in category_names_to_delete:
        if category := discord.utils.get(guild.categories, name=cat_name):
            for channel in category.channels: await channel.delete()
            await category.delete()
    
    await msg_progresso.edit(content="🔥 A iniciar a reconstrução... (1/3)")

    # --- Lógica de Permissões ---
    perm_nivel_4_id = int(get_config_value('perm_nivel_4', '0'))
    perm_nivel_4_role = guild.get_role(perm_nivel_4_id)
    admin_overwrites = { 
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        guild.me: discord.PermissionOverwrite(view_channel=True)
    }
    if perm_nivel_4_role: admin_overwrites[perm_nivel_4_role] = discord.PermissionOverwrite(view_channel=True)

    # --- Função Auxiliar para Criar e Fixar ---
    async def create_and_pin(category, name, embed, overwrites=None):
        try:
            channel = await category.create_text_channel(name, overwrites=overwrites)
            msg = await channel.send(embed=embed)
            await msg.pin()
            return channel
        except discord.Forbidden:
            await ctx.send(f"❌ Erro de permissão ao criar ou fixar mensagem no canal `{name}`.")
            return None
        except Exception as e:
            await ctx.send(f"⚠️ Ocorreu um erro inesperado ao criar o canal `{name}`: {e}")
            return None

    # 1. Categoria Principal: ARAUTO BANK
    cat_principal = await guild.create_category("🏦 ARAUTO BANK")
    
    # Canais Públicos
    embed_tutorial = discord.Embed(title="🎓 Como Usar o Arauto Bank", description="Bem-vindo ao sistema económico da guilda!", color=0xffd700)
    embed_tutorial.add_field(name="Comandos Essenciais", value=("• `!saldo`\n• `!extrato`\n• `!loja`\n• `!rank`\n• `!listareventos`"), inline=False)
    await create_and_pin(cat_principal, "🎓 | como-usar-o-bot", embed_tutorial, {guild.default_role: discord.PermissionOverwrite(send_messages=False)})

    embed_mercado = discord.Embed(title="📈 Mercado Financeiro", description="A nossa moeda é lastreada em Prata. Entenda o seu valor.", color=0x1abc9c)
    embed_mercado.add_field(name="O que é o Lastro?", value="Significa que para cada moeda, existe Prata (🥈) guardada no tesouro. Use `!infomoeda` para ver os detalhes!", inline=False)
    ch_mercado = await create_and_pin(cat_principal, "📈 | mercado-financeiro", embed_mercado, {guild.default_role: discord.PermissionOverwrite(send_messages=False)})
    if ch_mercado: set_config_value('canal_mercado', str(ch_mercado.id))

    embed_conta = discord.Embed(title="💰 Minha Conta", description="Use os comandos `!saldo` e `!extrato` para gerir as suas finanças.", color=0x2ecc71)
    await create_and_pin(cat_principal, "💰 | minha-conta", embed_conta)

    embed_loja = discord.Embed(title="🛍️ Loja da Guilda", description="Use `!loja` para ver os itens e `!comprar <id>` para adquirir.", color=0x3498db)
    await create_and_pin(cat_principal, "🛍️ | loja-da-guilda", embed_loja)
    
    embed_eventos = discord.Embed(title="🏆 Eventos e Missões", description="Use `!listareventos` para ver as missões ativas e `!participar <id>` para se inscrever.", color=0xe91e63)
    await create_and_pin(cat_principal, "🏆 | eventos-e-missões", embed_eventos)

    embed_orbes = discord.Embed(title="🔮 Submissão de Orbes", description="Use `!orbe <cor> <@membros...>` e anexe o print para ganhar recompensas.", color=0x9b59b6)
    ch_orbes = await create_and_pin(cat_principal, "🔮 | submeter-orbes", embed_orbes)
    if ch_orbes: set_config_value('canal_orbes', str(ch_orbes.id))
    await msg_progresso.edit(content="🔥 A iniciar a reconstrução... (2/3)")
    
    # 2. Categoria de Taxas
    cat_taxas = await guild.create_category("💸 TAXA SEMANAL")
    embed_info_taxa = discord.Embed(title="ℹ️ Como Funciona a Taxa", description="Um sistema para garantir a manutenção e o crescimento da nossa guilda.", color=0x7f8c8d)
    embed_info_taxa.add_field(name="Como Regularizar?", value=("Use `!pagar-taxa` ou `!paguei-prata` no canal `🪙 | pagamento-de-taxas`."), inline=False)
    await create_and_pin(cat_taxas, "ℹ️ | como-funciona-a-taxa", embed_info_taxa, {guild.default_role: discord.PermissionOverwrite(send_messages=False)})
    
    embed_pagamento = discord.Embed(title="🪙 Pagamento de Taxas", description="Se o seu acesso for restrito, use `!pagar-taxa` ou `!paguei-prata` aqui.", color=0x95a5a6)
    await create_and_pin(cat_taxas, "🪙 | pagamento-de-taxas", embed_pagamento)

    # 3. Categoria de Administração (MOVENDO CANAIS PARA CÁ)
    cat_admin = await guild.create_category("⚙️ ADMINISTRAÇÃO", overwrites=admin_overwrites)
    embed_aprovacao = discord.Embed(title="✅ Aprovações", description="Aqui aparecerão as submissões de orbes e pagamentos de taxa.", color=0xf1c40f)
    ch_aprovacao = await create_and_pin(cat_admin, "✅ | aprovações", embed_aprovacao)
    if ch_aprovacao: set_config_value('canal_aprovacao', str(ch_aprovacao.id))
    
    embed_comandos = discord.Embed(title="🔩 Comandos Admin", description="Use este canal para todos os comandos de gestão.", color=0xe67e22)
    await create_and_pin(cat_admin, "🔩 | comandos-admin", embed_comandos)
    
    await msg_progresso.edit(content="✅ Estrutura de canais final criada e configurada com sucesso!")

# (Todos os outros comandos permanecem exatamente iguais e são omitidos por brevidade)

# =================================================================================
# 6. INICIAR O BOT
# =================================================================================
if TOKEN and DATABASE_URL:
    bot.run(TOKEN)
else:
    print("ERRO: Variáveis de ambiente essenciais não encontradas.")

