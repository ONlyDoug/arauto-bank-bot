import discord
from discord.ext import commands
import datetime
from typing import Optional
from utils.permissions import check_permission_level

# --- CLASSES DE INTERFACE (MODALS, VIEWS, SELECTS) ---
# Todas as classes são definidas PRIMEIRO para resolver o 'NameError'.

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
            # Parse da data; astimezone() mantido para compatibilidade caso haja tz
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
            text = (self.recompensa.value or "").strip()
            self.view.evento_data['recompensa'] = int(text) if text != "" else None
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
            text = (self.vagas.value or "").strip()
            self.view.evento_data['vagas'] = int(text) if text != "" else None
            await self.view.atualizar_preview(interaction)
        except ValueError:
            await interaction.response.send_message("❌ O número de vagas deve ser um número.", ephemeral=True, delete_after=10)

# --- VIEW PÚBLICA DO ANÚNCIO (mínima para evitar NameError) ---
class EventoView(discord.ui.View):
    def __init__(self, bot, evento_id, criador_id):
        super().__init__(timeout=None)
        self.bot = bot
        self.evento_id = evento_id
        self.criador_id = criador_id

    async def atualizar_embed(self, interaction: discord.Interaction):
        evento = await self.bot.db_manager.execute_query("SELECT * FROM eventos WHERE id = $1", self.evento_id, fetch="one")
        if not evento:
            embed = discord.Embed(title="Evento", description="Dados indisponíveis.", color=discord.Color.dark_grey())
            try:
                if interaction.message:
                    await interaction.message.edit(embed=embed, view=self)
            except Exception:
                pass
            return

        embed = discord.Embed(
            title=f"[{(evento.get('tipo_evento') or '').upper()}] {evento.get('nome')}",
            description=evento.get('descricao') or "Sem detalhes.",
            color=discord.Color.blue()
        )
        if evento.get('data_evento'):
            try:
                embed.add_field(name="🗓️ Data e Hora", value=f"<t:{int(evento['data_evento'].timestamp())}:F>", inline=False)
            except Exception:
                pass
        if evento.get('recompensa', 0) > 0:
            embed.add_field(name="💰 Recompensa", value=f"`{evento['recompensa']}` 🪙", inline=False)
        inscritos = evento.get('inscritos') or []
        vagas_texto = f"{len(inscritos)}"
        if evento.get('max_participantes'):
            vagas_texto += f" / {evento['max_participantes']}"
        embed.add_field(name="👥 Inscritos", value=vagas_texto, inline=False)
        lista = "\n".join([f"<@{uid}>" for uid in inscritos[:15]]) or "Ninguém se inscreveu ainda."
        if len(inscritos) > 15:
            lista += f"\n... e mais {len(inscritos)-15}."
        embed.add_field(name="Lista de Presença", value=lista, inline=False)
        embed.set_footer(text=f"ID do Evento: {self.evento_id} | Organizador: {self.criador_id}")
        try:
            if interaction.message:
                await interaction.message.edit(embed=embed, view=self)
        except Exception:
            pass

    @discord.ui.button(label="Inscrever-se", style=discord.ButtonStyle.success, custom_id="inscrever_evento")
    async def inscrever(self, interaction: discord.Interaction, button: discord.ui.Button):
        evento = await self.bot.db_manager.execute_query("SELECT inscritos, max_participantes, cargo_requerido_id FROM eventos WHERE id = $1", self.evento_id, fetch="one")
        if not evento:
            await interaction.response.send_message("Evento não encontrado.", ephemeral=True)
            return
        cargo_id = evento.get('cargo_requerido_id')
        if cargo_id:
            has = any(r.id == int(cargo_id) for r in interaction.user.roles)
            if not has:
                await interaction.response.send_message(f"❌ Evento restrito ao cargo <@&{cargo_id}>.", ephemeral=True)
                return
        inscritos = evento.get('inscritos') or []
        maxp = evento.get('max_participantes')
        if maxp and len(inscritos) >= maxp:
            await interaction.response.send_message("❌ Vagas esgotadas.", ephemeral=True)
            return
        await self.bot.db_manager.execute_query("UPDATE eventos SET inscritos = array_append(inscritos, $1) WHERE id = $2 AND NOT ($1 = ANY(inscritos))", interaction.user.id, self.evento_id)
        await self.atualizar_embed(interaction)
        await interaction.response.send_message("✅ Inscrição confirmada.", ephemeral=True)

    @discord.ui.button(label="Remover Inscrição", style=discord.ButtonStyle.danger, custom_id="remover_inscricao_evento")
    async def remover_inscricao(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.bot.db_manager.execute_query("UPDATE eventos SET inscritos = array_remove(inscritos, $1) WHERE id = $2", interaction.user.id, self.evento_id)
        await self.atualizar_embed(interaction)
        await interaction.response.send_message("🗑️ Inscrição removida.", ephemeral=True)

    @discord.ui.button(label="Gerir Evento", style=discord.ButtonStyle.secondary, custom_id="gerir_evento", emoji="⚙️")
    async def gerir_evento(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.criador_id:
            await interaction.response.send_message("Apenas o organizador pode gerir o evento.", ephemeral=True)
            return
        view = discord.ui.View(timeout=1800)
        await interaction.response.send_message("Painel de gestão disponível.", ephemeral=True, view=view)

# --- VIEW DO ASSISTENTE DE CRIAÇÃO ---
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
            publish_button.disabled = False
        else:
            embed.description = "Preencha os detalhes essenciais para poder publicar."

        if self.evento_data.get('cargo_requerido'):
            embed.add_field(name="🎯 Exclusivo para", value=self.evento_data['cargo_requerido'].mention)
        if self.evento_data.get('recompensa') is not None:
            embed.add_field(name="💰 Recompensa", value=f"`{self.evento_data['recompensa']}` 🪙")
        if self.evento_data.get('vagas') is not None:
            embed.add_field(name="👥 Vagas", value=f"{self.evento_data['vagas']}")

        # tenta editar a resposta da interação; alguns fluxos já responderam ao modal
        try:
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
        # armazena o objeto Role (RoleSelect devolve roles)
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
        await interaction.response.defer()  # confirma a interação
        cargo_id = self.evento_data.get('cargo_requerido').id if self.evento_data.get('cargo_requerido') else None

        # insere evento usando DatabaseManager (conforme convensão do projeto)
        try:
            resultado = await self.bot.db_manager.execute_query(
                """INSERT INTO eventos (nome, descricao, tipo_evento, data_evento, recompensa, max_participantes, criador_id, cargo_requerido_id)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id""",
                self.evento_data['nome'], self.evento_data.get('descricao'), self.evento_data.get('tipo_evento'),
                self.evento_data['data_evento'], self.evento_data.get('recompensa', 0), self.evento_data.get('vagas'),
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

        # construir embed final a partir dos dados (evita depêndencia de interaction.message)
        final_embed = discord.Embed(
            title=f"[{self.evento_data.get('tipo_evento','INDEFINIDO').upper()}] {self.evento_data['nome']}",
            description=self.evento_data.get('descricao', 'Sem detalhes.'),
            color=discord.Color.blue()
        )
        try:
            final_embed.add_field(name="🗓️ Data e Hora", value=f"<t:{int(self.evento_data['data_evento'].timestamp())}:F>")
        except Exception:
            pass
        if self.evento_data.get('recompensa') is not None:
            final_embed.add_field(name="💰 Recompensa", value=f"`{self.evento_data['recompensa']}` 🪙")
        vagas_texto = "Ilimitadas" if not self.evento_data.get('vagas') else f"0 / {self.evento_data['vagas']}"
        final_embed.add_field(name="👥 Inscritos", value=vagas_texto)
        if self.evento_data.get('cargo_requerido'):
            final_embed.add_field(name="🎯 Exclusivo para", value=self.evento_data['cargo_requerido'].mention, inline=False)
        final_embed.set_footer(text=f"ID do Evento: {evento_id} | Organizado por: {interaction.user.display_name}")

        if canal:
            try:
                public_view = EventoView(self.bot, evento_id, interaction.user.id)
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

# --- COG PRINCIPAL ---
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

        # prioriza enviar por DM; se falhar, publica no canal (com aviso)
        try:
            await ctx.author.send(embed=embed, view=view)
            try:
                await ctx.message.add_reaction("✅")
            except Exception:
                pass
            try:
                info = await ctx.send("✅ Assistente enviado por DM. Verifique suas mensagens privadas.")
                await info.delete(delay=10)
            except Exception:
                pass
        except discord.Forbidden:
            # fallback: envia no canal onde o comando foi usado
            try:
                await ctx.send(embed=embed, view=view)
            except Exception as e:
                try:
                    await ctx.send(f"❌ Falha ao iniciar o assistente: {e}", delete_after=10)
                except Exception:
                    pass

async def setup(bot):
    await bot.add_cog(Eventos(bot))
