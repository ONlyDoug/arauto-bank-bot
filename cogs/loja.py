import discord
from discord.ext import commands
from utils.permissions import check_permission_level

class Loja(commands.Cog):
    """Cog para gerir a loja da guilda."""
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='loja')
    async def ver_loja(self, ctx):
        with self.bot.db_manager.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT id, nome, preco, descricao FROM loja ORDER BY id ASC")
                itens = cursor.fetchall()
        
        if not itens:
            return await ctx.send("A loja está vazia no momento.")

        embed = discord.Embed(title="🛍️ Loja da Guilda", color=0x3498db)
        for id, nome, preco, descricao in itens:
            embed.add_field(name=f"ID: {id} | {nome} - `{preco:,} GC`".replace(',', '.'),
                            value=descricao, inline=False)
        await ctx.send(embed=embed)

    @commands.command(name='comprar')
    async def comprar_item(self, ctx, item_id: int):
        with self.bot.db_manager.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT nome, preco FROM loja WHERE id = %s", (item_id,))
                item = cursor.fetchone()

        if not item:
            return await ctx.send("Item não encontrado.")
            
        nome_item, preco_item = item
        economia_cog = self.bot.get_cog('Economia')
        
        try:
            await economia_cog.levantar(ctx.author.id, preco_item, f"Compra na loja: {nome_item}")
            await ctx.send(f"✅ Você comprou **{nome_item}** por `{preco_item:,} GC`.".replace(',', '.'))
        except ValueError as e:
            await ctx.send(f"❌ Erro: {e}")

    @commands.command(name='additem')
    @check_permission_level(4)
    async def add_item(self, ctx, item_id: int, preco: int, *, nome_e_descricao: str):
        if preco <= 0:
            return await ctx.send("O preço deve ser um valor positivo.")
        
        partes = nome_e_descricao.split('|', 1)
        nome = partes[0].strip()
        descricao = partes[1].strip() if len(partes) > 1 else "Sem descrição."

        with self.bot.db_manager.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("INSERT INTO loja (id, nome, preco, descricao) VALUES (%s, %s, %s, %s) ON CONFLICT (id) DO UPDATE SET nome = EXCLUDED.nome, preco = EXCLUDED.preco, descricao = EXCLUDED.descricao",
                               (item_id, nome, preco, descricao))
            conn.commit()
        await ctx.send(f"✅ Item '{nome}' (ID: {item_id}) adicionado/atualizado na loja.")

    @commands.command(name='delitem')
    @check_permission_level(4)
    async def del_item(self, ctx, item_id: int):
        with self.bot.db_manager.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM loja WHERE id = %s RETURNING nome", (item_id,))
                item_removido = cursor.fetchone()
            conn.commit()

        if item_removido:
            await ctx.send(f"✅ Item '{item_removido[0]}' (ID: {item_id}) removido da loja.")
        else:
            await ctx.send("Item não encontrado.")

async def setup(bot):
    await bot.add_cog(Loja(bot))

