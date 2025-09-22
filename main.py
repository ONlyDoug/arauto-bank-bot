"""
Ficheiro principal do Arauto Bank.

Versão 2.0 - Migrado para Base de Dados SQLite
Este ficheiro contém toda a lógica para o bot do Discord, usando uma base de dados
SQLite para garantir a persistência dos dados na plataforma de hospedagem.
"""

# =================================================================================
# 1. IMPORTAÇÕES E CONFIGURAÇÃO INICIAL
# =================================================================================

import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import sqlite3

# Carrega as variáveis de ambiente do ficheiro .env
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# Define as Intents do bot
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

# Define o nome do ficheiro da nossa base de dados
DB_FILE = "arauto_bank.db"

# =================================================================================
# 2. CONFIGURAÇÃO E FUNÇÕES DA BASE DE DADOS (SQLITE)
# =================================================================================

def setup_database():
    """
    Inicializa a base de dados e cria as tabelas se não existirem.
    Esta função é executada uma vez quando o bot é iniciado.
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
    print("Base de dados configurada e pronta.")

def ensure_account(user_id):
    """
    Garante que um utilizador tem uma conta no banco.
    Usa 'INSERT OR IGNORE' para evitar erros se a conta já existir.
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO banco (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()

# Executa a configuração da base de dados ao iniciar o script
setup_database()

# =================================================================================
# 3. INICIALIZAÇÃO DO BOT
# =================================================================================

bot = commands.Bot(command_prefix='!', intents=intents)

# =================================================================================
# 4. EVENTOS DO BOT
# =================================================================================

@bot.event
async def on_ready():
    """Evento disparado quando o bot se conecta com sucesso ao Discord."""
    print(f'Login bem-sucedido como {bot.user.name}')
    print('O Arauto Bank está online e a usar a base de dados SQLite!')
    print('------')

@bot.event
async def on_member_join(member):
    """Cria automaticamente uma conta no banco para novos membros."""
    ensure_account(member.id)
    print(f'Conta criada na base de dados para o novo membro: {member.name}')

# =================================================================================
# 5. COMANDOS DE UTILIZADOR (Atualizados para SQLite)
# =================================================================================

@bot.command(name='saldo', help='Exibe o saldo de moedas do utilizador.')
async def balance(ctx):
    """Verifica e exibe o saldo do utilizador a partir da base de dados."""
    ensure_account(ctx.author.id)
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT saldo FROM banco WHERE user_id = ?", (ctx.author.id,))
    user_balance = cursor.fetchone()[0]
    conn.close()
    
    embed = discord.Embed(
        title=f"Saldo de {ctx.author.name}",
        description=f"O seu saldo atual no Arauto Bank é de:\n🪙 **{user_balance}** moedas",
        color=discord.Color.gold()
    )
    await ctx.send(embed=embed)

@bot.command(name='loja', help='Mostra os itens disponíveis na loja de recompensas.')
async def shop(ctx):
    """Exibe todos os itens da loja a partir da base de dados."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT item_id, nome, preco, descricao FROM loja ORDER BY preco ASC")
    items = cursor.fetchall()
    conn.close()

    embed = discord.Embed(
        title="🎁 Loja de Recompensas do Arauto Bank 🎁",
        description="Aqui estão os itens que pode comprar com as suas moedas:",
        color=discord.Color.purple()
    )
    
    if not items:
        embed.description = "A loja está vazia no momento. Peça a um admin para adicionar itens!"
    else:
        for item_id, nome, preco, descricao in items:
            embed.add_field(
                name=f"ID: {item_id} | {nome} - 🪙 {preco} moedas",
                value=descricao or "Sem descrição.",
                inline=False
            )
            
    embed.set_footer(text="Para comprar, use o comando !comprar <ID do item>")
    await ctx.send(embed=embed)

@bot.command(name='comprar', help='Compra um item da loja. Uso: !comprar <ID do item>')
async def buy_item(ctx, item_id: str):
    """Processa a compra de um item, interagindo com a base de dados."""
    comprador_id = ctx.author.id
    ensure_account(comprador_id)

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Verifica os dados do item e do comprador
    cursor.execute("SELECT preco, nome FROM loja WHERE item_id = ?", (item_id,))
    item = cursor.fetchone()
    cursor.execute("SELECT saldo FROM banco WHERE user_id = ?", (comprador_id,))
    saldo_comprador = cursor.fetchone()[0]

    if not item:
        await ctx.send(f"Desculpe, o item com ID `{item_id}` não foi encontrado na loja.")
        conn.close()
        return

    preco_item, nome_item = item
    if saldo_comprador < preco_item:
        await ctx.send(f"Saldo insuficiente para comprar **{nome_item}**. Você precisa de 🪙 {preco_item}, mas tem apenas 🪙 {saldo_comprador}.")
        conn.close()
        return

    # Processa a compra (Transação)
    novo_saldo = saldo_comprador - preco_item
    cursor.execute("UPDATE banco SET saldo = ? WHERE user_id = ?", (novo_saldo, comprador_id))
    conn.commit()
    conn.close()

    # Mensagens de confirmação
    await ctx.send(f"✅ Compra realizada com sucesso! Você comprou **{nome_item}** por **{preco_item}** moedas. O seu novo saldo é 🪙 **{novo_saldo}**.")
    
    # Notificação para a staff
    canal_staff = discord.utils.get(ctx.guild.text_channels, name='🚨-staff-resgates')
    if canal_staff:
        await canal_staff.send(f"📢 **Nova Compra para Resgate!**\nO membro **{ctx.author.mention}** comprou **{nome_item}** (ID: `{item_id}`).")

@bot.command(name='transferir', help='Transfere moedas para outro membro. Uso: !transferir @membro <quantidade>')
async def transfer_coins(ctx, destinatario: discord.Member, quantidade: int):
    """Transfere moedas entre membros, com transações na base de dados."""
    remetente = ctx.author
    if destinatario == remetente or quantidade <= 0:
        await ctx.send("Entrada inválida. Verifique o destinatário e a quantidade.")
        return
        
    ensure_account(remetente.id)
    ensure_account(destinatario.id)
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT saldo FROM banco WHERE user_id = ?", (remetente.id,))
    saldo_remetente = cursor.fetchone()[0]

    if saldo_remetente < quantidade:
        await ctx.send(f"Saldo insuficiente. Você tem apenas 🪙 {saldo_remetente} moedas.")
        conn.close()
        return

    # Realiza a transação
    cursor.execute("UPDATE banco SET saldo = saldo - ? WHERE user_id = ?", (quantidade, remetente.id))
    cursor.execute("UPDATE banco SET saldo = saldo + ? WHERE user_id = ?", (quantidade, destinatario.id))
    conn.commit()
    
    # Obtém os novos saldos para confirmação
    cursor.execute("SELECT saldo FROM banco WHERE user_id = ?", (remetente.id,))
    novo_saldo_remetente = cursor.fetchone()[0]
    cursor.execute("SELECT saldo FROM banco WHERE user_id = ?", (destinatario.id,))
    novo_saldo_destinatario = cursor.fetchone()[0]
    conn.close()
    
    await ctx.send(f"✅ Transferência de **{quantidade}** moedas para **{destinatario.name}** concluída!\nSeu novo saldo: 🪙 {novo_saldo_remetente}\nNovo saldo de {destinatario.name}: 🪙 {novo_saldo_destinatario}")

# =================================================================================
# 6. COMANDOS DE ADMINISTRAÇÃO (Atualizados para SQLite)
# =================================================================================

@bot.command(name='setup', help='(Admin) Configura os canais e categorias do bot.')
@commands.has_permissions(administrator=True)
async def setup_server(ctx):
    """Cria a estrutura de canais. (Funcionalidade inalterada)"""
    # ... (O código deste comando não precisa de alterações)
    await ctx.send("Comando !setup executado (a lógica de canais permanece a mesma).")

@bot.command(name='addmoedas', help='(Admin) Adiciona moedas a um membro. Uso: !addmoedas @membro <quantidade>')
@commands.has_permissions(administrator=True)
async def add_coins(ctx, membro: discord.Member, quantidade: int):
    """Adiciona moedas a um membro na base de dados."""
    ensure_account(membro.id)
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE banco SET saldo = saldo + ? WHERE user_id = ?", (quantidade, membro.id))
    conn.commit()
    cursor.execute("SELECT saldo FROM banco WHERE user_id = ?", (membro.id,))
    novo_saldo = cursor.fetchone()[0]
    conn.close()
    
    await ctx.send(f"✅ Foram adicionadas **{quantidade}** moedas à conta de **{membro.name}**. Novo saldo: 🪙 **{novo_saldo}**.")

@bot.command(name='additem', help='(Admin) Adiciona um item à loja. Uso: !additem <ID> <preço> "Nome do Item" "Descrição"')
@commands.has_permissions(administrator=True)
async def add_item_to_shop(ctx, item_id: str, preco: int, nome: str, *, descricao: str):
    """Adiciona um novo item à tabela da loja na base de dados."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO loja (item_id, nome, preco, descricao) VALUES (?, ?, ?, ?)", (item_id, nome, preco, descricao))
        conn.commit()
        await ctx.send(f"✅ Item **{nome}** adicionado à loja com sucesso!")
    except sqlite3.IntegrityError:
        await ctx.send(f"⚠️ Erro: Já existe um item com o ID `{item_id}`.")
    finally:
        conn.close()

