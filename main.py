# =================================================================================
# 1. IMPORTAÇÕES E CONFIGURAÇÃO INICIAL
# =================================================================================
import discord
from discord.ext import commands, tasks
import psycopg2
import psycopg2.extras
import os
from dotenv import load_dotenv
from datetime import datetime, date
import time

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

# Variáveis de controlo em memória
user_message_cooldowns = {}

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
    """Inicializa a base de dados, criando todas as tabelas se não existirem."""
    conn = get_db_connection()
    if conn is None: return

    with conn.cursor() as cursor:
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
            'lastro_prata': '1000', 'recompensa_voz': '10', 'recompensa_chat': '1', 'recompensa_reacao': '50',
            'limite_diario_voz': '120', 'limite_diario_chat': '100', 'cooldown_chat': '60', 'canal_anuncios': '0',
            'cargos_gerente_eventos': ''
        }
        for chave, valor in default_configs.items():
            cursor.execute("INSERT INTO configuracoes (chave, valor) VALUES (%s, %s) ON CONFLICT (chave) DO NOTHING", (chave, valor))
    
    conn.commit()
    conn.close()
    print("Base de dados Supabase verificada e pronta (com sistema de economia completo).")

def get_config_value(chave: str, default: str = None):
    conn = get_db_connection()
    if conn is None: return default
    with conn.cursor() as cursor:
        cursor.execute("SELECT valor FROM configuracoes WHERE chave = %s", (chave,))
        resultado = cursor.fetchone()
    conn.close()
    return resultado[0] if resultado else default

def set_config_value(chave: str, valor: str):
    conn = get_db_connection()
    if conn is None: return
    with conn.cursor() as cursor:
        cursor.execute("INSERT INTO configuracoes (chave, valor) VALUES (%s, %s) ON CONFLICT (chave) DO UPDATE SET valor = EXCLUDED.valor", (chave, valor))
        conn.commit()
    conn.close()

def get_account(user_id: int):
    conn = get_db_connection()
    if conn is None: return
    with conn.cursor() as cursor:
        cursor.execute("SELECT 1 FROM banco WHERE user_id = %s", (user_id,))
        if cursor.fetchone() is None:
            cursor.execute("INSERT INTO banco (user_id, saldo) VALUES (%s, 0) ON CONFLICT (user_id) DO NOTHING", (user_id,))
            conn.commit()
    conn.close()

def registrar_transacao(user_id: int, tipo: str, valor: int, descricao: str):
    conn = get_db_connection()
    if conn is None: return
    with conn.cursor() as cursor:
        cursor.execute("INSERT INTO transacoes (user_id, tipo, valor, descricao) VALUES (%s, %s, %s, %s)", (user_id, tipo, valor, descricao))
        conn.commit()
    conn.close()
    
def get_or_create_daily_activity(user_id: int, target_date: date):
    """Obtém ou cria o registo de atividade para um utilizador numa data específica."""
    conn = get_db_connection()
    if conn is None: return None
    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
        cursor.execute("SELECT * FROM atividade_diaria WHERE user_id = %s AND data = %s", (user_id, target_date))
        activity = cursor.fetchone()
        if activity is None:
            cursor.execute("INSERT INTO atividade_diaria (user_id, data) VALUES (%s, %s) ON CONFLICT (user_id, data) DO NOTHING", (user_id, target_date))
            conn.commit()
            cursor.execute("SELECT * FROM atividade_diaria WHERE user_id = %s AND data = %s", (user_id, target_date))
            activity = cursor.fetchone()
    conn.close()
    return activity

# =================================================================================
# 3. VERIFICAÇÕES DE PERMISSÃO PERSONALIZADAS
# =================================================================================

def can_manage_events():
    """Verificação para ver se o autor é Admin OU tem um dos cargos de Gerente de Eventos."""
    async def predicate(ctx):
        if ctx.author.guild_permissions.administrator: return True
        roles_id_str = get_config_value('cargos_gerente_eventos', '');
        if not roles_id_str: return False
        allowed_role_ids = {int(id_str) for id_str in roles_id_str.split(',') if id_str}
        author_role_ids = {role.id for role in ctx.author.roles}
        if not allowed_role_ids.isdisjoint(author_role_ids): return True
        return False
    return commands.check(predicate)

# =================================================================================
# 4. TAREFAS EM BACKGROUND E EVENTOS DO BOT
# =================================================================================

