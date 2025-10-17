import discord
from discord.ext import commands, tasks
from discord import app_commands
import datetime
from typing import Optional
from utils.permissions import app_check_permission_level, check_permission_level

# --- Classes de Interface (Views, Modals, Selects) para o novo sistema guiado ---

class DetalhesEventoModal(discord.ui.Modal, title='Detalhes Essenciais do Evento'):
    nome = discord.ui.TextInput(label='Nome do Evento', placeholder='Ex: Defesa de Território em MR')
    data_hora = discord.ui.TextInput(label='Data e Hora (AAAA-MM-DD HH:MM)', placeholder='Ex: 2025-10-18 21:00')
    tipo_evento = discord.ui.TextInput(label='Tipo de Conteúdo', placeholder='ZvZ, DG AVA, Gank, Reunião, Outro...')
    descricao = discord.ui.TextInput(label='Descrição e Requisitos', style=discord.TextStyle.paragraph, placeholder='IP Mínimo: 1400...', required=False)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()

class RecompensaModal(discord.ui.Modal, title='Definir Recompensa'):
    recompensa = discord.ui.TextInput(label='Recompensa por participante', placeholder='Digite 0 para remover. Ex: 100')
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()

class VagasModal(discord.ui.Modal, title='Definir Limite de Vagas'):
    vagas = discord.ui.TextInput(label='Número máximo de vagas', placeholder='Deixe em branco para remover o limite.')
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()

