import discord
from discord.ext import commands
from discord import app_commands
import datetime
import asyncio
from utils.permissions import check_permission_level

# --- Classes de Interface (Formulário e Botões) ---

class FormularioEvento(discord.ui.Modal, title='Agendar Novo Evento'):
    nome = discord.ui.TextInput(label='Nome do Evento', placeholder='Ex: Defesa de Território em MR')
    data_hora = discord.ui.TextInput(label='Data e Hora (AAAA-MM-DD HH:MM)', placeholder='Ex: 2025-10-18 21:00')
    tipo_evento = discord.ui.TextInput(label='Tipo de Conteúdo', placeholder='ZvZ, DG AVA, Gank, Reunião, Outro...')
    descricao = discord.ui.TextInput(label='Descrição e Requisitos', style=discord.TextStyle.paragraph, placeholder='IP Mínimo: 1400, Ponto de Encontro: HO de MR...', required=False)
    opcionais = discord.ui.TextInput(label='Opcionais (Recompensa, Vagas)', placeholder='Ex: recompensa=100 vagas=20', required=False)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer() # Apenas confirma o envio

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
            await interaction.message.edit(view=self)
            return

        embed = discord.Embed(
            title=f"[{evento['tipo_evento'].upper()}] {evento['nome']}",
            description=evento['descricao'] or "Sem detalhes adicionais.",
            color=discord.Color.blue()
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
            lista_inscritos = "\n".join(mencoes)
        
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

class Eventos(commands.Cog):
    """Cog para gerir a criação e participação em eventos."""
    def __init__(self, bot):
        self.bot = bot

    @commands.command(
        name='puxar',
        help='Cria um evento rápido (puxada) com recompensa e meta pré-definidas. Exclusivo para Puxadores de conteúdo.',
        usage='!puxar ouro Gank em Lymhurst',
        hidden=True # Esconde este comando da ajuda geral, pois é para um grupo específico
    )
    @check_permission_level(1)
    async def puxar_evento(self, ctx, tier: str, *, nome: str):
        """Cria um evento rápido com recompensa pré-definida."""
        tier_lower = tier.lower()
        if tier_lower not in ['bronze', 'ouro']:
            return await ctx.send("❌ Tier inválido. Use `bronze` ou `ouro`.")

        # Verificar limite diário de puxadas
        limite_diario_str = await self.bot.db_manager.get_config_value('limite_puxadas_diario', '5')
        limite_diario = int(limite_diario_str)
        
        hoje = date.today()
        puxadas_hoje = await self.bot.db_manager.execute_query(
            "SELECT quantidade FROM puxadas_log WHERE puxador_id = $1 AND data = $2",
            ctx.author.id, hoje, fetch="one"
        )
        
        quantidade_puxadas = puxadas_hoje['quantidade'] if puxadas_hoje else 0
        if quantidade_puxadas >= limite_diario:
            return await ctx.send(f"❌ Você já atingiu o seu limite de **{limite_diario}** puxadas de eventos hoje.")

        # Obter recompensa do tier
        recompensa_str = await self.bot.db_manager.get_config_value(f'recompensa_puxar_{tier_lower}', '0')
        recompensa = int(recompensa_str)

        if recompensa == 0:
            return await ctx.send(f"⚠️ A recompensa para o tier '{tier.capitalize()}' não está configurada.")
        
        # Criar o evento com meta padrão de 1 participação
        meta = 1
        resultado = await self.bot.db_manager.execute_query(
            "INSERT INTO eventos (nome, recompensa, meta_participacao, criador_id) VALUES ($1, $2, $3, $4) RETURNING id",
            f"[{tier.capitalize()}] {nome}", recompensa, meta, ctx.author.id, fetch="one"
        )
        evento_id = resultado['id']

        # Atualizar log de puxadas
        await self.bot.db_manager.execute_query(
            "INSERT INTO puxadas_log (puxador_id, data, quantidade) VALUES ($1, $2, 1) ON CONFLICT (puxador_id, data) DO UPDATE SET quantidade = puxadas_log.quantidade + 1",
            ctx.author.id, hoje
        )
        
        await ctx.send(f"✅ Evento **'{nome}'** (Tier: {tier.capitalize()}, ID: {evento_id}) criado com sucesso! Recompensa: **{recompensa}** moedas.")

    @commands.command(
        name='listareventos',
        help='Mostra uma lista de todos os eventos e missões que estão a decorrer na guilda.'
    )
    async def listar_eventos(self, ctx):
        eventos = await self.bot.db_manager.execute_query(
            "SELECT id, nome, recompensa, meta_participacao FROM eventos WHERE ativo = TRUE", fetch="all"
        )

        if not eventos:
            return await ctx.send("Não há eventos ativos no momento. Que tédio...")

        embed = discord.Embed(title="🏆 Eventos Ativos", color=0xe91e63)
        for evento in eventos:
            embed.add_field(
                name=f"ID: {evento['id']} - {evento['nome']}",
                value=f"Recompensa: `{evento['recompensa']} GC` | Meta: `{evento['meta_participacao']} participações`",
                inline=False
            )
        await ctx.send(embed=embed)

    @commands.command(
        name='participar',
        help='Inscreve-se num evento ativo usando o ID do mesmo. Não fiques de fora!',
        usage='!participar 12'
    )
    async def participar(self, ctx, evento_id: int):
        evento = await self.bot.db_manager.execute_query(
            "SELECT 1 FROM eventos WHERE id = $1 AND ativo = TRUE", evento_id, fetch="one"
        )
        if not evento:
            return await ctx.send("Evento não encontrado ou inativo. Chegaste tarde à festa.")
        
        await self.bot.db_manager.execute_query(
            "INSERT INTO participantes (evento_id, user_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            evento_id, ctx.author.id
        )
        await ctx.send(f"✅ Inscrição no evento ID {evento_id} confirmada! Agora dá o teu melhor.")

    # Comandos de staff ficam escondidos da ajuda padrão
    @commands.command(name='criarevento', hidden=True)
    @check_permission_level(2)
    async def criar_evento(self, ctx, recompensa: int, meta: int, *, nome: str):
        if recompensa <= 0 or meta <= 0:
            return await ctx.send("A recompensa e a meta devem ser valores positivos.")
        
        resultado = await self.bot.db_manager.execute_query(
            "INSERT INTO eventos (nome, recompensa, meta_participacao, criador_id) VALUES ($1, $2, $3, $4) RETURNING id",
            nome, recompensa, meta, ctx.author.id, fetch="one"
        )
        evento_id = resultado['id']
        
        await ctx.send(f"✅ Evento **'{nome}'** (ID: {evento_id}) criado com sucesso!")

    @commands.command(name='confirmar', hidden=True)
    @check_permission_level(1)
    async def confirmar(self, ctx, evento_id: int, membros: commands.Greedy[discord.Member]):
        if not membros:
            return await ctx.send("Você precisa de mencionar pelo menos um membro.")
            
        evento = await self.bot.db_manager.execute_query(
            "SELECT 1 FROM eventos WHERE id = $1 AND ativo = TRUE", evento_id, fetch="one"
        )
        if not evento:
            return await ctx.send("Evento não encontrado ou inativo.")
        
        membros_ids = [m.id for m in membros]
        await self.bot.db_manager.execute_query(
            "UPDATE participantes SET progresso = progresso + 1 WHERE evento_id = $1 AND user_id = ANY($2::BIGINT[])",
            evento_id, membros_ids
        )
        await ctx.send(f"✅ Progresso adicionado para {len(membros)} membros no evento ID {evento_id}.")

    @commands.command(name='confirmartodos', hidden=True)
    @check_permission_level(1)
    async def confirmar_todos(self, ctx, evento_id: int):
        evento = await self.bot.db_manager.execute_query(
            "SELECT 1 FROM eventos WHERE id = $1 AND ativo = TRUE", evento_id, fetch="one"
        )
        if not evento:
            return await ctx.send("Evento não encontrado ou inativo.")

        # Obter todos os IDs de participantes do evento
        participantes = await self.bot.db_manager.execute_query(
            "SELECT user_id FROM participantes WHERE evento_id = $1", evento_id, fetch="all"
        )
        if not participantes:
            return await ctx.send("Nenhum membro inscrito neste evento.")

        membros_ids = [p['user_id'] for p in participantes]
        
        await self.bot.db_manager.execute_query(
            "UPDATE participantes SET progresso = progresso + 1 WHERE evento_id = $1",
            evento_id
        )
        await ctx.send(f"✅ Progresso adicionado para **todos os {len(membros_ids)}** membros inscritos no evento ID {evento_id}.")

    @commands.command(name='confirmarexceto', hidden=True)
    @check_permission_level(1)
    async def confirmar_exceto(self, ctx, evento_id: int, membros_excluidos: commands.Greedy[discord.Member]):
        """Confirma todos, exceto os membros mencionados."""
        if not membros_excluidos:
            return await ctx.send("Você precisa de mencionar pelo menos um membro para excluir da confirmação.")

        evento = await self.bot.db_manager.execute_query(
            "SELECT 1 FROM eventos WHERE id = $1 AND ativo = TRUE", evento_id, fetch="one"
        )
        if not evento:
            return await ctx.send("Evento não encontrado ou inativo.")

        ids_excluidos = {m.id for m in membros_excluidos}
        
        # Obter todos os participantes e filtrar os que não devem ser confirmados
        participantes = await self.bot.db_manager.execute_query(
            "SELECT user_id FROM participantes WHERE evento_id = $1", evento_id, fetch="all"
        )
        if not participantes:
            return await ctx.send("Nenhum membro inscrito neste evento.")

        membros_a_confirmar_ids = [p['user_id'] for p in participantes if p['user_id'] not in ids_excluidos]

        if not membros_a_confirmar_ids:
            return await ctx.send("Nenhum membro para confirmar após a exclusão.")

        await self.bot.db_manager.execute_query(
            "UPDATE participantes SET progresso = progresso + 1 WHERE evento_id = $1 AND user_id = ANY($2::BIGINT[])",
            evento_id, membros_a_confirmar_ids
        )
        await ctx.send(f"✅ Progresso adicionado para **{len(membros_a_confirmar_ids)}** membros no evento ID {evento_id} (excluindo {len(membros_excluidos)} mencionados).")

    @commands.command(name='finalizarevento', hidden=True)
    @check_permission_level(1)
    async def finalizar_evento(self, ctx, evento_id: int):
        evento_info = await self.bot.db_manager.execute_query(
            "SELECT recompensa, meta_participacao, nome FROM eventos WHERE id = $1 AND ativo = TRUE",
            evento_id, fetch="one"
        )
        if not evento_info:
            return await ctx.send("Evento não encontrado ou já finalizado.")
        
        recompensa, meta, nome_evento = evento_info['recompensa'], evento_info['meta_participacao'], evento_info['nome']
        
        vencedores = await self.bot.db_manager.execute_query(
            "SELECT user_id FROM participantes WHERE evento_id = $1 AND progresso >= $2",
            evento_id, meta, fetch="all"
        )
        vencedores_ids = [rec['user_id'] for rec in vencedores]
        
        await self.bot.db_manager.execute_query(
            "UPDATE eventos SET ativo = FALSE WHERE id = $1", evento_id
        )

        if not vencedores_ids:
            return await ctx.send(f"Evento '{nome_evento}' (ID: {evento_id}) finalizado. Nenhum participante atingiu a meta.")

        economia_cog = self.bot.get_cog('Economia')
        sucessos = 0
        falhas = 0
        
        for user_id in vencedores_ids:
            try:
                await economia_cog.transferir_do_tesouro(user_id, recompensa, f"Recompensa do evento '{nome_evento}'")
                sucessos += 1
            except Exception as e:
                falhas += 1
                print(f"Falha ao pagar evento '{nome_evento}' para user {user_id}: {e}")

        msg_final = f"🎉 Evento '{nome_evento}' (ID: {evento_id}) finalizado! {sucessos} membros foram recompensados com `{recompensa} GC` cada."
        if falhas > 0:
            msg_final += f"\n⚠️ **{falhas} pagamentos falharam.** Verifique os logs. (Provavelmente o tesouro não tem saldo suficiente)."
        
        await ctx.send(msg_final)

    @commands.hybrid_command(
        name='agendarevento',
        description='Abre um formulário para criar e agendar um novo evento da guilda.'
    )
    @check_permission_level(1)
    async def agendar_evento(self, ctx: commands.Context):
        formulario = FormularioEvento()
        await ctx.interaction.response.send_modal(formulario)
        await formulario.wait()

        try:
            data_evento = datetime.datetime.strptime(formulario.data_hora.value, '%Y-%m-%d %H:%M').astimezone()
        except ValueError:
            await ctx.followup.send("❌ Formato de data e hora inválido. Use AAAA-MM-DD HH:MM.", ephemeral=True)
            return

        recompensa, max_participantes = 0, None
        if formulario.opcionais.value:
            for parte in formulario.opcionais.value.split():
                if 'recompensa=' in parte:
                    recompensa = int(parte.split('=')[1])
                if 'vagas=' in parte:
                    max_participantes = int(parte.split('=')[1])

        resultado = await self.bot.db_manager.execute_query(
            """INSERT INTO eventos (nome, descricao, tipo_evento, data_evento, recompensa, max_participantes, criador_id)
               VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING id""",
            formulario.nome.value, formulario.descricao.value, formulario.tipo_evento.value,
            data_evento, recompensa, max_participantes, ctx.author.id,
            fetch="one"
        )
        evento_id = resultado['id']

        canal_eventos_id = await self.bot.db_manager.get_config_value('canal_eventos', '0')
        if canal_eventos_id == '0':
            await ctx.followup.send("✅ Evento agendado, mas o canal de eventos não está configurado! Use `!definircanal eventos #canal`.", ephemeral=True)
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
            embed.set_footer(text=f"ID do Evento: {evento_id} | Organizado por: {ctx.author.display_name}")

            await canal.send(embed=embed, view=view)
            await ctx.followup.send(f"✅ Evento **{formulario.nome.value}** agendado com sucesso no canal {canal.mention}!", ephemeral=True)
        else:
            await ctx.followup.send("❌ Canal de eventos configurado mas não encontrado.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Eventos(bot))
