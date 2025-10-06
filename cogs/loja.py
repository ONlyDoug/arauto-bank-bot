import discord
from discord.ext import commands
from utils.permissions import check_permission_level

class Loja(commands.Cog):
    """Cog para gerir a loja da guilda."""
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='loja')
    async def ver_loja(self, ctx):
        itens = await self.bot.db_manager.execute_query(
            "SELECT id, nome, preco, descricao FROM loja ORDER BY id ASC",
            fetch="all"
        )
        
        if not itens:
            return await ctx.send("A loja está vazia no momento.")

        embed = discord.Embed(title="🛍️ Loja da Guilda", color=0x3498db)
        for id, nome, preco, descricao in itens:
            embed.add_field(name=f"ID: {id} | {nome} - `{preco:,} GC`".replace(',', '.'),
                            value=descricao, inline=False)
        await ctx.send(embed=embed)

    @commands.command(name='comprar')
    async def comprar_item(self, ctx, item_id: int):
        item = await self.bot.db_manager.execute_query(
            "SELECT nome, preco FROM loja WHERE id = %s",
            (item_id,),
            fetch="one"
        )

        if not item:
            return await ctx.send("Item não encontrado.")
            
        nome_item, preco_item = item
        economia_cog = self.bot.get_cog('Economia')
        
        try:
            # Debita o valor da conta do utilizador
            await economia_cog.levantar(ctx.author.id, preco_item, f"Compra na loja: {nome_item}")
            
            # Confirma a compra ao utilizador
            await ctx.send(f"✅ Você comprou **{nome_item}** por `{preco_item:,} GC`! Um staff irá entregar o seu item em breve.".replace(',', '.'))

            # Envia a notificação para o canal da staff
            canal_resgates_id_str = await self.bot.db_manager.get_config_value('canal_resgates', '0')
            if canal_resgates_id_str and canal_resgates_id_str != '0':
                canal_resgates = self.bot.get_channel(int(canal_resgates_id_str))
                if canal_resgates:
                    embed = discord.Embed(
                        title="📦 Pedido de Entrega da Loja",
                        description=f"Um item foi comprado e precisa de ser entregue no jogo.",
                        color=discord.Color.from_rgb(52, 152, 219) # Azul
                    )
                    embed.add_field(name="Comprador", value=ctx.author.mention, inline=True)
                    embed.add_field(name="Item Comprado", value=f"{nome_item} (ID: {item_id})", inline=True)
                    embed.set_footer(text="Staff: Por favor, entregue o item e reaja com ✅ a esta mensagem após a entrega.")
                    
                    try:
                        await canal_resgates.send(embed=embed)
                    except discord.Forbidden:
                        print(f"ERRO: Não foi possível enviar a notificação de compra para o canal {canal_resgates.name}. Sem permissões.")
                else:
                    print(f"AVISO: O canal de resgates (ID: {canal_resgates_id_str}) está configurado mas não foi encontrado.")

        except ValueError as e:
            await ctx.send(f"❌ Erro: {e}")
        except Exception as e:
            await ctx.send("Ocorreu um erro inesperado durante a compra.")
            print(f"Erro no comando comprar: {e}")

    @commands.command(name='additem')
    @check_permission_level(4)
    async def add_item(self, ctx, item_id: int, preco: int, *, nome_e_descricao: str):
        if preco <= 0:
            return await ctx.send("O preço deve ser um valor positivo.")
        
        partes = nome_e_descricao.split('|', 1)
        nome = partes[0].strip()
        descricao = partes[1].strip() if len(partes) > 1 else "Sem descrição."

        await self.bot.db_manager.execute_query(
            "INSERT INTO loja (id, nome, preco, descricao) VALUES (%s, %s, %s, %s) ON CONFLICT (id) DO UPDATE SET nome = EXCLUDED.nome, preco = EXCLUDED.preco, descricao = EXCLUDED.descricao",
            (item_id, nome, preco, descricao)
        )
        await ctx.send(f"✅ Item '{nome}' (ID: {item_id}) adicionado/atualizado na loja.")

    @commands.command(name='delitem')
    @check_permission_level(4)
    async def del_item(self, ctx, item_id: int):
        item_removido = await self.bot.db_manager.execute_query(
            "DELETE FROM loja WHERE id = %s RETURNING nome",
            (item_id,),
            fetch="one"
        )

        if item_removido:
            await ctx.send(f"✅ Item '{item_removido[0]}' (ID: {item_id}) removido da loja.")
        else:
            await ctx.send("Item não encontrado.")

async def setup(bot):
    await bot.add_cog(Loja(bot))

