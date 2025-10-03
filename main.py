import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import asyncio

# Carrega as variáveis de ambiente
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')

# Importa os componentes de utilidades
from utils.db_manager import DatabaseManager
from utils.views import OrbeAprovacaoView, TaxaPrataView

# Define as intenções do bot
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.messages = True
intents.message_content = True
intents.voice_states = True
intents.reactions = True

# --- CHECK GLOBAL PARA RESTRIÇÃO DE CANAIS (LÓGICA CORRIGIDA) ---
async def global_channel_check(ctx):
    # 1. Admins podem usar qualquer comando em qualquer lugar. É a regra principal.
    if ctx.author.guild_permissions.administrator:
        return True
    
    # 2. O comando !setup é uma exceção e pode ser usado em qualquer lugar (a permissão de admin é verificada no próprio comando).
    if ctx.command and ctx.command.name == 'setup':
        return True
    
    # 3. Para outros usuários, o comando só funciona nas categorias permitidas.
    if ctx.guild and ctx.channel.category and ctx.channel.category.name in ctx.bot.allowed_categories:
        return True
    
    # 4. Permite comandos em DMs (mensagens privadas).
    if not ctx.guild:
        return True
        
    # Se nenhuma das condições for atendida, o comando é bloqueado silenciosamente.
    # print(f"Comando '{ctx.command}' bloqueado para {ctx.author} no canal {ctx.channel}")
    return False

class ArautoBankBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents, case_insensitive=True)
        self.db_manager = DatabaseManager(dsn=DATABASE_URL)
        self.allowed_categories = ["🏦 ARAUTO BANK", "💸 TAXA SEMANAL", "⚙️ ADMINISTRAÇÃO"]
        
        # Adiciona o check global ao bot
        self.add_check(global_channel_check)

    async def setup_hook(self):
        print("A executar o setup_hook...")
        await self.db_manager.connect()

        self.add_view(OrbeAprovacaoView(self))
        self.add_view(TaxaPrataView(self))
        print("Vistas persistentes registadas.")

        # Carrega o Admin Cog primeiro para garantir que a DB está pronta
        try:
            await self.load_extension('cogs.admin')
            admin_cog = self.get_cog('Admin')
            if admin_cog:
                print("A inicializar o esquema da base de dados...")
                await admin_cog.initialize_database_schema()
            else:
                 raise Exception("Não foi possível carregar o Cog de Admin.")
        except Exception as e:
            print(f"ERRO CRÍTICO ao carregar ou inicializar o Admin Cog: {e}")
            return # Impede o bot de continuar se a DB falhar

        # Carrega os outros cogs
        cogs_to_load = [
            'cogs.economia', 'cogs.eventos', 'cogs.loja', 
            'cogs.taxas', 'cogs.engajamento', 'cogs.orbes', 'cogs.utilidades'
        ]

        for cog_name in cogs_to_load: 
            try:
                await self.load_extension(cog_name)
                print(f"Cog '{cog_name}' carregado com sucesso.")
            except Exception as e:
                print(f"ERRO ao carregar o cog '{cog_name}': {e}")
        
        print("Setup_hook concluído.")

    async def on_ready(self):
        print(f'Login bem-sucedido como {self.user.name} (ID: {self.user.id})')
        print('------')

    async def on_command_error(self, ctx, error):
        # Ignora erros que são tratados (comandos não encontrados, falhas de permissão)
        if isinstance(error, (commands.CommandNotFound, commands.CheckFailure)):
            return
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"❌ Faltam argumentos. Use `!help {ctx.command.name}` para ver como usar o comando.", delete_after=10)
        else:
            print(f"Erro num comando: {ctx.command}: {error}")
            # Opcional: enviar uma mensagem genérica de erro para o utilizador
            # await ctx.send("Ocorreu um erro inesperado ao processar o comando.", delete_after=10)


# --- Iniciar o Bot ---
if __name__ == "__main__":
    if not TOKEN or not DATABASE_URL:
        print("ERRO CRÍTICO: DISCORD_TOKEN ou DATABASE_URL não definidos no .env")
    else:
        bot = ArautoBankBot()
        bot.run(TOKEN)

