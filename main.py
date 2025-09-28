# =================================================================================
# 1. IMPORTAÇÕES E CONFIGURAÇÃO INICIAL
# =================================================================================
import discord
from discord.ext import commands
import psycopg2
import psycopg2.extras # Para aceder às colunas por nome
import os
from dotenv import load_dotenv
from datetime import datetime

# Carrega as variáveis de ambiente do ficheiro .env
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')

# Define as intenções (Intents) do bot
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.messages = True
intents.message_content = True

# Cria a instância do bot
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
    """Inicializa a base de dados, criando todas as tabelas se não existirem."""
    conn = get_db_connection()
    if conn is None: return

    with conn.cursor() as cursor:
        cursor.execute("CREATE TABLE IF NOT EXISTS banco (user_id BIGINT PRIMARY KEY, saldo INTEGER NOT NULL DEFAULT 0)")
        cursor.execute("CREATE TABLE IF NOT EXISTS loja (item_id TEXT PRIMARY KEY, nome TEXT NOT NULL, preco INTEGER NOT NULL, descricao TEXT)")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS transacoes (
            id SERIAL PRIMARY KEY, user_id BIGINT NOT NULL, tipo TEXT NOT NULL,
            valor INTEGER NOT NULL, descricao TEXT, data TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        )""")
        # TABELA DE EVENTOS ATUALIZADA com meta_participacao
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS eventos (
            id SERIAL PRIMARY KEY, nome TEXT NOT NULL, recompensa INTEGER NOT NULL,
            meta_participacao INTEGER NOT NULL DEFAULT 1,
            ativo BOOLEAN DEFAULT TRUE, criador_id BIGINT NOT NULL,
            data_criacao TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        )""")
        # TABELA DE PARTICIPANTES ATUALIZADA com progresso
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS participantes (
            evento_id INTEGER REFERENCES eventos(id) ON DELETE CASCADE,
            user_id BIGINT,
            progresso INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (evento_id, user_id)
        )""")
    
    conn.commit()
    conn.close()
    print("Base de dados Supabase verificada e pronta (com sistema de progresso de eventos).")

def get_account(user_id: int):
    """Garante que um utilizador tem uma conta no banco."""
    conn = get_db_connection()
    if conn is None: return
    with conn.cursor() as cursor:
        cursor.execute("SELECT 1 FROM banco WHERE user_id = %s", (user_id,))
        if cursor.fetchone() is None:
            cursor.execute("INSERT INTO banco (user_id, saldo) VALUES (%s, 0) ON CONFLICT (user_id) DO NOTHING", (user_id,))
            conn.commit()
    conn.close()

def registrar_transacao(user_id: int, tipo: str, valor: int, descricao: str):
    """Registra uma nova transação na base de dados."""
    conn = get_db_connection()
    if conn is None: return
    with conn.cursor() as cursor:
        cursor.execute("INSERT INTO transacoes (user_id, tipo, valor, descricao) VALUES (%s, %s, %s, %s)", (user_id, tipo, valor, descricao))
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

@bot.event
async def on_member_join(member):
    """Cria uma conta para novos membros."""
    get_account(member.id)
    registrar_transacao(member.id, "Criação de Conta", 0, "Conta criada ao entrar no servidor.")
    print(f'Conta bancária criada para o novo membro: {member.name}')

# =================================================================================
# 5. COMANDOS DO BOT
# =================================================================================

# --- Comandos Gerais (Inalterados) ---
@bot.command(name='ola')
async def hello(ctx):
    await ctx.send(f'Olá, {ctx.author.mention}! Eu sou o Arauto Bank, pronto para servir.')

# --- Comandos de Economia (Inalterados) ---
@bot.command(name='saldo')
async def balance(ctx):
    get_account(ctx.author.id)
    conn = get_db_connection()
    if conn is None: return await ctx.send("Erro de conexão com a base de dados.")
    with conn.cursor() as cursor:
        cursor.execute("SELECT saldo FROM banco WHERE user_id = %s", (ctx.author.id,))
        saldo = cursor.fetchone()[0]
    conn.close()
    embed = discord.Embed(title=f"Saldo de {ctx.author.display_name}", description=f"Você possui **🪙 {saldo}** moedas.", color=discord.Color.gold())
    await ctx.send(embed=embed)

@bot.command(name='transferir')
async def transfer(ctx, destinatario: discord.Member, quantidade: int):
    # (Código inalterado)
    remetente_id = ctx.author.id; destinatario_id = destinatario.id
    if remetente_id == destinatario_id: return await ctx.send("Você não pode transferir para si mesmo.")
    if quantidade <= 0: return await ctx.send("A quantidade deve ser positiva.")
    get_account(remetente_id); get_account(destinatario_id)
    conn = get_db_connection();
    if conn is None: return await ctx.send("Erro de conexão com a base de dados.")
    with conn.cursor() as cursor:
        cursor.execute("SELECT saldo FROM banco WHERE user_id = %s", (remetente_id,)); saldo_remetente = cursor.fetchone()[0]
        if saldo_remetente < quantidade: return await ctx.send("Saldo insuficiente.")
        cursor.execute("UPDATE banco SET saldo = saldo - %s WHERE user_id = %s", (quantidade, remetente_id))
        cursor.execute("UPDATE banco SET saldo = saldo + %s WHERE user_id = %s", (quantidade, destinatario_id)); conn.commit()
    registrar_transacao(remetente_id, "Transferência Enviada", -quantidade, f"Para {destinatario.display_name}")
    registrar_transacao(destinatario_id, "Transferência Recebida", quantidade, f"De {ctx.author.display_name}")
    conn.close()
    embed = discord.Embed(title="💸 Transferência Realizada", description=f"**{ctx.author.display_name}** transferiu **🪙 {quantidade}** para **{destinatario.display_name}**.", color=discord.Color.green())
    await ctx.send(embed=embed)

@bot.command(name='extrato')
async def statement(ctx):
    # (Código inalterado)
    user_id = ctx.author.id; get_account(user_id)
    conn = get_db_connection();
    if conn is None: return await ctx.send("Erro de conexão com a base de dados.")
    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
        cursor.execute("SELECT tipo, valor, descricao, data FROM transacoes WHERE user_id = %s ORDER BY data DESC LIMIT 5", (user_id,))
        transacoes = cursor.fetchall()
    conn.close()
    embed = discord.Embed(title=f"Extrato Bancário de {ctx.author.display_name}", color=discord.Color.blue())
    if not transacoes: embed.description = "Você ainda não tem nenhuma transação registada."
    else:
        for t in transacoes:
            valor_str = f"+{t['valor']}" if t['valor'] > 0 else str(t['valor']); cor_valor = "🟢" if t['valor'] > 0 else ("🔴" if t['valor'] < 0 else "⚪")
            data_formatada = t['data'].strftime('%d/%m/%Y %H:%M')
            embed.add_field(name=f"**{t['tipo']}** - {data_formatada}", value=f"{cor_valor} **Valor:** {valor_str} moedas\n*_{t['descricao']}_*", inline=False)
    await ctx.send(embed=embed)

# --- Comandos da Loja (Inalterados) ---
@bot.command(name='loja')
async def shop(ctx):
    # (Código inalterado)
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
    # (Código inalterado)
    comprador_id = ctx.author.id; get_account(comprador_id)
    conn = get_db_connection();
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

# --- Comandos de Eventos (ATUALIZADOS E NOVOS) ---
@bot.command(name='criarevento')
@commands.has_permissions(administrator=True)
async def create_event(ctx, recompensa: int, meta: int, *, nome: str):
    """Cria um novo evento com uma recompensa e uma meta de participação."""
    if recompensa <= 0 or meta <= 0: return await ctx.send("A recompensa e a meta devem ser valores positivos.")
    conn = get_db_connection();
    if conn is None: return await ctx.send("Erro de conexão com a base de dados.")
    with conn.cursor() as cursor:
        cursor.execute("INSERT INTO eventos (nome, recompensa, meta_participacao, criador_id) VALUES (%s, %s, %s, %s) RETURNING id", (nome, recompensa, meta, ctx.author.id))
        evento_id = cursor.fetchone()[0]; conn.commit()
    conn.close()
    embed = discord.Embed(title="🎉 Novo Evento Criado!", description=f"O evento **'{nome}'** está agora ativo!", color=discord.Color.green())
    embed.add_field(name="ID do Evento", value=f"`{evento_id}`", inline=True)
    embed.add_field(name="Recompensa", value=f"**🪙 {recompensa}** moedas", inline=True)
    embed.add_field(name="Meta de Participação", value=f"**🎯 {meta}**", inline=True)
    embed.set_footer(text=f"Use !participar {evento_id} para se inscrever.")
    await ctx.send(embed=embed)

@bot.command(name='listareventos')
async def list_events(ctx):
    """Lista todos os eventos ativos."""
    conn = get_db_connection();
    if conn is None: return await ctx.send("Erro de conexão com a base de dados.")
    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
        cursor.execute("SELECT id, nome, recompensa, meta_participacao FROM eventos WHERE ativo = TRUE ORDER BY id ASC")
        eventos = cursor.fetchall()
    conn.close()
    if not eventos: return await ctx.send("Não há eventos ativos no momento.")
    embed = discord.Embed(title="🏆 Eventos Ativos", color=discord.Color.orange())
    for evento in eventos:
        embed.add_field(name=f"**{evento['nome']}** (ID: {evento['id']})", value=f"Recompensa: 🪙 {evento['recompensa']} | Meta: 🎯 {evento['meta_participacao']}\nUse `!participar {evento['id']}`", inline=False)
    await ctx.send(embed=embed)

@bot.command(name='participar')
async def join_event(ctx, evento_id: int):
    """Permite que um membro se inscreva para participar de um evento."""
    get_account(ctx.author.id)
    conn = get_db_connection();
    if conn is None: return await ctx.send("Erro de conexão com a base de dados.")
    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
        cursor.execute("SELECT nome FROM eventos WHERE id = %s AND ativo = TRUE", (evento_id,)); evento = cursor.fetchone()
        if evento is None: return await ctx.send("Este evento não existe ou não está mais ativo.")
        try:
            cursor.execute("INSERT INTO participantes (evento_id, user_id, progresso) VALUES (%s, %s, 0)", (evento_id, ctx.author.id)); conn.commit()
            await ctx.send(f"{ctx.author.mention}, você inscreveu-se com sucesso no evento **'{evento['nome']}'**!")
        except psycopg2.IntegrityError:
            conn.rollback(); await ctx.send(f"{ctx.author.mention}, você já está inscrito neste evento.")
    conn.close()

@bot.command(name='confirmar')
@commands.has_permissions(administrator=True)
async def confirm_participation(ctx, evento_id: int, membros: commands.Greedy[discord.Member]):
    """Confirma a participação de um ou mais membros numa atividade do evento."""
    if not membros: return await ctx.send("Você precisa de mencionar pelo menos um membro para confirmar a participação.")
    conn = get_db_connection();
    if conn is None: return await ctx.send("Erro de conexão com a base de dados.")
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
        
    conn.close()
    await ctx.send(f"**Confirmação de Participação no Evento '{evento['nome']}':**\n" + "\n".join(confirmados_msg))

@bot.command(name='meuprogresso')
async def my_progress(ctx, evento_id: int):
    """Mostra o progresso do membro num evento específico."""
    conn = get_db_connection();
    if conn is None: return await ctx.send("Erro de conexão com a base de dados.")
    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
        cursor.execute("SELECT nome, meta_participacao FROM eventos WHERE id = %s AND ativo = TRUE", (evento_id,)); evento = cursor.fetchone()
        if evento is None: return await ctx.send("Este evento não existe ou não está ativo.")
        cursor.execute("SELECT progresso FROM participantes WHERE evento_id = %s AND user_id = %s", (evento_id, ctx.author.id))
        participante = cursor.fetchone()
        progresso = participante['progresso'] if participante else 0
    conn.close()
    embed = discord.Embed(title=f"Meu Progresso no Evento: {evento['nome']}", description=f"Você participou **{progresso}** de **{evento['meta_participacao']}** vezes.", color=discord.Color.light_grey())
    await ctx.send(embed=embed)

@bot.command(name='finalizarevento')
@commands.has_permissions(administrator=True)
async def finish_event(ctx, evento_id: int):
    """Finaliza um evento e distribui as recompensas para quem atingiu a meta."""
    conn = get_db_connection();
    if conn is None: return await ctx.send("Erro de conexão com a base de dados.")
    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
        cursor.execute("SELECT nome, recompensa, meta_participacao FROM eventos WHERE id = %s AND ativo = TRUE", (evento_id,)); evento = cursor.fetchone()
        if evento is None: return await ctx.send("Este evento não existe ou já foi finalizado.")
        
        cursor.execute("SELECT user_id, progresso FROM participantes WHERE evento_id = %s", (evento_id,))
        participantes = cursor.fetchall()
        
        vencedores = []
        if participantes:
            recompensa = evento['recompensa']
            meta = evento['meta_participacao']
            for p in participantes:
                if p['progresso'] >= meta:
                    user_id = p['user_id']
                    cursor.execute("UPDATE banco SET saldo = saldo + %s WHERE user_id = %s", (recompensa, user_id))
                    registrar_transacao(user_id, "Recompensa de Evento", recompensa, f"Completou o evento '{evento['nome']}'")
                    vencedores.append(f"<@{user_id}>")
            conn.commit()
        
        if not vencedores:
            await ctx.send(f"O evento **'{evento['nome']}'** foi finalizado, mas nenhum participante atingiu a meta de **{evento['meta_participacao']}** participações.")
        else:
            await ctx.send(f"🎉 O evento **'{evento['nome']}'** foi finalizado! **{len(vencedores)}** participantes atingiram a meta e receberam **🪙 {evento['recompensa']}** moedas cada!\nParabéns: {', '.join(vencedores)}")

        cursor.execute("DELETE FROM eventos WHERE id = %s", (evento_id,)); conn.commit()
    conn.close()

@bot.command(name='cancelarevento')
@commands.has_permissions(administrator=True)
async def cancel_event(ctx, evento_id: int):
    # (Código inalterado)
    conn = get_db_connection();
    if conn is None: return await ctx.send("Erro de conexão com a base de dados.")
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM eventos WHERE id = %s RETURNING nome", (evento_id,)); evento_nome = cursor.fetchone(); conn.commit()
    conn.close()
    if evento_nome: await ctx.send(f"🗑️ O evento **'{evento_nome[0]}'** (ID: {evento_id}) foi cancelado e removido.")
    else: await ctx.send(f"Não foi encontrado nenhum evento ativo com o ID {evento_id}.")

# --- Comandos de Administração (Inalterados) ---
@bot.command(name='setup')
@commands.has_permissions(administrator=True)
async def setup_server(ctx):
    # (Código inalterado)
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
    # (Código inalterado)
    get_account(membro.id); conn = get_db_connection()
    if conn is None: return await ctx.send("Erro de conexão com a base de dados.")
    with conn.cursor() as cursor:
        cursor.execute("UPDATE banco SET saldo = saldo + %s WHERE user_id = %s RETURNING saldo", (quantidade, membro.id)); novo_saldo = cursor.fetchone()[0]; conn.commit()
    registrar_transacao(membro.id, "Depósito Admin", quantidade, f"Adicionado por {ctx.author.display_name}"); conn.close()
    await ctx.send(f"🪙 **{quantidade}** moedas foram adicionadas a {membro.mention}. Novo saldo: **{novo_saldo}**.")

@bot.command(name='additem')
@commands.has_permissions(administrator=True)
async def add_item_to_shop(ctx, item_id: str, preco: int, nome: str, *, descricao: str):
    # (Código inalterado)
    conn = get_db_connection();
    if conn is None: return await ctx.send("Erro de conexão com a base de dados.")
    with conn.cursor() as cursor:
        try:
            cursor.execute("INSERT INTO loja (item_id, nome, preco, descricao) VALUES (%s, %s, %s, %s)", (item_id, nome, preco, descricao)); conn.commit()
            await ctx.send(f"✅ O item **'{nome}'** foi adicionado à loja com sucesso!")
        except psycopg2.IntegrityError: await ctx.send(f"⚠️ Erro: Já existe um item com o ID `{item_id}`.")
    conn.close()

@bot.command(name='delitem')
@commands.has_permissions(administrator=True)
async def delete_item_from_shop(ctx, item_id: str):
    # (Código inalterado)
    conn = get_db_connection();
    if conn is None: return await ctx.send("Erro de conexão com a base de dados.")
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM loja WHERE item_id = %s", (item_id,))
        if cursor.rowcount > 0:
            conn.commit(); await ctx.send(f"🗑️ O item com ID `{item_id}` foi removido da loja.")
        else: await ctx.send(f"⚠️ Não foi encontrado nenhum item com o ID `{item_id}`.")
    conn.close()

# =================================================================================
# 6. INICIAR O BOT
# =================================================================================
if TOKEN and DATABASE_URL:
    bot.run(TOKEN)
else:
    print("ERRO: Token do Discord ou URL da Base de Dados não encontrados. Verifique as variáveis de ambiente.")

