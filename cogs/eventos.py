import discord
from discord.ext import commands
import datetime
from typing import Optional
from utils.permissions import check_permission_level

# --- CLASSES DE INTERFACE (MODALS, VIEWS, SELECTS) ---
# (As classes DetalhesEventoModal, RecompensaModal, VagasModal, EventoView e CriacaoEventoView permanecem exatamente como na versão anterior)

class DetalhesEventoModal(discord.ui.Modal, title='Detalhes Essenciais do Evento'):
    def __init__(self, view):
        super().__init__()
        self.view = view
    nome = discord.ui.TextInput(label='Nome do Evento', placeholder='Ex: Defesa de Território em MR')
    data_hora = discord.ui.TextInput(label='Data e Hora (AAAA-MM-DD HH:MM)', placeholder='Ex: 2025-10-18 21:00')
    tipo_evento = discord.ui.TextInput(label='Tipo de Conteúdo', placeholder='ZvZ, DG AVA, Gank, Reunião...')
    descricao = discord.ui.TextInput(label='Descrição e Requisitos', style=discord.TextStyle.paragraph, placeholder='IP Mínimo: 1400...', required=False)
    async def on_submit(self, interaction: discord.Interaction):
        try:
            self.view.evento_data['data_evento'] = datetime.datetime.strptime(self.data_hora.value, '%Y-%m-%d %H:%M').astimezone()
            self.view.evento_data['nome'] = self.nome.value
            self.view.evento_data['tipo_evento'] = self.tipo_evento.value
            self.view.evento_data['descricao'] = self.descricao.value
            await self.view.atualizar_preview(interaction)
        except (ValueError, TypeError):
            await interaction.response.send_message("❌ Formato de data inválido. Use `AAAA-MM-DD HH:MM`.", ephemeral=True, delete_after=10)

class RecompensaModal(discord.ui.Modal, title='Definir Recompensa'):
    def __init__(self, view):
        super().__init__()
        self.view = view
    recompensa = discord.ui.TextInput(label='Recompensa por participante (apenas números)', placeholder='Ex: 10000', required=False)
    async def on_submit(self, interaction: discord.Interaction):
        try:
            self.view.evento_data['recompensa'] = int(self.recompensa.value) if self.recompensa.value else 0
            await self.view.atualizar_preview(interaction)
        except ValueError:
            await interaction.response.send_message("❌ A recompensa deve ser um número.", ephemeral=True, delete_after=10)

class VagasModal(discord.ui.Modal, title='Definir Limite de Vagas'):
    def __init__(self, view):
        super().__init__()
        self.view = view
    vagas = discord.ui.TextInput(label='Número máximo de vagas (apenas números)', placeholder='Deixe em branco para ilimitado.', required=False)
    async def on_submit(self, interaction: discord.Interaction):
        try:
            self.view.evento_data['max_participantes'] = int(self.vagas.value) if self.vagas.value else None
            await self.view.atualizar_preview(interaction)
        except ValueError:
            await interaction.response.send_message("❌ O número de vagas deve ser um número.", ephemeral=True, delete_after=10)

