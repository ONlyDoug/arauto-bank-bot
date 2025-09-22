# PASSO 1: Importar as bibliotecas necessárias
import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import json

# PASSO 2: Carregar as variáveis de ambiente
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# PASSO 3: Configurar as "Intents"
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

# Caminhos para os nossos ficheiros de "base de dados"
BANK_DATA_FILE = "bank_data.json"
LOJA_DATA_FILE = "loja_data.json"

# PASSO 4: Funções para carregar e guardar os dados
def load_data(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if file_path == BANK_DATA_FILE:
                return {int(k): v for k, v in data.items()}
            return data
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_data(data, file_path):
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)

# Carregamos os dados quando o script começa
bank_data = load_data(BANK_DATA_FILE)
loja_data = load_data(LOJA_DATA_FILE)

# PASSO 5: Criar uma instância do Bot
bot = commands.Bot(command_prefix='!', intents=intents)

# PASSO 6: Evento 'on_ready'
@bot.event
async def on_ready():
    print(f'Login bem-sucedido como {bot.user.name}')
    print(f'Dados do banco carregados com {len(bank_data)} contas.')
    print(f'Dados da loja carregados com {len(loja_data)} itens.')
    print('O Arauto Bank está online e pronto para operar!')
    print('------')

# Função auxiliar para garantir que um utilizador tem uma conta
def ensure_account(member_id):
    if member_id not in bank_data:
        bank_data[member_id] = 0
        save_data(bank_data, BANK_DATA_FILE)
        print(f'Conta criada sob demanda para o ID: {member_id}')

# PASSO 7: Comando '!loja'
@bot.command(name='loja')
async def shop(ctx):
    embed = discord.Embed(
        title="🎁 Loja de Recompensas do Arauto Bank 🎁",
        description="Aqui estão os itens que pode comprar com as suas moedas:",
        color=discord.Color.purple()
    )
    if not loja_data:
        embed.description = "A loja está vazia no momento. Volte mais tarde!"
    else:
        for item_id, item_info in loja_data.items():
            nome = item_info.get('nome', 'Item sem nome')
            preco = item_info.get('preco', 'Preço indisponível')
            descricao = item_info.get('descricao', 'Sem descrição.')
            embed.add_field(name=f"ID: {item_id} | {nome} - 🪙 {preco} moedas", value=descricao, inline=False)
    embed.set_footer(text="Para comprar, use o comando !comprar <ID do item>")
    await ctx.send(embed=embed)

# --- NOVO CÓDIGO ADICIONADO ---

# PASSO 8: Comando '!comprar'
@bot.command(name='comprar')
async def buy_item(ctx, item_id: str):
    comprador = ctx.author
    ensure_account(comprador.id)

    # Verificar se o item existe na loja
    if item_id not in loja_data:
        await ctx.send(f"Desculpe, o item com ID `{item_id}` não foi encontrado na loja.")
        return

    item = loja_data[item_id]
    preco_item = item.get('preco')

    # Verificar se o preço é um número válido
    if preco_item is None:
        await ctx.send(f"O item `{item.get('nome')}` não tem um preço definido. Por favor, contacte um administrador.")
        return
        
    # Verificar se o comprador tem saldo suficiente
    if bank_data[comprador.id] < preco_item:
        await ctx.send(f"Saldo insuficiente para comprar **{item.get('nome')}**. Você precisa de 🪙 {preco_item}, mas tem apenas 🪙 {bank_data[comprador.id]}.")
        return

    # Processar a compra
    bank_data[comprador.id] -= preco_item
    save_data(bank_data, BANK_DATA_FILE)

    # Enviar confirmação ao comprador
    embed_confirmacao = discord.Embed(
        title="✅ Compra Realizada com Sucesso!",
        description=f"Você comprou **{item.get('nome')}** por **{preco_item}** moedas.",
        color=discord.Color.green()
    )
    embed_confirmacao.add_field(name="Seu Novo Saldo", value=f"🪙 {bank_data[comprador.id]}")
    embed_confirmacao.set_footer(text="A staff foi notificada e irá entregar o seu item em breve.")
    await ctx.send(embed=embed_confirmacao)

    # Enviar notificação para a staff
    canal_staff_nome = '🚨-staff-resgates'
    canal_staff = discord.utils.get(ctx.guild.text_channels, name=canal_staff_nome)
    if canal_staff:
        embed_staff = discord.Embed(
            title="📢 Nova Compra para Resgate!",
            description=f"O membro **{comprador.name}** comprou um item e aguarda a entrega.",
            color=discord.Color.orange()
        )
        embed_staff.add_field(name="Membro", value=comprador.mention, inline=True)
        embed_staff.add_field(name="Item Comprado", value=item.get('nome'), inline=True)
        embed_staff.add_field(name="ID do Item", value=item_id, inline=True)
        await canal_staff.send(embed=embed_staff)
    else:
        # Mensagem de fallback se o canal de staff não for encontrado
        await ctx.send("Aviso: Não foi possível encontrar o canal de resgates da staff. Por favor, avise um administrador sobre a sua compra.")

@buy_item.error
async def buy_item_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send('Uso incorreto. Formato: `!comprar <ID do item>`')
    else:
        await ctx.send(f'Ocorreu um erro inesperado: {error}')

# --- FIM DO NOVO CÓDIGO ---

# PASSO 9: Evento 'on_member_join'
@bot.event
async def on_member_join(member):
    ensure_account(member.id)
    print(f'Conta criada para o novo membro: {member.name} (ID: {member.id})')