@tasks.loop(minutes=5)
async def voice_channel_rewards():
    """Tarefa que corre em background para dar moedas por tempo em call."""
    await bot.wait_until_ready()
    recompensa_por_hora = int(get_config_value('recompensa_voz', '10'))
    limite_minutos_diario = int(get_config_value('limite_diario_voz', '120'))
    recompensa_por_ciclo = (recompensa_por_hora / 60) * 5
    for guild in bot.guilds:
        for member in guild.members:
            if member.voice and not member.voice.self_mute and not member.voice.self_deaf:
                get_account(member.id)
                activity = get_or_create_daily_activity(member.id, date.today())
                if activity and activity['minutos_voz'] < limite_minutos_diario:
                    conn = get_db_connection()
                    if conn is None: continue
                    with conn.cursor() as cursor:
                        cursor.execute("UPDATE banco SET saldo = saldo + %s WHERE user_id = %s", (recompensa_por_ciclo, member.id))
                        cursor.execute("UPDATE atividade_diaria SET minutos_voz = minutos_voz + 5 WHERE user_id = %s AND data = %s", (member.id, date.today()))
                        conn.commit()
                    conn.close()
                    # A transação não é mais registada individualmente

@bot.event
async def on_ready():
    if not DATABASE_URL: print("ERRO CRÍTICO: A variável de ambiente DATABASE_URL não foi definida."); return
    setup_database()
    voice_channel_rewards.start()
    print(f'Login bem-sucedido como {bot.user.name}')
    print(f'O Arauto Bank está online e pronto para operar!'); print('------')

@bot.event
async def on_message(message):
    if message.author.bot or message.content.startswith('!'): await bot.process_commands(message); return
    user_id = message.author.id
    current_time = time.time()
    cooldown_seconds = int(get_config_value('cooldown_chat', '60'))
    if user_id in user_message_cooldowns and current_time - user_message_cooldowns[user_id] < cooldown_seconds:
        await bot.process_commands(message); return
    get_account(user_id)
    activity = get_or_create_daily_activity(user_id, date.today())
    limite_diario = int(get_config_value('limite_diario_chat', '100'))
    recompensa = int(get_config_value('recompensa_chat', '1'))
    if activity and activity['moedas_chat'] < limite_diario:
        conn = get_db_connection()
        if conn is None: await bot.process_commands(message); return
        with conn.cursor() as cursor:
            cursor.execute("UPDATE banco SET saldo = saldo + %s WHERE user_id = %s", (recompensa, user_id))
            cursor.execute("UPDATE atividade_diaria SET moedas_chat = moedas_chat + %s WHERE user_id = %s AND data = %s", (recompensa, user_id, date.today()))
            conn.commit()
        conn.close()
        # A transação não é mais registada individualmente
        user_message_cooldowns[user_id] = current_time
    await bot.process_commands(message)

@bot.event
async def on_raw_reaction_add(payload):
    if payload.member.bot: return
    canal_anuncios_id = int(get_config_value('canal_anuncios', '0'))
    if payload.channel_id != canal_anuncios_id: return
    user_id = payload.user_id; message_id = payload.message_id
    recompensa = int(get_config_value('recompensa_reacao', '50'))
    conn = get_db_connection()
    if conn is None: return
    with conn.cursor() as cursor:
        try:
            cursor.execute("INSERT INTO reacoes_recompensadas (message_id, user_id) VALUES (%s, %s)", (message_id, user_id)); conn.commit()
            get_account(user_id)
            cursor.execute("UPDATE banco SET saldo = saldo + %s WHERE user_id = %s", (recompensa, user_id)); conn.commit()
            registrar_transacao(user_id, "Recompensa", recompensa, f"Leitura do anúncio {message_id}")
        except psycopg2.IntegrityError: conn.rollback()
    conn.close()

@bot.event
async def on_member_join(member):
    get_account(member.id)
    registrar_transacao(member.id, "Criação de Conta", 0, "Conta criada ao entrar no servidor.")
    print(f'Conta bancária criada para o novo membro: {member.name}')
    
# =================================================================================
# 5. COMANDOS DO BOT
# =================================================================================

# --- Comandos Gerais ---
@bot.command(name='ola')
async def hello(ctx): await ctx.send(f'Olá, {ctx.author.mention}! Eu sou o Arauto Bank, pronto para servir.')

# --- Comandos de Economia e Lastro ---
@bot.command(name='saldo')
async def balance(ctx):
    get_account(ctx.author.id); conn = get_db_connection()
    if conn is None: return await ctx.send("Erro de conexão com a base de dados.")
    with conn.cursor() as cursor:
        cursor.execute("SELECT saldo FROM banco WHERE user_id = %s", (ctx.author.id,)); saldo = cursor.fetchone()[0]
    conn.close()
    embed = discord.Embed(title=f"Saldo de {ctx.author.display_name}", description=f"Você possui **🪙 {saldo}** moedas.", color=discord.Color.gold())
    await ctx.send(embed=embed)

