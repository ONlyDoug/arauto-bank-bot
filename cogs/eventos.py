import discord
from discord.ext import commands
import contextlib
from utils.permissions import check_permission_level

class Eventos(commands.Cog):
    """Cog que agrupa todos os comandos relacionados a eventos."""
    def __init__(self, bot):
        self.bot = bot

    @contextlib.contextmanager
    def get_db_connection(self):
        """Obtém uma conexão do pool e garante que ela é devolvida."""
        conn = None
        try:
            conn = self.bot.db_pool.getconn()
            yield conn
        finally:
            if conn:
                self.bot.db_pool.putconn(conn)

    # =================================================================================
    # Comandos de Gestão de Eventos (Puxadores e Admins)
    # =================================================================================

    @commands.command(name='criarevento')
    @check_permission_level(1)
    async def criar_evento(self, ctx, recompensa: int, meta: int, *, nome: str):
        """Cria um novo evento com recompensa e meta de participações. (Nível 1+)"""
        if recompensa <= 0 or meta <= 0:
            return await ctx.send("A recompensa e a meta devem ser valores positivos.")
        
        with self.get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO eventos (nome, recompensa, meta_participacao, criador_id) VALUES (%s, %s, %s, %s) RETURNING id",
                    (nome, recompensa, meta, ctx.author.id)
                )
                evento_id = cursor.fetchone()[0]
            conn.commit()

        embed = discord.Embed(
            title=f"🎉 Novo Evento Criado: {nome}",
            description=f"Um novo evento foi aberto para inscrições!",
            color=discord.Color.purple()
        )
        embed.add_field(name="ID do Evento", value=f"`{evento_id}`", inline=True)
        embed.add_field(name="Recompensa", value=f"`{recompensa:,} GC`".replace(',', '.'), inline=True)
        embed.add_field(name="Meta", value=f"`{meta} participações`", inline=True)
        embed.set_footer(text=f"Use !participar {evento_id} para se inscrever.")
        
        await ctx.send(embed=embed)

    @commands.command(name='confirmar')
    @check_permission_level(1)
    async def confirmar(self, ctx, evento_id: int, membros: commands.Greedy[discord.Member]):
        """Adiciona +1 ao progresso dos membros mencionados num evento. (Nível 1+)"""
        if not membros:
            return await ctx.send("Você precisa mencionar pelo menos um membro para confirmar a participação.")

        updates = []
        with self.get_db_connection() as conn:
            with conn.cursor() as cursor:
                # Verifica se o evento existe e está ativo
                cursor.execute("SELECT nome FROM eventos WHERE id = %s AND ativo = TRUE", (evento_id,))
                evento = cursor.fetchone()
                if not evento:
                    return await ctx.send(f"Evento com ID `{evento_id}` não encontrado ou já foi finalizado.")
                
                for membro in membros:
                    # Insere o participante se não existir, e atualiza o progresso
                    cursor.execute(
                        """
                        INSERT INTO participantes (evento_id, user_id, progresso) VALUES (%s, %s, 1)
                        ON CONFLICT (evento_id, user_id) DO UPDATE SET progresso = participantes.progresso + 1
                        """,
                        (evento_id, membro.id)
                    )
                    updates.append(membro.mention)
            conn.commit()
        
        membros_str = ", ".join(updates)
        await ctx.send(f"✅ Progresso confirmado para {membros_str} no evento **{evento[0]}** (ID: {evento_id}).")


    @commands.command(name='finalizarevento')
    @check_permission_level(1)
    async def finalizar_evento(self, ctx, evento_id: int):
        """Encerra um evento e distribui a recompensa a quem atingiu a meta. (Nível 1+)"""
        with self.get_db_connection() as conn:
            with conn.cursor() as cursor:
                # Obtém detalhes do evento
                cursor.execute("SELECT nome, recompensa, meta_participacao FROM eventos WHERE id = %s AND ativo = TRUE", (evento_id,))
                evento = cursor.fetchone()
                if not evento:
                    return await ctx.send(f"Evento com ID `{evento_id}` não encontrado ou já foi finalizado.")
                
                nome_evento, recompensa, meta = evento

                # Marca o evento como inativo
                cursor.execute("UPDATE eventos SET ativo = FALSE WHERE id = %s", (evento_id,))

                # Encontra os vencedores
                cursor.execute(
                    "SELECT user_id FROM participantes WHERE evento_id = %s AND progresso >= %s",
                    (evento_id, meta)
                )
                vencedores = cursor.fetchall()
                
                if not vencedores:
                    await ctx.send(f"🏁 Evento **{nome_evento}** finalizado, mas ninguém atingiu a meta de `{meta}` participações.")
                    conn.commit()
                    return

                # Paga as recompensas
                vencedores_ids = [v[0] for v in vencedores]
                for user_id in vencedores_ids:
                    # Reutilizando a lógica do Cog de Economia (idealmente seria uma função partilhada)
                    cursor.execute("UPDATE banco SET saldo = saldo + %s WHERE user_id = %s", (recompensa, user_id))
                    cursor.execute(
                        "INSERT INTO transacoes (user_id, tipo, valor, descricao) VALUES (%s, 'recompensa_evento', %s, %s)",
                        (user_id, recompensa, f"Recompensa do evento: {nome_evento}")
                    )
            conn.commit()
        
        mencoes_vencedores = [f"<@{user_id}>" for user_id in vencedores_ids]
        embed = discord.Embed(
            title=f"🏆 Evento Finalizado: {nome_evento}",
            description=f"A recompensa de **{recompensa:,} GC** foi distribuída aos seguintes participantes:".replace(',', '.'),
            color=discord.Color.gold()
        )
        embed.add_field(name="Vencedores", value="\n".join(mencoes_vencedores))
        await ctx.send(embed=embed)


    # =================================================================================
    # Comandos de Participação (Membros)
    # =================================================================================
    
    @commands.command(name='listareventos')
    async def listar_eventos(self, ctx):
        """Lista todos os eventos que estão atualmente ativos."""
        with self.get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT id, nome, recompensa, meta_participacao FROM eventos WHERE ativo = TRUE ORDER BY id ASC")
                eventos_ativos = cursor.fetchall()

        if not eventos_ativos:
            return await ctx.send("Não há eventos ativos no momento.")

        embed = discord.Embed(title="🏆 Eventos e Missões Ativas", color=0xe91e63)
        for id, nome, recompensa, meta in eventos_ativos:
            embed.add_field(
                name=f"ID: {id} - {nome}",
                value=f"**Recompensa:** {recompensa:,} GC | **Meta:** {meta} participações".replace(',', '.'),
                inline=False
            )
        embed.set_footer(text="Use !participar <ID> para se inscrever.")
        await ctx.send(embed=embed)

    @commands.command(name='participar')
    async def participar(self, ctx, evento_id: int):
        """Inscreve-se num evento ativo para começar a registar progresso."""
        with self.get_db_connection() as conn:
            with conn.cursor() as cursor:
                 # Verifica se o evento existe e está ativo
                cursor.execute("SELECT nome FROM eventos WHERE id = %s AND ativo = TRUE", (evento_id,))
                evento = cursor.fetchone()
                if not evento:
                    return await ctx.send(f"Evento com ID `{evento_id}` não encontrado ou já foi finalizado.")
                
                # Tenta inscrever o participante
                cursor.execute(
                    "INSERT INTO participantes (evento_id, user_id, progresso) VALUES (%s, %s, 0) ON CONFLICT DO NOTHING",
                    (evento_id, ctx.author.id)
                )
                # A propriedade 'rowcount' diz-nos se a linha foi realmente inserida (1) ou se já existia (0)
                if cursor.rowcount > 0:
                    conn.commit()
                    await ctx.send(f"✅ Você inscreveu-se com sucesso no evento **{evento[0]}** (ID: {evento_id}).")
                else:
                    await ctx.send(f"ℹ️ Você já está inscrito(a) no evento **{evento[0]}** (ID: {evento_id}).")
            
async def setup(bot):
    await bot.add_cog(Eventos(bot))
