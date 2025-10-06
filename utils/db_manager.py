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

    async def connect(self):
        try:
            loop = asyncio.get_event_loop()
            self._pool = await loop.run_in_executor(
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
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._pool.closeall)
            print("Pool de conexões fechado.")

    @contextlib.contextmanager
    def get_connection(self):
        if not self._pool:
            raise Exception("O pool de conexões não foi inicializado ou foi perdido.")
        
        conn = None
        retries = 3
        last_exception = None

        for attempt in range(retries):
            try:
                conn = self._pool.getconn()
                yield conn
                return
            except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
                last_exception = e
                print(f"AVISO: Erro de conexão com a DB (Tentativa {attempt + 1}/{retries}): {e}")
                
                if conn:
                    self._pool.putconn(conn, close=True)
                    conn = None
                
                time.sleep(1) 
            finally:
                if conn:
                    self._pool.putconn(conn)
        
        print("ERRO: Não foi possível restabelecer a conexão com a base de dados após várias tentativas.")
        raise last_exception

    def execute_query(self, query, params=None, fetch=None):
        """Executa uma query com a lógica de reconexão."""
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, params)
                if fetch == "one":
                    return cursor.fetchone()
                if fetch == "all":
                    return cursor.fetchall()
            conn.commit()

    def get_config_value(self, chave: str, default: str = None):
        resultado = self.execute_query("SELECT valor FROM configuracoes WHERE chave = %s", (chave,), fetch="one")
        return resultado[0] if resultado else default

    def set_config_value(self, chave: str, valor: str):
        self.execute_query(
            "INSERT INTO configuracoes (chave, valor) VALUES (%s, %s) ON CONFLICT (chave) DO UPDATE SET valor = EXCLUDED.valor",
            (chave, valor)
        )

