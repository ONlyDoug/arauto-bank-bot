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

class ArautoBankBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents, case_insensitive=True)
        # Inicializa o gestor de DB central
        self.db_manager = DatabaseManager(dsn=DATABASE_URL)
        self.allowed_categories = ["🏦 ARAUTO BANK", "💸 TAXA SEMANAL", "⚙️ ADMINISTRAÇÃO"]

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
        
        # Carrega o Admin primeiro para que a função de inicialização da DB exista
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
            return

        # Carrega os Cogs restantes
        for cog_name in cogs_to_load[1:]: 
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
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.CheckFailure):
            return
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"❌ Faltam argumentos. Use `!help {ctx.command.name}` para ver como usar o comando.", delete_after=10)
        else:
            print(f"Erro num comando: {ctx.command}: {error}")
            # Descomente a linha abaixo para feedback no Discord (útil em produção)
            # await ctx.send("Ocorreu um erro inesperado. A equipa de desenvolvimento foi notificada.", ephemeral=True)


    async def on_message(self, message):
        if message.author.bot:
            return

        ctx = await self.get_context(message)
        if ctx.command:
            # Processa DMs normalmente
            if message.guild is None:
                await self.process_commands(message)
                return

            # Verifica se o autor é admin ou se o canal está numa categoria permitida
            is_admin = ctx.author.guild_permissions.administrator
            is_allowed_category = ctx.channel.category and ctx.channel.category.name in self.allowed_categories
            
            if is_allowed_category or is_admin:
                await self.process_commands(message)
            else:
                # Silenciosamente ignora o comando fora dos canais designados
                return
        else:
            # Permite que eventos on_message (ex: renda por chat) continuem a funcionar
            await self.process_commands(message)

# --- Iniciar o Bot ---
if __name__ == "__main__":
    if not TOKEN or not DATABASE_URL:
        print("ERRO CRÍTICO: DISCORD_TOKEN ou DATABASE_URL não definidos no .env")
    else:
        bot = ArautoBankBot()
        bot.run(TOKEN)

