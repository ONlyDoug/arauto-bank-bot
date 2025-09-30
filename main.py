# =================================================================================
# 1. IMPORTAÇÕES E CONFIGURAÇÃO INICIAL
# =================================================================================
import discord
from discord.ext import commands, tasks
import psycopg2
import psycopg2.extras
from psycopg2 import pool # Para o Pool de Conexões
import os
from dotenv import load_dotenv
from datetime import datetime, date
import time
import contextlib # Para gerir o contexto da conexão

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
db_connection_pool = None # Variável global para o nosso pool de conexões

# =================================================================================
# 2. GESTÃO OTIMIZADA DA BASE DE DADOS (COM CONNECTION POOL)
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
    """Inicializa a base de dados, criando todas as tabelas se não existirem."""
    with get_db_connection() as conn:
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
    print("Base de dados Supabase verificada e pronta.")

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
    await bot.wait_until_ready()
    recompensa_por_hora = int(get_config_value('recompensa_voz', '10'))
    limite_minutos_diario = int(get_config_value('limite_diario_voz', '120'))
    recompensa_por_ciclo = round((recompensa_por_hora / 60) * 5)
    
    if recompensa_por_ciclo < 1: return

    for guild in bot.guilds:
        for member in guild.members:
            if member.voice and not member.voice.self_mute and not member.voice.self_deaf:
                get_account(member.id)
                activity = get_or_create_daily_activity(member.id, date.today())
                if activity and activity['minutos_voz'] < limite_minutos_diario:
                    with get_db_connection() as conn:
                        with conn.cursor() as cursor:
                            cursor.execute("UPDATE banco SET saldo = saldo + %s WHERE user_id = %s", (recompensa_por_ciclo, member.id))
                            cursor.execute("UPDATE atividade_diaria SET minutos_voz = minutos_voz + 5 WHERE user_id = %s AND data = %s", (member.id, date.today()))
                            conn.commit()

@bot.event
async def on_ready():
    if not DATABASE_URL:
        print("ERRO CRÍTICO: A variável de ambiente DATABASE_URL não foi definida.")
        return
    initialize_connection_pool()
    setup_database()
    voice_channel_rewards.start()
    print(f'Login bem-sucedido como {bot.user.name}')
    print(f'O Arauto Bank está online e pronto para operar!')
    print('------')

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
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("UPDATE banco SET saldo = saldo + %s WHERE user_id = %s", (recompensa, user_id))
                cursor.execute("UPDATE atividade_diaria SET moedas_chat = moedas_chat + %s WHERE user_id = %s AND data = %s", (recompensa, user_id, date.today()))
                conn.commit()
        user_message_cooldowns[user_id] = current_time
    await bot.process_commands(message)

@bot.event
async def on_raw_reaction_add(payload):
    if payload.member.bot: return
    canal_anuncios_id = int(get_config_value('canal_anuncios', '0'))
    if payload.channel_id != canal_anuncios_id: return
    user_id = payload.user_id; message_id = payload.message_id
    recompensa = int(get_config_value('recompensa_reacao', '50'))
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            try:
                cursor.execute("INSERT INTO reacoes_recompensadas (message_id, user_id) VALUES (%s, %s)", (message_id, user_id)); conn.commit()
                get_account(user_id)
                cursor.execute("UPDATE banco SET saldo = saldo + %s WHERE user_id = %s", (recompensa, user_id)); conn.commit()
                registrar_transacao(user_id, "Recompensa", recompensa, f"Leitura do anúncio {message_id}")
            except psycopg2.IntegrityError:
                conn.rollback()

@bot.event
async def on_member_join(member):
    get_account(member.id)
    registrar_transacao(member.id, "Criação de Conta", 0, "Conta criada ao entrar no servidor.")
    print(f'Conta bancária criada para o novo membro: {member.name}')
    
