import discord
from discord.ext import commands, tasks
import datetime
from typing import Optional
from utils.permissions import check_permission_level

# --- CLASSES DE INTERFACE (MODALS, VIEWS, SELECTS) PARA O SISTEMA GUIADO ---

class DetalhesEventoModal(discord.ui.Modal, title='Detalhes Essenciais do Evento'):
    def __init__(self, view):
        super().__init__()
        self.view = view

    nome = discord.ui.TextInput(label='Nome do Evento', placeholder='Ex: Defesa de Território em MR')
    data_hora = discord.ui.TextInput(label='Data e Hora (AAAA-MM-DD HH:MM)', placeholder='Ex: 2025-10-18 21:00')
    tipo_evento = discord.ui.TextInput(label='Tipo de Conteúdo', placeholder='ZvZ, DG AVA, Gank, Reunião, Outro...')
    descricao = discord.ui.TextInput(label='Descrição e Requisitos', style=discord.TextStyle.paragraph, placeholder='IP Mínimo: 1400...', required=False)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            self.view.evento_data['data_evento'] = datetime.datetime.strptime(self.data_hora.value, '%Y-%m-%d %H:%M').astimezone()
            self.view.evento_data['nome'] = self.nome.value
            self.view.evento_data['tipo_evento'] = self.tipo_evento.value
            self.view.evento_data['descricao'] = self.descricao.value
            await self.view.atualizar_preview(interaction)
        except (ValueError, TypeError):
            await interaction.response.send_message("❌ Formato de data inválido. Use `AAAA-MM-DD HH:MM`.", ephemeral=True)

class RecompensaModal(discord.ui.Modal, title='Definir Recompensa'):
    def __init__(self, view):
        super().__init__()
        self.view = view

    recompensa = discord.ui.TextInput(label='Recompensa por participante (apenas números)', placeholder='Digite 0 para remover. Ex: 100', required=False)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            text = self.recompensa.value.strip() if self.recompensa.value else ""
            self.view.evento_data['recompensa'] = int(text) if text != "" else None
            await self.view.atualizar_preview(interaction)
        except ValueError:
            await interaction.response.send_message("❌ A recompensa deve ser um número.", ephemeral=True)

class VagasModal(discord.ui.Modal, title='Definir Limite de Vagas'):
    def __init__(self, view):
        super().__init__()
        self.view = view

    vagas = discord.ui.TextInput(label='Número máximo de vagas (apenas números)', placeholder='Deixe em branco para remover o limite.', required=False)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            text = self.vagas.value.strip() if self.vagas.value else ""
            self.view.evento_data['vagas'] = int(text) if text != "" else None
            await self.view.atualizar_preview(interaction)
        except ValueError:
            await interaction.response.send_message("❌ O número de vagas deve ser um número.", ephemeral=True)

class MembroModal(discord.ui.Modal, title='ID do Membro'):
    membro_id = discord.ui.TextInput(label='ID do Membro', placeholder='Cole aqui o ID do membro a adicionar/remover.')

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        # Apenas responde; ação concreta é tratada no callback do botão que chamou este modal.
        await interaction.followup.send("ID recebido. Use o painel de gestão para confirmar a ação.", ephemeral=True)

class FinalizarEventoSelect(discord.ui.ChannelSelect):
    def __init__(self, evento_id, bot):
        super().__init__(placeholder="Selecione o canal de voz para confirmar presença...", channel_types=[discord.ChannelType.voice])
        self.evento_id = evento_id
        self.bot = bot

    async def callback(self, interaction: discord.Interaction):
        canal_de_voz = self.values[0]  # Channel selecionado
        members = getattr(canal_de_voz, "members", [])
        mentions = [m.mention for m in members][:50]
        texto = f"Foram encontrados {len(members)} participantes em {canal_de_voz.mention}.\n"
        if mentions:
            texto += "Lista (até 50):\n" + "\n".join(mentions)
        else:
            texto += "Nenhum participante encontrado no canal."
        await interaction.response.send_message(texto, ephemeral=True)
        # Aqui você pode adicionar lógica extra: marcar presença na DB, distribuir recompensas, etc.
        # Exemplo (opcional): atualizar inscritos no DB com os IDs dos membros presentes.
        try:
            ids = [m.id for m in members]
            await self.bot.db_manager.execute_query("UPDATE eventos SET inscritos = $1 WHERE id = $2", ids, self.evento_id)
        except Exception:
            pass

