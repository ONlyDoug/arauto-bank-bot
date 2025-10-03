import psycopg2
import psycopg2.pool
import contextlib
import time
import asyncio

class DatabaseManager:
    """
    Uma classe para gerir o pool de conexões com a base de dados de forma resiliente.
    """
    def __init__(self, dsn: str, min_conn: int = 1, max_conn: int = 10):
        self._dsn = dsn
        self._min_conn = min_conn
        self._max_conn = max_conn
        self._pool = None

    async def connect(self):
        """Inicializa o pool de conexões de forma assíncrona."""
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
        """Fecha o pool de conexões."""
        if self._pool:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._pool.closeall)
            print("Pool de conexões fechado.")

    @contextlib.contextmanager
    def get_connection(self):
        """
        Obtém uma conexão do pool com lógica de retry para lidar com desconexões.
        """
        if not self._pool:
            raise Exception("O pool de conexões não foi inicializado. Chame connect() primeiro.")
        
        conn = None
        retries = 3
        last_exception = None

        for attempt in range(retries):
            try:
                conn = self._pool.getconn()
                yield conn
                # Se o bloco 'with' for concluído com sucesso, sai do loop
                return
            except psycopg2.OperationalError as e:
                last_exception = e
                print(f"AVISO: Erro de conexão com a DB (Tentativa {attempt + 1}/{retries}): {e}")
                
                # Devolve a conexão quebrada ao pool para ser fechada
                if conn:
                    self._pool.putconn(conn, close=True)
                    conn = None # Garante que não tentemos devolver a mesma conexão duas vezes

                time.sleep(1) # Espera um segundo antes de tentar novamente
            finally:
                # Se uma conexão válida foi usada, devolve-a ao pool
                if conn:
                    self._pool.putconn(conn)
        
        # Se todas as tentativas falharem, levanta a última exceção
        raise last_exception