# =================================================================================
# 5. COMANDOS DO BOT
# =================================================================================
@bot.command(name='ola')
async def hello(ctx): await ctx.send(f'Olá, {ctx.author.mention}! Eu sou o Arauto Bank, pronto para servir.')

@bot.command(name='saldo')
async def balance(ctx):
    get_account(ctx.author.id)
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT saldo FROM banco WHERE user_id = %s", (ctx.author.id,)); saldo = cursor.fetchone()[0]
    embed = discord.Embed(title=f"Saldo de {ctx.author.display_name}", description=f"Você possui **🪙 {saldo}** moedas.", color=discord.Color.gold())
    await ctx.send(embed=embed)

@bot.command(name='transferir')
async def transfer(ctx, destinatario: discord.Member, quantidade: int):
    remetente_id = ctx.author.id; destinatario_id = destinatario.id
    if remetente_id == destinatario_id: return await ctx.send("Você não pode transferir para si mesmo.")
    if quantidade <= 0: return await ctx.send("A quantidade deve ser positiva.")
    get_account(remetente_id); get_account(destinatario_id)
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT saldo FROM banco WHERE user_id = %s", (remetente_id,)); saldo_remetente = cursor.fetchone()[0]
            if saldo_remetente < quantidade: return await ctx.send("Saldo insuficiente.")
            cursor.execute("UPDATE banco SET saldo = saldo - %s WHERE user_id = %s", (quantidade, remetente_id))
            cursor.execute("UPDATE banco SET saldo = saldo + %s WHERE user_id = %s", (quantidade, destinatario_id)); conn.commit()
    registrar_transacao(remetente_id, "Transferência Enviada", -quantidade, f"Para {destinatario.display_name}")
    registrar_transacao(destinatario_id, "Transferência Recebida", quantidade, f"De {ctx.author.display_name}")
    embed = discord.Embed(title="💸 Transferência Realizada", description=f"**{ctx.author.display_name}** transferiu **🪙 {quantidade}** para **{destinatario.display_name}**.", color=discord.Color.green())
    await ctx.send(embed=embed)

# --- COMANDO DE EXTRATO CORRIGIDO ---
@bot.command(name='extrato')
async def statement(ctx, data_str: str = None):
    """Mostra o resumo de ganhos e as transações de um dia específico ou as mais recentes."""
    user_id = ctx.author.id
    target_date = None
    if data_str:
        try: target_date = datetime.strptime(data_str, '%d/%m/%Y').date()
        except ValueError: return await ctx.send("Formato de data inválido. Use `DD/MM/AAAA`.")
    
    get_account(user_id)

    # Define a data para o resumo diário (hoje, por defeito)
    display_date = target_date if target_date else date.today()
    
    embed = discord.Embed(title=f"Extrato de {ctx.author.display_name}", color=discord.Color.blue())
    
    # Busca e adiciona o resumo de renda diária
    activity = get_or_create_daily_activity(user_id, display_date)
    recompensa_voz_hora = int(get_config_value('recompensa_voz', '10'))
    total_ganho_voz = (activity['minutos_voz'] / 60) * recompensa_voz_hora
    total_ganho_chat = activity['moedas_chat']
    resumo_renda = (f"**Voz:** 🗣️ +{int(total_ganho_voz)} moedas ({activity['minutos_voz']} minutos)\n"
                    f"**Chat:** 💬 +{total_ganho_chat} moedas")
    embed.add_field(name=f"Resumo de Renda ({display_date.strftime('%d/%m/%Y')})", value=resumo_renda, inline=False)
    
    # Busca as transações importantes, filtrando a renda passiva
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            if target_date:
                cursor.execute("SELECT tipo, valor, descricao, data FROM transacoes WHERE user_id = %s AND DATE(data) = %s AND tipo NOT IN ('Renda Passiva') ORDER BY data DESC", (user_id, target_date))
            else:
                cursor.execute("SELECT tipo, valor, descricao, data FROM transacoes WHERE user_id = %s AND tipo NOT IN ('Renda Passiva') ORDER BY data DESC LIMIT 5", (user_id,))
            transacoes = cursor.fetchall()

    # Adiciona as outras transações
    if not transacoes:
        embed.add_field(name="Transações Detalhadas", value="Nenhuma transação importante para mostrar.", inline=False)
    else:
        title = "Últimas Transações Detalhadas" if not target_date else f"Transações Detalhadas ({target_date.strftime('%d/%m/%Y')})"
        list_of_transactions = []
        for t in transacoes:
            valor_str = f"+{t['valor']}" if t['valor'] > 0 else str(t['valor'])
            cor_valor = "🟢" if t['valor'] > 0 else ("🔴" if t['valor'] < 0 else "⚪")
            data_formatada = t['data'].strftime('%d/%m/%Y %H:%M')
            list_of_transactions.append(f"**{t['tipo']}** - {data_formatada}\n{cor_valor} **Valor:** {valor_str} moedas\n*_{t['descricao']}_*")
        
        embed.add_field(name=title, value="\n\n".join(list_of_transactions), inline=False)
            
    await ctx.send(embed=embed)


