import discord
from discord.ext import commands
from utils.permissions import check_permission_level

class OrbeAprovacaoView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def handle_interaction(self, interaction: discord.Interaction, novo_status: str):
        if not await check_permission_level(2).predicate(interaction):
            return 

        db_manager = self.bot.db_manager
        
        try:
            submissao = await db_manager.execute_query(
                "SELECT autor_id, membros, valor_total FROM submissoes_orbe WHERE message_id = $1",
                interaction.message.id,
                fetch="one"
            )
            if not submissao:
                return await interaction.response.send_message("Submissão não encontrada na base de dados.", ephemeral=True)

            autor_id, membros_str, valor_total = submissao['autor_id'], submissao['membros'], submissao['valor_total']
            membros_ids = [int(id_str) for id_str in membros_str.split(',')]
            
            if novo_status == "aprovado":
                recompensa_individual = valor_total // len(membros_ids)
                economia_cog = self.bot.get_cog('Economia')
                for user_id in membros_ids:
                    await economia_cog.depositar(user_id, recompensa_individual, f"Recompensa de Orbe aprovada por {interaction.user.name}")
            
            await db_manager.execute_query(
                "UPDATE submissoes_orbe SET status = $1 WHERE message_id = $2",
                novo_status, interaction.message.id
            )

            embed = interaction.message.embeds[0]
            if novo_status == "aprovado":
                embed.color = discord.Color.green()
                embed.title = "✅ Submissão de Orbe APROVADA"
                embed.set_footer(text=f"Aprovado por: {interaction.user.display_name}")
            else:
                embed.color = discord.Color.red()
                embed.title = "❌ Submissão de Orbe RECUSADA"
                embed.set_footer(text=f"Recusado por: {interaction.user.display_name}")
            
            for item in self.children:
                item.disabled = True
            await interaction.message.edit(embed=embed, view=self)
            await interaction.response.defer()

        except Exception as e:
            print(f"Erro ao processar aprovação de orbe: {e}")
            await interaction.response.send_message("Ocorreu um erro ao processar a sua ação.", ephemeral=True)

    @discord.ui.button(label="Aprovar", style=discord.ButtonStyle.success, custom_id="aprovar_orbe")
    async def aprovar_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_interaction(interaction, "aprovado")

    @discord.ui.button(label="Recusar", style=discord.ButtonStyle.danger, custom_id="recusar_orbe")
    async def recusar_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_interaction(interaction, "recusado")


class TaxaPrataView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def handle_interaction(self, interaction: discord.Interaction, novo_status: str):
        if not await check_permission_level(2).predicate(interaction):
            return

        db_manager = self.bot.db_manager
        
        try:
            submissao = await db_manager.execute_query(
                "SELECT user_id FROM submissoes_taxa WHERE message_id = $1",
                interaction.message.id,
                fetch="one"
            )
            if not submissao:
                return await interaction.response.send_message("Submissão não encontrada.", ephemeral=True)

            user_id = submissao['user_id']
            membro = interaction.guild.get_member(user_id)
            
            if novo_status == "aprovado" and membro:
                taxas_cog = self.bot.get_cog('Taxas')
                # A função regularizar membro precisa dos configs para funcionar
                configs = await db_manager.get_all_configs(['cargo_membro', 'cargo_inadimplente'])
                await taxas_cog.regularizar_membro(membro, configs)
                await db_manager.execute_query("UPDATE taxas SET status = 'pago_prata' WHERE user_id = $1", user_id)

            await db_manager.execute_query(
                "UPDATE submissoes_taxa SET status = $1 WHERE message_id = $2",
                novo_status, interaction.message.id
            )

            embed = interaction.message.embeds[0]
            if novo_status == "aprovado":
                embed.color = discord.Color.green()
                embed.title = "✅ Pagamento de Taxa (Prata) APROVADO"
                embed.set_footer(text=f"Aprovado por: {interaction.user.display_name}")
            else:
                embed.color = discord.Color.red()
                embed.title = "❌ Pagamento de Taxa (Prata) RECUSADO"
                embed.set_footer(text=f"Recusado por: {interaction.user.display_name}")
            
            for item in self.children:
                item.disabled = True
            await interaction.message.edit(embed=embed, view=self)
            await interaction.response.defer()

        except Exception as e:
            print(f"Erro ao processar aprovação de taxa prata: {e}")
            await interaction.response.send_message("Ocorreu um erro ao processar a sua ação.", ephemeral=True)

    @discord.ui.button(label="Aprovar", style=discord.ButtonStyle.success, custom_id="aprovar_taxa_prata")
    async def aprovar_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_interaction(interaction, "aprovado")

    @discord.ui.button(label="Recusar", style=discord.ButtonStyle.danger, custom_id="recusar_taxa_prata")
    async def recusar_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_interaction(interaction, "recusado")
