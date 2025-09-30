# =================================================================================
# Arauto Bank - Ficheiro Principal (main.py)
# Responsável por carregar as extensões (Cogs) e iniciar o bot.
# =================================================================================
import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import asyncio

# Carrega as variáveis de ambiente
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')

# Define as intenções (Intents) do bot
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.messages = True
intents.message_content = True
intents.reactions = True
intents.voice_states = True

class ArautoBankBot(commands.Bot):
    """Classe principal do bot, herda de commands.Bot."""
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents, case_insensitive=True)
        # Remove o comando de ajuda padrão para usar o nosso personalizado
        self.remove_command('help')

    async def setup_hook(self):
        """
        Esta função é chamada automaticamente ao iniciar o bot.
        Ela carrega todas as extensões (Cogs) da pasta 'cogs'.
        """
        print("A carregar extensões (Cogs)...")
        # Lista de cogs a serem carregados, incluindo o novo 'ajuda'
        cogs_to_load = ['economia', 'eventos', 'admin', 'ajuda']
        for cog_name in cogs_to_load:
            try:
                await self.load_extension(f'cogs.{cog_name}')
                print(f"-> Cog '{cog_name}' carregado com sucesso.")
            except Exception as e:
                print(f"ERRO: Falha ao carregar o Cog '{cog_name}'.")
                print(f"  |__ Causa: {e}")

    async def on_ready(self):
        """Evento disparado quando o bot está online e pronto."""
        print("-" * 30)
        print(f'Login bem-sucedido como {self.user.name}')
        print(f'ID do Bot: {self.user.id}')
        print(f'O Arauto Bank está online e pronto para operar!')
        print("-" * 30)

# Cria e inicia o bot
if __name__ == "__main__":
    if not TOKEN or not DATABASE_URL:
        print("ERRO CRÍTICO: Variáveis de ambiente TOKEN ou DATABASE_URL não definidas.")
    else:
        bot = ArautoBankBot()
        bot.run(TOKEN)

