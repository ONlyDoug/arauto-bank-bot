import discord
from discord.ext import commands, tasks
from utils.permissions import check_permission_level
from datetime import datetime, time, timedelta, timezone
from collections import defaultdict
import asyncio

# A classe TaxaPrataView é importada de utils.views, que deve estar correto.
from utils.views import TaxaPrataView

class Taxas(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.ciclo_semanal_taxas.start()
        self.atualizar_relatorio_automatico.start()
        print("Módulo de Taxas v2.3 (com Comando de Correção) pronto.")

    def cog_unload(self):
        self.ciclo_semanal_taxas.cancel()
        self.atualizar_relatorio_automatico.cancel()

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        # ... (lógica inalterada)
        configs = await self.bot.db_manager.get_all_configs(['cargo_membro'])
        cargo_membro_id = int(configs.get('cargo_membro', '0'))
        if cargo_membro_id == 0: return
        cargo_membro = after.guild.get_role(cargo_membro_id)
        if not cargo_membro: return
        if cargo_membro not in before.roles and cargo_membro in after.roles:
            await self.bot.db_manager.execute_query(
                """INSERT INTO taxas (user_id, status_ciclo, data_entrada) VALUES ($1, 'ISENTO_NOVO_MEMBRO', $2)
                   ON CONFLICT (user_id) DO UPDATE SET data_entrada = EXCLUDED.data_entrada, status_ciclo = 'ISENTO_NOVO_MEMBRO'""",
                after.id, datetime.now(timezone.utc)
            )
            print(f"Novo membro detetado: {after.name}. Data de entrada registada.")

    async def regularizar_membro(self, membro: discord.Member, configs: dict):
        # ... (lógica inalterada)
        cargo_inadimplente = membro.guild.get_role(int(configs.get('cargo_inadimplente', '0')))
        cargo_membro = membro.guild.get_role(int(configs.get('cargo_membro', '0')))
        if not cargo_inadimplente or not cargo_membro: return
        try:
            if cargo_inadimplente in membro.roles: await membro.remove_roles(cargo_inadimplente, reason="Taxa regularizada")
            if cargo_membro not in membro.roles: await membro.add_roles(cargo_membro, reason="Taxa regularizada")
        except discord.Forbidden: print(f"Erro de permissão ao alterar cargos para {membro.name}")

    # --- TAREFAS EM SEGUNDO PLANO ---
    @tasks.loop(minutes=15)
    async def atualizar_relatorio_automatico(self):
        # ... (lógica inalterada)
        try:
            configs = await self.bot.db_manager.get_all_configs(['canal_relatorio_taxas', 'taxa_relatorio_msg_id'])
            canal_id = int(configs.get('canal_relatorio_taxas', '0'))
            msg_id = int(configs.get('taxa_relatorio_msg_id', '0'))
            if canal_id == 0: return
            canal = self.bot.get_channel(canal_id)
            if not canal: return
            embed = await self._construir_embed_relatorio(canal.guild)
            try:
                msg = await canal.fetch_message(msg_id)
                await msg.edit(content="", embed=embed)
            except discord.NotFound:
                nova_msg = await canal.send(embed=embed)
                await self.bot.db_manager.set_config_value('taxa_relatorio_msg_id', str(nova_msg.id))
        except Exception as e:
            print(f"Erro ao atualizar relatório automático de taxas: {e}")

    @atualizar_relatorio_automatico.before_loop
    async def before_atualizar_relatorio(self):
        await self.bot.wait_until_ready()

    @tasks.loop(time=time(hour=12, minute=0, tzinfo=datetime.now().astimezone().tzinfo))
    async def ciclo_semanal_taxas(self):
        # ... (lógica inalterada)
        configs = await self.bot.db_manager.get_all_configs(['taxa_dia_semana'])
        dia_reset = int(configs.get('taxa_dia_semana', '-1'))
        if datetime.now().weekday() == dia_reset:
            await self.executar_ciclo_de_taxas(resetar_ciclo=True)

    # --- LÓGICA PRINCIPAL DO CICLO ---
    async def executar_ciclo_de_taxas(self, ctx=None, resetar_ciclo: bool = False):
        # ... (lógica inalterada)
        guild = ctx.guild if ctx else (self.bot.guilds[0] if self.bot.guilds else None)
        if not guild: return
        configs = await self.bot.db_manager.get_all_configs(['cargo_membro', 'cargo_inadimplente', 'cargo_isento', 'canal_log_taxas'])
        canal_log = None
        try:
            canal_log_id = int(configs.get('canal_log_taxas', '0') or '0')
            if canal_log_id:
                canal_log = self.bot.get_channel(canal_log_id)
        except Exception:
            canal_log = None

        membros_pendentes_db = await self.bot.db_manager.execute_query("SELECT user_id, data_entrada FROM taxas WHERE status_ciclo = 'PENDENTE'", fetch="all")
        novos_isentos, inadimplentes, falhas = [], [], []
        uma_semana_atras = datetime.now(timezone.utc) - timedelta(days=7)
        for registro in membros_pendentes_db:
            membro = guild.get_member(registro['user_id'])
            if not membro: continue
            if (isento := guild.get_role(int(configs.get('cargo_isento', '0')))) and isento in membro.roles: continue
            data_entrada = registro.get('data_entrada')
            if data_entrada and data_entrada > uma_semana_atras:
                novos_isentos.append(membro)
                await self.bot.db_manager.execute_query("UPDATE taxas SET status_ciclo = 'ISENTO_NOVO_MEMBRO' WHERE user_id = $1", membro.id)
                continue
            try:
                membro_role = guild.get_role(int(configs.get('cargo_membro', '0')))
                inadimplente_role = guild.get_role(int(configs.get('cargo_inadimplente', '0')))
                if membro_role and membro_role in membro.roles: await membro.remove_roles(membro_role, reason="Ciclo de taxa")
                if inadimplente_role and inadimplente_role not in membro.roles: await membro.add_roles(inadimplente_role, reason="Ciclo de taxa")
                inadimplentes.append(membro)
            except Exception as e: falhas.append(f"{membro.name} ({e})")
        embed = discord.Embed(title="Relatório do Ciclo de Taxas", timestamp=datetime.now(timezone.utc))
        embed.description = "**Modo: Aplicação de Penalidades**"
        embed.add_field(name="✅ Inadimplentes Aplicados", value=f"{len(inadimplentes)} membros.", inline=False)
        embed.add_field(name="🐣 Novos Membros Isentos", value=f"{len(novos_isentos)} membros.", inline=False)
        if resetar_ciclo:
            embed.description = "**Modo: Ciclo Semanal Completo (com Reset)**"
            resetados_db = await self.bot.db_manager.execute_query("UPDATE taxas SET status_ciclo = 'PENDENTE' WHERE status_ciclo LIKE 'PAGO_%' OR status_ciclo = 'ISENTO_NOVO_MEMBRO' RETURNING user_id", fetch="all")
            embed.add_field(name="🔄 Status Resetados", value=f"{len(resetados_db)} membros.", inline=False)
        if falhas: embed.add_field(name="❌ Falhas", value="\n".join(falhas), inline=False)
        if ctx:
            try: await ctx.send(embed=embed)
            except Exception: pass
        if canal_log:
            try: await canal_log.send(embed=embed)
            except Exception: pass

    # --- COMANDOS DO UTILIZADOR ---
    @commands.command(name="pagar-taxa", help='Paga a sua taxa semanal.')
    async def pagar_taxa(self, ctx):
        # ... (lógica inalterada)
        configs = await self.bot.db_manager.get_all_configs(['taxa_semanal_valor', 'taxa_dia_semana', 'taxa_dia_abertura', 'cargo_membro', 'cargo_inadimplente'])
        valor_taxa = int(configs.get('taxa_semanal_valor', 0) or 0)
        if valor_taxa == 0: return await ctx.send("Sistema de taxas desativado.")
        status_db = await self.bot.db_manager.execute_query("SELECT status_ciclo FROM taxas WHERE user_id = $1", ctx.author.id, fetch="one")
        status = status_db['status_ciclo'] if status_db else 'PENDENTE'
        if status.startswith('PAGO'): return await ctx.send("✅ Você já pagou a taxa para este ciclo.", delete_after=10)
        hoje = datetime.now().weekday()
        dia_abertura = int(configs.get('taxa_dia_abertura', '5'))
        dia_reset = int(configs.get('taxa_dia_semana', '6'))
        atrasado = False
        try:
            atrasado = ctx.guild.get_role(int(configs.get('cargo_inadimplente', '0'))) in ctx.author.roles
        except Exception:
            atrasado = False
        antecipado = status == 'PENDENTE' and (hoje >= dia_abertura or hoje < dia_reset)
        if not antecipado and not atrasado:
            dias = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
            return await ctx.send(f"❌ A janela de pagamento abre na **{dias[dia_abertura]}**.", delete_after=15)
        try:
            status_pagamento = 'PAGO_ANTECIPADO' if antecipado else 'PAGO_ATRASADO'
            await self.bot.get_cog('Economia').levantar(ctx.author.id, valor_taxa, f"Pagamento de taxa semanal ({status_pagamento})")
            await self.bot.db_manager.execute_query("INSERT INTO taxas (user_id, status_ciclo) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET status_ciclo = $2", ctx.author.id, status_pagamento)
            if atrasado: await self.regularizar_membro(ctx.author, configs)
            await ctx.send(f"✅ Taxa paga com sucesso! Seu status: **{status_pagamento}**.")
        except ValueError:
            await ctx.send(f"❌ Você não tem saldo suficiente. A taxa custa **{valor_taxa}** moedas.")

    @commands.command(name="paguei-prata", help='Inicia o processo de pagamento da taxa com prata do jogo.')
    async def paguei_prata(self, ctx):
        # mantém comportamento anterior usando TaxaPrataView
        if not ctx.message.attachments or not ctx.message.attachments[0].content_type.startswith('image/'):
            return await ctx.send("❌ Anexe a imagem do comprovativo de pagamento.", delete_after=15)

        imagem = ctx.message.attachments[0]
        canal_aprovacao_id_str = await self.bot.db_manager.get_config_value('canal_aprovacao', '0')
        canal_aprovacao = None
        try:
            canal_aprovacao = self.bot.get_channel(int(canal_aprovacao_id_str)) if canal_aprovacao_id_str and canal_aprovacao_id_str != '0' else None
        except Exception:
            canal_aprovacao = None

        if not canal_aprovacao:
            return await ctx.send("⚠️ O canal de aprovações não foi configurado. Contacte um administrador. A sua prata está no limbo por agora.")

        embed = discord.Embed(
            title="🧾 Pagamento de Taxa em Prata",
            description=f"**Membro:** {ctx.author.mention} (`{ctx.author.id}`)\nEnviou um comprovativo de pagamento da taxa em prata.",
            color=discord.Color.orange()
        )
        embed.set_image(url=imagem.url)
        embed.set_footer(text="Aguardando aprovação da Staff...")

        view = TaxaPrataView(self.bot)

        try:
            msg_aprovacao = await canal_aprovacao.send(embed=embed, view=view)
            await self.bot.db_manager.execute_query("DELETE FROM submissoes_taxa WHERE message_id = $1", msg_aprovacao.id)
            await self.bot.db_manager.execute_query("INSERT INTO submissoes_taxa (message_id, user_id, status) VALUES ($1, $2, $3)", msg_aprovacao.id, ctx.author.id, 'pendente')
            await ctx.message.add_reaction("✅")
            await ctx.send("✅ Comprovativo enviado para análise! Agora aguarde a Staff aprovar.", delete_after=15)
        except Exception as e:
            await ctx.send("❌ Ocorreu um erro ao enviar o seu comprovativo.")
            print(f"Erro no comando paguei-prata: {e}")

    # --- COMANDOS DE ADMINISTRAÇÃO ---

    # --- NOVO COMANDO DE EMERGÊNCIA ---
    @commands.command(name="corrigir-taxas", hidden=True)
    @check_permission_level(4)
    async def corrigir_taxas(self, ctx):
        """Comando de emergência para regularizar membros que pagaram a taxa mas foram penalizados."""
        await ctx.send("⚙️ A iniciar procedimento de correção de taxas. A verificar logs de pagamento...")

        configs = await self.bot.db_manager.get_all_configs(['taxa_dia_semana', 'taxa_semanal_valor', 'cargo_inadimplente'])
        dia_reset = int(configs.get('taxa_dia_semana', '6'))
        valor_taxa = int(configs.get('taxa_semanal_valor', 0))

        # Calcula a data do último dia de reset
        hoje = datetime.now(timezone.utc)
        dias_desde_reset = (hoje.weekday() - dia_reset + 7) % 7
        ultimo_reset = hoje - timedelta(days=dias_desde_reset)
        ultimo_reset = ultimo_reset.replace(hour=12, minute=0, second=0, microsecond=0)

        # Busca todos os pagamentos de taxa feitos desde o último reset
        pagamentos = await self.bot.db_manager.execute_query(
            "SELECT user_id FROM transacoes WHERE descricao LIKE 'Pagamento de taxa semanal%' AND data >= $1 AND valor = $2",
            ultimo_reset, valor_taxa, fetch="all"
        )

        if not pagamentos:
            return await ctx.send("Nenhum pagamento de taxa encontrado no período. Nenhuma ação necessária.")

        pagadores_ids = {p['user_id'] for p in pagamentos}
        corrigidos, ja_regulares = [], []

        for user_id in pagadores_ids:
            membro = ctx.guild.get_member(user_id)
            if not membro: continue

            # Atualiza o status na DB e regulariza os cargos
            await self.bot.db_manager.execute_query("INSERT INTO taxas (user_id, status_ciclo) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET status_ciclo = $2", user_id, 'PAGO_ATRASADO')

            cargo_inadimplente = ctx.guild.get_role(int(configs.get('cargo_inadimplente', '0')))
            if cargo_inadimplente and cargo_inadimplente in membro.roles:
                await self.regularizar_membro(membro, configs)
                corrigidos.append(membro.mention)
            else:
                ja_regulares.append(membro.mention)

        embed = discord.Embed(title="✅ Correção de Taxas Concluída")
        embed.add_field(name="Membros Corrigidos", value="\n".join(corrigidos) or "Nenhum", inline=False)
        embed.add_field(name="Membros que Já Estavam Regulares", value="\n".join(ja_regulares) or "Nenhum", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="forcar-taxa", hidden=True)
    @check_permission_level(4)
    async def forcar_taxa(self, ctx):
        await ctx.send("🔥 A forçar a execução do ciclo de penalidades de taxas (sem resetar quem já pagou)...")
        await self.executar_ciclo_de_taxas(ctx, resetar_ciclo=False)

    # --- FUNÇÃO AUXILIAR PARA CONSTRUIR O EMBED (USADA PELO RELATÓRIO) ---
    async def _construir_embed_relatorio(self, guild: discord.Guild):
        registros = await self.bot.db_manager.execute_query("SELECT user_id, status_ciclo FROM taxas ORDER BY status_ciclo", fetch="all")
        embed = discord.Embed(title="📈 Relatório de Status das Taxas", color=discord.Color.from_rgb(100, 150, 200))
        embed.set_footer(text=f"Atualizado em: {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M:%S')}")
        status_map = defaultdict(list)
        for r in registros:
            membro = guild.get_member(r['user_id'])
            if membro:
                status_map[r.get('status_ciclo', 'PENDENTE')].append(membro.mention)

        def formatar_lista(lista):
            if not lista: return "Nenhum"
            texto = "\n".join(lista)
            if len(texto) > 1024: return texto[:1020] + "\n..."
            return texto

        embed.add_field(name=f"🔴 Pendentes ({len(status_map.get('PENDENTE', []))})", value=formatar_lista(status_map.get('PENDENTE', [])), inline=False)
        pagos_total = status_map.get('PAGO_ANTECIPADO', []) + status_map.get('PAGO_ATRASADO', [])
        embed.add_field(name=f"🟢 Pagos ({len(pagos_total)})", value=formatar_lista(pagos_total), inline=False)
        embed.add_field(name=f"🐣 Isentos (Novos Membros) ({len(status_map.get('ISENTO_NOVO_MEMBRO', []))})", value=formatar_lista(status_map.get('ISENTO_NOVO_MEMBRO', [])), inline=False)
        return embed

    @commands.command(name="relatorio-taxas", hidden=True)
    @check_permission_level(2)
    async def relatorio_taxas(self, ctx):
        await ctx.send("A gerar um relatório instantâneo de taxas...")
        embed = await self._construir_embed_relatorio(ctx.guild)
        await ctx.send(embed=embed)

    # ... (outros comandos de admin inalterados) ...

async def setup(bot):
    await bot.add_cog(Taxas(bot))



