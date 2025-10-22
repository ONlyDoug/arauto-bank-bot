import discord
from discord.ext import commands
import asyncio
from datetime import datetime
from utils.permissions import check_permission_level
from collections import defaultdict

class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.ID_TESOURO_GUILDA = 1

    async def initialize_database_schema(self):
        try:
            await self.bot.db_manager.execute_query("CREATE TABLE IF NOT EXISTS banco (user_id BIGINT PRIMARY KEY, saldo BIGINT NOT NULL DEFAULT 0)")
            await self.bot.db_manager.execute_query("""CREATE TABLE IF NOT EXISTS transacoes (id SERIAL PRIMARY KEY, user_id BIGINT NOT NULL, tipo TEXT NOT NULL, valor BIGINT NOT NULL, descricao TEXT, data TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP)""")
            await self.bot.db_manager.execute_query("CREATE TABLE IF NOT EXISTS configuracoes (chave TEXT PRIMARY KEY, valor TEXT NOT NULL)")

            await self.bot.db_manager.execute_query("""
                CREATE TABLE IF NOT EXISTS taxas (user_id BIGINT PRIMARY KEY, status_ciclo TEXT DEFAULT 'PENDENTE', data_entrada TIMESTAMP WITH TIME ZONE)""")
            try:
                await self.bot.db_manager.execute_query("ALTER TABLE taxas ADD COLUMN IF NOT EXISTS status_ciclo TEXT DEFAULT 'PENDENTE'")
                await self.bot.db_manager.execute_query("ALTER TABLE taxas ADD COLUMN IF NOT EXISTS data_entrada TIMESTAMP WITH TIME ZONE")
            except Exception as e:
                print(f"Nota de migração: Não foi possível adicionar colunas a 'taxas'. Erro: {e}")

            await self.bot.db_manager.execute_query("""CREATE TABLE IF NOT EXISTS submissoes_orbe (id SERIAL PRIMARY KEY, message_id BIGINT, cor TEXT NOT NULL, valor_total INTEGER NOT NULL, autor_id BIGINT, membros TEXT, status TEXT DEFAULT 'pendente')""")
            await self.bot.db_manager.execute_query("CREATE TABLE IF NOT EXISTS loja (id SERIAL PRIMARY KEY, nome TEXT NOT NULL, preco INTEGER NOT NULL, descricao TEXT)")
            await self.bot.db_manager.execute_query("CREATE TABLE IF NOT EXISTS renda_passiva_log (user_id BIGINT, tipo TEXT, data DATE, valor INTEGER, PRIMARY KEY (user_id, tipo, data))")
            await self.bot.db_manager.execute_query("CREATE TABLE IF NOT EXISTS submissoes_taxa (message_id BIGINT PRIMARY KEY, user_id BIGINT, status TEXT)")
            await self.bot.db_manager.execute_query("CREATE TABLE IF NOT EXISTS reacoes_anuncios (user_id BIGINT, message_id BIGINT, PRIMARY KEY (user_id, message_id))")
            await self.bot.db_manager.execute_query("""CREATE TABLE IF NOT EXISTS eventos (id SERIAL PRIMARY KEY, nome TEXT NOT NULL, descricao TEXT, tipo_evento TEXT, data_evento TIMESTAMP WITH TIME ZONE, recompensa INTEGER DEFAULT 0, max_participantes INTEGER, criador_id BIGINT NOT NULL, message_id BIGINT, status TEXT DEFAULT 'AGENDADO', inscritos BIGINT[] DEFAULT '{}'::BIGINT[], cargo_requerido_id BIGINT, canal_voz_id BIGINT)""")

            # --- CHAVES DE CONFIGURAÇÃO ATUALIZADAS ---
            default_configs = {
                'taxa_semanal_valor': '500', 'taxa_dia_semana': '6', 'taxa_dia_abertura': '5',
                'cargo_membro': '0', 'cargo_inadimplente': '0', 'cargo_isento': '0',
                'canal_relatorio_taxas': '0', 'canal_pagamento_taxas': '0', 'canal_info_taxas': '0',
                'taxa_msg_id_pendentes': '0', 'taxa_msg_id_pagos': '0', 'taxa_msg_id_isentos': '0',
                'taxa_mensagem_inadimplente': 'Olá {member}! A taxa semanal de {tax_value} moedas não foi paga. O seu acesso foi temporariamente restringido. Use `!pagar-taxa` ou `!paguei-prata` para regularizar.', # <-- NOVA CONFIG
                # ... (resto das configs existentes devem permanecer) ...
            }
            for chave, valor in default_configs.items():
                await self.bot.db_manager.execute_query(
                    "INSERT INTO configuracoes (chave, valor) VALUES ($1, $2) ON CONFLICT (chave) DO NOTHING",
                    chave, valor
                )

            # garante existência do tesouro na tabela banco
            await self.bot.db_manager.execute_query("INSERT INTO banco (user_id, saldo) VALUES ($1, 0) ON CONFLICT (user_id) DO NOTHING", self.ID_TESOURO_GUILDA)

            print("Base de dados verificada (Estrutura de Taxas v2.7 com Mensagem Inadimplente).")
        except Exception as e:
            print(f"❌ Ocorreu um erro ao inicializar a base de dados: {e}")
            raise e

    @commands.command(name='initdb', hidden=True)
    @commands.has_permissions(administrator=True)
    async def initdb(self, ctx):
        await ctx.send("A forçar a verificação da base de dados...")
        try:
            await self.initialize_database_schema()
            await ctx.send("✅ Verificação da base de dados concluída.")
        except Exception as e:
            await ctx.send(f"❌ Falha ao inicializar a base de dados: {e}")

    async def create_and_pin(self, ctx, *, category, name, embed, overwrites=None, set_config_key=None):
        try:
            channel_overwrites = overwrites if overwrites is not None else {}
            channel = await category.create_text_channel(name, overwrites=channel_overwrites)
            await asyncio.sleep(1.5)
            msg = await channel.send(embed=embed)
            await msg.pin()
            
            if set_config_key and channel:
                await self.bot.db_manager.set_config_value(set_config_key, str(channel.id))
                
            return channel
        except discord.Forbidden as e:
            await ctx.send(f"❌ Erro de permissão ao criar o canal `{name}`: {e}")
        except Exception as e:
            await ctx.send(f"⚠️ Ocorreu um erro inesperado ao criar o canal `{name}`: {e}")
        return None

    @commands.command(name='setup')
    @commands.has_permissions(administrator=True)
    async def setup_server(self, ctx):
        guild = ctx.guild
        await ctx.send("⚠️ **AVISO:** Este comando irá apagar e recriar as categorias do Arauto Bank. A ação é irreversível.\nDigite `confirmar wipe` para prosseguir.")
        
        def check(m): return m.author == ctx.author and m.channel == ctx.channel and m.content.lower() == 'confirmar wipe'
        
        try: 
            await self.bot.wait_for('message', timeout=30.0, check=check)
        except asyncio.TimeoutError: 
            return await ctx.send("Comando cancelado.")

        msg_progresso = await ctx.send("🔥 Confirmado! A iniciar a reconstrução...")

        category_names_to_delete = ["🏦 ARAUTO BANK", "💸 TAXA SEMANAL", "⚙️ ADMINISTRAÇÃO"]
        for cat_name in category_names_to_delete:
            if category := discord.utils.get(guild.categories, name=cat_name):
                for channel in category.channels: 
                    try: await channel.delete()
                    except Exception as e: print(f"Não foi possível apagar o canal {channel.name}: {e}")
                try: await category.delete()
                except Exception as e: print(f"Não foi possível apagar a categoria {category.name}: {e}")
                await asyncio.sleep(1.5)
        
        await msg_progresso.edit(content="🔥 Estrutura antiga removida. A criar a nova...")

        # Permissões para canais de staff
        perm_roles_ids = set()
        for i in range(1, 5):
            role_ids_str = await self.bot.db_manager.get_config_value(f'perm_nivel_{i}', '')
            if role_ids_str:
                perm_roles_ids.update(role_ids_str.split(','))
        
        admin_overwrites = { 
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(view_channel=True)
        }
        for role_id in perm_roles_ids:
            try:
                if role := guild.get_role(int(role_id)):
                    admin_overwrites[role] = discord.PermissionOverwrite(view_channel=True)
            except Exception:
                continue

        # 1. Categoria Principal
        cat_bank = await guild.create_category("🏦 ARAUTO BANK")
        await asyncio.sleep(1.5)
        
        embed = discord.Embed(title="🎓｜Como Usar o Arauto Bank", description="Bem-vindo ao centro nevrálgico da nossa economia! Aqui pode aprender a usar o bot, consultar o seu saldo e muito mais.", color=0xffd700)
        embed.add_field(name="Comece por aqui", value="Cada canal tem uma mensagem fixada que explica o seu propósito. Leia-as para entender como tudo funciona.", inline=False)
        embed.add_field(name="Comandos Essenciais", value="`!saldo` - Vê o seu saldo de moedas.\n`!extrato` - Vê o seu histórico de transações.\n`!loja` - Mostra os itens que pode comprar.\n`!info-moeda` - Vê a saúde da nossa economia.", inline=False)
        await self.create_and_pin(ctx, category=cat_bank, name="🎓｜como-usar-o-bot", embed=embed, overwrites={guild.default_role: discord.PermissionOverwrite(send_messages=False)})
        
        embed = discord.Embed(title="📈｜Mercado Financeiro", description="A nossa moeda tem valor real! O seu valor é **lastreado** (garantido) pela prata guardada no tesouro da guilda.", color=0x1abc9c)
        embed.add_field(name="O que é o Lastro?", value="Significa que para cada moeda em circulação, existe uma quantidade correspondente de prata guardada. Isto garante que a nossa moeda nunca perde o seu valor.", inline=False)
        embed.add_field(name="Comando Útil", value="Use `!info-moeda` para ver o total de prata no tesouro, a taxa de conversão atual e quantas moedas existem no total.", inline=False)
        await self.create_and_pin(ctx, category=cat_bank, name="📈｜mercado-financeiro", embed=embed, set_config_key='canal_mercado', overwrites={guild.default_role: discord.PermissionOverwrite(send_messages=False)})
        
        embed = discord.Embed(title="💰｜Minha Conta", description="Este é o seu espaço pessoal para gerir as suas finanças.", color=0x2ecc71)
        embed.add_field(name="Comandos de Gestão", value="`!saldo` - Vê o seu saldo atual.\n`!saldo @membro` - Vê o saldo de outro membro.\n`!extrato` - Mostra o seu extrato do dia.\n`!extrato AAAA-MM-DD` - Vê o extrato de um dia específico.\n`!transferir @membro <valor>` - Envia moedas para outro membro.", inline=False)
        await self.create_and_pin(ctx, category=cat_bank, name="💰｜minha-conta", embed=embed)

        embed = discord.Embed(title="🛍️｜Loja da Guilda", description="Todo o seu esforço é recompensado! Use as suas moedas para comprar itens valiosos.", color=0x3498db)
        embed.add_field(name="Como Comprar", value="1. Use `!loja` para ver a lista de itens disponíveis e os seus IDs.\n2. Use `!comprar <ID_do_item>` para fazer a sua compra.", inline=False)
        await self.create_and_pin(ctx, category=cat_bank, name="🛍️｜loja-da-guilda", embed=embed)
        
        embed = discord.Embed(title="🏆｜Eventos e Missões", description="A principal forma de ganhar moedas! Participar nos conteúdos da guilda é a sua maior fonte de renda.", color=0xe91e63)
        embed.add_field(name="Como Participar", value="**Para Puxadores:**\n`!puxar <tier> <nome>` (tier: bronze, prata, ouro)\n`!criarevento <recompensa> <meta> <nome>`\n`!confirmar <ID> <@membros...>`\n`!finalizarevento <ID>`\n\n**Para Membros:**\n`!listareventos`\n`!participar <ID>`", inline=False)
        await self.create_and_pin(ctx, category=cat_bank, name="🏆｜eventos-e-missões", embed=embed, set_config_key='canal_eventos')

        embed = discord.Embed(title="🔮｜Submeter Orbes", description="Apanhou uma orbe? Registe-a aqui para ganhar uma recompensa para si e para o seu grupo!", color=0x9b59b6)
        embed.add_field(name="Como Submeter", value="Anexe o print da captura da orbe nesta sala e use o comando:\n`!orbe <cor> <@membro1> <@membro2> ...`", inline=False)
        await self.create_and_pin(ctx, category=cat_bank, name="🔮｜submeter-orbes", embed=embed, set_config_key='canal_orbes')
        
        # 2. Categoria de Taxas
        cat_taxas = await guild.create_category("💸 TAXA SEMANAL")
        await asyncio.sleep(1.5)

        embed = discord.Embed(title="ℹ️｜Como Funciona a Taxa", description="A taxa semanal é um sistema automático que ajuda a financiar os projetos e as atividades da guilda.", color=0x7f8c8d)
        await self.create_and_pin(ctx, category=cat_taxas, name="ℹ️｜como-funciona-a-taxa", embed=embed, overwrites={guild.default_role: discord.PermissionOverwrite(send_messages=False)}, set_config_key='canal_info_taxas')
        
        embed = discord.Embed(title="🪙｜Pagamento de Taxas", description="Use este canal para regularizar a sua situação se estiver com a taxa em atraso.", color=0x95a5a6)
        await self.create_and_pin(ctx, category=cat_taxas, name="🪙｜pagamento-de-taxas", embed=embed, set_config_key='canal_pagamento_taxas')

        # 3. Categoria de Administração
        cat_admin = await guild.create_category("⚙️ ADMINISTRAÇÃO", overwrites=admin_overwrites)
        await asyncio.sleep(1.5)
        
        embed = discord.Embed(title="📋｜Planeamento de Eventos", description="Este canal é para uso exclusivo da staff para a criação de eventos.", color=0x546e7a)
        await self.create_and_pin(ctx, category=cat_admin, name="📋｜planeamento", embed=embed, set_config_key='canal_planejamento')
        
        embed = discord.Embed(title="📈｜Relatório de Taxas", description="Este canal mostra o status de pagamento de taxas de todos os membros, atualizado automaticamente.")
        await self.create_and_pin(ctx, category=cat_admin, name="📈｜relatorio-de-taxas", embed=embed, overwrites={guild.default_role: discord.PermissionOverwrite(send_messages=False)}, set_config_key='canal_relatorio_taxas')
        
        embed = discord.Embed(title="✅｜Aprovações", description="Este canal é para uso exclusivo da staff. Aqui aparecerão todas as submissões de orbes e pagamentos de taxa.", color=0xf1c40f)
        await self.create_and_pin(ctx, category=cat_admin, name="✅｜aprovações", embed=embed, set_config_key='canal_aprovacao')

        embed = discord.Embed(title="🚨｜Resgates Staff", description="Este canal notifica a equipa financeira sempre que um resgate de moedas por prata é processado ou um item é comprado na loja.", color=0xe74c3c)
        await self.create_and_pin(ctx, category=cat_admin, name="🚨｜resgates-staff", embed=embed, set_config_key='canal_resgates')

        embed = discord.Embed(title="🔩｜Comandos Admin", description="Utilize este canal para todos os comandos de gestão e configuração do bot.", color=0xe67e22)
        await self.create_and_pin(ctx, category=cat_admin, name="🔩｜comandos-admin", embed=embed)
        
        embed = discord.Embed(title="📊｜Logs de Taxas", description="Este canal regista todas as ações automáticas do ciclo de taxas.", color=0x546e7a)
        await self.create_and_pin(ctx, category=cat_admin, name="📊｜logs-de-taxas", embed=embed, set_config_key='canal_log_taxas')
        
        await msg_progresso.edit(content="✅ Estrutura de canais final criada e configurada com sucesso!")

    @commands.group(name="cargo", invoke_without_command=True)
    @check_permission_level(4)
    async def cargo(self, ctx):
        await ctx.send("Comandos disponíveis: `!cargo definir <tipo> <@cargo>` e `!cargo permissao <nível> <@cargo(s)>`")

    @cargo.command(name="definir")
    async def cargo_definir(self, ctx, tipo: str, cargo: discord.Role):
        tipos_validos = ['membro', 'inadimplente', 'isento']
        if tipo.lower() not in tipos_validos:
            return await ctx.send(f"❌ Tipo inválido. Tipos válidos: `{', '.join(tipos_validos)}`")
        
        chave = f"cargo_{tipo.lower()}"
        await self.bot.db_manager.set_config_value(chave, str(cargo.id))
        await ctx.send(f"✅ O cargo **{tipo.capitalize()}** foi definido como {cargo.mention}.")

    @cargo.command(name="permissao")
    async def cargo_permissao(self, ctx, nivel: int, cargos: commands.Greedy[discord.Role]):
        if not 1 <= nivel <= 4:
            return await ctx.send("❌ O nível de permissão deve ser entre 1 e 4.")
        if not cargos:
            return await ctx.send("❌ Você precisa de mencionar pelo menos um cargo.")
        
        ids_cargos_str = ",".join(str(c.id) for c in cargos)
        chave = f"perm_nivel_{nivel}"
        await self.bot.db_manager.set_config_value(chave, ids_cargos_str)

        mencoes_cargos = ", ".join(c.mention for c in cargos)
        await ctx.send(f"✅ Os cargos {mencoes_cargos} foram associados ao **Nível de Permissão {nivel}**.")
    
    @commands.group(name="definircanal", invoke_without_command=True)
    @check_permission_level(4)
    async def definir_canal(self, ctx):
        tipos = "`planejamento`, `eventos`, `anuncios`, `batepapo`, `aprovacao`, `logtaxas`, `resgates`, `relatoriotaxas`, `pagamentotaxas`, `infotaxas`"
        await ctx.send(f"Use `!definircanal <tipo> #canal`. Tipos disponíveis: {tipos}.")
    
    @definir_canal.command(name="planejamento")
    async def definir_canal_planejamento(self, ctx, canal: discord.TextChannel):
        await self.bot.db_manager.set_config_value("canal_planejamento", str(canal.id))
        await ctx.send(f"✅ O canal de planeamento de eventos foi definido como {canal.mention}.")

    @definir_canal.command(name="eventos")
    async def definir_canal_eventos(self, ctx, canal: discord.TextChannel):
        await self.bot.db_manager.set_config_value("canal_eventos", str(canal.id))
        await ctx.send(f"✅ O canal para anúncios de eventos foi definido como {canal.mention}.")

    @definir_canal.command(name="anuncios")
    async def definir_canal_anuncios(self, ctx, canal: discord.TextChannel):
        await self.bot.db_manager.set_config_value("canal_anuncios", str(canal.id))
        await ctx.send(f"✅ O canal de anúncios para reações foi definido como {canal.mention}.")

    @definir_canal.command(name="batepapo")
    async def definir_canal_batepapo(self, ctx, canal: discord.TextChannel):
        await self.bot.db_manager.set_config_value("canal_batepapo", str(canal.id))
        await ctx.send(f"✅ O canal de bate-papo para engajamento foi definido como {canal.mention}.")
    
    @definir_canal.command(name="aprovacao")
    async def definir_canal_aprovacao(self, ctx, canal: discord.TextChannel):
        await self.bot.db_manager.set_config_value("canal_aprovacao", str(canal.id))
        await ctx.send(f"✅ O canal de aprovações da staff foi definido como {canal.mention}.")
        
    @definir_canal.command(name="logtaxas")
    async def definir_canal_logtaxas(self, ctx, canal: discord.TextChannel):
        await self.bot.db_manager.set_config_value("canal_log_taxas", str(canal.id))
        await ctx.send(f"✅ O canal de logs das taxas foi definido como {canal.mention}.")
        
    @definir_canal.command(name="resgates")
    async def definir_canal_resgates(self, ctx, canal: discord.TextChannel):
        await self.bot.db_manager.set_config_value("canal_resgates", str(canal.id))
        await ctx.send(f"✅ O canal de resgates para a staff foi definido como {canal.mention}.")

    @definir_canal.command(name="relatoriotaxas")
    async def definir_canal_relatorio_taxas(self, ctx, canal: discord.TextChannel):
        await self.bot.db_manager.set_config_value("canal_relatorio_taxas", str(canal.id))
        await ctx.send(f"✅ O canal para o relatório automático de taxas foi definido como {canal.mention}.")

    @definir_canal.command(name="pagamentotaxas")
    async def definir_canal_pagamento_taxas(self, ctx, canal: discord.TextChannel):
        await self.bot.db_manager.set_config_value("canal_pagamento_taxas", str(canal.id))
        await ctx.send(f"✅ O canal para pagamento de taxas foi definido como {canal.mention}.")

    @definir_canal.command(name="infotaxas")
    async def definir_canal_info_taxas(self, ctx, canal: discord.TextChannel):
        await self.bot.db_manager.set_config_value("canal_info_taxas", str(canal.id))
        await ctx.send(f"✅ O canal de informações sobre taxas foi definido como {canal.mention}.")

    @commands.command(name="anunciar")
    @check_permission_level(3)
    async def anunciar(self, ctx, tipo_canal: str, *, mensagem: str):
        tipos_validos = { "mercado": "canal_mercado", "batepapo": "canal_batepapo" }
        if tipo_canal.lower() not in tipos_validos:
            return await ctx.send("❌ Tipo de canal inválido. Use `mercado` ou `batepapo`.")
        
        chave_canal = tipos_validos[tipo_canal.lower()]
        canal_id_str = await self.bot.db_manager.get_config_value(chave_canal)
        if not canal_id_str or canal_id_str == '0':
            return await ctx.send(f"⚠️ O canal `{tipo_canal}` ainda não foi configurado.")
        canal = self.bot.get_channel(int(canal_id_str))
        if not canal:
            return await ctx.send("❌ Canal não encontrado.")
        embed = discord.Embed(title="📢 Anúncio da Administração", description=mensagem, color=discord.Color.blue(), timestamp=datetime.utcnow())
        embed.set_footer(text=f"Anunciado por: {ctx.author.display_name}", icon_url=ctx.author.display_avatar.url)
        try:
            await canal.send(embed=embed)
            await ctx.send("✅ Anúncio enviado!", delete_after=10)
        except discord.Forbidden:
            await ctx.send("❌ O bot não tem permissão para enviar mensagens nesse canal.")

    @commands.command(name="definir-lastro")
    @check_permission_level(4)
    async def definir_lastro(self, ctx, valor: int):
        if valor < 0:
            return await ctx.send("❌ O valor do lastro não pode ser negativo.")
        await self.bot.db_manager.set_config_value('lastro_total_prata', str(valor))
        taxa_conversao = int(await self.bot.db_manager.get_config_value('taxa_conversao_prata', '1000'))
        suprimento_maximo = valor // taxa_conversao if taxa_conversao > 0 else 0
        await self.bot.db_manager.execute_query("UPDATE banco SET saldo = $1 WHERE user_id = $2", suprimento_maximo, self.ID_TESOURO_GUILDA)
        await ctx.send(f"✅ Lastro total de prata definido para **{valor:,}** 🥈. O tesouro foi atualizado para **{suprimento_maximo:,}** 🪙.".replace(',', '.'))

    @commands.command(name="definir-taxa-conversao")
    @check_permission_level(4)
    async def definir_taxa_conversao(self, ctx, valor: int):
        if valor <= 0:
            return await ctx.send("❌ A taxa de conversão deve ser um valor positivo.")
        await self.bot.db_manager.set_config_value('taxa_conversao_prata', str(valor))
        await ctx.send(f"✅ Taxa de conversão definida para **1 🪙 = {valor:,} 🥈**.".replace(',', '.'))

    @commands.command(name="definir-recompensa-puxar")
    @check_permission_level(4)
    async def definir_recompensa_puxar(self, ctx, tier: str, valor: int):
        tier_lower = tier.lower()
        if tier_lower not in ['bronze', 'ouro']: return await ctx.send("❌ Tier inválido. Use `bronze` ou `ouro`.")
        if valor < 0: return await ctx.send("❌ O valor da recompensa não pode ser negativo.")
        await self.bot.db_manager.set_config_value(f"recompensa_puxar_{tier_lower}", str(valor))
        await ctx.send(f"✅ Recompensa para puxadas **{tier.capitalize()}** definida para **{valor}** moedas.")

    @commands.command(name="definir-limite-puxadas")
    @check_permission_level(4)
    async def definir_limite_puxadas(self, ctx, limite: int):
        if limite < 0: return await ctx.send("❌ O limite não pode ser negativo.")
        await self.bot.db_manager.set_config_value('limite_puxadas_diario', str(limite))
        await ctx.send(f"✅ Limite diário de puxadas por membro definido para **{limite}**.")

    @commands.command(name="verificarconfig", aliases=["verconfig"], hidden=True)
    @check_permission_level(4)
    async def verificar_config(self, ctx):
        await ctx.send("🔍 A gerar o relatório completo de configurações...")
        configs = {item['chave']: item['valor'] for item in await self.bot.db_manager.execute_query("SELECT chave, valor FROM configuracoes", fetch="all")}
        embed = discord.Embed(title="⚙️ Painel de Configuração do Arauto Bank", color=discord.Color.orange())
        categorias = {
            "Canais": ['canal_planejamento', 'canal_eventos', 'canal_anuncios', 'canal_batepapo', 'canal_aprovacao', 'canal_log_taxas', 'canal_resgates', 'canal_mercado', 'canal_orbes'],
            "Cargos": ['cargo_membro', 'cargo_inadimplente', 'cargo_isento'],
            "Permissões": ['perm_nivel_1', 'perm_nivel_2', 'perm_nivel_3', 'perm_nivel_4'],
            "Economia": ['lastro_total_prata', 'taxa_conversao_prata'],
            "Taxas": ['taxa_semanal_valor', 'taxa_dia_semana'],
            "Renda": ['recompensa_voz', 'limite_voz', 'recompensa_chat', 'limite_chat', 'cooldown_chat', 'recompensa_reacao'],
            "Eventos": ['recompensa_puxar_bronze', 'recompensa_puxar_ouro', 'limite_puxadas_diario']
        }
        for nome_cat, chaves in categorias.items():
            texto = ""
            for chave in sorted(chaves):
                valor = configs.get(chave, "Não definido")
                try:
                    if 'canal' in chave and valor.isdigit() and valor != '0':
                        c = self.bot.get_channel(int(valor))
                        valor = c.mention if c else f"⚠️ ID `{valor}`"
                    elif 'cargo' in chave and valor.isdigit() and valor != '0':
                        r = ctx.guild.get_role(int(valor))
                        valor = r.mention if r else f"⚠️ ID `{valor}`"
                    elif 'perm_nivel' in chave and valor and valor != '0':
                        valor = ", ".join([(r := ctx.guild.get_role(int(rid))) and r.mention or f"⚠️ ID `{rid}`" for rid in valor.split(',')])
                except Exception:
                    pass
                texto += f"**{chave}:** {valor}\n"
            if texto: embed.add_field(name=f"--- {nome_cat} ---", value=texto, inline=False)
        await ctx.send(embed=embed)

    @commands.command(name='auditar', hidden=True)
    @check_permission_level(4)
    async def auditar(self, ctx, membro: discord.Member):
        await ctx.send(f"🔍 A iniciar auditoria para **{membro.display_name}**...")
        transacoes = await self.bot.db_manager.execute_query("SELECT valor, descricao FROM transacoes WHERE user_id = $1 AND tipo = 'deposito'", membro.id, fetch="all")
        if not transacoes: return await ctx.send(f"Nenhum ganho encontrado para {membro.display_name}.")
        categorias = defaultdict(lambda: {'total': 0, 'count': 0})
        for t in transacoes:
            desc = (t['descricao'] or '').lower()
            cat = 'Outros'
            if desc.startswith("recompensa do evento"): cat = 'Eventos'
            elif desc.startswith("recompensa de orbe"): cat = 'Orbes'
            elif "renda passiva" in desc: cat = 'Renda Passiva'
            elif desc.startswith("recompensa por reagir"): cat = 'Reações'
            elif desc.startswith("transferência de"): cat = 'Transferências Recebidas'
            elif "emissão" in desc or "airdrop" in desc: cat = 'Administrativo'
            categorias[cat]['total'] += t['valor']
            categorias[cat]['count'] += 1
        saldo = await self.bot.get_cog('Economia').get_saldo(membro.id)
        embed = discord.Embed(title=f"🕵️‍♂️ Relatório de Auditoria: {membro.display_name}", color=discord.Color.dark_blue())
        embed.set_thumbnail(url=membro.display_avatar.url)
        embed.add_field(name="Saldo Atual", value=f"**{saldo:,}** 🪙", inline=False)
        texto_relatorio = "\n".join([f"**{cat}:** `{dados['total']:,}` 🪙 ({dados['count']}x)" for cat, dados in sorted(categorias.items(), key=lambda i: i[1]['total'], reverse=True)])
        embed.add_field(name="Ganhos por Categoria", value=texto_relatorio, inline=False)
        await ctx.send(embed=embed)

    @commands.command(name='confiscar', hidden=True)
    @check_permission_level(4)
    async def confiscar(self, ctx, membro: discord.Member, valor: int):
        if valor <= 0: return await ctx.send("❌ O valor deve ser positivo.")
        economia_cog = self.bot.get_cog('Economia')
        try:
            await economia_cog.levantar(membro.id, valor, f"Confisco por {ctx.author.name}")
            await economia_cog.depositar(self.ID_TESOURO_GUILDA, valor, f"Devolução de confisco de {membro.name}")
            saldo_final = await economia_cog.get_saldo(membro.id)
            embed = discord.Embed(title="⚖️ Correção de Saldo", description=f"O saldo de **{membro.display_name}** foi corrigido.", color=discord.Color.dark_red())
            embed.add_field(name="Valor Confiscado", value=f"**{valor:,}** 🪙", inline=True)
            embed.add_field(name="Saldo Final", value=f"**{saldo_final:,}** 🪙", inline=True)
            await ctx.send(embed=embed)
        except ValueError as e: await ctx.send(f"❌ **Falha:** {e}")
        except Exception as e: await ctx.send(f"❌ Erro inesperado: {e}")

    @commands.command(name='testar-engajamento', hidden=True)
    @check_permission_level(4)
    async def testar_engajamento(self, ctx):
        engajamento_cog = self.bot.get_cog('Engajamento')
        if not engajamento_cog: return await ctx.send("❌ Módulo de Engajamento não carregado.")
        try:
            await ctx.send("🚀 A enviar mensagem de engajamento de teste...")
            await engajamento_cog.enviar_mensagem_engajamento()
            await ctx.send("✅ Teste concluído.")
        except Exception as e: await ctx.send(f"❌ Falha no teste: {e}")

    @commands.command(name="sync", hidden=True)
    @commands.is_owner()
    async def sync(self, ctx):
        await ctx.send("🔄 Sincronizando comandos de barra...")
        try:
            synced = await self.bot.tree.sync()
            await ctx.send(f"✅ {len(synced)} comandos sincronizados.")
        except Exception as e: await ctx.send(f"❌ Falha na sincronização: {e}")

    # --- NOVO COMANDO PARA DEFINIR MENSAGENS ---
    @commands.group(name="definirmsg", invoke_without_command=True, hidden=True)
    @check_permission_level(4)
    async def definir_msg(self, ctx):
        await ctx.send("Use `!definirmsg <tipo> <mensagem>`. Tipos disponíveis: `taxa_inadimplente`.")

    @definir_msg.command(name="taxa_inadimplente")
    async def definir_msg_taxa_inadimplente(self, ctx, *, mensagem: str):
        """Define a mensagem a ser enviada por DM aos membros que ficam inadimplentes."""
        await self.bot.db_manager.set_config_value("taxa_mensagem_inadimplente", mensagem)
        await ctx.send(f"✅ Mensagem para inadimplentes definida!\n**Preview:**\n{mensagem.format(member=ctx.author.mention, tax_value=123)}")

async def setup(bot):
    # Garante que o Admin cog é adicionado ao bot
    await bot.add_cog(Admin(bot))

