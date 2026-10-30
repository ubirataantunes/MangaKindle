# MangaKindle

App web para escolher mangás nas mesmas extensões do Mihon e enviá-los ao Kindle por e-mail,
já convertidos para EPUB com leitura da direita para a esquerda.

- **Suwayomi-Server** roda as extensões do Mihon/Tachiyomi fora do Android.
- **KCC (Kindle Comic Converter)** converte as páginas para o tamanho de tela do seu Kindle.
- **MangaKindle** (este app) tem login, busca, seleção de capítulos, fila de envio e histórico.

## Como subir (uso local)

1. Instale o Docker Desktop.
2. Copie `.env.example` para `.env` e preencha:
   - `APP_PASSWORD_HASH`: veja [Gerar o hash da senha](#gerar-o-hash-da-senha);
   - `SESSION_SECRET`: um texto aleatório e longo;
   - SMTP do e-mail remetente. No Gmail, crie uma [senha de app](https://myaccount.google.com/apppasswords);
   - `KINDLE_EMAIL` e `KINDLE_PROFILE` do seu modelo.
3. Cadastre o e-mail remetente como aprovado na Amazon: **Conteúdo e dispositivos → Preferências →
   Configurações de documentos pessoais → Lista de e-mails aprovados**.
4. Rode `docker compose up -d --build`.
5. Abra `http://localhost:8000`.

No uso local o `docker-compose.yml` publica o app só em `127.0.0.1`, desliga `SECURE_COOKIES`
(senão o navegador não guarda o cookie em `http://`) e desliga o login (`LOGIN_ENABLED=false`): o app abre direto, sem senha. Para abrir pelo celular na mesma rede, troque a porta
do app para `"8000:8000"` no compose, sabendo que ele fica aberto para a rede local.

O PC só precisa estar ligado para navegar e enviar. Depois de entregues, os mangás ficam no Kindle.

## Variáveis de ambiente de segurança

| Variável | Para que serve |
|---|---|
| `LOGIN_ENABLED` | `true` (padrão) exige senha. O `docker-compose.yml` local usa `false`, que só é aceito com `SECURE_COOKIES=false`; o `docker-compose.prod.yml` religa. |
| `APP_PASSWORD_HASH` | Hash argon2 da senha. Obrigatória com o login ligado. A antiga `APP_PASSWORD` não funciona mais. |
| `SESSION_SECRET` | Assina o cookie de sessão. |
| `SECURE_COOKIES` | `true` (padrão) envia o cookie só por HTTPS. `false` só no desenvolvimento local. |
| `TRUSTED_PROXY_IPS` | IPs de proxies confiáveis. Só deles o app aceita o `CF-Connecting-IP` como IP do visitante. O uvicorn roda com `--no-proxy-headers`, senão ele trocaria o IP do proxy pelo do `X-Forwarded-For` e o `CF-Connecting-IP` nunca seria lido. |
| `TUNNEL_TOKEN` | Token do Cloudflare Tunnel (só em produção). |

## Gerar o hash da senha

Com Docker (não precisa subir o Suwayomi):

```
docker compose run --rm --no-deps mangakindle python password_hash.py
```

Ou no venv local: `.venv\Scripts\python app\password_hash.py`.

O comando pede a senha duas vezes (mínimo de 8 caracteres) e imprime uma linha que começa com `$argon2id$`. Copie essa linha para o `.env`.

O hash tem vários `$`, e o Docker Compose interpreta `$nome` como variável. Confirmado com `docker compose config`
(Compose v5.3.1), existem duas formas corretas:

```
# 1) Aspas simples: o valor é literal (recomendado)
APP_PASSWORD_HASH='$argon2id$v=19$m=65536,t=3,p=4$...$...'

# 2) Sem aspas, cada "$" vira "$$"
APP_PASSWORD_HASH=$$argon2id$$v=19$$m=65536,t=3,p=4$$...$$...
```

Sem aspas e sem `$$`, ou com aspas duplas, o Compose troca os trechos por vazio e o login nunca funciona.
Não misture as formas: `$$` dentro de aspas simples fica literal e quebra o hash.

## Segurança

- Login com senha única (argon2), sessões guardadas no servidor (`data/app/seguranca.sqlite`) com validade de 7 dias.
  **Sair** e **Encerrar todas as sessões** invalidam a sessão no servidor.
- Limite de tentativas: 5 falhas em 15 minutos bloqueiam o IP por 15 minutos. Falhas de login são registradas no log com o IP.
- Todos os formulários POST exigem token CSRF.
- Cabeçalhos de segurança em todas as respostas (CSP restritiva, `X-Content-Type-Options`, `Referrer-Policy`,
  `Permissions-Policy`, `frame-ancestors 'none'`). `/docs`, `/redoc` e `/openapi.json` ficam desligados.
- O proxy de imagens (`/imagem`) só aceita capas, ícones de extensão e ícones de fonte do Suwayomi.
- O app roda como usuário comum (uid 1000), com sistema de arquivos somente leitura. Só `/data` (volume) e `/tmp` são graváveis.

## Deploy numa VPS com Cloudflare Tunnel e Access

O app não abre nenhuma porta na VPS: o `cloudflared` conecta de dentro para fora, e só o Cloudflare chega ao app.

1. **Criar o túnel.** No painel Cloudflare Zero Trust, abra a área de Tunnels, crie um túnel do tipo *Cloudflared*
   e copie o **token**. Ponha em `TUNNEL_TOKEN` no `.env` da VPS.
2. **DNS e rota.** No túnel, adicione um *Public hostname*, por exemplo `manga.seudominio.com`, com serviço
   `HTTP` e URL `mangakindle:8000`. O Cloudflare cria o registro DNS (CNAME) sozinho. O domínio precisa estar na sua conta Cloudflare.
3. **Cloudflare Access.** Em Zero Trust, crie uma aplicação *Self-hosted* para o mesmo hostname, com uma política
   **Allow** cuja regra *Emails* seja só `<seu-email>`. Sem a política, o Access bloqueia todo mundo. Teste numa janela anônima.
4. **Subir na VPS** (com o `.env` pronto, `SECURE_COOKIES` não precisa ser mexido). Em Linux, o app roda
   com o usuário de uid 1000 e precisa gravar em `data/app`: crie a pasta e ajuste o dono antes
   (`mkdir -p data/app && sudo chown -R 1000:1000 data/app`).

   ```
   docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
   ```

   O override remove as portas do app e do Suwayomi, liga `SECURE_COOKIES` e fixa o IP do `cloudflared` (`172.30.0.2`)
   como único proxy confiável. A rede interna usa `172.30.0.0/24`; se essa faixa já existir na VPS, troque nos
   dois lugares do `docker-compose.prod.yml`.
5. **Conferir:** `docker compose -f docker-compose.yml -f docker-compose.prod.yml ps` deve mostrar os três serviços `healthy`,
   e `http://<ip-da-vps>:8000` não deve responder.

### Backup

Tudo que importa está em `data/`: `data/app` (histórico e segurança) e `data/suwayomi` (extensões e biblioteca).
Pare os serviços (`docker compose stop`) e copie a pasta `data/` para um local fora da VPS. O `.env` também precisa de cópia segura.

## Uso

1. **Extensões:** cole o link do repositório de extensões que você usa no Mihon e instale as extensões.
   A URL precisa ser `https://` e terminar em `.json` ou `.pb`. Um repositório que funciona bem, com várias
   fontes em português:

   ```
   https://raw.githubusercontent.com/FelipeGFA/extensoes/refs/heads/repo/index.pb
   ```
2. **Buscar:** escolha a fonte e busque o título.
3. **Mangá:** marque os capítulos (até 200 por envio) e clique em **Enviar selecionados pro Kindle**.
4. **Envios:** acompanhe a fila. Se der erro, use **Tentar de novo**: só os capítulos que ainda não chegaram são reenviados.

Capítulos são juntados em um EPUB por envio, até `MAX_ATTACHMENT_MEGABYTES`. Seleções maiores viram vários EPUBs.

## Organização no Kindle

O Send to Kindle não permite escolher uma coleção, então o app usa os metadados:

- **Título:** `[Origem] Mangá - Cap. 1-10`. Ordenando a biblioteca por título, cada origem fica agrupada.
- **Autor:** o nome da origem. Ordenando por autor, a origem também agrupa.

Se quiser coleções de verdade, crie uma por origem no Kindle (**Biblioteca → ⋯ → Criar coleção**)
e adicione os novos volumes a ela. As coleções sincronizam entre dispositivos.

## Desenvolvimento

```
python -m venv .venv
$env:PIP_CACHE_DIR = "Z:\caches\pip"
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest
.venv\Scripts\pip-audit -r app\requirements.txt
```

Os testes não leem o `.env`. Para rodar o app fora do Docker, defina as variáveis do `.env.example` no ambiente
(com `SECURE_COOKIES=false` e `DATA_DIRECTORY` apontando para uma pasta local) e rode `uvicorn main:app_with_security_headers --no-proxy-headers` dentro de `app/`.

A API GraphQL do Suwayomi fica em `http://127.0.0.1:4567/api/graphql`, exposta só no localhost para depuração.

## Licença

MIT. Veja o arquivo [LICENSE](LICENSE).
