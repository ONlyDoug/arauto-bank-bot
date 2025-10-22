import discord
from discord.ext import commands
from utils.permissions import check_permission_level

class OrbeAprovacaoView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def handle_interaction(self, interaction: discord.Interaction, novo_status: str):
        # A verificação de permissão é a primeira coisa a fazer
        if not await check_permission_level(2).predicate(interaction):
            return 

        # Adiar a resposta da interação para evitar o erro "Unknown Interaction"
        await interaction.response.defer()
        
        db_manager = self.bot.db_manager
        
        try:
            submissao = await db_manager.execute_query(
                "SELECT autor_id, membros, valor_total FROM submissoes_orbe WHERE message_id = $1 AND status = 'pendente'",
                interaction.message.id,
                fetch="one"
            )
            if not submissao:
                # Se não encontrar, é porque já foi tratada. Apenas edita a mensagem.
                embed = interaction.message.embeds[0]
                embed.description += "\n\n**Esta submissão já foi tratada.**"
                for item in self.children: item.disabled = True
                await interaction.message.edit(embed=embed, view=self)
                return

            autor_id, membros_str, valor_total = submissao['autor_id'], submissao['membros'], submissao['valor_total']
            membros_ids = [int(id_str) for id_str in membros_str.split(',')]
            
            recompensa_individual = 0 # Inicializa a variável
            if novo_status == "aprovado":
                recompensa_individual = valor_total // len(membros_ids)
                economia_cog = self.bot.get_cog('Economia')
                for user_id in membros_ids:
                    await economia_cog.transferir_do_tesouro(user_id, recompensa_individual, f"Recompensa de Orbe aprovada por {interaction.user.name}")
            
            await db_manager.execute_query(
                "UPDATE submissoes_orbe SET status = $1 WHERE message_id = $2",
                novo_status, interaction.message.id
            )

            embed = interaction.message.embeds[0]
            if novo_status == "aprovado":
                embed.color = discord.Color.green()
                embed.title = "✅ Submissão de Orbe APROVADA"
                embed.set_footer(text=f"Aprovado por: {interaction.user.display_name}")
            else: # Recusado
                embed.color = discord.Color.red()
                embed.title = "❌ Submissão de Orbe RECUSADA"
                embed.set_footer(text=f"Recusado por: {interaction.user.display_name}")
            
            for item in self.children:
                item.disabled = True
            await interaction.message.edit(embed=embed, view=self)
            
            # --- ATUALIZAÇÃO IMPORTANTE ---
            # Enviar DM para o autor da submissão
            autor_da_submissao = self.bot.get_user(autor_id)
            if autor_da_submissao:
                try:
                    if novo_status == "aprovado":
                        await autor_da_submissao.send(f"🎉 Boas notícias! A sua submissão de orbe foi **APROVADA**! Você e o seu grupo receberam **{recompensa_individual}** moedas cada um.")
                    else: # Recusado
                        await autor_da_submissao.send(f"😕 A sua submissão de orbe foi **RECUSADA** por um staff. Se achar que foi um erro, fale com a liderança.")
                except discord.Forbidden:
                    print(f"Não foi possível enviar DM para o utilizador {autor_id}. Provavelmente tem as DMs desativadas.")

        except Exception as e:
            print(f"Erro ao processar aprovação de orbe: {e}")
            await interaction.followup.send("Ocorreu um erro ao processar a sua ação.", ephemeral=True)

    @discord.ui.button(label="Aprovar", style=discord.ButtonStyle.success, custom_id="aprovar_orbe")
    async def aprovar_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_interaction(interaction, "aprovado")

    @discord.ui.button(label="Recusar", style=discord.ButtonStyle.danger, custom_id="recusar_orbe")
    async def recusar_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_interaction(interaction, "recusado")


# --- ATUALIZAÇÃO CRÍTICA NA TaxaPrataView ---
class TaxaPrataView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def handle_interaction(self, interaction: discord.Interaction, novo_status: str):
        if not await check_permission_level(2).predicate(interaction): return
        await interaction.response.defer()
        db_manager = self.bot.db_manager

        try:
            # Busca a submissão PENDENTE pelo message_id
            submissao = await db_manager.execute_query(
                "SELECT id, user_id FROM submissoes_taxa WHERE message_id = $1 AND status = 'pendente'",
                interaction.message.id, fetch="one"
            )
            if not submissao:
                # Já tratada, edita a mensagem e sai
                embed = interaction.message.embeds[0]
                embed.description = (embed.description or "") + "\n\n**Esta submissão já foi tratada.**"
                for item in self.children: item.disabled = True
                await interaction.edit_original_response(embed=embed, view=self)
                return

            submissao_id = submissao['id']
            user_id = submissao['user_id']
            membro = interaction.guild.get_member(user_id)

            # Marca a submissão como processada PRIMEIRO para evitar dupla execução
            await db_manager.execute_query(
                "UPDATE submissoes_taxa SET status = $1 WHERE id = $2",
                novo_status, submissao_id
            )

            if novo_status == "aprovado" and membro:
                taxas_cog = self.bot.get_cog('Taxas')
                configs = await db_manager.get_all_configs(['cargo_membro', 'cargo_inadimplente'])
                # Atualiza status na tabela principal de taxas
                await db_manager.execute_query(
                    "INSERT INTO taxas (user_id, status_ciclo) VALUES ($1, 'PAGO_ATRASADO') ON CONFLICT (user_id) DO UPDATE SET status_ciclo = 'PAGO_ATRASADO'",
                    user_id
                )
                # Restaura os cargos
                await taxas_cog.regularizar_membro(membro, configs)

            # Edita o embed de aprovação
            embed = interaction.message.embeds[0]
            embed.color = discord.Color.green() if novo_status == "aprovado" else discord.Color.red()
            embed.title = f"{'✅' if novo_status == 'aprovado' else '❌'} Pagamento (Prata) {novo_status.upper()}"
            embed.set_footer(text=f"{novo_status.capitalize()} por: {interaction.user.display_name}")
            for item in self.children: item.disabled = True
            await interaction.edit_original_response(embed=embed, view=self)

            # Envia DM
            if membro:
                try:
                    msg = f"🎉 Seu comprovativo (prata) foi **APROVADO**! Acesso restaurado." if novo_status == "aprovado" else f"😕 Seu comprovativo (prata) foi **RECUSADO** por {interaction.user.mention}. Contacte a staff."
                    await membro.send(msg)
                except Exception as e: print(f"Falha DM {user_id}: {e}")

        except Exception as e:
            print(f"Erro handle_interaction TaxaPrataView: {e}")
            await interaction.followup.send("❌ Erro ao processar.", ephemeral=True)

    @discord.ui.button(label="Aprovar", style=discord.ButtonStyle.success, custom_id="aprovar_taxa_prata")
    async def aprovar_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_interaction(interaction, "aprovado")

    @discord.ui.button(label="Recusar", style=discord.ButtonStyle.danger, custom_id="recusar_taxa_prata")
    async def recusar_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_interaction(interaction, "recusado")
