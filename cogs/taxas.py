import discord
from discord.ext import commands, tasks
from utils.permissions import check_permission_level
from datetime import datetime, time, timedelta, timezone
from collections import defaultdict
import asyncio

from utils.views import TaxaPrataView

class Taxas(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.ciclo_semanal_taxas.start()
        self.atualizar_relatorio_automatico.start()
        print("Módulo de Taxas v2.6 (Sincronização e Relatórios Robustos) pronto.")

    def cog_unload(self):
        self.ciclo_semanal_taxas.cancel()
        self.atualizar_relatorio_automatico.cancel()

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        configs = await self.bot.db_manager.get_all_configs(['cargo_membro'])
        cargo_membro_id = int(configs.get('cargo_membro', '0') or 0)
        if cargo_membro_id == 0: return
        cargo_membro = after.guild.get_role(cargo_membro_id)
        if not cargo_membro: return
        if cargo_membro not in before.roles and cargo_membro in after.roles:
            await self.bot.db_manager.execute_query(
                """INSERT INTO taxas (user_id, status_ciclo, data_entrada)
                   VALUES ($1, 'ISENTO_NOVO_MEMBRO', $2)
                   ON CONFLICT (user_id) DO UPDATE
                   SET data_entrada = EXCLUDED.data_entrada, status_ciclo = 'ISENTO_NOVO_MEMBRO'""",
                after.id, datetime.now(timezone)
            )

    async def regularizar_membro(self, membro, configs):
        cargo_inadimplente = membro.guild.get_role(int(configs.get('cargo_inadimplente', '0') or 0))
        cargo_membro = membro.guild.get_role(int(configs.get('cargo_membro', '0') or 0))
        if not cargo_inadimplente or not cargo_membro: return
        try:
            if cargo_inadimplente in membro.roles: await membro.remove_roles(cargo_inadimplente, reason="Taxa regularizada")
            if cargo_membro not in membro.roles: await membro.add_roles(cargo_membro, reason="Taxa regularizada")
        except discord.Forbidden: print(f"Erro de permissão para {membro.name}")

    async def _update_report_message(self, canal: discord.TextChannel, config_key: str, embed: discord.Embed):
        try:
            msg_id = int(await self.bot.db_manager.get_config_value(config_key, '0') or 0)
            msg = await canal.fetch_message(msg_id)
            await msg.edit(content=None, embed=embed)
        except discord.NotFound:
            nova_msg = await canal.send(embed=embed)
            await self.bot.db_manager.set_config_value(config_key, str(nova_msg.id))
        except discord.HTTPException as e:
            # tenta detectar erro de "Invalid Form Body" por tamanho/formatos inválidos
            try:
                if getattr(e, "code", None) == 50035:
                    error_embed = discord.Embed(
                        title=embed.title,
                        description="Erro: A lista de membros é demasiado longa para ser exibida.",
                        color=discord.Color.orange()
                    )
                    # envia uma versão reduzida (recursivo controlado — error_embed pequeno)
                    await self._update_report_message(canal, config_key, error_embed)
            except Exception:
                pass
            print(f"Erro de HTTP ao editar relatório: {e}")


    @tasks.loop(minutes=10)
    async def atualizar_relatorio_automatico(self):
        try:
            canal_id = int(await self.bot.db_manager.get_config_value('canal_relatorio_taxas', '0') or 0)
            if canal_id == 0:
                return
            canal = self.bot.get_channel(canal_id)
            if not canal:
                return

            registros = await self.bot.db_manager.execute_query("SELECT user_id, status_ciclo FROM taxas", fetch="all")
            status_map = defaultdict(list)
            for r in registros:
                user_id = r.get('user_id')
                status = r.get('status_ciclo', 'PENDENTE')
                membro = canal.guild.get_member(user_id)
                if membro:
                    status_map[status].append(membro.mention)

            def format_list(mentions, limit=40):
                if not mentions:
                    return "Nenhum membro nesta categoria."
                display = mentions[:limit]
                text = "\n".join(display)
                if len(mentions) > limit:
                    text += f"\n... e mais {len(mentions) - limit} membros."
                return text

            pendentes = status_map.get('PENDENTE', [])
            embed_pendentes = discord.Embed(
                title=f"🔴 Membros Pendentes ({len(pendentes)})",
                description=format_list(pendentes),
                color=discord.Color.red()
            )
            await self._update_report_message(canal, 'taxa_msg_id_pendentes', embed_pendentes)

            pagos = status_map.get('PAGO_ANTECIPADO', []) + status_map.get('PAGO_ATRASADO', [])
            embed_pagos = discord.Embed(
                title=f"🟢 Membros Pagos ({len(pagos)})",
                description=format_list(pagos),
                color=discord.Color.green()
            )
            await self._update_report_message(canal, 'taxa_msg_id_pagos', embed_pagos)

            isentos = status_map.get('ISENTO_NOVO_MEMBRO', [])
            embed_isentos = discord.Embed(
                title=f"😇 Membros Isentos ({len(isentos)})",
                description=format_list(isentos),
                color=discord.Color.light_grey()
            )
            await self._update_report_message(canal, 'taxa_msg_id_isentos', embed_isentos)

        except Exception as e:
            print(f"Erro ao atualizar relatório automático de taxas: {e}")

    @atualizar_relatorio_automatico.before_loop
    async def before_relatorio(self):
        await self.bot.wait_until_ready()

    @tasks.loop(time=time(hour=12, minute=0, tzinfo=datetime.now().astimezone().tzinfo))
    async def ciclo_semanal_taxas(self):
        dia_reset = int(await self.bot.db_manager.get_config_value('taxa_dia_semana', '6') or 6)
        if datetime.now().weekday() == dia_reset:
            await self.executar_ciclo_de_taxas(resetar_ciclo=True)

    async def executar_ciclo_de_taxas(self, ctx=None, resetar_ciclo: bool = False):
        guild = ctx.guild if ctx else (self.bot.guilds[0] if self.bot.guilds else None)
        if not guild: return
        configs = await self.bot.db_manager.get_all_configs(['cargo_membro', 'cargo_inadimplente', 'cargo_isento', 'canal_log_taxas'])
        canal_log = None
        try:
            canal_log_id = int(configs.get('canal_log_taxas', '0') or 0)
            if canal_log_id: canal_log = self.bot.get_channel(canal_log_id)
        except Exception:
            canal_log = None

        membros_pendentes_db = await self.bot.db_manager.execute_query(
            "SELECT user_id, data_entrada FROM taxas WHERE status_ciclo = 'PENDENTE'", fetch="all"
        )
        novos_isentos, inadimplentes, falhas = [], [], []
        uma_semana_atras = datetime.now(timezone) - timedelta(days=7)
        for registro in membros_pendentes_db:
            user_id = registro.get('user_id')
            membro = guild.get_member(user_id)
            if not membro: continue
            isento_role = guild.get_role(int(configs.get('cargo_isento', '0') or 0))
            if isento_role and isento_role in membro.roles: continue
            data_entrada = registro.get('data_entrada')
            if data_entrada and data_entrada > uma_semana_atras:
                novos_isentos.append(membro)
                await self.bot.db_manager.execute_query("UPDATE taxas SET status_ciclo = 'ISENTO_NOVO_MEMBRO' WHERE user_id = $1", membro.id)
                continue
            try:
                membro_role = guild.get_role(int(configs.get('cargo_membro', '0') or 0))
                inadimplente_role = guild.get_role(int(configs.get('cargo_inadimplente', '0') or 0))
                if membro_role and membro_role in membro.roles:
                    await membro.remove_roles(membro_role, reason="Ciclo de taxa")
                if inadimplente_role and inadimplente_role not in membro.roles:
                    await membro.add_roles(inadimplente_role, reason="Ciclo de taxa")
                inadimplentes.append(membro)
            except Exception as e:
                falhas.append(f"{membro.name} ({e})")

        embed = discord.Embed(title="Relatório do Ciclo de Taxas", timestamp=datetime.now(timezone))
        embed.description = "**Modo: Aplicação de Penalidades**"
        embed.add_field(name="✅ Inadimplentes Aplicados", value=f"{len(inadimplentes)} membros.", inline=False)
        embed.add_field(name="🐣 Novos Membros Isentos", value=f"{len(novos_isentos)} membros.", inline=False)
        if resetar_ciclo:
            embed.description = "**Modo: Ciclo Semanal Completo (com Reset)**"
            resetados_db = await self.bot.db_manager.execute_query(
                "UPDATE taxas SET status_ciclo = 'PENDENTE' WHERE status_ciclo LIKE 'PAGO_%' OR status_ciclo = 'ISENTO_NOVO_MEMBRO' RETURNING user_id",
                fetch="all"
            )
            embed.add_field(name="🔄 Status Resetados", value=f"{len(resetados_db)} membros.", inline=False)
        if falhas:
            embed.add_field(name="❌ Falhas", value="\n".join(falhas), inline=False)

        if ctx:
            try: await ctx.send(embed=embed)
            except Exception: pass
        if canal_log:
            try: await canal_log.send(embed=embed)
            except Exception: pass

    @commands.command(name="pagar-taxa")
    async def pagar_taxa(self, ctx):
        configs = await self.bot.db_manager.get_all_configs(['taxa_semanal_valor', 'taxa_dia_semana', 'taxa_dia_abertura', 'cargo_membro', 'cargo_inadimplente'])
        valor_taxa = int(configs.get('taxa_semanal_valor', 0) or 0)
        if valor_taxa == 0:
            return await ctx.send("Sistema de taxas desativado.")
        status_db = await self.bot.db_manager.execute_query("SELECT status_ciclo FROM taxas WHERE user_id = $1", ctx.author.id, fetch="one")
        status = status_db['status_ciclo'] if status_db else 'PENDENTE'
        if status.startswith('PAGO'):
            return await ctx.send("✅ Você já pagou a taxa para este ciclo.", delete_after=10)
        hoje = datetime.now().weekday()
        dia_abertura = int(configs.get('taxa_dia_abertura', '5') or 5)
        dia_reset = int(configs.get('taxa_dia_semana', '6') or 6)
        atrasado = False
        try:
            atrasado = ctx.guild.get_role(int(configs.get('cargo_inadimplente', '0') or 0)) in ctx.author.roles
        except Exception:
            atrasado = False
        antecipado = status == 'PENDENTE' and (hoje >= dia_abertura or hoje < dia_reset)
        if not antecipado and not atrasado:
            dias = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
            return await ctx.send(f"❌ A janela de pagamento abre na **{dias[dia_abertura]}**.", delete_after=15)
        try:
            status_pagamento = 'PAGO_ANTECIPADO' if antecipado else 'PAGO_ATRASADO'
            await self.bot.get_cog('Economia').levantar(ctx.author.id, valor_taxa, f"Pagamento de taxa semanal ({status_pagamento})")
            await self.bot.db_manager.execute_query(
                "INSERT INTO taxas (user_id, status_ciclo) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET status_ciclo = $2",
                ctx.author.id, status_pagamento
            )
            if atrasado: await self.regularizar_membro(ctx.author, configs)
            await ctx.send(f"✅ Taxa paga com sucesso! Seu status: **{status_pagamento}**.")
        except ValueError:
            await ctx.send(f"❌ Você não tem saldo suficiente. A taxa custa **{valor_taxa}** moedas.")

    @commands.command(name="forcar-taxa", hidden=True)
    @check_permission_level(4)
    async def forcar_taxa(self, ctx):
        await ctx.send("🔥 A forçar a execução do ciclo de penalidades (sem resetar quem já pagou)...")
        await self.executar_ciclo_de_taxas(ctx, resetar_ciclo=False)

    @commands.command(name="sincronizar-pagamentos", hidden=True)
    @check_permission_level(4)
    async def sincronizar_pagamentos(self, ctx):
        await ctx.send("⚙️ **Iniciando Sincronização Total de Pagamentos!**\nA analisar pagamentos em moedas e em prata...")
        configs = await self.bot.db_manager.get_all_configs(['taxa_dia_semana', 'taxa_semanal_valor', 'cargo_inadimplente', 'cargo_membro'])
        dia_reset = int(configs.get('taxa_dia_semana', '6') or 6)
        valor_taxa = int(configs.get('taxa_semanal_valor', 0) or 0)
        hoje = datetime.now(timezone)
        dias_desde_reset = (hoje.weekday() - dia_reset + 7) % 7
        ultimo_reset = (hoje - timedelta(days=dias_desde_reset)).replace(hour=12, minute=0, second=0, microsecond=0)

        pagamentos_moedas = await self.bot.db_manager.execute_query(
            "SELECT DISTINCT user_id FROM transacoes WHERE (descricao LIKE 'Pagamento de taxa semanal%') AND data >= $1 AND valor = $2",
            ultimo_reset, valor_taxa, fetch="all"
        )
        pagadores_moedas_ids = {p['user_id'] for p in pagamentos_moedas} if pagamentos_moedas else set()

        pagamentos_prata = await self.bot.db_manager.execute_query(
            "SELECT user_id FROM submissoes_taxa WHERE status = 'aprovado'", fetch="all"
        )
        pagadores_prata_ids = {p['user_id'] for p in pagamentos_prata} if pagamentos_prata else set()

        todos_pagadores_ids = pagadores_moedas_ids.union(pagadores_prata_ids)
        if not todos_pagadores_ids:
            return await ctx.send("Nenhum pagamento (moedas ou prata) encontrado para sincronizar.")

        corrigidos, ja_regulares = [], []
        for user_id in todos_pagadores_ids:
            membro = ctx.guild.get_member(user_id)
            if not membro: continue

            await self.bot.db_manager.execute_query(
                "INSERT INTO taxas (user_id, status_ciclo) VALUES ($1, 'PAGO_ATRASADO') ON CONFLICT (user_id) DO UPDATE SET status_ciclo = 'PAGO_ATRASADO'",
                user_id
            )

            cargo_inadimplente = ctx.guild.get_role(int(configs.get('cargo_inadimplente', '0') or 0))
            if cargo_inadimplente and cargo_inadimplente in membro.roles:
                await self.regularizar_membro(membro, configs)
                corrigidos.append(membro.mention)
            else:
                ja_regulares.append(membro.mention)

        def format_report_list(mentions):
            if not mentions: return "Nenhum"
            text = "\n".join(mentions)
            if len(text) > 1024:
                truncated_text = text[:1000]
                last_newline = truncated_text.rfind('\n')
                if last_newline != -1:
                    truncated_text = truncated_text[:last_newline]
                num_omitted = len(mentions) - truncated_text.count('\n') - 1
                return f"{truncated_text}\n... e mais {num_omitted} membros."
            return text

        embed = discord.Embed(title="✅ Sincronização de Pagamentos Concluída", description=f"Analisado o período desde {ultimo_reset.strftime('%d/%m %H:%M')} UTC.")
        embed.add_field(name=f"Acesso Restaurado ({len(corrigidos)})", value=format_report_list(corrigidos), inline=False)
        embed.add_field(name=f"Pagamentos Contabilizados ({len(ja_regulares)})", value=format_report_list(ja_regulares), inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="corrigir-taxas", hidden=True)
    @check_permission_level(4)
    async def corrigir_taxas(self, ctx):
        await ctx.send("⚙️ **Iniciando correção de emergência!** A analisar pagamentos desde o último reset...")
        configs = await self.bot.db_manager.get_all_configs(['taxa_dia_semana', 'taxa_semanal_valor', 'cargo_inadimplente', 'cargo_membro'])
        dia_reset = int(configs.get('taxa_dia_semana', '6') or 6)
        valor_taxa = int(configs.get('taxa_semanal_valor', 0) or 0)
        hoje = datetime.now(timezone)
        dias_desde_reset = (hoje.weekday() - dia_reset + 7) % 7
        ultimo_reset = (hoje - timedelta(days=dias_desde_reset)).replace(hour=12, minute=0, second=0, microsecond=0)

        pagamentos = await self.bot.db_manager.execute_query(
            "SELECT DISTINCT user_id FROM transacoes WHERE descricao LIKE 'Pagamento de taxa semanal%' AND data >= $1 AND valor = $2",
            ultimo_reset, valor_taxa, fetch="all"
        )
        if not pagamentos:
            return await ctx.send("Nenhum pagamento encontrado no período. Nenhuma correção necessária.")

        pagadores_ids = {p['user_id'] for p in pagamentos}
        corrigidos, ja_regulares = [], []
        for user_id in pagadores_ids:
            membro = ctx.guild.get_member(user_id)
            if not membro: continue

            await self.bot.db_manager.execute_query(
                "INSERT INTO taxas (user_id, status_ciclo) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET status_ciclo = $2",
                user_id, 'PAGO_ATRASADO'
            )

            cargo_inadimplente = ctx.guild.get_role(int(configs.get('cargo_inadimplente', '0') or 0))
            if cargo_inadimplente and cargo_inadimplente in membro.roles:
                await self.regularizar_membro(membro, configs)
                corrigidos.append(membro.mention)
            else:
                ja_regulares.append(membro.mention)

        embed = discord.Embed(title="✅ Correção de Taxas Concluída", description=f"Analisado o período desde {ultimo_reset.strftime('%d/%m %H:%M')} UTC.")
        embed.add_field(name=f"Acesso Restaurado ({len(corrigidos)})", value="\n".join(corrigidos) or "Nenhum", inline=False)
        embed.add_field(name=f"Pagamentos Contabilizados ({len(ja_regulares)})", value="\n".join(ja_regulares) or "Nenhum", inline=False)
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Taxas(bot))



