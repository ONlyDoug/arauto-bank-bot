import discord
from discord.ext import commands, tasks
import contextlib
from datetime import date, timedelta

class Taxas(commands.Cog):
    """Cog para gerir o sistema de taxa semanal."""
    def __init__(self, bot):
        self.bot = bot
        self.cobrar_taxas.start()

    def cog_unload(self):
        self.cobrar_taxas.cancel()

    @contextlib.contextmanager
    def get_db_connection(self):
        conn = None
        try:
            conn = self.bot.db_pool.getconn()
            yield conn
        finally:
            if conn: self.bot.db_pool.putconn(conn)

    @tasks.loop(hours=24)
    async def cobrar_taxas(self):
        await self.bot.wait_until_ready()
        hoje = date.today()
        # Executar apenas aos domingos (weekday() == 6)
        if hoje.weekday() != 6: return

        admin_cog = self.bot.get_cog('Admin')
        economia_cog = self.bot.get_cog('Economia')
        
        valor_taxa = int(admin_cog.get_config_value('taxa_semanal_valor', '0'))
        if valor_taxa <= 0: return

        cargo_membro_id = int(admin_cog.get_config_value('cargo_membro', '0'))
        cargo_inadimplente_id = int(admin_cog.get_config_value('cargo_inadimplente', '0'))
        cargo_isento_id = int(admin_cog.get_config_value('cargo_isento', '0'))

        if not all([cargo_membro_id, cargo_inadimplente_id]): return

        for guild in self.bot.guilds:
            cargo_membro = guild.get_role(cargo_membro_id)
            cargo_inadimplente = guild.get_role(cargo_inadimplente_id)
            cargo_isento = guild.get_role(cargo_isento_id)
            if not all([cargo_membro, cargo_inadimplente]): continue

            for member in guild.members:
                if member.bot or (cargo_isento and cargo_isento in member.roles):
                    continue
                
                saldo = await economia_cog.get_saldo(member.id)
                if saldo >= valor_taxa:
                    await economia_cog.update_saldo(member.id, -valor_taxa, "pagamento_taxa", "Taxa semanal automática")
                    # Garantir que está com o cargo certo
                    if cargo_inadimplente in member.roles: await member.remove_roles(cargo_inadimplente)
                    if cargo_membro not in member.roles: await member.add_roles(cargo_membro)
                else:
                    # Tornar inadimplente
                    if cargo_membro in member.roles: await member.remove_roles(cargo_membro)
                    if cargo_inadimplente not in member.roles: await member.add_roles(cargo_inadimplente)

    @commands.command(name='pagar-taxa')
    async def pagar_taxa(self, ctx):
        admin_cog = self.bot.get_cog('Admin')
        valor_taxa = int(admin_cog.get_config_value('taxa_semanal_valor', '0'))
        
        economia_cog = self.bot.get_cog('Economia')
        saldo = await economia_cog.get_saldo(ctx.author.id)

        if saldo < valor_taxa:
            return await ctx.send(f"Você não tem saldo suficiente. Precisa de `{valor_taxa} GC`.")

        await economia_cog.update_saldo(ctx.author.id, -valor_taxa, "pagamento_taxa", "Pagamento manual de taxa")

        cargo_membro_id = int(admin_cog.get_config_value('cargo_membro', '0'))
        cargo_inadimplente_id = int(admin_cog.get_config_value('cargo_inadimplente', '0'))
        cargo_membro = ctx.guild.get_role(cargo_membro_id)
        cargo_inadimplente = ctx.guild.get_role(cargo_inadimplente_id)

        if cargo_membro and cargo_inadimplente:
            if cargo_inadimplente in ctx.author.roles:
                await ctx.author.remove_roles(cargo_inadimplente)
            if cargo_membro not in ctx.author.roles:
                await ctx.author.add_roles(cargo_membro)
        
        await ctx.send("✅ Taxa paga com sucesso! O seu acesso foi restaurado.")

async def setup(bot):
    await bot.add_cog(Taxas(bot))