@bot.command(name='lastro')
async def silver_value(ctx):
    get_account(ctx.author.id)
    lastro_prata_str = get_config_value('lastro_prata', '1000'); lastro_prata = int(lastro_prata_str)
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT saldo FROM banco WHERE user_id = %s", (ctx.author.id,)); saldo = cursor.fetchone()[0]
    patrimonio_em_prata = saldo * lastro_prata
    embed = discord.Embed(title="🏦 Valor de Lastro em Prata", color=discord.Color.light_grey())
    embed.add_field(name="Taxa de Conversão Atual", value=f"**1** 🪙 moeda do bot = **{lastro_prata:,}** de prata.", inline=False)
    embed.add_field(name=f"Patrimônio de {ctx.author.display_name}", value=f"O seu saldo de **{saldo:,}** 🪙 moedas equivale a **{patrimonio_em_prata:,}** de prata.", inline=False)
    await ctx.send(embed=embed)

@bot.command(name='loja')
async def shop(ctx):
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            cursor.execute("SELECT item_id, nome, preco, descricao FROM loja ORDER BY preco ASC"); itens = cursor.fetchall()
    if not itens: return await ctx.send("A loja está vazia no momento.")
    embed = discord.Embed(title="🎁 Loja de Recompensas do Arauto Bank", color=discord.Color.purple())
    for item in itens: embed.add_field(name=f"**{item['nome']}** (ID: {item['item_id']})", value=f"**Preço:** 🪙 {item['preco']}\n*_{item['descricao']}_*", inline=False)
    await ctx.send(embed=embed)

@bot.command(name='comprar')
async def buy(ctx, item_id: str):
    comprador_id = ctx.author.id; get_account(comprador_id)
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            cursor.execute("SELECT nome, preco FROM loja WHERE item_id = %s", (item_id,)); item = cursor.fetchone()
            if item is None: return await ctx.send(f"O item com ID `{item_id}` não foi encontrado.")
            cursor.execute("SELECT saldo FROM banco WHERE user_id = %s", (comprador_id,)); saldo_comprador = cursor.fetchone()['saldo']
            if saldo_comprador < item['preco']: return await ctx.send(f"Saldo insuficiente! Faltam **🪙 {item['preco'] - saldo_comprador}** moedas.")
            cursor.execute("UPDATE banco SET saldo = saldo - %s WHERE user_id = %s", (item['preco'], comprador_id)); conn.commit()
            registrar_transacao(comprador_id, "Compra na Loja", -item['preco'], f"Comprou o item '{item['nome']}'")
    await ctx.send(f"🎉 Parabéns, {ctx.author.mention}! Você comprou **{item['nome']}** por **🪙 {item['preco']}** moedas.")
    canal_staff = discord.utils.get(ctx.guild.channels, name='🚨-staff-resgates')
    if canal_staff: await canal_staff.send(f"⚠️ **Novo Resgate!** {ctx.author.mention} comprou **'{item['nome']}'** (ID: {item_id}).")

