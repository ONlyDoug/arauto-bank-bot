import discord
from discord.ext import commands
import asyncio
import contextlib

ID_TESOURO_GUILDA = 1

class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

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
                        'lastro_total_prata': '100000000', 'taxa_conversao_prata': '1000',
                        'taxa_semanal_valor': '500', 'cargo_membro': '0', 'cargo_inadimplente': '0',
                        'cargo_isento': '0', 'perm_nivel_1': '0', 'perm_nivel_2': '0',
                        'perm_nivel_3': '0', 'perm_nivel_4': '0', 'canal_aprovacao': '0', 'canal_orbes': '0',
                        'canal_anuncios': '0', 'canal_resgates': '0', 'recompensa_voz': '1', 'limite_voz': '120', 'recompensa_chat': '1',
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
                await asyncio.sleep(2)
                await category.delete()
        await prog_msg.edit(content="🔥 **A iniciar reconstrução total...** (1/5)")

        perm_nivel_4_id = int(self.get_config_value('perm_nivel_4', '0'))
        perm_4 = guild.get_role(perm_nivel_4_id) if perm_nivel_4_id != 0 else None
        admin_overwrites = { guild.default_role: discord.PermissionOverwrite(view_channel=False), guild.me: discord.PermissionOverwrite(view_channel=True) }
        if perm_4: admin_overwrites[perm_4] = discord.PermissionOverwrite(view_channel=True)

        async def create_and_pin(category, name, embed, overwrites=None, set_config_key=None):
            channel_options = {}
            if overwrites is not None: channel_options['overwrites'] = overwrites
            channel = await category.create_text_channel(name, **channel_options)
            await asyncio.sleep(2)
            msg = await channel.send(embed=embed)
            await msg.pin()
            if set_config_key: self.set_config_value(set_config_key, str(channel.id))
            return channel

        # === CATEGORIA ARAUTO BANK ===
        cat_bank = await guild.create_category("🏦 ARAUTO BANK")
        await prog_msg.edit(content="🔥 **A iniciar reconstrução total...** (2/5)")

        embed = discord.Embed(title="🎓 Bem-vindo ao Arauto Bank!", color=0xffd700, description="O sistema económico da nossa guilda, baseado no princípio de **Prova de Participação**: toda a geração de valor está ligada a ações que beneficiam a guilda.")
        embed.add_field(name="💸 Como Ganhar Moedas?", value="**Renda Ativa:** Participe em eventos e missões.\n**Renda Passiva:** Esteja ativo nos canais de voz e texto.\n**Engajamento:** Reaja a anúncios importantes.", inline=False)
        embed.add_field(name="🏦 Comandos Essenciais", value="`!saldo` - Ver o seu saldo.\n`!extrato` - Ver o seu histórico de transações.\n`!loja` - Ver os itens disponíveis para compra.\n`!info-moeda` - Ver a saúde da nossa economia.", inline=False)
        await create_and_pin(cat_bank, "🎓｜como-usar-o-bot", embed, overwrites={guild.default_role: discord.PermissionOverwrite(send_messages=False)})
        
        embed = discord.Embed(title="📈 Mercado Financeiro", color=0x1abc9c, description="A nossa economia é **lastreada em Prata**, o que significa que cada moeda em circulação tem um valor real correspondente guardado no tesouro da guilda.")
        embed.add_field(name="Comando Principal", value="`!info-moeda` ou `!lastro`\nUse este comando para ver todas as estatísticas vitais da economia, incluindo o total de prata, a taxa de conversão e quantas moedas estão em circulação.", inline=False)
        embed.add_field(name="Resgatando Moedas", value="As suas moedas podem ser convertidas de volta para prata. Fale com um administrador para usar o comando `!resgatar` e iniciar o processo.", inline=False)
        await create_and_pin(cat_bank, "📈｜mercado-financeiro", embed)
        
        embed = discord.Embed(title="💰 Saldo e Extrato", color=0x2ecc71, description="Utilize este canal para todos os comandos relacionados com as suas finanças pessoais.")
        embed.add_field(name="Consultar Saldo", value="`!saldo` - Mostra o seu saldo atual.\n`!saldo @membro` - Mostra o saldo de outro membro.", inline=False)
        embed.add_field(name="Ver Histórico de Transações", value="`!extrato` - Mostra a sua atividade de hoje.\n`!extrato AAAA-MM-DD` - Mostra a atividade de um dia específico.", inline=False)
        embed.add_field(name="Transferir Moedas", value="`!transferir @membro <valor>` - Envia moedas para outro jogador.", inline=False)
        await create_and_pin(cat_bank, "💰｜saldo-e-extrato", embed)

        embed = discord.Embed(title="🛍️ Loja da Guilda", color=0x3498db, description="Gaste as suas GuildCoins (GC) para adquirir itens que o ajudarão no jogo, fechando o ciclo económico da guilda.")
        embed.add_field(name="Comandos da Loja", value="`!loja` - Lista todos os itens disponíveis e os seus preços.\n`!comprar <ID_do_item>` - Compra o item desejado.", inline=False)
        embed.add_field(name="Gestão (Staff)", value="`!additem <ID> <preço> <nome>`\n`!delitem <ID>`", inline=False)
        await create_and_pin(cat_bank, "🛍️｜loja-da-guilda", embed)

        embed = discord.Embed(title="🏆 Eventos e Missões", color=0xe91e63, description="Esta é a principal fonte de **Renda Ativa** e a forma mais eficaz de ganhar grandes quantidades de moedas.")
        embed.add_field(name="Comandos para Membros", value="`!listareventos` - Vê todos os eventos ativos.\n`!participar <ID_do_evento>` - Inscreve-se num evento para começar a contar o seu progresso.", inline=False)
        embed.add_field(name="Comandos para Organizadores", value="`!criarevento <recompensa> <meta> <nome>`\n`!confirmar <ID> @membros...`\n`!finalizarevento <ID>`", inline=False)
        await create_and_pin(cat_bank, "🏆｜eventos-e-missões", embed)

        embed = discord.Embed(title="🔮 Submeter Orbes", color=0x9b59b6, description="Ganhe recompensas por capturar orbes de energia no jogo.")
        embed.add_field(name="Como Funciona?", value="1. Tire um print (screenshot) da mensagem de captura da orbe no jogo.\n2. Use o comando `!orbe <cor> <@membros...>` neste canal, marcando todos os que participaram.\n3. **Anexe o print** à sua mensagem.\n4. Aguarde a aprovação de um staff. O valor será dividido igualmente.", inline=False)
        await create_and_pin(cat_bank, "🔮｜submeter-orbes", embed, set_config_key='canal_orbes')
        
        # === CATEGORIA TAXA SEMANAL ===
        cat_taxas = await guild.create_category("💸 TAXA SEMANAL")
        await prog_msg.edit(content="🔥 **A iniciar reconstrução total...** (3/5)")
        
        embed = discord.Embed(title="ℹ️ Como Funciona a Taxa Semanal", color=0x7f8c8d, description="A taxa semanal é um sistema automatizado para garantir a manutenção e o crescimento da nossa guilda. O valor é debitado automaticamente do seu `!saldo`.")
        embed.add_field(name="O que acontece se eu não tiver saldo?", value="Se não tiver moedas suficientes, você receberá o cargo de `@Inadimplente` e perderá o acesso a alguns canais até regularizar a sua situação.", inline=False)
        embed.add_field(name="Como Pagar?", value="Use o canal `🪙｜pagamento-de-taxas` e os comandos `!pagar-taxa` (com moedas) ou `!paguei-prata` (com prata do jogo).", inline=False)
        await create_and_pin(cat_taxas, "ℹ️｜como-funciona-a-taxa", embed, overwrites={guild.default_role: discord.PermissionOverwrite(send_messages=False)})

        embed = discord.Embed(title="🪙 Pagamento de Taxas", color=0x95a5a6, description="Utilize este canal para regularizar a sua situação e recuperar o acesso total ao servidor.")
        embed.add_field(name="Pagar com Moedas (Automático)", value="`!pagar-taxa`\nO valor será debitado do seu saldo e o seu acesso será restaurado instantaneamente.", inline=False)
        embed.add_field(name="Pagar com Prata (Requer Aprovação)", value="`!paguei-prata`\nAnexe um print do comprovativo de pagamento no jogo. Um staff irá aprovar e restaurar o seu acesso.", inline=False)
        await create_and_pin(cat_taxas, "🪙｜pagamento-de-taxas", embed)
        
        # === CATEGORIA ADMINISTRAÇÃO ===
        cat_admin = await guild.create_category("⚙️ ADMINISTRAÇÃO", overwrites=admin_overwrites)
        await prog_msg.edit(content="🔥 **A iniciar reconstrução total...** (4/5)")
        
        embed = discord.Embed(title="✅ Aprovações", color=0xf1c40f, description="Canal restrito à staff para aprovar ou recusar submissões pendentes, como capturas de orbes e pagamentos de taxa em prata. As ações são realizadas através de botões.")
        await create_and_pin(cat_admin, "✅｜aprovações", embed, set_config_key='canal_aprovacao')

        embed = discord.Embed(title="🚨 Resgates Staff", color=0xc27c0e, description="Canal para a staff processar os pedidos de resgate de moedas por prata do jogo. Quando uma solicitação aparecer aqui, um tesoureiro deve entregar a prata ao jogador e reagir com ✅.")
        await create_and_pin(cat_admin, "🚨｜resgates-staff", embed, set_config_key='canal_resgates')

        embed = discord.Embed(title="🔩 Comandos Admin", color=0xe67e22, description="Utilize este canal para todos os comandos de gestão e configuração do bot.")
        embed.add_field(name="Gestão Económica", value="`!definir-lastro <valor>`\n`!emitir <@membro> <valor>`\n`!resgatar <@membro> <valor>`", inline=False)
        embed.add_field(name="Configurações Gerais", value="`!definircanal <tipo> #canal`\n`!definirrecompensa <tipo> <valor>`\n`!definirlimite <tipo> <valor>`", inline=False)
        await create_and_pin(cat_admin, "🔩｜comandos-admin", embed)
        
        await prog_msg.edit(content="✅ **Estrutura final criada e configurada com sucesso!** (5/5)")

async def setup(bot):
    await bot.add_cog(Admin(bot))

