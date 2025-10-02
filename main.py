import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import psycopg2.pool
import asyncio

# Carrega as variáveis de ambiente
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')

# Lista de Cogs a serem carregados
COGS_A_CARREGAR = [
    'cogs.economia',
    'cogs.eventos',
    'cogs.loja',
    'cogs.taxas',
    'cogs.engajamento',
    'cogs.orbes',
    'cogs.utilidades'
]

class ArautoBankBot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.db_pool = None

    async def setup_hook(self):
        """Gancho assíncrono que é executado antes do bot fazer login."""
        print("A executar o setup_hook...")
        
        # 1. Inicializar o pool de conexões com a base de dados
        try:
            self.db_pool = psycopg2.pool.SimpleConnectionPool(1, 20, dsn=DATABASE_URL)
            if self.db_pool:
                print("Pool de conexões com a base de dados inicializado com sucesso.")
        except Exception as e:
            print(f"ERRO CRÍTICO ao inicializar o pool de conexões: {e}")
            await self.close()
            return

        # 2. Carregar o Cog de Admin primeiro
        try:
            await self.load_extension('cogs.admin')
            print("Cog 'cogs.admin' carregado com sucesso.")
        except Exception as e:
            print(f"ERRO CRÍTICO ao carregar 'cogs.admin': {e}")
            await self.close()
            return
            
        # 3. Inicializar o esquema da base de dados automaticamente
        admin_cog = self.get_cog('Admin')
        if admin_cog:
            print("A inicializar o esquema da base de dados...")
            await admin_cog.initialize_database_schema()
        else:
            print("ERRO CRÍTICO: Não foi possível obter o Cog de Admin para inicializar a base de dados.")
            await self.close()
            return

        # 4. Carregar os restantes Cogs
        for cog in COGS_A_CARREGAR:
            try:
                await self.load_extension(cog)
                print(f"Cog '{cog}' carregado com sucesso.")
            except Exception as e:
                print(f"ERRO ao carregar o cog '{cog}': {e}")

    async def on_ready(self):
        print(f'Login bem-sucedido como {self.user.name} (ID: {self.user.id})')
        print('------')

    async def close(self):
        """Fecha as conexões antes de desligar o bot."""
        if self.db_pool:
            self.db_pool.closeall()
            print("Pool de conexões com a base de dados fechado.")
        await super().close()

def main():
    if not TOKEN or not DATABASE_URL:
        print("ERRO CRÍTICO: As variáveis de ambiente DISCORD_TOKEN e DATABASE_URL são obrigatórias.")
        return

    # Define as intenções do bot
    intents = discord.Intents.default()
    intents.guilds = True
    intents.members = True
    intents.messages = True
    intents.message_content = True
    intents.reactions = True
    intents.voice_states = True

    # Cria a instância do bot
    bot = ArautoBankBot(command_prefix='!', intents=intents, case_insensitive=True)
    
    # Inicia o bot
    bot.run(TOKEN)

if __name__ == '__main__':
    main()