# --- VIEW DO PAINEL DE GESTÃO (NOVO) ---
class GerenciamentoEventoView(discord.ui.View):
    def __init__(self, bot, author, evento_id):
        super().__init__(timeout=1800)
        self.bot = bot
        self.author = author
        self.evento_id = evento_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("Apenas o organizador do evento pode gerir.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Iniciar", style=discord.ButtonStyle.green, emoji="▶️")
    async def iniciar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await self.bot.db_manager.execute_query("UPDATE eventos SET status = $1 WHERE id = $2", "ATIVO", self.evento_id)
        await interaction.followup.send("Evento iniciado.", ephemeral=True)

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.danger, emoji="✖️")
    async def cancelar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await self.bot.db_manager.execute_query("UPDATE eventos SET status = $1 WHERE id = $2", "CANCELADO", self.evento_id)
        await interaction.followup.send("Evento cancelado.", ephemeral=True)

    @discord.ui.button(label="Canal de Voz", style=discord.ButtonStyle.secondary, emoji="🎙️")
    async def gerir_voz(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        evento = await self.bot.db_manager.execute_query("SELECT nome, canal_voz_id FROM eventos WHERE id = $1", self.evento_id, fetch="one")
        guild = interaction.guild
        if not evento:
            await interaction.followup.send("Evento não encontrado.", ephemeral=True)
            return

        if evento.get('canal_voz_id'):
            try:
                canal = guild.get_channel(int(evento['canal_voz_id']))
                if canal:
                    await canal.delete()
                await self.bot.db_manager.execute_query("UPDATE eventos SET canal_voz_id = NULL WHERE id = $1", self.evento_id)
                await interaction.followup.send("Canal de voz removido.", ephemeral=True)
            except Exception as e:
                await interaction.followup.send(f"Falha ao remover canal: {e}", ephemeral=True)
        else:
            try:
                canal_eventos_id = await self.bot.db_manager.get_config_value('canal_eventos', '0')
                categoria = None
                if canal_eventos_id and canal_eventos_id != '0' and str(canal_eventos_id).isdigit():
                    texto = self.bot.get_channel(int(canal_eventos_id))
                    categoria = texto.category if texto else None
                novo = await guild.create_voice_channel(name=f"▶ {evento.get('nome')}", category=categoria)
                await self.bot.db_manager.execute_query("UPDATE eventos SET canal_voz_id = $1 WHERE id = $2", novo.id, self.evento_id)
                await interaction.followup.send(f"Canal de voz criado: {novo.mention}", ephemeral=True)
            except discord.Forbidden:
                await interaction.followup.send("Erro: permissão insuficiente para criar canais.", ephemeral=True)
            except Exception as e:
                await interaction.followup.send(f"Erro inesperado: {e}", ephemeral=True)

    @discord.ui.button(label="Adicionar Membro", style=discord.ButtonStyle.primary, emoji="➕")
    async def adicionar_membro(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(MembroModal())

    @discord.ui.button(label="Remover Membro", style=discord.ButtonStyle.primary, emoji="➖")
    async def remover_membro(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(MembroModal())

    @discord.ui.button(label="Finalizar", style=discord.ButtonStyle.success, emoji="🏆", row=1)
    async def finalizar(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = discord.ui.View(timeout=180)
        view.add_item(FinalizarEventoSelect(self.evento_id, self.bot))
        await interaction.response.send_message("Selecione o canal de voz para confirmar presença:", view=view, ephemeral=True)

# --- VIEW PÚBLICA DO ANÚNCIO (ATUALIZADA) ---
class EventoView(discord.ui.View):
    def __init__(self, bot, evento_id, criador_id):
        super().__init__(timeout=None)
        self.bot = bot
        self.evento_id = evento_id
        self.criador_id = criador_id

    async def atualizar_embed(self, interaction: discord.Interaction):
        evento = await self.bot.db_manager.execute_query("SELECT * FROM eventos WHERE id = $1", self.evento_id, fetch="one")
        if not evento:
            # fallback simples
            embed = discord.Embed(title="Evento", description="Dados indisponíveis.", color=discord.Color.dark_grey())
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
        try:
            if evento.get('data_evento'):
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
            mencoes = [f"<@{uid}>" for uid in inscritos]
            lista_inscritos = "\n".join(mencoes[:15])
            if len(mencoes) > 15:
                lista_inscritos += f"\n... e mais {len(mencoes) - 15}."
        embed.add_field(name="Lista de Presença", value=lista_inscritos, inline=False)
        embed.set_footer(text=f"ID do Evento: {self.evento_id} | Status: {evento.get('status')}")
        # update message (interaction.message may be None in some flows)
        try:
            await interaction.message.edit(embed=embed, view=self)
        except Exception:
            # attempt to edit original response if available
            try:
                await interaction.edit_original_response(embed=embed, view=self)
            except Exception:
                pass

    @discord.ui.button(label="Inscrever-se", style=discord.ButtonStyle.success, custom_id="inscrever_evento")
    async def inscrever(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        evento = await self.bot.db_manager.execute_query("SELECT cargo_requerido_id, inscritos, max_participantes FROM eventos WHERE id = $1", self.evento_id, fetch="one")
        if not evento:
            await interaction.response.send_message("Evento não encontrado.", ephemeral=True)
            return
        if evento.get('cargo_requerido_id'):
            try:
                cargo_req_id = int(evento['cargo_requerido_id'])
            except Exception:
                cargo_req_id = None
            cargo_requerido = discord.utils.get(user.roles, id=cargo_req_id) if cargo_req_id else None
            if not cargo_requerido:
                await interaction.response.send_message(f"❌ Evento restrito ao cargo <@&{evento['cargo_requerido_id']}>.", ephemeral=True)
                return
        inscritos = evento.get('inscritos') or []
        max_part = evento.get('max_participantes')
        if max_part and len(inscritos) >= max_part:
            await interaction.response.send_message("❌ Vagas esgotadas.", ephemeral=True)
            return
        await self.bot.db_manager.execute_query("UPDATE eventos SET inscritos = array_append(inscritos, $1) WHERE id = $2 AND NOT ($1 = ANY(inscritos))", user.id, self.evento_id)
        await self.atualizar_embed(interaction)
        await interaction.response.send_message("✅ Você foi inscrito.", ephemeral=True)

    @discord.ui.button(label="Remover Inscrição", style=discord.ButtonStyle.danger, custom_id="remover_inscricao_evento")
    async def remover_inscricao(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        await self.bot.db_manager.execute_query("UPDATE eventos SET inscritos = array_remove(inscritos, $1) WHERE id = $2", user_id, self.evento_id)
        await self.atualizar_embed(interaction)
        await interaction.response.send_message("🗑️ Inscrição removida.", ephemeral=True)

    @discord.ui.button(label="Gerir Evento", style=discord.ButtonStyle.secondary, custom_id="gerir_evento", emoji="⚙️")
    async def gerir_evento(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.criador_id:
            await interaction.response.send_message("Apenas o organizador pode gerir o evento.", ephemeral=True)
            return
        view = GerenciamentoEventoView(self.bot, interaction.user, self.evento_id)
        await interaction.response.send_message("Painel de gestão do evento:", view=view, ephemeral=True)

# --- COG PRINCIPAL ---
class Eventos(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='agendarevento', help='Inicia o assistente para criar um novo evento.')
    @check_permission_level(1)
    async def agendarevento(self, ctx: commands.Context):
        view = CriacaoEventoView(self.bot, ctx.author)
        embed = discord.Embed(title="Assistente de Criação de Eventos", description="Use os botões abaixo para configurar o seu evento. Quando terminar, clique em 'Publicar'.", color=discord.Color.yellow())
        
        # Prioriza enviar por DM (ephemeral-like). Se falhar, abre o assistente no canal.
        try:
            await ctx.author.send(embed=embed, view=view)
            try:
                await ctx.message.add_reaction("✅")
            except Exception:
                pass
            await ctx.send("✅ Assistente enviado por DM. Verifique suas mensagens privadas.", delete_after=10)
        except discord.Forbidden:
            # Não é possível enviar DM — envia no canal público (não é ephemeral porque comandos prefix não suportam).
            try:
                await ctx.send(embed=embed, view=view)
                try:
                    await ctx.message.add_reaction("✅")
                except Exception:
                    pass
                await ctx.send("⚠️ Não foi possível enviar DM. Assistente aberto no canal.", delete_after=10)
            except Exception as e:
                await ctx.send(f"❌ Falha ao iniciar o assistente: {e}", delete_after=10)

async def setup(bot):
    await bot.add_cog(Eventos(bot))