class EventoView(discord.ui.View):
    def __init__(self, bot, evento_id: int):
        super().__init__(timeout=None)
        self.bot = bot
        self.evento_id = evento_id

    async def atualizar_mensagem(self, interaction: discord.Interaction):
        evento = await self.bot.db_manager.execute_query(
            "SELECT inscritos, max_participantes FROM eventos WHERE id = $1", self.evento_id, fetch="one"
        )
        if not evento:
            for item in self.children:
                item.disabled = True
            try:
                if interaction.message:
                    await interaction.message.edit(view=self)
            except Exception:
                pass
            return

        inscritos = evento.get('inscritos') or []
        max_participantes = evento.get('max_participantes')

        embed = None
        if interaction.message and interaction.message.embeds:
            embed = interaction.message.embeds[0]
        else:
            embed = discord.Embed(title="Evento", description="Detalhes não disponíveis.", color=discord.Color.blue())

        # Atualiza o campo de vagas (se ele existir)
        for i, field in enumerate(embed.fields):
            if field.name.startswith("👥"):
                try:
                    embed.set_field_at(
                        i, name=field.name,
                        value=f"**{len(inscritos)} / {max_participantes or '∞'}**",
                        inline=True
                    )
                except Exception:
                    pass
                break

        try:
            if interaction.response.is_done():
                await interaction.followup.edit_message(message_id=interaction.message.id, embed=embed, view=self)
            else:
                await interaction.response.edit_message(embed=embed, view=self)
        except Exception:
            try:
                if interaction.message:
                    await interaction.message.edit(embed=embed, view=self)
            except Exception:
                pass

    @discord.ui.button(label="Inscrever-se", style=discord.ButtonStyle.success, custom_id="inscrever_evento")
    async def inscrever_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True)

        evento = await self.bot.db_manager.execute_query(
            "SELECT inscritos, max_participantes, cargo_requerido_id FROM eventos WHERE id = $1",
            self.evento_id, fetch="one"
        )

        if not evento:
            return await interaction.followup.send("❌ Este evento já não existe.", ephemeral=True)

        inscritos = evento.get('inscritos') or []
        max_participantes = evento.get('max_participantes')
        cargo_requerido_id = evento.get('cargo_requerido_id')

        if interaction.user.id in inscritos:
            return await interaction.followup.send("🤔 Você já está inscrito neste evento.", ephemeral=True)

        if max_participantes is not None and len(inscritos) >= max_participantes:
            return await interaction.followup.send("❌ O evento está lotado! Mais sorte para a próxima.", ephemeral=True)

        if cargo_requerido_id:
            cargo_requerido = interaction.guild.get_role(int(cargo_requerido_id))
            if not cargo_requerido or cargo_requerido not in interaction.user.roles:
                return await interaction.followup.send(f"❌ Apenas membros com o cargo {cargo_requerido.mention} se podem inscrever.", ephemeral=True)

        await self.bot.db_manager.execute_query(
            "UPDATE eventos SET inscritos = array_append(inscritos, $1) WHERE id = $2",
            interaction.user.id, self.evento_id
        )

        await self.atualizar_mensagem(interaction)
        await interaction.followup.send("✅ Inscrição confirmada! Vemo-nos lá.", ephemeral=True)

    @discord.ui.button(label="Desinscrever-se", style=discord.ButtonStyle.danger, custom_id="desinscrever_evento")
    async def desinscrever_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True)

        resultado = await self.bot.db_manager.execute_query(
            "UPDATE eventos SET inscritos = array_remove(inscritos, $1) WHERE id = $2 AND $1 = ANY(inscritos) RETURNING id",
            interaction.user.id, self.evento_id, fetch="one"
        )

        if resultado:
            await self.atualizar_mensagem(interaction)
            await interaction.followup.send("✅ Inscrição removida. Que pena!", ephemeral=True)
        else:
            await interaction.followup.send("🤔 Você não estava inscrito neste evento.", ephemeral=True)

