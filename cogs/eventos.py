import discord
from discord.ext import commands
from discord import app_commands
import datetime
import asyncio
from utils.permissions import app_check_permission_level

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
            "SELECT nome, descricao, tipo_evento, data_evento, recompensa, max_participantes, inscritos, status FROM eventos WHERE id = $1",
            self.evento_id, fetch="one"
        )
        if not evento:
            self.clear_items()
            try:
                await interaction.message.edit(view=self)
            except Exception:
                pass
            return

        embed = discord.Embed(
            title=f"[{(evento['tipo_evento'] or '').upper()}] {evento['nome']}",
            description=evento['descricao'] or "Sem detalhes adicionais.",
            color=discord.Color.blue()
        )
        if evento['data_evento']:
            embed.add_field(name="🗓️ Data e Hora", value=f"<t:{int(evento['data_evento'].timestamp())}:F>")
        if evento.get('recompensa', 0) > 0:
            embed.add_field(name="💰 Recompensa", value=f"`{evento['recompensa']}` 🪙 por participante")
        
        inscritos = evento.get('inscritos') or []
        vagas_texto = f"{len(inscritos)}"
        if evento.get('max_participantes'):
            vagas_texto += f" / {evento['max_participantes']}"
        embed.add_field(name="👥 Inscritos", value=vagas_texto)

        lista_inscritos = "Ninguém se inscreveu ainda."
        if inscritos:
            mencoes = [f"<@{user_id}>" for user_id in inscritos]
            lista_inscritos = "\n".join(mencoes)
        
        embed.add_field(name="Lista de Presença", value=lista_inscritos, inline=False)
        embed.set_footer(text=f"ID do Evento: {self.evento_id} | Status: {evento.get('status','N/A')}")

        try:
            await interaction.message.edit(embed=embed, view=self)
        except Exception:
            pass

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
        except Exception:
            await interaction.followup.send("❌ Formato de data e hora inválido. Use AAAA-MM-DD HH:MM.", ephemeral=True)
            return

        recompensa, max_participantes = 0, None
        if formulario.opcionais.value:
            for parte in formulario.opcionais.value.split():
                if 'recompensa=' in parte:
                    try:
                        recompensa = int(parte.split('=')[1])
                    except Exception:
                        recompensa = 0
                if 'vagas=' in parte:
                    try:
                        max_participantes = int(parte.split('=')[1])
                    except Exception:
                        max_participantes = None

        resultado = await self.bot.db_manager.execute_query(
            """INSERT INTO eventos (nome, descricao, tipo_evento, data_evento, recompensa, max_participantes, criador_id)
               VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING id""",
            formulario.nome.value, formulario.descricao.value, formulario.tipo_evento.value,
            data_evento, recompensa, max_participantes, interaction.user.id,
            fetch="one"
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
            if recompensa > 0:
                embed.add_field(name="💰 Recompensa", value=f"`{recompensa}` 🪙 por participante")
            
            vagas_texto = "Ilimitadas"
            if max_participantes:
                vagas_texto = f"0 / {max_participantes}"
            embed.add_field(name="👥 Inscritos", value=vagas_texto)
            embed.set_footer(text=f"ID do Evento: {evento_id} | Organizado por: {interaction.user.display_name}")

            await canal.send(embed=embed, view=view)
            await interaction.followup.send(f"✅ Evento **{formulario.nome.value}** agendado com sucesso no canal {canal.mention}!", ephemeral=True)
        else:
            await interaction.followup.send("❌ Canal de eventos configurado mas não encontrado.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Eventos(bot))
