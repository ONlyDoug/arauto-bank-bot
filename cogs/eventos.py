import discord
from discord.ext import commands, tasks
from discord import app_commands
import datetime
import asyncio
from utils.permissions import app_check_permission_level, check_permission_level # Importamos os dois tipos de verificadores

# --- Classes de Interface (Formulário e Botões) ---

class FormularioEvento(discord.ui.Modal, title='Agendar Novo Evento'):
    nome = discord.ui.TextInput(label='Nome do Evento', placeholder='Ex: Defesa de Território em MR')
    data_hora = discord.ui.TextInput(label='Data e Hora (AAAA-MM-DD HH:MM)', placeholder='Ex: 2025-10-18 21:00')
    tipo_evento = discord.ui.TextInput(label='Tipo de Conteúdo', placeholder='ZvZ, DG AVA, Gank, Reunião, Outro...')
    descricao = discord.ui.TextInput(label='Descrição e Requisitos', style=discord.TextStyle.paragraph, placeholder='IP Mínimo: 1400, Ponto de Encontro: HO de MR...', required=False)
    opcionais = discord.ui.TextInput(label='Opcionais (Recompensa, Vagas)', placeholder='Ex: recompensa=100 vagas=20', required=False)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()

class EventoView(discord.ui.View):
    def __init__(self, bot, evento_id):
        super().__init__(timeout=None)
        self.bot = bot
        self.evento_id = evento_id

    async def atualizar_embed(self, interaction: discord.Interaction):
        evento = await self.bot.db_manager.execute_query(
            "SELECT * FROM eventos WHERE id = $1",
            self.evento_id, fetch="one"
        )
        if not evento or evento['status'] in ['FINALIZADO', 'CANCELADO']:
            self.clear_items()
            # Adiciona uma nota final ao embed se o evento terminou
            embed = interaction.message.embeds[0]
            if evento:
                embed.color = discord.Color.dark_grey()
                embed.set_footer(text=f"ID do Evento: {self.evento_id} | Status: {evento['status']}")
            await interaction.message.edit(embed=embed, view=self)
            return

        embed = discord.Embed(
            title=f"[{evento['tipo_evento'].upper()}] {evento['nome']}",
            description=evento['descricao'] or "Sem detalhes adicionais.",
            color=discord.Color.blue() if evento['status'] == 'AGENDADO' else discord.Color.green()
        )
        embed.add_field(name="🗓️ Data e Hora", value=f"<t:{int(evento['data_evento'].timestamp())}:F>")
        if evento['recompensa'] > 0:
            embed.add_field(name="💰 Recompensa", value=f"`{evento['recompensa']}` 🪙 por participante")
        
        inscritos = evento['inscritos'] or []
        vagas_texto = f"{len(inscritos)}"
        if evento['max_participantes']:
            vagas_texto += f" / {evento['max_participantes']}"
        embed.add_field(name="👥 Inscritos", value=vagas_texto)

        lista_inscritos = "Ninguém se inscreveu ainda."
        if inscritos:
            mencoes = [f"<@{user_id}>" for user_id in inscritos]
            lista_inscritos = "\n".join(mencoes[:15]) # Limita a 15 para não quebrar o embed
            if len(mencoes) > 15:
                lista_inscritos += f"\n... e mais {len(mencoes) - 15}."

        embed.add_field(name="Lista de Presença", value=lista_inscritos, inline=False)
        embed.set_footer(text=f"ID do Evento: {self.evento_id} | Status: {evento['status']}")

        await interaction.message.edit(embed=embed, view=self)

    @discord.ui.button(label="Inscrever-se", style=discord.ButtonStyle.success, custom_id="inscrever_evento")
    async def inscrever(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        await self.bot.db_manager.execute_query(
            "UPDATE eventos SET inscritos = array_append(inscritos, $1) WHERE id = $2 AND NOT ($1 = ANY(inscritos))",
            user_id, self.evento_id
        )
        await self.atualizar_embed(interaction)
        await interaction.followup.send("Você foi inscrito no evento!", ephemeral=True, delete_after=5)

    @discord.ui.button(label="Remover Inscrição", style=discord.ButtonStyle.danger, custom_id="remover_inscricao_evento")
    async def remover_inscricao(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        await self.bot.db_manager.execute_query(
            "UPDATE eventos SET inscritos = array_remove(inscritos, $1) WHERE id = $2",
            user_id, self.evento_id
        )
        await self.atualizar_embed(interaction)
        await interaction.followup.send("Sua inscrição foi removida.", ephemeral=True, delete_after=5)


# --- Cog Principal de Eventos ---

class Eventos(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name='agendarevento',
        description='Abre um formulário para criar e agendar um novo evento da guilda.'
    )
    @app_check_permission_level(1)
    async def agendar_evento(self, interaction: discord.Interaction):
        formulario = FormularioEvento()
        await interaction.response.send_modal(formulario)
        await formulario.wait()
        try:
            data_evento = datetime.datetime.strptime(formulario.data_hora.value, '%Y-%m-%d %H:%M').astimezone()
        except ValueError:
            await interaction.followup.send("❌ Formato de data e hora inválido. Use AAAA-MM-DD HH:MM.", ephemeral=True)
            return
        recompensa, max_participantes = 0, None
        if formulario.opcionais.value:
            for parte in formulario.opcionais.value.split():
                if 'recompensa=' in parte: recompensa = int(parte.split('=')[1])
                if 'vagas=' in parte: max_participantes = int(parte.split('=')[1])
        resultado = await self.bot.db_manager.execute_query(
            """INSERT INTO eventos (nome, descricao, tipo_evento, data_evento, recompensa, max_participantes, criador_id)
               VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING id""",
            formulario.nome.value, formulario.descricao.value, formulario.tipo_evento.value,
            data_evento, recompensa, max_participantes, interaction.user.id, fetch="one"
        )
        evento_id = resultado['id']
        canal_eventos_id = await self.bot.db_manager.get_config_value('canal_eventos', '0')
        if canal_eventos_id == '0':
            await interaction.followup.send("✅ Evento agendado, mas o canal de eventos não está configurado! Use `!definircanal eventos #canal`.", ephemeral=True)
            return
        canal = self.bot.get_channel(int(canal_eventos_id))
        if canal:
            view = EventoView(self.bot, evento_id)
            embed = discord.Embed(
                title=f"[{formulario.tipo_evento.value.upper()}] {formulario.nome.value}",
                description=formulario.descricao.value or "Sem detalhes adicionais.",
                color=discord.Color.blue()
            )
            embed.add_field(name="🗓️ Data e Hora", value=f"<t:{int(data_evento.timestamp())}:F>")
            if recompensa > 0: embed.add_field(name="💰 Recompensa", value=f"`{recompensa}` 🪙 por participante")
            vagas_texto = "Ilimitadas"
            if max_participantes: vagas_texto = f"0 / {max_participantes}"
            embed.add_field(name="👥 Inscritos", value=vagas_texto)
            embed.set_footer(text=f"ID do Evento: {evento_id} | Organizado por: {interaction.user.display_name}")
            msg = await canal.send(embed=embed, view=view)
            await self.bot.db_manager.execute_query("UPDATE eventos SET message_id = $1 WHERE id = $2", msg.id, evento_id)
            await interaction.followup.send(f"✅ Evento agendado com sucesso em {canal.mention}!", ephemeral=True)
        else:
            await interaction.followup.send("❌ Canal de eventos configurado mas não encontrado.", ephemeral=True)

    # --- NOVOS COMANDOS DE GESTÃO E VISUALIZAÇÃO ---

    @commands.command(name='eventos', help='Mostra os próximos eventos agendados na guilda.')
    async def eventos(self, ctx):
        eventos_agendados = await self.bot.db_manager.execute_query(
            "SELECT id, nome, data_evento, tipo_evento FROM eventos WHERE status = 'AGENDADO' ORDER BY data_evento ASC LIMIT 5",
            fetch="all"
        )
        if not eventos_agendados:
            return await ctx.send("Não há eventos agendados para o futuro. Que tal organizar um?")
        embed = discord.Embed(title="🗓️ Próximos Eventos da Guilda", color=discord.Color.purple())
        for evento in eventos_agendados:
            embed.add_field(
                name=f"**{evento['nome']}** (ID: {evento['id']})",
                value=f"**Tipo:** {evento['tipo_evento']}\n**Quando:** <t:{int(evento['data_evento'].timestamp())}:R>",
                inline=False
            )
        await ctx.send(embed=embed)

    @commands.command(name='iniciarevento', help='Notifica todos os inscritos que o evento está a começar.', usage='!iniciarevento <ID>')
    @check_permission_level(1)
    async def iniciar_evento(self, ctx, evento_id: int):
        evento = await self.bot.db_manager.execute_query("SELECT nome, inscritos FROM eventos WHERE id = $1 AND status = 'AGENDADO'", evento_id, fetch="one")
        if not evento: return await ctx.send("❌ Evento não encontrado ou já não está agendado.")
        inscritos_ids = evento['inscritos'] or []
        if not inscritos_ids: return await ctx.send("⚠️ Nenhum membro inscrito para notificar.")
        
        notificados = 0
        for user_id in inscritos_ids:
            membro = ctx.guild.get_member(user_id)
            if membro:
                try:
                    await membro.send(f"📢 **LEMBRETE:** O evento **'{evento['nome']}'** para o qual te inscreveste está a começar agora!")
                    notificados += 1
                except discord.Forbidden:
                    pass # Não consegue enviar DM para este membro
        await self.bot.db_manager.execute_query("UPDATE eventos SET status = 'EM ANDAMENTO' WHERE id = $1", evento_id)
        await ctx.send(f"✅ Evento ID {evento_id} iniciado! **{notificados}** de **{len(inscritos_ids)}** membros inscritos foram notificados por DM.")

    @commands.command(name='cancelarevento', help='Cancela um evento agendado.', usage='!cancelarevento <ID>')
    @check_permission_level(1)
    async def cancelar_evento(self, ctx, evento_id: int):
        await self.bot.db_manager.execute_query("UPDATE eventos SET status = 'CANCELADO' WHERE id = $1", evento_id)
        await ctx.send(f"✅ Evento ID {evento_id} foi cancelado. O anúncio será desativado.")

    @commands.command(name='finalizarevento', help='Finaliza um evento e paga a recompensa aos presentes no canal de voz.', usage='!finalizarevento <ID> <#CanalDeVoz>')
    @check_permission_level(1)
    async def finalizar_evento(self, ctx, evento_id: int, canal_de_voz: discord.VoiceChannel):
        evento = await self.bot.db_manager.execute_query("SELECT nome, recompensa, inscritos FROM eventos WHERE id = $1 AND status = 'EM ANDAMENTO'", evento_id, fetch="one")
        if not evento: return await ctx.send("❌ Evento não encontrado ou não está 'EM ANDAMENTO'.")
        
        inscritos_ids = set(evento['inscritos'] or [])
        presentes_ids = {membro.id for membro in canal_de_voz.members}
        
        vencedores_ids = list(inscritos_ids.intersection(presentes_ids))
        
        if not vencedores_ids:
            await self.bot.db_manager.execute_query("UPDATE eventos SET status = 'FINALIZADO' WHERE id = $1", evento_id)
            return await ctx.send(f"Eventos ID {evento_id} finalizado. Nenhum dos inscritos estava no canal de voz `{canal_de_voz.name}`. Nenhuma recompensa foi paga.")

        if evento['recompensa'] == 0:
            await self.bot.db_manager.execute_query("UPDATE eventos SET status = 'FINALIZADO' WHERE id = $1", evento_id)
            return await ctx.send(f"✅ Evento '{evento['nome']}' finalizado. Este evento não tinha recompensa monetária.")

        economia_cog = self.bot.get_cog('Economia')
        sucessos, falhas = 0, 0
        for user_id in vencedores_ids:
            try:
                await economia_cog.transferir_do_tesouro(user_id, evento['recompensa'], f"Recompensa do evento '{evento['nome']}'")
                sucessos += 1
            except Exception:
                falhas += 1
        
        await self.bot.db_manager.execute_query("UPDATE eventos SET status = 'FINALIZADO' WHERE id = $1", evento_id)
        await ctx.send(f"🎉 Evento **'{evento['nome']}'** finalizado! **{sucessos}** participantes foram recompensados com `{evento['recompensa']}` 🪙 cada um. Falhas: {falhas}.")

    @commands.command(name='premiarmanual', help='Paga a recompensa de um evento a membros específicos.', usage='!premiarmanual <ID> @membro1 @membro2')
    @check_permission_level(1)
    async def premiar_manual(self, ctx, evento_id: int, membros: commands.Greedy[discord.Member]):
        if not membros: return await ctx.send("❌ Você precisa de mencionar pelo menos um membro.")
        evento = await self.bot.db_manager.execute_query("SELECT nome, recompensa FROM eventos WHERE id = $1", evento_id, fetch="one")
        if not evento: return await ctx.send("❌ Evento não encontrado.")
        if evento['recompensa'] == 0: return await ctx.send("⚠️ Este evento não tem uma recompensa configurada para pagar.")

        economia_cog = self.bot.get_cog('Economia')
        sucessos, falhas = 0, 0
        for membro in membros:
            try:
                await economia_cog.transferir_do_tesouro(membro.id, evento['recompensa'], f"Pagamento manual do evento '{evento['nome']}'")
                sucessos += 1
            except Exception:
                falhas += 1
        await ctx.send(f"✅ Pagamento manual para o evento **'{evento['nome']}'** concluído. **{sucessos}** membros pagos. Falhas: {falhas}.")


async def setup(bot):
    await bot.add_cog(Eventos(bot))
