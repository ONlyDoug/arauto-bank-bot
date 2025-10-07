import discord
from discord.ext import commands
from utils.permissions import check_permission_level
from datetime import datetime, date

class Eventos(commands.Cog):
    """Cog para gerir a criação e participação em eventos."""
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='puxar')
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

    @commands.command(name='criarevento')
    @check_permission_level(2) # Permissão elevada para Nível 2
    async def criar_evento(self, ctx, recompensa: int, meta: int, *, nome: str):
        if recompensa <= 0 or meta <= 0:
            return await ctx.send("A recompensa e a meta devem ser valores positivos.")
        
        resultado = await self.bot.db_manager.execute_query(
            "INSERT INTO eventos (nome, recompensa, meta_participacao, criador_id) VALUES ($1, $2, $3, $4) RETURNING id",
            nome, recompensa, meta, ctx.author.id, fetch="one"
        )
        evento_id = resultado['id']
        
        await ctx.send(f"✅ Evento **'{nome}'** (ID: {evento_id}) criado com sucesso!")

    @commands.command(name='listareventos')
    async def listar_eventos(self, ctx):
        eventos = await self.bot.db_manager.execute_query(
            "SELECT id, nome, recompensa, meta_participacao FROM eventos WHERE ativo = TRUE", fetch="all"
        )

        if not eventos:
            return await ctx.send("Não há eventos ativos no momento.")

        embed = discord.Embed(title="🏆 Eventos Ativos", color=0xe91e63)
        for evento in eventos:
            embed.add_field(
                name=f"ID: {evento['id']} - {evento['nome']}",
                value=f"Recompensa: `{evento['recompensa']} GC` | Meta: `{evento['meta_participacao']} participações`",
                inline=False
            )
        await ctx.send(embed=embed)

    @commands.command(name='participar')
    async def participar(self, ctx, evento_id: int):
        evento = await self.bot.db_manager.execute_query(
            "SELECT 1 FROM eventos WHERE id = $1 AND ativo = TRUE", evento_id, fetch="one"
        )
        if not evento:
            return await ctx.send("Evento não encontrado ou inativo.")
        
        await self.bot.db_manager.execute_query(
            "INSERT INTO participantes (evento_id, user_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            evento_id, ctx.author.id
        )
        await ctx.send(f"✅ Você inscreveu-se no evento ID {evento_id}!")

    @commands.command(name='confirmar')
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

    @commands.command(name='confirmartodos')
    @check_permission_level(1)
    async def confirmar_todos(self, ctx, evento_id: int):
        """Confirma a participação de todos os membros inscritos num evento."""
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

    @commands.command(name='confirmarexceto')
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

    @commands.command(name='finalizarevento')
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

async def setup(bot):
    await bot.add_cog(Eventos(bot))
