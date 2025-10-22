import discord
from discord.ext import commands, tasks
from utils.permissions import check_permission_level
from datetime import datetime, time, timedelta, timezone
from collections import defaultdict
import asyncio

from utils.views import TaxaPrataView

# Função auxiliar para formatar listas longas em embeds
def format_list_for_embed(mentions, limit=40):
    """Formata uma lista de menções para um campo de embed, truncando se necessário."""
    if not mentions:
        return "Nenhum membro nesta categoria."
    
    display_mentions = mentions[:limit]
    text = "\n".join(display_mentions)
    
    remaining_count = len(mentions) - limit
    if remaining_count > 0:
        text += f"\n... e mais {remaining_count} membros."
        
    # Limite de 1024 caracteres por valor de campo
    if len(text) > 1024:
        text = text[:1020] + "\n..."
        
    return text

class Taxas(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.ciclo_semanal_taxas.start()
        self.atualizar_relatorio_automatico.start()
        self.gerenciar_canal_e_anuncios_taxas.start()
        print("Módulo de Taxas v2.9 (Gestão Manual e Logs Detalhados) pronto.")

    def cog_unload(self):
        self.ciclo_semanal_taxas.cancel()
        self.atualizar_relatorio_automatico.cancel()
        self.gerenciar_canal_e_anuncios_taxas.cancel()

    # --- Listener on_member_update e regularizar_membro (mantidos) ---
    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        configs = await self.bot.db_manager.get_all_configs(['cargo_membro'])
        cargo_membro_id = int(configs.get('cargo_membro', '0') or 0)
        if cargo_membro_id == 0:
            return
        cargo_membro = after.guild.get_role(cargo_membro_id)
        if not cargo_membro:
            return
        if cargo_membro not in before.roles and cargo_membro in after.roles:
            await self.bot.db_manager.execute_query(
                """INSERT INTO taxas (user_id, status_ciclo, data_entrada)
                   VALUES ($1, 'ISENTO_NOVO_MEMBRO', $2)
                   ON CONFLICT (user_id) DO UPDATE
                   SET data_entrada = EXCLUDED.data_entrada, status_ciclo = 'ISENTO_NOVO_MEMBRO'""",
                after.id, datetime.now(timezone.utc)
            )

    async def regularizar_membro(self, membro, configs):
        cargo_inadimplente = membro.guild.get_role(int(configs.get('cargo_inadimplente', '0') or 0))
        cargo_membro = membro.guild.get_role(int(configs.get('cargo_membro', '0') or 0))
        if not cargo_inadimplente or not cargo_membro:
            return
        try:
            if cargo_inadimplente in membro.roles:
                await membro.remove_roles(cargo_inadimplente, reason="Taxa regularizada")
            if cargo_membro not in membro.roles:
                await membro.add_roles(cargo_membro, reason="Taxa regularizada")
        except discord.Forbidden:
            print(f"Erro de permissão para {membro.name}")

    # --- Lógica de Relatório Atualizada (usa função auxiliar) ---
    async def _update_report_message(self, canal: discord.TextChannel, config_key: str, embed: discord.Embed):
        try:
            msg_id = int(await self.bot.db_manager.get_config_value(config_key, '0') or 0)
        except Exception:
            msg_id = 0

        if msg_id:
            try:
                msg = await canal.fetch_message(msg_id)
                await msg.edit(content=None, embed=embed)
                return
            except discord.NotFound:
                msg_id = 0
            except discord.HTTPException as e:
                if getattr(e, "code", None) == 50035:
                    count = 0
                    if embed.description and embed.description != "Nenhum membro nesta categoria.":
                        count = embed.description.count('\n') + 1
                    error_embed = discord.Embed(
                        title=embed.title,
                        description=f"Erro: A lista de {count} membros é demasiado longa para ser exibida.",
                        color=discord.Color.orange()
                    )
                    try:
                        if msg_id:
                            msg = await canal.fetch_message(msg_id)
                            await msg.edit(content=None, embed=error_embed)
                            return
                    except discord.NotFound:
                        pass
                print(f"Erro de HTTP ao editar relatório ({config_key}): {e}")

        try:
            nova_msg = await canal.send(embed=embed)
            await self.bot.db_manager.set_config_value(config_key, str(nova_msg.id))
        except Exception as e:
            print(f"Falha ao criar/atualizar mensagem de relatório ({config_key}): {e}")

    # --- Tarefas em Segundo Plano ---
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
                    status_map[status].append(f"{membro.mention} (`{membro.name}#{membro.discriminator}`)")

            pendentes = status_map.get('PENDENTE', [])
            embed_pendentes = discord.Embed(
                title=f"🔴 Membros Pendentes ({len(pendentes)})",
                description=format_list_for_embed(pendentes),
                color=discord.Color.red()
            )
            await self._update_report_message(canal, 'taxa_msg_id_pendentes', embed_pendentes)

            pagos = status_map.get('PAGO_ANTECIPADO', []) + status_map.get('PAGO_ATRASADO', []) + status_map.get('PAGO_MANUAL', [])
            embed_pagos = discord.Embed(
                title=f"🟢 Membros Pagos ({len(pagos)})",
                description=format_list_for_embed(pagos),
                color=discord.Color.green()
            )
            await self._update_report_message(canal, 'taxa_msg_id_pagos', embed_pagos)

            isentos = status_map.get('ISENTO_NOVO_MEMBRO', []) + status_map.get('ISENTO_MANUAL', [])
            embed_isentos = discord.Embed(
                title=f"😇 Membros Isentos ({len(isentos)})",
                description=format_list_for_embed(isentos),
                color=discord.Color.light_grey()
            )
            await self._update_report_message(canal, 'taxa_msg_id_isentos', embed_isentos)

        except Exception as e:
            print(f"Erro ao atualizar relatório automático de taxas: {e}")

    @atualizar_relatorio_automatico.before_loop
    async def before_relatorio(self):
        await self.bot.wait_until_ready()

    @tasks.loop(time=time(hour=0, minute=1, tzinfo=datetime.now().astimezone().tzinfo))
    async def gerenciar_canal_e_anuncios_taxas(self):
        try:
            configs = await self.bot.db_manager.get_all_configs([
                'canal_pagamento_taxas', 'cargo_membro',
                'taxa_dia_abertura', 'taxa_dia_semana', 'taxa_mensagem_abertura'
            ])
            canal_id = int(configs.get('canal_pagamento_taxas', '0') or 0)
            cargo_id = int(configs.get('cargo_membro', '0') or 0)
            dia_abertura = int(configs.get('taxa_dia_abertura', '5') or 5)
            dia_reset = int(configs.get('taxa_dia_semana', '6') or 6)
            dia_fechamento = (dia_reset + 1) % 7

            if canal_id == 0 or cargo_id == 0:
                print("AVISO: Canal de pagamento ou cargo de membro não configurados para gestão de acesso.")
                return

            canal = self.bot.get_channel(canal_id)
            if not canal:
                print(f"AVISO: Canal {canal_id} não encontrado.")
                return

            guild = canal.guild
            cargo = guild.get_role(cargo_id)
            if not cargo:
                print(f"AVISO: Cargo {cargo_id} não encontrado no servidor {guild.name}.")
                return

            hoje = datetime.now().weekday()
            perms = canal.overwrites_for(cargo)

            if hoje == dia_abertura:
                if perms.send_messages is False or perms.send_messages is None:
                    perms.send_messages = True
                    await canal.set_permissions(cargo, overwrite=perms, reason="Abertura da janela de pagamento de taxa")
                    msg_abertura = configs.get('taxa_mensagem_abertura', '')
                    if msg_abertura:
                        try:
                            await canal.send(msg_abertura)
                        except Exception as e:
                            print(f"Erro ao enviar mensagem de abertura: {e}")
                    print(f"Canal {canal.name} ABERTO para pagamento de taxa.")

            elif hoje == dia_fechamento:
                if perms.send_messages is not False:
                    perms.send_messages = False
                    await canal.set_permissions(cargo, overwrite=perms, reason="Fechamento da janela de pagamento de taxa")
                    print(f"Canal {canal.name} FECHADO para pagamento de taxa.")

        except Exception as e:
            print(f"Erro na tarefa de gestão do canal de taxas: {e}")

    @gerenciar_canal_e_anuncios_taxas.before_loop
    async def before_gerenciar_canal(self):
        await self.bot.wait_until_ready()

    # --- Ciclo Semanal ---
    @tasks.loop(time=time(hour=12, minute=0, tzinfo=datetime.now().astimezone().tzinfo))
    async def ciclo_semanal_taxas(self):
        dia_reset = int(await self.bot.db_manager.get_config_value('taxa_dia_semana', '6') or 6)
        if datetime.now().weekday() == dia_reset:
            await self.executar_ciclo_de_taxas(resetar_ciclo=True)

    # --- Execução do Ciclo com LOGS DETALHADOS ---
    async def executar_ciclo_de_taxas(self, ctx=None, resetar_ciclo: bool = False):
        guild = ctx.guild if ctx else (self.bot.guilds[0] if self.bot.guilds else None)
        if not guild:
            return print("ERRO: Bot não está em nenhum servidor.")
        
        configs = await self.bot.db_manager.get_all_configs([
            'cargo_membro', 'cargo_inadimplente', 'cargo_isento', 'canal_log_taxas',
            'taxa_mensagem_inadimplente', 'taxa_semanal_valor', 'canal_pagamento_taxas', 'taxa_mensagem_reset'
        ])
        canal_log = self.bot.get_channel(int(configs.get('canal_log_taxas', '0') or 0))
        msg_inadimplente_template = configs.get('taxa_mensagem_inadimplente')
        valor_taxa = configs.get('taxa_semanal_valor', '0')

        # Envia anúncio de reset se aplicável
        if resetar_ciclo:
            canal_pagamento_id = int(configs.get('canal_pagamento_taxas', '0') or 0)
            msg_reset = configs.get('taxa_mensagem_reset', '')
            if canal_pagamento_id and msg_reset:
                canal_pagamento = self.bot.get_channel(canal_pagamento_id)
                if canal_pagamento:
                    try:
                        await canal_pagamento.send(msg_reset)
                    except Exception as e:
                        print(f"Erro ao enviar mensagem de reset no canal de pagamento: {e}")

        membros_pendentes_db = await self.bot.db_manager.execute_query("SELECT user_id, data_entrada FROM taxas WHERE status_ciclo = 'PENDENTE'", fetch="all")
        novos_isentos, inadimplentes, falhas = [], [], []
        membros_com_isencao_cargo = []
        uma_semana_atras = datetime.now(timezone.utc) - timedelta(days=7)

        cargo_isento = guild.get_role(int(configs.get('cargo_isento', '0') or 0))

        for registro in membros_pendentes_db:
            user_id = registro.get('user_id')
            membro = guild.get_member(user_id)
            if not membro:
                continue
            
            if cargo_isento and cargo_isento in membro.roles:
                membros_com_isencao_cargo.append(membro)
                continue
                
            data_entrada = registro.get('data_entrada')
            if data_entrada and data_entrada > uma_semana_atras:
                novos_isentos.append(membro)
                await self.bot.db_manager.execute_query("UPDATE taxas SET status_ciclo = 'ISENTO_NOVO_MEMBRO' WHERE user_id = $1", membro.id)
                continue
                
            try:
                membro_role = guild.get_role(int(configs.get('cargo_membro', '0') or 0))
                inadimplente_role = guild.get_role(int(configs.get('cargo_inadimplente', '0') or 0))
                needs_update = False
                if membro_role and membro_role in membro.roles:
                    await membro.remove_roles(membro_role, reason="Ciclo de taxa")
                    needs_update = True
                if inadimplente_role and inadimplente_role not in membro.roles:
                    await membro.add_roles(inadimplente_role, reason="Ciclo de taxa")
                    needs_update = True
                if needs_update:
                     inadimplentes.append(membro)
                     if msg_inadimplente_template:
                         try:
                             msg_dm = msg_inadimplente_template.format(member=membro.mention, tax_value=valor_taxa)
                             await membro.send(msg_dm)
                         except discord.Forbidden:
                             print(f"Não foi possível enviar DM para {membro.name} (provavelmente desativada).")
                         except Exception as dm_error:
                             print(f"Erro ao enviar DM para {membro.name}: {dm_error}")
            except Exception as e:
                falhas.append(f"{membro.name} (`{membro.id}`): {e}")
                print(f"Erro ao processar taxas para {membro.name}: {e}")

        # --- LOG DETALHADO ---
        embed = discord.Embed(title="Relatório Detalhado do Ciclo de Taxas", timestamp=datetime.now(timezone.utc))
        embed.description = "**Modo: Aplicação de Penalidades**"
        
        embed.add_field(name=f"🔴 Inadimplentes Aplicados ({len(inadimplentes)})", value=format_list_for_embed([m.mention for m in inadimplentes]), inline=False)
        embed.add_field(name=f"🐣 Novos Membros Isentos ({len(novos_isentos)})", value=format_list_for_embed([m.mention for m in novos_isentos]), inline=False)
        embed.add_field(name=f"🛡️ Membros com Cargo Isento ({len(membros_com_isencao_cargo)})", value=format_list_for_embed([m.mention for m in membros_com_isencao_cargo]), inline=False)

        resetados_db = []
        if resetar_ciclo:
            embed.description = "**Modo: Ciclo Semanal Completo (com Reset)**"
            resetados_db = await self.bot.db_manager.execute_query(
                "UPDATE taxas SET status_ciclo = 'PENDENTE' WHERE status_ciclo LIKE 'PAGO_%' OR status_ciclo = 'ISENTO_NOVO_MEMBRO' OR status_ciclo = 'ISENTO_MANUAL' RETURNING user_id",
                fetch="all"
            )
            membros_resetados = [guild.get_member(r['user_id']) for r in resetados_db if guild.get_member(r['user_id'])]
            embed.add_field(name=f"🔄 Status Resetados para Pendente ({len(membros_resetados)})", value=format_list_for_embed([m.mention for m in membros_resetados]), inline=False)

        if falhas:
            embed.add_field(name=f"❌ Falhas ({len(falhas)})", value="\n".join(falhas), inline=False)
        
        log_msg = f"Ciclo de taxas executado. {len(inadimplentes)} inadimplentes, {len(novos_isentos)} novos isentos."
        if resetar_ciclo: log_msg += f" {len(resetados_db)} status resetados."
        
        if ctx: await ctx.send(log_msg)
        if canal_log:
            try: await canal_log.send(embed=embed)
            except Exception as log_e: print(f"Erro ao enviar log detalhado: {log_e}")
        print(log_msg)

    # --- Comandos do Utilizador (mantidos) ---
    @commands.command(name="pagar-taxa")
    async def pagar_taxa(self, ctx):
        configs = await self.bot.db_manager.get_all_configs([
            'taxa_semanal_valor', 'taxa_dia_semana', 'taxa_dia_abertura',
            'cargo_membro', 'cargo_inadimplente'
        ])
        valor_taxa = int(configs.get('taxa_semanal_valor', 0) or 0)
        if valor_taxa == 0:
            return await ctx.send("ℹ️ O sistema de taxas está atualmente desativado.")

        status_db = await self.bot.db_manager.execute_query(
            "SELECT status_ciclo FROM taxas WHERE user_id = $1", ctx.author.id, fetch="one"
        )
        status_atual = status_db['status_ciclo'] if status_db else 'PENDENTE'

        if status_atual.startswith('PAGO'):
            return await ctx.send(f"✅ {ctx.author.mention}, você já pagou a taxa para este ciclo. Tudo certo!", delete_after=20)

        hoje = datetime.now().weekday()
        dia_abertura = int(configs.get('taxa_dia_abertura', '5') or 5)

        inadimplente_role_id = int(configs.get('cargo_inadimplente', '0') or 0)
        esta_inadimplente = False
        if inadimplente_role_id:
            inadimplente_role = ctx.guild.get_role(inadimplente_role_id)
            if inadimplente_role and inadimplente_role in ctx.author.roles:
                esta_inadimplente = True

        pode_pagar_antecipado = status_atual == 'PENDENTE' and (hoje >= dia_abertura)

        if not pode_pagar_antecipado and not esta_inadimplente:
            dias = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
            return await ctx.send(
                f"⏳ {ctx.author.mention}, a janela para pagamento **antecipado** abre apenas na **{dias[dia_abertura]}**. Se você não estiver inadimplente, aguarde.",
                delete_after=20
            )

        try:
            economia = self.bot.get_cog('Economia')
            saldo_atual = await economia.get_saldo(ctx.author.id)
            if saldo_atual < valor_taxa:
                return await ctx.send(
                    f"❌ {ctx.author.mention}, saldo insuficiente! A taxa custa **{valor_taxa}** moedas e você possui apenas **{saldo_atual}**."
                )

            status_pagamento = 'PAGO_ANTECIPADO' if (pode_pagar_antecipado and not esta_inadimplente) else 'PAGO_ATRASADO'
            await economia.levantar(ctx.author.id, valor_taxa, f"Pagamento de taxa semanal ({status_pagamento})")

            await self.bot.db_manager.execute_query(
                "INSERT INTO taxas (user_id, status_ciclo) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET status_ciclo = $2",
                ctx.author.id, status_pagamento
            )

            mensagem_sucesso = f"✅ Pagamento de **{valor_taxa}** moedas recebido, {ctx.author.mention}! Seu status neste ciclo é: **{status_pagamento}**."
            if esta_inadimplente:
                await self.regularizar_membro(ctx.author, configs)
                mensagem_sucesso += " Seu acesso foi restaurado!"

            await ctx.send(mensagem_sucesso)

        except ValueError:
            await ctx.send(f"❌ {ctx.author.mention}, saldo insuficiente! A taxa custa **{valor_taxa}** moedas.")
        except Exception as e:
            await ctx.send(f"⚠️ Ocorreu um erro ao processar o pagamento. Tente novamente ou contacte a staff. Erro: {e}")

    @commands.command(name="paguei-prata")
    async def paguei_prata(self, ctx):
        if not ctx.message.attachments:
            return await ctx.send(f"❌ {ctx.author.mention}, anexe o print do comprovativo na mesma mensagem do comando `!paguei-prata`.", delete_after=20)

        attachment = ctx.message.attachments[0]
        content_type = getattr(attachment, "content_type", None)
        if not content_type or not content_type.startswith("image/"):
            return await ctx.send(f"❌ {ctx.author.mention}, o anexo deve ser uma imagem (print).", delete_after=20)

        try:
            submissao = await self.bot.db_manager.execute_query(
                "INSERT INTO submissoes_taxa (user_id, message_id, status, anexo_url) VALUES ($1, $2, $3, $4) RETURNING id",
                ctx.author.id, 0, 'pendente', attachment.url, fetch="one"
            )
            canal_aprovacao_id = int((await self.bot.db_manager.get_config_value('canal_pagamento_taxas', '0') or 0))
            if canal_aprovacao_id:
                canal_aprovacao = self.bot.get_channel(canal_aprovacao_id)
                if canal_aprovacao:
                    embed = discord.Embed(
                        title="Submissão: Pagamento em Prata",
                        description=f"Usuário: {ctx.author.mention}\nID: {ctx.author.id}",
                        color=discord.Color.blurple(),
                        timestamp=datetime.now(timezone.utc)
                    )
                    embed.set_image(url=attachment.url)
                    msg = await canal_aprovacao.send(embed=embed, view=TaxaPrataView(self.bot))
                    await self.bot.db_manager.execute_query(
                        "UPDATE submissoes_taxa SET message_id = $1 WHERE id = $2", msg.id, submissao['id']
                    )

            await ctx.send(f"✅ {ctx.author.mention}, comprovativo enviado para análise da staff! Aguarde a aprovação para ter seu acesso restaurado.", delete_after=20)
        except Exception as e:
            print(f"Erro ao enviar submissão de prata: {e}")
            await ctx.send("❌ Falha ao enviar o comprovativo. Tente novamente ou contacte a staff.", delete_after=20)

    @commands.command(name="sincronizar-pagamentos", hidden=True)
    @check_permission_level(4)
    async def sincronizar_pagamentos(self, ctx):
        configs = await self.bot.db_manager.get_all_configs(['taxa_dia_semana', 'taxa_semanal_valor', 'cargo_inadimplente', 'cargo_membro'])
        dia_reset = int(configs.get('taxa_dia_semana', '6') or 6)
        valor_taxa = int(configs.get('taxa_semanal_valor', 0) or 0)
        hoje = datetime.now(timezone.utc)
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
            if not membro:
                continue

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
            if not mentions:
                return "Nenhum"
            text = "\n".join(mentions)
            if len(text) > 1024:
                truncated_text = text[:1000]
                last_newline = truncated_text.rfind('\n')
                if last_newline != -1:
                    truncated_text = truncated_text[:last_newline]
                num_omitted = len(mentions) - truncated_text.count('\n') - 1
                return f"{truncated_text}\n... e mais {num_omitted} membros."
            return text

        embed = discord.Embed(
            title="✅ Sincronização de Pagamentos Concluída",
            description=f"Analisado o período desde {ultimo_reset.strftime('%d/%m %H:%M')} UTC."
        )
        embed.add_field(name=f"Acesso Restaurado ({len(corrigidos)})", value=format_report_list(corrigidos), inline=False)
        embed.add_field(name=f"Pagamentos Contabilizados ({len(ja_regulares)})", value=format_report_list(ja_regulares), inline=False)
        await ctx.send(embed=embed)

    # --- Comandos de Gestão Manual ---
    @commands.group(name="taxamanual", invoke_without_command=True, hidden=True)
    @check_permission_level(2)
    async def taxa_manual(self, ctx):
         await ctx.send("Use `!taxamanual pago <@membro>` ou `!taxamanual isento <@membro>`.")

    @taxa_manual.command(name="pago")
    async def taxa_manual_pago(self, ctx, membro: discord.Member):
        try:
            configs = await self.bot.db_manager.get_all_configs(['cargo_inadimplente', 'cargo_membro'])
            await self.bot.db_manager.execute_query(
                "INSERT INTO taxas (user_id, status_ciclo) VALUES ($1, 'PAGO_MANUAL') ON CONFLICT (user_id) DO UPDATE SET status_ciclo = 'PAGO_MANUAL'",
                membro.id
            )
            await self.regularizar_membro(membro, configs)
            await ctx.send(f"✅ {membro.mention} foi marcado manualmente como **PAGO** para este ciclo.")
            canal_log = self.bot.get_channel(int(await self.bot.db_manager.get_config_value('canal_log_taxas', '0') or 0))
            if canal_log:
                await canal_log.send(f"ℹ️ {ctx.author.mention} marcou {membro.mention} como **PAGO** manualmente.")
        except Exception as e:
            await ctx.send(f"❌ Erro ao marcar como pago: {e}")

    @taxa_manual.command(name="isento")
    async def taxa_manual_isento(self, ctx, membro: discord.Member):
        try:
            configs = await self.bot.db_manager.get_all_configs(['cargo_inadimplente', 'cargo_membro'])
            await self.bot.db_manager.execute_query(
                "INSERT INTO taxas (user_id, status_ciclo) VALUES ($1, 'ISENTO_MANUAL') ON CONFLICT (user_id) DO UPDATE SET status_ciclo = 'ISENTO_MANUAL'",
                membro.id
            )
            await self.regularizar_membro(membro, configs)
            await ctx.send(f"✅ {membro.mention} foi marcado manualmente como **ISENTO** para este ciclo.")
            canal_log = self.bot.get_channel(int(await self.bot.db_manager.get_config_value('canal_log_taxas', '0') or 0))
            if canal_log:
                await canal_log.send(f"ℹ️ {ctx.author.mention} marcou {membro.mention} como **ISENTO** manualmente.")
        except Exception as e:
            await ctx.send(f"❌ Erro ao marcar como isento: {e}")

async def setup(bot):
    await bot.add_cog(Taxas(bot))



