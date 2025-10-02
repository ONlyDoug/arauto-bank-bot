import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import psycopg2.pool
import asyncio

# --- Configuração Inicial ---

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.messages = True
intents.message_content = True
intents.voice_states = True
intents.reactions = True

class ArautoBankBot(commands.Bot):
def **init**(self):
super().**init**(command_prefix='!', intents=intents, case_insensitive=True)
self.db_pool = None
self.initial_extensions = [
'cogs.admin', 'cogs.economia', 'cogs.eventos', 'cogs.loja',
'cogs.taxas', 'cogs.engajamento', 'cogs.orbes', 'cogs.utilidades'
]

    async def setup_hook(self):
        print("A executar o setup_hook...")
        try:
            self.db_pool = psycopg2.pool.SimpleConnectionPool(1, 20, dsn=DATABASE_URL)
            print("Pool de conexões com a base de dados inicializado com sucesso.")
        except Exception as e:
            print(f"ERRO CRÍTICO ao inicializar o pool de conexões: {e}")
            return

        # Carrega o admin primeiro para inicializar a BD
        await self.load_extension('cogs.admin')
        admin_cog = self.get_cog('Admin')
        if admin_cog:
            print("A inicializar o esquema da base de dados...")
            await admin_cog.initialize_database_schema()

        # Carrega as outras extensões
        for extension in self.initial_extensions:
            if extension == 'cogs.admin': continue
            try:
                await self.load_extension(extension)
                print(f"Cog '{extension}' carregado com sucesso.")
            except Exception as e:
                print(f"Falha ao carregar o cog {extension}: {e}")

        # Adiciona a verificação global de canais
        self.add_check(self.check_channel)

    async def on_ready(self):
        print(f'Login bem-sucedido como {self.user} (ID: {self.user.id})')
        print('------')

    # Verificação global para restringir comandos aos canais do bot
    async def check_channel(self, ctx):
        # Comandos que podem ser usados em qualquer lugar
        allowed_anywhere = ['setup', 'initdb', 'status']
        if ctx.command and ctx.command.name in allowed_anywhere:
            return True

        if ctx.guild:
            # Nomes das categorias onde os comandos são permitidos
            allowed_categories = ["🏦 ARAUTO BANK", "💸 TAXA SEMANAL", "⚙️ ADMINISTRAÇÃO"]
            if ctx.channel.category and ctx.channel.category.name in allowed_categories:
                return True
            else:
                # Impede o comando de ser executado e envia uma mensagem de erro temporária
                await ctx.send(f"❌ Este comando só pode ser usado nos canais do **Arauto Bank**.", delete_after=10)
                return False
        return True # Permite DMs

bot = ArautoBankBot()
bot.run(TOKEN)