@bot.command(name='criarevento')
@can_manage_events()
async def create_event(ctx, recompensa: int, meta: int, *, nome: str):
    if recompensa <= 0 or meta <= 0: return await ctx.send("A recompensa e a meta devem ser valores positivos.")
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("INSERT INTO eventos (nome, recompensa, meta_participacao, criador_id) VALUES (%s, %s, %s, %s) RETURNING id", (nome, recompensa, meta, ctx.author.id))
            evento_id = cursor.fetchone()[0]; conn.commit()
    embed = discord.Embed(title="🎉 Novo Evento Criado!", description=f"O evento **'{nome}'** está agora ativo!", color=discord.Color.green())
    embed.add_field(name="ID do Evento", value=f"`{evento_id}`", inline=True); embed.add_field(name="Recompensa", value=f"**🪙 {recompensa}** moedas", inline=True)
    embed.add_field(name="Meta de Participação", value=f"**🎯 {meta}**", inline=True); embed.set_footer(text=f"Use !participar {evento_id} para se inscrever.")
    await ctx.send(embed=embed)

@bot.command(name='listareventos')
async def list_events(ctx):
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            cursor.execute("SELECT id, nome, recompensa, meta_participacao FROM eventos WHERE ativo = TRUE ORDER BY id ASC")
            eventos = cursor.fetchall()
    if not eventos: return await ctx.send("Não há eventos ativos no momento.")
    embed = discord.Embed(title="🏆 Eventos Ativos", color=discord.Color.orange())
    for evento in eventos:
        embed.add_field(name=f"**{evento['nome']}** (ID: {evento['id']})", value=f"Recompensa: 🪙 {evento['recompensa']} | Meta: 🎯 {evento['meta_participacao']}\nUse `!participar {evento['id']}`", inline=False)
    await ctx.send(embed=embed)

@bot.command(name='participar')
async def join_event(ctx, evento_id: int):
    get_account(ctx.author.id)
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            cursor.execute("SELECT nome FROM eventos WHERE id = %s AND ativo = TRUE", (evento_id,)); evento = cursor.fetchone()
            if evento is None: return await ctx.send("Este evento não existe ou não está mais ativo.")
            try:
                cursor.execute("INSERT INTO participantes (evento_id, user_id, progresso) VALUES (%s, %s, 0)", (evento_id, ctx.author.id)); conn.commit()
                await ctx.send(f"{ctx.author.mention}, você inscreveu-se com sucesso no evento **'{evento['nome']}'**!")
            except psycopg2.IntegrityError:
                conn.rollback(); await ctx.send(f"{ctx.author.mention}, você já está inscrito neste evento.")

@bot.command(name='confirmar')
@can_manage_events()
async def confirm_participation(ctx, evento_id: int, membros: commands.Greedy[discord.Member]):
    if not membros: return await ctx.send("Você precisa de mencionar pelo menos um membro para confirmar a participação.")
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            cursor.execute("SELECT nome, recompensa, meta_participacao FROM eventos WHERE id = %s AND ativo = TRUE", (evento_id,)); evento = cursor.fetchone()
            if evento is None: return await ctx.send("Este evento não existe ou não está ativo.")
            confirmados_msg = []
            for membro in membros:
                cursor.execute("UPDATE participantes SET progresso = progresso + 1 WHERE evento_id = %s AND user_id = %s RETURNING progresso", (evento_id, membro.id))
                resultado = cursor.fetchone(); conn.commit()
                if resultado:
                    progresso_atual = resultado['progresso']
                    confirmados_msg.append(f"✅ {membro.mention} (Progresso: {progresso_atual}/{evento['meta_participacao']})")
                else:
                    confirmados_msg.append(f"❌ {membro.mention} (Não está inscrito no evento)")
    await ctx.send(f"**Confirmação de Participação no Evento '{evento['nome']}':**\n" + "\n".join(confirmados_msg))

