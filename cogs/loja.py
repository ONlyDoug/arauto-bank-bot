import discord
from discord.ext import commands
import contextlib
from utils.permissions import check_permission_level

# Constante para o ID do tesouro
ID_TESOURO_GUILDA = 1

class Loja(commands.Cog):
    """Cog para todos os comandos relacionados à loja da guilda."""
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
    # Comandos de Membros
    # =================================================================================

    @commands.command(name='loja')
    async def ver_loja(self, ctx):
        """Mostra todos os itens disponíveis para compra."""
        with self.get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT id, nome, preco, descricao FROM loja ORDER BY id ASC")
                itens = cursor.fetchall()

        if not itens:
            return await ctx.send("A loja está vazia no momento.")

        embed = discord.Embed(
            title="🛍️ Loja da Guilda",
            description="Use `!comprar <ID_do_item>` para adquirir um item.",
            color=0x3498db
        )

        for item_id, nome, preco, descricao in itens:
            embed.add_field(
                name=f"ID: {item_id} - {nome}",
                value=f"**Preço:** `{preco:,} GC`\n*Desc: {descricao or 'Sem descrição'}*".replace(',', '.'),
                inline=False
            )
        
        await ctx.send(embed=embed)

    @commands.command(name='comprar')
    async def comprar_item(self, ctx, item_id: int):
        """Compra um item da loja."""
        economia_cog = self.bot.get_cog('Economia')
        if not economia_cog:
            return await ctx.send("Erro: O módulo de economia não está a funcionar. Contacte um admin.")

        async with ctx.typing():
            with self.get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT nome, preco FROM loja WHERE id = %s", (item_id,))
                    item = cursor.fetchone()
                    if not item:
                        return await ctx.send(f"Não foi encontrado nenhum item com o ID `{item_id}`.")
                    
                    nome_item, preco_item = item
                    
                    saldo_comprador = await economia_cog.get_saldo(ctx.author.id)
                    if saldo_comprador < preco_item:
                        return await ctx.send(f"Você não tem saldo suficiente para comprar **{nome_item}**. Saldo atual: `{saldo_comprador:,} GC`.".replace(',', '.'))

                    await economia_cog.update_saldo(ctx.author.id, -preco_item, "compra_loja", f"Compra do item: {nome_item} (ID: {item_id})")
                    await economia_cog.update_saldo(ID_TESOURO_GUILDA, preco_item, "venda_loja", f"Venda de {nome_item} para {ctx.author.name}")

        embed = discord.Embed(
            title="✅ Compra Realizada com Sucesso!",
            description=f"Você comprou **{nome_item}** por **{preco_item:,} GC**.".replace(',', '.'),
            color=discord.Color.green()
        )
        embed.set_footer(text="Um administrador irá entregar o seu item em breve.")
        await ctx.send(embed=embed)

    # =================================================================================
    # Comandos de Administração
    # =================================================================================

    @commands.command(name='additem')
    @check_permission_level(4)
    async def add_item(self, ctx, item_id: int, preco: int, nome: str, *, descricao: str):
        """Adiciona um novo item à loja. (Nível 4+)"""
        if preco <= 0:
            return await ctx.send("O preço do item deve ser um valor positivo.")

        with self.get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO loja (id, nome, preco, descricao) VALUES (%s, %s, %s, %s) ON CONFLICT (id) DO UPDATE SET nome = EXCLUDED.nome, preco = EXCLUDED.preco, descricao = EXCLUDED.descricao",
                    (item_id, nome, preco, descricao)
                )
            conn.commit()

        await ctx.send(f"✅ Item **{nome}** (ID: {item_id}) foi adicionado/atualizado na loja com o preço de `{preco:,} GC`.".replace(',', '.'))

    @commands.command(name='delitem')
    @check_permission_level(4)
    async def del_item(self, ctx, item_id: int):
        """Remove um item da loja. (Nível 4+)"""
        with self.get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM loja WHERE id = %s RETURNING nome", (item_id,))
                item_removido = cursor.fetchone()
            conn.commit()

        if item_removido:
            await ctx.send(f"🗑️ O item **{item_removido[0]}** (ID: {item_id}) foi removido da loja.")
        else:
            await ctx.send(f"Não foi encontrado nenhum item com o ID `{item_id}`.")


async def setup(bot):
    await bot.add_cog(Loja(bot))
