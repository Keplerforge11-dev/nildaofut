#!/usr/bin/env python3
"""Robô do NildãoFut.

Roda sozinho no GitHub (veja .github/workflows/update.yml) e atualiza o arquivo data.json:
  - jogos, placares e tabela do Brasileirão: football-data.org (gratuito, precisa da chave FOOTBALL_DATA_KEY)
  - canais de transmissão: tabela do blog da Claro
  - notícias dos times: feed RSS da Gazeta Esportiva

Regra de ouro: se uma fonte falhar ou mudar de formato, os dados antigos ficam como estavam
e o app nunca mostra uma tela vazia. O aviso aparece na página da execução no GitHub.
"""
import json
import os
import re
import sys
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Sao_Paulo")
UA = "Mozilla/5.0 (compatible; NildaoFutBot/1.0; app de uso familiar)"
DATA_FILE = "data.json"
DEBUG_DIR = "debug"
API = "https://api.football-data.org/v4/competitions/BSA"
CLARO_URL = "https://www.claro.com.br/blog/tv/brasileirao"
FEED_URL = "https://www.gazetaesportiva.com/feedrss/"
GAZETA_COPAS = {
    "libertadores": "https://www.gazetaesportiva.com/campeonatos/libertadores-da-america/",
    "sulamericana": "https://www.gazetaesportiva.com/campeonatos/copa-sulamericana/",
    "copa-do-brasil": "https://www.gazetaesportiva.com/campeonatos/copa-do-brasil/",
}

# nome usado no app, palavras que identificam o time (sem acento, minúsculas)
CLUBS = [
    ("Flamengo", ["flamengo"]),
    ("Palmeiras", ["palmeiras"]),
    ("Athletico-PR", ["athletico", "paranaense"]),
    ("Fluminense", ["fluminense"]),
    ("Bahia", ["bahia"]),
    ("Cruzeiro", ["cruzeiro"]),
    ("Atlético-MG", ["atletico mg", "atletico mineiro", "mineiro"]),
    ("Santos", ["santos"]),
    ("Red Bull Bragantino", ["bragantino"]),
    ("São Paulo", ["sao paulo"]),
    ("Coritiba", ["coritiba"]),
    ("Vitória", ["vitoria"]),
    ("Botafogo", ["botafogo"]),
    ("Vasco", ["vasco"]),
    ("Mirassol", ["mirassol"]),
    ("Corinthians", ["corinthians"]),
    ("Internacional", ["internacional"]),
    ("Grêmio", ["gremio"]),
    ("Remo", ["remo"]),
    ("Chapecoense", ["chapecoense"]),
]
# nomes que também são palavras comuns: não servem para achar time pelo título de uma notícia
AMBIGUOS = {"Bahia", "Vitória", "Internacional", "Remo"}

CANAIS = {
    "globo": "TV Globo", "tv globo": "TV Globo", "sportv": "SporTV", "premiere": "Premiere",
    "cazetv": "CazéTV", "caze tv": "CazéTV", "tnt": "TNT Sports", "tnt sports": "TNT Sports",
    "espn": "ESPN", "prime video": "Prime Video", "disney": "Disney+",
}

avisos = []


def aviso(msg):
    print("AVISO:", msg)
    print("::warning::" + msg)
    avisos.append(msg)


def get(url, headers=None):
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9", **(headers or {})}
    )
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read().decode("utf-8", errors="replace")


def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def contem(n, kw):
    return re.search(r"\b" + re.escape(kw) + r"\b", n) is not None


def canon(name):
    n = norm(name)
    for app, kws in CLUBS:
        if any(contem(n, k) for k in kws):
            return app
    return None


def nome_time(t):
    for campo in ("name", "shortName"):
        c = canon(t.get(campo))
        if c:
            return c
    raw = t.get("shortName") or t.get("name") or "?"
    aviso("time sem correspondência no app: " + raw)
    return raw