class CriacaoEventoView(discord.ui.View):
    def __init__(self, bot, author):
        super().__init__(timeout=1800)
        self.bot = bot
        self.author = author
        self.evento_data = {'recompensa': 0}
        # Garante que o objeto Role seja armazenado para permitir .mention
        self.cargo_requerido_obj = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("Apenas o criador do evento pode usar estes botões.", ephemeral=True, delete_after=10)
            return False
        return True

    async def atualizar_preview(self, interaction: discord.Interaction):
        embed = discord.Embed(title="Pré-visualização do Evento", color=discord.Color.yellow())
        # Encontra o botão de publicação pelo custom_id
        publish_button = discord.utils.get(self.children, custom_id="publicar_evento")

        if self.evento_data.get('nome') and self.evento_data.get('data_evento'):
            embed.title = f"[{self.evento_data.get('tipo_evento', 'INDEFINIDO').upper()}] {self.evento_data['nome']}"
            embed.description = self.evento_data.get('descricao', 'Sem detalhes.')
            try:
                embed.add_field(name="🗓️ Data e Hora", value=f"<t:{int(self.evento_data['data_evento'].timestamp())}:F>", inline=False)
            except Exception:
                pass
            publish_button.disabled = False
        else:
            embed.description = "Preencha os detalhes essenciais (`Nome` e `Data/Hora`) para poder publicar."
            publish_button.disabled = True

        if self.cargo_requerido_obj:
            embed.add_field(name="🎯 Exclusivo para", value=self.cargo_requerido_obj.mention, inline=True)
        
        if self.evento_data.get('recompensa', 0) > 0:
            embed.add_field(name="💰 Recompensa", value=f"`{self.evento_data['recompensa']}` 🪙 por pessoa", inline=True)
        
        if self.evento_data.get('max_participantes'):
            embed.add_field(name="👥 Vagas", value=f"**0 / {self.evento_data['max_participantes']}**", inline=True)

        embed.set_footer(text=f"Organizado por: {self.author.display_name}")
        
        # A resposta à interação é sempre editar a mensagem original
        try:
            if interaction.response.is_done():
                await interaction.followup.edit_message(message_id=interaction.message.id, embed=embed, view=self)
            else:
                await interaction.response.edit_message(embed=embed, view=self)
        except Exception:
            try:
                if interaction.message:
                    await interaction.message.edit(embed=embed, view=self)
            except Exception:
                pass


    @discord.ui.button(label="📝 Detalhes", style=discord.ButtonStyle.primary, row=0)
    async def definir_detalhes(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DetalhesEventoModal(self))

    @discord.ui.select(cls=discord.ui.RoleSelect, placeholder="🎯 Restringir por Cargo (Opcional)", row=1, max_values=1)
    async def selecionar_cargo(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        # RoleSelect devolve objetos Role; armazenamos o objeto para permitir .mention
        self.cargo_requerido_obj = select.values[0] if select.values else None
        # armazena opcionalmente o ID também no evento_data
        self.evento_data['cargo_requerido_id'] = self.cargo_requerido_obj.id if self.cargo_requerido_obj else None
        await self.atualizar_preview(interaction)

    @discord.ui.button(label="💰 Recompensa", style=discord.ButtonStyle.secondary, row=2)
    async def definir_recompensa(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RecompensaModal(self))

    @discord.ui.button(label="👥 Vagas", style=discord.ButtonStyle.secondary, row=2)
    async def definir_vagas(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(VagasModal(self))

    @discord.ui.button(label="🚀 Publicar", style=discord.ButtonStyle.success, row=3, custom_id="publicar_evento", disabled=True)
    async def publicar_evento(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        cargo_id = self.evento_data.get('cargo_requerido_id')

        try:
            resultado = await self.bot.db_manager.execute_query(
                """INSERT INTO eventos (nome, descricao, tipo_evento, data_evento, recompensa, max_participantes, criador_id, cargo_requerido_id)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id""",
                self.evento_data['nome'], self.evento_data.get('descricao'), self.evento_data.get('tipo_evento'),
                self.evento_data['data_evento'], self.evento_data.get('recompensa', 0), self.evento_data.get('max_participantes'),
                interaction.user.id, cargo_id, fetch="one"
            )
        except Exception as e:
            try:
                await interaction.followup.send(f"❌ Falha ao salvar o evento: {e}", ephemeral=True)
            except Exception:
                pass
            return

        evento_id = resultado['id']

        canal_eventos_id = await self.bot.db_manager.get_config_value('canal_eventos', '0')
        canal = None
        if canal_eventos_id and canal_eventos_id != '0' and str(canal_eventos_id).isdigit():
            canal = self.bot.get_channel(int(canal_eventos_id))

        final_embed = discord.Embed(
            title=f"[{self.evento_data.get('tipo_evento','INDEFINIDO').upper()}] {self.evento_data['nome']}",
            description=self.evento_data.get('descricao', 'Sem detalhes.'),
            color=discord.Color.blue()
        )
        try:
            final_embed.add_field(name="🗓️ Data e Hora", value=f"<t:{int(self.evento_data['data_evento'].timestamp())}:F>", inline=False)
        except Exception:
            pass
        if self.evento_data.get('recompensa', 0) > 0:
            final_embed.add_field(name="💰 Recompensa", value=f"`{self.evento_data['recompensa']}` 🪙 por pessoa", inline=False)
        vagas_texto = "Ilimitadas" if not self.evento_data.get('max_participantes') else f"0 / {self.evento_data['max_participantes']}"
        final_embed.add_field(name="👥 Inscritos", value=vagas_texto, inline=False)
        if self.cargo_requerido_obj:
            final_embed.add_field(name="🎯 Exclusivo para", value=self.cargo_requerido_obj.mention, inline=False)
        final_embed.set_footer(text=f"ID do Evento: {evento_id} | Organizado por: {interaction.user.display_name}")

        if canal:
            try:
                public_view = EventoView(self.bot, evento_id)
                msg = await canal.send(embed=final_embed, view=public_view)
                await self.bot.db_manager.execute_query("UPDATE eventos SET message_id = $1 WHERE id = $2", msg.id, evento_id)
                try:
                    await interaction.edit_original_response(content=f"✅ Evento publicado com sucesso em {canal.mention}!", embed=None, view=None)
                except Exception:
                    try:
                        await interaction.followup.send(f"✅ Evento publicado em {canal.mention}!", ephemeral=True)
                    except Exception:
                        pass
            except Exception as e:
                try:
                    await interaction.followup.send(f"❌ Falha ao publicar no canal de eventos: {e}", ephemeral=True)
                except Exception:
                    pass
        else:
            try:
                await interaction.followup.send("❌ O canal de eventos não está configurado! Evento salvo apenas no banco.", ephemeral=True)
            except Exception:
                pass

        self.stop()

    @discord.ui.button(label="✖️ Cancelar", style=discord.ButtonStyle.danger, row=3)
    async def cancelar(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.edit_message(content="Criação de evento cancelada.", embed=None, view=None)
        except Exception:
            try:
                await interaction.edit_original_response(content="Criação de evento cancelada.", embed=None, view=None)
            except Exception:
                pass
        self.stop()


class Eventos(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        """Regista a view persistente quando o bot está pronto."""
        # Passa um evento_id=0 simbólico, pois ele será substituído pelo ID real no custom_id
        try:
            self.bot.add_view(EventoView(self.bot, evento_id=0))
        except Exception:
            pass


    @commands.command(name='agendarevento', help='Inicia o assistente para criar um novo evento.')
    @check_permission_level(1)
    async def agendarevento(self, ctx: commands.Context):
        # --- ALTERAÇÃO PRINCIPAL AQUI ---
        canal_planejamento_id_str = await self.bot.db_manager.get_config_value('canal_planejamento', '0')
        
        # Verifica se o comando está a ser usado no canal correto
        if str(ctx.channel.id) != canal_planejamento_id_str:
            canal_planejamento = None
            try:
                if canal_planejamento_id_str and canal_planejamento_id_str != '0' and canal_planejamento_id_str.isdigit():
                    canal_planejamento = self.bot.get_channel(int(canal_planejamento_id_str))
            except Exception:
                canal_planejamento = None

            if canal_planejamento:
                await ctx.send(f"❌ Este comando só pode ser usado no canal {canal_planejamento.mention}.", delete_after=15)
            else:
                await ctx.send("❌ O canal de planeamento de eventos ainda não foi configurado pela administração.", delete_after=15)
            return

        view = CriacaoEventoView(self.bot, ctx.author)
        embed = discord.Embed(title="Assistente de Criação de Eventos", description="Use os botões abaixo para configurar o seu evento. A pré-visualização será atualizada em tempo real.", color=discord.Color.dark_grey())
        embed.set_footer(text="Preencha os detalhes essenciais para poder publicar.")
        
        try:
            await ctx.message.delete()
        except (discord.Forbidden, discord.NotFound):
            pass

        # Envia a mensagem no canal, sem o 'ephemeral=True'
        await ctx.send(embed=embed, view=view)

async def setup(bot):
    await bot.add_cog(Eventos(bot))
