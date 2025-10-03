import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import asyncio

# Carrega as variáveis de ambiente
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')

# Importa o novo gestor de base de dados
from utils.db_manager import DatabaseManager

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
        self.allowed_categories = ["🏦 ARAUTO BANK", "💸 TAXA SEMANAL"]

    async def setup_hook(self):
        print("A executar o setup_hook...")

        # Conecta o gestor de base de dados
        await self.db_manager.connect()

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
            await ctx.send(" Ocorreu um erro inesperado ao executar o comando.", delete_after=10)

    # Verificação global para restringir comandos aos canais do bot
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.channel and interaction.channel.category:
            if interaction.channel.category.name in self.allowed_categories:
                return True
        # Permite interações fora das categorias (ex: DMs), se aplicável no futuro
        return True 

    async def on_message(self, message):
        # Permite que DMs e mensagens de bots passem
        if message.guild is None or message.author.bot:
            await self.process_commands(message)
            return

        # Verifica se a mensagem está numa categoria permitida
        if message.content.startswith(self.command_prefix):
            if message.channel.category and message.channel.category.name in self.allowed_categories:
                 await self.process_commands(message)
            # Ignora comandos fora das categorias permitidas, exceto para admins
            elif message.author.guild_permissions.administrator:
                 await self.process_commands(message)
            else:
                # Opcional: informar o usuário
                # await message.channel.send("Este comando só pode ser usado nos canais do Arauto Bank.", delete_after=5)
                pass # Silenciosamente ignora
        else:
            # Processa a mensagem para eventos on_message (ex: renda por chat)
            await self.process_commands(message)

# --- Iniciar o Bot ---
if __name__ == "__main__":
    if not TOKEN or not DATABASE_URL:
        print("ERRO CRÍTICO: DISCORD_TOKEN ou DATABASE_URL não definidos no .env")
    else:
        bot = ArautoBankBot()
        bot.run(TOKEN)