class EventoView(discord.ui.View):
    def __init__(self, bot, evento_id):
        super().__init__(timeout=None)
        self.bot = bot
        self.evento_id = evento_id

    async def atualizar_embed(self, interaction: discord.Interaction):
        evento = await self.bot.db_manager.execute_query(
            "SELECT * FROM eventos WHERE id = $1", self.evento_id, fetch="one"
        )
        # Caso não exista ou esteja finalizado/cancelado
        if not evento or (evento.get('status') and evento.get('status') in ['FINALIZADO', 'CANCELADO']):
            self.clear_items()
            embed = interaction.message.embeds[0] if interaction.message and interaction.message.embeds else discord.Embed(description="Evento não encontrado.", color=discord.Color.dark_grey())
            if evento:
                embed.color = discord.Color.dark_grey()
                embed.set_footer(text=f"ID do Evento: {self.evento_id} | Status: {evento.get('status')}")
            await interaction.message.edit(embed=embed, view=self)
            return

        embed = discord.Embed(
            title=f"[{(evento.get('tipo_evento') or '').upper()}] {evento.get('nome')}",
            description=evento.get('descricao') or "Sem detalhes.",
            color=discord.Color.blue()
        )

        if evento.get('cargo_requerido_id'):
            embed.add_field(name="🎯 Exclusivo para", value=f"<@&{evento['cargo_requerido_id']}>", inline=False)
        if evento.get('canal_voz_id'):
            embed.add_field(name="🔊 Canal de Voz", value=f"<#{evento['canal_voz_id']}>", inline=False)

        if evento.get('data_evento'):
            try:
                embed.add_field(name="🗓️ Data e Hora", value=f"<t:{int(evento['data_evento'].timestamp())}:F>")
            except Exception:
                pass

        if evento.get('recompensa', 0) > 0:
            embed.add_field(name="💰 Recompensa", value=f"`{evento['recompensa']}` 🪙")

        inscritos = evento.get('inscritos') or []
        vagas_texto = f"{len(inscritos)}"
        if evento.get('max_participantes'):
            vagas_texto += f" / {evento['max_participantes']}"
        embed.add_field(name="👥 Inscritos", value=vagas_texto)

        lista_inscritos = "Ninguém se inscreveu ainda."
        if inscritos:
            mencoes = [f"<@{user_id}>" for user_id in inscritos]
            lista_inscritos = "\n".join(mencoes[:15])
            if len(mencoes) > 15:
                lista_inscritos += f"\n... e mais {len(mencoes) - 15}."
        embed.add_field(name="Lista de Presença", value=lista_inscritos, inline=False)

        embed.set_footer(text=f"ID do Evento: {self.evento_id} | Status: {evento.get('status')}")
        await interaction.message.edit(embed=embed, view=self)

    @discord.ui.button(label="Inscrever-se", style=discord.ButtonStyle.success, custom_id="inscrever_evento")
    async def inscrever(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        evento = await self.bot.db_manager.execute_query(
            "SELECT cargo_requerido_id, inscritos, max_participantes FROM eventos WHERE id = $1", self.evento_id, fetch="one"
        )

        if not evento:
            await interaction.response.send_message("Evento não encontrado.", ephemeral=True)
            return

        # Verifica cargo requerido
        if evento.get('cargo_requerido_id'):
            try:
                cargo_req_id = int(evento['cargo_requerido_id'])
            except Exception:
                cargo_req_id = None
            cargo_requerido = discord.utils.get(user.roles, id=cargo_req_id) if cargo_req_id else None
            if not cargo_requerido:
                await interaction.response.send_message(f"❌ Este evento é exclusivo para o cargo <@&{evento['cargo_requerido_id']}> e você não o possui.", ephemeral=True)
                return

        # Verifica limite de vagas
        inscritos = evento.get('inscritos') or []
        max_part = evento.get('max_participantes')
        if max_part and len(inscritos) >= max_part:
            await interaction.response.send_message("❌ O evento já atingiu o número máximo de participantes.", ephemeral=True)
            return

        await self.bot.db_manager.execute_query(
            "UPDATE eventos SET inscritos = array_append(inscritos, $1) WHERE id = $2 AND NOT ($1 = ANY(inscritos))",
            user.id, self.evento_id
        )
        await self.atualizar_embed(interaction)
        # resposta ephemeral
        if not interaction.response.is_done():
            await interaction.response.send_message("Você foi inscrito no evento!", ephemeral=True, delete_after=5)
        else:
            await interaction.followup.send("Você foi inscrito no evento!", ephemeral=True, delete_after=5)

    @discord.ui.button(label="Remover Inscrição", style=discord.ButtonStyle.danger, custom_id="remover_inscricao_evento")
    async def remover_inscricao(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        await self.bot.db_manager.execute_query(
            "UPDATE eventos SET inscritos = array_remove(inscritos, $1) WHERE id = $2",
            user_id, self.evento_id
        )
        await self.atualizar_embed(interaction)
        if not interaction.response.is_done():
            await interaction.response.send_message("Sua inscrição foi removida.", ephemeral=True, delete_after=5)
        else:
            await interaction.followup.send("Sua inscrição foi removida.", ephemeral=True, delete_after=5)

    @discord.ui.button(label="Criar Canal de Voz", style=discord.ButtonStyle.secondary, custom_id="criar_canal_voz_evento", emoji="🎙️")
    async def criar_canal_voz(self, interaction: discord.Interaction, button: discord.ui.Button):
        evento = await self.bot.db_manager.execute_query(
            "SELECT criador_id, nome, canal_voz_id FROM eventos WHERE id = $1", self.evento_id, fetch="one"
        )
        if not evento:
            await interaction.response.send_message("Evento não encontrado.", ephemeral=True)
            return

        # Apenas o criador pode criar o canal
        if interaction.user.id != evento.get('criador_id'):
            await interaction.response.send_message("Apenas o organizador do evento pode usar este botão.", ephemeral=True, delete_after=10)
            return

        if evento.get('canal_voz_id'):
            await interaction.response.send_message("O canal de voz para este evento já foi criado.", ephemeral=True, delete_after=10)
            return

        await interaction.response.defer(ephemeral=True)
        try:
            guild = interaction.guild
            canal_eventos_id = await self.bot.db_manager.get_config_value('canal_eventos', '0')
            categoria = None
            try:
                if canal_eventos_id and canal_eventos_id != '0' and str(canal_eventos_id).isdigit():
                    texto = self.bot.get_channel(int(canal_eventos_id))
                    categoria = texto.category if texto else None
            except Exception:
                categoria = None

            novo_canal = await guild.create_voice_channel(name=f"▶ {evento.get('nome')}", category=categoria)

            await self.bot.db_manager.execute_query("UPDATE eventos SET canal_voz_id = $1 WHERE id = $2", novo_canal.id, self.evento_id)

            # Desabilita o botão localmente e atualiza a mensagem
            button.disabled = True
            await self.atualizar_embed(interaction)
            try:
                await interaction.followup.send(f"Canal de voz {novo_canal.mention} criado com sucesso!", ephemeral=True)
            except Exception:
                pass

        except discord.Forbidden:
            await interaction.followup.send("❌ Erro de Permissão! O bot não tem a permissão 'Gerir Canais'.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Ocorreu um erro inesperado: {e}", ephemeral=True)

class CriacaoEventoView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=1800) # O painel expira após 30 minutos
        self.bot = bot
        self.evento_data = {} # Dicionário para guardar os dados do evento em criação

    async def atualizar_preview(self, interaction: discord.Interaction):
        embed = discord.Embed(title="Pré-visualização do Evento", color=discord.Color.yellow())
        
        if not self.evento_data.get('nome') or not self.evento_data.get('data_evento'):
            embed.description = "Preencha os detalhes essenciais para continuar."
            # tenta encontrar o botão de publicar (último botão por padrão)
            if self.children:
                self.children[-1].disabled = True
        else:
            embed.title = f"[{self.evento_data.get('tipo_evento', 'INDEFINIDO').upper()}] {self.evento_data['nome']}"
            embed.description = self.evento_data.get('descricao', 'Sem detalhes.')
            try:
                embed.add_field(name="🗓️ Data e Hora", value=f"<t:{int(self.evento_data['data_evento'].timestamp())}:F>")
            except Exception:
                pass
            if self.children:
                self.children[-1].disabled = False

        if self.evento_data.get('cargo_requerido'):
            embed.add_field(name="🎯 Exclusivo para", value=self.evento_data['cargo_requerido'].mention)
        if self.evento_data.get('recompensa') is not None:
            embed.add_field(name="💰 Recompensa", value=f"`{self.evento_data['recompensa']}` 🪙")
        if self.evento_data.get('vagas') is not None:
            embed.add_field(name="👥 Vagas", value=f"{self.evento_data['vagas']}")
            
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="📝 Definir Detalhes", style=discord.ButtonStyle.primary, row=0)
    async def definir_detalhes(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = DetalhesEventoModal()
        await interaction.response.send_modal(modal)
        await modal.wait()
        
        try:
            self.evento_data['data_evento'] = datetime.datetime.strptime(modal.data_hora.value, '%Y-%m-%d %H:%M').astimezone()
            self.evento_data['nome'] = modal.nome.value
            self.evento_data['tipo_evento'] = modal.tipo_evento.value if hasattr(modal, 'tipo_evento') else getattr(modal, 'tipo', None)
            self.evento_data['descricao'] = modal.descricao.value
            await self.atualizar_preview(interaction)
        except ValueError:
            await interaction.followup.send("❌ Formato de data inválido. Use AAAA-MM-DD HH:MM.", ephemeral=True)

    @discord.ui.select(cls=discord.ui.RoleSelect, placeholder="🎯 Restringir por Cargo (Opcional)", row=1)
    async def selecionar_cargo(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        # RoleSelect retorna uma lista de roles selecionadas
        if select.values:
            self.evento_data['cargo_requerido'] = select.values[0]
        else:
            self.evento_data.pop('cargo_requerido', None)
        await self.atualizar_preview(interaction)

    @discord.ui.button(label="💰 Recompensa", style=discord.ButtonStyle.secondary, row=2)
    async def definir_recompensa(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = RecompensaModal()
        await interaction.response.send_modal(modal)
        await modal.wait()
        try:
            valor = int(modal.recompensa.value)
            self.evento_data['recompensa'] = valor if valor > 0 else None
            await self.atualizar_preview(interaction)
        except Exception:
            await interaction.followup.send("❌ O valor da recompensa deve ser um número.", ephemeral=True)
            
    @discord.ui.button(label="👥 Vagas", style=discord.ButtonStyle.secondary, row=2)
    async def definir_vagas(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = VagasModal()
        await interaction.response.send_modal(modal)
        await modal.wait()
        try:
            valor = int(modal.vagas.value)
            self.evento_data['vagas'] = valor if valor > 0 else None
            await self.atualizar_preview(interaction)
        except Exception:
            self.evento_data['vagas'] = None
            await self.atualizar_preview(interaction)

    @discord.ui.button(label="🚀 Publicar Evento", style=discord.ButtonStyle.success, row=3, disabled=True)
    async def publicar_evento(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Lógica final para inserir na DB e publicar
        cargo_id = self.evento_data.get('cargo_requerido').id if self.evento_data.get('cargo_requerido') else None
        
        resultado = await self.bot.db_manager.execute_query(
            """INSERT INTO eventos (nome, descricao, tipo_evento, data_evento, recompensa, max_participantes, criador_id, cargo_requerido_id)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id""",
            self.evento_data['nome'], self.evento_data.get('descricao'), self.evento_data['tipo_evento'],
            self.evento_data['data_evento'], self.evento_data.get('recompensa', 0), self.evento_data.get('vagas'),
            interaction.user.id, cargo_id, fetch="one"
        )
        evento_id = resultado['id']

        canal_eventos_id = await self.bot.db_manager.get_config_value('canal_eventos', '0')
        canal = self.bot.get_channel(int(canal_eventos_id)) if canal_eventos_id and canal_eventos_id != '0' else None

        # Cria embed final diretamente (evita depender da mensagem ephemeral)
        final_embed = discord.Embed(
            title=f"[{self.evento_data.get('tipo_evento','INDEFINIDO').upper()}] {self.evento_data['nome']}",
            description=self.evento_data.get('descricao', 'Sem detalhes.'),
            color=discord.Color.blue()
        )
        try:
            final_embed.add_field(name="🗓️ Data e Hora", value=f"<t:{int(self.evento_data['data_evento'].timestamp())}:F>")
        except Exception:
            pass
        if self.evento_data.get('recompensa'):
            final_embed.add_field(name="💰 Recompensa", value=f"`{self.evento_data['recompensa']}` 🪙")
        vagas_texto = "Ilimitadas" if not self.evento_data.get('vagas') else f"0 / {self.evento_data['vagas']}"
        final_embed.add_field(name="👥 Inscritos", value=vagas_texto)
        if self.evento_data.get('cargo_requerido'):
            final_embed.add_field(name="🎯 Exclusivo para", value=self.evento_data['cargo_requerido'].mention, inline=False)
        final_embed.set_footer(text=f"ID do Evento: {evento_id} | Organizado por: {interaction.user.display_name}")

        if canal:
            public_view = EventoView(self.bot, evento_id)
            msg = await canal.send(embed=final_embed, view=public_view)
            await self.bot.db_manager.execute_query("UPDATE eventos SET message_id = $1 WHERE id = $2", msg.id, evento_id)
            await interaction.edit_original_response(content=f"✅ Evento publicado com sucesso em {canal.mention}!", embed=None, view=None)
        else:
            await interaction.edit_original_response(content="❌ O canal de eventos não está configurado. Evento salvo, mas não publicado.", embed=None, view=None)
        
        self.stop()

class Eventos(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name='agendarevento', description='Inicia o assistente para criar um novo evento.')
    @app_check_permission_level(1)
    async def agendar_evento(self, interaction: discord.Interaction):
        view = CriacaoEventoView(self.bot)
        embed = discord.Embed(title="Assistente de Criação de Eventos", description="Use os botões abaixo para configurar o seu evento. Quando terminar, clique em 'Publicar'.", color=discord.Color.yellow())
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    # (Os outros comandos como !eventos, !finalizarevento, etc. permanecem aqui inalterados)

async def setup(bot):
    await bot.add_cog(Eventos(bot))
