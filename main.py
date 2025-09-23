# =================================================================================
# 1. IMPORTAÇÕES E CONFIGURAÇÃO INICIAL
# =================================================================================
import discord
from discord.ext import commands
import sqlite3
import os
from dotenv import load_dotenv

# Carrega as variáveis de ambiente do ficheiro .env (para desenvolvimento local)
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# Define o caminho para a base de dados no armazenamento sincronizado da Discloud
# O diretório /storage é fornecido automaticamente pela Discloud.
STORAGE_PATH = "/storage"
DB_FILE = os.path.join(STORAGE_PATH, "arauto_bank.db")

# Define as intenções (Intents) necessárias para o bot funcionar
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.messages = True
intents.message_content = True

# Cria a instância do bot com o prefixo '!' e as intenções definidas
bot = commands.Bot(command_prefix='!', intents=intents)

# =================================================================================
# 2. CONFIGURAÇÃO DA BASE DE DADOS
# =================================================================================

def setup_database():
    """
    Inicializa a base de dados SQLite, criando as tabelas 'banco' e 'loja'
    se elas ainda não existirem.
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Cria a tabela para guardar os saldos dos membros
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS banco (
        user_id INTEGER PRIMARY KEY,
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
    print("Base de dados verificada e pronta.")

# =================================================================================
# 3. FUNÇÕES AUXILIARES DO BANCO
# =================================================================================

def get_account(user_id: int):
    """
    Verifica se um utilizador tem uma conta. Se não tiver, cria uma com saldo 0.
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT saldo FROM banco WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    if result is None:
        cursor.execute("INSERT INTO banco (user_id, saldo) VALUES (?, 0)", (user_id,))
        conn.commit()
    conn.close()

# =================================================================================
# 4. EVENTOS DO BOT
# =================================================================================

@bot.event
async def on_ready():
    """
    Evento que é disparado quando o bot se conecta com sucesso ao Discord.
    """
    setup_database() # Garante que a BD está pronta ao iniciar
    print(f'Login bem-sucedido como {bot.user.name}')
    print(f'O Arauto Bank está online e pronto para operar!')
    print('------')

@bot.event
async def on_member_join(member):
    """
    Evento que é disparado quando um novo membro entra no servidor.
    Cria automaticamente uma conta no banco para ele.
    """
    get_account(member.id)
    print(f'Conta bancária criada para o novo membro: {member.name}')

# =================================================================================
# 5. COMANDOS DO BOT
# =================================================================================

# --- Comandos Gerais ---
@bot.command(name='ola')
async def hello(ctx):
    """Responde com uma saudação."""
    await ctx.send(f'Olá, {ctx.author.mention}! Eu sou o Arauto Bank, pronto para servir.')

# --- Comandos de Economia ---
@bot.command(name='saldo')
async def balance(ctx):
    """Mostra o saldo do utilizador que executou o comando."""
    get_account(ctx.author.id) # Garante que o utilizador tem uma conta
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT saldo FROM banco WHERE user_id = ?", (ctx.author.id,))
    saldo = cursor.fetchone()[0]
    conn.close()
    
    embed = discord.Embed(
        title=f"Saldo de {ctx.author.display_name}",
        description=f"Você possui **🪙 {saldo}** moedas.",
        color=discord.Color.gold()
    )
    await ctx.send(embed=embed)

@bot.command(name='transferir')
async def transfer(ctx, destinatario: discord.Member, quantidade: int):
    """Transfere moedas para outro membro."""
    remetente_id = ctx.author.id
    destinatario_id = destinatario.id

    if remetente_id == destinatario_id:
        await ctx.send("Você não pode transferir moedas para si mesmo.")
        return
    if quantidade <= 0:
        await ctx.send("A quantidade deve ser um número positivo.")
        return

    get_account(remetente_id)
    get_account(destinatario_id)
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT saldo FROM banco WHERE user_id = ?", (remetente_id,))
    saldo_remetente = cursor.fetchone()[0]

    if saldo_remetente < quantidade:
        await ctx.send("Saldo insuficiente para realizar a transferência.")
        conn.close()
        return

    # Realiza a transação
    cursor.execute("UPDATE banco SET saldo = saldo - ? WHERE user_id = ?", (quantidade, remetente_id))
    cursor.execute("UPDATE banco SET saldo = saldo + ? WHERE user_id = ?", (quantidade, destinatario_id))
    conn.commit()
    conn.close()
    
    embed = discord.Embed(
        title="💸 Transferência Realizada com Sucesso",
        description=f"**{ctx.author.display_name}** transferiu **🪙 {quantidade}** moedas para **{destinatario.display_name}**.",
        color=discord.Color.green()
    )
    await ctx.send(embed=embed)

