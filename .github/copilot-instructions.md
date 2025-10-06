# Copilot Instructions for arauto-bank-bot

## Visão Geral
Este projeto é um bot de banco para Discord, estruturado em Python, com funcionalidades de economia, engajamento, eventos, loja, orbes, taxas e utilidades. O código está organizado em cogs (módulos de comandos) e utils (utilitários de backend).

## Estrutura Principal
- `main.py`: Ponto de entrada do bot. Inicializa o bot, carrega cogs e configurações.
- `cogs/`: Contém módulos de comandos separados por domínio (ex: `economia.py`, `eventos.py`). Cada arquivo define uma classe Cog do discord.py.
- `utils/`: Funções utilitárias e helpers, como acesso a banco de dados (`db_manager.py`), permissões e views customizadas.

## Padrões e Convenções
- Cada cog implementa comandos relacionados ao seu domínio e utiliza helpers de `utils/` para lógica compartilhada.
- O acesso ao banco de dados é centralizado em `utils/db_manager.py`.
- Permissões customizadas são implementadas em `utils/permissions.py`.
- Views interativas (ex: menus, botões) ficam em `utils/views.py`.
- Use sempre funções utilitárias para lógica repetida entre cogs.

## Fluxo de Dados
- Comandos de usuário (via Discord) são roteados para cogs.
- Cogs interagem com utilitários para persistência, validação e lógica de negócio.
- Respostas e interações são enviadas de volta ao Discord.

## Workflows de Desenvolvimento
- Instale dependências com: `pip install -r requirements.txt`
- Execute o bot localmente: `python main.py`
- Não há testes automatizados definidos por padrão.
- Para adicionar comandos, crie um novo arquivo em `cogs/` e registre a classe Cog em `main.py`.

## Integrações e Dependências
- Baseado em `discord.py` (ou fork compatível).
- Banco de dados: verifique `db_manager.py` para detalhes de integração (ex: SQLite, PostgreSQL, etc).
- Outras dependências estão listadas em `requirements.txt`.

## Exemplos de Padrões
- Para adicionar um comando:
  ```python
  from discord.ext import commands

  class MinhaCog(commands.Cog):
      @commands.command()
      async def meucomando(self, ctx):
          # lógica aqui
          pass
  ```
- Para acessar o banco:
  ```python
  from utils.db_manager import get_user_balance
  saldo = get_user_balance(user_id)
  ```

## Observações
- Siga a estrutura modular para facilitar manutenção.
- Centralize lógica compartilhada em `utils/`.
- Consulte cogs existentes para exemplos de implementação.
