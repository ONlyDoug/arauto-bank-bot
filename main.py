import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import asyncio

# Carrega as variáveis de ambiente
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')

# Importa o gestor de base de dados e as Vistas a partir do novo ficheiro de utilidades
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

class ArautoBankBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents, case_insensitive=True)
        self.db_manager = DatabaseManager(dsn=DATABASE_URL)
        self.allowed_categories = ["🏦 ARAUTO BANK", "💸 TAXA SEMANAL", "⚙️ ADMINISTração"]

    async def setup_hook(self):
        print("A executar o setup_hook...")
        await self.db_manager.connect()

        # Adiciona as Vistas persistentes
        self.add_view(OrbeAprovacaoView(self))
        self.add_view(TaxaPrataView(self))
        print("Vistas persistentes registadas.")

        # Carrega os cogs
        cogs_to_load = [
            'cogs.admin', 'cogs.economia', 'cogs.eventos', 'cogs.loja', 
            'cogs.taxas', 'cogs.engajamento', 'cogs.orbes', 'cogs.utilidades'
        ]
        # Carrega o Admin primeiro para garantir que a DB está pronta
        await self.load_extension('cogs.admin')
        admin_cog = self.get_cog('Admin')
        if admin_cog:
            print("A inicializar o esquema da base de dados...")
            await admin_cog.initialize_database_schema()

        for cog in cogs_to_load[1:]: # Carrega o resto
            try:
                await self.load_extension(cog)
                print(f"Cog '{cog}' carregado com sucesso.")
            except Exception as e:
                print(f"ERRO ao carregar o cog '{cog}': {e}")
        
        print("Setup_hook concluído.")

    async def on_ready(self):
        print(f'Login bem-sucedido como {self.user.name} (ID: {self.user.id})')
        print('------')

    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.CheckFailure):
            return
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"❌ Faltam argumentos. Use `!help {ctx.command.name}` para ver como usar o comando.", delete_after=10)
        else:
            print(f"Erro num comando: {ctx.command}: {error}")

    async def on_message(self, message):
        if message.author.bot:
            return

        ctx = await self.get_context(message)
        if ctx.command:
            if message.guild is None:
                await self.process_commands(message)
                return

            is_admin = ctx.author.guild_permissions.administrator
            is_allowed_category = ctx.channel.category and ctx.channel.category.name in self.allowed_categories
            
            if is_allowed_category or is_admin:
                await self.process_commands(message)
            else:
                return
        else:
            await self.process_commands(message)

# --- Iniciar o Bot ---
if __name__ == "__main__":
    if not TOKEN or not DATABASE_URL:
        print("ERRO CRÍTICO: DISCORD_TOKEN ou DATABASE_URL não definidos no .env")
    else:
        bot = ArautoBankBot()
        bot.run(TOKEN)

