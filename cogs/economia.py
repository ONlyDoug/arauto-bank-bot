import discord
from discord.ext import commands
import psycopg2
import psycopg2.extras
from psycopg2 import pool
import os
import contextlib

# (Funções auxiliares de BD)
# ...

class Economia(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # (Inicialização do pool)

    # TODOS os comandos de economia vão aqui
    @commands.command(name='saldo')
    async def balance(self, ctx):
        # ...
        pass
        
    @commands.command(name='transferir')
    async def transfer(self, ctx, destinatario: discord.Member, quantidade: int):
        # ...
        pass

    @commands.command(name='loja')
    async def shop(self, ctx):
        # ...
        pass

    # ... e todos os outros (infomoeda, comprar, orbe, pagar-taxa, etc.)

async def setup(bot):
    await bot.add_cog(Economia(bot))

