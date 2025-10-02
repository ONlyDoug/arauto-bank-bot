import discord
from discord.ext import commands
import contextlib
from utils.permissions import check_permission_level

class Eventos(commands.Cog):
    """Cog para gerir a criação e participação em eventos."""
    def __init__(self, bot):
        self.bot = bot

    @contextlib.contextmanager
    def get_db_connection(self):
        conn = None
        try:
            conn = self.bot.db_pool.getconn()
            yield conn
        finally:
            if conn: self.bot.db_pool.putconn(conn)

    @commands.command(name='criarevento')
    @check_permission_level(1)
    async def criar_evento(self, ctx, recompensa: int, meta: int, *, nome: str):
        if recompensa <= 0 or meta <= 0:
            return await ctx.send("A recompensa e a meta devem ser valores positivos.")
        
        with self.get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("INSERT INTO eventos (nome, recompensa, meta_participacao, criador_id) VALUES (%s, %s, %s, %s) RETURNING id",
                               (nome, recompensa, meta, ctx.author.id))
                evento_id = cursor.fetchone()[0]
            conn.commit()
        
        await ctx.send(f"✅ Evento **'{nome}'** (ID: {evento_id}) criado com sucesso!")

    @commands.command(name='listareventos')
    async def listar_eventos(self, ctx):
        with self.get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT id, nome, recompensa, meta_participacao FROM eventos WHERE ativo = TRUE")
                eventos = cursor.fetchall()

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
        with self.get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1 FROM eventos WHERE id = %s AND ativo = TRUE", (evento_id,))
                if not cursor.fetchone():
                    return await ctx.send("Evento não encontrado ou inativo.")
                
                cursor.execute("INSERT INTO participantes (evento_id, user_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                               (evento_id, ctx.author.id))
            conn.commit()
        await ctx.send(f"✅ Você inscreveu-se no evento ID {evento_id}!")

    @commands.command(name='confirmar')
    @check_permission_level(1)
    async def confirmar(self, ctx, evento_id: int, membros: commands.Greedy[discord.Member]):
        if not membros:
            return await ctx.send("Você precisa de mencionar pelo menos um membro.")
            
        with self.get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1 FROM eventos WHERE id = %s AND ativo = TRUE", (evento_id,))
                if not cursor.fetchone():
                    return await ctx.send("Evento não encontrado ou inativo.")
                
                membros_ids = [m.id for m in membros]
                cursor.execute("UPDATE participantes SET progresso = progresso + 1 WHERE evento_id = %s AND user_id = ANY(%s)",
                               (evento_id, membros_ids))
            conn.commit()
        await ctx.send(f"✅ Progresso adicionado para {len(membros)} membros no evento ID {evento_id}.")

    @commands.command(name='finalizarevento')
    @check_permission_level(1)
    async def finalizar_evento(self, ctx, evento_id: int):
        with self.get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT recompensa, meta_participacao FROM eventos WHERE id = %s AND ativo = TRUE", (evento_id,))
                evento_info = cursor.fetchone()
                if not evento_info:
                    return await ctx.send("Evento não encontrado ou já finalizado.")
                
                recompensa, meta = evento_info
                cursor.execute("SELECT user_id FROM participantes WHERE evento_id = %s AND progresso >= %s", (evento_id, meta))
                vencedores = [row[0] for row in cursor.fetchall()]
                
                cursor.execute("UPDATE eventos SET ativo = FALSE WHERE id = %s", (evento_id,))
            conn.commit()

        if not vencedores:
            return await ctx.send(f"Evento ID {evento_id} finalizado. Nenhum participante atingiu a meta.")

        economia_cog = self.bot.get_cog('Economia')
        for user_id in vencedores:
            await economia_cog.update_saldo(user_id, recompensa, "recompensa_evento", f"Evento ID {evento_id}")
        
        await ctx.send(f"🎉 Evento ID {evento_id} finalizado! {len(vencedores)} membros foram recompensados com `{recompensa} GC` cada.")

async def setup(bot):
    await bot.add_cog(Eventos(bot))

