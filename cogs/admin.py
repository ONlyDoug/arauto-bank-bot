import discord
from discord.ext import commands
import asyncio
import contextlib
from utils.permissions import check_permission_level

ID_TESOURO_GUILDA = 1

class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ... (funções de BD permanecem iguais) ...
    @contextlib.contextmanager
    def get_db_connection(self):
        conn = None
        try:
            conn = self.bot.db_pool.getconn()
            yield conn
        finally:
            if conn: self.bot.db_pool.putconn(conn)

    def get_config_value(self, chave: str, default: str = None):
        with self.get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT valor FROM configuracoes WHERE chave = %s", (chave,))
                resultado = cursor.fetchone()
        return resultado[0] if resultado else default

    def set_config_value(self, chave: str, valor: str):
        with self.get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("INSERT INTO configuracoes (chave, valor) VALUES (%s, %s) ON CONFLICT (chave) DO UPDATE SET valor = EXCLUDED.valor", (chave, valor))
            conn.commit()

    async def initialize_database_schema(self):
        try:
            with self.get_db_connection() as conn:
                with conn.cursor() as cursor:
                    # ... (criação de tabelas)
                    cursor.execute("CREATE TABLE IF NOT EXISTS banco (user_id BIGINT PRIMARY KEY, saldo BIGINT NOT NULL DEFAULT 0)")
                    cursor.execute("""CREATE TABLE IF NOT EXISTS transacoes (id SERIAL PRIMARY KEY, user_id BIGINT NOT NULL, tipo TEXT NOT NULL,
                        valor BIGINT NOT NULL, descricao TEXT, data TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP)""")
                    cursor.execute("""CREATE TABLE IF NOT EXISTS eventos (id SERIAL PRIMARY KEY, nome TEXT NOT NULL, recompensa INTEGER NOT NULL,
                        meta_participacao INTEGER NOT NULL DEFAULT 1, ativo BOOLEAN DEFAULT TRUE, criador_id BIGINT NOT NULL, message_id BIGINT)""")
                    cursor.execute("""CREATE TABLE IF NOT EXISTS participantes (evento_id INTEGER REFERENCES eventos(id) ON DELETE CASCADE,
                        user_id BIGINT, progresso INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (evento_id, user_id))""")
                    cursor.execute("CREATE TABLE IF NOT EXISTS configuracoes (chave TEXT PRIMARY KEY, valor TEXT NOT NULL)")
                    cursor.execute("""CREATE TABLE IF NOT EXISTS taxas (user_id BIGINT PRIMARY KEY, data_vencimento DATE, status TEXT DEFAULT 'pago')""")
                    cursor.execute("""CREATE TABLE IF NOT EXISTS submissoes_taxa (id SERIAL PRIMARY KEY, message_id BIGINT, user_id BIGINT, status TEXT DEFAULT 'pendente')""")
                    cursor.execute("""CREATE TABLE IF NOT EXISTS submissoes_orbe (id SERIAL PRIMARY KEY, message_id BIGINT, cor TEXT NOT NULL, 
                        valor_total INTEGER NOT NULL, autor_id BIGINT, membros TEXT, status TEXT DEFAULT 'pendente')""")
                    cursor.execute("""CREATE TABLE IF NOT EXISTS loja (id INTEGER PRIMARY KEY, nome TEXT NOT NULL,
                        descricao TEXT, preco INTEGER NOT NULL CHECK (preco > 0))""")
                    cursor.execute("""CREATE TABLE IF NOT EXISTS atividade_diaria (user_id BIGINT, data DATE, 
                        minutos_voz INTEGER DEFAULT 0, moedas_chat INTEGER DEFAULT 0, PRIMARY KEY (user_id, data))""")
                    cursor.execute("""CREATE TABLE IF NOT EXISTS reacoes_recompensadas (message_id BIGINT, user_id BIGINT, 
                        PRIMARY KEY (message_id, user_id))""")
                    
                    default_configs = {
                        'lastro_total_prata': '100000000', 'taxa_conversao_prata': '1000',
                        'taxa_semanal_valor': '500', 'cargo_membro': '0', 'cargo_inadimplente': '0',
                        'cargo_isento': '0', 'perm_nivel_1': '0', 'perm_nivel_2': '0',
                        'perm_nivel_3': '0', 'perm_nivel_4': '0', 'canal_aprovacao': '0', 'canal_orbes': '0',
                        'canal_anuncios': '0', 'canal_resgates': '0', 'canal_mercado': '0', 'canal_batepapo': '0',
                        'recompensa_voz': '1', 'limite_voz': '120', 'recompensa_chat': '1',
                        'limite_chat': '100', 'recompensa_reacao': '50', 'orbe_verde': '100', 'orbe_azul': '250',
                        'orbe_roxa': '500', 'orbe_dourada': '1000'
                    }
                    for chave, valor in default_configs.items():
                        cursor.execute("INSERT INTO configuracoes (chave, valor) VALUES (%s, %s) ON CONFLICT (chave) DO NOTHING", (chave, valor))
                    
                    cursor.execute("INSERT INTO banco (user_id, saldo) VALUES (%s, 0) ON CONFLICT (user_id) DO NOTHING", (ID_TESOURO_GUILDA,))
                conn.commit()
            print("Base de dados Supabase verificada e pronta.")
        except Exception as e:
            print(f"❌ Ocorreu um erro ao inicializar a base de dados: {e}")

    # ... (!initdb e !setup permanecem iguais, mas com a mensagem de !anunciar atualizada) ...
    @commands.command(name='initdb')
    @commands.has_permissions(administrator=True)
    async def setup_database_command(self, ctx):
        await ctx.send("A verificar e configurar a base de dados...")
        await self.initialize_database_schema()
        await ctx.send("✅ Verificação da base de dados concluída.")

    @commands.command(name='setup')
    @commands.has_permissions(administrator=True)
    async def setup_server(self, ctx):
        # ... (código do !setup)
        # Na embed de "comandos-admin":
        embed = discord.Embed(title="🔩 Comandos Admin", color=0xe67e22, description="Utilize este canal para todos os comandos de gestão e configuração do bot.")
        embed.add_field(name="Gestão Económica", value="`!definir-lastro <valor>`\n`!emitir <@membro> <valor>`\n`!resgatar <@membro> <valor>`\n`!airdrop <valor> <@cargo>`", inline=False)
        embed.add_field(name="Comunicação", value="`!anunciar <canal> <mensagem>`\n*Canais válidos: `mercado`, `batepapo`*", inline=False)
        embed.add_field(name="Configurações Gerais", value="`!definircanal <tipo> #canal`\n*Tipos: `aprovacao`, `orbes`, `anuncios`, `resgates`, `mercado`, `batepapo`*\n`!definirrecompensa <tipo> <valor>`\n`!definirlimite <tipo> <valor>`", inline=False)
        # ... (restante do código do !setup)
        pass

    @commands.command(name='anunciar')
    @check_permission_level(3)
    async def anunciar(self, ctx, canal_alvo: str, *, mensagem: str):
        mapa_canais = {
            'mercado': 'canal_mercado',
            'batepapo': 'canal_batepapo'
        }

        if canal_alvo.lower() not in mapa_canais:
            return await ctx.send("Canal inválido. Canais disponíveis: `mercado`, `batepapo`.")

        id_canal_str = self.get_config_value(mapa_canais[canal_alvo.lower()], '0')
        if id_canal_str == '0':
            return await ctx.send(f"O canal `{canal_alvo}` não está configurado. Use `!definircanal`.")

        canal = self.bot.get_channel(int(id_canal_str))
        if not canal:
            return await ctx.send("Canal não encontrado no servidor. Verifique a configuração.")

        embed = discord.Embed(title="📢 Anúncio do Arauto Bank", description=mensagem, color=0x3498db)
        embed.set_footer(text=f"Anúncio feito por {ctx.author.display_name}")
        
        try:
            await canal.send(embed=embed)
            await ctx.send(f"✅ Anúncio enviado com sucesso para o canal {canal.mention}.")
        except discord.Forbidden:
            await ctx.send(f"❌ Não tenho permissão para enviar mensagens no canal {canal.mention}.")

async def setup(bot):
    await bot.add_cog(Admin(bot))

