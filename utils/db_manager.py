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
            # psycopg2 não é async, então executamos num executor para não bloquear o loop de eventos
            loop = asyncio.get_event_loop()
            self._pool = await loop.run_in_executor(
                None, 
                lambda: psycopg2.pool.SimpleConnectionPool(self._min_conn, self._max_conn, dsn=self._dsn)
            )
            if self._pool:
                print("Pool de conexões com a base de dados inicializado com sucesso.")
        except Exception as e:
            print(f"ERRO CRÍTICO ao inicializar o pool de conexões: {e}")
            raise e # Propaga o erro para parar a inicialização do bot se a DB falhar

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
                # Se a operação foi bem-sucedida, sai do loop
                return
            except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
                last_exception = e
                print(f"AVISO: Erro de conexão com a DB (Tentativa {attempt + 1}/{retries}): {e}")
                
                # Fecha a conexão quebrada, se houver uma
                if conn:
                    self._pool.putconn(conn, close=True)
                    conn = None
                
                # Pausa antes de tentar novamente
                time.sleep(1) 
            finally:
                # Garante que a conexão é devolvida ao pool se não foi fechada
                if conn:
                    self._pool.putconn(conn)
        
        # Se todas as tentativas falharem, levanta a última exceção
        print("ERRO: Não foi possível restabelecer a conexão com a base de dados após várias tentativas.")
        raise last_exception

    # --- Funções de Configuração Centralizadas ---
    def get_config_value(self, chave: str, default: str = None):
        """Busca um valor de configuração da base de dados de forma segura."""
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT valor FROM configuracoes WHERE chave = %s", (chave,))
                resultado = cursor.fetchone()
        return resultado[0] if resultado else default

    def set_config_value(self, chave: str, valor: str):
        """Define um valor de configuração na base de dados de forma segura."""
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO configuracoes (chave, valor) VALUES (%s, %s) ON CONFLICT (chave) DO UPDATE SET valor = EXCLUDED.valor",
                    (chave, valor)
                )
            conn.commit()