@bot.command(name='transferir')
async def transfer(ctx, destinatario: discord.Member, quantidade: int):
    # (Código inalterado - já regista transação)
    remetente_id = ctx.author.id; destinatario_id = destinatario.id
    if remetente_id == destinatario_id: return await ctx.send("Você não pode transferir para si mesmo.")
    if quantidade <= 0: return await ctx.send("A quantidade deve ser positiva.")
    get_account(remetente_id); get_account(destinatario_id); conn = get_db_connection();
    if conn is None: return await ctx.send("Erro de conexão com a base de dados.")
    with conn.cursor() as cursor:
        cursor.execute("SELECT saldo FROM banco WHERE user_id = %s", (remetente_id,)); saldo_remetente = cursor.fetchone()[0]
        if saldo_remetente < quantidade: return await ctx.send("Saldo insuficiente.")
        cursor.execute("UPDATE banco SET saldo = saldo - %s WHERE user_id = %s", (quantidade, remetente_id))
        cursor.execute("UPDATE banco SET saldo = saldo + %s WHERE user_id = %s", (quantidade, destinatario_id)); conn.commit()
    registrar_transacao(remetente_id, "Transferência Enviada", -quantidade, f"Para {destinatario.display_name}")
    registrar_transacao(destinatario_id, "Transferência Recebida", quantidade, f"De {ctx.author.display_name}"); conn.close()
    embed = discord.Embed(title="💸 Transferência Realizada", description=f"**{ctx.author.display_name}** transferiu **🪙 {quantidade}** para **{destinatario.display_name}**.", color=discord.Color.green())
    await ctx.send(embed=embed)

# --- COMANDO DE EXTRATO ATUALIZADO ---
@bot.command(name='extrato')
async def statement(ctx, data_str: str = None):
    """Mostra o resumo de ganhos e as principais transações de um dia."""
    user_id = ctx.author.id
    target_date = date.today()

    if data_str:
        try:
            target_date = datetime.strptime(data_str, '%d/%m/%Y').date()
        except ValueError:
            return await ctx.send("Formato de data inválido. Use `DD/MM/AAAA`.")

    get_account(user_id)
    conn = get_db_connection()
    if conn is None: return await ctx.send("Erro de conexão com a base de dados.")

    # Busca o resumo de atividade diária
    activity = get_or_create_daily_activity(user_id, target_date)
    recompensa_voz_hora = int(get_config_value('recompensa_voz', '10'))
    total_ganho_voz = (activity['minutos_voz'] / 60) * recompensa_voz_hora
    total_ganho_chat = activity['moedas_chat']

    # Busca as transações importantes do dia
    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
        cursor.execute("""
            SELECT tipo, valor, descricao, data FROM transacoes 
            WHERE user_id = %s AND DATE(data) = %s 
            AND tipo NOT IN ('Renda Passiva')
            ORDER BY data DESC
        """, (user_id, target_date))
        transacoes = cursor.fetchall()
    conn.close()

    embed = discord.Embed(title=f"Extrato de {ctx.author.display_name} - {target_date.strftime('%d/%m/%Y')}", color=discord.Color.blue())
    
    # Adiciona o resumo de renda diária
    resumo_renda = (
        f"**Voz:** 🗣️ +{int(total_ganho_voz)} moedas ({activity['minutos_voz']} minutos)\n"
        f"**Chat:** 💬 +{total_ganho_chat} moedas"
    )
    embed.add_field(name="Resumo de Renda Diária", value=resumo_renda, inline=False)
    
    # Adiciona as outras transações
    if not transacoes:
        embed.add_field(name="Outras Transações", value="Nenhuma outra transação neste dia.", inline=False)
    else:
        for t in transacoes:
            valor_str = f"+{t['valor']}" if t['valor'] > 0 else str(t['valor'])
            cor_valor = "🟢" if t['valor'] > 0 else ("🔴" if t['valor'] < 0 else "⚪")
            data_formatada = t['data'].strftime('%H:%M')
            embed.add_field(
                name=f"**{t['tipo']}** - {data_formatada}",
                value=f"{cor_valor} **Valor:** {valor_str} moedas\n*_{t['descricao']}_*",
                inline=False
            )
            
    await ctx.send(embed=embed)


