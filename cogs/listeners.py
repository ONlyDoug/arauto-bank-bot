import discord
from discord.ext import commands, tasks
import psycopg2
import psycopg2.extras
from psycopg2 import pool
import os
import contextlib
from datetime import date
import time
import random

# Funções auxiliares de BD (copiadas para autonomia do Cog)
DATABASE_URL = os.getenv('DATABASE_URL')
db_connection_pool = None

def initialize_cog_connection_pool():
    global db_connection_pool
    if not db_connection_pool:
        try:
            db_connection_pool = psycopg2.pool.SimpleConnectionPool(1, 10, dsn=DATABASE_URL)
        except Exception as e:
            print(f"Erro ao inicializar pool em 'listeners': {e}")

@contextlib.contextmanager
def get_db_connection():
    if db_connection_pool is None: raise Exception("Pool não inicializado.")
    conn = None
    try:
        conn = db_connection_pool.getconn()
        yield conn
    finally:
        if conn: db_connection_pool.putconn(conn)

def get_config_value(chave: str, default: str = None):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT valor FROM configuracoes WHERE chave = %s", (chave,)); resultado = cursor.fetchone()
    return resultado[0] if resultado else default

def get_account(user_id: int):
     with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1 FROM banco WHERE user_id = %s", (user_id,))
            if cursor.fetchone() is None:
                cursor.execute("INSERT INTO banco (user_id, saldo) VALUES (%s, 0) ON CONFLICT (user_id) DO NOTHING", (user_id,)); conn.commit()

def get_or_create_daily_activity(user_id: int, target_date: date):
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            cursor.execute("SELECT * FROM atividade_diaria WHERE user_id = %s AND data = %s", (user_id, target_date))
            activity = cursor.fetchone()
            if activity is None:
                cursor.execute("INSERT INTO atividade_diaria (user_id, data) VALUES (%s, %s) ON CONFLICT (user_id, data) DO NOTHING", (user_id, target_date)); conn.commit()
                cursor.execute("SELECT * FROM atividade_diaria WHERE user_id = %s AND data = %s", (user_id, target_date)); activity = cursor.fetchone()
    return activity

class Listeners(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        initialize_cog_connection_pool()
        self.user_message_cooldowns = {}
        # As tarefas em background agora vivem aqui
        self.market_update.start()

    def cog_unload(self):
        self.market_update.cancel()

    @commands.Cog.listener()
    async def on_message(self, message):
        """Processa todas as mensagens para comandos e recompensas de chat."""
        if message.author.bot:
            return

        # 1. Processa comandos PRIMEIRO. Isto corrige o bug de o bot não responder.
        await self.bot.process_commands(message)

        # 2. Verifica se a mensagem era um comando válido. Se sim, para por aqui.
        ctx = await self.bot.get_context(message)
        if ctx.valid:
            return

        # 3. Se não for um comando, aplica a lógica de recompensa por chat.
        user_id = message.author.id
        current_time = time.time()
        cooldown_seconds = int(get_config_value('cooldown_chat', '60'))
        if user_id in self.user_message_cooldowns and current_time - self.user_message_cooldowns[user_id] < cooldown_seconds:
            return
        
        get_account(user_id)
        activity = get_or_create_daily_activity(user_id, date.today())
        limite_diario = int(get_config_value('limite_diario_chat', '100'))
        recompensa = int(get_config_value('recompensa_chat', '1'))
        
        if activity and activity['moedas_chat'] < limite_diario:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("UPDATE banco SET saldo = saldo + %s WHERE user_id = %s", (recompensa, user_id))
                    cursor.execute("UPDATE atividade_diaria SET moedas_chat = moedas_chat + %s WHERE user_id = %s AND data = %s", (recompensa, user_id, date.today())); conn.commit()
            self.user_message_cooldowns[user_id] = current_time

    @tasks.loop(hours=6)
    async def market_update(self):
        """Envia uma atualização periódica sobre a saúde da economia."""
        await self.bot.wait_until_ready()
        channel_id = int(get_config_value('canal_mercado', '0'))
        if channel_id == 0 or (channel := self.bot.get_channel(channel_id)) is None:
            return
        # (Lógica da mensagem de mercado)
        pass
        
async def setup(bot):
    await bot.add_cog(Listeners(bot))
