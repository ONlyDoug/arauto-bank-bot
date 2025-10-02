from discord.ext import commands

def check_permission_level(level: int):
    """
    Verificador de permissão personalizado baseado em cargos configurados na base de dados.
    Níveis mais altos herdam as permissões dos níveis inferiores.
    """
    async def predicate(ctx):
        # Administradores do servidor têm acesso a tudo
        if ctx.author.guild_permissions.administrator:
            return True

        # Obtém o cog de Admin para aceder às funções de BD
        admin_cog = ctx.bot.get_cog('Admin')
        if not admin_cog:
            # Fallback de segurança se o cog não for encontrado
            await ctx.send("Erro de configuração de permissões.", ephemeral=True, delete_after=10)
            return False

        author_roles_ids = {str(role.id) for role in ctx.author.roles}

        # Verifica se o autor tem um cargo de nível `level` ou superior
        for i in range(level, 5):  # Itera do nível exigido até o nível máximo (4)
            perm_key = f'perm_nivel_{i}'
            role_id_str = admin_cog.get_config_value(perm_key, '0')
            
            if role_id_str in author_roles_ids:
                return True # Permissão concedida

        # Se o loop terminar, o usuário não tem nenhum cargo de permissão adequado
        await ctx.send("Você não tem permissão para usar este comando.", ephemeral=True, delete_after=10)
        return False
    
    return commands.check(predicate)

