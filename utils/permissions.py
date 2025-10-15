from discord.ext import commands
from discord import app_commands  # <-- Adicione esta linha no topo
import discord  # Adicione esta também, para o tipo da 'interaction'

def check_permission_level(level: int):
    async def predicate(ctx_or_interaction):
        if isinstance(ctx_or_interaction, commands.Context):
            user = ctx_or_interaction.author
            bot = ctx_or_interaction.bot
        else: # Is an Interaction
            user = ctx_or_interaction.user
            bot = ctx_or_interaction.client

        if user.guild_permissions.administrator:
            return True
        
        author_roles_ids = {str(role.id) for role in user.roles}
        db_manager = bot.db_manager

        for i in range(level, 5):
            perm_key = f'perm_nivel_{i}'
            # Agora buscamos uma lista de IDs, separada por vírgulas
            role_ids_str = await db_manager.get_config_value(perm_key, '')
            if role_ids_str:
                allowed_role_ids = set(role_ids_str.split(','))
                # Se qualquer um dos cargos do autor estiver na lista de permissões, retorna True
                if not author_roles_ids.isdisjoint(allowed_role_ids):
                    return True
        
        if isinstance(ctx_or_interaction, commands.Context):
            pass # O erro é tratado globalmente
        else:
            await ctx_or_interaction.response.send_message("Você não tem permissão para executar esta ação.", ephemeral=True, delete_after=10)

        return False
    
    return commands.check(predicate)

# --- NOVO CÓDIGO A ADICIONAR ---
# Verificador de permissões específico para Comandos de Barra (/)
def app_check_permission_level(level: int):
    async def predicate(interaction: discord.Interaction) -> bool:
        user = interaction.user
        bot = interaction.client

        if user.guild_permissions.administrator:
            return True
        
        author_roles_ids = {str(role.id) for role in user.roles}
        db_manager = bot.db_manager

        for i in range(level, 5):
            perm_key = f'perm_nivel_{i}'
            role_ids_str = await db_manager.get_config_value(perm_key, '')
            if role_ids_str:
                allowed_role_ids = set(role_ids_str.split(','))
                if not author_roles_ids.isdisjoint(allowed_role_ids):
                    return True
        
        # Se a verificação falhar, envia uma mensagem e retorna False
        await interaction.response.send_message("Você não tem permissão para usar este comando.", ephemeral=True, delete_after=10)
        return False
    
    return app_commands.check(predicate)
