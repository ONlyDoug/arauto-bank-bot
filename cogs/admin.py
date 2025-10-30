import discord
from discord.ext import commands
import asyncio
from datetime import datetime
from utils.permissions import check_permission_level
from collections import defaultdict

# Dicionário de Configurações Padrão
DEFAULT_CONFIGS = {
    'lastro_total_prata': '0', 'taxa_conversao_prata': '1000',
    'taxa_semanal_valor': '500', 'taxa_dia_semana': '6', 'taxa_dia_abertura': '5',
    'taxa_aceitar_moedas': 'true', # Toggle para !pagar-taxa
    'cargo_membro': '0', 'cargo_inadimplente': '0', 'cargo_isento': '0',
    'perm_nivel_1': '', 'perm_nivel_2': '', 'perm_nivel_3': '', 'perm_nivel_4': '',
    'canal_aprovacao': '0', 'canal_mercado': '0', 'canal_orbes': '0', 'canal_anuncios': '0',
    'canal_resgates': '0', 'canal_batepapo': '0', 'canal_log_taxas': '0',
    'canal_eventos': '0', 'canal_planejamento': '0',
    'canal_relatorio_taxas': '0', 'canal_pagamento_taxas': '0', 'canal_info_taxas': '0',
    'taxa_msg_id_pendentes': '0', 'taxa_msg_id_pagos': '0',
    'taxa_msg_id_isentos_novos': '0', 'taxa_msg_id_isentos_cargo': '0',
    'taxa_mensagem_inadimplente': 'Olá {member}! A taxa semanal de {tax_value} moedas não foi paga. O seu acesso foi temporariamente restringido. Use `!pagar-taxa` ou `!paguei-prata` para regularizar.',
    'taxa_mensagem_abertura': '✅ A janela para pagamento da taxa semanal está **ABERTA**! Use `!pagar-taxa` ou `!paguei-prata` até Domingo.',
    'taxa_mensagem_reset': '⚠️ Hoje é o dia do reset das taxas! Este é o último dia para efetuar o pagamento e evitar a restrição de acesso.',
    'taxa_mensagem_fechamento': '❌ A janela de pagamento de taxas está **FECHADA**. O canal será limpo em breve.',
    'recompensa_voz': '1', 'limite_voz': '120', 'recompensa_chat': '1', 'limite_chat': '100', 'cooldown_chat': '60', 'recompensa_reacao': '50',
}

