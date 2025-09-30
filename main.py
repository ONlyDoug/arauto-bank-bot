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
                'canal_aprovacao': '0', 'canal_mercado': '0'
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
        await ctx.send("Você não tem permissão para usar este comando.", ephemeral=True)
        return False
    return commands.check(predicate)

@bot.event
async def on_ready():
    if not DATABASE_URL: print("ERRO CRÍTICO: DATABASE_URL não definida."); return
    initialize_connection_pool()
    setup_database()
    market_update.start() # Inicia a nova tarefa de mercado
    print(f'Login bem-sucedido como {bot.user.name}'); print('------')

# =================================================================================
# 4. TAREFAS DE ENGAJAMENTO
# =================================================================================

@tasks.loop(hours=6)
async def market_update():
    """Envia uma atualização periódica sobre a saúde da economia."""
    await bot.wait_until_ready()
    channel_id = int(get_config_value('canal_mercado', '0'))
    if channel_id == 0 or (channel := bot.get_channel(channel_id)) is None:
        return

    # Reutiliza a lógica do comando !infomoeda
    taxa_conversao = int(get_config_value('lastro_prata', '1000'))
    lastro_total = int(get_config_value('lastro_total_prata', '0'))
    suprimento_maximo = lastro_total // taxa_conversao if taxa_conversao > 0 else 0
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT saldo FROM banco WHERE user_id = %s", (ID_TESOURO_GUILDA,))
            saldo_tesouro = cursor.fetchone()[0]
    
    moedas_com_membros = suprimento_maximo - saldo_tesouro

    embed = discord.Embed(title="📈 Boletim Económico do Arauto Bank", 
                          description=f"Atualização de mercado de {datetime.now().strftime('%d/%m/%Y às %H:%M')}",
                          color=discord.Color.from_rgb(255, 215, 0)) # Dourado
    embed.add_field(name="Lastro Total de Prata", value=f"**{lastro_total:,}** 🥈", inline=True)
    embed.add_field(name="Taxa de Câmbio", value=f"**1 🪙 = {taxa_conversao:,}** 🥈", inline=True)
    embed.add_field(name="Suprimento Máximo", value=f"**{suprimento_maximo:,}** 🪙", inline=True)
    embed.set_footer(text="Use !infomoeda para mais detalhes a qualquer momento.")
    
    await channel.send(embed=embed)


# =================================================================================
# 5. COMANDOS DO BOT
# =================================================================================

