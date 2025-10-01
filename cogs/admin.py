import discord
from discord.ext import commands
import asyncio
import contextlib

# Constante para o ID do tesouro, para evitar "números mágicos"
ID_TESOURO_GUILDA = 1

class Admin(commands.Cog):
    """Cog que agrupa todos os comandos de administração e configuração do bot."""
    def __init__(self, bot):
        self.bot = bot

    @contextlib.contextmanager
    def get_db_connection(self):
        """Obtém uma conexão do pool e garante que ela é devolvida."""
        conn = None
        try:
            conn = self.bot.db_pool.getconn()
            yield conn
        finally:
            if conn:
                self.bot.db_pool.putconn(conn)

    # =================================================================================
    # 2.1. Funções Auxiliares de Base de Dados
    # =================================================================================

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

    # =================================================================================
    # 2.2. Comando de Setup
    # =================================================================================
    
    @commands.command(name='setup')
    @commands.has_permissions(administrator=True)
    async def setup_server(self, ctx):
        """Apaga a estrutura antiga e cria a estrutura de canais final para o bot."""
        guild = ctx.guild
        await ctx.send("⚠️ **AVISO:** Este comando irá apagar e recriar as categorias do Arauto Bank. A ação é irreversível.\nDigite `confirmar wipe` para prosseguir.")

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel and m.content.lower() == 'confirmar wipe'

        try:
            await self.bot.wait_for('message', timeout=30.0, check=check)
        except asyncio.TimeoutError:
            return await ctx.send("Comando cancelado por inatividade.")

        msg_progresso = await ctx.send("🔥 Confirmado! A iniciar a reconstrução... (0/3)")

        # Apaga a estrutura antiga
        category_names_to_delete = ["🏦 ARAUTO BANK", "💸 TAXA SEMANAL", "⚙️ ADMINISTRAÇÃO"]
        for cat_name in category_names_to_delete:
            if category := discord.utils.get(guild.categories, name=cat_name):
                for channel in category.channels:
                    await channel.delete()
                await category.delete()

        await msg_progresso.edit(content="🔥 Estrutura antiga removida. A criar nova estrutura... (1/3)")

        # Lógica de Permissões
        perm_nivel_4_id = int(self.get_config_value('perm_nivel_4', '0'))
        perm_nivel_4_role = guild.get_role(perm_nivel_4_id) if perm_nivel_4_id != 0 else None
        admin_overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(view_channel=True)
        }
        if perm_nivel_4_role:
            admin_overwrites[perm_nivel_4_role] = discord.PermissionOverwrite(view_channel=True)
        else:
             await ctx.send("⚠️ Aviso: Cargo de Admin (nível 4) não configurado. A categoria de administração será visível apenas para administradores do servidor.")


        # Função Auxiliar para Criar e Fixar
        async def create_and_pin(category, name, embed, overwrites=None):
            try:
                channel = await category.create_text_channel(name, overwrites=overwrites)
                msg = await channel.send(embed=embed)
                await msg.pin()
                return channel
            except discord.Forbidden:
                await ctx.send(f"❌ Erro de permissão ao criar ou fixar mensagem no canal `{name}`.")
            except Exception as e:
                await ctx.send(f"⚠️ Ocorreu um erro inesperado ao criar o canal `{name}`: {e}")
            return None

        # 1. Categoria Principal: ARAUTO BANK
        cat_principal = await guild.create_category("🏦 ARAUTO BANK")
        
        # Canais Públicos
        embed_tutorial = discord.Embed(title="🎓 Como Usar o Arauto Bank", description="Bem-vindo ao sistema económico da guilda! Use este canal para tirar dúvidas e aprender os comandos.", color=0xffd700)
        await create_and_pin(cat_principal, "🎓-como-usar-o-bot", embed_tutorial, {guild.default_role: discord.PermissionOverwrite(send_messages=False)})

        embed_mercado = discord.Embed(title="📈 Mercado Financeiro", description="Use `!infomoeda` para ver os detalhes da nossa economia!", color=0x1abc9c)
        ch_mercado = await create_and_pin(cat_principal, "📈-mercado-financeiro", embed_mercado)
        if ch_mercado: self.set_config_value('canal_mercado', str(ch_mercado.id))

        await msg_progresso.edit(content="🔥 Canais principais criados... (2/3)")

        # 2. Categoria de Administração
        cat_admin = await guild.create_category("⚙️ ADMINISTRAÇÃO", overwrites=admin_overwrites)
        
        embed_aprovacao = discord.Embed(title="✅ Aprovações", description="Aqui aparecerão as submissões de orbes e pagamentos de taxa.", color=0xf1c40f)
        ch_aprovacao = await create_and_pin(cat_admin, "✅-aprovações", embed_aprovacao)
        if ch_aprovacao: self.set_config_value('canal_aprovacao', str(ch_aprovacao.id))

        embed_comandos = discord.Embed(title="🔩 Comandos Admin", description="Use este canal para todos os comandos de gestão.", color=0xe67e22)
        await create_and_pin(cat_admin, "🔩-comandos-admin", embed_comandos)

        await msg_progresso.edit(content="✅ Estrutura de canais final criada e configurada com sucesso!")

    @commands.command(name='initdb')
    @commands.has_permissions(administrator=True)
    async def setup_database_command(self, ctx):
        """Comando para inicializar manualmente a base de dados."""
        await ctx.send("A verificar e configurar a base de dados...")
        try:
            with self.get_db_connection() as conn:
                with conn.cursor() as cursor:
                    # Estrutura de tabelas
                    cursor.execute("CREATE TABLE IF NOT EXISTS banco (user_id BIGINT PRIMARY KEY, saldo BIGINT NOT NULL DEFAULT 0)")
                    cursor.execute("""CREATE TABLE IF NOT EXISTS transacoes (id SERIAL PRIMARY KEY, user_id BIGINT NOT NULL, tipo TEXT NOT NULL,
                        valor BIGINT NOT NULL, descricao TEXT, data TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP)""")
                    cursor.execute("""CREATE TABLE IF NOT EXISTS eventos (id SERIAL PRIMARY KEY, nome TEXT NOT NULL, recompensa INTEGER NOT NULL,
                        meta_participacao INTEGER NOT NULL DEFAULT 1, ativo BOOLEAN DEFAULT TRUE, criador_id BIGINT NOT NULL, message_id BIGINT)""")
                    cursor.execute("""CREATE TABLE IF NOT EXISTS participantes (evento_id INTEGER REFERENCES eventos(id) ON DELETE CASCADE,
                        user_id BIGINT, progresso INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (evento_id, user_id))""")
                    cursor.execute("CREATE TABLE IF NOT EXISTS configuracoes (chave TEXT PRIMARY KEY, valor TEXT NOT NULL)")
                    cursor.execute("""CREATE TABLE IF NOT EXISTS taxas (user_id BIGINT PRIMARY KEY, data_vencimento DATE, status TEXT DEFAULT 'pago')""")
                    cursor.execute("""CREATE TABLE IF NOT EXISTS submissoes_orbe (id SERIAL PRIMARY KEY, message_id BIGINT, cor TEXT NOT NULL, 
                        valor_total INTEGER NOT NULL, autor_id BIGINT, membros TEXT, status TEXT DEFAULT 'pendente')""")
                    cursor.execute("""CREATE TABLE IF NOT EXISTS loja (id INTEGER PRIMARY KEY, nome TEXT NOT NULL,
                        descricao TEXT, preco INTEGER NOT NULL CHECK (preco > 0))""")
                    # --- NOVAS TABELAS DE ENGAJAMENTO ---
                    cursor.execute("""CREATE TABLE IF NOT EXISTS atividade_diaria (user_id BIGINT, data DATE, 
                        minutos_voz INTEGER DEFAULT 0, moedas_chat INTEGER DEFAULT 0, PRIMARY KEY (user_id, data))""")
                    cursor.execute("""CREATE TABLE IF NOT EXISTS reacoes_recompensadas (message_id BIGINT, user_id BIGINT, 
                        PRIMARY KEY (message_id, user_id))""")

                    default_configs = {
                        'lastro_total_prata': '0', 'lastro_prata': '1000',
                        'recompensa_tier_bronze': '50', 'recompensa_tier_prata': '100', 'recompensa_tier_ouro': '200',
                        'orbe_verde': '100', 'orbe_azul': '250', 'orbe_roxa': '500', 'orbe_dourada': '1000',
                        'taxa_semanal_valor': '500', 'cargo_membro': '0', 'cargo_inadimplente': '0', 'cargo_isento': '0',
                        'perm_nivel_1': '0', 'perm_nivel_2': '0', 'perm_nivel_3': '0', 'perm_nivel_4': '0',
                        'canal_aprovacao': '0', 'canal_mercado': '0', 'canal_orbes': '0', 'canal_anuncios': '0',
                        # --- NOVAS CONFIGS DE ENGAJAMENTO ---
                        'recompensa_voz': '2', # 2 GC a cada 5 min = 24 GC/hora
                        'limite_voz': '120', # 120 minutos = 2 horas
                        'recompensa_chat': '1',
                        'limite_chat': '100', # 100 moedas
                        'recompensa_reacao': '50'
                    }
                    for chave, valor in default_configs.items():
                        cursor.execute("INSERT INTO configuracoes (chave, valor) VALUES (%s, %s) ON CONFLICT (chave) DO NOTHING", (chave, valor))
                    
                    cursor.execute("INSERT INTO banco (user_id, saldo) VALUES (%s, 0) ON CONFLICT (user_id) DO NOTHING", (ID_TESOURO_GUILDA,))
                conn.commit()
            await ctx.send("✅ Base de dados Supabase verificada e pronta.")
        except Exception as e:
            await ctx.send(f"❌ Ocorreu um erro ao configurar a base de dados: {e}")


async def setup(bot):
    await bot.add_cog(Admin(bot))

