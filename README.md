# NildãoFut

App de futebol brasileiro feito para quem tem pouca prática com o celular: letra grande, poucos botões,
preto e dourado, e o Nildão para dar boas-vindas.

- `index.html`: o app (abre no navegador e pode ser instalado na tela inicial do Android)
- `data.json`: jogos, placares, tabela, canais e notícias. É atualizado sozinho pelo robô
- `update.py`: o robô. Brasileirão pela football-data.org, canais pelo blog da Claro, notícias pelo feed da Gazeta Esportiva
- `.github/workflows/update.yml`: faz o robô rodar de meia em meia hora
- Melhores momentos: o robô lê o feed público da playlist do ge tv no YouTube e liga cada vídeo ao jogo pelos nomes dos times no título
- `debug/`: cópias de páginas das fontes, só para ajustar a leitura quando uma fonte muda de formato

A chave da football-data.org fica em *Settings > Secrets and variables > Actions* com o nome `FOOTBALL_DATA_KEY`.
Nunca coloque a chave dentro dos arquivos.

## Ranking de palpites (Supabase gratuito)

- `supabase/schema.sql`: cria as tabelas e as regras no Supabase. Cole no *SQL Editor* e clique em Run (pode rodar de novo sem problema)
- `palpites.js`: as telas (Primeiro acesso, Meus grupos, Ranking, Palpites, Comentários, Criar grupo, Entrar com código)
- `supabase.js`: biblioteca oficial do Supabase, guardada aqui para o app não depender de outro site
- `sync_supabase.py`: o robô envia os jogos e placares do `data.json` para o Supabase. Quando um jogo termina, o ranking atualiza sozinho

A chave **pública** (anon) fica em `palpites.js`: ela pode ficar no código, quem protege os dados são as regras do `schema.sql`.
A chave **service_role** fica só em *Settings > Secrets and variables > Actions* com o nome `SUPABASE_SERVICE_KEY`.
