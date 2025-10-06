import psycopg2
import psycopg2.pool
import psycopg2.extras
import contextlib
import time
import asyncio

class DatabaseManager:
    def __init__(self, dsn: str, min_conn: int = 1, max_conn: int = 10):
        self._dsn = dsn
        self._min_conn = min_conn
        self._max_conn = max_conn
        self._pool = None
        self._loop = asyncio.get_event_loop()

    async def connect(self):
        try:
            self._pool = await self._loop.run_in_executor(
                None,
                lambda: psycopg2.pool.SimpleConnectionPool(self._min_conn, self._max_conn, dsn=self._dsn)
            )
            if self._pool:
                print("Pool de conexões com a base de dados inicializado com sucesso.")
        except Exception as e:
            print(f"ERRO CRÍTICO ao inicializar o pool de conexões: {e}")
            raise e

    async def close(self):
        if self._pool:
            await self._loop.run_in_executor(None, self._pool.closeall)
            print("Pool de conexões fechado.")

    def _execute_sync(self, query, params=None, fetch=None):
        """Função síncrona para ser executada no executor, com gestão de conexão."""
        conn = None
        try:
            conn = self._pool.getconn()
            with conn.cursor() as cursor:
                cursor.execute(query, params)
                if fetch == "one":
                    return cursor.fetchone()
                if fetch == "all":
                    return cursor.fetchall()
            conn.commit()
        except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
            print(f"AVISO: Erro de conexão com a DB: {e}")
            if conn:
                self._pool.putconn(conn, close=True) # Fecha a conexão problemática
            raise 
        finally:
            if conn:
                self._pool.putconn(conn)

    async def execute_query(self, query, params=None, fetch=None):
        """Executa uma query de forma assíncrona, sem bloquear o loop de eventos."""
        retries = 3
        last_exception = None
        for attempt in range(retries):
            try:
                return await self._loop.run_in_executor(
                    None,  # Usa o executor de thread padrão
                    self._execute_sync,
                    query,
                    params,
                    fetch
                )
            except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
                last_exception = e
                print(f"AVISO: Tentativa de query falhou ({attempt + 1}/{retries}). A tentar novamente em 1s.")
                await asyncio.sleep(1)
        
        print("ERRO: Não foi possível executar a query após várias tentativas.")
        raise last_exception

    async def get_config_value(self, chave: str, default: str = None):
        resultado = await self.execute_query("SELECT valor FROM configuracoes WHERE chave = %s", (chave,), fetch="one")
        return resultado[0] if resultado else default

    async def set_config_value(self, chave: str, valor: str):
        await self.execute_query(
            "INSERT INTO configuracoes (chave, valor) VALUES (%s, %s) ON CONFLICT (chave) DO UPDATE SET valor = EXCLUDED.valor",
            (chave, valor)
        )

