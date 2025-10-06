# Copilot Instructions for arauto-bank-bot

## Visão Geral e Arquitetura

Este projeto é um bot de economia bancária para Discord, escrito em Python, estruturado de forma modular para facilitar manutenção e extensão. O bot utiliza `discord.py` e organiza comandos em cogs por domínio de negócio, com utilitários centralizados para lógica compartilhada e persistência.

### Componentes Principais

- **`main.py`**: Ponto de entrada. Inicializa o bot, define intenções, carrega cogs, conecta ao banco e registra views persistentes. Implementa um check global para restringir comandos a categorias específicas do Discord.
- **`cogs/`**: Cada arquivo representa um domínio funcional (ex: `economia.py`, `eventos.py`). Cada cog é uma subclasse de `commands.Cog` e deve ser registrada em `main.py`.
- **`utils/`**: Funções utilitárias e helpers:
  - `db_manager.py`: Centraliza acesso ao banco de dados (ex: PostgreSQL via `psycopg2-binary`).
  - `permissions.py`: Permissões customizadas para comandos.
  - `views.py`: Views interativas persistentes (menus, botões, etc).

## Fluxo de Dados e Integração

- Usuários interagem via comandos no Discord, roteados para cogs.
- Cogs utilizam funções de `utils/` para lógica de negócio, persistência e validação.
- Respostas e interações são enviadas de volta ao Discord.
- O banco de dados é acessado exclusivamente via `DatabaseManager` (em `utils/db_manager.py`).

## Convenções e Padrões Específicos

- **Cogs**: Cada cog implementa comandos de um domínio e importa helpers de `utils/` para lógica comum.
- **Banco de Dados**: Nunca acesse o banco diretamente nos cogs; use sempre métodos do `DatabaseManager`.
- **Views**: Views persistentes devem ser registradas em `main.py` usando `self.add_view`.
- **Permissões**: Use checks customizados de `utils/permissions.py` para regras de acesso.
- **Categorias Permitidas**: O check global em `main.py` restringe comandos a categorias específicas (ver `self.allowed_categories`).

## Workflows de Desenvolvimento

- Instale dependências: `pip install -r requirements.txt`
- Execute localmente: `python main.py`
- Variáveis de ambiente (ex: `DISCORD_TOKEN`, `DATABASE_URL`) devem estar em um arquivo `.env` (não versionado).
- Para adicionar comandos: crie um novo arquivo em `cogs/`, implemente uma classe Cog e registre em `main.py`.
- Não há testes automatizados definidos por padrão.

## Exemplos de Uso e Padrão

- **Novo comando em um cog**:

  ```python
  from discord.ext import commands

  class Economia(commands.Cog):
      @commands.command()
      async def saldo(self, ctx):
          from utils.db_manager import get_user_balance
          saldo = await get_user_balance(ctx.author.id)
          await ctx.send(f'Seu saldo: {saldo}')
  ```

- **Acesso ao banco**:
  ```python
  from utils.db_manager import get_user_balance
  saldo = await get_user_balance(user_id)
  ```

## Observações Importantes

- Siga a estrutura modular e centralize lógica repetida em `utils/`.
- Consulte cogs existentes para exemplos de implementação.
- O bot depende de variáveis de ambiente e banco de dados externo; garanta que estejam configurados antes de rodar.
