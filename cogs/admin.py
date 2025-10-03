import discord
from discord.ext import commands
import asyncio
from utils.permissions import check_permission_level

class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_manager = self.bot.db_manager

    async def initialize_database_schema(self):
        """
        Cria todas as tabelas e configurações na DB se não existirem.
        """
        try:
            with self.db_manager.get_connection() as conn:
                with conn.cursor() as cursor:
                    # Estrutura de tabelas
                    cursor.execute("CREATE TABLE IF NOT EXISTS banco (user_id BIGINT PRIMARY KEY, saldo BIGINT NOT NULL DEFAULT 0)")
                    cursor.execute("""CREATE TABLE IF NOT EXISTS transacoes (id SERIAL PRIMARY KEY, user_id BIGINT NOT NULL, tipo TEXT NOT NULL,
                        valor BIGINT NOT NULL, descricao TEXT, data TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP)""")
                    cursor.execute("""CREATE TABLE IF NOT EXISTS eventos (id SERIAL PRIMARY KEY, nome TEXT NOT NULL, recompensa INTEGER NOT NULL,
                        meta_participacao INTEGER NOT NULL DEFAULT 1, ativo BOOLEAN DEFAULT TRUE, criador_id BIGINT NOT NULL, message_id BIGINT)""")
                    cursor.execute("""CREATE TABLE IF NOT EXISTS participantes (evento_id INTEGER REFERENCES eventos(id) ON DELETE CASCADE,
                        user_id BIGINT, progresso INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (evento_id, user_id))""")
                    cursor.execute("CREATE TABLE IF NOT EXISTS configuracoes (chave TEXT PRIMARY KEY, valor TEXT NOT NULL)")
                    cursor.execute("""CREATE TABLE IF NOT EXISTS taxas (user_id BIGINT PRIMARY KEY, data_vencimento DATE, status TEXT DEFAULT 'pago')""")
                    cursor.execute("""CREATE TABLE IF NOT EXISTS submissoes_orbe (id SERIAL PRIMARY KEY, message_id BIGINT, cor TEXT NOT NULL, 
                        valor_total INTEGER NOT NULL, autor_id BIGINT, membros TEXT, status TEXT DEFAULT 'pendente')""")
                    cursor.execute("CREATE TABLE IF NOT EXISTS loja (id INTEGER PRIMARY KEY, nome TEXT NOT NULL, preco INTEGER NOT NULL, descricao TEXT)")
                    cursor.execute("CREATE TABLE IF NOT EXISTS renda_passiva_log (user_id BIGINT, tipo TEXT, data DATE, valor INTEGER, PRIMARY KEY (user_id, tipo, data))")
                    cursor.execute("CREATE TABLE IF NOT EXISTS submissoes_taxa (message_id BIGINT PRIMARY KEY, user_id BIGINT, status TEXT, url_imagem TEXT)")
                    
                    default_configs = {
                        'lastro_total_prata': '0', 'taxa_conversao_prata': '1000',
                        'recompensa_tier_bronze': '50', 'recompensa_tier_prata': '100', 'recompensa_tier_ouro': '200',
                        'orbe_verde': '100', 'orbe_azul': '250', 'orbe_roxa': '500', 'orbe_dourada': '1000',
                        'taxa_semanal_valor': '500', 'cargo_membro': '0', 'cargo_inadimplente': '0', 'cargo_isento': '0',
                        'perm_nivel_1': '0', 'perm_nivel_2': '0', 'perm_nivel_3': '0', 'perm_nivel_4': '0',
                        'canal_aprovacao': '0', 'canal_mercado': '0', 'canal_orbes': '0', 'canal_anuncios': '0',
                        'canal_resgates': '0', 'canal_batepapo': '0',
                        'recompensa_voz': '1', 'limite_voz': '120',
                        'recompensa_chat': '1', 'limite_chat': '100', 'cooldown_chat': '60',
                        'recompensa_reacao': '50'
                    }
                    for chave, valor in default_configs.items():
                        cursor.execute("INSERT INTO configuracoes (chave, valor) VALUES (%s, %s) ON CONFLICT (chave) DO NOTHING", (chave, valor))
                    
                    cursor.execute("INSERT INTO banco (user_id, saldo) VALUES (%s, 0) ON CONFLICT (user_id) DO NOTHING", (1,))
                conn.commit()
            print("Base de dados Supabase verificada e pronta.")
        except Exception as e:
            print(f"❌ Ocorreu um erro ao inicializar a base de dados: {e}")

    # ... (restante do código do cogs/admin.py, que não necessita de alterações)

async def setup(bot):
    await bot.add_cog(Admin(bot))

