import discord
from discord.ext import commands

def check_permission_level(level: int):
    """
    Verificador de permissão que funciona tanto para comandos (Context)
    quanto para interações de componentes (Interaction).
    """
    async def predicate(ctx):
        # Determina se é um Contexto de Comando ou uma Interação
        is_interaction = isinstance(ctx, discord.Interaction)
        
        user = ctx.user if is_interaction else ctx.author
        
        # O Administrador do servidor sempre tem permissão
        if user.guild_permissions.administrator:
            return True
            
        author_roles_ids = {str(role.id) for role in user.roles}
        
        # Acesso ao Cog Admin para ler a configuração
        admin_cog = ctx.bot.get_cog('Admin')
        if not admin_cog:
            print("AVISO: O Cog 'Admin' não foi encontrado para verificação de permissão.")
            return False

        # Verifica se o usuário tem algum cargo com nível de permissão igual ou superior
        for i in range(level, 5):
            perm_key = f'perm_nivel_{i}'
            role_id_str = admin_cog.get_config_value(perm_key, '0')
            if role_id_str in author_roles_ids:
                return True

        # Se for uma interação, envia uma resposta efêmera. Se for comando, envia uma mensagem normal.
        if is_interaction:
            await ctx.response.send_message("Você não tem permissão para usar este comando.", ephemeral=True, delete_after=10)
        else:
            await ctx.send("Você não tem permissão para usar este comando.", delete_after=10)
            
        return False
    
    # Retorna o decorador de verificação apropriado
    if isinstance(level, int):
        # Para comandos de barra (não usados aqui, mas bom ter)
        # return discord.app_commands.check(predicate)
        # Para comandos de prefixo
        return commands.check(predicate)
    else: # Se for usado diretamente numa interação
        return predicate