# --- Comandos da Loja ---
@bot.command(name='loja')
async def shop(ctx):
    """Mostra os itens disponíveis na loja."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row # Permite aceder às colunas por nome
    cursor = conn.cursor()
    cursor.execute("SELECT item_id, nome, preco, descricao FROM loja ORDER BY preco ASC")
    itens = cursor.fetchall()
    conn.close()

    if not itens:
        await ctx.send("A loja está vazia no momento.")
        return

    embed = discord.Embed(title="🎁 Loja de Recompensas do Arauto Bank", color=discord.Color.purple())
    for item in itens:
        embed.add_field(
            name=f"**{item['nome']}** (ID: {item['item_id']})",
            value=f"**Preço:** 🪙 {item['preco']}\n*_{item['descricao']}_*",
            inline=False
        )
    await ctx.send(embed=embed)

@bot.command(name='comprar')
async def buy(ctx, item_id: str):
    """Compra um item da loja."""
    comprador_id = ctx.author.id
    get_account(comprador_id)

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Verifica se o item existe
    cursor.execute("SELECT nome, preco FROM loja WHERE item_id = ?", (item_id,))
    item = cursor.fetchone()
    if item is None:
        await ctx.send(f"O item com ID `{item_id}` não foi encontrado na loja.")
        conn.close()
        return

    # Verifica se o comprador tem saldo
    cursor.execute("SELECT saldo FROM banco WHERE user_id = ?", (comprador_id,))
    saldo_comprador = cursor.fetchone()['saldo']

    if saldo_comprador < item['preco']:
        await ctx.send(f"Saldo insuficiente! Você precisa de mais **🪙 {item['preco'] - saldo_comprador}** moedas para comprar `{item['nome']}`.")
        conn.close()
        return

    # Processa a compra
    cursor.execute("UPDATE banco SET saldo = saldo - ? WHERE user_id = ?", (item['preco'], comprador_id))
    conn.commit()
    conn.close()

    # Envia confirmação ao comprador
    await ctx.send(f"🎉 Parabéns, {ctx.author.mention}! Você comprou **{item['nome']}** por **🪙 {item['preco']}** moedas. O seu novo saldo é **🪙 {saldo_comprador - item['preco']}**.")

    # Envia notificação para a staff
    canal_staff = discord.utils.get(ctx.guild.channels, name='🚨-staff-resgates')
    if canal_staff:
        await canal_staff.send(
            f"⚠️ **Novo Resgate!** O membro {ctx.author.mention} comprou o item **'{item['nome']}'** (ID: {item_id}). Por favor, realize a entrega."
        )

# --- Comandos de Administração ---
@bot.command(name='setup')
@commands.has_permissions(administrator=True)
async def setup_server(ctx):
    """Cria a estrutura de canais e categorias para o bot."""
    guild = ctx.guild
    # Verifica se a categoria já existe
    categoria_existente = discord.utils.get(guild.categories, name="🪙 BANCO ARAUTO 🪙")
    if categoria_existente:
        await ctx.send("⚠️ A estrutura de canais do Arauto Bank já existe.")
        return

    await ctx.send("Iniciando a configuração do servidor para o Arauto Bank...")
    
    # Cria a categoria
    categoria = await guild.create_category("🪙 BANCO ARAUTO 🪙")

    # Define permissões para canais públicos
    overwrites_publico = {
        guild.default_role: discord.PermissionOverwrite(send_messages=False, view_channel=True)
    }
    
    # Define permissões para o canal de staff
    staff_role = discord.utils.get(guild.roles, name="Staff") # Assumindo que existe um cargo "Staff"
    if not staff_role:
        # Se não houver cargo Staff, apenas administradores podem ver
        overwrites_staff = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(view_channel=True)
        }
    else:
        overwrites_staff = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            staff_role: discord.PermissionOverwrite(view_channel=True),
            guild.me: discord.PermissionOverwrite(view_channel=True)
        }

    # Cria os canais
    await categoria.create_text_channel('📜-regras-e-infos', overwrites=overwrites_publico)
    await categoria.create_text_channel('💰-saldo-e-extrato')
    await categoria.create_text_channel('🎁-loja-de-recompensas')
    await categoria.create_text_channel('🚨-staff-resgates', overwrites=overwrites_staff)
    
    await ctx.send("✅ Configuração do servidor concluída com sucesso!")

@bot.command(name='addmoedas')
@commands.has_permissions(administrator=True)
async def add_coins(ctx, membro: discord.Member, quantidade: int):
    """Adiciona moedas a um membro."""
    get_account(membro.id)
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE banco SET saldo = saldo + ? WHERE user_id = ?", (quantidade, membro.id))
    conn.commit()
    cursor.execute("SELECT saldo FROM banco WHERE user_id = ?", (membro.id,))
    novo_saldo = cursor.fetchone()[0]
    conn.close()

    await ctx.send(f"🪙 **{quantidade}** moedas foram adicionadas a {membro.mention}. Novo saldo: **{novo_saldo}**.")

@bot.command(name='additem')
@commands.has_permissions(administrator=True)
async def add_item_to_shop(ctx, item_id: str, preco: int, nome: str, *, descricao: str):
    """Adiciona um novo item à loja."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO loja (item_id, nome, preco, descricao) VALUES (?, ?, ?, ?)",
                       (item_id, nome, preco, descricao))
        conn.commit()
        await ctx.send(f"✅ O item **'{nome}'** foi adicionado à loja com sucesso!")
    except sqlite3.IntegrityError:
        await ctx.send(f"⚠️ Erro: Já existe um item com o ID `{item_id}`.")
    finally:
        conn.close()

@bot.command(name='delitem')
@commands.has_permissions(administrator=True)
async def delete_item_from_shop(ctx, item_id: str):
    """Remove um item da loja pelo seu ID."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM loja WHERE item_id = ?", (item_id,))
    if cursor.rowcount > 0:
        conn.commit()
        await ctx.send(f"🗑️ O item com ID `{item_id}` foi removido da loja.")
    else:
        await ctx.send(f"⚠️ Não foi encontrado nenhum item com o ID `{item_id}`.")
    conn.close()

# =================================================================================
# 6. INICIAR O BOT
# =================================================================================
bot.run(TOKEN)

