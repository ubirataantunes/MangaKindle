# MangaKindle

App web para escolher mangás nas mesmas extensões do Mihon e enviá-los ao Kindle por e-mail,
já convertidos para EPUB com leitura da direita para a esquerda.

- **Suwayomi-Server** roda as extensões do Mihon/Tachiyomi fora do Android.
- **KCC (Kindle Comic Converter)** converte as páginas para o tamanho de tela do seu Kindle.
- **MangaKindle** (este app) tem busca, seleção de capítulos, favoritos, marcação de lidos, fila de envio e histórico.

## Como rodar

1. Instale o [Docker Desktop](https://www.docker.com/products/docker-desktop/).
2. Copie `.env.example` para `.env` e preencha:
   - `SMTP_USERNAME` e `SMTP_PASSWORD`: o Gmail que vai enviar e a [senha de app](#senha-de-app-do-gmail) dele;
   - `KINDLE_EMAIL` e `KINDLE_PROFILE`: veja [Dados do Kindle](#dados-do-kindle);
   - `SESSION_SECRET`: um texto aleatório e longo (qualquer sequência grande de letras e números).
3. Libere o Gmail remetente na Amazon (passo 3 de [Dados do Kindle](#dados-do-kindle)).
4. Rode `docker compose up -d --build`.
5. Abra `http://localhost:8000`.

O PC só precisa estar ligado para navegar e enviar. Depois de entregues, os mangás ficam no Kindle.

Para abrir pelo celular na mesma rede Wi-Fi, troque a porta do app para `"8000:8000"` no `docker-compose.yml`
e acesse `http://<ip-do-pc>:8000`. Nesse caso, vale [ligar a senha](#ligar-a-senha).

## Senha de app do Gmail

O Gmail não deixa apps enviarem e-mail com a senha normal da conta. É preciso gerar uma **senha de app**:

1. Ative a **verificação em duas etapas** na conta Google: [myaccount.google.com/security](https://myaccount.google.com/security)
   → *Como você faz login no Google* → *Verificação em duas etapas*. Sem ela, a opção de senha de app não aparece.
2. Abra [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords).
3. Dê um nome (por exemplo, `MangaKindle`) e clique em **Criar**.
4. O Google mostra uma senha de 16 letras. Copie para `SMTP_PASSWORD` no `.env` (com ou sem os espaços).
   Ela só aparece uma vez; se perder, apague e crie outra.

Se você usar outro provedor de e-mail, ajuste `SMTP_HOST` e `SMTP_PORT` (465 usa SSL direto; as outras portas usam STARTTLS).

O Gmail aceita até **500 e-mails a cada 24 horas**. O app conta os envios e para antes de passar do limite
(a tela **Envios** mostra quantos já foram). Ajuste em `MAX_EMAILS_PER_DAY` se o seu limite for outro.

## Dados do Kindle

1. **E-mail do Kindle (`KINDLE_EMAIL`):** na Amazon, abra **Conteúdo e dispositivos → Dispositivos**, escolha o
   seu Kindle e copie o endereço **E-mail** (termina em `@kindle.com`).
2. **Modelo (`KINDLE_PROFILE`):** na mesma tela aparece o nome do aparelho. Use o perfil da tabela:

   | Kindle | Perfil |
   |---|---|
   | Kindle 8ª e 10ª geração | `K810` |
   | Kindle 11ª geração (2022) | `K11` |
   | Paperwhite 3 e 4 | `KPW34` |
   | Paperwhite 5 / Signature | `KPW5` |
   | Paperwhite 2024 | `KPW6` |
   | Oasis 2 e 3 | `KO` |
   | Scribe | `KS` |
   | Colorsoft | `KCS` |

   O perfil define o tamanho das páginas. Com o perfil errado, o mangá fica com bordas ou cortado.
3. **Liberar o remetente:** em **Conteúdo e dispositivos → Preferências → Configurações de documentos pessoais →
   Lista de e-mails aprovados**, adicione o Gmail de `SMTP_USERNAME`. Sem isso, a Amazon descarta os envios.

## Ligar a senha

Por padrão o app abre direto, sem senha (`LOGIN_ENABLED=false`), porque fica acessível só no seu PC.
Para exigir senha:

1. Gere o hash da senha (o comando pede a senha duas vezes e imprime uma linha começando com `$argon2id$`):

   ```
   docker compose run --rm --no-deps mangakindle python password_hash.py
   ```

   No Windows, rode no PowerShell; no Git Bash, use `winpty docker compose run ...`.
2. No `.env`, coloque `LOGIN_ENABLED=true` e o hash **entre aspas simples** (ele tem vários `$`):

   ```
   APP_PASSWORD_HASH='$argon2id$v=19$m=65536,t=3,p=4$...$...'
   ```
3. Rode `docker compose up -d` de novo.

Com a senha ligada, 5 tentativas erradas em 15 minutos bloqueiam o acesso por 15 minutos.

## Uso

1. **Extensões:** cole o link do repositório de extensões que você usa no Mihon e instale as extensões.
   A URL precisa ser `https://` e terminar em `.json` ou `.pb`. Um repositório que funciona bem, com várias
   fontes em português:

   ```
   https://raw.githubusercontent.com/FelipeGFA/extensoes/refs/heads/repo/index.pb
   ```
2. **Buscar:** escolha a fonte e busque o título.
3. **Mangá:** marque os capítulos (toque em qualquer lugar da linha) e clique em **Enviar pro Kindle**.
   Use **Lido** e **Até aqui** para controlar o que você já leu.
4. **Envios:** acompanhe a fila. Se der erro, use **Tentar de novo**: só os capítulos que ainda não chegaram são reenviados.

Capítulos são juntados em um EPUB por envio, até `MAX_ATTACHMENT_MEGABYTES`. Seleções maiores viram vários EPUBs.

## Organização no Kindle

O Send to Kindle não permite escolher uma coleção, então o app usa os metadados:

- **Título:** `[Origem] Mangá - Cap. 1-10`. Ordenando a biblioteca por título, cada origem fica agrupada.
- **Autor:** o nome da origem. Ordenando por autor, a origem também agrupa.

Se quiser coleções de verdade, crie uma por origem no Kindle (**Biblioteca → ⋯ → Criar coleção**)
e adicione os novos volumes a ela. As coleções sincronizam entre dispositivos.

## Backup

Tudo que importa está em `data/`: `data/app` (histórico, favoritos e lidos) e `data/suwayomi` (extensões e biblioteca).
Pare os serviços (`docker compose stop`) e copie a pasta `data/` junto com o `.env`.

## Desenvolvimento

```
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest
```

Os testes não leem o `.env`. Para rodar o app fora do Docker, defina as variáveis do `.env.example` no ambiente
(com `SECURE_COOKIES=false` e `DATA_DIRECTORY` apontando para uma pasta local) e rode
`uvicorn main:app_with_security_headers --no-proxy-headers` dentro de `app/`.

A API GraphQL do Suwayomi fica em `http://127.0.0.1:4567/api/graphql`, exposta só no localhost para depuração.

## Licença

MIT. Veja o arquivo [LICENSE](LICENSE).
