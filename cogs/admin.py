import discord
from discord.ext import commands
import asyncio
from datetime import datetime
from utils.permissions import check_permission_level

class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # O db_manager é acedido através de self.bot.db_manager

    async def initialize_database_schema(self):
        try:
            with self.bot.db_manager.get_connection() as conn:
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
                    cursor.execute("CREATE TABLE IF NOT EXISTS loja (id INTEGER PRIMARY KEY, nome TEXT NOT NULL, preco INTEGER NOT NULL, descricao TEXT)")
                    cursor.execute("CREATE TABLE IF NOT EXISTS renda_passiva_log (user_id BIGINT, tipo TEXT, data DATE, valor INTEGER, PRIMARY KEY (user_id, tipo, data))")
                    cursor.execute("CREATE TABLE IF NOT EXISTS submissoes_taxa (message_id BIGINT PRIMARY KEY, user_id BIGINT, status TEXT, url_imagem TEXT)")
                    
                    default_configs = {
                        'lastro_total_prata': '0', 'taxa_conversao_prata': '1000',
                        'taxa_semanal_valor': '500', 'cargo_membro': '0', 'cargo_inadimplente': '0', 'cargo_isento': '0',
                        'perm_nivel_1': '0', 'perm_nivel_2': '0', 'perm_nivel_3': '0', 'perm_nivel_4': '0',
                        'canal_aprovacao': '0', 'canal_mercado': '0', 'canal_orbes': '0', 'canal_anuncios': '0',
                        'canal_resgates': '0', 'canal_batepapo': '0',
                        'recompensa_voz': '1', 'limite_voz': '120',
                        'recompensa_chat': '1', 'limite_chat': '100', 'cooldown_chat': '60',
                        'recompensa_reacao': '50'
                    }
                    for chave, valor in default_configs.items():
                        cursor.execute("INSERT INTO configuracoes (chave, valor) VALUES (%s, %s) ON CONFLICT (chave) DO NOTHING", (chave, valor))
                    
                    cursor.execute("INSERT INTO banco (user_id, saldo) VALUES (%s, 0) ON CONFLICT (user_id) DO NOTHING", (1,))
                conn.commit()
            print("Base de dados Supabase verificada e pronta.")
        except Exception as e:
            print(f"❌ Ocorreu um erro ao inicializar a base de dados: {e}")
            raise e

    @commands.command(name='initdb')
    @commands.has_permissions(administrator=True)
    async def initdb(self, ctx):
        await ctx.send("A forçar a verificação da base de dados...")
        await self.initialize_database_schema()
        await ctx.send("✅ Verificação da base de dados concluída.")

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
                await asyncio.sleep(2)
        
        await msg_progresso.edit(content="🔥 Estrutura antiga removida. A criar a nova...")

        perm_nivel_4_id = int(self.bot.db_manager.get_config_value('perm_nivel_4', '0'))
        perm_nivel_4_role = guild.get_role(perm_nivel_4_id)
        admin_overwrites = { 
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(view_channel=True)
        }
        if perm_nivel_4_role: 
            admin_overwrites[perm_nivel_4_role] = discord.PermissionOverwrite(view_channel=True)

        async def create_and_pin(category, name, embed, overwrites=None, set_config_key=None):
            try:
                channel = await category.create_text_channel(name, overwrites=overwrites)
                await asyncio.sleep(2)
                msg = await channel.send(embed=embed)
                await msg.pin()
                if set_config_key and channel:
                    self.bot.db_manager.set_config_value(set_config_key, str(channel.id))
                return channel
            except discord.Forbidden as e:
                await ctx.send(f"❌ Erro de permissão ao criar o canal `{name}`: {e}")
            except Exception as e:
                await ctx.send(f"⚠️ Ocorreu um erro inesperado ao criar o canal `{name}`: {e}")
            return None

        # 1. Categoria Principal
        cat_bank = await guild.create_category("🏦 ARAUTO BANK")
        await asyncio.sleep(2)
        
        embed = discord.Embed(title="🎓｜Como Usar o Arauto Bank", description="Bem-vindo ao centro nevrálgico da nossa economia! Aqui pode aprender a usar o bot, consultar o seu saldo e muito mais.", color=0xffd700)
        embed.add_field(name="Comece por aqui", value="Cada canal tem uma mensagem fixada que explica o seu propósito. Leia-as para entender como tudo funciona.", inline=False)
        embed.add_field(name="Comandos Essenciais", value="`!saldo` - Vê o seu saldo de moedas.\n`!extrato` - Vê o seu histórico de transações.\n`!loja` - Mostra os itens que pode comprar.\n`!info-moeda` - Vê a saúde da nossa economia.", inline=False)
        await create_and_pin(category=cat_bank, name="🎓｜como-usar-o-bot", embed=embed, overwrites={guild.default_role: discord.PermissionOverwrite(send_messages=False)})

        embed = discord.Embed(title="📈｜Mercado Financeiro", description="A nossa moeda tem valor real! O seu valor é **lastreado** (garantido) pela prata guardada no tesouro da guilda.", color=0x1abc9c)
        embed.add_field(name="O que é o Lastro?", value="Significa que para cada moeda em circulação, existe uma quantidade correspondente de prata guardada. Isto garante que a nossa moeda nunca perde o seu valor.", inline=False)
        embed.add_field(name="Comando Útil", value="Use `!info-moeda` para ver o total de prata no tesouro, a taxa de conversão atual e quantas moedas existem no total.", inline=False)
        await create_and_pin(category=cat_bank, name="📈｜mercado-financeiro", embed=embed, set_config_key='canal_mercado', overwrites={guild.default_role: discord.PermissionOverwrite(send_messages=False)})
        
        embed = discord.Embed(title="💰｜Minha Conta", description="Este é o seu espaço pessoal para gerir as suas finanças.", color=0x2ecc71)
        embed.add_field(name="Comandos de Gestão", value="`!saldo` - Vê o seu saldo atual.\n`!saldo @membro` - Vê o saldo de outro membro.\n`!extrato` - Mostra o seu extrato do dia.\n`!extrato AAAA-MM-DD` - Vê o extrato de um dia específico.\n`!transferir @membro <valor>` - Envia moedas para outro membro.", inline=False)
        await create_and_pin(category=cat_bank, name="💰｜minha-conta", embed=embed)

        embed = discord.Embed(title="🛍️｜Loja da Guilda", description="Todo o seu esforço é recompensado! Use as suas moedas para comprar itens valiosos.", color=0x3498db)
        embed.add_field(name="Como Comprar", value="1. Use `!loja` para ver a lista de itens disponíveis e os seus IDs.\n2. Use `!comprar <ID_do_item>` para fazer a sua compra.", inline=False)
        await create_and_pin(category=cat_bank, name="🛍️｜loja-da-guilda", embed=embed)
        
        embed = discord.Embed(title="🏆｜Eventos e Missões", description="A principal forma de ganhar moedas! Participar nos conteúdos da guilda é a sua maior fonte de renda.", color=0xe91e63)
        embed.add_field(name="Como Participar", value="1. Use `!listareventos` para ver as missões ativas.\n2. Inscreva-se com `!participar <ID_do_evento>`.\n3. Participe no evento e garanta que o líder confirma a sua presença!", inline=False)
        await create_and_pin(category=cat_bank, name="🏆｜eventos-e-missões", embed=embed)

        embed = discord.Embed(title="🔮｜Submeter Orbes", description="Apanhou uma orbe? Registe-a aqui para ganhar uma recompensa para si e para o seu grupo!", color=0x9b59b6)
        embed.add_field(name="Como Submeter", value="Anexe o print da captura da orbe nesta sala e use o comando:\n`!orbe <cor> <@membro1> <@membro2> ...`", inline=False)
        await create_and_pin(category=cat_bank, name="🔮｜submeter-orbes", embed=embed, set_config_key='canal_orbes')
        
        # 2. Categoria de Taxas
        cat_taxas = await guild.create_category("💸 TAXA SEMANAL")
        await asyncio.sleep(2)

        embed = discord.Embed(title="ℹ️｜Como Funciona a Taxa", description="A taxa semanal é um sistema automático que ajuda a financiar os projetos e as atividades da guilda.", color=0x7f8c8d)
        embed.add_field(name="Como funciona?", value="Uma vez por semana, o bot tenta debitar automaticamente o valor da taxa do seu `!saldo`. Se não tiver saldo, o seu cargo será temporariamente alterado.", inline=False)
        embed.add_field(name="Como Regularizar?", value="Vá ao canal `🪙｜pagamento-de-taxas` e use `!pagar-taxa` ou `!paguei-prata`.", inline=False)
        await create_and_pin(category=cat_taxas, name="ℹ️｜como-funciona-a-taxa", embed=embed, overwrites={guild.default_role: discord.PermissionOverwrite(send_messages=False)})
        
        embed = discord.Embed(title="🪙｜Pagamento de Taxas", description="Use este canal para regularizar a sua situação se estiver com a taxa em atraso.", color=0x95a5a6)
        embed.add_field(name="Pagar com Moedas", value="Use o comando `!pagar-taxa`.", inline=False)
        embed.add_field(name="Pagar com Prata", value="Anexe o print do comprovativo de pagamento no jogo e use o comando `!paguei-prata`.", inline=False)
        await create_and_pin(category=cat_taxas, name="🪙｜pagamento-de-taxas", embed=embed)

        # 3. Categoria de Administração
        cat_admin = await guild.create_category("⚙️ ADMINISTRAÇÃO", overwrites=admin_overwrites)
        await asyncio.sleep(2)
        
        embed = discord.Embed(title="✅｜Aprovações", description="Este canal é para uso exclusivo da staff. Aqui aparecerão todas as submissões de orbes e pagamentos de taxa.", color=0xf1c40f)
        await create_and_pin(category=cat_admin, name="✅｜aprovações", embed=embed, set_config_key='canal_aprovacao')

        embed = discord.Embed(title="🚨｜Resgates Staff", description="Este canal notifica a equipa financeira sempre que um resgate de moedas por prata é processado.", color=0xe74c3c)
        await create_and_pin(category=cat_admin, name="🚨｜resgates-staff", embed=embed, set_config_key='canal_resgates')

        embed = discord.Embed(title="🔩｜Comandos Admin", description="Utilize este canal para todos os comandos de gestão e configuração do bot.", color=0xe67e22)
        await create_and_pin(category=cat_admin, name="🔩｜comandos-admin", embed=embed)
        
        await msg_progresso.edit(content="✅ Estrutura de canais final criada e configurada com sucesso!")

    @commands.group(name="cargo", invoke_without_command=True)
    @check_permission_level(4)
    async def cargo(self, ctx):
        await ctx.send("Comandos disponíveis: `!cargo definir <tipo> <@cargo>` e `!cargo permissao <nível> <@cargo>`")

    @cargo.command(name="definir")
    @check_permission_level(4)
    async def cargo_definir(self, ctx, tipo: str, cargo: discord.Role):
        tipos_validos = ['membro', 'inadimplente', 'isento']
        if tipo.lower() not in tipos_validos:
            return await ctx.send(f"❌ Tipo inválido. Tipos válidos: `{', '.join(tipos_validos)}`")
        
        chave = f"cargo_{tipo.lower()}"
        self.bot.db_manager.set_config_value(chave, str(cargo.id))
        await ctx.send(f"✅ O cargo **{tipo.capitalize()}** foi definido como {cargo.mention}.")

    @cargo.command(name="permissao")
    @check_permission_level(4)
    async def cargo_permissao(self, ctx, nivel: int, cargo: discord.Role):
        if not 1 <= nivel <= 4:
            return await ctx.send("❌ O nível de permissão deve ser entre 1 e 4.")
        
        chave = f"perm_nivel_{nivel}"
        self.bot.db_manager.set_config_value(chave, str(cargo.id))
        await ctx.send(f"✅ O cargo {cargo.mention} foi associado ao **Nível de Permissão {nivel}**.")

    @commands.command(name="definir")
    @check_permission_level(4)
    async def definir(self, ctx, *args):
        # Este comando agrupa os !definir...
        await ctx.send("Comando movido. Use `!definir canal`, `!definir lastro` ou `!definir recompensa/limite`.")

    @commands.group(name="definircanal", invoke_without_command=True)
    @check_permission_level(4)
    async def definir_canal(self, ctx):
        await ctx.send("Use `!definir canal <tipo> #canal`.")
    
    @definir_canal.command(name="anuncios")
    @check_permission_level(4)
    async def definir_canal_anuncios(self, ctx, canal: discord.TextChannel):
        self.bot.db_manager.set_config_value("canal_anuncios", str(canal.id))
        await ctx.send(f"✅ O canal de anúncios foi definido como {canal.mention}.")

    @definir_canal.command(name="batepapo")
    @check_permission_level(4)
    async def definir_canal_batepapo(self, ctx, canal: discord.TextChannel):
        self.bot.db_manager.set_config_value("canal_batepapo", str(canal.id))
        await ctx.send(f"✅ O canal de bate-papo para mensagens de engajamento foi definido como {canal.mention}.")

async def setup(bot):
    await bot.add_cog(Admin(bot))