@bot.command(name='meuprogresso')
async def my_progress(ctx, evento_id: int):
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            cursor.execute("SELECT nome, meta_participacao FROM eventos WHERE id = %s AND ativo = TRUE", (evento_id,)); evento = cursor.fetchone()
            if evento is None: return await ctx.send("Este evento não existe ou não está ativo.")
            cursor.execute("SELECT progresso FROM participantes WHERE evento_id = %s AND user_id = %s", (evento_id, ctx.author.id))
            participante = cursor.fetchone()
            progresso = participante['progresso'] if participante else 0
    embed = discord.Embed(title=f"Meu Progresso no Evento: {evento['nome']}", description=f"Você participou **{progresso}** de **{evento['meta_participacao']}** vezes.", color=discord.Color.light_grey())
    await ctx.send(embed=embed)

@bot.command(name='finalizarevento')
@can_manage_events()
async def finish_event(ctx, evento_id: int):
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            cursor.execute("SELECT nome, recompensa, meta_participacao FROM eventos WHERE id = %s AND ativo = TRUE", (evento_id,)); evento = cursor.fetchone()
            if evento is None: return await ctx.send("Este evento não existe ou já foi finalizado.")
            cursor.execute("SELECT user_id, progresso FROM participantes WHERE evento_id = %s", (evento_id,))
            participantes = cursor.fetchall()
            vencedores = []
            if participantes:
                recompensa = evento['recompensa']; meta = evento['meta_participacao']
                for p in participantes:
                    if p['progresso'] >= meta:
                        user_id = p['user_id']
                        cursor.execute("UPDATE banco SET saldo = saldo + %s WHERE user_id = %s", (recompensa, user_id))
                        registrar_transacao(user_id, "Recompensa de Evento", recompensa, f"Completou o evento '{evento['nome']}'")
                        vencedores.append(f"<@{user_id}>")
                conn.commit()
            if not vencedores: await ctx.send(f"O evento **'{evento['nome']}'** foi finalizado, mas nenhum participante atingiu a meta de **{evento['meta_participacao']}** participações.")
            else: await ctx.send(f"🎉 O evento **'{evento['nome']}'** foi finalizado! **{len(vencedores)}** participantes atingiram a meta e receberam **🪙 {recompensa}** moedas cada!\nParabéns: {', '.join(vencedores)}")
            cursor.execute("DELETE FROM eventos WHERE id = %s", (evento_id,)); conn.commit()

@bot.command(name='cancelarevento')
@can_manage_events()
async def cancel_event(ctx, evento_id: int):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM eventos WHERE id = %s RETURNING nome", (evento_id,)); evento_nome = cursor.fetchone(); conn.commit()
    if evento_nome: await ctx.send(f"🗑️ O evento **'{evento_nome[0]}'** (ID: {evento_id}) foi cancelado e removido.")
    else: await ctx.send(f"Não foi encontrado nenhum evento ativo com o ID {evento_id}.")

@bot.command(name='setup')
@commands.has_permissions(administrator=True)
async def setup_server(ctx):
    guild = ctx.guild; categoria_existente = discord.utils.get(guild.categories, name="🪙 BANCO ARAUTO 🪙")
    if categoria_existente: return await ctx.send("⚠️ A estrutura de canais do Arauto Bank já existe.")
    await ctx.send("Iniciando a configuração do servidor..."); categoria = await guild.create_category("🪙 BANCO ARAUTO 🪙")
    overwrites_publico = { guild.default_role: discord.PermissionOverwrite(send_messages=False, view_channel=True) }
    staff_role = discord.utils.get(guild.roles, name="Staff")
    overwrites_staff = { guild.default_role: discord.PermissionOverwrite(view_channel=False), guild.me: discord.PermissionOverwrite(view_channel=True) }
    if staff_role: overwrites_staff[staff_role] = discord.PermissionOverwrite(view_channel=True)
    await categoria.create_text_channel('📜-regras-e-infos', overwrites=overwrites_publico)
    await categoria.create_text_channel('💰-saldo-e-extrato'); await categoria.create_text_channel('🎁-loja-de-recompensas')
    await categoria.create_text_channel('🚨-staff-resgates', overwrites=overwrites_staff); await ctx.send("✅ Configuração do servidor concluída!")