# PASSO 10: Comando '!saldo'
@bot.command(name='saldo')
async def balance(ctx):
    ensure_account(ctx.author.id)
    user_balance = bank_data[ctx.author.id]
    embed = discord.Embed(title=f"Saldo de {ctx.author.name}", description=f"O seu saldo atual no Arauto Bank é de:", color=discord.Color.gold())
    embed.add_field(name="Moedas", value=f"🪙 {user_balance}", inline=False)
    embed.set_footer(text="Arauto Bank | Economia da Guilda")
    await ctx.send(embed=embed)

# PASSO 11: Comando '!addmoedas'
@bot.command(name='addmoedas')
@commands.has_permissions(administrator=True)
async def add_coins(ctx, membro: discord.Member, quantidade: int):
    ensure_account(membro.id)
    bank_data[membro.id] += quantidade
    save_data(bank_data, BANK_DATA_FILE)
    embed = discord.Embed(title="Transação Concluída", description=f"Foram adicionadas **{quantidade}** moedas à conta de **{membro.name}**.", color=discord.Color.green())
    embed.add_field(name="Novo Saldo", value=f"🪙 {bank_data[membro.id]}", inline=False)
    embed.set_footer(text=f"Transação realizada por: {ctx.author.name}")
    await ctx.send(embed=embed)

@add_coins.error
async def add_coins_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send('Você não tem permissão de Administrador para usar este comando.')
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send('Uso incorreto. Formato: `!addmoedas @membro <quantidade>`')
    elif isinstance(error, commands.BadArgument):
        await ctx.send('Não consegui encontrar esse membro. Por favor, mencione um membro válido do servidor.')
    else:
        await ctx.send(f'Ocorreu um erro: {error}')

# PASSO 12: Comando '!transferir'
@bot.command(name='transferir')
async def transfer_coins(ctx, destinatario: discord.Member, quantidade: int):
    remetente = ctx.author
    if destinatario == remetente:
        await ctx.send("Você não pode transferir moedas para si mesmo.")
        return
    if quantidade <= 0:
        await ctx.send("A quantidade a transferir deve ser um número positivo.")
        return
    ensure_account(remetente.id)
    ensure_account(destinatario.id)
    if bank_data[remetente.id] < quantidade:
        await ctx.send(f"Saldo insuficiente. Você tem apenas 🪙 {bank_data[remetente.id]} moedas.")
        return
    bank_data[remetente.id] -= quantidade
    bank_data[destinatario.id] += quantidade
    save_data(bank_data, BANK_DATA_FILE)
    embed = discord.Embed(title="Transferência Realizada com Sucesso", description=f"**{remetente.name}** transferiu **{quantidade}** moedas para **{destinatario.name}**.", color=discord.Color.blue())
    embed.add_field(name=f"Saldo de {remetente.name}", value=f"🪙 {bank_data[remetente.id]}", inline=True)
    embed.add_field(name=f"Saldo de {destinatario.name}", value=f"🪙 {bank_data[destinatario.id]}", inline=True)
    embed.set_footer(text="Arauto Bank | As suas finanças seguras")
    await ctx.send(embed=embed)

@transfer_coins.error
async def transfer_coins_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send('Uso incorreto. Formato: `!transferir @destinatario <quantidade>`')
    elif isinstance(error, commands.BadArgument):
        await ctx.send('Não consegui encontrar esse membro. Por favor, mencione um membro válido do servidor.')
    else:
        await ctx.send(f'Ocorreu um erro inesperado: {error}')

# PASSO 13: Comandos de teste e setup
@bot.command(name='ola')
async def hello(ctx):
    await ctx.send(f'Olá, {ctx.author.name}! Eu sou o Arauto Bank, pronto para servir.')

@bot.command(name='setup')
@commands.has_permissions(administrator=True)
async def setup_server(ctx):
    guild = ctx.guild
    await ctx.send(f'Iniciando a configuração do Arauto Bank no servidor {guild.name}...')
    category_name = "🪙 BANCO ARAUTO 🪙"
    category = discord.utils.get(guild.categories, name=category_name)
    if not category:
        await ctx.send(f'Criando a categoria: {category_name}')
        category = await guild.create_category(category_name)
    else:
        await ctx.send(f'Categoria {category_name} já existe.')
    channels_to_create = [
        '📜-regras-e-infos', '💰-saldo-e-extrato', '🎁-loja-de-recompensas',
        {'name': '🚨-staff-resgates', 'private': True}
    ]
    for channel_data in channels_to_create:
        if isinstance(channel_data, dict):
            channel_name = channel_data['name']
            existing_channel = discord.utils.get(guild.text_channels, name=channel_name)
            if not existing_channel:
                await ctx.send(f'Criando canal privado: #{channel_name}')
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(read_messages=False),
                    guild.me: discord.PermissionOverwrite(read_messages=True)
                }
                # Garante que a staff pode ver
                staff_role = discord.utils.get(guild.roles, name="Staff") # Assumindo que tem um cargo "Staff"
                if staff_role:
                    overwrites[staff_role] = discord.PermissionOverwrite(read_messages=True)
                await guild.create_text_channel(channel_name, category=category, overwrites=overwrites)
            else:
                await ctx.send(f'Canal #{channel_name} já existe.')
        else:
            channel_name = channel_data
            existing_channel = discord.utils.get(guild.text_channels, name=channel_name)
            if not existing_channel:
                await ctx.send(f'Criando canal público: #{channel_name}')
                await guild.create_text_channel(channel_name, category=category)
            else:
                await ctx.send(f'Canal #{channel_name} já existe.')
    await ctx.send('✅ Configuração do servidor concluída com sucesso!')

@setup_server.error
async def setup_server_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send('Você não tem permissão de Administrador para usar este comando.')

# PASSO 14: Iniciar o bot
bot.run(TOKEN)

