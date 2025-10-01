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
    # Funções Auxiliares de Base de Dados
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
    # Comando de Setup Melhorado
    # =================================================================================
    
    @commands.command(name='setup')
    @commands.has_permissions(administrator=True)
    async def setup_server(self, ctx):
        """(Admin) Apaga a estrutura antiga e cria a estrutura de canais final para o bot, com mensagens detalhadas."""
        guild = ctx.guild
        await ctx.send("⚠️ **AVISO:** Este comando irá apagar e recriar TODAS as categorias e canais do Arauto Bank. A ação é irreversível.\nDigite `confirmar wipe` para prosseguir.")

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel and m.content.lower() == 'confirmar wipe'

        try:
            await self.bot.wait_for('message', timeout=30.0, check=check)
        except asyncio.TimeoutError:
            return await ctx.send("Comando cancelado por inatividade.")

        prog_msg = await ctx.send("🔥 **A iniciar reconstrução total...** (0/5)")

        # --- 1. Apagar Estrutura Antiga ---
        for cat_name in ["🏦 ARAUTO BANK", "💸 TAXA SEMANAL", "⚙️ ADMINISTRAÇÃO"]:
            if category := discord.utils.get(guild.categories, name=cat_name):
                for channel in category.channels: await channel.delete()
                await category.delete()
        await prog_msg.edit(content="🔥 **A iniciar reconstrução total...** (1/5)")

        # --- 2. Lógica de Permissões ---
        perm_nivel_4_id = int(self.get_config_value('perm_nivel_4', '0'))
        perm_4 = guild.get_role(perm_nivel_4_id) if perm_nivel_4_id != 0 else None
        admin_overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(view_channel=True)
        }
        if perm_4: admin_overwrites[perm_4] = discord.PermissionOverwrite(view_channel=True)

        # --- 3. Função Auxiliar de Criação ---
        async def create_and_pin(category, name, embed, overwrites=None, set_config_key=None):
            channel = await category.create_text_channel(name, overwrites=overwrites)
            msg = await channel.send(embed=embed)
            await msg.pin()
            if set_config_key: self.set_config_value(set_config_key, str(channel.id))
            return channel

        # --- 4. Criação da Estrutura ---
        # CATEGORIA: ARAUTO BANK
        cat_bank = await guild.create_category("🏦 ARAUTO BANK")
        await prog_msg.edit(content="🔥 **A iniciar reconstrução total...** (2/5)")

        # Canais do ARAUTO BANK
        embed = discord.Embed(title="🎓 Bem-vindo ao Arauto Bank!", color=0xffd700, description="O sistema económico da nossa guilda, baseado no princípio de **Prova de Participação**.")
        embed.add_field(name="Como funciona?", value="Tudo o que você faz para ajudar a guilda (participar em eventos, estar ativo no chat e em canais de voz) gera **GuildCoins (GC)**, a nossa moeda interna.", inline=False)
        embed.add_field(name="Comandos Essenciais", value="`!saldo` - Ver o seu dinheiro\n`!extrato` - Ver as suas últimas transações\n`!loja` - Ver os itens disponíveis\n`!info-moeda` - Ver a saúde da economia", inline=False)
        await create_and_pin(cat_bank, "🎓｜como-usar-o-bot", embed, {guild.default_role: discord.PermissionOverwrite(send_messages=False)})

        embed = discord.Embed(title="📈 Mercado Financeiro", color=0x1abc9c, description="A nossa economia é **lastreada em Prata**, o que significa que a nossa moeda tem valor real.")
        embed.add_field(name="O que é o Lastro?", value="Significa que para uma quantidade de GuildCoins em circulação, existe uma quantidade de Prata guardada no tesouro da guilda. Isso impede a inflação e garante que a moeda seja forte.", inline=False)
        embed.add_field(name="Comando Útil", value="Use `!info-moeda` ou `!lastro` neste canal para ver o estado atual da economia, incluindo o total de prata no tesouro e a taxa de conversão.", inline=False)
        await create_and_pin(cat_bank, "📈｜mercado-financeiro", embed)

        embed = discord.Embed(title="💰 Saldo e Extrato", color=0x2ecc71, description="Utilize este canal para consultar as suas finanças pessoais.")
        embed.add_field(name="!saldo [@membro]", value="Verifica o seu saldo de GuildCoins ou o de outro membro.", inline=False)
        embed.add_field(name="!extrato [página]", value="Mostra um histórico detalhado das suas últimas 10 transações (compras, ganhos, transferências).", inline=False)
        await create_and_pin(cat_bank, "💰｜saldo-e-extrato", embed)

        embed = discord.Embed(title="🛍️ Loja da Guilda", color=0x3498db, description="Aqui pode gastar as suas GuildCoins em itens valiosos!")
        embed.add_field(name="!loja", value="Lista todos os itens disponíveis para compra, com os seus IDs, preços e descrições.", inline=False)
        embed.add_field(name="!comprar <ID_do_item>", value="Compra um item da loja. O valor será debitado do seu saldo.", inline=False)
        await create_and_pin(cat_bank, "🛍️｜loja-da-guilda", embed)

        embed = discord.Embed(title="🏆 Eventos e Missões", color=0xe91e63, description="A principal fonte de renda da guilda! Participe nos conteúdos para ser recompensado.")
        embed.add_field(name="!listareventos", value="Mostra todos os eventos que estão a decorrer, com as suas recompensas e metas.", inline=False)
        embed.add_field(name="!participar <ID_do_evento>", value="Inscreve-se num evento ativo para começar a registar o seu progresso.", inline=False)
        await create_and_pin(cat_bank, "🏆｜eventos-e-missões", embed)

        embed = discord.Embed(title="🔮 Submeter Orbes", color=0x9b59b6, description="Ganhe recompensas por capturar orbes no jogo.")
        embed.add_field(name="Como funciona?", value="Use o comando abaixo e **anexe o print (screenshot)** da captura na mesma mensagem.", inline=False)
        embed.add_field(name="Comando", value="`!orbe <cor> <@membro1> <@membro2>...`\n**Cores válidas:** verde, azul, roxa, dourada.", inline=False)
        embed.set_footer(text="A sua submissão será enviada para aprovação da administração.")
        await create_and_pin(cat_bank, "🔮｜submeter-orbes", embed, set_config_key='canal_orbes')

        # CATEGORIA: TAXA SEMANAL
        cat_taxas = await guild.create_category("💸 TAXA SEMANAL")
        await prog_msg.edit(content="🔥 **A iniciar reconstrução total...** (3/5)")

        embed = discord.Embed(title="ℹ️ Como Funciona a Taxa Semanal", color=0x7f8c8d, description="Um sistema para garantir a manutenção e o crescimento da nossa guilda.")
        embed.add_field(name="O que é?", value="É uma pequena contribuição semanal, debitada automaticamente do seu saldo em GuildCoins, que ajuda a financiar as atividades e os recursos da guilda.", inline=False)
        embed.add_field(name="O que acontece se eu não tiver saldo?", value="O seu cargo será alterado para `@Inadimplente`, restringindo o seu acesso a alguns canais. Para voltar ao normal, basta regularizar o pagamento no canal `🪙｜pagamento-de-taxas`.", inline=False)
        await create_and_pin(cat_taxas, "ℹ️｜como-funciona-a-taxa", embed, {guild.default_role: discord.PermissionOverwrite(send_messages=False)})

        embed = discord.Embed(title="🪙 Pagamento de Taxas", color=0x95a5a6, description="Utilize este canal para regularizar a sua situação caso o seu cargo seja alterado para `@Inadimplente`.")
        embed.add_field(name="Pagar com GuildCoins (Automático)", value="Use `!pagar-taxa`\nO sistema irá debitar o valor do seu saldo e restaurar o seu cargo de membro instantaneamente.", inline=False)
        embed.add_field(name="Pagar com Prata (Manual)", value="Use `!paguei-prata` e anexe um print do comprovativo de envio da prata no jogo. Um administrador irá aprovar e restaurar o seu acesso.", inline=False)
        await create_and_pin(cat_taxas, "🪙｜pagamento-de-taxas", embed)
        
        # CATEGORIA: ADMINISTRAÇÃO
        cat_admin = await guild.create_category("⚙️ ADMINISTRAÇÃO", overwrites=admin_overwrites)
        await prog_msg.edit(content="🔥 **A iniciar reconstrução total...** (4/5)")

        embed = discord.Embed(title="✅ Aprovações", color=0xf1c40f, description="Este canal é usado pela staff para aprovar ou recusar submissões pendentes, como pagamentos de taxa em prata e capturas de orbes.")
        await create_and_pin(cat_admin, "✅｜aprovações", embed, set_config_key='canal_aprovacao')

        embed = discord.Embed(title="🚨 Resgates Staff", color=0xc27c0e, description="Canal exclusivo para a staff processar a conversão de GuildCoins de membros para Prata do jogo.")
        embed.add_field(name="Comando", value="`!resgatar <@membro> <valor>`", inline=False)
        await create_and_pin(cat_admin, "🚨｜resgates-staff", embed)

        embed = discord.Embed(title="🔩 Comandos Admin", color=0xe67e22, description="Utilize este canal para todos os comandos de gestão e configuração para não poluir os outros canais.")
        await create_and_pin(cat_admin, "🔩｜comandos-admin", embed)

        await prog_msg.edit(content="✅ **Estrutura final criada e configurada com sucesso!** (5/5)")


    @commands.command(name='initdb')
    @commands.has_permissions(administrator=True)
    async def setup_database_command(self, ctx):
        """(Admin) Comando para inicializar manualmente a base de dados."""
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
                    cursor.execute("""CREATE TABLE IF NOT EXISTS atividade_diaria (user_id BIGINT, data DATE, 
                        minutos_voz INTEGER DEFAULT 0, moedas_chat INTEGER DEFAULT 0, PRIMARY KEY (user_id, data))""")
                    cursor.execute("""CREATE TABLE IF NOT EXISTS reacoes_recompensadas (message_id BIGINT, user_id BIGINT, 
                        PRIMARY KEY (message_id, user_id))""")

                    default_configs = {
                        'lastro_prata': '1000',
                        'taxa_semanal_valor': '500', 'cargo_membro': '0', 'cargo_inadimplente': '0', 'cargo_isento': '0',
                        'perm_nivel_1': '0', 'perm_nivel_2': '0', 'perm_nivel_3': '0', 'perm_nivel_4': '0',
                        'canal_aprovacao': '0', 'canal_orbes': '0', 'canal_anuncios': '0',
                        'recompensa_voz': '2', 'limite_voz': '120', 'recompensa_chat': '1',
                        'limite_chat': '100', 'recompensa_reacao': '50', 'orbe_verde': '100', 'orbe_azul': '250',
                        'orbe_roxa': '500', 'orbe_dourada': '1000'
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

