import discord
from discord.ext import commands, tasks
import contextlib
from datetime import date, timedelta, datetime
from utils.permissions import check_permission_level

# --- View para Aprovação de Pagamento em Prata ---
class TaxaPrataView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def handle_interaction(self, interaction: discord.Interaction, status: str):
        perm_check = await check_permission_level(2).predicate(interaction)
        if not perm_check:
            return await interaction.response.send_message("Você não tem permissão para esta ação.", ephemeral=True)

        message_id = interaction.message.id
        
        with self.get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT user_id FROM submissoes_taxa WHERE message_id = %s AND status = 'pendente'", (message_id,))
                result = cursor.fetchone()
                if not result:
                    return await interaction.response.send_message("Esta submissão já foi processada.", ephemeral=True, delete_after=10)
                
                user_id = result[0]
                cursor.execute("UPDATE submissoes_taxa SET status = %s WHERE message_id = %s", (status, message_id))
                conn.commit()

        membro = interaction.guild.get_member(user_id)
        original_embed = interaction.message.embeds[0]
        new_embed = original_embed.copy()
        
        if status == "aprovado":
            await self.bot.get_cog('Taxas').regularizar_membro(membro)
            new_embed.title = "✅ Pagamento Aprovado"
            new_embed.color = discord.Color.green()
            new_embed.clear_fields()
            new_embed.add_field(name="Membro", value=membro.mention)
            new_embed.add_field(name="Status", value=f"Aprovado por {interaction.user.mention}")
        else: # recusado
            new_embed.title = "❌ Pagamento Recusado"
            new_embed.color = discord.Color.red()
            new_embed.clear_fields()
            new_embed.add_field(name="Membro", value=membro.mention)
            new_embed.add_field(name="Status", value=f"Recusado por {interaction.user.mention}")

        await interaction.message.edit(embed=new_embed, view=None)
        await interaction.response.send_message(f"Submissão de {membro.display_name} marcada como `{status}`.", ephemeral=True)

    @discord.ui.button(label="Aprovar", style=discord.ButtonStyle.green, custom_id="aprovar_taxa_prata_button")
    async def aprovar_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_interaction(interaction, "aprovado")

    @discord.ui.button(label="Recusar", style=discord.ButtonStyle.red, custom_id="recusar_taxa_prata_button")
    async def recusar_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_interaction(interaction, "recusado")
    
    @contextlib.contextmanager
    def get_db_connection(self):
        conn = None
        try:
            conn = self.bot.db_pool.getconn()
            yield conn
        finally:
            if conn: self.bot.db_pool.putconn(conn)


class Taxas(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.cobrar_taxa.start()
        self.bot.add_view(TaxaPrataView(bot))

    def cog_unload(self):
        self.cobrar_taxa.cancel()

    @contextlib.contextmanager
    def get_db_connection(self):
        conn = None
        try:
            conn = self.bot.db_pool.getconn()
            yield conn
        finally:
            if conn: self.bot.db_pool.putconn(conn)

    @commands.command(name='paguei-prata')
    async def paguei_prata(self, ctx):
        if not ctx.message.attachments:
            return await ctx.send("❌ Você precisa anexar um print (screenshot) do comprovativo de pagamento.", delete_after=10)
        
        comprovativo = ctx.message.attachments[0]
        if not comprovativo.content_type.startswith('image/'):
            return await ctx.send("❌ O anexo deve ser uma imagem.", delete_after=10)

        admin_cog = self.bot.get_cog('Admin')
        canal_aprovacao_id = int(admin_cog.get_config_value('canal_aprovacao', '0'))
        if canal_aprovacao_id == 0:
            return await ctx.send("⚠️ O canal de aprovações não está configurado. Contacte um administrador.")

        canal_aprovacao = self.bot.get_channel(canal_aprovacao_id)
        if not canal_aprovacao:
            return await ctx.send("⚠️ O canal de aprovações não foi encontrado. Contacte um administrador.")

        embed = discord.Embed(title="⏳ Aprovação de Taxa (Prata)", description=f"O membro **{ctx.author.display_name}** enviou um comprovativo de pagamento.", color=0xf1c40f)
        embed.set_image(url=comprovativo.url)
        embed.add_field(name="Membro", value=ctx.author.mention)
        embed.set_footer(text="Ação requerida: Verificar o pagamento no jogo e aprovar/recusar.")
        
        view = TaxaPrataView(self.bot)
        msg_aprovacao = await canal_aprovacao.send(embed=embed, view=view)

        with self.get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO submissoes_taxa (message_id, user_id, status) VALUES (%s, %s, 'pendente')",
                    (msg_aprovacao.id, ctx.author.id)
                )
            conn.commit()

        await ctx.send("✅ O seu comprovativo foi enviado para aprovação. Por favor, aguarde.", delete_after=15)
        # Apaga a mensagem do usuário para manter o canal limpo
        await ctx.message.delete()

    async def regularizar_membro(self, membro: discord.Member):
        if not membro: return
        admin_cog = self.bot.get_cog('Admin')
        id_cargo_inadimplente = int(admin_cog.get_config_value('cargo_inadimplente', '0'))
        id_cargo_membro = int(admin_cog.get_config_value('cargo_membro', '0'))
        cargo_inadimplente = membro.guild.get_role(id_cargo_inadimplente)
        cargo_membro = membro.guild.get_role(id_cargo_membro)
        if cargo_inadimplente in membro.roles:
            await membro.remove_roles(cargo_inadimplente)
        if cargo_membro and cargo_membro not in membro.roles:
            await membro.add_roles(cargo_membro)
        with self.get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("UPDATE taxas SET status = 'pago', data_vencimento = %s WHERE user_id = %s",
                               (date.today() + timedelta(days=7), membro.id))
            conn.commit()
    
    # ... (restante do código)
    @tasks.loop(hours=24)
    async def cobrar_taxa(self):
        pass

    @cobrar_taxa.before_loop
    async def before_cobrar_taxa(self):
        await self.bot.wait_until_ready()
        print("Módulo de Taxas pronto. A iniciar a tarefa de cobrança.")

async def setup(bot):
    await bot.add_cog(Taxas(bot))

