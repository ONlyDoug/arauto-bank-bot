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
        """Garante que todas as tabelas e configurações padrão existam na base de dados."""
        try:
            with self.get_db_connection() as conn:
                with conn.cursor() as cursor:
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
                    cursor.execute("""CREATE TABLE IF NOT EXISTS atividade_diaria (user_id BIGINT, data DATE, 
                        minutos_voz INTEGER DEFAULT 0, moedas_chat INTEGER DEFAULT 0, PRIMARY KEY (user_id, data))""")
                    cursor.execute("""CREATE TABLE IF NOT EXISTS reacoes_recompensadas (message_id BIGINT, user_id BIGINT, 
                        PRIMARY KEY (message_id, user_id))""")

                    default_configs = {
                        'lastro_prata': '1000', 'taxa_semanal_valor': '500', 'cargo_membro': '0',
                        'cargo_inadimplente': '0', 'cargo_isento': '0', 'perm_nivel_1': '0', 'perm_nivel_2': '0',
                        'perm_nivel_3': '0', 'perm_nivel_4': '0', 'canal_aprovacao': '0', 'canal_orbes': '0',
                        'canal_anuncios': '0', 'recompensa_voz': '2', 'limite_voz': '120', 'recompensa_chat': '1',
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

    @commands.command(name='initdb')
    @commands.has_permissions(administrator=True)
    async def setup_database_command(self, ctx):
        await ctx.send("A verificar e configurar a base de dados...")
        await self.initialize_database_schema()
        await ctx.send("✅ Verificação da base de dados concluída.")

    @commands.command(name='setup')
    @commands.has_permissions(administrator=True)
    async def setup_server(self, ctx):
        guild = ctx.guild
        await ctx.send("⚠️ **AVISO:** Este comando irá apagar e recriar TODAS as categorias e canais do Arauto Bank. A ação é irreversível.\nDigite `confirmar wipe` para prosseguir.")

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel and m.content.lower() == 'confirmar wipe'

        try:
            await self.bot.wait_for('message', timeout=30.0, check=check)
        except asyncio.TimeoutError:
            return await ctx.send("Comando cancelado por inatividade.")

        prog_msg = await ctx.send("🔥 **A iniciar reconstrução total...** (0/5)")

        for cat_name in ["🏦 ARAUTO BANK", "💸 TAXA SEMANAL", "⚙️ ADMINISTRAÇÃO"]:
            if category := discord.utils.get(guild.categories, name=cat_name):
                for channel in category.channels: await channel.delete()
                await asyncio.sleep(1)
                await category.delete()
        await prog_msg.edit(content="🔥 **A iniciar reconstrução total...** (1/5)")

        perm_nivel_4_id = int(self.get_config_value('perm_nivel_4', '0'))
        perm_4 = guild.get_role(perm_nivel_4_id) if perm_nivel_4_id != 0 else None
        admin_overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(view_channel=True)
        }
        if perm_4: admin_overwrites[perm_4] = discord.PermissionOverwrite(view_channel=True)

        async def create_and_pin(category, name, embed, overwrites=None, set_config_key=None):
            channel = await category.create_text_channel(name, overwrites=overwrites)
            await asyncio.sleep(1)
            msg = await channel.send(embed=embed)
            await msg.pin()
            if set_config_key: self.set_config_value(set_config_key, str(channel.id))
            return channel

        cat_bank = await guild.create_category("🏦 ARAUTO BANK")
        await prog_msg.edit(content="🔥 **A iniciar reconstrução total...** (2/5)")

        embed = discord.Embed(title="🎓 Bem-vindo ao Arauto Bank!", color=0xffd700, description="O sistema económico da nossa guilda, baseado no princípio de **Prova de Participação**.")
        embed.add_field(name="Como funciona?", value="Tudo o que você faz para ajudar a guilda gera **GuildCoins (GC)**, a nossa moeda interna.", inline=False)
        embed.add_field(name="Comandos Essenciais", value="`!saldo`, `!extrato`, `!loja`, `!info-moeda`", inline=False)
        await create_and_pin(cat_bank, "🎓｜como-usar-o-bot", embed, {guild.default_role: discord.PermissionOverwrite(send_messages=False)})
        
        embed = discord.Embed(title="📈 Mercado Financeiro", color=0x1abc9c, description="A nossa economia é **lastreada em Prata**.")
        embed.add_field(name="O que é o Lastro?", value="Significa que a nossa moeda tem valor real e não pode ser criada infinitamente.", inline=False)
        embed.add_field(name="Comando Útil", value="Use `!info-moeda` ou `!lastro` para ver o estado atual da economia.", inline=False)
        await create_and_pin(cat_bank, "📈｜mercado-financeiro", embed)
        
        embed = discord.Embed(title="💰 Saldo e Extrato", color=0x2ecc71, description="Utilize este canal para consultar as suas finanças.")
        embed.add_field(name="!saldo [@membro]", value="Verifica o seu saldo ou o de outro membro.", inline=False)
        embed.add_field(name="!extrato [página]", value="Mostra o seu histórico de transações.", inline=False)
        await create_and_pin(cat_bank, "💰｜saldo-e-extrato", embed)

        embed = discord.Embed(title="🛍️ Loja da Guilda", color=0x3498db, description="Gaste as suas GuildCoins aqui!")
        embed.add_field(name="!loja", value="Lista todos os itens disponíveis.", inline=False)
        embed.add_field(name="!comprar <ID_do_item>", value="Compra um item da loja.", inline=False)
        await create_and_pin(cat_bank, "🛍️｜loja-da-guilda", embed)

        embed = discord.Embed(title="🏆 Eventos e Missões", color=0xe91e63, description="A principal fonte de renda da guilda!")
        embed.add_field(name="!listareventos", value="Mostra os eventos a decorrer.", inline=False)
        embed.add_field(name="!participar <ID_do_evento>", value="Inscreve-se num evento.", inline=False)
        await create_and_pin(cat_bank, "🏆｜eventos-e-missões", embed)

        embed = discord.Embed(title="🔮 Submeter Orbes", color=0x9b59b6, description="Ganhe recompensas por capturar orbes.")
        embed.add_field(name="Comando", value="`!orbe <cor> <@membros...>` e anexe o print.", inline=False)
        await create_and_pin(cat_bank, "🔮｜submeter-orbes", embed, set_config_key='canal_orbes')
        
        cat_taxas = await guild.create_category("💸 TAXA SEMANAL")
        await prog_msg.edit(content="🔥 **A iniciar reconstrução total...** (3/5)")
        
        embed = discord.Embed(title="ℹ️ Como Funciona a Taxa Semanal", color=0x7f8c8d, description="Um sistema para a manutenção da guilda.")
        embed.add_field(name="O que é?", value="É uma contribuição semanal debitada do seu saldo em GuildCoins.", inline=False)
        embed.add_field(name="E se eu não pagar?", value="O seu cargo será alterado para `@Inadimplente`.", inline=False)
        await create_and_pin(cat_taxas, "ℹ️｜como-funciona-a-taxa", embed, {guild.default_role: discord.PermissionOverwrite(send_messages=False)})

        embed = discord.Embed(title="🪙 Pagamento de Taxas", color=0x95a5a6, description="Utilize este canal para regularizar a sua situação.")
        embed.add_field(name="Pagar com GuildCoins", value="Use `!pagar-taxa`.", inline=False)
        embed.add_field(name="Pagar com Prata", value="Use `!paguei-prata` e anexe um print.", inline=False)
        await create_and_pin(cat_taxas, "🪙｜pagamento-de-taxas", embed)
        
        cat_admin = await guild.create_category("⚙️ ADMINISTRAÇÃO", overwrites=admin_overwrites)
        await prog_msg.edit(content="🔥 **A iniciar reconstrução total...** (4/5)")
        
        embed = discord.Embed(title="✅ Aprovações", color=0xf1c40f, description="Canal para a staff aprovar submissões.")
        await create_and_pin(cat_admin, "✅｜aprovações", embed, set_config_key='canal_aprovacao')

        embed = discord.Embed(title="🚨 Resgates Staff", color=0xc27c0e, description="Canal para a staff processar resgates de moedas.")
        embed.add_field(name="Comando", value="`!resgatar <@membro> <valor>`", inline=False)
        await create_and_pin(cat_admin, "🚨｜resgates-staff", embed)

        embed = discord.Embed(title="🔩 Comandos Admin", color=0xe67e22, description="Utilize este canal para comandos de gestão.")
        await create_and_pin(cat_admin, "🔩｜comandos-admin", embed)
        
        await prog_msg.edit(content="✅ **Estrutura final criada e configurada com sucesso!** (5/5)")

async def setup(bot):
    await bot.add_cog(Admin(bot))

