import discord
from discord.ext import commands
import datetime
from typing import Optional
from utils.permissions import check_permission_level

# --- CLASSES DE INTERFACE (MODALS, VIEWS, SELECTS) ---

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
    recompensa = discord.ui.TextInput(label='Recompensa (apenas números)', placeholder='Deixe em branco para remover.', required=False)
    async def on_submit(self, interaction: discord.Interaction):
        try:
            self.view.evento_data['recompensa'] = int(self.recompensa.value) if self.recompensa.value else None
            await self.view.atualizar_preview(interaction)
        except ValueError:
            await interaction.response.send_message("❌ A recompensa deve ser um número.", ephemeral=True, delete_after=10)

class VagasModal(discord.ui.Modal, title='Definir Limite de Vagas'):
    def __init__(self, view):
        super().__init__()
        self.view = view
    vagas = discord.ui.TextInput(label='Número máximo de vagas (apenas números)', placeholder='Deixe em branco para remover o limite.', required=False)
    async def on_submit(self, interaction: discord.Interaction):
        try:
            self.view.evento_data['vagas'] = int(self.vagas.value) if self.vagas.value else None
            await self.view.atualizar_preview(interaction)
        except ValueError:
            await interaction.response.send_message("❌ O número de vagas deve ser um número.", ephemeral=True, delete_after=10)

class CriacaoEventoView(discord.ui.View):
    def __init__(self, bot, author):
        super().__init__(timeout=1800)
        self.bot = bot
        self.author = author
        self.evento_data = {}
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("Apenas o criador do evento pode usar estes botões.", ephemeral=True)
            return False
        return True
    async def atualizar_preview(self, interaction: discord.Interaction):
        embed = discord.Embed(title="Pré-visualização do Evento", color=discord.Color.yellow())
        publish_button = discord.utils.get(self.children, custom_id="publicar_evento")
        if publish_button:
            publish_button.disabled = True
        if self.evento_data.get('nome') and self.evento_data.get('data_evento'):
            embed.title = f"[{self.evento_data.get('tipo_evento', 'INDEFINIDO').upper()}] {self.evento_data['nome']}"
            embed.description = self.evento_data.get('descricao', 'Sem detalhes.')
            try:
                embed.add_field(name="🗓️ Data e Hora", value=f"<t:{int(self.evento_data['data_evento'].timestamp())}:F>")
            except Exception:
                pass
            if publish_button:
                publish_button.disabled = False
        else:
            embed.description = "Preencha os detalhes essenciais para poder publicar."
        if self.evento_data.get('cargo_requerido'):
            embed.add_field(name="🎯 Exclusivo para", value=self.evento_data['cargo_requerido'].mention)
        if self.evento_data.get('recompensa') is not None:
            embed.add_field(name="💰 Recompensa", value=f"`{self.evento_data['recompensa']}` 🪙")
        if self.evento_data.get('vagas') is not None:
            embed.add_field(name="👥 Vagas", value=f"{self.evento_data['vagas']}")
        # sempre verificar se a resposta ainda está aberta; alguns fluxos (modal) já respondem
        try:
            await interaction.response.edit_message(embed=embed, view=self)
        except Exception:
            try:
                await interaction.followup.edit_message(interaction.message.id, embed=embed, view=self)
            except Exception:
                pass

    @discord.ui.button(label="📝 Detalhes", style=discord.ButtonStyle.primary, row=0)
    async def definir_detalhes(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DetalhesEventoModal(self))
    @discord.ui.select(cls=discord.ui.RoleSelect, placeholder="🎯 Restringir por Cargo (Opcional)", row=1, max_values=1)
    async def selecionar_cargo(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        self.evento_data['cargo_requerido'] = select.values[0] if select.values else None
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
        # Lógica de publicação...
        # inserir na DB via DatabaseManager (conforme copilot-instructions) e publicar no canal configurado
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

    @commands.command(name='agendarevento', help='Inicia o assistente para criar um novo evento.')
    @check_permission_level(1)
    async def agendarevento(self, ctx: commands.Context):
        view = CriacaoEventoView(self.bot, ctx.author)
        embed = discord.Embed(title="Assistente de Criação de Eventos", description="Use os botões abaixo para configurar o seu evento.", color=discord.Color.yellow())
        # tenta deletar a mensagem de comando para limpar chat (pode falhar por permissões)
        try:
            await ctx.message.delete()
        except Exception:
            pass
        # prioriza enviar por DM (comportamento "ephemeral-like"); se falhar, publica no canal
        try:
            await ctx.author.send(embed=embed, view=view)
            try:
                await ctx.message.add_reaction("✅")
            except Exception:
                pass
            await ctx.send("✅ Assistente enviado por DM. Verifique suas mensagens privadas.", delete_after=10)
        except discord.Forbidden:
            # fallback: envia no canal (não é ephemeral para comandos prefix)
            try:
                await ctx.send(embed=embed, view=view)
            except Exception as e:
                await ctx.send(f"❌ Falha ao iniciar o assistente: {e}", delete_after=10)

    # ... (outros comandos de eventos aqui)

async def setup(bot):
    await bot.add_cog(Eventos(bot))
