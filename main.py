import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import asyncio
import difflib

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

# --- CHECK GLOBAL PARA RESTRIÇÃO DE CANAIS ---
async def global_channel_check(ctx):
    # Administradores podem sempre
    if ctx.author.guild_permissions.administrator:
        return True

    # Comandos de setup/ajuda permitidos globalmente
    if ctx.command and ctx.command.name in ['setup', 'ajuda']:
        return True

    # Permite apenas se o canal estiver nas categorias permitidas
    if ctx.guild and ctx.channel.category and ctx.channel.category.name in ctx.bot.allowed_categories:
        return True

    # Se está em servidor mas fora das categorias permitidas, tenta apagar e notificar
    if ctx.guild:
        if ctx.command is not None:
            try:
                await ctx.message.delete()
            except Exception:
                pass
            try:
                await ctx.send(f"❌ {ctx.author.mention}, este comando só pode ser usado nos canais do **Arauto Bank**.", delete_after=10)
            except Exception:
                pass
        return False

    # Em DMs permite
    return True

class ArautoBankBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents, case_insensitive=True)
        self.db_manager = DatabaseManager(dsn=DATABASE_URL)
        self.allowed_categories = ["🏦 ARAUTO BANK", "💸 TAXA SEMANAL", "⚙️ ADMINISTRAÇÃO"]

        # Remove comando de ajuda padrão e adiciona check global
        self.remove_command('help')
        self.add_check(global_channel_check)

    async def setup_hook(self):
        print("A executar setup_hook...")
        await self.db_manager.connect()

        # Regista views persistentes
        try:
            self.add_view(OrbeAprovacaoView(self))
            self.add_view(TaxaPrataView(self))
            print("Vistas persistentes registadas.")
        except Exception as e:
            print(f"Aviso: falha ao registar views persistentes: {e}")

        # Carrega cog de admin primeiro para inicializar DB
        try:
            await self.load_extension('cogs.admin')
            admin_cog = self.get_cog('Admin')
            if admin_cog:
                print("A inicializar o esquema da base de dados...")
                await admin_cog.initialize_database_schema()
            else:
                raise Exception("Não foi possível obter o Cog Admin após carregamento.")
        except Exception as e:
            print(f"ERRO CRÍTICO ao carregar/inicializar o Admin Cog: {e}")
            return

        # Lista de cogs principais
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
        print(f'Logado como {self.user.name} (ID: {self.user.id})')
        print('------')

    # --- FUNÇÃO on_command_error ATUALIZADA ---
    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.CheckFailure):
            # Ignora erros de permissão tratados localmente ou pelo check global
            return
            
        # Não processa erros em DMs ou de comandos desconhecidos sem prefixo claro
        if not ctx.guild or not ctx.command:
             # Trata CommandNotFound especificamente mesmo sem ctx.command
             if isinstance(error, commands.CommandNotFound) and ctx.invoked_with:
                 try: await ctx.message.delete()
                 except: pass # Ignora se não conseguir apagar

                 comando_errado = ctx.invoked_with
                 comandos_validos = [cmd.name for cmd in self.commands if not cmd.hidden] + [alias for cmd in self.commands if not cmd.hidden for alias in cmd.aliases]
                 sugestoes = difflib.get_close_matches(comando_errado, comandos_validos, n=1, cutoff=0.7)

                 if sugestoes:
                     try:
                         await ctx.send(
                             f"🤔 {ctx.author.mention}, o comando `!{comando_errado}` não existe. Você quis dizer `!{sugestoes[0]}`? "
                             f"Use `!ajuda {sugestoes[0]}` para detalhes.",
                             delete_after=30
                         )
                     except Exception:
                         pass
                 else:
                     try:
                         await ctx.send(
                             f"😕 {ctx.author.mention}, não reconheço o comando `!{comando_errado}`. "
                             f"Verifique a ortografia ou consulte a lista completa com `!ajuda`.",
                             delete_after=30
                         )
                     except Exception:
                         pass
             return # Ignora outros erros se não houver comando válido

        try: await ctx.message.delete()
        except: pass # Tenta apagar a mensagem original

        if isinstance(error, commands.CommandNotFound):
            # Este bloco agora só é alcançado se ctx.command for None, o que é raro
            pass

        elif isinstance(error, commands.MissingRequiredArgument):
            parametro_em_falta = error.param.name
            try:
                await ctx.send(
                    f"⚠️ {ctx.author.mention}, faltou um argumento para o comando `!{ctx.command.name}`!\n"
                    f"Precisa de fornecer: **`{parametro_em_falta}`**.\n"
                    f"Use `!ajuda {ctx.command.name}` para ver a sintaxe correta e exemplos.",
                    delete_after=45
                )
            except Exception:
                pass

        elif isinstance(error, commands.BadArgument):
             # Tenta obter o tipo esperado se disponível
             expected_type = ""
             if hasattr(error, 'param') and hasattr(error.param.annotation, '__name__'):
                 expected_type = f" (esperava um {error.param.annotation.__name__})"
             
             try:
                 await ctx.send(
                     f"❌ {ctx.author.mention}, o tipo de argumento fornecido para `!{ctx.command.name}` está incorreto{expected_type}.\n"
                     f"Por favor, verifique os dados inseridos. Use `!ajuda {ctx.command.name}` para exemplos.",
                     delete_after=45
                 )
             except Exception:
                 pass

        elif isinstance(error, commands.CommandInvokeError):
             # Erros que acontecem DENTRO da lógica do comando
             original = getattr(error, "original", error)
             print(f"Erro ao invocar comando '{getattr(ctx.command, 'qualified_name', str(ctx.command))}': {original}")
             try:
                 await ctx.send(
                     f"🤯 {ctx.author.mention}, ocorreu um erro inesperado ao executar o comando `!{ctx.command.name}`. "
                     f"A equipe de administração já foi (ou deveria ser) notificada. Se o problema persistir, contacte a staff.\n"
                     f"`Erro: {original}`",
                     delete_after=60
                 )
             except Exception:
                 pass

        else:
             # Outros erros genéricos da biblioteca
             try:
                 print(f"Erro inesperado não tratado para o comando '{getattr(ctx.command, 'qualified_name', str(ctx.command))}': {error}")
                 await ctx.send(
                     f"🤔 {ctx.author.mention}, algo correu mal com o comando `!{ctx.command.name}`. "
                     f"Erro: `{error}`",
                     delete_after=60
                 )
             except Exception:
                 pass

# --- Iniciar o Bot ---
if __name__ == "__main__":
    if not TOKEN or not DATABASE_URL:
        print("ERRO CRÍTICO: DISCORD_TOKEN ou DATABASE_URL não definidos no .env")
    else:
        bot = ArautoBankBot()
        bot.run(TOKEN)
