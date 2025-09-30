import discord
from discord.ext import commands
import psycopg2
import psycopg2.extras
from psycopg2 import pool
import os
import contextlib

# (Funções auxiliares de BD e Permissões)
# ... (código omitido por brevidade)

class Eventos(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # (Inicialização do pool)
    
    # (Comandos de eventos: !puxar, !confirmar-todos, !criarevento, !confirmar, etc.)
    # ...

async def setup(bot):
    await bot.add_cog(Eventos(bot))