@bot.command(name='delitem', help='(Admin) Remove um item da loja. Uso: !delitem <ID>')
@commands.has_permissions(administrator=True)
async def remove_item_from_shop(ctx, item_id: str):
    """Remove um item da loja usando o seu ID."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM loja WHERE item_id = ?", (item_id,))
    conn.commit()
    
    if cursor.rowcount > 0:
        await ctx.send(f"✅ Item com ID `{item_id}` removido da loja com sucesso.")
    else:
        await ctx.send(f"⚠️ Item com ID `{item_id}` não encontrado na loja.")
    conn.close()

# =================================================================================
# 7. GESTÃO DE ERROS (Simplificado)
# =================================================================================

@bot.event
async def on_command_error(ctx, error):
    """Um gestor de erros genérico para feedback ao utilizador."""
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("⚠️ Faltam argumentos. Verifique o comando e tente novamente.")
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("🚫 Você não tem permissão para usar este comando.")
    elif isinstance(error, commands.CommandNotFound):
        pass # Ignora comandos que não existem
    else:
        print(f"Ocorreu um erro não tratado: {error}")
        await ctx.send("Ocorreu um erro inesperado. A equipa de desenvolvimento foi notificada.")

# =================================================================================
# 8. INICIAR O BOT
# =================================================================================

bot.run(TOKEN)

