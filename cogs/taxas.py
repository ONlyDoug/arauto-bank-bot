import discord
from discord.ext import commands, tasks
import contextlib
from datetime import date
from utils.permissions import check_permission_level

ID_TESOURO_GUILDA = 1

class Taxas(commands.Cog):
    """Cog para gerir o sistema de taxa semanal."""
    def __init__(self, bot):
        self.bot = bot

    def cog_unload(self):
        self.cobrar_taxas.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        print("Módulo de Taxas pronto. A iniciar a tarefa de cobrança.")
        self.cobrar_taxas.start()

    # =================================================================================
    # Tarefa de Cobrança Semanal
    # =================================================================================

    @tasks.loop(hours=24)
    async def cobrar_taxas(self):
        if date.today().weekday() != 0:  # Executa apenas à segunda-feira
            return

        print(f"[{date.today()}] A iniciar o processo de cobrança de taxas semanais.")
        
        if not self.bot.guilds:
            print("Bot não está em nenhum servidor. A saltar a cobrança de taxas.")
            return
        guild = self.bot.guilds[0]

        admin_cog = self.bot.get_cog('Admin')
        economia_cog = self.bot.get_cog('Economia')
        if not admin_cog or not economia_cog:
            print("ERRO: Cogs dependentes (Admin, Economia) não carregados. A abortar taxas.")
            return

        try:
            valor_taxa = int(admin_cog.get_config_value('taxa_semanal_valor', '0'))
            cargo_membro_id = int(admin_cog.get_config_value('cargo_membro', '0'))
            cargo_inadimplente_id = int(admin_cog.get_config_value('cargo_inadimplente', '0'))
            cargo_isento_id = int(admin_cog.get_config_value('cargo_isento', '0'))
        except (ValueError, TypeError):
             print("ERRO: Configurações de taxa inválidas. A abortar a cobrança.")
             return

        if not all([valor_taxa, cargo_membro_id, cargo_inadimplente_id]):
            print("AVISO: Configurações de taxa (valor, cargo membro, cargo inadimplente) não definidas. A abortar a cobrança.")
            return

        cargo_membro = guild.get_role(cargo_membro_id)
        cargo_inadimplente = guild.get_role(cargo_inadimplente_id)
        cargo_isento = guild.get_role(cargo_isento_id) if cargo_isento_id else None

        if not all([cargo_membro, cargo_inadimplente]):
            print("ERRO: Cargos de membro ou inadimplente não encontrados. A abortar a cobrança.")
            return

        for membro in cargo_membro.members:
            if membro.bot or (cargo_isento and cargo_isento in membro.roles):
                continue

            saldo_membro = await economia_cog.get_saldo(membro.id)

            if saldo_membro >= valor_taxa:
                await economia_cog.update_saldo(membro.id, -valor_taxa, "taxa_semanal", "Pagamento automático")
                await economia_cog.update_saldo(ID_TESOURO_GUILDA, valor_taxa, "recebimento_taxa", f"Taxa de {membro.name}")
            else:
                try:
                    await membro.remove_roles(cargo_membro, reason="Não pagamento da taxa")
                    await membro.add_roles(cargo_inadimplente, reason="Não pagamento da taxa")
                    await membro.send(f"⚠️ **Aviso de Inadimplência** ⚠️\nNão foi possível cobrar a taxa de `{valor_taxa} GC`. O seu cargo foi alterado para `{cargo_inadimplente.name}`. Use `!pagar-taxa` para regularizar.")
                except discord.Forbidden:
                    print(f"ERRO: Sem permissão para alterar os cargos de {membro.name}.")

        print("Processo de cobrança de taxas concluído.")

    @cobrar_taxas.before_loop
    async def before_cobrar_taxas(self):
        await self.bot.wait_until_ready()

    # =================================================================================
    # Comandos de Pagamento e Configuração
    # =================================================================================
    @commands.command(name='pagar-taxa')
    async def pagar_taxa(self, ctx):
        """Paga a taxa semanal atrasada usando GuildCoins."""
        admin_cog = self.bot.get_cog('Admin')
        economia_cog = self.bot.get_cog('Economia')

        valor_taxa = int(admin_cog.get_config_value('taxa_semanal_valor', '0'))
        cargo_membro_id = int(admin_cog.get_config_value('cargo_membro', '0'))
        cargo_inadimplente_id = int(admin_cog.get_config_value('cargo_inadimplente', '0'))
        
        cargo_membro = ctx.guild.get_role(cargo_membro_id)
        cargo_inadimplente = ctx.guild.get_role(cargo_inadimplente_id)

        if not cargo_inadimplente or not cargo_membro:
            return await ctx.send("Os cargos de taxa não estão configurados. Contacte um admin.")

        if cargo_inadimplente not in ctx.author.roles:
            return await ctx.send("Este comando é apenas para membros inadimplentes.")

        saldo_atual = await economia_cog.get_saldo(ctx.author.id)
        if saldo_atual < valor_taxa:
            return await ctx.send(f"Saldo insuficiente. Necessário: `{valor_taxa} GC`. Saldo atual: `{saldo_atual} GC`.")

        await economia_cog.update_saldo(ctx.author.id, -valor_taxa, "pagamento_taxa_atrasada", "Pagamento manual de taxa")
        await economia_cog.update_saldo(ID_TESOURO_GUILDA, valor_taxa, "recebimento_taxa", f"Taxa atrasada de {ctx.author.name}")

        await ctx.author.remove_roles(cargo_inadimplente, reason="Pagamento da taxa")
        await ctx.author.add_roles(cargo_membro, reason="Pagamento da taxa")

        await ctx.send(f"✅ Obrigado, {ctx.author.mention}! A sua taxa foi paga e o seu acesso foi restaurado.")
        
    @commands.group(name='config-taxa', invoke_without_command=True)
    @check_permission_level(4)
    async def config_taxa(self, ctx):
        """Grupo de comandos para configurar o sistema de taxas. (Nível 4+)"""
        await ctx.send("Use `!config-taxa valor <n>`, `!config-taxa cargo membro <@cargo>`, `... inadimplente <@cargo>`, ou `... isento <@cargo>`.")

    @config_taxa.command(name='valor')
    @check_permission_level(4)
    async def config_taxa_valor(self, ctx, valor: int):
        """Define o valor da taxa semanal em GuildCoins."""
        if valor < 0: return
        self.bot.get_cog('Admin').set_config_value('taxa_semanal_valor', str(valor))
        await ctx.send(f"✅ O valor da taxa semanal foi definido para `{valor} GC`.")

    @config_taxa.command(name='cargo')
    @check_permission_level(4)
    async def config_taxa_cargo(self, ctx, tipo: str, cargo: discord.Role):
        """Define os cargos do sistema. Tipos: membro, inadimplente, isento."""
        tipo = tipo.lower()
        if tipo not in ['membro', 'inadimplente', 'isento']:
            return await ctx.send("Tipo inválido. Use `membro`, `inadimplente` ou `isento`.")
        
        self.bot.get_cog('Admin').set_config_value(f'cargo_{tipo}', str(cargo.id))
        await ctx.send(f"✅ O cargo de `{tipo}` foi definido como **@{cargo.name}**.")

async def setup(bot):
    await bot.add_cog(Taxas(bot))
