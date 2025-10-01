import discord
from discord.ext import commands
import contextlib
from typing import List
from utils.permissions import check_permission_level

# =================================================================================
# 1. VIEW DE APROVAÇÃO (BOTÕES)
# =================================================================================

class OrbApprovalView(discord.ui.View):
    def __init__(self):
        # O timeout=None torna a view persistente
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Verifica se o usuário tem permissão para interagir (Nível 2+)."""
        # A verificação de permissão é feita de forma manual aqui
        if interaction.user.guild_permissions.administrator:
            return True
        
        author_roles_ids = {str(role.id) for role in interaction.user.roles}
        admin_cog = interaction.client.get_cog('Admin')
        if not admin_cog:
            await interaction.response.send_message("Erro: Módulo Admin não encontrado.", ephemeral=True)
            return False

        for i in range(2, 5): # Nível 2 ou superior
            perm_key = f'perm_nivel_{i}'
            role_id_str = admin_cog.get_config_value(perm_key, '0')
            if role_id_str in author_roles_ids:
                return True
        
        await interaction.response.send_message("Você não tem permissão para aprovar ou recusar submissões.", ephemeral=True)
        return False

    @discord.ui.button(label="Aprovar", style=discord.ButtonStyle.success, custom_id="orb_approve")
    async def approve_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer() # Confirma a interação e permite mais tempo para processar

        submission_id = int(interaction.message.embeds[0].footer.text.split("ID: ")[1])
        orbes_cog = interaction.client.get_cog('Orbes')
        economia_cog = interaction.client.get_cog('Economia')

        submission = await orbes_cog.get_submission(submission_id)
        if not submission or submission['status'] != 'pendente':
            await interaction.followup.send("Esta submissão já foi processada.", ephemeral=True)
            return

        # Desativa os botões
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)

        # Lógica de Pagamento
        membro_ids = [int(id_str) for id_str in submission['membros'].split(',')]
        recompensa_individual = submission['valor_total'] // len(membro_ids)

        for user_id in membro_ids:
            await economia_cog.update_saldo(user_id, recompensa_individual, "recompensa_orbe", f"Orbe {submission['cor']} (ID: {submission_id})")

        # Atualiza o status no banco de dados
        await orbes_cog.update_submission_status(submission_id, 'aprovado')

        # Edita o embed original
        original_embed = interaction.message.embeds[0]
        original_embed.color = discord.Color.green()
        original_embed.title = f"✅ Submissão de Orbe APROVADA"
        original_embed.add_field(name="Aprovado por", value=interaction.user.mention, inline=False)
        original_embed.add_field(name="Recompensa Distribuída", value=f"`{recompensa_individual:,}` GC para cada um dos {len(membro_ids)} membros.".replace(',', '.'), inline=False)
        await interaction.message.edit(embed=original_embed)

        # Notifica o autor original
        autor = interaction.guild.get_member(submission['autor_id'])
        if autor:
            await autor.send(f"🎉 Sua submissão de orbe (ID: {submission_id}) foi **aprovada**!")


    @discord.ui.button(label="Recusar", style=discord.ButtonStyle.danger, custom_id="orb_deny")
    async def deny_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

        submission_id = int(interaction.message.embeds[0].footer.text.split("ID: ")[1])
        orbes_cog = interaction.client.get_cog('Orbes')
        
        submission = await orbes_cog.get_submission(submission_id)
        if not submission or submission['status'] != 'pendente':
            await interaction.followup.send("Esta submissão já foi processada.", ephemeral=True)
            return

        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)

        await orbes_cog.update_submission_status(submission_id, 'recusado')
        
        original_embed = interaction.message.embeds[0]
        original_embed.color = discord.Color.red()
        original_embed.title = f"❌ Submissão de Orbe RECUSADA"
        original_embed.add_field(name="Recusado por", value=interaction.user.mention, inline=False)
        await interaction.message.edit(embed=original_embed)

        autor = interaction.guild.get_member(submission['autor_id'])
        if autor:
            await autor.send(f"😔 Sua submissão de orbe (ID: {submission_id}) foi **recusada**. Contacte um administrador para mais detalhes.")

# =================================================================================
# 2. COG PRINCIPAL DE ORBES
# =================================================================================

class Orbes(commands.Cog):
    """Cog para gerir a submissão e aprovação de orbes."""
    def __init__(self, bot):
        self.bot = bot
        self.persistent_views_added = False

    @commands.Cog.listener()
    async def on_ready(self):
        """Adiciona a view persistente quando o bot estiver pronto."""
        if not self.persistent_views_added:
            self.bot.add_view(OrbApprovalView())
            self.persistent_views_added = True
            print("View de aprovação de orbes registada.")

    @contextlib.contextmanager
    def get_db_connection(self):
        conn = None
        try:
            conn = self.bot.db_pool.getconn()
            yield conn
        finally:
            if conn: self.bot.db_pool.putconn(conn)

    # Funções de DB
    async def get_submission(self, submission_id: int):
        with self.get_db_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
                cursor.execute("SELECT * FROM submissoes_orbe WHERE id = %s", (submission_id,))
                return cursor.fetchone()
    
    async def update_submission_status(self, submission_id: int, status: str):
        with self.get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("UPDATE submissoes_orbe SET status = %s WHERE id = %s", (status, submission_id))
            conn.commit()

    @commands.command(name='orbe')
    async def submeter_orbe(self, ctx, cor: str, membros: commands.Greedy[discord.Member]):
        """Submete uma captura de orbe para aprovação. Anexe o print à mensagem."""
        cor = cor.lower()
        valid_cores = ['verde', 'azul', 'roxa', 'dourada']
        if cor not in valid_cores:
            return await ctx.send(f"Cor de orbe inválida. Use uma das seguintes: `{', '.join(valid_cores)}`.")

        if not ctx.message.attachments:
            return await ctx.send("Você precisa de anexar um print (screenshot) da captura da orbe.")

        if not membros:
            membros = [ctx.author]
        elif ctx.author not in membros:
            membros.append(ctx.author)

        admin_cog = self.bot.get_cog('Admin')
        try:
            valor_total = int(admin_cog.get_config_value(f'orbe_{cor}', '0'))
        except (ValueError, TypeError):
            return await ctx.send("Erro ao obter o valor da orbe. A configuração pode estar em falta.")
        
        if valor_total == 0:
            return await ctx.send(f"A recompensa para a orbe `{cor}` não está configurada.")

        canal_aprovacao_id = int(admin_cog.get_config_value('canal_aprovacao', '0'))
        canal_aprovacao = self.bot.get_channel(canal_aprovacao_id)
        if not canal_aprovacao:
            return await ctx.send("O canal de aprovações não está configurado. Contacte um administrador.")

        membros_str = ",".join([str(m.id) for m in membros])
        
        with self.get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO submissoes_orbe (cor, valor_total, autor_id, membros, status) VALUES (%s, %s, %s, %s, 'pendente') RETURNING id",
                    (cor, valor_total, ctx.author.id, membros_str)
                )
                submission_id = cursor.fetchone()[0]
            conn.commit()

        # Envia para o canal de aprovações
        embed = discord.Embed(
            title=f"📝 Nova Submissão de Orbe - Pendente",
            description=f"**Autor:** {ctx.author.mention}\n**Orbe:** {cor.capitalize()}\n**Recompensa Total:** `{valor_total:,}` GC".replace(',', '.'),
            color=discord.Color.orange()
        )
        embed.add_field(name="Grupo", value="\n".join([m.mention for m in membros]), inline=False)
        embed.set_image(url=ctx.message.attachments[0].url)
        embed.set_footer(text=f"ID da Submissão: {submission_id}")

        await canal_aprovacao.send(embed=embed, view=OrbApprovalView())
        await ctx.send(f"✅ Submissão enviada com sucesso! A sua solicitação (ID: {submission_id}) está a aguardar aprovação.")

    @commands.group(name='config-orbe', invoke_without_command=True)
    @check_permission_level(4)
    async def config_orbe(self, ctx):
        """Grupo de comandos para configurar recompensas de orbes. (Nível 4+)"""
        await ctx.send("Use `!config-orbe valor <cor> <valor_total>`.")

    @config_orbe.command(name='valor')
    @check_permission_level(4)
    async def config_orbe_valor(self, ctx, cor: str, valor: int):
        """Define o valor total de recompensa para uma cor de orbe."""
        cor = cor.lower()
        valid_cores = ['verde', 'azul', 'roxa', 'dourada']
        if cor not in valid_cores:
            return await ctx.send(f"Cor inválida. Use uma das seguintes: `{', '.join(valid_cores)}`.")
        if valor < 0: return

        self.bot.get_cog('Admin').set_config_value(f'orbe_{cor}', str(valor))
        await ctx.send(f"✅ O valor da orbe `{cor}` foi definido para `{valor:,} GC`.".replace(',', '.'))


async def setup(bot):
    await bot.add_cog(Orbes(bot))
