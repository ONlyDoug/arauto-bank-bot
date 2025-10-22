import discord
from discord.ext import commands, tasks
from utils.permissions import check_permission_level
from datetime import datetime, time, timedelta, timezone
from collections import defaultdict
import asyncio
from utils.views import TaxaPrataView

# Função auxiliar
def format_list_for_embed(member_data, limit=40):
    if not member_data: return "Nenhum membro nesta categoria."
    display_data = member_data[:limit]
    text = "\n".join(display_data)
    remaining_count = len(member_data) - limit
    if remaining_count > 0: text += f"\n... e mais {remaining_count} membros."
    if len(text) > 4096: text = text[:4090] + "\n..."
    return text

class Taxas(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.ciclo_semanal_taxas.start()
        self.atualizar_relatorio_automatico.start()
        self.gerenciar_canal_e_anuncios_taxas.start()
        print("Módulo de Taxas v3.1 (Final) pronto.")

    def cog_unload(self):
        self.ciclo_semanal_taxas.cancel()
        self.atualizar_relatorio_automatico.cancel()
        self.gerenciar_canal_e_anuncios_taxas.cancel()

    # --- Listener e Regularizar ---
    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        try:
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
                    after.id, datetime.now(timezone.utc)
                )
                print(f"Novo membro {after.name} registado para isenção de taxa.")
        except Exception as e:
            print(f"Erro no listener on_member_update: {e}")

    async def regularizar_membro(self, membro: discord.Member, configs: dict):
        try:
            cargo_inadimplente = membro.guild.get_role(int(configs.get('cargo_inadimplente', '0') or 0))
            cargo_membro = membro.guild.get_role(int(configs.get('cargo_membro', '0') or 0))
            if not cargo_membro: return
            roles_to_add, roles_to_remove = [], []
            if cargo_membro not in membro.roles: roles_to_add.append(cargo_membro)
            if cargo_inadimplente and cargo_inadimplente in membro.roles: roles_to_remove.append(cargo_inadimplente)
            if roles_to_add: await membro.add_roles(*roles_to_add, reason="Taxa regularizada")
            if roles_to_remove: await membro.remove_roles(*roles_to_remove, reason="Taxa regularizada")
        except discord.Forbidden:
            print(f"Erro de permissão ao regularizar {membro.name}")
        except Exception as e:
            print(f"Erro ao regularizar {membro.name}: {e}")

    # --- Tarefas em Segundo Plano ---
    async def _update_report_message(self, canal: discord.TextChannel, config_key: str, embed: discord.Embed):
        try:
            msg_id = int(await self.bot.db_manager.get_config_value(config_key, '0') or 0)
        except Exception:
            msg_id = 0

        current_embed_dict = embed.to_dict()

        if msg_id:
            try:
                msg = await canal.fetch_message(msg_id)
                if not msg.embeds or msg.embeds[0].to_dict() != current_embed_dict:
                    await msg.edit(content=None, embed=embed)
                return
            except discord.NotFound:
                msg_id = 0
            except discord.HTTPException as e:
                if getattr(e, "code", None) == 50035:
                    count = embed.description.count('\n') + 1 if embed.description and embed.description != "Nenhum membro nesta categoria." else 0
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
                    except Exception:
                        pass
                print(f"Erro de HTTP ao editar relatório ({config_key}): {e}")
                msg_id = 0

        try:
            nova_msg = await canal.send(embed=embed)
            await self.bot.db_manager.set_config_value(config_key, str(nova_msg.id))
        except Exception as e:
            try:
                if hasattr(e, "code") and e.code == 50035:
                    count = embed.description.count('\n') + 1 if embed.description and embed.description != "Nenhum membro nesta categoria." else 0
                    error_embed = discord.Embed(
                        title=embed.title,
                        description=f"Erro: A lista de {count} membros é demasiado longa para ser exibida.",
                        color=discord.Color.orange()
                    )
                    nova_msg = await canal.send(embed=error_embed)
                    await self.bot.db_manager.set_config_value(config_key, str(nova_msg.id))
                else:
                    print(f"Falha ao criar/atualizar mensagem de relatório ({config_key}): {e}")
            except Exception as final_e:
                print(f"Falha CRÍTICA ao enviar/atualizar relatório ({config_key}): {final_e}")

    @tasks.loop(minutes=10)
    async def atualizar_relatorio_automatico(self):
        # Relatório com 4 categorias (Pendentes, Pagos, Isentos Novos, Isentos Cargo)
        try:
            canal_id = int(await self.bot.db_manager.get_config_value('canal_relatorio_taxas', '0') or 0)
            if canal_id == 0: return
            canal = self.bot.get_channel(canal_id)
            if not canal: return

            # Busca membros com cargo isento primeiro
            cargo_isento_id = int(await self.bot.db_manager.get_config_value('cargo_isento', '0') or 0)
            membros_cargo_isento_ids = set()
            if cargo_isento_id and (cargo_isento := canal.guild.get_role(cargo_isento_id)):
                membros_cargo_isento_ids = {m.id for m in cargo_isento.members}

            registros = await self.bot.db_manager.execute_query("SELECT user_id, status_ciclo FROM taxas", fetch="all")
            status_map = defaultdict(list)
            membros_isentos_cargo_report = []

            for r in registros:
                user_id = r['user_id']
                # Separa membros com cargo isento
                if user_id in membros_cargo_isento_ids:
                    if (membro := canal.guild.get_member(user_id)):
                         membros_isentos_cargo_report.append(f"{membro.mention} (`{membro.name}#{membro.discriminator}`)")
                    continue

                # Processa os restantes
                if (membro := canal.guild.get_member(user_id)):
                    status_map[r['status_ciclo']].append(f"{membro.mention} (`{membro.name}#{membro.discriminator}`)")

            # Garantir chaves mínimas
            for chave in ['PENDENTE', 'PAGO_ANTECIPADO', 'PAGO_ATRASADO', 'PAGO_MANUAL', 'ISENTO_NOVO_MEMBRO', 'ISENTO_MANUAL']:
                status_map.setdefault(chave, [])

            # Ordena as listas
            for status in status_map: status_map[status].sort(key=lambda x: x.split('(`')[1].lower() if '(`' in x else x)
            membros_isentos_cargo_report.sort(key=lambda x: x.split('(`')[1].lower() if '(`' in x else x)

            # Envia/Edita as 4 mensagens
            embed_pendentes = discord.Embed(title=f"🔴 Membros Pendentes ({len(status_map['PENDENTE'])})", description=format_list_for_embed(status_map['PENDENTE']), color=discord.Color.red())
            await self._update_report_message(canal, 'taxa_msg_id_pendentes', embed_pendentes)

            pagos = status_map['PAGO_ANTECIPADO'] + status_map['PAGO_ATRASADO'] + status_map['PAGO_MANUAL']
            embed_pagos = discord.Embed(title=f"🟢 Membros Pagos ({len(pagos)})", description=format_list_for_embed(pagos), color=discord.Color.green())
            await self._update_report_message(canal, 'taxa_msg_id_pagos', embed_pagos)

            embed_isentos_novos = discord.Embed(title=f"🐣 Isentos (Novos Membros) ({len(status_map['ISENTO_NOVO_MEMBRO'])})", description=format_list_for_embed(status_map['ISENTO_NOVO_MEMBRO']), color=discord.Color.light_grey())
            await self._update_report_message(canal, 'taxa_msg_id_isentos_novos', embed_isentos_novos)

            embed_isentos_cargo = discord.Embed(title=f"🛡️ Isentos (Cargo Específico) ({len(membros_isentos_cargo_report)})", description=format_list_for_embed(membros_isentos_cargo_report), color=discord.Color.dark_grey())
            await self._update_report_message(canal, 'taxa_msg_id_isentos_cargo', embed_isentos_cargo)

        except Exception as e:
            print(f"Erro crítico na task atualizar_relatorio_automatico: {e}")

    @atualizar_relatorio_automatico.before_loop
    async def before_relatorio(self): await self.bot.wait_until_ready()

    @tasks.loop(time=time(hour=0, minute=1, tzinfo=datetime.now().astimezone().tzinfo))
    async def gerenciar_canal_e_anuncios_taxas(self):
        # Gestão de abertura/fecho e LIMPEZA do canal
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
                # Abre se não estiver aberto
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
                # Fecha e limpa se não estiver fechado
                if perms.send_messages is not False:
                    perms.send_messages = False
                    await canal.set_permissions(cargo, overwrite=perms, reason="Fechamento da janela de pagamento de taxa")
                    print(f"Canal {canal.name} FECHADO para pagamento de taxa.")
                    # LIMPEZA DO CANAL
                    try:
                        await canal.purge(limit=200, check=lambda msg: not msg.pinned)
                        await canal.send("🧹 Mensagens anteriores limpas para organização.", delete_after=60)
                        print(f"Canal {canal.name} limpo.")
                    except discord.Forbidden:
                        print(f"Sem permissão para limpar o canal {canal.name}.")
                    except Exception as clean_e:
                        print(f"Erro ao limpar canal {canal.name}: {clean_e}")

        except Exception as e:
            print(f"Erro na tarefa gerenciar_canal_e_anuncios_taxas: {e}")

    @gerenciar_canal_e_anuncios_taxas.before_loop
    async def before_gerenciar_canal(self): await self.bot.wait_until_ready()

    @tasks.loop(time=time(hour=12, minute=0, tzinfo=datetime.now().astimezone().tzinfo))
    async def ciclo_semanal_taxas(self):
        dia_reset = int(await self.bot.db_manager.get_config_value('taxa_dia_semana', '6') or 6)
        if datetime.now().weekday() == dia_reset:
            print(f"[{datetime.now()}] Iniciando ciclo semanal completo de taxas...")
            await self.executar_ciclo_de_taxas(resetar_ciclo=True)

    async def executar_ciclo_de_taxas(self, ctx=None, resetar_ciclo: bool = False):
        # Lógica principal com LOGS DETALHADOS
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

        # Anúncio de reset
        if resetar_ciclo:
            canal_pagamento_id = int(configs.get('canal_pagamento_taxas', '0') or 0)
            msg_reset = configs.get('taxa_mensagem_reset', '')
            if canal_pagamento_id and msg_reset and (canal_pgto := self.bot.get_channel(canal_pagamento_id)):
                try: await canal_pgto.send(msg_reset)
                except Exception as e: print(f"Erro ao enviar msg reset: {e}")

        membros_pendentes_db = await self.bot.db_manager.execute_query("SELECT user_id, data_entrada FROM taxas WHERE status_ciclo = 'PENDENTE'", fetch="all")
        novos_isentos, inadimplentes, falhas, isentos_cargo = [], [], [], []
        uma_semana_atras = datetime.now(timezone.utc) - timedelta(days=7)
        cargo_isento = guild.get_role(int(configs.get('cargo_isento', '0') or 0))

        for registro in membros_pendentes_db:
            membro = guild.get_member(registro.get('user_id'))
            if not membro: continue
            if cargo_isento and cargo_isento in membro.roles:
                isentos_cargo.append(membro); continue
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
                    await membro.remove_roles(membro_role, reason="Ciclo de taxa"); needs_update = True
                if inadimplente_role and inadimplente_role not in membro.roles:
                    await membro.add_roles(inadimplente_role, reason="Ciclo de taxa"); needs_update = True
                if needs_update:
                    inadimplentes.append(membro)
                    if msg_inadimplente_template:
                        try:
                            await membro.send(msg_inadimplente_template.format(member=membro.mention, tax_value=valor_taxa))
                        except discord.Forbidden:
                            print(f"Não foi possível enviar DM para {membro.name}.")
                        except Exception as dm_error:
                            print(f"Erro ao enviar DM para {membro.name}: {dm_error}")
            except Exception as e:
                falhas.append(f"{membro.name} (`{membro.id}`): {e}")
                print(f"Erro ao processar taxas para {membro.name}: {e}")

        # --- LOG DETALHADO / RELATÓRIO ---
        embed = discord.Embed(title="Relatório Detalhado do Ciclo de Taxas", timestamp=datetime.now(timezone.utc))
        embed.description = "**Modo: Aplicação de Penalidades**"
        embed.add_field(name=f"🔴 Inadimplentes Aplicados ({len(inadimplentes)})", value=format_list_for_embed([m.mention for m in inadimplentes]), inline=False)
        embed.add_field(name=f"🐣 Novos Membros Isentos ({len(novos_isentos)})", value=format_list_for_embed([m.mention for m in novos_isentos]), inline=False)
        embed.add_field(name=f"🛡️ Membros com Cargo Isento ({len(isentos_cargo)})", value=format_list_for_embed([m.mention for m in isentos_cargo]), inline=False)

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

        # Envia o embed detalhado para o ctx, se houver
        if ctx:
            try:
                await ctx.send(embed=embed)
            except Exception as e:
                print(f"Erro ao enviar embed para ctx: {e}")
                try: await ctx.send("Erro ao gerar relatório detalhado.")
                except: pass

        # Envia para canal de logs configurado
        if canal_log:
            try: await canal_log.send(embed=embed)
            except Exception as log_e: print(f"Erro ao enviar log detalhado: {log_e}")

        log_msg = f"Ciclo de taxas executado. {len(inadimplentes)} inadimplentes, {len(novos_isentos)} novos isentos."
        if resetar_ciclo: log_msg += f" {len(resetados_db)} status resetados."
        print(log_msg)

    # --- Comandos do Utilizador com Verificação de Janela ---
    @commands.command(name="pagar-taxa")
    async def pagar_taxa(self, ctx):
        configs = await self.bot.db_manager.get_all_configs(['taxa_semanal_valor', 'taxa_dia_semana', 'taxa_dia_abertura', 'cargo_membro', 'cargo_inadimplente'])
        valor_taxa = int(configs.get('taxa_semanal_valor', 0) or 0)
        if valor_taxa == 0: return await ctx.send("ℹ️ Sistema de taxas desativado.")

        status_db = await self.bot.db_manager.execute_query("SELECT status_ciclo FROM taxas WHERE user_id = $1", ctx.author.id, fetch="one")
        status_atual = status_db['status_ciclo'] if status_db else 'PENDENTE'
        if status_atual.startswith('PAGO'): return await ctx.send(f"✅ {ctx.author.mention}, você já pagou.", delete_after=20)

        hoje = datetime.now().weekday()
        dia_abertura = int(configs.get('taxa_dia_abertura', '5') or 5)
        dia_reset = int(configs.get('taxa_dia_semana', '6') or 6)

        inadimplente_role = ctx.guild.get_role(int(configs.get('cargo_inadimplente', '0') or 0))
        esta_inadimplente = inadimplente_role and inadimplente_role in ctx.author.roles

        janela_aberta = (hoje >= dia_abertura)

        if not janela_aberta and not esta_inadimplente:
            dias = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
            try: await ctx.message.delete()
            except: pass
            return await ctx.send(f"⏳ {ctx.author.mention}, o canal de pagamento está fechado agora. A janela abre na **{dias[dia_abertura]}**.", delete_after=20)

        try:
            economia = self.bot.get_cog('Economia')
            saldo_atual = await economia.get_saldo(ctx.author.id)
            if saldo_atual < valor_taxa:
                return await ctx.send(f"❌ {ctx.author.mention}, saldo insuficiente! Precisa de **{valor_taxa}** 🪙, possui **{saldo_atual}** 🪙.")

            status_pagamento = 'PAGO_ANTECIPADO' if janela_aberta and not esta_inadimplente else 'PAGO_ATRASADO'
            await economia.levantar(ctx.author.id, valor_taxa, f"Pagamento de taxa semanal ({status_pagamento})")
            await self.bot.db_manager.execute_query("INSERT INTO taxas (user_id, status_ciclo) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET status_ciclo = $2", ctx.author.id, status_pagamento)

            msg_sucesso = f"✅ Pagamento de **{valor_taxa}** 🪙 recebido, {ctx.author.mention}! Status: **{status_pagamento}**."
            if esta_inadimplente:
                await self.regularizar_membro(ctx.author, configs)
                msg_sucesso += " Acesso restaurado!"
            await ctx.send(msg_sucesso)
        except Exception as e:
            await ctx.send(f"⚠️ Erro no pagamento: {e}")

    @commands.command(name="paguei-prata")
    async def paguei_prata(self, ctx):
        configs = await self.bot.db_manager.get_all_configs(['taxa_dia_semana', 'taxa_dia_abertura', 'cargo_inadimplente'])
        hoje = datetime.now().weekday()
        dia_abertura = int(configs.get('taxa_dia_abertura', '5') or 5)
        dia_reset = int(configs.get('taxa_dia_semana', '6') or 6)
        inadimplente_role = ctx.guild.get_role(int(configs.get('cargo_inadimplente', '0') or 0))
        esta_inadimplente = inadimplente_role and inadimplente_role in ctx.author.roles
        janela_aberta = (hoje >= dia_abertura)

        if not janela_aberta and not esta_inadimplente:
            dias = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
            try: await ctx.message.delete()
            except: pass
            return await ctx.send(f"⏳ {ctx.author.mention}, o canal está fechado para envio de comprovativos agora. A janela abre na **{dias[dia_abertura]}**.", delete_after=20)

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
                    await self.bot.db_manager.execute_query("UPDATE submissoes_taxa SET message_id = $1 WHERE id = $2", msg.id, submissao['id'])

            await ctx.send(f"✅ {ctx.author.mention}, comprovativo enviado para análise da staff! Aguarde a aprovação para ter seu acesso restaurado.", delete_after=20)
        except Exception as e:
            print(f"Erro ao enviar submissão de prata: {e}")
            await ctx.send("❌ Falha ao enviar o comprovativo. Tente novamente ou contacte a staff.", delete_after=20)

    # --- Comandos Admin (inalterados, chamadas para funções implementadas acima) ---
    @commands.command(name="forcar-taxa", hidden=True)
    @check_permission_level(4)
    async def forcar_taxa(self, ctx):
        await ctx.send("🔥 A forçar a execução do ciclo de penalidades (sem resetar)...")
        await self.executar_ciclo_de_taxas(ctx, resetar_ciclo=False)

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

        pagamentos_prata = await self.bot.db_manager.execute_query("SELECT user_id FROM submissoes_taxa WHERE status = 'aprovado'", fetch="all")
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

        embed = discord.Embed(
            title="✅ Sincronização de Pagamentos Concluída",
            description=f"Analisado o período desde {ultimo_reset.strftime('%d/%m %H:%M')} UTC."
        )
        embed.add_field(name=f"Acesso Restaurado ({len(corrigidos)})", value=format_report_list(corrigidos), inline=False)
        embed.add_field(name=f"Pagamentos Contabilizados ({len(ja_regulares)})", value=format_report_list(ja_regulares), inline=False)
        await ctx.send(embed=embed)

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

    # ... (outros comandos admin mantidos) ...

async def setup(bot):
    await bot.add_cog(Taxas(bot))



