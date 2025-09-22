"""
Ficheiro principal do Arauto Bank.

Este ficheiro contém toda a lógica para o bot do Discord, incluindo a inicialização,
conexão com a API do Discord, gestão de dados de utilizadores e da loja,
e a definição de todos os comandos disponíveis para utilizadores e administradores.
"""

# =================================================================================
# 1. IMPORTAÇÕES E CONFIGURAÇÃO INICIAL
# =================================================================================

import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import json

# Carrega as variáveis de ambiente do ficheiro .env para o sistema.
# Isto permite-nos aceder ao token do bot de forma segura.
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# Define as "Intents" (intenções) do bot.
# As Intents dão permissões ao bot para aceder a certos tipos de eventos.
# - members: para eventos de entrada/saída de membros.
# - message_content: para ler o conteúdo das mensagens (necessário para comandos).
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

# Define os caminhos para os nossos ficheiros de "base de dados" em formato JSON.
BANK_DATA_FILE = "bank_data.json"
LOJA_DATA_FILE = "loja_data.json"

# =================================================================================
# 2. FUNÇÕES DE GESTÃO DE DADOS (JSON)
# =================================================================================

def load_data(file_path):
    """
    Carrega dados de um ficheiro JSON.

    Tenta ler e interpretar um ficheiro JSON. Se o ficheiro não existir ou estiver
    vazio/corrompido, retorna um dicionário vazio.

    :param file_path: O caminho para o ficheiro JSON.
    :return: Um dicionário com os dados carregados.
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Caso especial: as chaves do dicionário do banco são IDs de utilizador.
            # O JSON guarda-as como strings, mas nós precisamos delas como inteiros.
            if file_path == BANK_DATA_FILE:
                return {int(k): v for k, v in data.items()}
            return data
    except (FileNotFoundError, json.JSONDecodeError):
        # Se o ficheiro não existir ou for inválido, começamos do zero.
        return {}

def save_data(data, file_path):
    """
    Guarda dados num ficheiro JSON.

    Escreve o dicionário fornecido para um ficheiro JSON de forma formatada.

    :param data: O dicionário de dados a ser guardado.
    :param file_path: O caminho para o ficheiro JSON de destino.
    """
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)

# =================================================================================
# 3. INICIALIZAÇÃO DO BOT E CARREGAMENTO DE DADOS
# =================================================================================

# Carrega os dados dos ficheiros para a memória quando o bot é iniciado.
bank_data = load_data(BANK_DATA_FILE)
loja_data = load_data(LOJA_DATA_FILE)

# Cria a instância principal do Bot, definindo o prefixo dos comandos e as intents.
bot = commands.Bot(command_prefix='!', intents=intents)

def ensure_account(member_id):
    """
    Garante que um utilizador tem uma conta no banco.

    Se o ID do membro não existir na base de dados, cria uma nova entrada com saldo 0
    e guarda a alteração no ficheiro JSON.

    :param member_id: O ID do membro do Discord.
    """
    if member_id not in bank_data:
        bank_data[member_id] = 0
        save_data(bank_data, BANK_DATA_FILE)
        print(f'Conta criada sob demanda para o ID: {member_id}')

# =================================================================================
# 4. EVENTOS DO BOT
# =================================================================================

@bot.event
async def on_ready():
    """
    Evento disparado quando o bot se conecta com sucesso ao Discord.
    """
    print(f'Login bem-sucedido como {bot.user.name}')
    print(f'Dados do banco carregados com {len(bank_data)} contas.')
    print(f'Dados da loja carregados com {len(loja_data)} itens.')
    print('O Arauto Bank está online e pronto para operar!')
    print('------')

@bot.event
async def on_member_join(member):
    """
    Evento disparado quando um novo membro entra no servidor.
    Cria automaticamente uma conta no banco para ele.
    """
    ensure_account(member.id)
    print(f'Conta criada para o novo membro: {member.name} (ID: {member.id})')

# =================================================================================
# 5. COMANDOS DE UTILIZADOR
# =================================================================================

@bot.command(name='ola', help='O bot cumprimenta o utilizador.')
async def hello(ctx):
    """Um simples comando de "olá" para testar a resposta do bot."""
    await ctx.send(f'Olá, {ctx.author.name}! Eu sou o Arauto Bank, pronto para servir.')

@bot.command(name='saldo', help='Exibe o saldo de moedas do utilizador.')
async def balance(ctx):
    """Verifica e exibe o saldo do utilizador que executou o comando."""
    ensure_account(ctx.author.id)
    user_balance = bank_data[ctx.author.id]
    
    embed = discord.Embed(
        title=f"Saldo de {ctx.author.name}",
        description="O seu saldo atual no Arauto Bank é de:",
        color=discord.Color.gold()
    )
    embed.add_field(name="Moedas", value=f"🪙 {user_balance}", inline=False)
    embed.set_footer(text="Arauto Bank | Economia da Guilda")
    await ctx.send(embed=embed)

@bot.command(name='loja', help='Mostra os itens disponíveis na loja de recompensas.')
async def shop(ctx):
    """Exibe todos os itens da loja num embed formatado."""
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

@bot.command(name='comprar', help='Compra um item da loja. Uso: !comprar <ID do item>')
async def buy_item(ctx, item_id: str):
    """
    Processa a compra de um item da loja.
    
    Verifica se o item existe, se o utilizador tem saldo suficiente,
    deduz o valor e notifica a staff para a entrega do item.
    """
    comprador = ctx.author
    ensure_account(comprador.id)

    if item_id not in loja_data:
        await ctx.send(f"Desculpe, o item com ID `{item_id}` não foi encontrado na loja.")
        return

    item = loja_data[item_id]
    preco_item = item.get('preco')

    if preco_item is None:
        await ctx.send(f"O item `{item.get('nome')}` não tem um preço definido. Por favor, contacte um administrador.")
        return
        
    if bank_data[comprador.id] < preco_item:
        await ctx.send(f"Saldo insuficiente para comprar **{item.get('nome')}**. Você precisa de 🪙 {preco_item}, mas tem apenas 🪙 {bank_data[comprador.id]}.")
        return

    # Se todas as verificações passarem, processa a compra
    bank_data[comprador.id] -= preco_item
    save_data(bank_data, BANK_DATA_FILE)

    # Envia confirmação ao comprador
    embed_confirmacao = discord.Embed(
        title="✅ Compra Realizada com Sucesso!",
        description=f"Você comprou **{item.get('nome')}** por **{preco_item}** moedas.",
        color=discord.Color.green()
    )
    embed_confirmacao.add_field(name="Seu Novo Saldo", value=f"🪙 {bank_data[comprador.id]}")
    embed_confirmacao.set_footer(text="A staff foi notificada e irá entregar o seu item em breve.")
    await ctx.send(embed=embed_confirmacao)

    # Envia notificação para a staff
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
        await ctx.send(f"Aviso para {ctx.author.mention}: Não foi possível encontrar o canal de resgates da staff (`{canal_staff_nome}`). Por favor, avise um administrador sobre a sua compra.")

@bot.command(name='transferir', help='Transfere moedas para outro membro. Uso: !transferir @membro <quantidade>')
async def transfer_coins(ctx, destinatario: discord.Member, quantidade: int):
    """
    Transfere uma quantia de moedas do autor do comando para outro membro.
    
    Realiza várias verificações: se o destinatário é válido, se a quantidade é positiva,
    e se o remetente tem saldo suficiente.
    """
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

    # Processa a transferência
    bank_data[remetente.id] -= quantidade
    bank_data[destinatario.id] += quantidade
    save_data(bank_data, BANK_DATA_FILE)
    
    embed = discord.Embed(
        title="Transferência Realizada com Sucesso",
        description=f"**{remetente.name}** transferiu **{quantidade}** moedas para **{destinatario.name}**.",
        color=discord.Color.blue()
    )
    embed.add_field(name=f"Saldo de {remetente.name}", value=f"🪙 {bank_data[remetente.id]}", inline=True)
    embed.add_field(name=f"Saldo de {destinatario.name}", value=f"🪙 {bank_data[destinatario.id]}", inline=True)
    embed.set_footer(text="Arauto Bank | As suas finanças seguras")
    await ctx.send(embed=embed)

# =================================================================================
# 6. COMANDOS DE ADMINISTRAÇÃO
# =================================================================================

@bot.command(name='setup', help='(Admin) Configura as categorias e canais necessários para o bot.')
@commands.has_permissions(administrator=True)
async def setup_server(ctx):
    """Cria a estrutura de canais e categorias para o funcionamento do bot."""
    guild = ctx.guild
    await ctx.send(f'Iniciando a configuração do Arauto Bank no servidor {guild.name}...')
    
    category_name = "🪙 BANCO ARAUTO 🪙"
    category = discord.utils.get(guild.categories, name=category_name)
    if not category:
        await ctx.send(f'Criando a categoria: {category_name}')
        category = await guild.create_category(category_name)
    else:
        await ctx.send(f'Categoria {category_name} já existe.')
        
    # Estrutura de canais a serem criados
    channels_to_create = [
        {'name': '📜-regras-e-infos', 'private': False},
        {'name': '💰-saldo-e-extrato', 'private': False},
        {'name': '🎁-loja-de-recompensas', 'private': False},
        {'name': '🚨-staff-resgates', 'private': True}
    ]

    for channel_info in channels_to_create:
        channel_name = channel_info['name']
        is_private = channel_info['private']
        
        existing_channel = discord.utils.get(guild.text_channels, name=channel_name, category=category)
        if not existing_channel:
            if is_private:
                await ctx.send(f'Criando canal privado: #{channel_name}')
                # Permissões para canal privado (só a staff vê)
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(read_messages=False),
                    guild.me: discord.PermissionOverwrite(read_messages=True)
                }
                staff_role = discord.utils.get(guild.roles, name="Staff")
                if staff_role:
                    overwrites[staff_role] = discord.PermissionOverwrite(read_messages=True)
                await guild.create_text_channel(channel_name, category=category, overwrites=overwrites)
            else:
                await ctx.send(f'Criando canal público: #{channel_name}')
                await guild.create_text_channel(channel_name, category=category)
        else:
            await ctx.send(f'Canal #{channel_name} já existe.')
            
    await ctx.send('✅ Configuração do servidor concluída com sucesso!')

@bot.command(name='addmoedas', help='(Admin) Adiciona moedas à conta de um membro. Uso: !addmoedas @membro <quantidade>')
@commands.has_permissions(administrator=True)
async def add_coins(ctx, membro: discord.Member, quantidade: int):
    """Adiciona uma certa quantidade de moedas ao saldo de um membro."""
    ensure_account(membro.id)
    bank_data[membro.id] += quantidade
    save_data(bank_data, BANK_DATA_FILE)
    
    embed = discord.Embed(
        title="Transação Concluída",
        description=f"Foram adicionadas **{quantidade}** moedas à conta de **{membro.name}**.",
        color=discord.Color.green()
    )
    embed.add_field(name="Novo Saldo", value=f"🪙 {bank_data[membro.id]}", inline=False)
    embed.set_footer(text=f"Transação realizada por: {ctx.author.name}")
    await ctx.send(embed=embed)

# =================================================================================
# 7. GESTÃO DE ERROS DOS COMANDOS
# =================================================================================

@buy_item.error
async def buy_item_error(ctx, error):
    """Trata erros específicos para o comando !comprar."""
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send('Uso incorreto. Formato: `!comprar <ID do item>`')
    else:
        print(f"Erro no comando !comprar: {error}")
        await ctx.send('Ocorreu um erro inesperado ao processar a sua compra.')

@transfer_coins.error
async def transfer_coins_error(ctx, error):
    """Trata erros específicos para o comando !transferir."""
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send('Uso incorreto. Formato: `!transferir @destinatario <quantidade>`')
    elif isinstance(error, commands.BadArgument):
        await ctx.send('Não consegui encontrar esse membro. Por favor, mencione um membro válido do servidor.')
    else:
        print(f"Erro no comando !transferir: {error}")
        await ctx.send('Ocorreu um erro inesperado ao processar a transferência.')

@add_coins.error
async def add_coins_error(ctx, error):
    """Trata erros específicos para o comando !addmoedas."""
    if isinstance(error, commands.MissingPermissions):
        await ctx.send('Você não tem permissão de Administrador para usar este comando.')
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send('Uso incorreto. Formato: `!addmoedas @membro <quantidade>`')
    elif isinstance(error, commands.BadArgument):
        await ctx.send('Não consegui encontrar esse membro. Por favor, mencione um membro válido do servidor.')
    else:
        print(f"Erro no comando !addmoedas: {error}")
        await ctx.send(f'Ocorreu um erro inesperado.')
        
@setup_server.error
async def setup_server_error(ctx, error):
    """Trata erros específicos para o comando !setup."""
    if isinstance(error, commands.MissingPermissions):
        await ctx.send('Você não tem permissão de Administrador para usar este comando.')
    else:
        print(f"Erro no comando !setup: {error}")
        await ctx.send(f'Ocorreu um erro inesperado.')

# =================================================================================
# 8. INICIAR O BOT
# =================================================================================

# Esta é a linha final que efetivamente liga o bot, usando o token.
bot.run(TOKEN)
