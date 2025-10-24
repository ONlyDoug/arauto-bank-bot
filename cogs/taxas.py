import discord
from discord.ext import commands, tasks
from utils.permissions import check_permission_level
from datetime import datetime, time, timedelta, timezone
from collections import defaultdict
import asyncio
from utils.views import TaxaPrataView
from zoneinfo import ZoneInfo  # <-- Importado ZoneInfo para GMT-3

def format_list_for_embed(member_data, limit=40):
    if not member_data:
        return "Nenhum membro nesta categoria."
    display_data = member_data[:limit]
    text = "\n".join(display_data)
    remaining_count = len(member_data) - limit
    if remaining_count > 0:
        text += f"\n... e mais {remaining_count} membros."
    if len(text) > 4096:
        text = text[:4090] + "\n..."
    return text

class Taxas(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.ciclo_semanal_taxas.start()
        self.atualizar_relatorio_automatico.start()
        self.gerenciar_canal_e_anuncios_taxas.start()
        print("Módulo de Taxas v3.2 (Final - Horário GMT-3) pronto.")

    def cog_unload(self):
        self.ciclo_semanal_taxas.cancel()
        self.atualizar_relatorio_automatico.cancel()
        self.gerenciar_canal_e_anuncios_taxas.cancel()

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        try:
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
        except Exception as e:
            print(f"Erro no listener on_member_update: {e}")

    async def regularizar_membro(self, membro: discord.Member, configs: dict):
        try:
            cargo_inadimplente = membro.guild.get_role(int(configs.get('cargo_inadimplente', '0') or 0))
            cargo_membro = membro.guild.get_role(int(configs.get('cargo_membro', '0') or 0))
            if not cargo_membro:
                return
            roles_to_add, roles_to_remove = [], []
            if cargo_membro not in membro.roles:
                roles_to_add.append(cargo_membro)
            if cargo_inadimplente and cargo_inadimplente in membro.roles:
                roles_to_remove.append(cargo_inadimplente)
            if roles_to_add:
                await membro.add_roles(*roles_to_add, reason="Taxa regularizada")
            if roles_to_remove:
                await membro.remove_roles(*roles_to_remove, reason="Taxa regularizada")
        except discord.Forbidden:
            print(f"Erro de permissão ao regularizar {membro.name}")
        except Exception as e:
            print(f"Erro ao regularizar {membro.name}: {e}")

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
        try:
            canal_id = int(await self.bot.db_manager.get_config_value('canal_relatorio_taxas', '0') or 0)
            if canal_id == 0:
                return
            canal = self.bot.get_channel(canal_id)
            if not canal:
                return

            cargo_isento_id = int(await self.bot.db_manager.get_config_value('cargo_isento', '0') or 0)
            membros_cargo_isento_ids = set()
            if cargo_isento_id and (cargo_isento := canal.guild.get_role(cargo_isento_id)):
                membros_cargo_isento_ids = {m.id for m in cargo_isento.members}

            registros = await self.bot.db_manager.execute_query("SELECT user_id, status_ciclo FROM taxas", fetch="all")
            status_map = defaultdict(list)
            membros_isentos_cargo_report = []

            for r in registros:
                user_id = r['user_id']
                if user_id in membros_cargo_isento_ids:
                    if (membro := canal.guild.get_member(user_id)):
                        membros_isentos_cargo_report.append(f"{membro.mention} (`{membro.name}#{membro.discriminator}`)")
                    continue
                if (membro := canal.guild.get_member(user_id)):
                    status_map[r['status_ciclo']].append(f"{membro.mention} (`{membro.name}#{membro.discriminator}`)")

            for chave in ['PENDENTE', 'PAGO_ANTECIPADO', 'PAGO_ATRASADO', 'PAGO_MANUAL', 'ISENTO_NOVO_MEMBRO', 'ISENTO_MANUAL']:
                status_map.setdefault(chave, [])

            for status in status_map:
                status_map[status].sort(key=lambda x: x.split('(`')[1].lower() if '(`' in x else x)
            membros_isentos_cargo_report.sort(key=lambda x: x.split('(`')[1].lower() if '(`' in x else x)

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
    async def before_relatorio(self):
        await self.bot.wait_until_ready()

    @tasks.loop(time=time(hour=0, minute=0, tzinfo=ZoneInfo("America/Sao_Paulo")))  # 00:00 GMT-3 (São_Paulo)
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
                return
            canal = self.bot.get_channel(canal_id)
            if not canal:
                return
            cargo = canal.guild.get_role(cargo_id)
            if not cargo:
                return

            # Usa fuso GMT-3 para determinar o dia (America/Sao_Paulo)
            hoje = datetime.now(ZoneInfo("America/Sao_Paulo")).weekday()
            perms = canal.overwrites_for(cargo)

            if hoje == dia_abertura:
                if perms.send_messages is not True:
                    perms.send_messages = True
                    await canal.set_permissions(cargo, overwrite=perms, reason="Abertura janela taxa")
                    msg_abertura = configs.get('taxa_mensagem_abertura', '')
                    if msg_abertura:
                        try:
                            await canal.send(msg_abertura)
                        except Exception as e:
                            print(f"Erro ao enviar mensagem de abertura: {e}")
                    print(f"Canal {canal.name} ABERTO para taxa (GMT-3).")
            elif hoje == dia_fechamento:
                if perms.send_messages is not False:
                    perms.send_messages = False
                    await canal.set_permissions(cargo, overwrite=perms, reason="Fechamento janela taxa")
                    print(f"Canal {canal.name} FECHADO para taxa (GMT-3).")
                    try:
                        await canal.purge(limit=200, check=lambda msg: not msg.pinned)
                        await self._enviar_instrucoes_pagamento(canal)
                        print(f"Canal {canal.name} limpo e instruções atualizadas.")
                    except discord.Forbidden:
                        print(f"Sem permissão para limpar {canal.name}.")
                    except Exception as e:
                        print(f"Erro ao limpar/instruir {canal.name}: {e}")
        except Exception as e:
            print(f"Erro task gerenciar_canal_e_anuncios_taxas: {e}")

    @gerenciar_canal_e_anuncios_taxas.before_loop
    async def before_gerenciar_canal(self):
        await self.bot.wait_until_ready()

    @tasks.loop(time=time(hour=12, minute=0, tzinfo=datetime.now().astimezone().tzinfo))
    async def ciclo_semanal_taxas(self):
         dia_reset = int(await self.bot.db_manager.get_config_value('taxa_dia_semana', '6') or 6)
         # Usar fuso horário local do servidor para esta comparação
         if datetime.now().astimezone().weekday() == dia_reset:
             print(f"[{datetime.now()}] Iniciando ciclo semanal COMPLETO de taxas...")
             await self.executar_ciclo_de_taxas(resetar_ciclo=True)

    async def executar_ciclo_de_taxas(self, ctx=None, resetar_ciclo: bool = False):
        guild = ctx.guild if ctx else (self.bot.guilds[0] if self.bot.guilds else None)
        if not guild:
            return

        configs = await self.bot.db_manager.get_all_configs([
            'cargo_membro', 'cargo_inadimplente', 'cargo_isento', 'canal_log_taxas',
            'taxa_mensagem_inadimplente', 'taxa_semanal_valor', 'canal_pagamento_taxas', 'taxa_mensagem_reset'
        ])
        canal_log = self.bot.get_channel(int(configs.get('canal_log_taxas', '0') or 0))
        msg_inadimplente_template = configs.get('taxa_mensagem_inadimplente')
        valor_taxa = configs.get('taxa_semanal_valor', '0')

        if resetar_ciclo:
            canal_pagamento_id = int(configs.get('canal_pagamento_taxas', '0') or 0)
            msg_reset = configs.get('taxa_mensagem_reset', '')
            if canal_pagamento_id and msg_reset and (canal_pgto := self.bot.get_channel(canal_pagamento_id)):
                try:
                    await canal_pgto.send(msg_reset)
                except Exception:
                    pass

        membros_pendentes_db = await self.bot.db_manager.execute_query("SELECT user_id, data_entrada FROM taxas WHERE status_ciclo = 'PENDENTE'", fetch="all")
        novos_isentos, inadimplentes, falhas, isentos_cargo = [], [], [], []
        uma_semana_atras = datetime.now(timezone.utc) - timedelta(days=7)
        cargo_isento = guild.get_role(int(configs.get('cargo_isento', '0') or 0))

        for registro in membros_pendentes_db:
            membro = guild.get_member(registro.get('user_id'))
            if not membro:
                continue
            if cargo_isento and cargo_isento in membro.roles:
                isentos_cargo.append(membro)
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
                            await membro.send(msg_inadimplente_template.format(member=membro.mention, tax_value=valor_taxa))
                        except Exception:
                            pass
            except Exception as e:
                falhas.append(f"{membro.name} (`{membro.id}`): {e}")

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
                try:
                    await ctx.send("Erro ao gerar relatório detalhado.")
                except:
                    pass

        # Envia para canal de logs configurado
        if canal_log:
            try:
                await canal_log.send(embed=embed)
            except Exception as log_e:
                print(f"Erro ao enviar log detalhado: {log_e}")

        log_msg = f"Ciclo de taxas executado. {len(inadimplentes)} inadimplentes, {len(novos_isentos)} novos isentos."
        if resetar_ciclo:
            log_msg += f" {len(resetados_db)} status resetados."
        print(log_msg)

    @commands.command(name="pagar-taxa")
    async def pagar_taxa(self, ctx):
        configs = await self.bot.db_manager.get_all_configs([
             'taxa_semanal_valor', 'taxa_aceitar_moedas',
             'cargo_membro', 'cargo_inadimplente', 'canal_pagamento_taxas'
        ])

        valor_lido_str = str(configs.get('taxa_aceitar_moedas') or 'true').strip().lower()
        if valor_lido_str == 'false':
            try: await ctx.message.delete()
            except: pass
            return await ctx.send(f"⚠️ {ctx.author.mention}, o pagamento de taxas com moedas está temporariamente desativado.", delete_after=20)

        canal_pagamento_id = int(configs.get('canal_pagamento_taxas', '0') or 0)
        if canal_pagamento_id and ctx.channel.id != canal_pagamento_id:
            try: await ctx.message.delete()
            except: pass
            canal_pagamento = self.bot.get_channel(canal_pagamento_id)
            mention = f" no canal {canal_pagamento.mention}" if canal_pagamento else ""
            return await ctx.send(f"❌ {ctx.author.mention}, este comando só pode ser usado{mention}.", delete_after=15)

        if not ctx.channel.permissions_for(ctx.author).send_messages:
            inadimplente_role_id = int(configs.get('cargo_inadimplente', '0') or 0)
            is_inadimplente = discord.utils.get(ctx.author.roles, id=inadimplente_role_id) if inadimplente_role_id else None
            if not is_inadimplente:
                try: await ctx.message.delete()
                except: pass
                return await ctx.send(f"⏳ {ctx.author.mention}, o canal de pagamento está fechado para pagamentos antecipados agora.", delete_after=20)

        try:
            valor_taxa = int(configs.get('taxa_semanal_valor', 0) or 0)
            if valor_taxa == 0:
                return await ctx.send("ℹ️ Sistema de taxas desativado.")

            economia = self.bot.get_cog('Economia')
            if not economia:
                return await ctx.send("⚠️ Sistema econômico indisponível. Tente mais tarde.")

            saldo_atual = await economia.get_saldo(ctx.author.id)
            if saldo_atual < valor_taxa:
                return await ctx.send(f"❌ {ctx.author.mention}, saldo insuficiente! Precisa de **{valor_taxa}** 🪙, possui **{saldo_atual}** 🪙.")

            status_pagamento = 'PAGO_ANTECIPADO' if ctx.channel.permissions_for(ctx.author).send_messages else 'PAGO_ATRASADO'
            await economia.levantar(ctx.author.id, valor_taxa, f"Pagamento de taxa semanal ({status_pagamento})")
            await self.bot.db_manager.execute_query("INSERT INTO taxas (user_id, status_ciclo) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET status_ciclo = $2", ctx.author.id, status_pagamento)

            configs_local = configs
            if discord.utils.get(ctx.author.roles, id=int(configs_local.get('cargo_inadimplente', '0') or 0)):
                await self.regularizar_membro(ctx.author, configs_local)
                msg_sucesso = f"✅ Pagamento de **{valor_taxa}** 🪙 recebido, {ctx.author.mention}! Status: **{status_pagamento}**. Acesso restaurado!"
            else:
                msg_sucesso = f"✅ Pagamento de **{valor_taxa}** 🪙 recebido, {ctx.author.mention}! Status: **{status_pagamento}**."
            await ctx.send(msg_sucesso)
        except Exception as e:
            await ctx.send(f"⚠️ Erro no pagamento: {e}")

    @commands.command(name="paguei-prata")
    async def paguei_prata(self, ctx):
        configs = await self.bot.db_manager.get_all_configs([
            'cargo_inadimplente', 'canal_pagamento_taxas', 'canal_aprovacao'
        ])
        canal_pagamento_id = int(configs.get('canal_pagamento_taxas', '0') or 0)
        canal_aprovacao_id = int(configs.get('canal_aprovacao', '0') or 0)

        # Verifica se está no canal de pagamento configurado
        if canal_pagamento_id and ctx.channel.id != canal_pagamento_id:
            try: await ctx.message.delete()
            except: pass
            canal_pagamento = self.bot.get_channel(canal_pagamento_id)
            mention = f" no canal {canal_pagamento.mention}" if canal_pagamento else ""
            return await ctx.send(f"❌ {ctx.author.mention}, este comando só pode ser usado{mention}.", delete_after=15)

        # Verifica permissão do canal
        if not ctx.channel.permissions_for(ctx.author).send_messages:
            inadimplente_role_id = int(configs.get('cargo_inadimplente', '0') or 0)
            is_inadimplente = discord.utils.get(ctx.author.roles, id=inadimplente_role_id) if inadimplente_role_id else None
            if not is_inadimplente:
                try: await ctx.message.delete()
                except: pass
                return await ctx.send(f"⏳ {ctx.author.mention}, o canal está fechado para envio de comprovativos agora.", delete_after=20)

        # Validação do anexo
        if not ctx.message.attachments:
            return await ctx.send(f"❌ {ctx.author.mention}, anexe o print do comprovativo na mesma mensagem do comando `!paguei-prata`.", delete_after=20)

        attachment = ctx.message.attachments[0]
        content_type = getattr(attachment, "content_type", None)
        if not content_type or not content_type.startswith("image/"):
            return await ctx.send(f"❌ {ctx.author.mention}, o anexo deve ser uma imagem (print).", delete_after=20)

        # Verifica se canal de aprovação está configurado e existe
        if not canal_aprovacao_id:
            return await ctx.send("⚠️ O canal de aprovações não foi configurado pela administração. Contacte a staff.", delete_after=30)
        canal_aprovacao = self.bot.get_channel(canal_aprovacao_id)
        if not canal_aprovacao:
            return await ctx.send(f"⚠️ Erro: Canal de aprovações configurado (ID: {canal_aprovacao_id}) não encontrado.", delete_after=30)

        # Prepara embed para o canal de aprovação
        embed_aprovacao = discord.Embed(
            title="🧾 Submissão: Pagamento em Prata",
            description=f"**Membro:** {ctx.author.mention} (`{ctx.author.id}`)",
            color=discord.Color.orange(),
            timestamp=datetime.now(timezone.utc)
        )
        embed_aprovacao.set_image(url=attachment.url)
        embed_aprovacao.set_footer(text="Aguardando ação da Staff...")

        try:
            # Envia para o canal de aprovação com a View (botões)
            msg_aprovacao = await canal_aprovacao.send(embed=embed_aprovacao, view=TaxaPrataView(self.bot))

            # Regista a submissão associando o message_id correto
            await self.bot.db_manager.execute_query(
                "INSERT INTO submissoes_taxa (user_id, message_id, status, anexo_url) VALUES ($1, $2, $3, $4)",
                ctx.author.id, msg_aprovacao.id, 'pendente', attachment.url
            )

            # Feedback ao utilizador no canal de pagamento
            await ctx.send(f"✅ {ctx.author.mention}, comprovativo enviado para análise da staff em {canal_aprovacao.mention}! Aguarde a aprovação.", delete_after=60)
            try: await ctx.message.add_reaction("👍")
            except: pass

        except discord.Forbidden:
            await ctx.send(f"❌ Erro de permissão ao enviar para {canal_aprovacao.mention}. Verifique as permissões do bot.", delete_after=30)
        except Exception as e:
            print(f"Erro ao enviar submissão de prata: {e}")
            await ctx.send("❌ Falha ao enviar o comprovativo. Tente novamente ou contacte a staff.", delete_after=20)

    @commands.command(name="forcar-taxa", hidden=True)
    @check_permission_level(4)
    async def forcar_taxa(self, ctx):
        await ctx.send("🔥 Forçando execução do ciclo de penalidades (sem resetar)...")
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

    @commands.group(name="taxamanual", invoke_without_command=True, hidden=True)
    @check_permission_level(3)
    async def taxa_manual(self, ctx):
        await ctx.send("Use `!taxamanual <status> <@membro>`. Status: `pago`, `isento`, `removerpago`, `removerisento`.")

    async def _log_manual_action(self, ctx, membro, acao):
        canal_log = self.bot.get_channel(int(await self.bot.db_manager.get_config_value('canal_log_taxas', '0') or 0))
        if canal_log:
            await canal_log.send(f"ℹ️ **Ação Manual:** {ctx.author.mention} definiu o status de {membro.mention} como **{acao}**.")

    @taxa_manual.command(name="pago")
    async def taxa_manual_pago(self, ctx, membro: discord.Member):
        try:
            configs = await self.bot.db_manager.get_all_configs(['cargo_inadimplente', 'cargo_membro'])
            await self.bot.db_manager.execute_query("INSERT INTO taxas (user_id, status_ciclo) VALUES ($1, 'PAGO_MANUAL') ON CONFLICT (user_id) DO UPDATE SET status_ciclo = 'PAGO_MANUAL'", membro.id)
            await self.regularizar_membro(membro, configs)
            await ctx.send(f"✅ {membro.mention} marcado como **PAGO** manualmente.")
            await self._log_manual_action(ctx, membro, "PAGO_MANUAL")
        except Exception as e:
            await ctx.send(f"❌ Erro: {e}")

    @taxa_manual.command(name="isento")
    async def taxa_manual_isento(self, ctx, membro: discord.Member):
        try:
            configs = await self.bot.db_manager.get_all_configs(['cargo_inadimplente', 'cargo_membro'])
            await self.bot.db_manager.execute_query("INSERT INTO taxas (user_id, status_ciclo) VALUES ($1, 'ISENTO_MANUAL') ON CONFLICT (user_id) DO UPDATE SET status_ciclo = 'ISENTO_MANUAL'", membro.id)
            await self.regularizar_membro(membro, configs)
            await ctx.send(f"✅ {membro.mention} marcado como **ISENTO** manualmente.")
            await self._log_manual_action(ctx, membro, "ISENTO_MANUAL")
        except Exception as e:
            await ctx.send(f"❌ Erro: {e}")

    @taxa_manual.command(name="removerpago")
    async def taxa_manual_remover_pago(self, ctx, membro: discord.Member):
        try:
            await self.bot.db_manager.execute_query("UPDATE taxas SET status_ciclo = 'PENDENTE' WHERE user_id = $1 AND status_ciclo LIKE 'PAGO_%'", membro.id)
            await ctx.send(f"✅ Status PAGO removido de {membro.mention}. Status atual: **PENDENTE**.")
            await self._log_manual_action(ctx, membro, "PENDENTE (Remoção de PAGO)")
        except Exception as e:
            await ctx.send(f"❌ Erro: {e}")

    @taxa_manual.command(name="removerisento")
    async def taxa_manual_remover_isento(self, ctx, membro: discord.Member):
        try:
            await self.bot.db_manager.execute_query("UPDATE taxas SET status_ciclo = 'PENDENTE' WHERE user_id = $1 AND status_ciclo LIKE 'ISENTO_%'", membro.id)
            await ctx.send(f"✅ Status ISENTO removido de {membro.mention}. Status atual: **PENDENTE**.")
            await self._log_manual_action(ctx, membro, "PENDENTE (Remoção de ISENTO)")
        except Exception as e:
            await ctx.send(f"❌ Erro: {e}")

    async def _controlar_canal_pagamento(self, ctx, abrir: bool):
        configs = await self.bot.db_manager.get_all_configs(['canal_pagamento_taxas', 'cargo_membro'])
        canal_id = int(configs.get('canal_pagamento_taxas', '0') or 0)
        cargo_id = int(configs.get('cargo_membro', '0') or 0)
        if not canal_id or not cargo_id:
            return await ctx.send("❌ Canal de pagamento ou cargo membro não configurados.")
        canal = self.bot.get_channel(canal_id)
        cargo = ctx.guild.get_role(cargo_id)
        if not canal or not cargo:
            return await ctx.send("❌ Canal ou cargo não encontrados.")

        try:
            perms = canal.overwrites_for(cargo)
            perms.send_messages = abrir
            await canal.set_permissions(cargo, overwrite=perms, reason=f"Controlo manual por {ctx.author.name}")
            status = "ABERTO" if abrir else "FECHADO"
            await ctx.send(f"✅ Canal {canal.mention} foi **{status}** para {cargo.mention}.")
        except discord.Forbidden:
            await ctx.send("❌ Sem permissão para alterar as permissões do canal.")
        except Exception as e:
            await ctx.send(f"❌ Erro ao controlar canal: {e}")

    @commands.command(name="abrircanalpagamento", hidden=True)
    @check_permission_level(4)
    async def abrir_canal_pagamento(self, ctx):
        await self._controlar_canal_pagamento(ctx, abrir=True)

    @commands.command(name="fecharcanalpagamento", hidden=True)
    @check_permission_level(4)
    async def fechar_canal_pagamento(self, ctx):
        await self._controlar_canal_pagamento(ctx, abrir=False)

    async def _enviar_instrucoes_pagamento(self, canal: discord.TextChannel):
        embed = discord.Embed(
            title="🪙 Instruções para Pagamento da Taxa Semanal",
            description="Leia atentamente como regularizar a sua situação.",
            color=discord.Color.gold()
        )
        embed.add_field(
            name="Opção 1: Pagar com Moedas (GC 🪙)",
            value=f"- Use o comando `!pagar-taxa` neste canal.\n"
                  f"- O valor será debitado automaticamente do seu saldo.\n"
                  f"- Seu acesso é restaurado **imediatamente**.",
            inline=False
        )
        embed.add_field(
            name="Opção 2: Pagar com Prata (🥈)",
            value=f"- Faça o pagamento da taxa em prata no jogo para a conta da guilda.\n"
                  f"- Tire um print **completo** da tela do jogo mostrando:\n"
                  f"  - A confirmação do envio da prata.\n"
                  f"  - **A data e hora do seu computador visíveis**.\n"
                  f"- Use o comando `!paguei-prata` **anexando o print na mesma mensagem**.\n"
                  f"- Aguarde a **aprovação manual** da staff. Seu acesso só será restaurado após a aprovação.",
            inline=False
        )
        embed.add_field(
            name="⚠️ Atenção ⚠️",
            value="- O canal só fica aberto para pagamento durante a janela definida.\n"
                  "- Membros com o cargo 'Inadimplente' podem pagar a qualquer momento.\n"
                  "- Novos membros são isentos da primeira taxa.",
            inline=False
        )
        embed.set_footer(text="Mantenha sua taxa em dia e contribua com a guilda!")

        try:
            async for msg in canal.history(limit=10):
                if msg.pinned and msg.author == self.bot.user and msg.embeds and msg.embeds[0].title.startswith("🪙 Instruções"):
                    try:
                        await msg.unpin()
                        await msg.delete()
                    except Exception:
                        pass

            msg_instrucoes = await canal.send(embed=embed)
            try:
                await msg_instrucoes.pin()
            except Exception:
                pass
        except discord.Forbidden:
            print(f"Sem permissão para fixar/apagar mensagens em {canal.name}")
        except Exception as e:
            print(f"Erro ao enviar/fixar instruções em {canal.name}: {e}")

    @commands.command(name="limparcanalpagamento", hidden=True)
    @check_permission_level(4)
    async def limpar_canal_pagamento(self, ctx):
        configs = await self.bot.db_manager.get_all_configs(['canal_pagamento_taxas'])
        canal_id = int(configs.get('canal_pagamento_taxas', '0') or 0)
        if not canal_id:
            return await ctx.send("❌ Canal de pagamento não configurado.")
        canal = self.bot.get_channel(canal_id)
        if not canal:
            return await ctx.send("❌ Canal de pagamento não encontrado.")

        try:
            await ctx.send(f"🧹 A limpar mensagens antigas em {canal.mention}...")
            deleted = await canal.purge(limit=200, check=lambda msg: not msg.pinned)
            await self._enviar_instrucoes_pagamento(canal)
            await ctx.send(f"✅ Canal limpo ({len(deleted)} mensagens removidas) e instruções atualizadas/fixadas.")
        except discord.Forbidden:
            await ctx.send("❌ Sem permissão para apagar mensagens neste canal.")
        except Exception as e:
            await ctx.send(f"❌ Erro ao limpar canal: {e}")

async def setup(bot): await bot.add_cog(Taxas(bot))