# (Resto dos comandos como lastro, loja, comprar, eventos e admin permanecem iguais e são omitidos por brevidade)
@bot.command(name='lastro')
async def silver_value(ctx):
    # ... código ...
    get_account(ctx.author.id); conn = get_db_connection()
    if conn is None: return await ctx.send("Erro de conexão com a base de dados.")
    lastro_prata_str = get_config_value('lastro_prata', '1000'); lastro_prata = int(lastro_prata_str)
    with conn.cursor() as cursor:
        cursor.execute("SELECT saldo FROM banco WHERE user_id = %s", (ctx.author.id,)); saldo = cursor.fetchone()[0]
    conn.close()
    patrimonio_em_prata = saldo * lastro_prata
    embed = discord.Embed(title="🏦 Valor de Lastro em Prata", color=discord.Color.light_grey())
    embed.add_field(name="Taxa de Conversão Atual", value=f"**1** 🪙 moeda do bot = **{lastro_prata:,}** de prata.", inline=False)
    embed.add_field(name=f"Patrimônio de {ctx.author.display_name}", value=f"O seu saldo de **{saldo:,}** 🪙 moedas equivale a **{patrimonio_em_prata:,}** de prata.", inline=False)
    await ctx.send(embed=embed)

@bot.command(name='loja')
async def shop(ctx):
    # ... código ...
    conn = get_db_connection();
    if conn is None: return await ctx.send("Erro de conexão com a base de dados.")
    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
        cursor.execute("SELECT item_id, nome, preco, descricao FROM loja ORDER BY preco ASC"); itens = cursor.fetchall()
    conn.close()
    if not itens: return await ctx.send("A loja está vazia no momento.")
    embed = discord.Embed(title="🎁 Loja de Recompensas do Arauto Bank", color=discord.Color.purple())
    for item in itens: embed.add_field(name=f"**{item['nome']}** (ID: {item['item_id']})", value=f"**Preço:** 🪙 {item['preco']}\n*_{item['descricao']}_*", inline=False)
    await ctx.send(embed=embed)

@bot.command(name='comprar')
async def buy(ctx, item_id: str):
    # ... código ...
    comprador_id = ctx.author.id; get_account(comprador_id); conn = get_db_connection();
    if conn is None: return await ctx.send("Erro de conexão com a base de dados.")
    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
        cursor.execute("SELECT nome, preco FROM loja WHERE item_id = %s", (item_id,)); item = cursor.fetchone()
        if item is None: return await ctx.send(f"O item com ID `{item_id}` não foi encontrado.")
        cursor.execute("SELECT saldo FROM banco WHERE user_id = %s", (comprador_id,)); saldo_comprador = cursor.fetchone()['saldo']
        if saldo_comprador < item['preco']: return await ctx.send(f"Saldo insuficiente! Faltam **🪙 {item['preco'] - saldo_comprador}** moedas.")
        cursor.execute("UPDATE banco SET saldo = saldo - %s WHERE user_id = %s", (item['preco'], comprador_id)); conn.commit()
        registrar_transacao(comprador_id, "Compra na Loja", -item['preco'], f"Comprou o item '{item['nome']}'")
    conn.close()
    await ctx.send(f"🎉 Parabéns, {ctx.author.mention}! Você comprou **{item['nome']}** por **🪙 {item['preco']}** moedas.")
    canal_staff = discord.utils.get(ctx.guild.channels, name='🚨-staff-resgates')
    if canal_staff: await canal_staff.send(f"⚠️ **Novo Resgate!** {ctx.author.mention} comprou **'{item['nome']}'** (ID: {item_id}).")

@bot.command(name='criarevento')
@can_manage_events()
async def create_event(ctx, recompensa: int, meta: int, *, nome: str):
    # ... código ...
    if recompensa <= 0 or meta <= 0: return await ctx.send("A recompensa e a meta devem ser valores positivos.")
    conn = get_db_connection();
    if conn is None: return await ctx.send("Erro de conexão com a base de dados.")
    with conn.cursor() as cursor:
        cursor.execute("INSERT INTO eventos (nome, recompensa, meta_participacao, criador_id) VALUES (%s, %s, %s, %s) RETURNING id", (nome, recompensa, meta, ctx.author.id))
        evento_id = cursor.fetchone()[0]; conn.commit()
    conn.close()
    embed = discord.Embed(title="🎉 Novo Evento Criado!", description=f"O evento **'{nome}'** está agora ativo!", color=discord.Color.green())
    embed.add_field(name="ID do Evento", value=f"`{evento_id}`", inline=True); embed.add_field(name="Recompensa", value=f"**🪙 {recompensa}** moedas", inline=True)
    embed.add_field(name="Meta de Participação", value=f"**🎯 {meta}**", inline=True); embed.set_footer(text=f"Use !participar {evento_id} para se inscrever.")
    await ctx.send(embed=embed)
# (etc...)

# =================================================================================
# 6. INICIAR O BOT
# =================================================================================
if TOKEN and DATABASE_URL:
    bot.run(TOKEN)
else:
    print("ERRO: Token do Discord ou URL da Base de Dados não encontrados. Verifique as variáveis de ambiente.")

