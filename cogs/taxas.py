import discord
from discord.ext import commands, tasks
from utils.permissions import check_permission_level
from datetime import datetime, time, timedelta, timezone
from utils.views import TaxaPrataView
from collections import defaultdict
import asyncio

class Taxas(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.ciclo_semanal_taxas.start()
        print("Módulo de Taxas v2.1 (com !forcar-taxa seguro) pronto.")

    def cog_unload(self):
        self.ciclo_semanal_taxas.cancel()

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
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
        cargo_inadimplente = membro.guild.get_role(int(configs.get('cargo_inadimplente', '0')))
        cargo_membro = membro.guild.get_role(int(configs.get('cargo_membro', '0')))
        if not cargo_inadimplente or not cargo_membro: return
        try:
            if cargo_inadimplente in membro.roles:
                await membro.remove_roles(cargo_inadimplente, reason="Taxa regularizada")
            if cargo_membro not in membro.roles:
                await membro.add_roles(cargo_membro, reason="Taxa regularizada")
        except discord.Forbidden:
            print(f"Erro de permissão ao alterar cargos para {membro.name}")

    @tasks.loop(time=time(hour=12, minute=0, tzinfo=datetime.now().astimezone().tzinfo))
    async def ciclo_semanal_taxas(self):
        configs = await self.bot.db_manager.get_all_configs(['taxa_dia_semana'])
        dia_reset = int(configs.get('taxa_dia_semana', '-1'))
        hoje = datetime.now().weekday()
        if hoje == dia_reset:
            print(f"Hoje é o dia de reset das taxas ({dia_reset}). A iniciar o ciclo completo.")
            # O ciclo automático executa o processo completo, incluindo o reset.
            await self.executar_ciclo_de_taxas(resetar_ciclo=True)

    # --- FUNÇÃO MODIFICADA ---
    async def executar_ciclo_de_taxas(self, ctx=None, resetar_ciclo: bool = False):
        """Lógica que aplica inadimplência e, opcionalmente, reseta o ciclo."""
        guild = ctx.guild if ctx else self.bot.guilds[0] if self.bot.guilds else None
        if not guild: return print("ERRO: Bot não está em nenhum servidor.")

        configs = await self.bot.db_manager.get_all_configs([
            'cargo_membro', 'cargo_inadimplente', 'cargo_isento', 'canal_log_taxas'
        ])
        canal_log = None
        try:
            canal_log_id = int(configs.get('canal_log_taxas', '0'))
            canal_log = self.bot.get_channel(canal_log_id) if canal_log_id else None
        except Exception:
            canal_log = None

        membros_pendentes_db = await self.bot.db_manager.execute_query(
            "SELECT user_id, data_entrada FROM taxas WHERE status_ciclo = 'PENDENTE'", fetch="all"
        )

        novos_isentos, inadimplentes, falhas = [], [], []
        uma_semana_atras = datetime.now(timezone.utc) - timedelta(days=7)

        for registro in membros_pendentes_db:
            membro = guild.get_member(registro['user_id'])
            if not membro: continue

            cargo_isento = guild.get_role(int(configs.get('cargo_isento', '0')))
            if cargo_isento and cargo_isento in membro.roles:
                continue

            if registro.get('data_entrada') and registro['data_entrada'] > uma_semana_atras:
                novos_isentos.append(membro)
                await self.bot.db_manager.execute_query("UPDATE taxas SET status_ciclo = 'ISENTO_NOVO_MEMBRO' WHERE user_id = $1", membro.id)
                continue

            try:
                cargo_membro = guild.get_role(int(configs.get('cargo_membro', '0')))
                cargo_inadimplente = guild.get_role(int(configs.get('cargo_inadimplente', '0')))
                if cargo_membro and cargo_membro in membro.roles:
                    await membro.remove_roles(cargo_membro, reason="Ciclo de taxa semanal")
                if cargo_inadimplente and cargo_inadimplente not in membro.roles:
                    await membro.add_roles(cargo_inadimplente, reason="Ciclo de taxa semanal")
                inadimplentes.append(membro)
            except Exception as e:
                falhas.append(f"{membro.name} ({e})")

        embed = discord.Embed(title="Relatório do Ciclo de Taxas", timestamp=datetime.now(timezone.utc))
        embed.description = "**Modo: Aplicação de Penalidades**"
        embed.add_field(name="✅ Inadimplentes Aplicados", value=f"**{len(inadimplentes)}** membros foram marcados como inadimplentes.", inline=False)
        embed.add_field(name="🐣 Novos Membros Isentos", value=f"**{len(novos_isentos)}** membros foram isentos neste ciclo.", inline=False)

        if resetar_ciclo:
            embed.description = "**Modo: Ciclo Semanal Completo (com Reset)**"
            membros_resetados_db = await self.bot.db_manager.execute_query(
                "UPDATE taxas SET status_ciclo = 'PENDENTE' WHERE status_ciclo LIKE 'PAGO_%' OR status_ciclo = 'ISENTO_NOVO_MEMBRO' RETURNING user_id", fetch="all"
            )
            embed.add_field(name="🔄 Status Resetados", value=f"**{len(membros_resetados_db)}** membros tiveram seu status resetado para 'Pendente' para o próximo ciclo.", inline=False)

        if falhas:
            embed.add_field(name="❌ Falhas", value="\n".join(falhas), inline=False)

        log_msg = "Ciclo de taxas executado."
        if ctx:
            try: await ctx.send(log_msg, embed=embed)
            except Exception: pass
        if canal_log:
            try: await canal_log.send(embed=embed)
            except Exception: pass
        print(log_msg)

    @ciclo_semanal_taxas.before_loop
    async def before_ciclo_taxas(self):
        await self.bot.wait_until_ready()

    @commands.command(name="pagar-taxa", help='Paga a sua taxa semanal.')
    async def pagar_taxa(self, ctx):
        configs = await self.bot.db_manager.get_all_configs(['taxa_semanal_valor', 'taxa_dia_semana', 'taxa_dia_abertura', 'cargo_membro', 'cargo_inadimplente'])
        valor_taxa = int(configs.get('taxa_semanal_valor', 0))
        if valor_taxa == 0: return await ctx.send("O sistema de taxas não está configurado.")

        status_atual_db = await self.bot.db_manager.execute_query("SELECT status_ciclo FROM taxas WHERE user_id = $1", ctx.author.id, fetch="one")
        status_atual = status_atual_db['status_ciclo'] if status_atual_db else 'PENDENTE'

        if status_atual.startswith('PAGO'):
            return await ctx.send("✅ Você já pagou a taxa para este ciclo.", delete_after=10)

        hoje = datetime.now().weekday()
        dia_abertura = int(configs.get('taxa_dia_abertura', '5'))
        dia_reset = int(configs.get('taxa_dia_semana', '6'))

        pagamento_atrasado = False
        try:
            pagamento_atrasado = ctx.guild.get_role(int(configs.get('cargo_inadimplente', '0'))) in ctx.author.roles
        except Exception:
            pagamento_atrasado = False

        pagamento_antecipado = status_atual == 'PENDENTE' and (hoje >= dia_abertura or hoje < dia_reset)

        if not pagamento_antecipado and not pagamento_atrasado:
            dias = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
            return await ctx.send(f"❌ A janela para pagamento antecipado abre na **{dias[dia_abertura]}**. Aguarde.", delete_after=15)

        try:
            status_pagamento = 'PAGO_ANTECIPADO' if pagamento_antecipado else 'PAGO_ATRASADO'
            await self.bot.get_cog('Economia').levantar(ctx.author.id, valor_taxa, f"Pagamento de taxa semanal ({status_pagamento})")
            await self.bot.db_manager.execute_query(
                "INSERT INTO taxas (user_id, status_ciclo) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET status_ciclo = $2",
                ctx.author.id, status_pagamento
            )
            if pagamento_atrasado: await self.regularizar_membro(ctx.author, configs)
            await ctx.send(f"✅ Taxa paga com sucesso! O seu status para este ciclo é: **{status_pagamento}**.")
        except ValueError:
            await ctx.send(f"❌ Você não tem saldo suficiente. A taxa custa **{valor_taxa}** moedas.")

    # --- COMANDO MODIFICADO ---
    @commands.command(name="forcar-taxa", hidden=True)
    @check_permission_level(4)
    async def forcar_taxa(self, ctx):
        await ctx.send("🔥 A forçar a execução do ciclo de penalidades de taxas (sem resetar quem já pagou)...")
        # Força a execução apenas da parte de penalização, sem resetar o ciclo.
        await self.executar_ciclo_de_taxas(ctx, resetar_ciclo=False)

    @commands.command(name="relatorio-taxas", hidden=True)
    @check_permission_level(2)
    async def relatorio_taxas(self, ctx):
        await ctx.send("A gerar relatório de taxas...")
        registros = await self.bot.db_manager.execute_query("SELECT user_id, status_ciclo FROM taxas ORDER BY status_ciclo", fetch="all")
        embed = discord.Embed(title="Relatório de Status das Taxas", color=discord.Color.blue())
        status_map = defaultdict(list)
        for r in registros:
            membro = ctx.guild.get_member(r['user_id'])
            if membro:
                status_map[r['status_ciclo']].append(membro.mention)

        for status, mentions in status_map.items():
            value = "\n".join(mentions)
            if len(value) > 1024:
                value = value[:1020] + "\n..."
            embed.add_field(name=f"Status: {status} ({len(mentions)})", value=value or "Nenhum", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="definir-taxa-dia-abertura", hidden=True)
    @check_permission_level(4)
    async def definir_taxa_dia_abertura(self, ctx, dia_da_semana: int):
        if not 0 <= dia_da_semana <= 6:
            return await ctx.send("❌ Dia inválido (0=Segunda, 6=Domingo).")
        dias = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
        await self.bot.db_manager.set_config_value('taxa_dia_abertura', str(dia_da_semana))
        await ctx.send(f"✅ Janela de pagamento de taxas abrirá toda **{dias[dia_da_semana]}**.")

    # Manter os outros comandos de admin de taxas
    @commands.command(name="paguei-prata", help='Inicia o processo de pagamento da taxa com prata do jogo.')
    async def paguei_prata(self, ctx):
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
            description=f"**Membro:** {ctx.author.mention} (`{ctx.author.id}`)\n"
                        f"Enviou um comprovativo de pagamento da taxa em prata.",
            color=discord.Color.orange()
        )
        embed.set_image(url=imagem.url)
        embed.set_footer(text="Aguardando aprovação da Staff...")

        view = TaxaPrataView(self.bot)

        try:
            msg_aprovacao = await canal_aprovacao.send(embed=embed, view=view)

            await self.bot.db_manager.execute_query(
                "DELETE FROM submissoes_taxa WHERE message_id = $1",
                msg_aprovacao.id
            )
            await self.bot.db_manager.execute_query(
                "INSERT INTO submissoes_taxa (message_id, user_id, status) VALUES ($1, $2, $3)",
                msg_aprovacao.id, ctx.author.id, 'pendente'
            )

            await ctx.message.add_reaction("✅")
            await ctx.send("✅ Comprovativo enviado para análise! Agora aguente a ansiedade até um staff aprovar.", delete_after=15)

        except Exception as e:
            await ctx.send("❌ Ocorreu um erro ao enviar o seu comprovativo.")
            print(f"Erro no comando paguei-prata: {e}")

    @commands.command(name="definir-taxa", hidden=True)
    @check_permission_level(4)
    async def definir_taxa(self, ctx, valor: int):
        if valor < 0: return await ctx.send("O valor não pode ser negativo.")
        await self.bot.db_manager.set_config_value('taxa_semanal_valor', str(valor))
        await ctx.send(f"✅ Valor da taxa semanal definido para **{valor}** moedas.")

    @commands.command(name="definir-taxa-dia", hidden=True)
    @check_permission_level(4)
    async def definir_taxa_dia(self, ctx, dia_da_semana: int):
        if not 0 <= dia_da_semana <= 6: return await ctx.send("❌ Dia inválido (0=Segunda, 6=Domingo).")
        dias = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
        await self.bot.db_manager.set_config_value('taxa_dia_semana', str(dia_da_semana))
        await ctx.send(f"✅ O ciclo de reset das taxas foi agendado para **{dias[dia_da_semana]}**.")

async def setup(bot):
    await bot.add_cog(Taxas(bot))



