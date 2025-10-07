from discord.ext import commands

def check_permission_level(level: int):
    async def predicate(ctx_or_interaction):
        if isinstance(ctx_or_interaction, commands.Context):
            user = ctx_or_interaction.author
            channel = ctx_or_interaction.channel
            bot = ctx_or_interaction.bot
        else: # Is an Interaction
            user = ctx_or_interaction.user
            channel = ctx_or_interaction.channel
            bot = ctx_or_interaction.client

        if user.guild_permissions.administrator:
            return True
        
        author_roles_ids = {str(role.id) for role in user.roles}
        
        for i in range(level, 5):
            perm_key = f'perm_nivel_{i}'
            db_manager = bot.db_manager
            role_id_str = await db_manager.get_config_value(perm_key, '0')
            if role_id_str in author_roles_ids:
                return True
        
        if isinstance(ctx_or_interaction, commands.Context):
            # Não enviamos mais mensagens de erro daqui para evitar spam. O check global já trata disso.
            pass
        else:
            await ctx_or_interaction.response.send_message("Você não tem permissão para executar esta ação.", ephemeral=True, delete_after=10)

        return False
    
    return commands.check(predicate)
