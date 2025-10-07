import asyncpg
import asyncio

class DatabaseManager:
    def __init__(self, dsn: str, min_conn: int = 2, max_conn: int = 10):
        self._dsn = dsn
        self._min_conn = min_conn
        self._max_conn = max_conn
        self._pool = None

    async def connect(self):
        """Inicializa o pool de conexões com asyncpg."""
        try:
            self._pool = await asyncpg.create_pool(
                dsn=self._dsn,
                min_size=self._min_conn,
                max_size=self._max_conn
            )
            print("Pool de conexões com a base de dados (asyncpg) inicializado com sucesso.")
        except Exception as e:
            print(f"ERRO CRÍTICO ao inicializar o pool de conexões: {e}")
            raise

    async def close(self):
        """Fecha o pool de conexões."""
        if self._pool:
            await self._pool.close()
            print("Pool de conexões fechado.")

    async def execute_query(self, query, params=None, fetch=None):
        """Executa uma query de forma assíncrona."""
        if not self._pool:
            raise Exception("O pool de conexões não foi inicializado.")
            
        async with self._pool.acquire() as conn:
            # asyncpg usa transações por padrão em blocos 'with', garantindo atomicidade.
            if fetch == "one":
                return await conn.fetchrow(query, *params if params else [])
            elif fetch == "all":
                return await conn.fetch(query, *params if params else [])
            else:
                await conn.execute(query, *params if params else [])
                return None

    async def get_config_value(self, chave: str, default: str = None):
        """Obtém um único valor de configuração da base de dados."""
        # asyncpg usa $1, $2 como placeholders
        resultado = await self.execute_query(
            "SELECT valor FROM configuracoes WHERE chave = $1",
            (chave,),
            fetch="one"
        )
        return resultado['valor'] if resultado else default

    async def get_all_configs(self, chaves: list):
        """Busca múltiplos valores de configuração numa única query."""
        if not chaves:
            return {}
            
        query = "SELECT chave, valor FROM configuracoes WHERE chave = ANY($1::TEXT[])"
        resultados = await self.execute_query(query, (chaves,), fetch="all")
        return {rec['chave']: rec['valor'] for rec in resultados}

    async def set_config_value(self, chave: str, valor: str):
        """Define um único valor de configuração na base de dados."""
        await self.execute_query(
            "INSERT INTO configuracoes (chave, valor) VALUES ($1, $2) ON CONFLICT (chave) DO UPDATE SET valor = EXCLUDED.valor",
            (chave, valor)
        )

