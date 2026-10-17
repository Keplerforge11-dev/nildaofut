# NildãoFut

App de futebol brasileiro feito para quem tem pouca prática com o celular: letra grande, poucos botões,
preto e dourado, e o Nildão para dar boas-vindas.

- `index.html`: o app (abre no navegador e pode ser instalado na tela inicial do Android)
- `data.json`: jogos, placares, tabela, canais e notícias. É atualizado sozinho pelo robô
- `update.py`: o robô. Brasileirão pela football-data.org, canais pelo blog da Claro, notícias pelo feed da Gazeta Esportiva
- `.github/workflows/update.yml`: faz o robô rodar de meia em meia hora
- `debug/`: cópias de páginas das fontes, só para ajustar a leitura quando uma fonte muda de formato

A chave da football-data.org fica em *Settings > Secrets and variables > Actions* com o nome `FOOTBALL_DATA_KEY`.
Nunca coloque a chave dentro dos arquivos.