@bot.command(name='addmoedas')
@commands.has_permissions(administrator=True)
async def add_coins(ctx, membro: discord.Member, quantidade: int):
    get_account(membro.id)
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE banco SET saldo = saldo + %s WHERE user_id = %s RETURNING saldo", (quantidade, membro.id)); novo_saldo = cursor.fetchone()[0]; conn.commit()
    registrar_transacao(membro.id, "Depósito Admin", quantidade, f"Adicionado por {ctx.author.display_name}")
    await ctx.send(f"🪙 **{quantidade}** moedas foram adicionadas a {membro.mention}. Novo saldo: **{novo_saldo}**.")

@bot.command(name='definirlastro')
@commands.has_permissions(administrator=True)
async def set_silver_value(ctx, novo_valor: int):
    if novo_valor <= 0: return await ctx.send("O valor do lastro deve ser positivo.")
    set_config_value('lastro_prata', str(novo_valor))
    await ctx.send(f"✅ O valor do lastro foi atualizado. **1** 🪙 moeda do bot agora vale **{novo_valor:,}** de prata.")

@bot.command(name='definirrecompensa')
@commands.has_permissions(administrator=True)
async def set_reward(ctx, tipo: str, valor: int):
    tipo = tipo.lower()
    chaves_validas = {'voz': 'recompensa_voz', 'chat': 'recompensa_chat', 'reacao': 'recompensa_reacao'}
    if tipo not in chaves_validas: return await ctx.send("Tipo de recompensa inválido. Use: `voz`, `chat`, `reacao`.")
    if valor < 0: return await ctx.send("O valor não pode ser negativo.")
    set_config_value(chaves_validas[tipo], str(valor))
    await ctx.send(f"✅ Recompensa para `{tipo}` definida para **{valor}** moedas.")

@bot.command(name='definirlimite')
@commands.has_permissions(administrator=True)
async def set_limit(ctx, tipo: str, valor: int):
    tipo = tipo.lower()
    chaves_validas = {'voz': 'limite_diario_voz', 'chat': 'limite_diario_chat'}
    if tipo not in chaves_validas: return await ctx.send("Tipo de limite inválido. Use: `voz`, `chat`.")
    if valor < 0: return await ctx.send("O valor não pode ser negativo.")
    unidade = "minutos" if tipo == "voz" else "moedas"
    set_config_value(chaves_validas[tipo], str(valor))
    await ctx.send(f"✅ Limite diário para `{tipo}` definido para **{valor}** {unidade}.")

@bot.command(name='definircanal')
@commands.has_permissions(administrator=True)
async def set_channel(ctx, tipo: str, canal: discord.TextChannel):
    tipo = tipo.lower()
    chaves_validas = {'anuncios': 'canal_anuncios'}
    if tipo not in chaves_validas: return await ctx.send("Tipo de canal inválido. Use: `anuncios`.")
    set_config_value(chaves_validas[tipo], str(canal.id))
    await ctx.send(f"✅ Canal de `{tipo}` definido para {canal.mention}.")