class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.ID_TESOURO_GUILDA = 1

    async def initialize_database_schema(self):
        try:
            # Cria/Verifica Tabelas Essenciais
            await self.bot.db_manager.execute_query("CREATE TABLE IF NOT EXISTS banco (user_id BIGINT PRIMARY KEY, saldo BIGINT NOT NULL DEFAULT 0)")
            await self.bot.db_manager.execute_query("""CREATE TABLE IF NOT EXISTS transacoes (id SERIAL PRIMARY KEY, user_id BIGINT NOT NULL, tipo TEXT NOT NULL, valor BIGINT NOT NULL, descricao TEXT, data TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP)""")
            await self.bot.db_manager.execute_query("CREATE TABLE IF NOT EXISTS configuracoes (chave TEXT PRIMARY KEY, valor TEXT NOT NULL)")
            await self.bot.db_manager.execute_query("""CREATE TABLE IF NOT EXISTS taxas (user_id BIGINT PRIMARY KEY, status_ciclo TEXT DEFAULT 'PENDENTE', data_entrada TIMESTAMPTZ)""")
            try: # Garante compatibilidade
                await self.bot.db_manager.execute_query("ALTER TABLE taxas ADD COLUMN IF NOT EXISTS status_ciclo TEXT DEFAULT 'PENDENTE'")
                await self.bot.db_manager.execute_query("ALTER TABLE taxas ADD COLUMN IF NOT EXISTS data_entrada TIMESTAMPTZ")
            except Exception as e: print(f"Nota (taxas): {e}")

            await self.bot.db_manager.execute_query("""CREATE TABLE IF NOT EXISTS submissoes_orbe (id SERIAL PRIMARY KEY, message_id BIGINT, cor TEXT NOT NULL, valor_total INTEGER NOT NULL, autor_id BIGINT, membros TEXT, status TEXT DEFAULT 'pendente')""")
            await self.bot.db_manager.execute_query("CREATE TABLE IF NOT EXISTS loja (id SERIAL PRIMARY KEY, nome TEXT NOT NULL, preco INTEGER NOT NULL, descricao TEXT)")
            await self.bot.db_manager.execute_query("CREATE TABLE IF NOT EXISTS renda_passiva_log (user_id BIGINT, tipo TEXT, data DATE, valor INTEGER, PRIMARY KEY (user_id, tipo, data))")
            await self.bot.db_manager.execute_query("CREATE TABLE IF NOT EXISTS submissoes_taxa (id SERIAL PRIMARY KEY, message_id BIGINT, user_id BIGINT, status TEXT, anexo_url TEXT)")
            try: # Garante compatibilidade
                 await self.bot.db_manager.execute_query("ALTER TABLE submissoes_taxa ADD COLUMN IF NOT EXISTS id SERIAL")
                 await self.bot.db_manager.execute_query("ALTER TABLE submissoes_taxa ADD COLUMN IF NOT EXISTS anexo_url TEXT")
                 await self.bot.db_manager.execute_query("ALTER TABLE submissoes_taxa DROP CONSTRAINT IF EXISTS submissoes_taxa_pkey")
                 await self.bot.db_manager.execute_query("ALTER TABLE submissoes_taxa ADD PRIMARY KEY (id)")
            except Exception as e: print(f"Nota (submissoes_taxa): {e}")
            await self.bot.db_manager.execute_query("CREATE TABLE IF NOT EXISTS reacoes_anuncios (user_id BIGINT, message_id BIGINT, PRIMARY KEY (user_id, message_id))")
            await self.bot.db_manager.execute_query("""CREATE TABLE IF NOT EXISTS eventos (id SERIAL PRIMARY KEY, nome TEXT NOT NULL, descricao TEXT, tipo_evento TEXT, data_evento TIMESTAMPTZ, recompensa INTEGER DEFAULT 0, max_participantes INTEGER, criador_id BIGINT NOT NULL, message_id BIGINT, status TEXT DEFAULT 'AGENDADO', inscritos BIGINT[] DEFAULT '{}'::BIGINT[], cargo_requerido_id BIGINT, canal_voz_id BIGINT)""")

            # Garante Configs Padrão
            await self.bot.db_manager.execute_query(
                 "INSERT INTO configuracoes (chave, valor) SELECT * FROM UNNEST($1::TEXT[], $2::TEXT[]) ON CONFLICT (chave) DO NOTHING",
                 list(DEFAULT_CONFIGS.keys()), list(DEFAULT_CONFIGS.values())
            )
            # Garante Tesouro
            await self.bot.db_manager.execute_query("INSERT INTO banco (user_id, saldo) VALUES ($1, 0) ON CONFLICT (user_id) DO NOTHING", self.ID_TESOURO_GUILDA)
            print("Base de dados verificada (Estrutura Final v3.2).")
        except Exception as e: print(f"❌ Erro CRÍTICO ao inicializar DB: {e}"); raise e

    @commands.command(name='initdb', hidden=True)
    @commands.is_owner()
    async def initdb(self, ctx):
        await ctx.send("Forçando verificação da base de dados...")
        try:
            await self.initialize_database_schema(); await ctx.send("✅ Verificação concluída.")
        except Exception as e: await ctx.send(f"❌ Falha: {e}")

    async def create_and_pin(self, ctx, *, category, name, embed, overwrites=None, set_config_key=None):
        try:
            channel = await category.create_text_channel(name, overwrites=overwrites or {})
            await asyncio.sleep(1.5) # Pausa para garantir que o canal está totalmente criado
            msg = await channel.send(embed=embed); await msg.pin()
            if set_config_key: await self.bot.db_manager.set_config_value(set_config_key, str(channel.id))
            return channel
        except Exception as e: await ctx.send(f"⚠️ Erro ao criar canal `{name}`: {e}")

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

        # Permissões para canais de staff (Nível 1-4)
        perm_roles_ids = set()
        for i in range(1, 5):
            role_ids_str = await self.bot.db_manager.get_config_value(f'perm_nivel_{i}', '')
            if role_ids_str:
                perm_roles_ids.update(r_id for r_id in role_ids_str.split(',') if r_id.isdigit())
        
        admin_overwrites = { 
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(view_channel=True)
        }
        for role_id in perm_roles_ids:
            if role := guild.get_role(int(role_id)):
                admin_overwrites[role] = discord.PermissionOverwrite(view_channel=True)

        # 1. Categoria Principal
        cat_bank = await guild.create_category("🏦 ARAUTO BANK")
        await asyncio.sleep(1.5)
        
        embed = discord.Embed(title="🎓｜Como Usar o Arauto Bank", description="Bem-vindo! Use `!ajuda` para ver os comandos.", color=0xffd700)
        await self.create_and_pin(ctx, category=cat_bank, name="🎓｜como-usar-o-bot", embed=embed, overwrites={guild.default_role: discord.PermissionOverwrite(send_messages=False)})
        embed = discord.Embed(title="📈｜Mercado Financeiro", description="Use `!info-moeda` para ver a saúde da nossa economia.", color=0x1abc9c)
        await self.create_and_pin(ctx, category=cat_bank, name="📈｜mercado-financeiro", embed=embed, set_config_key='canal_mercado', overwrites={guild.default_role: discord.PermissionOverwrite(send_messages=False)})
        embed = discord.Embed(title="💰｜Minha Conta", description="Comandos: `!saldo`, `!extrato`, `!transferir`.", color=0x2ecc71)
        await self.create_and_pin(ctx, category=cat_bank, name="💰｜minha-conta", embed=embed)
        embed = discord.Embed(title="🛍️｜Loja da Guilda", description="Comandos: `!loja`, `!comprar`.", color=0x3498db)
        await self.create_and_pin(ctx, category=cat_bank, name="🛍️｜loja-da-guilda", embed=embed)
        embed = discord.Embed(title="🏆｜Eventos e Missões", description="Comandos: `!listareventos`, `!participar`.", color=0xe91e63)
        await self.create_and_pin(ctx, category=cat_bank, name="🏆｜eventos-e-missões", embed=embed, set_config_key='canal_eventos')
        embed = discord.Embed(title="🔮｜Submeter Orbes", description="Comando: `!orbe <cor> <@membros...>`", color=0x9b59b6)
        await self.create_and_pin(ctx, category=cat_bank, name="🔮｜submeter-orbes", embed=embed, set_config_key='canal_orbes')
        
        # 2. Categoria de Taxas
        cat_taxas = await guild.create_category("💸 TAXA SEMANAL")
        await asyncio.sleep(1.5)
        embed = discord.Embed(title="ℹ️｜Como Funciona a Taxa", description="Este canal explica o sistema de taxas.", color=0x7f8c8d)
        await self.create_and_pin(ctx, category=cat_taxas, name="ℹ️｜como-funciona-a-taxa", embed=embed, overwrites={guild.default_role: discord.PermissionOverwrite(send_messages=False)}, set_config_key='canal_info_taxas')
        embed = discord.Embed(title="🪙｜Pagamento de Taxas", description="Comandos: `!pagar-taxa`, `!paguei-prata`, `!ajudataxa`.", color=0x95a5a6)
        await self.create_and_pin(ctx, category=cat_taxas, name="🪙｜pagamento-de-taxas", embed=embed, set_config_key='canal_pagamento_taxas')

        # 3. Categoria de Administração
        cat_admin = await guild.create_category("⚙️ ADMINISTRAÇÃO", overwrites=admin_overwrites)
        await asyncio.sleep(1.5)
        embed = discord.Embed(title="📋｜Planeamento de Eventos", description="Comando: `!agendarevento`.", color=0x546e7a)
        await self.create_and_pin(ctx, category=cat_admin, name="📋｜planeamento", embed=embed, set_config_key='canal_planejamento')
        embed = discord.Embed(title="📈｜Relatório de Taxas", description="Relatório automático do status das taxas.", color=0x71368a)
        await self.create_and_pin(ctx, category=cat_admin, name="📈｜relatorio-de-taxas", embed=embed, overwrites={guild.default_role: discord.PermissionOverwrite(send_messages=False)}, set_config_key='canal_relatorio_taxas')
        embed = discord.Embed(title="✅｜Aprovações", description="Canal para aprovações de submissões.", color=0xf1c40f)
        await self.create_and_pin(ctx, category=cat_admin, name="✅｜aprovações", embed=embed, set_config_key='canal_aprovacao')
        embed = discord.Embed(title="🚨｜Resgates Staff", description="Logs de compras na loja e resgates de moedas.", color=0xe74c3c)
        await self.create_and_pin(ctx, category=cat_admin, name="🚨｜resgates-staff", embed=embed, set_config_key='canal_resgates')
        embed = discord.Embed(title="🔩｜Comandos Admin", description="Canal para comandos de gestão.", color=0xe67e22)
        await self.create_and_pin(ctx, category=cat_admin, name="🔩｜comandos-admin", embed=embed)
        embed = discord.Embed(title="📊｜Logs de Taxas", description="Logs detalhados dos ciclos de taxas.", color=0x546e7a)
        await self.create_and_pin(ctx, category=cat_admin, name="📊｜logs-de-taxas", embed=embed, set_config_key='canal_log_taxas')
        
        await msg_progresso.edit(content="✅ Estrutura de canais final criada e configurada com sucesso!")


    @commands.group(name="cargo", invoke_without_command=True, hidden=True)
    @check_permission_level(4)
    async def cargo(self, ctx):
        await ctx.send("Use `!cargo definir <tipo> <@cargo>` ou `!cargo permissao <nível> <@cargo(s)>`.")
    @cargo.command(name="definir", hidden=True)
    @check_permission_level(4)
    async def cargo_definir(self, ctx, tipo: str, cargo: discord.Role):
        tipos_validos = ['membro', 'inadimplente', 'isento']
        if tipo.lower() not in tipos_validos: return await ctx.send(f"❌ Tipo inválido. Válidos: `{', '.join(tipos_validos)}`")
        await self.bot.db_manager.set_config_value(f"cargo_{tipo.lower()}", str(cargo.id))
        await ctx.send(f"✅ Cargo **{tipo.capitalize()}** definido como {cargo.mention}.")
    @cargo.command(name="permissao", hidden=True)
    @check_permission_level(4)
    async def cargo_permissao(self, ctx, nivel: int, cargos: commands.Greedy[discord.Role]):
        if not 1 <= nivel <= 4: return await ctx.send("❌ Nível deve ser 1-4.")
        if not cargos: return await ctx.send("❌ Mencione pelo menos um cargo.")
        ids_cargos_str = ",".join(str(c.id) for c in cargos)
        await self.bot.db_manager.set_config_value(f"perm_nivel_{nivel}", ids_cargos_str)
        await ctx.send(f"✅ Cargos associados ao **Nível {nivel}**: {', '.join(c.mention for c in cargos)}.")
    
    @commands.group(name="definircanal", invoke_without_command=True, hidden=True)
    @check_permission_level(4)
    async def definir_canal(self, ctx):
         tipos = [k.replace('canal_', '') for k in DEFAULT_CONFIGS.keys() if k.startswith('canal_')]
         await ctx.send(f"Use `!definircanal <tipo> #canal`. Tipos: `{', '.join(sorted(tipos))}`.")
    async def _definir_canal_generico(self, ctx, tipo, canal):
        chave = f"canal_{tipo}"
        if chave not in DEFAULT_CONFIGS: return await ctx.send("❌ Tipo de canal inválido.")
        await self.bot.db_manager.set_config_value(chave, str(canal.id))
        await ctx.send(f"✅ Canal para `{tipo}` definido como {canal.mention}.")
    @definir_canal.command(name="planejamento", hidden=True)
    async def definir_canal_planejamento(self, ctx, canal: discord.TextChannel): await self._definir_canal_generico(ctx, "planejamento", canal)
    @definir_canal.command(name="eventos", hidden=True)
    async def definir_canal_eventos(self, ctx, canal: discord.TextChannel): await self._definir_canal_generico(ctx, "eventos", canal)
    @definir_canal.command(name="anuncios", hidden=True)
    async def definir_canal_anuncios(self, ctx, canal: discord.TextChannel): await self._definir_canal_generico(ctx, "anuncios", canal)
    @definir_canal.command(name="batepapo", hidden=True)
    async def definir_canal_batepapo(self, ctx, canal: discord.TextChannel): await self._definir_canal_generico(ctx, "batepapo", canal)
    @definir_canal.command(name="aprovacao", hidden=True)
    async def definir_canal_aprovacao(self, ctx, canal: discord.TextChannel): await self._definir_canal_generico(ctx, "aprovacao", canal)
    @definir_canal.command(name="logtaxas", hidden=True)
    async def definir_canal_logtaxas(self, ctx, canal: discord.TextChannel): await self._definir_canal_generico(ctx, "log_taxas", canal)
    @definir_canal.command(name="resgates", hidden=True)
    async def definir_canal_resgates(self, ctx, canal: discord.TextChannel): await self._definir_canal_generico(ctx, "resgates", canal)
    @definir_canal.command(name="relatoriotaxas", hidden=True)
    async def definir_canal_relatorio_taxas(self, ctx, canal: discord.TextChannel): await self._definir_canal_generico(ctx, "relatorio_taxas", canal)
    @definir_canal.command(name="pagamentotaxas", hidden=True)
    async def definir_canal_pagamento_taxas(self, ctx, canal: discord.TextChannel): await self._definir_canal_generico(ctx, "pagamento_taxas", canal)
    @definir_canal.command(name="infotaxas", hidden=True)
    async def definir_canal_info_taxas(self, ctx, canal: discord.TextChannel): await self._definir_canal_generico(ctx, "info_taxas", canal)
    @definir_canal.command(name="mercado", hidden=True)
    async def definir_canal_mercado(self, ctx, canal: discord.TextChannel): await self._definir_canal_generico(ctx, "mercado", canal)
    @definir_canal.command(name="orbes", hidden=True)
    async def definir_canal_orbes(self, ctx, canal: discord.TextChannel): await self._definir_canal_generico(ctx, "orbes", canal)

    @commands.group(name="definirmsg", invoke_without_command=True, hidden=True)
    @check_permission_level(4)
    async def definir_msg(self, ctx):
        await ctx.send("Use `!definirmsg <tipo> <mensagem>`. Tipos: `taxa_inadimplente`, `taxa_abertura`, `taxa_reset`, `taxa_fechamento`.")
    @definir_msg.command(name="taxa_inadimplente", hidden=True)
    async def definir_msg_taxa_inadimplente(self, ctx, *, mensagem: str):
        await self.bot.db_manager.set_config_value("taxa_mensagem_inadimplente", mensagem)
        await ctx.send(f"✅ Mensagem para inadimplentes definida!\n**Preview:**\n{mensagem.format(member=ctx.author.mention, tax_value=123)}")
    @definir_msg.command(name="taxa_abertura", hidden=True)
    async def definir_msg_taxa_abertura(self, ctx, *, mensagem: str):
        await self.bot.db_manager.set_config_value("taxa_mensagem_abertura", mensagem)
        await ctx.send(f"✅ Mensagem de abertura definida!\n**Preview:**\n{mensagem}")
    @definir_msg.command(name="taxa_reset", hidden=True)
    async def definir_msg_taxa_reset(self, ctx, *, mensagem: str):
        await self.bot.db_manager.set_config_value("taxa_mensagem_reset", mensagem)
        await ctx.send(f"✅ Mensagem do dia de reset definida!\n**Preview:**\n{mensagem}")
    @definir_msg.command(name="taxa_fechamento", hidden=True)
    async def definir_msg_taxa_fechamento(self, ctx, *, mensagem: str):
        await self.bot.db_manager.set_config_value("taxa_mensagem_fechamento", mensagem)
        await ctx.send(f"✅ Mensagem de fechamento definida!\n**Preview:**\n{mensagem}")

    @commands.group(name="configtaxa", invoke_without_command=True, hidden=True)
    @check_permission_level(4)
    async def config_taxa(self, ctx): await ctx.send("Use `!configtaxa moedas <on|off>`.")
    @config_taxa.command(name="moedas", hidden=True)
    async def config_taxa_moedas(self, ctx, estado: str):
        valor_bool = 'true' if estado.lower() == 'on' else 'false'
        await self.bot.db_manager.set_config_value('taxa_aceitar_moedas', valor_bool)
        await ctx.send(f"✅ Pagamento com moedas (`!pagar-taxa`) **{'ATIVADO' if valor_bool == 'true' else 'DESATIVADO'}**.")

    @commands.command(name="verificarconfig", aliases=["verconfig"], hidden=True)
    @check_permission_level(4)
    async def verificar_config(self, ctx):
        await ctx.send("🔍 Gerando relatório completo de configurações...")
        configs = await self.bot.db_manager.execute_query("SELECT chave, valor FROM configuracoes ORDER BY chave ASC", fetch="all")
        configs_dict = {item['chave']: item['valor'] for item in configs}

        embed = discord.Embed(title="⚙️ Painel de Configuração Completo", color=discord.Color.orange())
        categorias = {
            "Canais": sorted([k for k in DEFAULT_CONFIGS.keys() if k.startswith('canal_')]),
            "Cargos": ['cargo_membro', 'cargo_inadimplente', 'cargo_isento'],
            "Permissões": ['perm_nivel_1', 'perm_nivel_2', 'perm_nivel_3', 'perm_nivel_4'],
            "Economia": ['lastro_total_prata', 'taxa_conversao_prata'],
            "Taxas Config": ['taxa_semanal_valor', 'taxa_dia_semana', 'taxa_dia_abertura', 'taxa_aceitar_moedas'],
            "Mensagens Taxas": ['taxa_mensagem_inadimplente', 'taxa_mensagem_abertura', 'taxa_mensagem_reset', 'taxa_mensagem_fechamento'],
            "IDs Msgs Relatório Taxas": sorted([k for k in DEFAULT_CONFIGS.keys() if k.startswith('taxa_msg_id_')]),
            "Renda Passiva": ['recompensa_voz', 'limite_voz', 'recompensa_chat', 'limite_chat', 'cooldown_chat', 'recompensa_reacao'],
        }
        known_keys = {k for cat_keys in categorias.values() for k in cat_keys}
        other_keys = sorted([k for k in configs_dict if k not in known_keys and k not in DEFAULT_CONFIGS]) # Apenas extras
        if other_keys: categorias["Outras Configurações"] = other_keys

        for nome_cat, chaves in categorias.items():
            texto = ""
            for chave in chaves:
                valor = configs_dict.get(chave, "*Não Definido*")
                if valor != "*Não Definido*":
                    try:
                        if 'canal' in chave and valor.isdigit() and valor != '0':
                             c = self.bot.get_channel(int(valor))
                             valor = c.mention if c else f"⚠️ ID `{valor}` Inv/Acesso"
                        elif 'cargo' in chave and valor.isdigit() and valor != '0':
                             r = ctx.guild.get_role(int(valor))
                             valor = r.mention if r else f"⚠️ ID `{valor}` Inválido"
                        elif 'perm_nivel' in chave and valor:
                             mencoes = []
                             for rid_str in valor.split(','):
                                 if rid_str.isdigit() and (r := ctx.guild.get_role(int(rid_str))):
                                     mencoes.append(r.mention)
                             valor = ", ".join(mencoes) if mencoes else "*Nenhum Cargo*"
                        elif '_msg_id_' in chave and valor == '0':
                            valor = "*Não criada*"
                        elif chave == 'taxa_mensagem_inadimplente':
                            valor = f"`{valor[:50]}...`" # Encurta a mensagem
                    except Exception: valor = f"⚠️ Erro ({valor})"
                texto += f"**{chave}:** {valor}\n"
            if texto: embed.add_field(name=f"--- {nome_cat} ---", value=texto, inline=False)
        await ctx.send(embed=embed)

    # --- Grupo !auditar (inalterado) ---
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

    # --- Comando !verificarconfig atualizado ---
    @commands.command(name="verificarconfig", aliases=["verconfig"], hidden=True)
    @check_permission_level(4)
    async def verificar_config(self, ctx):
        await ctx.send("🔍 Gerando relatório completo de configurações...")
        configs = await self.bot.db_manager.execute_query("SELECT chave, valor FROM configuracoes ORDER BY chave ASC", fetch="all")
        configs_dict = {item['chave']: item['valor'] for item in configs}

        embed = discord.Embed(title="⚙️ Painel de Configuração Completo", color=discord.Color.orange())
        # Define as categorias e as chaves dentro delas
        categorias = {
            "Canais": sorted([k for k in DEFAULT_CONFIGS.keys() if k.startswith('canal_')]),
            "Cargos": ['cargo_membro', 'cargo_inadimplente', 'cargo_isento'],
            "Permissões": ['perm_nivel_1', 'perm_nivel_2', 'perm_nivel_3', 'perm_nivel_4'],
            "Economia": ['lastro_total_prata', 'taxa_conversao_prata'],
            "Taxas Config": ['taxa_semanal_valor', 'taxa_dia_semana', 'taxa_dia_abertura', 'taxa_aceitar_moedas'],
            "Mensagens Taxas": ['taxa_mensagem_inadimplente', 'taxa_mensagem_abertura', 'taxa_mensagem_reset', 'taxa_mensagem_fechamento'],
            "IDs Msgs Relatório Taxas": sorted([k for k in DEFAULT_CONFIGS.keys() if k.startswith('taxa_msg_id_')]),
            "Renda Passiva": ['recompensa_voz', 'limite_voz', 'recompensa_chat', 'limite_chat', 'cooldown_chat', 'recompensa_reacao'],
        }
        # Adiciona chaves não categorizadas, se houver
        known_keys = {k for cat_keys in categorias.values() for k in cat_keys}
        other_keys = sorted([k for k in configs_dict if k not in known_keys and k not in DEFAULT_CONFIGS]) # Apenas extras
        if other_keys: categorias["Outras Configurações"] = other_keys

        for nome_cat, chaves in categorias.items():
            texto = ""
            for chave in chaves: # Itera sobre as chaves na ordem definida
                valor = configs_dict.get(chave, "*Não Definido*")
                # Formatação (copiada da versão anterior, deve estar correta)
                if valor != "*Não Definido*":
                    try:
                        if 'canal' in chave and valor.isdigit() and valor != '0':
                             c = self.bot.get_channel(int(valor)) or await self.bot.fetch_channel(int(valor))
                             valor = c.mention if c else f"⚠️ ID `{valor}` Inv/Acesso"
                        elif 'cargo' in chave and valor.isdigit() and valor != '0':
                             r = ctx.guild.get_role(int(valor))
                             valor = r.mention if r else f"⚠️ ID `{valor}` Inválido"
                        elif 'perm_nivel' in chave and valor:
                             mencoes = []
                             for rid_str in valor.split(','):
                                 if rid_str.isdigit() and (r := ctx.guild.get_role(int(rid_str))):
                                     mencoes.append(r.mention)
                             valor = ", ".join(mencoes) if mencoes else "*Nenhum Cargo*"
                        elif '_msg_id_' in chave and valor == '0':
                            valor = "*Não criada*"
                        elif chave == 'taxa_mensagem_inadimplente':
                            valor = f"`{valor[:50]}...`" # Encurta a mensagem
                    except Exception: valor = f"⚠️ Erro ({valor})"
                texto += f"**{chave}:** {valor}\n"

            # Adiciona o campo ao embed se houver conteúdo
            if texto:
                # Limita o valor do campo a 1024 caracteres
                if len(texto) > 1024:
                    texto = texto[:1020] + "\n..."
                embed.add_field(name=f"--- {nome_cat} ---", value=texto, inline=False)

        await ctx.send(embed=embed)


    @commands.group(name="configtaxa", invoke_without_command=True, hidden=True)
    @check_permission_level(4)
    async def config_taxa(self, ctx): await ctx.send("Use `!configtaxa moedas <on|off>`.")
    @config_taxa.command(name="moedas", hidden=True)
    async def config_taxa_moedas(self, ctx, estado: str):
        valor_bool = 'true' if estado.lower() == 'on' else 'false'
        await self.bot.db_manager.set_config_value('taxa_aceitar_moedas', valor_bool)
        await ctx.send(f"✅ Pagamento com moedas (`!pagar-taxa`) **{'ATIVADO' if valor_bool == 'true' else 'DESATIVADO'}**.")
    
    # ... (outros comandos admin inalterados) ...

async def setup(bot): await bot.add_cog(Admin(bot))

