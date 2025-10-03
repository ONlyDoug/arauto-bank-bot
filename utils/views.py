import discord
from utils.permissions import check_permission_level
from datetime import datetime, timedelta

# --- VISTA PERSISTENTE PARA APROVAÇÃO DE ORBE ---
class OrbeAprovacaoView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def handle_interaction(self, interaction: discord.Interaction, novo_status: str):
        perm_check = await check_permission_level(2).predicate(interaction)
        if not perm_check:
            await interaction.response.send_message("Você não tem permissão para aprovar/recusar submissões.", ephemeral=True)
            return

        submissao_id = None
        valor_total = 0
        membros_ids_str = ""
        original_embed = interaction.message.embeds[0]

        try:
            with self.bot.db_manager.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("UPDATE submissoes_orbe SET status = %s WHERE message_id = %s RETURNING id, valor_total, membros", (novo_status, interaction.message.id))
                    result = cursor.fetchone()
                    if result:
                        submissao_id, valor_total, membros_ids_str = result
                conn.commit()

            if submissao_id and novo_status == 'aprovado':
                membros_ids = [int(id) for id in membros_ids_str.split(',')]
                recompensa_individual = valor_total // len(membros_ids)
                
                economia_cog = self.bot.get_cog('Economia')
                for user_id in membros_ids:
                    await economia_cog.depositar(user_id, recompensa_individual, f"Recompensa de Orbe Aprovada (ID: {submissao_id})")

            status_texto = "✅ Aprovada" if novo_status == "aprovado" else "❌ Recusada"
            cor = discord.Color.green() if novo_status == "aprovado" else discord.Color.red()
            
            new_embed = discord.Embed(title=f"Submissão de Orbe - {status_texto}", description=original_embed.description, color=cor)
            if original_embed.image.url:
              new_embed.set_image(url=original_embed.image.url)
            new_embed.set_footer(text=f"Processado por {interaction.user.display_name}")
            
            self.stop()
            for item in self.children:
                item.disabled = True
            await interaction.message.edit(embed=new_embed, view=self)
            await interaction.response.send_message(f"Submissão marcada como '{novo_status}'.", ephemeral=True)
            
        except Exception as e:
            print(f"Erro ao processar aprovação de orbe: {e}")
            await interaction.response.send_message("Ocorreu um erro ao processar esta ação.", ephemeral=True)

    @discord.ui.button(label="Aprovar", style=discord.ButtonStyle.success, custom_id="aprovar_orbe")
    async def aprovar_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_interaction(interaction, "aprovado")

    @discord.ui.button(label="Recusar", style=discord.ButtonStyle.danger, custom_id="recusar_orbe")
    async def recusar_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_interaction(interaction, "recusado")

# --- VISTA PERSISTENTE PARA APROVAÇÃO DE TAXA ---
class TaxaPrataView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def handle_interaction(self, interaction: discord.Interaction, novo_status: str):
        perm_check = await check_permission_level(2).predicate(interaction)
        if not perm_check:
            await interaction.response.send_message("Você não tem permissão para aprovar/recusar pagamentos.", ephemeral=True)
            return

        user_id = None
        original_embed = interaction.message.embeds[0]
        
        try:
            with self.bot.db_manager.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT user_id FROM submissoes_taxa WHERE message_id = %s", (interaction.message.id,))
                    result = cursor.fetchone()
                    if result:
                        user_id = result[0]
                        cursor.execute("UPDATE submissoes_taxa SET status = %s WHERE message_id = %s", (novo_status, interaction.message.id))
                        if novo_status == "aprovado":
                            cursor.execute("UPDATE taxas SET status = 'pago', data_vencimento = %s WHERE user_id = %s", (datetime.now().date() + timedelta(days=7), user_id))
                    conn.commit()

            if user_id:
                guild = interaction.guild
                membro = guild.get_member(user_id)
                admin_cog = self.bot.get_cog('Admin')
                cargo_membro_id = int(self.bot.db_manager.get_config_value('cargo_membro', '0'))
                cargo_inadimplente_id = int(self.bot.db_manager.get_config_value('cargo_inadimplente', '0'))
                
                cargo_membro = guild.get_role(cargo_membro_id)
                cargo_inadimplente = guild.get_role(cargo_inadimplente_id)

                if novo_status == "aprovado" and membro and cargo_membro and cargo_inadimplente:
                    await membro.add_roles(cargo_membro, reason="Pagamento de taxa aprovado")
                    await membro.remove_roles(cargo_inadimplente, reason="Pagamento de taxa aprovado")

                status_texto = "✅ Aprovado" if novo_status == "aprovado" else "❌ Recusado"
                cor = discord.Color.green() if novo_status == "aprovado" else discord.Color.red()
                
                new_embed = discord.Embed(title=f"Pagamento de Taxa em Prata - {status_texto}", description=original_embed.description, color=cor)
                if original_embed.image.url:
                    new_embed.set_image(url=original_embed.image.url)
                new_embed.set_footer(text=f"Processado por {interaction.user.display_name}")
                
                self.stop()
                for item in self.children:
                    item.disabled = True
                await interaction.message.edit(embed=new_embed, view=self)
                await interaction.response.send_message(f"Submissão marcada como '{novo_status}'.", ephemeral=True)
        except Exception as e:
            print(f"Erro ao processar aprovação de taxa: {e}")
            await interaction.response.send_message("Ocorreu um erro ao processar esta ação.", ephemeral=True)

    @discord.ui.button(label="Aprovar", style=discord.ButtonStyle.success, custom_id="aprovar_taxa_prata")
    async def aprovar_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_interaction(interaction, "aprovado")

    @discord.ui.button(label="Recusar", style=discord.ButtonStyle.danger, custom_id="recusar_taxa_prata")
    async def recusar_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_interaction(interaction, "recusado")

