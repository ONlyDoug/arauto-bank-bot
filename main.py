import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import asyncio

# Carrega as variáveis de ambiente
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')

# Importa o gestor de base de dados e as Vistas Persistentes
from utils.db_manager import DatabaseManager
from cogs.orbes import OrbeAprovacaoView
from cogs.taxas import TaxaPrataView

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
        # Inicializa o gestor de DB
        self.db_manager = DatabaseManager(dsn=DATABASE_URL)
        self.allowed_categories = ["🏦 ARAUTO BANK", "💸 TAXA SEMANAL", "⚙️ ADMINISTRAÇÃO"]

    async def setup_hook(self):
        print("A executar o setup_hook...")

        # Conecta o gestor de base de dados
        await self.db_manager.connect()

        # Adiciona as Vistas persistentes para que os botões funcionem após reinicializações
        self.add_view(OrbeAprovacaoView(self))
        self.add_view(TaxaPrataView(self))
        print("Vistas persistentes registadas.")

        # Carrega o Cog de Admin primeiro para a inicialização da DB
        await self.load_extension('cogs.admin')
        admin_cog = self.get_cog('Admin')
        if admin_cog:
            print("A inicializar o esquema da base de dados...")
            await admin_cog.initialize_database_schema()
        
        # Carrega todos os outros cogs
        cogs_to_load = [
            'cogs.economia', 'cogs.eventos', 'cogs.loja', 'cogs.taxas',
            'cogs.engajamento', 'cogs.orbes', 'cogs.utilidades'
        ]
        for cog in cogs_to_load:
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
        elif isinstance(error, commands.CheckFailure):
            # A mensagem de "sem permissão" já é tratada no decorador
            return
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"❌ Faltam argumentos. Use `!help {ctx.command.name}` para ver como usar o comando.", delete_after=10)
        else:
            print(f"Erro num comando: {ctx.command}: {error}")
            # await ctx.send(" Ocorreu um erro inesperado ao executar o comando.", delete_after=10)

    # Verificação global para restringir comandos aos canais do bot
    async def on_message(self, message):
        if message.author.bot:
            return

        ctx = await self.get_context(message)
        if ctx.command:
            # Permite que DMs passem
            if message.guild is None:
                await self.process_commands(message)
                return

            # Verifica se o canal está na categoria permitida ou se o user é admin
            is_admin = ctx.author.guild_permissions.administrator
            is_allowed_category = ctx.channel.category and ctx.channel.category.name in self.allowed_categories
            
            if is_allowed_category or is_admin:
                await self.process_commands(message)
            else:
                # Silenciosamente ignora o comando
                return 
        else:
            # Permite que eventos on_message (ex: renda por chat) funcionem em qualquer canal
            # O próprio evento on_message no cog fará a verificação se necessário
            await self.process_commands(message)


# --- Iniciar o Bot ---
if __name__ == "__main__":
    if not TOKEN or not DATABASE_URL:
        print("ERRO CRÍTICO: DISCORD_TOKEN ou DATABASE_URL não definidos no .env")
    else:
        bot = ArautoBankBot()
        bot.run(TOKEN)

