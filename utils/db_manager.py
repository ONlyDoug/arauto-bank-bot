import psycopg2
import psycopg2.pool
import psycopg2.extras
import asyncio
from contextlib import asynccontextmanager

class DatabaseManager:
    def __init__(self, dsn: str, min_conn: int = 2, max_conn: int = 10):
        self._dsn = dsn
        self._min_conn = min_conn
        self._max_conn = max_conn
        self._pool = None

    async def connect(self):
        """Inicializa o pool de conexões de forma assíncrona."""
        try:
            loop = asyncio.get_running_loop()
            # A criação do pool é síncrona, por isso executamo-la num executor.
            self._pool = await loop.run_in_executor(
                None,
                lambda: psycopg2.pool.SimpleConnectionPool(self._min_conn, self._max_conn, dsn=self._dsn)
            )
            print("Pool de conexões com a base de dados inicializado com sucesso.")
        except Exception as e:
            print(f"ERRO CRÍTICO ao inicializar o pool de conexões: {e}")
            raise

    async def close(self):
        """Fecha todas as conexões no pool de forma assíncrona."""
        if self._pool:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._pool.closeall)
            print("Pool de conexões fechado.")

    @asynccontextmanager
    async def get_connection(self):
        """Obtém uma conexão do pool de forma assíncrona."""
        if not self._pool:
            raise Exception("O pool de conexões não foi inicializado.")
        
        conn = None
        loop = asyncio.get_running_loop()
        try:
            conn = await loop.run_in_executor(None, self._pool.getconn)
            yield conn
        finally:
            if conn:
                await loop.run_in_executor(None, self._pool.putconn, conn)

    async def execute_query(self, query, params=None, fetch=None):
        """Executa uma query de forma assíncrona e lida com commits corretamente."""
        loop = asyncio.get_running_loop()
        async with self.get_connection() as conn:
            def db_call():
                # Esta função será executada numa thread separada
                with conn.cursor() as cursor:
                    cursor.execute(query, params)
                    if fetch == "one":
                        return cursor.fetchone()
                    if fetch == "all":
                        return cursor.fetchall()
                # Faz commit apenas se não for uma query de busca (ex: INSERT, UPDATE, DELETE)
                conn.commit()
                return None # Retorna None para queries que não são de busca
            
            return await loop.run_in_executor(None, db_call)

    async def get_config_value(self, chave: str, default: str = None):
        """Obtém um único valor de configuração da base de dados."""
        resultado = await self.execute_query(
            "SELECT valor FROM configuracoes WHERE chave = %s",
            (chave,),
            fetch="one"
        )
        return resultado[0] if resultado else default

    async def get_all_configs(self, chaves: list):
        """Busca múltiplos valores de configuração numa única query."""
        if not chaves:
            return {}
            
        query = "SELECT chave, valor FROM configuracoes WHERE chave = ANY(%s)"
        resultados = await self.execute_query(query, (chaves,), fetch="all")
        return {chave: valor for chave, valor in resultados}

    async def set_config_value(self, chave: str, valor: str):
        """Define um único valor de configuração na base de dados."""
        await self.execute_query(
            "INSERT INTO configuracoes (chave, valor) VALUES (%s, %s) ON CONFLICT (chave) DO UPDATE SET valor = EXCLUDED.valor",
            (chave, valor)
        )

