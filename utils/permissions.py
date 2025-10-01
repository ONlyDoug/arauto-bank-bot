from discord.ext import commands

def get_config_value_sync(bot, chave: str, default: str = None):
    """
    Versão síncrona para obter um valor de configuração.
    Usado em 'checks' que não podem ser assíncronos.
    ATENÇÃO: Bloqueia o thread enquanto espera pela conexão. Usar com moderação.
    """
    conn = None
    try:
        conn = bot.db_pool.getconn()
        with conn.cursor() as cursor:
            cursor.execute("SELECT valor FROM configuracoes WHERE chave = %s", (chave,))
            resultado = cursor.fetchone()
    finally:
        if conn:
            bot.db_pool.putconn(conn)
    return resultado[0] if resultado else default

def check_permission_level(level: int):
    """
    Decorator de verificação que valida se o autor do comando tem o nível
    de permissão necessário ou superior.
    """
    async def predicate(ctx):
        # Administradores do servidor têm acesso a tudo
        if ctx.author.guild_permissions.administrator:
            return True
        
        author_roles_ids = {str(role.id) for role in ctx.author.roles}
        
        # Verifica o nível do autor e todos os níveis superiores
        for i in range(level, 5): # Níveis vão de 1 a 4
            perm_key = f'perm_nivel_{i}'
            
            # Obtém o ID do cargo associado a este nível de permissão
            role_id_str = get_config_value_sync(ctx.bot, perm_key, '0')
            
            # Se o autor tiver o cargo, a verificação passa
            if role_id_str in author_roles_ids:
                return True
                
        # Se o loop terminar, o autor não tem nenhum dos cargos necessários
        await ctx.send("Você não tem permissão para usar este comando.", ephemeral=True, delete_after=10)
        return False
        
    return commands.check(predicate)
