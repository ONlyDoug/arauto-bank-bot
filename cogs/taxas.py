import discord
from discord.ext import commands, tasks
from utils.permissions import check_permission_level
from datetime import datetime
import asyncio

class Taxas(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.ciclo_semanal_taxas.start()
        print("Módulo de Taxas pronto. A iniciar a tarefa do ciclo semanal.")

    def cog_unload(self):
        self.ciclo_semanal_taxas.cancel()

    async def regularizar_membro(self, membro: discord.Member):
        """
        Remove o cargo de inadimplente e adiciona o de membro, regularizando a situação do utilizador.
        Esta função é chamada pelos comandos de pagamento.
        """
        # Obtém os IDs dos cargos a partir da base de dados
        cargo_inadimplente_id = await self.bot.db_manager.get_config_value('cargo_inadimplente', '0')
        cargo_membro_id = await self.bot.db_manager.get_config_value('cargo_membro', '0')

        if not cargo_inadimplente_id or not cargo_membro_id:
            print("AVISO: Cargos de membro ou inadimplente não configurados. A função regularizar_membro não pode operar.")
            return

        cargo_inadimplente = membro.guild.get_role(int(cargo_inadimplente_id))
        cargo_membro = membro.guild.get_role(int(cargo_membro_id))

        if cargo_inadimplente and cargo_inadimplente in membro.roles:
            await membro.remove_roles(cargo_inadimplente, reason="Pagamento de taxa regularizado")
        
        if cargo_membro and cargo_membro not in membro.roles:
            await membro.add_roles(cargo_membro, reason="Pagamento de taxa regularizado")

    @tasks.loop(hours=1) # Verifica a cada hora
    async def ciclo_semanal_taxas(self):
        await self.bot.wait_until_ready()
        
        # O dia da semana para a cobrança (0=Segunda, 6=Domingo)
        dia_cobranca = int(await self.bot.db_manager.get_config_value('taxa_dia_semana', '0'))
        
        agora = datetime.utcnow()

        # Verifica se hoje é o dia da cobrança e se a tarefa já foi executada hoje
        if agora.weekday() == dia_cobranca:
            data_hoje_str = agora.strftime('%Y-%m-%d')
            ultima_execucao = await self.bot.db_manager.get_config_value('taxa_ultima_execucao', '')

            if ultima_execucao != data_hoje_str:
                print(f"A iniciar ciclo de taxas para {data_hoje_str}...")
                await self.executar_ciclo_de_taxas()
                await self.bot.db_manager.set_config_value('taxa_ultima_execucao', data_hoje_str)

    async def executar_ciclo_de_taxas(self, guild_override: discord.Guild = None):
        """
        Lógica principal que aplica o status de inadimplente a todos os membros elegíveis.
        Pode ser chamada pela tarefa agendada ou manualmente por um admin.
        """
        guilds = [guild_override] if guild_override else self.bot.guilds
        
        # Carrega todas as configurações necessárias de uma só vez
        configs = await self.bot.db_manager.get_all_configs([
            'cargo_membro', 'cargo_inadimplente', 'cargo_isento', 'canal_aprovacao'
        ])
        
        cargo_membro_id = int(configs.get('cargo_membro', '0'))
        cargo_inadimplente_id = int(configs.get('cargo_inadimplente', '0'))
        cargo_isento_id = int(configs.get('cargo_isento', '0'))
        canal_log_id = int(configs.get('canal_aprovacao', '0'))

        if not cargo_membro_id or not cargo_inadimplente_id:
            print("CICLO DE TAXAS IGNORADO: Cargos de membro ou inadimplente não configurados.")
            return

        for guild in guilds:
            cargo_membro = guild.get_role(cargo_membro_id)
            cargo_inadimplente = guild.get_role(cargo_inadimplente_id)
            cargo_isento = guild.get_role(cargo_isento_id) if cargo_isento_id else None

            if not cargo_membro or not cargo_inadimplente:
                print(f"CICLO DE TAXAS IGNORADO na guilda {guild.name}: Cargos não encontrados.")
                continue

            membros_afetados = 0
            for membro in guild.members:
                if membro.bot:
                    continue
                
                # Ignora membros que já são inadimplentes ou são isentos
                if cargo_inadimplente in membro.roles or (cargo_isento and cargo_isento in membro.roles):
                    continue
                
                # Aplica o cargo de inadimplente e remove o de membro
                if cargo_membro in membro.roles:
                    await membro.remove_roles(cargo_membro, reason="Início do ciclo de taxas")
                
                await membro.add_roles(cargo_inadimplente, reason="Início do ciclo de taxas")
                membros_afetados += 1
                await asyncio.sleep(0.5) # Pausa para não sobrecarregar a API

            # Envia um log para o canal de administração
            if canal_log_id:
                canal_log = self.bot.get_channel(canal_log_id)
                if canal_log:
                    await canal_log.send(f"✅ **Ciclo de Taxas Iniciado**\n`{membros_afetados}` membros foram marcados como inadimplentes e precisam de pagar a taxa semanal.")

    @commands.command(name="pagar-taxa")
    async def pagar_taxa(self, ctx):
        valor_taxa_str = await self.bot.db_manager.get_config_value('taxa_semanal_valor', '0')
        valor_taxa = int(valor_taxa_str)

        if valor_taxa == 0:
            return await ctx.send("O sistema de taxas não está configurado.")

        economia_cog = self.bot.get_cog('Economia')
        try:
            await economia_cog.levantar(ctx.author.id, valor_taxa, "Pagamento de taxa semanal")
            await self.regularizar_membro(ctx.author)
            await ctx.send("✅ Taxa paga com sucesso! O seu acesso foi restaurado.")
        except ValueError:
            await ctx.send("❌ Você não tem saldo suficiente para pagar a taxa.")

    @commands.command(name="paguei-prata")
    async def paguei_prata(self, ctx):
        if not ctx.message.attachments:
            return await ctx.send("❌ Você precisa de anexar um print (imagem) do comprovativo de pagamento.", delete_after=15)

        imagem = ctx.message.attachments[0]
        if not imagem.content_type.startswith('image/'):
            return await ctx.send("❌ O anexo precisa de ser uma imagem.", delete_after=15)

        canal_aprovacao_id = int(await self.bot.db_manager.get_config_value('canal_aprovacao', '0'))
        canal_aprovacao = self.bot.get_channel(canal_aprovacao_id)

        if not canal_aprovacao:
            return await ctx.send("⚠️ O canal de aprovações não foi configurado. Contacte um administrador.")
        
        embed = discord.Embed(
            title="🧾 Pagamento de Taxa em Prata",
            description=f"**Membro:** {ctx.author.mention} (`{ctx.author.id}`)\n"
                        f"Enviou um comprovativo de pagamento da taxa em prata.",
            color=discord.Color.orange()
        )
        embed.set_image(url=imagem.url)
        embed.set_footer(text="Aguardando aprovação da Staff...")
        
        view = self.bot.get_view("TaxaPrataView") # Reutiliza a view persistente
        if not view:
            # Fallback caso a view não seja encontrada (não deveria acontecer)
            from utils.views import TaxaPrataView as FallbackView
            view = FallbackView(self.bot)

        try:
            msg_aprovacao = await canal_aprovacao.send(embed=embed, view=view)
            
            await self.bot.db_manager.execute_query(
                "INSERT INTO submissoes_taxa (message_id, user_id, status, url_imagem) VALUES (%s, %s, %s, %s) ON CONFLICT (message_id) DO UPDATE SET user_id = EXCLUDED.user_id, status = EXCLUDED.status, url_imagem = EXCLUDED.url_imagem",
                (msg_aprovacao.id, ctx.author.id, 'pendente', imagem.url)
            )

            await ctx.message.add_reaction("✅")
            await ctx.send("✅ Comprovativo enviado para análise! A sua situação será regularizada assim que um staff aprovar.", delete_after=15)
        
        except Exception as e:
            await ctx.send("❌ Ocorreu um erro ao enviar o seu comprovativo.")
            print(f"Erro no comando paguei-prata: {e}")

    # --- Comandos de Configuração de Taxas ---
    
    @commands.command(name="definir-taxa")
    @check_permission_level(4)
    async def definir_taxa(self, ctx, valor: int):
        if valor < 0:
            return await ctx.send("O valor da taxa não pode ser negativo.")
        await self.bot.db_manager.set_config_value('taxa_semanal_valor', str(valor))
        await ctx.send(f"✅ Valor da taxa semanal definido para **{valor}** moedas.")

    @commands.command(name="definir-taxa-dia")
    @check_permission_level(4)
    async def definir_taxa_dia(self, ctx, dia: int):
        if not 0 <= dia <= 6:
            return await ctx.send("❌ O dia deve ser um número entre 0 (Segunda) e 6 (Domingo).")
        
        dias_semana = ["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira", "Sexta-feira", "Sábado", "Domingo"]
        await self.bot.db_manager.set_config_value('taxa_dia_semana', str(dia))
        await ctx.send(f"✅ O ciclo de taxas foi agendado para ser executado todas as **{dias_semana[dia]}**.")

    @commands.command(name="forcar-taxa")
    @check_permission_level(4)
    async def forcar_taxa(self, ctx):
        """Comando de teste para forçar a execução do ciclo de taxas."""
        msg = await ctx.send("Forçando a execução do ciclo de taxas para todos os membros... Isto pode demorar.")
        await self.executar_ciclo_de_taxas(ctx.guild)
        await msg.edit(content="✅ Ciclo de taxas executado manualmente com sucesso.")


async def setup(bot):
    await bot.add_cog(Taxas(bot))