# --- COMANDO !SETUP v2.3 (ESTRUTURA ENXUTA) ---
@bot.command(name='setup')
@commands.has_permissions(administrator=True)
async def setup_server(ctx):
    """Apaga a estrutura antiga e cria uma nova estrutura de canais otimizada."""
    guild = ctx.guild
    await ctx.send("⚠️ **AVISO:** Este comando irá apagar e recriar as categorias do Arauto Bank. A ação é irreversível.\nDigite `confirmar wipe` para prosseguir.")
    
    def check(m): return m.author == ctx.author and m.channel == ctx.channel and m.content.lower() == 'confirmar wipe'
    
    try: await bot.wait_for('message', timeout=30.0, check=check)
    except asyncio.TimeoutError: return await ctx.send("Comando cancelado.")

    await ctx.send("🔥 Confirmado! A iniciar a reconstrução... Isto pode demorar um pouco.")

    # --- Apaga a estrutura antiga ---
    category_names_to_delete = ["🏦 ARAUTO BANK", "💸 TAXA SEMANAL"]
    for cat_name in category_names_to_delete:
        if category := discord.utils.get(guild.categories, name=cat_name):
            for channel in category.channels: await channel.delete()
            await category.delete()
    
    # --- Cria a nova estrutura ---
    perm_nivel_4_id = int(get_config_value('perm_nivel_4', '0'))
    perm_nivel_4_role = guild.get_role(perm_nivel_4_id)
    admin_overwrites = { guild.default_role: discord.PermissionOverwrite(view_channel=False) }
    if perm_nivel_4_role: admin_overwrites[perm_nivel_4_role] = discord.PermissionOverwrite(view_channel=True)

    # 1. Categoria Principal: ARAUTO BANK
    cat_principal = await guild.create_category("🏦 ARAUTO BANK")
    
    # Canais Públicos dentro da Categoria Principal
    ch_tutorial = await cat_principal.create_text_channel("🎓 | como-usar-o-bot", overwrites={guild.default_role: discord.PermissionOverwrite(send_messages=False)})
    # (Mensagem do tutorial)
    embed_tutorial = discord.Embed(title="Bem-vindo ao Arauto Bank!", description="O sistema económico da nossa guilda, para recompensar a sua participação.", color=0xffd700)
    embed_tutorial.add_field(name="O que é a Moeda Arauto (🪙)?", value="É a nossa moeda interna! Você ganha-a ao participar em atividades e pode trocá-la por itens na `!loja`.", inline=False)
    embed_tutorial.add_field(name="Comandos Essenciais", value=("• `!saldo`\n• `!extrato`\n• `!loja`\n• `!rank`\n• `!listareventos`"), inline=False)
    msg_tutorial = await ch_tutorial.send(embed=embed_tutorial); await msg_tutorial.pin()

    ch_mercado = await cat_principal.create_text_channel("📈 | mercado-financeiro", overwrites={guild.default_role: discord.PermissionOverwrite(send_messages=False)})
    embed_mercado = discord.Embed(title="A Nossa Moeda: O Lastro em Prata", description="A Moeda Arauto (🪙) não é apenas um número, ela tem um valor real e tangível.", color=0x1abc9c)
    embed_mercado.add_field(name="O que é o Lastro?", value="Significa que para cada moeda em circulação, existe uma quantidade correspondente de Prata (🥈) guardada no tesouro da guilda. Isto garante que a moeda nunca perde o seu valor.", inline=False)
    embed_mercado.add_field(name="Porque isto é bom para si?", value="Ter moedas é como ter uma parte do tesouro da guilda. Quanto mais a guilda prospera, mais valiosa a sua participação se torna. Use `!infomoeda` para ver os detalhes!", inline=False)
    msg_mercado = await ch_mercado.send(embed=embed_mercado); await msg_mercado.pin()
    set_config_value('canal_mercado', str(ch_mercado.id))

    await cat_principal.create_text_channel("💰 | saldo-e-extrato")
    await cat_principal.create_text_channel("🛍️ | loja")
    await cat_principal.create_text_channel("🏆 | eventos-ativos")

    # Canais de Administração (Privados) dentro da Categoria Principal
    ch_aprovacao = await cat_principal.create_text_channel("✅ | aprovações", overwrites=admin_overwrites)
    set_config_value('canal_aprovacao', str(ch_aprovacao.id))
    ch_comandos = await cat_principal.create_text_channel("🔩 | comandos-admin", overwrites=admin_overwrites)

    # 2. Categoria de Taxas
    cat_taxas = await guild.create_category("💸 TAXA SEMANAL")
    # (Criação dos canais de taxas inalterada)
    ch_info_taxa = await cat_taxas.create_text_channel("ℹ️ | como-funciona-a-taxa", overwrites={guild.default_role: discord.PermissionOverwrite(send_messages=False)})
    embed_info_taxa = discord.Embed(title="Como Funciona o Sistema de Taxa Semanal", description="Um sistema para garantir a manutenção e o crescimento da nossa guilda.", color=0x7f8c8d)
    embed_info_taxa.add_field(name="1. Cobrança Automática", value="Toda semana, o bot irá debitar a taxa do seu `!saldo`.", inline=False)
    embed_info_taxa.add_field(name="2. Como Regularizar?", value=("• **Com Moedas:** Use `!pagar-taxa` no canal `🪙 | pagamento-taxas`.\n"
                                                               "• **Com Prata:** Use `!paguei-prata` no mesmo canal e aguarde aprovação."), inline=False)
    msg_info_taxa = await ch_info_taxa.send(embed=embed_info_taxa); await msg_info_taxa.pin()
    await cat_taxas.create_text_channel("🪙 | pagamento-taxas")

    await ctx.send("✅ Estrutura de canais v3.0 criada e configurada com sucesso!")


# (Todos os outros comandos permanecem exatamente iguais e são omitidos por brevidade)

# =================================================================================
# 6. INICIAR O BOT
# =================================================================================
if TOKEN and DATABASE_URL:
    bot.run(TOKEN)
else:
    print("ERRO: Variáveis de ambiente essenciais não encontradas.")

