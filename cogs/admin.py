import discord
from discord.ext import commands
import asyncio
from utils.permissions import check_permission_level

class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_manager = self.bot.db_manager

    async def initialize_database_schema(self):
        """
        Cria todas as tabelas e configurações na DB se não existirem.
        Esta função é chamada uma vez no arranque do bot.
        """
        try:
            with self.db_manager.get_connection() as conn:
                with conn.cursor() as cursor:
                    # Estrutura de tabelas (schema)
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
                    cursor.execute("CREATE TABLE IF NOT EXISTS loja (id INTEGER PRIMARY KEY, nome TEXT NOT NULL, preco INTEGER NOT NULL, descricao TEXT)")
                    cursor.execute("CREATE TABLE IF NOT EXISTS renda_passiva_log (user_id BIGINT, tipo TEXT, data DATE, valor INTEGER, PRIMARY KEY (user_id, tipo, data))")
                    cursor.execute("CREATE TABLE IF NOT EXISTS submissoes_taxa (message_id BIGINT PRIMARY KEY, user_id BIGINT, status TEXT, url_imagem TEXT)")
                    
                    # Configurações padrão do bot
                    default_configs = {
                        'lastro_total_prata': '0', 'taxa_conversao_prata': '1000',
                        'recompensa_tier_bronze': '50', 'recompensa_tier_prata': '100', 'recompensa_tier_ouro': '200',
                        'orbe_verde': '100', 'orbe_azul': '250', 'orbe_roxa': '500', 'orbe_dourada': '1000',
                        'taxa_semanal_valor': '500', 'cargo_membro': '0', 'cargo_inadimplente': '0', 'cargo_isento': '0',
                        'perm_nivel_1': '0', 'perm_nivel_2': '0', 'perm_nivel_3': '0', 'perm_nivel_4': '0',
                        'canal_aprovacao': '0', 'canal_mercado': '0', 'canal_orbes': '0', 'canal_anuncios': '0',
                        'canal_resgates': '0', 'canal_batepapo': '0',
                        'recompensa_voz': '1', 'limite_voz': '120',
                        'recompensa_chat': '1', 'limite_chat': '100', 'cooldown_chat': '60',
                        'recompensa_reacao': '50'
                    }
                    # Insere as configurações padrão apenas se elas não existirem
                    for chave, valor in default_configs.items():
                        cursor.execute("INSERT INTO configuracoes (chave, valor) VALUES (%s, %s) ON CONFLICT (chave) DO NOTHING", (chave, valor))
                    
                    # Garante que a conta do tesouro (ID 1) existe
                    cursor.execute("INSERT INTO banco (user_id, saldo) VALUES (%s, 0) ON CONFLICT (user_id) DO NOTHING", (1,))
                conn.commit()
            print("Base de dados Supabase verificada e pronta.")
        except Exception as e:
            print(f"❌ Ocorreu um erro ao inicializar a base de dados: {e}")
            raise e # Propaga o erro para que o bot não inicie com a DB defeituosa

    @commands.command(name='initdb')
    @commands.has_permissions(administrator=True)
    async def initdb(self, ctx):
        """
        (Admin) Força a verificação e criação do esquema da base de dados. Útil para resetar ou garantir a estrutura.
        """
        await ctx.send("A forçar a verificação da base de dados...")
        await self.initialize_database_schema()
        await ctx.send("✅ Verificação da base de dados concluída.")


    @commands.command(name='setup')
    @commands.has_permissions(administrator=True)
    async def setup_server(self, ctx):
        """(Admin) Cria a estrutura de categorias e canais para o bot funcionar."""
        guild = ctx.guild
        await ctx.send("⚠️ **AVISO:** Este comando irá apagar e recriar as categorias do Arauto Bank. A ação é irreversível.\nDigite `confirmar wipe` para prosseguir.")
        
        def check(m): return m.author == ctx.author and m.channel == ctx.channel and m.content.lower() == 'confirmar wipe'
        
        try: 
            await self.bot.wait_for('message', timeout=30.0, check=check)
        except asyncio.TimeoutError: 
            return await ctx.send("Comando cancelado.")

        msg_progresso = await ctx.send("🔥 Confirmado! A iniciar a reconstrução...")

        # --- Apaga a estrutura antiga ---
        category_names_to_delete = ["🏦 ARAUTO BANK", "💸 TAXA SEMANAL", "⚙️ ADMINISTRAÇÃO"]
        for cat_name in category_names_to_delete:
            if category := discord.utils.get(guild.categories, name=cat_name):
                for channel in category.channels: 
                    await channel.delete()
                await category.delete()
                await asyncio.sleep(1) # Pausa para evitar rate limit
        
        await msg_progresso.edit(content="🔥 Estrutura antiga removida. A criar a nova...")

        # --- Lógica de Permissões ---
        perm_nivel_4_id = int(self.db_manager.get_config_value('perm_nivel_4', '0'))
        perm_nivel_4_role = guild.get_role(perm_nivel_4_id)
        admin_overwrites = { 
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(view_channel=True)
        }
        if perm_nivel_4_role: 
            admin_overwrites[perm_nivel_4_role] = discord.PermissionOverwrite(view_channel=True)

        # --- Função Auxiliar para Criar e Fixar ---
        async def create_and_pin(category, name, embed, overwrites=None, set_config_key=None):
            channel = None
            try:
                channel = await category.create_text_channel(name, overwrites=overwrites)
                await asyncio.sleep(1)
                msg = await channel.send(embed=embed)
                await msg.pin()
                if set_config_key and channel:
                    self.db_manager.set_config_value(set_config_key, str(channel.id))
                return channel
            except discord.Forbidden:
                await ctx.send(f"❌ Erro de permissão ao criar ou fixar mensagem no canal `{name}`.")
            except Exception as e:
                await ctx.send(f"⚠️ Ocorreu um erro inesperado ao criar o canal `{name}`: {e}")
            return None

        # 1. Categoria Principal: ARAUTO BANK
        cat_bank = await guild.create_category("🏦 ARAUTO BANK")
        await asyncio.sleep(1)
        
        # ... (código das embeds e criação de canais, que está correto)
        
        await msg_progresso.edit(content="✅ Estrutura de canais final criada e configurada com sucesso!")

    # --- Comandos de Configuração ---
    @commands.group(name="definir", invoke_without_command=True)
    @check_permission_level(4)
    async def definir(self, ctx):
        await ctx.send("Comando de configuração. Use `!definir canal`, `!definir recompensa`, `!definir limite`, `!definir lastro` ou `!definir taxa`.")

    @definir.command(name="canal")
    @check_permission_level(4)
    async def definir_canal(self, ctx, tipo: str, canal: discord.TextChannel):
        tipos_validos = ['aprovacao', 'mercado', 'orbes', 'anuncios', 'resgates', 'batepapo']
        if tipo.lower() not in tipos_validos:
            await ctx.send(f"Tipo de canal inválido. Use um dos seguintes: `{', '.join(tipos_validos)}`")
            return
        
        chave = f"canal_{tipo.lower()}"
        self.db_manager.set_config_value(chave, str(canal.id))
        await ctx.send(f"✅ O canal de `{tipo}` foi definido para {canal.mention}.")

    @definir.command(name="recompensa")
    @check_permission_level(4)
    async def definir_recompensa(self, ctx, tipo: str, valor: int):
        tipos_validos = ['voz', 'chat', 'reacao']
        if tipo.lower() not in tipos_validos:
            await ctx.send(f"Tipo de recompensa inválido. Use: `{', '.join(tipos_validos)}`")
            return
        
        chave = f"recompensa_{tipo.lower()}"
        self.db_manager.set_config_value(chave, str(valor))
        await ctx.send(f"✅ A recompensa para `{tipo}` foi definida para **{valor}** moedas.")

    @definir.command(name="limite")
    @check_permission_level(4)
    async def definir_limite(self, ctx, tipo: str, valor: int):
        tipos_validos = ['voz', 'chat']
        if tipo.lower() not in tipos_validos:
            await ctx.send(f"Tipo de limite inválido. Use: `{', '.join(tipos_validos)}`")
            return

        unidade = "minutos" if tipo.lower() == 'voz' else "moedas"
        chave = f"limite_{tipo.lower()}"
        self.db_manager.set_config_value(chave, str(valor))
        await ctx.send(f"✅ O limite diário para `{tipo}` foi definido para **{valor} {unidade}**.")

    @definir.command(name="lastro")
    @check_permission_level(4)
    async def definir_lastro(self, ctx, valor_total_prata: int):
        self.db_manager.set_config_value('lastro_total_prata', str(valor_total_prata))
        await ctx.send(f"✅ O lastro total em prata da guilda foi definido para **{valor_total_prata:,}** 🥈.")

    @definir.command(name="taxa")
    @check_permission_level(4)
    async def definir_taxa(self, ctx, valor: int):
        self.db_manager.set_config_value('taxa_semanal_valor', str(valor))
        await ctx.send(f"✅ O valor da taxa semanal foi definido para **{valor}** moedas.")

    @commands.group(name="cargo", invoke_without_command=True)
    @check_permission_level(4)
    async def cargo(self, ctx):
        await ctx.send("Comando de configuração de cargos. Use `!cargo definir` ou `!cargo permissao`.")

    @cargo.command(name="definir")
    @check_permission_level(4)
    async def cargo_definir(self, ctx, tipo: str, cargo: discord.Role):
        tipos_validos = ['membro', 'inadimplente', 'isento']
        if tipo.lower() not in tipos_validos:
            await ctx.send(f"Tipo de cargo inválido. Use: `{', '.join(tipos_validos)}`")
            return
        
        chave = f"cargo_{tipo.lower()}"
        self.db_manager.set_config_value(chave, str(cargo.id))
        await ctx.send(f"✅ O cargo de `{tipo}` foi definido para {cargo.mention}.")

    @cargo.command(name="permissao")
    @check_permission_level(4)
    async def cargo_permissao(self, ctx, nivel: int, cargo: discord.Role):
        if not 1 <= nivel <= 4:
            await ctx.send("O nível de permissão deve ser entre 1 e 4.")
            return

        chave = f"perm_nivel_{nivel}"
        self.db_manager.set_config_value(chave, str(cargo.id))
        await ctx.send(f"✅ O cargo {cargo.mention} foi associado ao nível de permissão **{nivel}**.")
    
    @commands.command(name="anunciar")
    @check_permission_level(3)
    async def anunciar(self, ctx, canal_tipo: str, *, mensagem: str):
        tipos_validos = ['anuncios', 'mercado', 'batepapo']
        if canal_tipo.lower() not in tipos_validos:
            await ctx.send(f"Tipo de canal inválido. Use: `{', '.join(tipos_validos)}`")
            return

        chave_canal = f"canal_{canal_tipo.lower()}"
        canal_id = int(self.db_manager.get_config_value(chave_canal, '0'))
        
        if canal_id == 0:
            await ctx.send(f"O canal para `{canal_tipo}` ainda não foi configurado. Use `!definir canal`.")
            return

        canal = self.bot.get_channel(canal_id)
        if not canal:
            await ctx.send("Não foi possível encontrar o canal configurado.")
            return

        embed = discord.Embed(
            title="📢 Anúncio da Administração",
            description=mensagem,
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        embed.set_footer(text=f"Enviado por {ctx.author.display_name}", icon_url=ctx.author.avatar.url)

        await canal.send(embed=embed)
        await ctx.message.add_reaction("✅")

async def setup(bot):
    await bot.add_cog(Admin(bot))

