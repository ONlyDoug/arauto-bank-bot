import discord
from discord.ext import commands
import contextlib
import json
from utils.permissions import check_permission_level

class OrbApprovalView(discord.ui.View):
    def __init__(self, bot, submission_id):
        super().__init__(timeout=None)
        self.bot = bot
        self.submission_id = submission_id

    @contextlib.contextmanager
    def get_db_connection(self):
        conn = None
        try:
            conn = self.bot.db_pool.getconn()
            yield conn
        finally:
            if conn: self.bot.db_pool.putconn(conn)

    @discord.ui.button(label="Aprovar", style=discord.ButtonStyle.success, custom_id=f"approve_orb")
    async def approve_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # A verificação de permissão é feita no interaction check
        with self.get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT membros, valor_total, autor_id, cor FROM submissoes_orbe WHERE id = %s AND status = 'pendente'", (self.submission_id,))
                submissao = cursor.fetchone()
                
                if not submissao:
                    await interaction.response.send_message("Esta submissão já foi processada.", ephemeral=True)
                    return

                membros_json, valor_total, autor_id, cor = submissao
                membros_ids = json.loads(membros_json)
                recompensa_individual = valor_total // len(membros_ids)

                economia_cog = self.bot.get_cog('Economia')
                for membro_id in membros_ids:
                    await economia_cog.update_saldo(membro_id, recompensa_individual, "recompensa_orbe", f"Orbe {cor.capitalize()} (ID Sub: {self.submission_id})")

                cursor.execute("UPDATE submissoes_orbe SET status = 'aprovado' WHERE id = %s", (self.submission_id,))
            conn.commit()

        original_embed = interaction.message.embeds[0]
        original_embed.color = discord.Color.green()
        original_embed.set_footer(text=f"Aprovado por {interaction.user.name}")
        
        self.clear_items()
        await interaction.message.edit(embed=original_embed, view=self)
        await interaction.response.send_message(f"✅ Submissão de orbe {self.submission_id} aprovada.", ephemeral=True)

    @discord.ui.button(label="Recusar", style=discord.ButtonStyle.danger, custom_id=f"deny_orb")
    async def deny_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        with self.get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("UPDATE submissoes_orbe SET status = 'recusado' WHERE id = %s AND status = 'pendente'", (self.submission_id,))
                if cursor.rowcount == 0:
                    await interaction.response.send_message("Esta submissão já foi processada.", ephemeral=True)
                    return
            conn.commit()

        original_embed = interaction.message.embeds[0]
        original_embed.color = discord.Color.red()
        original_embed.set_footer(text=f"Recusado por {interaction.user.name}")

        self.clear_items()
        await interaction.message.edit(embed=original_embed, view=self)
        await interaction.response.send_message(f"❌ Submissão de orbe {self.submission_id} recusada.", ephemeral=True)
        
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Usando a função de verificação de permissão
        author_roles_ids = {str(role.id) for role in interaction.user.roles}
        admin_cog = self.bot.get_cog('Admin')
        
        for i in range(2, 5): # Nível 2 ou superior pode aprovar
            perm_key = f'perm_nivel_{i}'
            role_id_str = admin_cog.get_config_value(perm_key, '0')
            if role_id_str in author_roles_ids:
                return True
        
        await interaction.response.send_message("Você não tem permissão para aprovar/recusar submissões.", ephemeral=True)
        return False

class Orbes(commands.Cog):
    """Cog para gerir a submissão e aprovação de orbes."""
    def __init__(self, bot):
        self.bot = bot
        self.bot.add_view(OrbApprovalView(self.bot, submission_id=0)) # Registar a view

    @contextlib.contextmanager
    def get_db_connection(self):
        conn = None
        try:
            conn = self.bot.db_pool.getconn()
            yield conn
        finally:
            if conn: self.bot.db_pool.putconn(conn)

    @commands.command(name='config-orbe')
    @check_permission_level(4)
    async def config_orbe(self, ctx, cor: str, valor: int):
        cor = cor.lower()
        if cor not in ['verde', 'azul', 'roxa', 'dourada']:
            return await ctx.send("Cor inválida. Use: verde, azul, roxa, dourada.")
        if valor < 0:
            return await ctx.send("O valor não pode ser negativo.")
            
        self.bot.get_cog('Admin').set_config_value(f'orbe_{cor}', str(valor))
        await ctx.send(f"✅ O valor da orbe **{cor}** foi definido para `{valor} GC`.")

    @commands.command(name='orbe')
    async def submeter_orbe(self, ctx, cor: str, membros: commands.Greedy[discord.Member]):
        cor = cor.lower()
        if cor not in ['verde', 'azul', 'roxa', 'dourada']:
            return await ctx.send("Cor inválida. Use: verde, azul, roxa, dourada.")
        
        if not ctx.message.attachments:
            return await ctx.send("Você precisa de anexar um print (screenshot) da captura!")

        participantes = list(set([ctx.author] + membros))
        if not participantes:
            return await ctx.send("Você precisa de mencionar pelo menos um membro participante (ou será apenas você).")

        valor_total = int(self.bot.get_cog('Admin').get_config_value(f'orbe_{cor}', '0'))
        if valor_total == 0:
            return await ctx.send(f"A recompensa para a orbe **{cor}** ainda não foi configurada.")

        canal_aprovacao_id = int(self.bot.get_cog('Admin').get_config_value('canal_aprovacao', '0'))
        canal_aprovacao = self.bot.get_channel(canal_aprovacao_id)
        if not canal_aprovacao:
            return await ctx.send("O canal de aprovações não foi configurado. Contacte um administrador.")

        membros_ids_json = json.dumps([p.id for p in participantes])

        with self.get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO submissoes_orbe (cor, valor_total, autor_id, membros, status) VALUES (%s, %s, %s, %s, 'pendente') RETURNING id",
                    (cor, valor_total, ctx.author.id, membros_ids_json)
                )
                submission_id = cursor.fetchone()[0]
            conn.commit()

        embed = discord.Embed(title=f"🔮 Submissão de Orbe #{submission_id}", color=0xf1c40f)
        embed.add_field(name="Autor", value=ctx.author.mention, inline=True)
        embed.add_field(name="Cor da Orbe", value=cor.capitalize(), inline=True)
        embed.add_field(name="Recompensa Total", value=f"`{valor_total} GC`", inline=True)
        embed.add_field(name="Participantes", value=", ".join([p.mention for p in participantes]), inline=False)
        embed.set_image(url=ctx.message.attachments[0].url)
        embed.set_footer(text="Aguardando aprovação da staff.")

        view = OrbApprovalView(self.bot, submission_id=submission_id)
        await canal_aprovacao.send(embed=embed, view=view)
        await ctx.send(f"✅ A sua submissão (ID: {submission_id}) foi enviada para o canal de aprovações!")

async def setup(bot):
    await bot.add_cog(Orbes(bot))

