import discord
from discord.ext import commands, tasks
from utils.permissions import check_permission_level
from datetime import datetime, time, timedelta
from utils.views import TaxaPrataView
import asyncio

class Taxas(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.ciclo_semanal_taxas.start()
        print("Módulo de Taxas pronto. A iniciar a tarefa do ciclo semanal.")

    def cog_unload(self):
        self.ciclo_semanal_taxas.cancel()

    async def regularizar_membro(self, membro: discord.Member, configs: dict):
        cargo_inadimplente = membro.guild.get_role(int(configs.get('cargo_inadimplente', '0')))
        cargo_membro = membro.guild.get_role(int(configs.get('cargo_membro', '0')))

        if not cargo_inadimplente or not cargo_membro:
            print("AVISO: Cargos de membro ou inadimplente não configurados.")
            return

        try:
            if cargo_inadimplente in membro.roles:
                await membro.remove_roles(cargo_inadimplente, reason="Taxa regularizada")
            if cargo_membro not in membro.roles:
                await membro.add_roles(cargo_membro, reason="Taxa regularizada")
        except discord.Forbidden:
            print(f"Erro de permissão ao tentar alterar cargos para {membro.name}")
        except Exception as e:
            print(f"Erro inesperado ao alterar cargos para {membro.name}: {e}")

    @tasks.loop(time=time(hour=12, minute=0, tzinfo=datetime.now().astimezone().tzinfo))
    async def ciclo_semanal_taxas(self):
        dia_semana_config_str = await self.bot.db_manager.get_config_value('taxa_dia_semana', '-1')
        dia_semana_config = int(dia_semana_config_str)
        hoje = datetime.now().weekday() # Segunda é 0, Domingo é 6

        if hoje == dia_semana_config:
            print(f"Hoje é dia {hoje}, o dia configurado para as taxas. A iniciar o ciclo.")
            await self.executar_ciclo_de_taxas()
        else:
            print(f"Hoje é dia {hoje}, não é o dia configurado ({dia_semana_config}). A aguardar.")

    async def executar_ciclo_de_taxas(self, ctx=None):
        """A lógica que remove o cargo de membro e adiciona o de inadimplente."""
        guild = ctx.guild if ctx else self.bot.guilds[0] if self.bot.guilds else None
        
        if not guild:
            print("ERRO: O bot não está em nenhum servidor para executar o ciclo de taxas.")
            return

        configs = await self.bot.db_manager.get_all_configs([
            'cargo_membro', 'cargo_inadimplente', 'cargo_isento', 'canal_log_taxas'
        ])
        
        cargo_membro = guild.get_role(int(configs.get('cargo_membro', '0')))
        cargo_inadimplente = guild.get_role(int(configs.get('cargo_inadimplente', '0')))
        cargo_isento = guild.get_role(int(configs.get('cargo_isento', '0')))
        canal_log = self.bot.get_channel(int(configs.get('canal_log_taxas', '0')))

        if not cargo_membro or not cargo_inadimplente:
            msg = "ERRO: O ciclo de taxas não pode ser executado. Os cargos de Membro e Inadimplente precisam de ser configurados."
            print(msg)
            if ctx: await ctx.send(msg)
            if canal_log: await canal_log.send(msg)
            return

        membros_a_processar = [m for m in guild.members if cargo_membro in m.roles and not m.bot]
        if cargo_isento:
            membros_a_processar = [m for m in membros_a_processar if cargo_isento not in m.roles]

        if not membros_a_processar:
            msg = "Ciclo de taxas executado. Nenhum membro elegível encontrado para aplicar a taxa."
            print(msg)
            if ctx: await ctx.send(msg)
            if canal_log: await canal_log.send(f"ℹ️ {msg}")
            return
            
        afetados = 0
        falhas = 0
        lista_falhas = []

        for membro in membros_a_processar:
            try:
                await membro.remove_roles(cargo_membro, reason="Início do ciclo de taxa semanal")
                await membro.add_roles(cargo_inadimplente, reason="Início do ciclo de taxa semanal")
                afetados += 1
                await asyncio.sleep(0.5) 
            except discord.Forbidden:
                falhas += 1
                lista_falhas.append(f"{membro.name}#{membro.discriminator} (Permissão negada)")
                print(f"Sem permissão para alterar cargos do membro {membro.name} ({membro.id})")
            except Exception as e:
                falhas += 1
                lista_falhas.append(f"{membro.name}#{membro.discriminator} (Erro: {e})")
                print(f"Erro ao processar cargos para {membro.name}: {e}")
        
        if afetados > 0:
            ids_afetados = [m.id for m in membros_a_processar[:afetados]]
            await self.bot.db_manager.execute_query(
                "INSERT INTO taxas (user_id, status) SELECT user_id, 'inadimplente' FROM UNNEST($1::BIGINT[]) as t(user_id) ON CONFLICT (user_id) DO UPDATE SET status = 'inadimplente'",
                ids_afetados
            )

        msg = f"✅ Ciclo de taxas finalizado. {afetados} membros foram marcados como inadimplentes. Falhas: {falhas}."
        print(msg)
        if ctx: await ctx.send(msg)
        if canal_log:
            embed = discord.Embed(title="Relatório do Ciclo de Taxas", description=msg, color=discord.Color.green())
            if falhas > 0:
                embed.add_field(name="Detalhes das Falhas", value="\n".join(lista_falhas), inline=False)
            await canal_log.send(embed=embed)

    @ciclo_semanal_taxas.before_loop
    async def before_ciclo_taxas(self):
        await self.bot.wait_until_ready()
        print("Tarefa do ciclo de taxas está pronta e a aguardar a hora certa.")

    @commands.command(
        name="pagar-taxa",
        help='Paga a sua taxa semanal em atraso usando o seu saldo de moedas. Isto restaura o seu acesso aos canais da guilda.'
    )
    async def pagar_taxa(self, ctx):
        configs = await self.bot.db_manager.get_all_configs(['taxa_semanal_valor', 'cargo_membro', 'cargo_inadimplente'])
        valor_taxa = int(configs.get('taxa_semanal_valor', 0))

        if valor_taxa == 0:
            return await ctx.send("O sistema de taxas não está configurado. Sorte a sua!")

        economia_cog = self.bot.get_cog('Economia')
        try:
            await economia_cog.levantar(ctx.author.id, valor_taxa, "Pagamento de taxa semanal")
            await self.regularizar_membro(ctx.author, configs)
            await self.bot.db_manager.execute_query(
                "UPDATE taxas SET status = 'pago' WHERE user_id = $1", ctx.author.id
            )
            await ctx.send("✅ Taxa paga com sucesso! O seu acesso foi restaurado. Bem-vindo de volta, capitalista!")
        except ValueError:
            await ctx.send(f"❌ Você não tem saldo suficiente. A taxa custa **{valor_taxa}** moedas e você parece estar... 'economicamente desfavorecido'.")

    @commands.command(
        name="paguei-prata",
        help='Inicia o processo de pagamento da taxa com prata do jogo. Tem de anexar um print do comprovativo de pagamento na mesma mensagem.'
    )
    async def paguei_prata(self, ctx):
        if not ctx.message.attachments or not ctx.message.attachments[0].content_type.startswith('image/'):
            return await ctx.send("❌ Olá? O print? Anexe a imagem do comprovativo de pagamento para eu poder enviar para a staff.", delete_after=15)

        imagem = ctx.message.attachments[0]
        canal_aprovacao_id_str = await self.bot.db_manager.get_config_value('canal_aprovacao', '0')
        canal_aprovacao = self.bot.get_channel(int(canal_aprovacao_id_str))

        if not canal_aprovacao:
            return await ctx.send("⚠️ O canal de aprovações não foi configurado. Contacte um administrador. A sua prata está no limbo por agora.")
        
        embed = discord.Embed(
            title="🧾 Pagamento de Taxa em Prata",
            description=f"**Membro:** {ctx.author.mention} (`{ctx.author.id}`)\n"
                        f"Enviou um comprovativo de pagamento da taxa em prata.",
            color=discord.Color.orange()
        )
        embed.set_image(url=imagem.url)
        embed.set_footer(text="Aguardando aprovação da Staff...")
        
        view = TaxaPrataView(self.bot)

        try:
            msg_aprovacao = await canal_aprovacao.send(embed=embed, view=view)
            
            await self.bot.db_manager.execute_query(
                "DELETE FROM submissoes_taxa WHERE message_id = $1",
                msg_aprovacao.id
            )
            await self.bot.db_manager.execute_query(
                "INSERT INTO submissoes_taxa (message_id, user_id, status) VALUES ($1, $2, $3)",
                msg_aprovacao.id, ctx.author.id, 'pendente'
            )

            await ctx.message.add_reaction("✅")
            await ctx.send("✅ Comprovativo enviado para análise! Agora aguente a ansiedade até um staff aprovar.", delete_after=15)
        
        except Exception as e:
            await ctx.send("❌ Ocorreu um erro ao enviar o seu comprovativo.")
            print(f"Erro no comando paguei-prata: {e}")

    # Comandos de staff ficam escondidos
    @commands.command(name="definir-taxa", hidden=True)
    @check_permission_level(4)
    async def definir_taxa(self, ctx, valor: int):
        if valor < 0:
            return await ctx.send("O valor da taxa não pode ser negativo.")
        await self.bot.db_manager.set_config_value('taxa_semanal_valor', str(valor))
        await ctx.send(f"✅ Valor da taxa semanal definido para **{valor}** moedas.")
        
    @commands.command(name="definir-taxa-dia", hidden=True)
    @check_permission_level(4)
    async def definir_taxa_dia(self, ctx, dia_da_semana: int):
        if not 0 <= dia_da_semana <= 6:
            return await ctx.send("❌ O dia da semana deve ser um número de 0 (Segunda) a 6 (Domingo).")
        dias = ["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira", "Sexta-feira", "Sábado", "Domingo"]
        await self.bot.db_manager.set_config_value('taxa_dia_semana', str(dia_da_semana))
        await ctx.send(f"✅ O ciclo de taxas foi agendado para ser executado todas as **{dias[dia_da_semana]}**.")

    @commands.command(name="forcar-taxa", hidden=True)
    @check_permission_level(4)
    async def forcar_taxa(self, ctx):
        await ctx.send("🔥 A forçar a execução do ciclo de taxas... Isto pode demorar um pouco.")
        await self.executar_ciclo_de_taxas(ctx)

async def setup(bot):
    await bot.add_cog(Taxas(bot))



