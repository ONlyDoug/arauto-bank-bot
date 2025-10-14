import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import asyncio
import difflib  # <-- Adicione esta linha

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

# --- CHECK GLOBAL PARA RESTRIÇÃO DE CANAIS (LÓGICA FINAL) ---
async def global_channel_check(ctx):
    if ctx.author.guild_permissions.administrator:
        return True
    if ctx.command and ctx.command.name in ['setup', 'ajuda']:
        return True
    if ctx.guild and ctx.channel.category and ctx.channel.category.name in ctx.bot.allowed_categories:
        return True
    if ctx.guild:
        if ctx.command is not None:
            await ctx.message.delete()
            await ctx.send(f"❌ {ctx.author.mention}, este comando só pode ser usado nos canais do **Arauto Bank**.", delete_after=10)
        return False
    return True

class ArautoBankBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents, case_insensitive=True)
        self.db_manager = DatabaseManager(dsn=DATABASE_URL)
        self.allowed_categories = ["🏦 ARAUTO BANK", "💸 TAXA SEMANAL", "⚙️ ADMINISTRAÇÃO"]

        # --- ATUALIZAÇÃO IMPORTANTE ---
        # Remove o comando de ajuda padrão
        self.remove_command('help')
        self.add_check(global_channel_check)

    async def setup_hook(self):
        print("A executar o setup_hook...")
        await self.db_manager.connect()

        self.add_view(OrbeAprovacaoView(self))
        self.add_view(TaxaPrataView(self))
        print("Vistas persistentes registadas.")

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

        # --- ATUALIZAÇÃO IMPORTANTE ---
        # Adiciona 'cogs.ajuda' à lista de cogs
        cogs_to_load = [
            'cogs.ajuda', 'cogs.economia', 'cogs.eventos', 'cogs.loja',
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
        # Ignora falhas de permissão silenciosamente para não poluir o chat
        if isinstance(error, commands.CheckFailure):
            return

        # --- NOVO SISTEMA DE AJUDA INTELIGENTE E CÓMICO ---

        if isinstance(error, commands.CommandNotFound):
            # O utilizador escreveu um comando que não existe (ex: !paguei, !saldoo)
            comando_errado = ctx.invoked_with
            
            # Pega numa lista de todos os nomes de comandos que o bot conhece
            comandos_validos = [cmd.name for cmd in self.commands if not cmd.hidden]
            
            # Usa a magia da programação para encontrar a correspondência mais próxima
            sugestoes = difflib.get_close_matches(comando_errado, comandos_validos, n=1, cutoff=0.7)
            
            if sugestoes:
                # Se encontrarmos uma sugestão, a resposta é mais direcionada e sarcástica
                await ctx.send(
                    f"Burp... A sério, {ctx.author.mention}? `!{comando_errado}` não faz sentido nem na minha dimensão. "
                    f"O meu scanner de mentes de baixo QI sugere que talvez quisesses dizer **`!{sugestoes[0]}`**. Tenta lá isso, anda."
                )
            else:
                # Se nem o algoritmo adivinha, a resposta é mais genérica
                await ctx.send(
                    f"Ora bolas, {ctx.author.mention}. `!{comando_errado}`? Isso não é um comando. "
                    f"Parece que o teu teclado tropeçou. Pede o manual de instruções com `!ajuda` antes que eu perca a paciência."
                )
            return

        if isinstance(error, commands.MissingRequiredArgument):
            # O utilizador esqueceu-se de adicionar argumentos (ex: !transferir sem nada à frente)
            parametro_em_falta = error.param.name
            await ctx.send(
                f"Oh, geez, {ctx.author.mention}... `!{ctx.command.name}`. E depois? "
                f"Ficaste sem tinta a meio? Falta aí o **`{parametro_em_falta}`**. "
                f"Não me faças adivinhar, o meu cérebro já está ocupado a calcular o sentido do universo. Completa o comando ou usa `!ajuda {ctx.command.name}`."
            )
            return

        if isinstance(error, commands.BadArgument):
            # O utilizador usou o tipo de argumento errado (ex: !comprar batata)
            await ctx.send(
                f"Que diabo, {ctx.author.mention}! Estás a tentar enfiar um quadrado num buraco redondo. "
                f"Os argumentos que deste para `!{ctx.command.name}` são do tipo errado. "
                f"Lê as instruções em `!ajuda {ctx.command.name}` antes que eu transforme as tuas moedas em pó cósmico."
            )
            return

        # Para todos os outros erros, regista no log para a nossa análise
        print(f"Erro inesperado no comando '{ctx.command}': {error}")

# --- Iniciar o Bot ---
if __name__ == "__main__":
    if not TOKEN or not DATABASE_URL:
        print("ERRO CRÍTICO: DISCORD_TOKEN ou DATABASE_URL não definidos no .env")
    else:
        bot = ArautoBankBot()
        bot.run(TOKEN)

