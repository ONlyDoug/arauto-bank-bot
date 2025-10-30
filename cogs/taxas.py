import discord
from discord.ext import commands, tasks
from utils.permissions import check_permission_level
from datetime import datetime, time, timedelta, timezone
from collections import defaultdict
import asyncio
from utils.views import TaxaPrataView
from zoneinfo import ZoneInfo # Garante que a importação está presente

# Função auxiliar
def format_list_for_embed(member_data, limit=40):
    if not member_data: return "Nenhum membro nesta categoria."
    display_data = member_data[:limit]
    text = "\n".join(display_data)
    remaining_count = len(member_data) - limit
    if remaining_count > 0: text += f"\n... e mais {remaining_count} membros."
    if len(text) > 4096: text = text[:4090] + "\n..." # Limite do Discord
    return text

class Taxas(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.ciclo_semanal_taxas.start()
        self.atualizar_relatorio_automatico.start()
        self.gerenciar_canal_e_anuncios_taxas.start()
        print("Módulo de Taxas v3.3 (Verificação Prioritária) pronto.")

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
                    """INSERT INTO taxas (user_id, status_ciclo, data_entrada) VALUES ($1, 'ISENTO_NOVO_MEMBRO', $2)
                       ON CONFLICT (user_id) DO UPDATE SET data_entrada = EXCLUDED.data_entrada, status_ciclo = 'ISENTO_NOVO_MEMBRO'""",
                    after.id, datetime.now(timezone.utc))
                print(f"Novo membro {after.name} registado para isenção de taxa.")
        except Exception as e: print(f"Erro no listener on_member_update: {e}")

    async def regularizar_membro(self, membro: discord.Member, configs: dict):
        try:
            cargo_inadimplente = membro.guild.get_role(int(configs.get('cargo_inadimplente', '0') or 0))
            cargo_membro = membro.guild.get_role(int(configs.get('cargo_membro', '0') or 0))
            if not cargo_membro: return

            to_add, to_remove = [], []
            if cargo_membro not in membro.roles: to_add.append(cargo_membro)
            if cargo_inadimplente and cargo_inadimplente in membro.roles: to_remove.append(cargo_inadimplente)
            
            if to_add: await membro.add_roles(*to_add, reason="Taxa regularizada")
            if to_remove: await membro.remove_roles(*to_remove, reason="Taxa regularizada")
        except Exception as e: print(f"Erro ao regularizar {membro.name}: {e}")

    # --- Tarefas em Segundo Plano ---
    async def _update_report_message(self, canal: discord.TextChannel, config_key: str, embed: discord.Embed):
        try:
            msg_id = int(await self.bot.db_manager.get_config_value(config_key, '0') or 0)
        except ValueError: msg_id = 0
        current_embed_dict = embed.to_dict()

        if msg_id:
            try:
                msg = await canal.fetch_message(msg_id)
                if not msg.embeds or msg.embeds[0].to_dict() != current_embed_dict:
                    await msg.edit(content=None, embed=embed)
                return
            except discord.NotFound: msg_id = 0
            except discord.HTTPException as e:
                if getattr(e, "code", None) == 50035: # Mensagem muito longa
                    count = embed.description.count('\n') + 1 if embed.description != "Nenhum membro nesta categoria." else 0
                    error_embed = discord.Embed(title=embed.title, description=f"Erro: Lista de {count} membros muito longa.", color=discord.Color.orange())
                    try:
                        if msg_id: await msg.edit(content=None, embed=error_embed); return
                    except Exception: pass
                print(f"Erro HTTP ao editar relatório ({config_key}): {e}"); msg_id = 0

        try: # Cria nova mensagem
            nova_msg = await canal.send(embed=embed)
            await self.bot.db_manager.set_config_value(config_key, str(nova_msg.id))
        except discord.HTTPException as e:
             if getattr(e, "code", None) == 50035:
                 count = embed.description.count('\n') + 1 if embed.description != "Nenhum membro nesta categoria." else 0
                 error_embed = discord.Embed(title=embed.title, description=f"Erro: Lista de {count} membros muito longa.", color=discord.Color.orange())
                 try: nova_msg = await canal.send(embed=error_embed); await self.bot.db_manager.set_config_value(config_key, str(nova_msg.id))
                 except Exception as final_e: print(f"Falha CRÍTICA ao enviar erro relatório ({config_key}): {final_e}")
             else: print(f"Falha CRÍTICA ao enviar relatório ({config_key}): {e}")

    @tasks.loop(minutes=10)
    async def atualizar_relatorio_automatico(self):
        try:
            canal_id = int(await self.bot.db_manager.get_config_value('canal_relatorio_taxas', '0') or 0)
            if canal_id == 0: return
            canal = self.bot.get_channel(canal_id)
            if not canal: return

            cargo_isento_id = int(await self.bot.db_manager.get_config_value('cargo_isento', '0') or 0)
            membros_cargo_isento_ids = set()
            if cargo_isento_id and (cargo_isento := canal.guild.get_role(cargo_isento_id)):
                membros_cargo_isento_ids = {m.id for m in cargo_isento.members}

            registros = await self.bot.db_manager.execute_query("SELECT user_id, status_ciclo FROM taxas", fetch="all")
            status_map = defaultdict(list); isentos_cargo_report = []

            for r in registros:
                user_id = r['user_id']
                if user_id in membros_cargo_isento_ids:
                    if (membro := canal.guild.get_member(user_id)): isentos_cargo_report.append(f"{membro.mention} (`{membro.name}#{membro.discriminator}`)")
                    continue
                if (membro := canal.guild.get_member(user_id)): status_map[r.get('status_ciclo', 'PENDENTE')].append(f"{membro.mention} (`{membro.name}#{membro.discriminator}`)")

            for status in status_map: status_map[status].sort(key=lambda x: x.split('(`')[1].lower() if '(`' in x else x)
            isentos_cargo_report.sort(key=lambda x: x.split('(`')[1].lower() if '(`' in x else x)

            embed_pendentes = discord.Embed(title=f"🔴 Pendentes ({len(status_map['PENDENTE'])})", description=format_list_for_embed(status_map['PENDENTE']), color=discord.Color.red())
            await self._update_report_message(canal, 'taxa_msg_id_pendentes', embed_pendentes)
            pagos = status_map['PAGO_ANTECIPADO'] + status_map['PAGO_ATRASADO'] + status_map['PAGO_MANUAL']
            embed_pagos = discord.Embed(title=f"🟢 Pagos ({len(pagos)})", description=format_list_for_embed(pagos), color=discord.Color.green())
            await self._update_report_message(canal, 'taxa_msg_id_pagos', embed_pagos)
            embed_isentos_novos = discord.Embed(title=f"🐣 Isentos (Novos) ({len(status_map['ISENTO_NOVO_MEMBRO'])})", description=format_list_for_embed(status_map['ISENTO_NOVO_MEMBRO']), color=discord.Color.light_grey())
            await self._update_report_message(canal, 'taxa_msg_id_isentos_novos', embed_isentos_novos)
            embed_isentos_cargo = discord.Embed(title=f"🛡️ Isentos (Cargo) ({len(isentos_cargo_report)})", description=format_list_for_embed(isentos_cargo_report), color=discord.Color.dark_grey())
            await self._update_report_message(canal, 'taxa_msg_id_isentos_cargo', embed_isentos_cargo)
        except Exception as e: print(f"Erro task atualizar_relatorio_automatico: {e}")

    @atualizar_relatorio_automatico.before_loop
    async def before_relatorio(self): await self.bot.wait_until_ready()

    @tasks.loop(time=time(hour=0, minute=1, tzinfo=ZoneInfo("America/Sao_Paulo"))) # 00:01 GMT-3
    async def gerenciar_canal_e_anuncios_taxas(self):
        try:
            configs = await self.bot.db_manager.get_all_configs([
                'canal_pagamento_taxas', 'cargo_membro',
                'taxa_dia_abertura', 'taxa_dia_semana', 'taxa_mensagem_abertura', 'taxa_mensagem_fechamento',
                'canal_log_taxas'
            ])
            canal_id = int(configs.get('canal_pagamento_taxas', '0') or 0); cargo_id = int(configs.get('cargo_membro', '0') or 0)
            dia_abertura = int(configs.get('taxa_dia_abertura', '5') or 5); dia_reset = int(configs.get('taxa_dia_semana', '6') or 6)
            dia_fechamento = (dia_reset + 1) % 7
            if canal_id == 0 or cargo_id == 0: return
            canal = self.bot.get_channel(canal_id);
            if not canal: return
            cargo = canal.guild.get_role(cargo_id);
            if not cargo: return

            hoje = datetime.now(ZoneInfo("America/Sao_Paulo")).weekday(); perms = canal.overwrites_for(cargo)

            if hoje == dia_abertura:
                if perms.send_messages is not True:
                    perms.send_messages = True; await canal.set_permissions(cargo, overwrite=perms, reason="Abertura janela taxa")
                    msg_abertura = configs.get('taxa_mensagem_abertura', '');
                    if msg_abertura: await canal.send(embed=discord.Embed(title="🪙 Janela de Pagamento Aberta", description=msg_abertura, color=discord.Color.green()))
                    await self._log_acao_canal(f"Canal {canal.mention} **ABERTO** para {cargo.mention}.", canal)
            elif hoje == dia_fechamento:
                if perms.send_messages is not False:
                    perms.send_messages = False; await canal.set_permissions(cargo, overwrite=perms, reason="Fechamento janela taxa")
                    msg_fechamento = configs.get('taxa_mensagem_fechamento', '');
                    if msg_fechamento: await canal.send(embed=discord.Embed(title="❌ Janela de Pagamento Fechada", description=msg_fechamento, color=discord.Color.red()))
                    try: 
                        await asyncio.sleep(10) # Espera 10s
                        await canal.purge(limit=200, check=lambda msg: not msg.pinned)
                        await self._enviar_instrucoes_pagamento(canal)
                    except Exception as e: print(f"Erro limpar/instruir {canal.name}: {e}")
                    await self._log_acao_canal(f"Canal {canal.mention} **FECHADO** e limpo.", canal)
        except Exception as e: print(f"Erro task gerenciar_canal_e_anuncios_taxas: {e}")

    @gerenciar_canal_e_anuncios_taxas.before_loop
    async def before_gerenciar_canal(self): await self.bot.wait_until_ready()

    @tasks.loop(time=time(hour=12, minute=0, tzinfo=datetime.now().astimezone().tzinfo))
    async def ciclo_semanal_taxas(self):
         dia_reset = int(await self.bot.db_manager.get_config_value('taxa_dia_semana', '6') or 6)
         if datetime.now().astimezone().weekday() == dia_reset:
             print(f"[{datetime.now()}] Iniciando ciclo semanal COMPLETO de taxas...")
             await self.executar_ciclo_de_taxas(resetar_ciclo=True)

    async def executar_ciclo_de_taxas(self, ctx=None, resetar_ciclo: bool = False):
        guild = ctx.guild if ctx else (self.bot.guilds[0] if self.bot.guilds else None)
        if not guild: return print("ERRO: Bot não está em nenhum servidor.")
        
        configs = await self.bot.db_manager.get_all_configs([
            'cargo_membro', 'cargo_inadimplente', 'cargo_isento', 'canal_log_taxas',
            'taxa_mensagem_inadimplente', 'taxa_semanal_valor', 'canal_pagamento_taxas', 'taxa_mensagem_reset'
        ])
        canal_log = self.bot.get_channel(int(configs.get('canal_log_taxas', '0') or 0))
        msg_inadimplente_template = configs.get('taxa_mensagem_inadimplente')
        valor_taxa = configs.get('taxa_semanal_valor', '0')

        if resetar_ciclo: # Anúncio de reset
             canal_pagamento_id = int(configs.get('canal_pagamento_taxas', '0') or 0)
             msg_reset = configs.get('taxa_mensagem_reset', '')
             if canal_pagamento_id and msg_reset and (canal_pgto := self.bot.get_channel(canal_pagamento_id)):
                 try: await canal_pgto.send(embed=discord.Embed(title="🚨 Último Dia para Pagamento", description=msg_reset, color=discord.Color.orange()))
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
            try: # Aplica inadimplência
                membro_role = guild.get_role(int(configs.get('cargo_membro', '0') or 0))
                inadimplente_role = guild.get_role(int(configs.get('cargo_inadimplente', '0') or 0))
                needs_update = False
                if membro_role and membro_role in membro.roles: await membro.remove_roles(membro_role, reason="Ciclo taxa"); needs_update = True
                if inadimplente_role and inadimplente_role not in membro.roles: await membro.add_roles(inadimplente_role, reason="Ciclo taxa"); needs_update = True
                if needs_update:
                     inadimplentes.append(membro)
                     if msg_inadimplente_template: # Envia DM
                         try: await membro.send(msg_inadimplente_template.format(member=membro.mention, tax_value=valor_taxa))
                         except Exception as e: print(f"Falha DM {membro.name}: {e}")
            except Exception as e: falhas.append(f"{membro.mention} (`{membro.id}`): {e}")

        embed = discord.Embed(title="Relatório Detalhado do Ciclo de Taxas", timestamp=datetime.now(timezone.utc))
        embed.description = "**Modo: Aplicação de Penalidades**"
        embed.add_field(name=f"🔴 Inadimplentes Aplicados ({len(inadimplentes)})", value=format_list_for_embed([m.mention for m in inadimplentes]), inline=False)
        embed.add_field(name=f"🐣 Novos Membros Isentos ({len(novos_isentos)})", value=format_list_for_embed([m.mention for m in novos_isentos]), inline=False)
        embed.add_field(name=f"🛡️ Membros com Cargo Isento ({len(isentos_cargo)})", value=format_list_for_embed([m.mention for m in isentos_cargo]), inline=False)

        resetados_db = []
        if resetar_ciclo:
            embed.description = "**Modo: Ciclo Semanal Completo (com Reset)**"
            resetados_db = await self.bot.db_manager.execute_query("UPDATE taxas SET status_ciclo = 'PENDENTE' WHERE status_ciclo LIKE 'PAGO_%' OR status_ciclo = 'ISENTO_%' RETURNING user_id", fetch="all")
            membros_resetados = [m.mention for r in resetados_db if (m := guild.get_member(r['user_id']))]
            embed.add_field(name=f"🔄 Status Resetados para Pendente ({len(membros_resetados)})", value=format_list_for_embed(membros_resetados), inline=False)
        if falhas: embed.add_field(name=f"❌ Falhas ({len(falhas)})", value="\n".join(falhas), inline=False)
        
        if ctx: await ctx.send(embed=embed) # Envia embed detalhado no ctx
        if canal_log:
            try: await canal_log.send(embed=embed)
            except Exception as e: print(f"Erro ao enviar log: {e}")
        print(f"Ciclo taxas: {len(inadimplentes)} inad., {len(novos_isentos)} isen. novos, {len(isentos_cargo)} isen. cargo." + (f" {len(resetados_db)} resetados." if resetar_ciclo else ""))

    # --- Comandos do Utilizador (LÓGICA ATUALIZADA) ---
    @commands.command(name="pagar-taxa")
    async def pagar_taxa(self, ctx):
        # Apaga o comando do utilizador imediatamente para manter o canal limpo
        try: await ctx.message.delete()
        except: pass

        configs = await self.bot.db_manager.get_all_configs([
             'taxa_semanal_valor', 'taxa_aceitar_moedas', 'cargo_inadimplente', 'canal_pagamento_taxas'
        ])

        # --- 1. VERIFICAÇÃO DE CANAL ---
        canal_pagamento_id = int(configs.get('canal_pagamento_taxas', '0') or 0)
        if canal_pagamento_id and ctx.channel.id != canal_pagamento_id:
             canal_p = self.bot.get_channel(canal_pagamento_id); mention = f" em {canal_p.mention}" if canal_p else ""
             return await ctx.send(f"❌ {ctx.author.mention}, use este comando{mention}.", delete_after=15)

        # --- 2. VERIFICAÇÃO DE STATUS DE PAGAMENTO (PRIORITÁRIA) ---
        status_db = await self.bot.db_manager.execute_query("SELECT status_ciclo FROM taxas WHERE user_id = $1", ctx.author.id, fetch="one")
        status_atual = status_db['status_ciclo'] if status_db else 'PENDENTE'
        if status_atual.startswith('PAGO'):
            return await ctx.send(f"✅ {ctx.author.mention}, você já pagou a taxa para este ciclo. Não precisa de pagar novamente.", delete_after=20)

        # --- 3. VERIFICAÇÃO DE TOGGLE (MOEDAS) ---
        if str(configs.get('taxa_aceitar_moedas', 'true')).lower() == 'false':
             return await ctx.send(f"⚠️ {ctx.author.mention}, o pagamento de taxas com moedas está temporariamente desativado.", delete_after=20)

        # --- 4. VERIFICAÇÃO DE CANAL FECHADO/JANELA ---
        if not ctx.channel.permissions_for(ctx.author).send_messages:
            inadimplente_role = ctx.guild.get_role(int(configs.get('cargo_inadimplente', '0') or 0))
            if not (inadimplente_role and inadimplente_role in ctx.author.roles):
                 return await ctx.send(f"⏳ {ctx.author.mention}, o canal de pagamento está fechado para pagamentos antecipados agora.", delete_after=20)

        # --- 5. LÓGICA DE PAGAMENTO ---
        try:
            valor_taxa = int(configs.get('taxa_semanal_valor', 0) or 0)
            if valor_taxa == 0: return await ctx.send("ℹ️ Sistema de taxas desativado.", delete_after=20)

            economia = self.bot.get_cog('Economia'); saldo_atual = await economia.get_saldo(ctx.author.id)
            if saldo_atual < valor_taxa:
                return await ctx.send(f"❌ {ctx.author.mention}, saldo insuficiente! Precisa de **{valor_taxa}** 🪙, possui **{saldo_atual}** 🪙.", delete_after=20)

            status_pagamento = 'PAGO_ANTECIPADO' if ctx.channel.permissions_for(ctx.author).send_messages else 'PAGO_ATRASADO'
            await economia.levantar(ctx.author.id, valor_taxa, f"Pagamento de taxa semanal ({status_pagamento})")
            await self.bot.db_manager.execute_query("INSERT INTO taxas (user_id, status_ciclo) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET status_ciclo = $2", ctx.author.id, status_pagamento)
            
            msg_sucesso = f"✅ Pagamento de **{valor_taxa}** 🪙 recebido, {ctx.author.mention}! Status: **{status_pagamento}**."
            if discord.utils.get(ctx.author.roles, id=int(configs.get('cargo_inadimplente', '0') or 0)):
                await self.regularizar_membro(ctx.author, configs); msg_sucesso += " Acesso restaurado!"
            await ctx.send(msg_sucesso, delete_after=30) # Mensagem de sucesso também é temporária
        except Exception as e: await ctx.send(f"⚠️ Erro no pagamento: {e}", delete_after=20)

    @commands.command(name="paguei-prata")
    async def paguei_prata(self, ctx):
        # Apaga o comando do utilizador imediatamente
        try: await ctx.message.delete()
        except: pass
        
        configs = await self.bot.db_manager.get_all_configs(['cargo_inadimplente', 'canal_pagamento_taxas', 'canal_aprovacao'])
        canal_pagamento_id = int(configs.get('canal_pagamento_taxas', '0') or 0)
        canal_aprovacao_id = int(configs.get('canal_aprovacao', '0') or 0)

        # --- 1. VERIFICAÇÃO DE CANAL ---
        if canal_pagamento_id and ctx.channel.id != canal_pagamento_id:
             canal_p = self.bot.get_channel(canal_pagamento_id); mention = f" em {canal_p.mention}" if canal_p else ""
             return await ctx.send(f"❌ {ctx.author.mention}, use este comando{mention}.", delete_after=15)

        # --- 2. VERIFICAÇÃO DE STATUS DE PAGAMENTO (PRIORITÁRIA) ---
        status_db = await self.bot.db_manager.execute_query("SELECT status_ciclo FROM taxas WHERE user_id = $1", ctx.author.id, fetch="one")
        status_atual = status_db['status_ciclo'] if status_db else 'PENDENTE'
        if status_atual.startswith('PAGO'):
            return await ctx.send(f"✅ {ctx.author.mention}, você já pagou a taxa para este ciclo.", delete_after=20)

        # --- 3. VERIFICAÇÃO DE CANAL FECHADO/JANELA ---
        if not ctx.channel.permissions_for(ctx.author).send_messages:
            inadimplente_role = ctx.guild.get_role(int(configs.get('cargo_inadimplente', '0') or 0))
            if not (inadimplente_role and inadimplente_role in ctx.author.roles):
                 return await ctx.send(f"⏳ {ctx.author.mention}, o canal está fechado para envio de comprovativos agora.", delete_after=20)

        # --- 4. LÓGICA DE SUBMISSÃO ---
        if not ctx.message.attachments or not ctx.message.attachments[0].content_type.startswith('image/'):
            return await ctx.send(f"❌ {ctx.author.mention}, anexe o print na **mesma mensagem**.", delete_after=20)
        
        if not canal_aprovacao_id: return await ctx.send("⚠️ Canal de aprovações não configurado. Contacte a staff.", delete_after=30)
        canal_aprovacao = self.bot.get_channel(canal_aprovacao_id)
        if not canal_aprovacao: return await ctx.send(f"⚠️ Erro: Canal de aprovações (ID: {canal_aprovacao_id}) não encontrado.", delete_after=30)

        attachment = ctx.message.attachments[0]
        embed_aprovacao = discord.Embed(title="🧾 Submissão: Pagamento em Prata", description=f"**Membro:** {ctx.author.mention} (`{ctx.author.id}`)", color=discord.Color.orange(), timestamp=datetime.now(timezone.utc))
        embed_aprovacao.set_image(url=attachment.url); embed_aprovacao.set_footer(text="Aguardando ação da Staff...")

        try:
            msg_aprovacao = await canal_aprovacao.send(embed=embed_aprovacao, view=TaxaPrataView(self.bot))
            await self.bot.db_manager.execute_query(
                "INSERT INTO submissoes_taxa (user_id, message_id, status, anexo_url) VALUES ($1, $2, $3, $4)",
                ctx.author.id, msg_aprovacao.id, 'pendente', attachment.url
            )
            await ctx.send(f"✅ {ctx.author.mention}, comprovativo enviado para análise! Aguarde a aprovação.", delete_after=60)
            # Não reagimos mais à mensagem, pois ela será apagada.
        except Exception as e:
            print(f"Erro ao enviar submissão de prata: {e}")
            await ctx.send("❌ Falha ao enviar o comprovativo. Tente novamente ou contacte a staff.", delete_after=20)
            
    # --- NOVO COMANDO DE AJUDA ESPECÍFICO ---
    @commands.command(name="ajudataxa")
    async def ajuda_taxa(self, ctx):
        canal_pagamento_id = int(await self.bot.db_manager.get_config_value('canal_pagamento_taxas', '0') or 0)
        
        # Só funciona no canal de pagamento
        if not canal_pagamento_id or ctx.channel.id != canal_pagamento_id:
            try: await ctx.message.delete()
            except: pass
            return

        try:
            await ctx.message.delete() # Deleta o comando !ajudataxa
        except: pass
        
        # Envia uma versão temporária das instruções (sem fixar)
        embed_instrucoes = await self._construir_embed_instrucoes()
        await ctx.send(embed=embed_instrucoes, delete_after=120) # Aumentado para 2 minutos

    # --- Comandos de Administração ---
    @commands.command(name="forcar-taxa", hidden=True)
    @check_permission_level(4)
    async def forcar_taxa(self, ctx):
         await ctx.send("🔥 Forçando execução do ciclo de penalidades (sem resetar)...")
         await self.executar_ciclo_de_taxas(ctx, resetar_ciclo=False)

    @commands.command(name="sincronizar-pagamentos", hidden=True)
    @check_permission_level(4)
    async def sincronizar_pagamentos(self, ctx):
        await ctx.send("⚙️ **Iniciando Sincronização Total de Pagamentos!**\nA analisar pagamentos em moedas e em prata...")
        configs = await self.bot.db_manager.get_all_configs(['taxa_dia_semana', 'taxa_semanal_valor', 'cargo_inadimplente', 'cargo_membro'])
        dia_reset = int(configs.get('taxa_dia_semana', '6') or 6)
        valor_taxa = int(configs.get('taxa_semanal_valor', 0) or 0)
        hoje = datetime.now(timezone.utc)
        dias_desde_reset = (hoje.weekday() - dia_reset + 7) % 7
        ultimo_reset = (hoje - timedelta(days=dias_desde_reset)).replace(hour=12, minute=0, second=0, microsecond=0)

        pagamentos_moedas = await self.bot.db_manager.execute_query("SELECT DISTINCT user_id FROM transacoes WHERE (descricao LIKE 'Pagamento de taxa semanal%') AND data >= $1 AND valor = $2", ultimo_reset, valor_taxa, fetch="all")
        pagadores_moedas_ids = {p['user_id'] for p in pagamentos_moedas} if pagamentos_moedas else set()
        pagamentos_prata = await self.bot.db_manager.execute_query("SELECT user_id FROM submissoes_taxa WHERE status = 'aprovado'", fetch="all")
        pagadores_prata_ids = {p['user_id'] for p in pagamentos_prata} if pagamentos_prata else set()
        todos_pagadores_ids = pagadores_moedas_ids.union(pagadores_prata_ids)
        if not todos_pagadores_ids: return await ctx.send("Nenhum pagamento (moedas ou prata) encontrado para sincronizar.")

        corrigidos, ja_regulares = [], []
        for user_id in todos_pagadores_ids:
            membro = ctx.guild.get_member(user_id)
            if not membro: continue
            await self.bot.db_manager.execute_query("INSERT INTO taxas (user_id, status_ciclo) VALUES ($1, 'PAGO_ATRASADO') ON CONFLICT (user_id) DO UPDATE SET status_ciclo = 'PAGO_ATRASADO'", user_id)
            cargo_inadimplente = ctx.guild.get_role(int(configs.get('cargo_inadimplente', '0') or 0))
            if cargo_inadimplente and cargo_inadimplente in membro.roles:
                await self.regularizar_membro(membro, configs); corrigidos.append(membro.mention)
            else: ja_regulares.append(membro.mention)

        embed = discord.Embed(title="✅ Sincronização de Pagamentos Concluída", description=f"Analisado período desde {ultimo_reset.strftime('%d/%m %H:%M')} UTC.")
        embed.add_field(name=f"Acesso Restaurado ({len(corrigidos)})", value=format_list_for_embed(corrigidos), inline=False)
        embed.add_field(name=f"Pagamentos Contabilizados ({len(ja_regulares)})", value=format_list_for_embed(ja_regulares), inline=False)
        await ctx.send(embed=embed)

    @commands.group(name="taxamanual", invoke_without_command=True, hidden=True)
    @check_permission_level(3)
    async def taxa_manual(self, ctx): await ctx.send("Use `!taxamanual <status> <@membro>`. Status: `pago`, `isento`, `removerpago`, `removerisento`.")
    async def _log_manual_action(self, ctx, membro, acao):
        if canal_log := self.bot.get_channel(int(await self.bot.db_manager.get_config_value('canal_log_taxas', '0') or 0)):
            await canal_log.send(f"ℹ️ **Ação Manual:** {ctx.author.mention} definiu o status de {membro.mention} como **{acao}**.")
    @taxa_manual.command(name="pago", hidden=True)
    async def taxa_manual_pago(self, ctx, membro: discord.Member):
        try:
            configs = await self.bot.db_manager.get_all_configs(['cargo_inadimplente', 'cargo_membro'])
            await self.bot.db_manager.execute_query("INSERT INTO taxas (user_id, status_ciclo) VALUES ($1, 'PAGO_MANUAL') ON CONFLICT (user_id) DO UPDATE SET status_ciclo = 'PAGO_MANUAL'", membro.id)
            await self.regularizar_membro(membro, configs); await ctx.send(f"✅ {membro.mention} marcado como **PAGO**."); await self._log_manual_action(ctx, membro, "PAGO_MANUAL")
        except Exception as e: await ctx.send(f"❌ Erro: {e}")
    @taxa_manual.command(name="isento", hidden=True)
    async def taxa_manual_isento(self, ctx, membro: discord.Member):
        try:
            configs = await self.bot.db_manager.get_all_configs(['cargo_inadimplente', 'cargo_membro'])
            await self.bot.db_manager.execute_query("INSERT INTO taxas (user_id, status_ciclo) VALUES ($1, 'ISENTO_MANUAL') ON CONFLICT (user_id) DO UPDATE SET status_ciclo = 'ISENTO_MANUAL'", membro.id)
            await self.regularizar_membro(membro, configs); await ctx.send(f"✅ {membro.mention} marcado como **ISENTO**."); await self._log_manual_action(ctx, membro, "ISENTO_MANUAL")
        except Exception as e: await ctx.send(f"❌ Erro: {e}")
    @taxa_manual.command(name="removerpago", hidden=True)
    async def taxa_manual_remover_pago(self, ctx, membro: discord.Member):
        try:
            await self.bot.db_manager.execute_query("UPDATE taxas SET status_ciclo = 'PENDENTE' WHERE user_id = $1 AND status_ciclo LIKE 'PAGO_%'", membro.id)
            await ctx.send(f"✅ Status PAGO removido de {membro.mention}. Status: **PENDENTE**."); await self._log_manual_action(ctx, membro, "PENDENTE (Remoção de PAGO)")
        except Exception as e: await ctx.send(f"❌ Erro: {e}")
    @taxa_manual.command(name="removerisento", hidden=True)
    async def taxa_manual_remover_isento(self, ctx, membro: discord.Member):
        try:
            await self.bot.db_manager.execute_query("UPDATE taxas SET status_ciclo = 'PENDENTE' WHERE user_id = $1 AND status_ciclo LIKE 'ISENTO_%'", membro.id)
            await ctx.send(f"✅ Status ISENTO removido de {membro.mention}. Status: **PENDENTE**."); await self._log_manual_action(ctx, membro, "PENDENTE (Remoção de ISENTO)")
        except Exception as e: await ctx.send(f"❌ Erro: {e}")

    async def _controlar_canal_pagamento(self, ctx, abrir: bool):
        configs = await self.bot.db_manager.get_all_configs(['canal_pagamento_taxas', 'cargo_membro'])
        canal_id = int(configs.get('canal_pagamento_taxas', '0') or 0); cargo_id = int(configs.get('cargo_membro', '0') or 0)
        if not canal_id or not cargo_id: return await ctx.send("❌ Canal ou cargo membro não configurados.")
        canal = self.bot.get_channel(canal_id); cargo = ctx.guild.get_role(cargo_id)
        if not canal or not cargo: return await ctx.send("❌ Canal ou cargo não encontrados.")
        try:
            perms = canal.overwrites_for(cargo); perms.send_messages = abrir
            await canal.set_permissions(cargo, overwrite=perms, reason=f"Controlo manual por {ctx.author.name}")
            status = "ABERTO" if abrir else "FECHADO"; await ctx.send(f"✅ Canal {canal.mention} **{status}** para {cargo.mention}.")
        except Exception as e: await ctx.send(f"❌ Erro: {e}")
    @commands.command(name="abrircanalpagamento", hidden=True)
    @check_permission_level(4)
    async def abrir_canal_pagamento(self, ctx): await self._controlar_canal_pagamento(ctx, abrir=True)
    @commands.command(name="fecharcanalpagamento", hidden=True)
    @check_permission_level(4)
    async def fechar_canal_pagamento(self, ctx): await self._controlar_canal_pagamento(ctx, abrir=False)

    async def _construir_embed_instrucoes(self):
        valor_taxa = await self.bot.db_manager.get_config_value('taxa_semanal_valor', '0')
        aceita_moedas = (await self.bot.db_manager.get_config_value('taxa_aceitar_moedas', 'true') or 'true') == 'true'
        embed = discord.Embed(title="🪙 Instruções para Pagamento da Taxa Semanal", description=f"A taxa semanal é de **{valor_taxa} moedas**. Veja abaixo como pagar:", color=discord.Color.gold())
        if aceita_moedas:
            embed.add_field(name="Opção 1: Pagar com Moedas (GC 🪙)", value="- Use o comando `!pagar-taxa` neste canal.\n- O valor será debitado **automaticamente**.\n- O seu acesso é restaurado **imediatamente**.", inline=False)
        else:
             embed.add_field(name="Opção 1: Pagar com Moedas (GC 🪙)", value="ℹ️ O pagamento com moedas está **temporariamente desativado**.", inline=False)
        embed.add_field(name="Opção 2: Pagar com Prata (🥈)", value="- Envie o valor em Prata para o tesouro da guilda no jogo.\n- Tire um print **completo** da tela mostrando:\n  1. A confirmação do envio.\n  2. **A data e hora do seu computador/jogo visíveis**.\n- Use `!paguei-prata` **anexando o print na mesma mensagem**.\n- Aguarde a **aprovação manual** da staff.", inline=False)
        embed.add_field(name="⚠️ Atenção ⚠️", value="- O canal só fica aberto durante a janela de pagamento.\n- Membros 'Inadimplentes' podem pagar a qualquer momento.\n- Novos membros são isentos da primeira taxa.\n- Use `!ajudataxa` para ver esta mensagem novamente.", inline=False)
        embed.set_footer(text="Mantenha sua taxa em dia!")
        return embed

    async def _enviar_instrucoes_pagamento(self, canal: discord.TextChannel):
        embed_instrucoes = await self._construir_embed_instrucoes()
        try:
             async for msg in canal.history(limit=10):
                 if msg.pinned and msg.author == self.bot.user and msg.embeds and msg.embeds[0].title.startswith("🪙 Instruções"):
                     try: await msg.unpin(); await msg.delete()
                     except Exception: pass
             msg_instrucoes = await canal.send(embed=embed_instrucoes)
             try: await msg_instrucoes.pin()
             except Exception: pass
        except Exception as e: print(f"Erro ao enviar/fixar instruções: {e}")

    @commands.command(name="limparcanalpagamento", hidden=True)
    @check_permission_level(4)
    async def limpar_canal_pagamento(self, ctx):
        canal_id = int(await self.bot.db_manager.get_config_value('canal_pagamento_taxas', '0') or 0)
        if not canal_id: return await ctx.send("❌ Canal de pagamento não configurado.")
        canal = self.bot.get_channel(canal_id)
        if not canal: return await ctx.send("❌ Canal de pagamento não encontrado.")
        if canal != ctx.channel: return await ctx.send(f"❌ Comando deve ser usado em {canal.mention}.")

        try:
            await ctx.message.delete()
            msg_confirm = await ctx.send(f"🧹 A limpar mensagens antigas em {canal.mention}...")
            deleted = await canal.purge(limit=200, check=lambda msg: not msg.pinned)
            await self._enviar_instrucoes_pagamento(canal)
            await msg_confirm.edit(content=f"✅ Canal limpo ({len(deleted)} msgs) e instruções fixadas.", delete_after=10)
        except Exception as e: await ctx.send(f"❌ Erro: {e}", delete_after=15)

    @commands.command(name="definir-taxa", hidden=True)
    @check_permission_level(4)
    async def definir_taxa(self, ctx, valor: int):
        if valor < 0: return await ctx.send("❌ O valor não pode ser negativo.")
        await self.bot.db_manager.set_config_value('taxa_semanal_valor', str(valor))
        await ctx.send(f"✅ Valor da taxa semanal definido para **{valor}** moedas.")

    @commands.command(name="definir-taxa-dia", hidden=True)
    @check_permission_level(4)
    async def definir_taxa_dia(self, ctx, dia_da_semana: int):
        if not 0 <= dia_da_semana <= 6: return await ctx.send("❌ Dia inválido (0=Segunda, 6=Domingo).")
        dias = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
        await self.bot.db_manager.set_config_value('taxa_dia_semana', str(dia_da_semana))
        await ctx.send(f"✅ O ciclo de reset das taxas foi agendado para **{dias[dia_da_semana]}**.")

    @commands.command(name="definir-taxa-dia-abertura", hidden=True)
    @check_permission_level(4)
    async def definir_taxa_dia_abertura(self, ctx, dia_da_semana: int):
        if not 0 <= dia_da_semana <= 6: return await ctx.send("❌ Dia inválido (0=Segunda, 6=Domingo).")
        dias = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
        await self.bot.db_manager.set_config_value('taxa_dia_abertura', str(dia_da_semana))
        await ctx.send(f"✅ Janela de pagamento de taxas abrirá toda **{dias[dia_da_semana]}**.")


async def setup(bot): await bot.add_cog(Taxas(bot))