@bot.command(name='addcargo')
@commands.has_permissions(administrator=True)
async def add_role_permission(ctx, tipo: str, cargo: discord.Role):
    tipo = tipo.lower()
    chaves_validas = {'eventos': 'cargos_gerente_eventos'}
    if tipo not in chaves_validas: return await ctx.send("Tipo de permissão inválido. Use: `eventos`.")
    chave_config = chaves_validas[tipo]
    ids_atuais_str = get_config_value(chave_config, '')
    ids_atuais = {id_str for id_str in ids_atuais_str.split(',') if id_str}
    if str(cargo.id) in ids_atuais: return await ctx.send(f"O cargo {cargo.mention} já tem permissão para gerir `{tipo}`.")
    ids_atuais.add(str(cargo.id))
    set_config_value(chave_config, ','.join(ids_atuais))
    await ctx.send(f"✅ O cargo {cargo.mention} agora pode gerir `{tipo}`.")

@bot.command(name='removecargo')
@commands.has_permissions(administrator=True)
async def remove_role_permission(ctx, tipo: str, cargo: discord.Role):
    tipo = tipo.lower()
    chaves_validas = {'eventos': 'cargos_gerente_eventos'}
    if tipo not in chaves_validas: return await ctx.send("Tipo de permissão inválido. Use: `eventos`.")
    chave_config = chaves_validas[tipo]
    ids_atuais_str = get_config_value(chave_config, '')
    ids_atuais = {id_str for id_str in ids_atuais_str.split(',') if id_str}
    if str(cargo.id) not in ids_atuais: return await ctx.send(f"O cargo {cargo.mention} não tem permissão para gerir `{tipo}`.")
    ids_atuais.remove(str(cargo.id))
    set_config_value(chave_config, ','.join(ids_atuais))
    await ctx.send(f"🗑️ O cargo {cargo.mention} já não pode gerir `{tipo}`.")

@bot.command(name='listacargos')
@commands.has_permissions(administrator=True)
async def list_role_permissions(ctx, tipo: str):
    tipo = tipo.lower()
    chaves_validas = {'eventos': 'cargos_gerente_eventos'}
    if tipo not in chaves_validas: return await ctx.send("Tipo de permissão inválido. Use: `eventos`.")
    chave_config = chaves_validas[tipo]
    ids_atuais_str = get_config_value(chave_config, '')
    if not ids_atuais_str: return await ctx.send(f"Nenhum cargo está configurado para gerir `{tipo}`.")
    ids_atuais = [int(id_str) for id_str in ids_atuais_str.split(',') if id_str]
    cargos_mencionados = [cargo.mention for role_id in ids_atuais if (cargo := ctx.guild.get_role(role_id))]
    if not cargos_mencionados: return await ctx.send(f"Nenhum dos cargos configurados para gerir `{tipo}` foi encontrado no servidor.")
    await ctx.send(f"**Cargos com permissão para gerir `{tipo}`:**\n" + ", ".join(cargos_mencionados))

@bot.command(name='additem')
@commands.has_permissions(administrator=True)
async def add_item_to_shop(ctx, item_id: str, preco: int, nome: str, *, descricao: str):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            try:
                cursor.execute("INSERT INTO loja (item_id, nome, preco, descricao) VALUES (%s, %s, %s, %s)", (item_id, nome, preco, descricao)); conn.commit()
                await ctx.send(f"✅ O item **'{nome}'** foi adicionado à loja com sucesso!")
            except psycopg2.IntegrityError: await ctx.send(f"⚠️ Erro: Já existe um item com o ID `{item_id}`.")

@bot.command(name='delitem')
@commands.has_permissions(administrator=True)
async def delete_item_from_shop(ctx, item_id: str):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM loja WHERE item_id = %s", (item_id,))
            if cursor.rowcount > 0:
                conn.commit(); await ctx.send(f"🗑️ O item com ID `{item_id}` foi removido da loja.")
            else: await ctx.send(f"⚠️ Não foi encontrado nenhum item com o ID `{item_id}`.")

# =================================================================================
# 6. INICIAR O BOT
# =================================================================================
if TOKEN and DATABASE_URL:
    bot.run(TOKEN)
else:
    print("ERRO: Token do Discord ou URL da Base de Dados não encontrados. Verifique as variáveis de ambiente.")

