import discord
from discord.ext import commands
from utils.permissions import check_permission_level

class Eventos(commands.Cog):
    """Cog para gerir a criação e participação em eventos."""
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='criarevento')
    @check_permission_level(1)
    async def criar_evento(self, ctx, recompensa: int, meta: int, *, nome: str):
        if recompensa <= 0 or meta <= 0:
            return await ctx.send("A recompensa e a meta devem ser valores positivos.")
        
        resultado = await self.bot.db_manager.execute_query(
            "INSERT INTO eventos (nome, recompensa, meta_participacao, criador_id) VALUES (%s, %s, %s, %s) RETURNING id",
            (nome, recompensa, meta, ctx.author.id),
            fetch="one"
        )
        evento_id = resultado[0]
        
        await ctx.send(f"✅ Evento **'{nome}'** (ID: {evento_id}) criado com sucesso!")

    @commands.command(name='listareventos')
    async def listar_eventos(self, ctx):
        eventos = await self.bot.db_manager.execute_query(
            "SELECT id, nome, recompensa, meta_participacao FROM eventos WHERE ativo = TRUE",
            fetch="all"
        )

        if not eventos:
            return await ctx.send("Não há eventos ativos no momento.")

        embed = discord.Embed(title="🏆 Eventos Ativos", color=0xe91e63)
        for id, nome, recompensa, meta in eventos:
            embed.add_field(name=f"ID: {id} - {nome}",
                            value=f"Recompensa: `{recompensa} GC` | Meta: `{meta} participações`",
                            inline=False)
        await ctx.send(embed=embed)

    @commands.command(name='participar')
    async def participar(self, ctx, evento_id: int):
        evento = await self.bot.db_manager.execute_query(
            "SELECT 1 FROM eventos WHERE id = %s AND ativo = TRUE",
            (evento_id,),
            fetch="one"
        )
        if not evento:
            return await ctx.send("Evento não encontrado ou inativo.")
        
        await self.bot.db_manager.execute_query(
            "INSERT INTO participantes (evento_id, user_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (evento_id, ctx.author.id)
        )
        await ctx.send(f"✅ Você inscreveu-se no evento ID {evento_id}!")

    @commands.command(name='confirmar')
    @check_permission_level(1)
    async def confirmar(self, ctx, evento_id: int, membros: commands.Greedy[discord.Member]):
        if not membros:
            return await ctx.send("Você precisa de mencionar pelo menos um membro.")
            
        evento = await self.bot.db_manager.execute_query(
            "SELECT 1 FROM eventos WHERE id = %s AND ativo = TRUE",
            (evento_id,),
            fetch="one"
        )
        if not evento:
            return await ctx.send("Evento não encontrado ou inativo.")
        
        membros_ids = [m.id for m in membros]
        await self.bot.db_manager.execute_query(
            "UPDATE participantes SET progresso = progresso + 1 WHERE evento_id = %s AND user_id = ANY(%s)",
            (evento_id, membros_ids)
        )
        await ctx.send(f"✅ Progresso adicionado para {len(membros)} membros no evento ID {evento_id}.")

    @commands.command(name='finalizarevento')
    @check_permission_level(1)
    async def finalizar_evento(self, ctx, evento_id: int):
        evento_info = await self.bot.db_manager.execute_query(
            "SELECT recompensa, meta_participacao, nome FROM eventos WHERE id = %s AND ativo = TRUE",
            (evento_id,),
            fetch="one"
        )
        if not evento_info:
            return await ctx.send("Evento não encontrado ou já finalizado.")
        
        recompensa, meta, nome_evento = evento_info
        
        vencedores_rows = await self.bot.db_manager.execute_query(
            "SELECT user_id FROM participantes WHERE evento_id = %s AND progresso >= %s",
            (evento_id, meta),
            fetch="all"
        )
        vencedores_ids = [row[0] for row in vencedores_rows]
        
        await self.bot.db_manager.execute_query("UPDATE eventos SET ativo = FALSE WHERE id = %s", (evento_id,))

        if not vencedores_ids:
            return await ctx.send(f"Evento '{nome_evento}' (ID: {evento_id}) finalizado. Nenhum participante atingiu a meta.")

        economia_cog = self.bot.get_cog('Economia')
        for user_id in vencedores_ids:
            await economia_cog.depositar(user_id, recompensa, f"Recompensa do evento '{nome_evento}'")
        
        await ctx.send(f"🎉 Evento '{nome_evento}' (ID: {evento_id}) finalizado! {len(vencedores_ids)} membros foram recompensados com `{recompensa} GC` cada.")

async def setup(bot):
    await bot.add_cog(Eventos(bot))
