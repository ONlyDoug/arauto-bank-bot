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
            # (O resto das criações de tabelas permanecem iguais)
            await self.bot.db_manager.execute_query("CREATE TABLE IF NOT EXISTS banco (user_id BIGINT PRIMARY KEY, saldo BIGINT NOT NULL DEFAULT 0)")
            await self.bot.db_manager.execute_query("""CREATE TABLE IF NOT EXISTS transacoes (id SERIAL PRIMARY KEY, user_id BIGINT NOT NULL, tipo TEXT NOT NULL,
                valor BIGINT NOT NULL, descricao TEXT, data TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP)""")
            await self.bot.db_manager.execute_query("""CREATE TABLE IF NOT EXISTS participantes (evento_id INTEGER, user_id BIGINT, progresso INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (evento_id, user_id))""")
            await self.bot.db_manager.execute_query("CREATE TABLE IF NOT EXISTS configuracoes (chave TEXT PRIMARY KEY, valor TEXT NOT NULL)")
            await self.bot.db_manager.execute_query("""CREATE TABLE IF NOT EXISTS taxas (user_id BIGINT PRIMARY KEY, data_vencimento DATE, status TEXT DEFAULT 'pago')""")
            await self.bot.db_manager.execute_query("""CREATE TABLE IF NOT EXISTS submissoes_orbe (id SERIAL PRIMARY KEY, message_id BIGINT, cor TEXT NOT NULL, 
                valor_total INTEGER NOT NULL, autor_id BIGINT, membros TEXT, status TEXT DEFAULT 'pendente')""")
            await self.bot.db_manager.execute_query("CREATE TABLE IF NOT EXISTS loja (id SERIAL PRIMARY KEY, nome TEXT NOT NULL, preco INTEGER NOT NULL, descricao TEXT)")
            await self.bot.db_manager.execute_query("CREATE TABLE IF NOT EXISTS renda_passiva_log (user_id BIGINT, tipo TEXT, data DATE, valor INTEGER, PRIMARY KEY (user_id, tipo, data))")
            await self.bot.db_manager.execute_query("CREATE TABLE IF NOT EXISTS submissoes_taxa (message_id BIGINT PRIMARY KEY, user_id BIGINT, status TEXT)")
            await self.bot.db_manager.execute_query("CREATE TABLE IF NOT EXISTS puxadas_log (puxador_id BIGINT, data DATE, quantidade INTEGER, PRIMARY KEY (puxador_id, data))")
            await self.bot.db_manager.execute_query("CREATE TABLE IF NOT EXISTS reacoes_anuncios (user_id BIGINT, message_id BIGINT, PRIMARY KEY (user_id, message_id))")

            # --- ATUALIZAÇÃO ESTRUTURAL DA TABELA DE EVENTOS ---
            # A tabela 'eventos' antiga será expandida com novas colunas.
            # O ideal é fazer um ALTER TABLE, mas para garantir a compatibilidade, vamos criar a nova estrutura.
            # NOTA: Eventos antigos podem não ser totalmente compatíveis, mas não serão perdidos.
            await self.bot.db_manager.execute_query("""
                CREATE TABLE IF NOT EXISTS eventos_v2 (
                    id SERIAL PRIMARY KEY,
                    nome TEXT NOT NULL,
                    descricao TEXT,
                    tipo_evento TEXT,
                    data_evento TIMESTAMP WITH TIME ZONE,
                    recompensa INTEGER DEFAULT 0,
                    meta_participacao INTEGER DEFAULT 1,
                    max_participantes INTEGER,
                    criador_id BIGINT NOT NULL,
                    message_id BIGINT,
                    status TEXT DEFAULT 'AGENDADO',
                    inscritos BIGINT[] DEFAULT '{}'::BIGINT[]
                )
            """)
            try:
                # Renomeia a tabela antiga se ela existir, para não perder dados.
                await self.bot.db_manager.execute_query("ALTER TABLE IF EXISTS eventos RENAME TO eventos_v1_deprecated")
                # Cria a nova tabela com o nome correto.
                await self.bot.db_manager.execute_query("ALTER TABLE IF EXISTS eventos_v2 RENAME TO eventos")
            except Exception as e:
                print(f"Nota de migração: Não foi possível renomear a tabela de eventos. Pode já estar no formato v2. Erro: {e}")

            default_configs = {
                'lastro_total_prata': '0', 'taxa_conversao_prata': '1000',
                'taxa_semanal_valor': '500', 'taxa_dia_semana': '6', 'cargo_membro': '0', 'cargo_inadimplente': '0', 'cargo_isento': '0',
                'perm_nivel_1': '0', 'perm_nivel_2': '0', 'perm_nivel_3': '0', 'perm_nivel_4': '0',
                'canal_aprovacao': '0', 'canal_mercado': '0', 'canal_orbes': '0', 'canal_anuncios': '0',
                'canal_resgates': '0', 'canal_batepapo': '0', 'canal_log_taxas': '0',
                'canal_eventos': '0', # <-- NOVA CONFIGURAÇÃO
                'recompensa_voz': '1', 'limite_voz': '120',
                'recompensa_chat': '1', 'limite_chat': '100', 'cooldown_chat': '60',
                'recompensa_reacao': '50',
                'recompensa_puxar_bronze': '100', 'recompensa_puxar_ouro': '250',
                'limite_puxadas_diario': '5'
            }

            for chave, valor in default_configs.items():
                await self.bot.db_manager.execute_query("INSERT INTO configuracoes (chave, valor) VALUES ($1, $2) ON CONFLICT (chave) DO NOTHING", chave, valor)

            await self.bot.db_manager.execute_query("INSERT INTO banco (user_id, saldo) VALUES ($1, 0) ON CONFLICT (user_id) DO NOTHING", 1)

            print("Base de dados Supabase verificada e pronta (Estrutura de Eventos v2).")
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

        perm_nivel_4_role = guild.get_role(int(await self.bot.db_manager.get_config_value('perm_nivel_4', '0')))
        admin_overwrites = { 
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(view_channel=True)
        }
        if perm_nivel_4_role: 
            admin_overwrites[perm_nivel_4_role] = discord.PermissionOverwrite(view_channel=True)

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
        await self.create_and_pin(ctx, category=cat_bank, name="🏆｜eventos-e-missões", embed=embed)

        embed = discord.Embed(title="🔮｜Submeter Orbes", description="Apanhou uma orbe? Registe-a aqui para ganhar uma recompensa para si e para o seu grupo!", color=0x9b59b6)
        embed.add_field(name="Como Submeter", value="Anexe o print da captura da orbe nesta sala e use o comando:\n`!orbe <cor> <@membro1> <@membro2> ...`", inline=False)
        await self.create_and_pin(ctx, category=cat_bank, name="🔮｜submeter-orbes", embed=embed, set_config_key='canal_orbes')
        
        # 2. Categoria de Taxas
        cat_taxas = await guild.create_category("💸 TAXA SEMANAL")
        await asyncio.sleep(1.5)

        embed = discord.Embed(title="ℹ️｜Como Funciona a Taxa", description="A taxa semanal é um sistema automático que ajuda a financiar os projetos e as atividades da guilda.", color=0x7f8c8d)
        embed.add_field(name="Como funciona?", value="Uma vez por semana, o bot irá verificar a sua situação. Se estiver inadimplente, o seu cargo será temporariamente alterado, restringindo o seu acesso.", inline=False)
        embed.add_field(name="Como Regularizar?", value="Vá ao canal `🪙｜pagamento-de-taxas` e use `!pagar-taxa` ou `!paguei-prata`.", inline=False)
        await self.create_and_pin(ctx, category=cat_taxas, name="ℹ️｜como-funciona-a-taxa", embed=embed, overwrites={guild.default_role: discord.PermissionOverwrite(send_messages=False)})
        
        embed = discord.Embed(title="🪙｜Pagamento de Taxas", description="Use este canal para regularizar a sua situação se estiver com a taxa em atraso.", color=0x95a5a6)
        embed.add_field(name="Pagar com Moedas", value="Use o comando `!pagar-taxa`.", inline=False)
        embed.add_field(name="Pagar com Prata", value="Anexe o print do comprovativo de pagamento no jogo e use o comando `!paguei-prata`.", inline=False)
        await self.create_and_pin(ctx, category=cat_taxas, name="🪙｜pagamento-de-taxas", embed=embed)

        # 3. Categoria de Administração
        cat_admin = await guild.create_category("⚙️ ADMINISTRAÇÃO", overwrites=admin_overwrites)
        await asyncio.sleep(1.5)
        
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
        
        # Converte a lista de cargos para uma string de IDs separados por vírgula
        ids_cargos_str = ",".join(str(c.id) for c in cargos)
        chave = f"perm_nivel_{nivel}"
        await self.bot.db_manager.set_config_value(chave, ids_cargos_str)

        mencoes_cargos = ", ".join(c.mention for c in cargos)
        await ctx.send(f"✅ Os cargos {mencoes_cargos} foram associados ao **Nível de Permissão {nivel}**.")
    
    @commands.group(name="definircanal", invoke_without_command=True)
    @check_permission_level(4)
    async def definir_canal(self, ctx):
        await ctx.send("Use `!definircanal <tipo> #canal`. Tipos: `anuncios`, `batepapo`, `logtaxas`.")
    
    @definir_canal.command(name="anuncios")
    async def definir_canal_anuncios(self, ctx, canal: discord.TextChannel):
        await self.bot.db_manager.set_config_value("canal_anuncios", str(canal.id))
        await ctx.send(f"✅ O canal de anúncios foi definido como {canal.mention}.")

    @definir_canal.command(name="batepapo")
    async def definir_canal_batepapo(self, ctx, canal: discord.TextChannel):
        await self.bot.db_manager.set_config_value("canal_batepapo", str(canal.id))
        await ctx.send(f"✅ O canal de bate-papo para mensagens de engajamento foi definido como {canal.mention}.")
    
    @definir_canal.command(name="logtaxas")
    async def definir_canal_logtaxas(self, ctx, canal: discord.TextChannel):
        await self.bot.db_manager.set_config_value("canal_log_taxas", str(canal.id))
        await ctx.send(f"✅ O canal de logs das taxas foi definido como {canal.mention}.")

    @commands.command(name="anunciar")
    @check_permission_level(3)
    async def anunciar(self, ctx, tipo_canal: str, *, mensagem: str):
        tipos_validos = {
            "mercado": "canal_mercado",
            "batepapo": "canal_batepapo"
        }
        if tipo_canal.lower() not in tipos_validos:
            return await ctx.send("❌ Tipo de canal inválido. Use `mercado` ou `batepapo`.")
        
        chave_canal = tipos_validos[tipo_canal.lower()]
        canal_id_str = await self.bot.db_manager.get_config_value(chave_canal)

        if not canal_id_str or canal_id_str == '0':
            return await ctx.send(f"⚠️ O canal `{tipo_canal}` ainda não foi configurado. Use `!definircanal`.")

        canal = self.bot.get_channel(int(canal_id_str))
        if not canal:
            return await ctx.send("❌ Canal não encontrado. Verifique se o bot tem acesso a ele.")

        embed = discord.Embed(
            title="📢 Anúncio da Administração",
            description=mensagem,
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text=f"Anunciado por: {ctx.author.display_name}", icon_url=ctx.author.display_avatar.url)
        
        try:
            await canal.send(embed=embed)
            await ctx.send("✅ Anúncio enviado com sucesso!", delete_after=10)
        except discord.Forbidden:
            await ctx.send("❌ O bot não tem permissão para enviar mensagens nesse canal.")

    @commands.command(name="definir-lastro")
    @check_permission_level(4)
    async def definir_lastro(self, ctx, valor: int):
        if valor < 0:
            return await ctx.send("❌ O valor do lastro não pode ser negativo.")
        
        # Salva o valor do lastro na configuração
        await self.bot.db_manager.set_config_value('lastro_total_prata', str(valor))
        
        # Calcula o novo suprimento máximo e atualiza o saldo do tesouro
        taxa_conversao_str = await self.bot.db_manager.get_config_value('taxa_conversao_prata', '1000')
        taxa_conversao = int(taxa_conversao_str)
        
        suprimento_maximo = valor // taxa_conversao if taxa_conversao > 0 else 0
        
        ID_TESOURO_GUILDA = 1
        await self.bot.db_manager.execute_query(
            "UPDATE banco SET saldo = $1 WHERE user_id = $2",
            suprimento_maximo, ID_TESOURO_GUILDA
        )
        
        await ctx.send(f"✅ Lastro total de prata definido para **{valor:,}** 🥈. O tesouro da guilda foi atualizado para **{suprimento_maximo:,}** 🪙.".replace(',', '.'))


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
        if tier_lower not in ['bronze', 'ouro']:
            return await ctx.send("❌ Tier inválido. Use `bronze` ou `ouro`.")
        if valor < 0:
            return await ctx.send("❌ O valor da recompensa não pode ser negativo.")

        chave = f"recompensa_puxar_{tier_lower}"
        await self.bot.db_manager.set_config_value(chave, str(valor))
        await ctx.send(f"✅ Recompensa para puxadas do tier **{tier.capitalize()}** definida para **{valor}** moedas.")

    @commands.command(name="definir-limite-puxadas")
    @check_permission_level(4)
    async def definir_limite_puxadas(self, ctx, limite: int):
        if limite < 0:
            return await ctx.send("❌ O limite não pode ser negativo.")
        
        await self.bot.db_manager.set_config_value('limite_puxadas_diario', str(limite))
        await ctx.send(f"✅ Limite diário de puxadas por membro definido para **{limite}**.")

    @commands.command(
        name="verificarconfig",
        aliases=["verconfig"],
        help="Exibe um painel completo com todas as configurações atuais do bot.",
        hidden=True
    )
    @check_permission_level(4)
    async def verificar_config(self, ctx):
        await ctx.send("🔍 A gerar o relatório completo de configurações do Arauto Bank...")

        # Busca todas as configurações de uma só vez
        todas_as_configs = await self.bot.db_manager.execute_query(
            "SELECT chave, valor FROM configuracoes ORDER BY chave ASC", fetch="all"
        )
        
        configs = {item['chave']: item['valor'] for item in todas_as_configs}

        embed = discord.Embed(
            title="⚙️ Painel de Configuração do Arauto Bank",
            description="Relatório completo de todas as variáveis de sistema.",
            color=discord.Color.orange()
        )

        # Mapeamento de categorias para chaves
        categorias = {
            "Canais do Sistema": ['canal_anuncios', 'canal_aprovacao', 'canal_batepapo', 'canal_log_taxas', 'canal_mercado', 'canal_orbes', 'canal_resgates'],
            "Cargos Funcionais": ['cargo_membro', 'cargo_inadimplente', 'cargo_isento'],
            "Hierarquia de Permissões": ['perm_nivel_1', 'perm_nivel_2', 'perm_nivel_3', 'perm_nivel_4'],
            "Economia Principal": ['lastro_total_prata', 'taxa_conversao_prata'],
            "Sistema de Taxas": ['taxa_semanal_valor', 'taxa_dia_semana'],
            "Renda Passiva": ['recompensa_voz', 'limite_voz', 'recompensa_chat', 'limite_chat', 'cooldown_chat', 'recompensa_reacao'],
            "Eventos (Puxadas)": ['recompensa_puxar_bronze', 'recompensa_puxar_ouro', 'limite_puxadas_diario']
        }

        for nome_categoria, chaves in categorias.items():
            texto_categoria = ""
            for chave in chaves:
                valor = configs.get(chave, "Não definido")
                display_valor = valor

                # Tenta "traduzir" IDs para menções legíveis
                if 'canal' in chave and valor.isdigit() and valor != '0':
                    obj = self.bot.get_channel(int(valor))
                    display_valor = obj.mention if obj else f"⚠️ ID Inválido: `{valor}`"
                elif 'cargo' in chave and valor.isdigit() and valor != '0':
                    obj = ctx.guild.get_role(int(valor))
                    display_valor = obj.mention if obj else f"⚠️ ID Inválido: `{valor}`"
                elif 'perm_nivel' in chave and valor and valor != '0':
                    ids = valor.split(',')
                    mencoes = []
                    for role_id in ids:
                        obj = ctx.guild.get_role(int(role_id))
                        mencoes.append(obj.mention if obj else f"⚠️ ID Inválido: `{role_id}`")
                    display_valor = ", ".join(mencoes)

                texto_categoria += f"**{chave}:** {display_valor}\n"
            
            if texto_categoria:
                embed.add_field(name=f"--- {nome_categoria} ---", value=texto_categoria, inline=False)

        await ctx.send(embed=embed)

    @commands.command(
        name='auditar',
        help='Realiza uma auditoria completa, categorizando todas as fontes de ganho de um membro.',
        usage='!auditar @MembroSuspeito',
        hidden=True
    )
    @check_permission_level(4)
    async def auditar(self, ctx, membro: discord.Member):
        user_id = membro.id
        await ctx.send(f"🔍 A iniciar auditoria económica completa para **{membro.display_name}**. A analisar os livros...")

        transacoes = await self.bot.db_manager.execute_query(
            "SELECT valor, descricao FROM transacoes WHERE user_id = $1 AND tipo = 'deposito' ORDER BY data DESC",
            user_id, fetch="all"
        )

        if not transacoes:
            return await ctx.send(f"Nenhuma transação de ganho encontrada para {membro.display_name}.")

        # defaultdict simplifica a contagem
        categorias = defaultdict(lambda: {'total': 0, 'count': 0})

        # Categorização inteligente das transações
        for t in transacoes:
            desc = t['descricao'].lower() if t['descricao'] else ''
            valor = t['valor']
            
            if desc.startswith("recompensa do evento"):
                categorias['Eventos']['total'] += valor
                categorias['Eventos']['count'] += 1
            elif desc.startswith("recompensa de orbe"):
                categorias['Orbes']['total'] += valor
                categorias['Orbes']['count'] += 1
            elif desc.startswith("renda passiva por atividade em voz"):
                categorias['Renda Passiva (Voz)']['total'] += valor
                categorias['Renda Passiva (Voz)']['count'] += 1
            elif desc.startswith("renda passiva por atividade no chat"):
                categorias['Renda Passiva (Chat)']['total'] += valor
                categorias['Renda Passiva (Chat)']['count'] += 1
            elif desc.startswith("recompensa por reagir"):
                categorias['Reações a Anúncios']['total'] += valor
                categorias['Reações a Anúncios']['count'] += 1
            elif desc.startswith("transferência de"):
                categorias['Transferências Recebidas']['total'] += valor
                categorias['Transferências Recebidas']['count'] += 1
            elif desc.startswith("emissão de moedas") or desc.startswith("airdrop"):
                categorias['Administrativo (Emissão/Airdrop)']['total'] += valor
                categorias['Administrativo (Emissão/Airdrop)']['count'] += 1
            else:
                categorias['Outros Ganhos']['total'] += valor
                categorias['Outros Ganhos']['count'] += 1

        economia_cog = self.bot.get_cog('Economia')
        saldo_atual = await economia_cog.get_saldo(user_id)

        # Monta o relatório completo
        embed = discord.Embed(
            title=f"🕵️‍♂️ Relatório de Auditoria Completo: {membro.display_name}",
            description=f"Análise detalhada de todas as fontes de rendimento registadas.",
            color=discord.Color.dark_blue()
        )
        embed.set_thumbnail(url=membro.display_avatar.url)
        embed.add_field(name="Saldo Atual Total", value=f"**{saldo_atual:,}** 🪙", inline=False)
        
        relatorio_texto = ""
        # Ordena as categorias por valor total para destacar as maiores fontes de renda
        for nome_cat, dados in sorted(categorias.items(), key=lambda item: item[1]['total'], reverse=True):
            relatorio_texto += f"**{nome_cat}:**\n"
            relatorio_texto += f" • Total Ganho: `{dados['total']:,}` 🪙\n"
            relatorio_texto += f" • N.º de Transações: `{dados['count']}`\n"
        
        embed.add_field(name="Discriminação de Ganhos por Categoria", value=relatorio_texto, inline=False)
        embed.set_footer(text="Use estes dados para identificar anomalias e depois corrija com !confiscar")
        await ctx.send(embed=embed)


    @commands.command(
        name='confiscar',
        help='Remove uma quantidade de moedas de um membro e devolve ao tesouro da guilda.',
        usage='!confiscar @MembroSuspeito 50000',
        hidden=True
    )
    @check_permission_level(4)
    async def confiscar(self, ctx, membro: discord.Member, valor: int):
        if valor <= 0:
            return await ctx.send("❌ O valor a confiscar deve ser positivo.")

        user_id = membro.id
        economia_cog = self.bot.get_cog('Economia')
        
        try:
            # Garante que as funções de levantar/depositar são usadas para manter os logs de transações
            await economia_cog.levantar(user_id, valor, f"Confisco administrativo por {ctx.author.name}")
            await economia_cog.depositar(self.ID_TESOURO_GUILDA, valor, f"Devolução de confisco de {membro.name}")

            saldo_final = await economia_cog.get_saldo(user_id)
            
            embed = discord.Embed(
                title="⚖️ Correção de Saldo Realizada",
                description=f"O saldo de **{membro.display_name}** foi corrigido com sucesso.",
                color=discord.Color.dark_red()
            )
            embed.add_field(name="Valor Confiscado", value=f"**{valor:,}** 🪙", inline=True)
            embed.add_field(name="Devolvido ao Tesouro", value="Sim", inline=True)
            embed.add_field(name="Saldo Final do Membro", value=f"**{saldo_final:,}** 🪙", inline=False)
            embed.set_footer(text=f"Ação realizada por: {ctx.author.display_name}")
            
            await ctx.send(embed=embed)

        except ValueError as e:
            await ctx.send(f"❌ **Falha na operação:** {e} (Provavelmente o membro não tem o saldo que está a tentar remover).")
        except Exception as e:
            await ctx.send(f"❌ Ocorreu um erro inesperado durante o confisco: {e}")

    @commands.command(
        name='testar-engajamento',
        help='Força o envio de uma mensagem de engajamento para o canal de bate-papo configurado.',
        hidden=True
    )
    @check_permission_level(4)
    async def testar_engajamento(self, ctx):
        engajamento_cog = self.bot.get_cog('Engajamento')
        if not engajamento_cog:
            return await ctx.send("❌ O módulo de Engajamento não está carregado.")

        try:
            await ctx.send("🚀 A tentar enviar uma mensagem de engajamento de teste...")
            # Chamamos a lógica diretamente
            await engajamento_cog.enviar_mensagem_engajamento()
            await ctx.send("✅ Teste concluído. Verifique o canal de bate-papo.")
        except Exception as e:
            await ctx.send(f"❌ Falha no teste. Erro: {e}")

async def setup(bot):
    # Garante que o Admin cog é adicionado ao bot
    await bot.add_cog(Admin(bot))

