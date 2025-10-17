import discord
from discord.ext import commands, tasks
from discord import app_commands
import datetime
from typing import Optional
from utils.permissions import app_check_permission_level, check_permission_level

# --- A CLASSE DE FORMULÁRIO FOI REMOVIDA ---

class EventoView(discord.ui.View):
    def __init__(self, bot, evento_id):
        super().__init__(timeout=None)
        self.bot = bot
        self.evento_id = evento_id

    async def atualizar_embed(self, interaction: discord.Interaction):
        evento = await self.bot.db_manager.execute_query("SELECT * FROM eventos WHERE id = $1", self.evento_id, fetch="one")
        if not evento or evento['status'] in ['FINALIZADO', 'CANCELADO']:
            self.clear_items()
            embed = interaction.message.embeds[0]
            if evento:
                embed.color = discord.Color.dark_grey()
                embed.set_footer(text=f"ID do Evento: {self.evento_id} | Status: {evento['status']}")
            await interaction.message.edit(embed=embed, view=self)
            return

        embed = discord.Embed(title=f"[{evento['tipo_evento'].upper()}] {evento['nome']}", description=evento['descricao'] or "Sem detalhes.", color=discord.Color.blue())
        
        if evento['cargo_requerido_id']:
            embed.add_field(name="🎯 Exclusivo para", value=f"<@&{evento['cargo_requerido_id']}>", inline=False)
        if evento['canal_voz_id']:
            embed.add_field(name="🔊 Canal de Voz", value=f"<#{evento['canal_voz_id']}>", inline=False)
            
        embed.add_field(name="🗓️ Data e Hora", value=f"<t:{int(evento['data_evento'].timestamp())}:F>")
        if evento['recompensa'] > 0:
            embed.add_field(name="💰 Recompensa", value=f"`{evento['recompensa']}` 🪙")
        
        inscritos = evento['inscritos'] or []
        vagas_texto = f"{len(inscritos)}"
        if evento['max_participantes']:
            vagas_texto += f" / {evento['max_participantes']}"
        embed.add_field(name="👥 Inscritos", value=vagas_texto)
        
        lista_inscritos = "Ninguém se inscreveu ainda."
        if inscritos:
            mencoes = [f"<@{user_id}>" for user_id in inscritos]
            lista_inscritos = "\n".join(mencoes[:15])
            if len(mencoes) > 15:
                lista_inscritos += f"\n... e mais {len(mencoes) - 15}."
        embed.add_field(name="Lista de Presença", value=lista_inscritos, inline=False)
        embed.set_footer(text=f"ID do Evento: {self.evento_id} | Status: {evento['status']}")
        
        await interaction.message.edit(embed=embed, view=self)

    @discord.ui.button(label="Inscrever-se", style=discord.ButtonStyle.success, custom_id="inscrever_evento")
    async def inscrever(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        evento = await self.bot.db_manager.execute_query("SELECT cargo_requerido_id, inscritos FROM eventos WHERE id = $1", self.evento_id, fetch="one")
        
        if evento['cargo_requerido_id']:
            cargo_requerido = discord.utils.get(user.roles, id=evento['cargo_requerido_id'])
            if not cargo_requerido:
                await interaction.response.send_message(f"❌ Este evento é exclusivo para o cargo <@&{evento['cargo_requerido_id']}> e você não o possui.", ephemeral=True)
                return

        await self.bot.db_manager.execute_query("UPDATE eventos SET inscritos = array_append(inscritos, $1) WHERE id = $2 AND NOT ($1 = ANY(inscritos))", user.id, self.evento_id)
        await self.atualizar_embed(interaction)
        await interaction.followup.send("Você foi inscrito no evento!", ephemeral=True, delete_after=5)

    @discord.ui.button(label="Remover Inscrição", style=discord.ButtonStyle.danger, custom_id="remover_inscricao_evento")
    async def remover_inscricao(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        await self.bot.db_manager.execute_query("UPDATE eventos SET inscritos = array_remove(inscritos, $1) WHERE id = $2", user_id, self.evento_id)
        await self.atualizar_embed(interaction)
        await interaction.followup.send("Sua inscrição foi removida.", ephemeral=True, delete_after=5)

    @discord.ui.button(label="Criar Canal de Voz", style=discord.ButtonStyle.secondary, custom_id="criar_canal_voz_evento", emoji="🎙️")
    async def criar_canal_voz(self, interaction: discord.Interaction, button: discord.ui.Button):
        evento = await self.bot.db_manager.execute_query("SELECT criador_id, nome, canal_voz_id FROM eventos WHERE id = $1", self.evento_id, fetch="one")
        if interaction.user.id != evento['criador_id']:
            await interaction.response.send_message("Apenas o organizador do evento pode usar este botão.", ephemeral=True, delete_after=10)
            return
        if evento['canal_voz_id']:
            await interaction.response.send_message("O canal de voz para este evento já foi criado.", ephemeral=True, delete_after=10)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            guild = interaction.guild
            canal_eventos_id = await self.bot.db_manager.get_config_value('canal_eventos', '0')
            categoria = self.bot.get_channel(int(canal_eventos_id)).category if canal_eventos_id != '0' else None
            novo_canal = await guild.create_voice_channel(name=f"▶ {evento['nome']}", category=categoria)
            await self.bot.db_manager.execute_query("UPDATE eventos SET canal_voz_id = $1 WHERE id = $2", novo_canal.id, self.evento_id)
            button.disabled = True
            await self.atualizar_embed(interaction)
            await interaction.followup.send(f"Canal de voz {novo_canal.mention} criado com sucesso!", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Ocorreu um erro: {e}", ephemeral=True)

class Eventos(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name='agendarevento', description='Agenda um novo evento da guilda com todas as opções.')
    @app_commands.describe(
        nome='O nome do evento. Ex: Defesa de Território',
        data_hora='A data e hora do evento. Formato: AAAA-MM-DD HH:MM',
        tipo='O tipo de conteúdo. Ex: ZvZ, DG AVA, Gank, Reunião',
        descricao='[OPCIONAL] Detalhes do evento, como IP mínimo e ponto de encontro.',
        recompensa='[OPCIONAL] A recompensa em moedas para cada participante.',
        vagas='[OPCIONAL] O número máximo de vagas para o evento.',
        cargo_requerido='[OPCIONAL] Restringe o evento a membros com este cargo.'
    )
    @app_check_permission_level(1)
    async def agendar_evento(
        self, 
        interaction: discord.Interaction, 
        nome: str, 
        data_hora: str, 
        tipo: str,
        descricao: Optional[str] = None,
        recompensa: Optional[int] = 0,
        vagas: Optional[int] = None,
        cargo_requerido: Optional[discord.Role] = None
    ):
        await interaction.response.defer(ephemeral=True)
        try:
            data_evento = datetime.datetime.strptime(data_hora, '%Y-%m-%d %H:%M').astimezone()
        except ValueError:
            await interaction.followup.send("❌ Formato de data e hora inválido. Use `AAAA-MM-DD HH:MM`.", ephemeral=True)
            return

        cargo_id = cargo_requerido.id if cargo_requerido else None

        resultado = await self.bot.db_manager.execute_query(
            """INSERT INTO eventos (nome, descricao, tipo_evento, data_evento, recompensa, max_participantes, criador_id, cargo_requerido_id)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id""",
            nome, descricao, tipo, data_evento, recompensa, vagas, interaction.user.id, cargo_id, fetch="one"
        )
        evento_id = resultado['id']
        
        canal_eventos_id = await self.bot.db_manager.get_config_value('canal_eventos', '0')
        if canal_eventos_id == '0':
            await interaction.followup.send("✅ Evento agendado, mas o canal de eventos não está configurado!", ephemeral=True)
            return

        canal = self.bot.get_channel(int(canal_eventos_id))
        if canal:
            view = EventoView(self.bot, evento_id)
            embed = discord.Embed(title=f"[{tipo.upper()}] {nome}", description=descricao or "Sem detalhes.", color=discord.Color.blue())
            if cargo_requerido:
                embed.add_field(name="🎯 Exclusivo para", value=cargo_requerido.mention, inline=False)
            embed.add_field(name="🗓️ Data e Hora", value=f"<t:{int(data_evento.timestamp())}:F>")
            if recompensa > 0: embed.add_field(name="💰 Recompensa", value=f"`{recompensa}` 🪙")
            vagas_texto = "Ilimitadas"
            if vagas: vagas_texto = f"0 / {vagas}"
            embed.add_field(name="👥 Inscritos", value=vagas_texto)
            embed.set_footer(text=f"ID do Evento: {evento_id} | Organizado por: {interaction.user.display_name}")
            msg = await canal.send(embed=embed, view=view)
            await self.bot.db_manager.execute_query("UPDATE eventos SET message_id = $1 WHERE id = $2", msg.id, evento_id)
            await interaction.followup.send(f"✅ Evento **{nome}** agendado com sucesso em {canal.mention}!", ephemeral=True)
        else:
            await interaction.followup.send("❌ Canal de eventos configurado mas não encontrado.", ephemeral=True)

    # (Todos os outros comandos de eventos, como !eventos, !finalizarevento, etc. permanecem aqui inalterados)

async def setup(bot):
    await bot.add_cog(Eventos(bot))