def guardar_copia(nome, corpo):
    """Guarda uma cópia da página para eu conferir o formato quando uma fonte muda."""
    caminho = os.path.join(DEBUG_DIR, nome + ".html")
    if os.path.exists(caminho) and not os.environ.get("REFRESH_DEBUG"):
        return
    os.makedirs(DEBUG_DIR, exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(corpo)


# ---------- Brasileirão: football-data.org ----------
def buscar_brasileirao(chave):
    h = {"X-Auth-Token": chave}
    partidas = json.loads(get(API + "/matches", h))["matches"]
    classif = json.loads(get(API + "/standings", h))

    jogos = []
    for m in partidas:
        if not m.get("utcDate"):
            continue
        st = m.get("status")
        if st in ("CANCELLED", "POSTPONED", "SUSPENDED"):
            continue
        dt = datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00")).astimezone(TZ)
        g = {
            "c": "br-a",
            "date": dt.strftime("%Y-%m-%d"),
            "t": dt.strftime("%H:%M"),
            "h": nome_time(m["homeTeam"]),
            "a": nome_time(m["awayTeam"]),
            "tv": "",
            "v": m.get("venue") or "",
        }
        ft = (m.get("score") or {}).get("fullTime") or {}
        if st == "FINISHED" and ft.get("home") is not None and ft.get("away") is not None:
            g["s"] = [ft["home"], ft["away"]]
        elif st == "SCHEDULED":
            g["tbc"] = True
        jogos.append(g)

    tabela = None
    for s in classif.get("standings", []):
        if s.get("type") == "TOTAL":
            tabela = s["table"]
            break
    if not tabela or len(tabela) != 20:
        raise ValueError("tabela de classificação veio incompleta")
    linhas = [
        [r["position"], nome_time(r["team"]), r["points"], r["playedGames"], r["won"], r["draw"],
         r["lost"], r["goalsFor"], r["goalsAgainst"], r["goalDifference"]]
        for r in tabela
    ]
    if len(jogos) < 100:
        raise ValueError("lista de jogos veio incompleta (%d)" % len(jogos))
    return linhas, jogos


# ---------- Canais: blog da Claro ----------
class Linhas(HTMLParser):
    def __init__(self):
        super().__init__()
        self.linhas, self.linha, self.cel = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.linha = []
        elif tag in ("td", "th") and self.linha is not None:
            self.cel = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cel is not None and self.linha is not None:
            self.linha.append(re.sub(r"\s+", " ", "".join(self.cel)).strip())
            self.cel = None
        elif tag == "tr" and self.linha is not None:
            self.linhas.append(self.linha)
            self.linha = None

    def handle_data(self, data):
        if self.cel is not None:
            self.cel.append(data)


def limpar_canais(txt):
    saida = []
    for parte in re.split(r"\s*/\s*|\s*,\s*|\s+e\s+", txt):
        p = parte.strip()
        if p:
            saida.append(CANAIS.get(norm(p), p))
    return " / ".join(dict.fromkeys(saida))


def buscar_canais():
    corpo = get(CLARO_URL)
    guardar_copia("claro", corpo)
    p = Linhas()
    p.feed(corpo)
    mapa = {}
    for l in p.linhas:
        if len(l) >= 7 and re.match(r"^\d+\s*[ªa°o]", l[0]) and re.match(r"\d{2}/\d{2}/\d{4}", l[1]):
            h, a = canon(l[3]), canon(l[4])
            canais = limpar_canais(l[6])
            if h and a and canais:
                mapa[(h, a)] = {"tv": canais, "v": re.sub(r"\s*\(.*?\)\s*$", "", l[5]).strip()}
    if len(mapa) < 20:
        raise ValueError("tabela de canais não encontrada na página (%d linhas)" % len(mapa))
    return mapa


# ---------- Notícias: feed da Gazeta Esportiva ----------
def times_da_noticia(titulo, url):
    achados = set()
    m = re.search(r"/times/([a-z0-9-]+)/", url)
    if m:
        c = canon(m.group(1).replace("-", " "))
        if c:
            achados.add(c)
    n = norm(titulo)
    for app, kws in CLUBS:
        if app not in AMBIGUOS and any(contem(n, k) for k in kws):
            achados.add(app)
    return achados


def buscar_noticias(antigas):
    corpo = get(FEED_URL)
    guardar_copia("feed", corpo)
    raiz = ET.fromstring(corpo.encode("utf-8"))
    itens = list(raiz.iter("item"))
    if not itens:
        raise ValueError("feed sem notícias")
    noticias = {k: list(v) for k, v in antigas.items()}
    for it in itens:
        titulo = (it.findtext("title") or "").strip()
        url = (it.findtext("link") or "").strip()
        if not titulo or not url:
            continue
        try:
            dt = parsedate_to_datetime(it.findtext("pubDate")).astimezone(TZ)
        except Exception:
            dt = datetime.now(TZ)
        n = {"t": titulo, "d": dt.strftime("%d/%m/%Y"), "u": url, "ts": int(dt.timestamp())}
        for clube in times_da_noticia(titulo, url):
            atual = {x["u"]: x for x in noticias.get(clube, [])}
            atual[url] = n
            noticias[clube] = sorted(atual.values(), key=lambda x: x["ts"], reverse=True)[:5]
    return noticias


# ---------- Copas: guarda uma cópia das páginas da Gazeta para eu ajustar a leitura ----------
def copiar_paginas_das_copas():
    for nome, url in GAZETA_COPAS.items():
        if os.path.exists(os.path.join(DEBUG_DIR, nome + ".html")) and not os.environ.get("REFRESH_DEBUG"):
            continue
        try:
            guardar_copia(nome, get(url))
        except Exception as e:
            aviso("não consegui copiar a página %s: %s" % (nome, e))


def carregar():
    try:
        with open(DATA_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def gravar(d):
    partes = []
    for k, v in d.items():
        if k in ("games", "table"):
            partes.append(json.dumps(k) + ": [\n" + ",\n".join(json.dumps(x, ensure_ascii=False) for x in v) + "\n]")
        else:
            partes.append(json.dumps(k) + ": " + json.dumps(v, ensure_ascii=False))
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        f.write("{\n" + ",\n".join(partes) + "\n}\n")


def main():
    antes = carregar()
    dados = dict(antes)
    status = dict(antes.get("status", {}))
    jogos_antes = antes.get("games", [])
    chave = os.environ.get("FOOTBALL_DATA_KEY", "").strip()

    novos = None
    if not chave:
        status["brasileirao"] = "sem chave"
        aviso("a chave FOOTBALL_DATA_KEY não foi configurada nos Secrets do GitHub")
    else:
        try:
            tabela, novos = buscar_brasileirao(chave)
            dados["table"] = tabela
            status["brasileirao"] = "ok"
        except Exception as e:
            status["brasileirao"] = "erro"
            aviso("Brasileirão não atualizou, mantive os dados antigos: %s" % e)

    if novos is not None:
        try:
            canais = buscar_canais()
            status["canais"] = "ok"
        except Exception as e:
            canais = {}
            status["canais"] = "erro"
            aviso("canais não atualizaram, mantive os antigos: %s" % e)
        velhos = {(g["h"], g["a"]): g for g in jogos_antes if g["c"] == "br-a"}
        for g in novos:
            k = (g["h"], g["a"])
            c, o = canais.get(k, {}), velhos.get(k, {})
            g["tv"] = c.get("tv") or o.get("tv", "")
            g["v"] = c.get("v") or g.get("v") or o.get("v", "")
        sem_canal = [g for g in novos if "s" not in g and not g["tv"] and g["date"] >= datetime.now(TZ).strftime("%Y-%m-%d")]
        if sem_canal and status["canais"] == "ok":
            print("jogos futuros sem canal na fonte:", len(sem_canal))
        jogos = novos + [g for g in jogos_antes if g["c"] != "br-a"]
    else:
        jogos = jogos_antes
    dados["games"] = sorted(jogos, key=lambda g: (g["date"], g["t"]))

    try:
        dados["news"] = buscar_noticias(antes.get("news", {}))
        status["noticias"] = "ok"
    except Exception as e:
        status["noticias"] = "erro"
        aviso("notícias não atualizaram, mantive as antigas: %s" % e)

    copiar_paginas_das_copas()
    status.setdefault("copas", "manual")

    dados["updated"] = datetime.now(TZ).isoformat(timespec="minutes")
    dados["status"] = status
    ordem = ["updated", "status", "table", "games", "news"]
    gravar({k: dados[k] for k in ordem if k in dados})
    print("pronto:", status, "| avisos:", len(avisos))


if __name__ == "__main__":
    sys.exit(main())
