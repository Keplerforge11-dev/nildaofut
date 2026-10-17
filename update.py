#!/usr/bin/env python3
"""Robô do NildãoFut.

Roda sozinho no GitHub (veja .github/workflows/update.yml) e atualiza o arquivo data.json:
  - jogos, placares e tabela do Brasileirão: football-data.org (gratuito, precisa da chave FOOTBALL_DATA_KEY)
  - canais de transmissão do Brasileirão: tabela do blog da Claro
  - Libertadores, Sul-Americana e Copa do Brasil: páginas dos campeonatos da Gazeta Esportiva
  - notícias dos times: feed RSS de cada time na Gazeta Esportiva

Regra de ouro: se uma fonte falhar ou mudar de formato, os dados antigos ficam como estavam
e o app nunca mostra uma tela vazia. O aviso aparece na página da execução no GitHub.
"""
import html
import json
import os
import re
import sys
import time
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Sao_Paulo")
UA = "Mozilla/5.0 (compatible; NildaoFutBot/1.0; app de uso familiar)"
DATA_FILE = "data.json"
DEBUG_DIR = "debug"
API = "https://api.football-data.org/v4/competitions/BSA"
CLARO_URL = "https://www.claro.com.br/blog/tv/brasileirao"
CLARO_BASE = "https://www.claro.com.br/blog/tv/"
GAZETA = "https://www.gazetaesportiva.com/"
COPAS = [
    ("sa-lib", GAZETA + "campeonatos/libertadores-da-america/"),
    ("sa-sul", GAZETA + "campeonatos/copa-sulamericana/"),
    ("br-copa", GAZETA + "campeonatos/copa-do-brasil/"),
]
# endereços que o blog da Claro pode usar para as copas (só guardo uma cópia para eu conferir)
CLARO_COPAS = {
    "libertadores": ["libertadores", "copa-libertadores"],
    "sulamericana": ["sul-americana", "copa-sul-americana", "sulamericana"],
    "copa-do-brasil": ["copa-do-brasil"],
}
# time -> nome do feed na Gazeta (Mirassol e Remo não têm feed)
FEEDS = {
    "Atlético-MG": "atletico-mg", "Athletico-PR": "atletico-pr", "Bahia": "bahia", "Botafogo": "botafogo",
    "Red Bull Bragantino": "bragantino", "Chapecoense": "chapecoense", "Corinthians": "corinthians",
    "Coritiba": "coritiba", "Cruzeiro": "cruzeiro", "Flamengo": "flamengo", "Fluminense": "fluminense",
    "Grêmio": "gremio", "Internacional": "inter-rs", "Palmeiras": "palmeiras", "Santos": "santos",
    "São Paulo": "sao-paulo", "Vasco": "vasco", "Vitória": "vitoria",
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
    """Acha o time do app dentro de um nome longo (ex.: 'CR Flamengo')."""
    n = norm(name)
    for app, kws in CLUBS:
        if any(contem(n, k) for k in kws):
            return app
    return None


def canon_exato(name):
    """Só aceita o nome quando ele é o do time (evita confundir 'Santos Laguna' com o Santos)."""
    n = norm(name)
    for app, kws in CLUBS:
        if n == norm(app) or n in kws:
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


def guardar_copia(arquivo, corpo):
    """Guarda uma cópia da página para eu conferir o formato quando uma fonte muda."""
    caminho = os.path.join(DEBUG_DIR, arquivo)
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
    guardar_copia("claro.html", corpo)
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


def guardar_paginas_claro_das_copas():
    """Tenta achar páginas de canais das copas no blog da Claro e guarda uma cópia, sem usar os dados ainda."""
    for nome, slugs in CLARO_COPAS.items():
        arquivo = "claro-%s.html" % nome
        if os.path.exists(os.path.join(DEBUG_DIR, arquivo)):
            continue
        for slug in slugs:
            try:
                corpo = get(CLARO_BASE + slug)
            except Exception:
                continue
            if len(corpo) > 5000:
                guardar_copia(arquivo, corpo)
                print("página da Claro encontrada:", slug)
                break


# ---------- Copas: páginas dos campeonatos da Gazeta Esportiva ----------
RE_JOGO = re.compile(r'<a [^>]*class="campeonato-mata-mata__jogo"[^>]*>(.*?)</a>', re.S)
RE_DATA = re.compile(r'<span class="date">\s*(\d{2})/(\d{2})\s+(\d{2}):(\d{2})\s*<b>.*?</b>\s*(.*?)\s*</span>', re.S)
RE_CASA = re.compile(r'class="equipe-mandante">.*?<span>([^<]+)</span>', re.S)
RE_FORA = re.compile(r'class="equipe-visitante">.*?<span>([^<]+)</span>', re.S)
RE_PCASA = re.compile(r'class="placar__home">([^<]*)<')
RE_PFORA = re.compile(r'class="placar__visitante">([^<]*)<')


def nome_copa(raw):
    raw = html.unescape(raw).strip()
    return canon_exato(raw) or raw


def ler_copa(campeonato, corpo, agora):
    jogos = []
    for bloco in RE_JOGO.findall(corpo):
        d, c, f = RE_DATA.search(bloco), RE_CASA.search(bloco), RE_FORA.search(bloco)
        if not (d and c and f):
            continue
        dia, mes, hora, minuto = (int(x) for x in d.groups()[:4])
        ano = agora.year
        dt = datetime(ano, mes, dia, hora, minuto, tzinfo=TZ)
        if dt < agora - timedelta(days=200):
            dt = dt.replace(year=ano + 1)
        elif dt > agora + timedelta(days=200):
            dt = dt.replace(year=ano - 1)
        g = {
            "c": campeonato,
            "date": dt.strftime("%Y-%m-%d"),
            "t": dt.strftime("%H:%M"),
            "h": nome_copa(c.group(1)),
            "a": nome_copa(f.group(1)),
            "tv": "",
            "v": html.unescape(d.group(5)).strip(),
        }
        pc, pf = RE_PCASA.search(bloco), RE_PFORA.search(bloco)
        if pc and pf and pc.group(1).strip().isdigit() and pf.group(1).strip().isdigit() and dt + timedelta(minutes=100) < agora:
            g["s"] = [int(pc.group(1)), int(pf.group(1))]
        jogos.append(g)
    return jogos


def buscar_copas():
    agora = datetime.now(TZ)
    novos, ok = [], 0
    for campeonato, url in COPAS:
        try:
            jogos = ler_copa(campeonato, get(url), agora)
            if not jogos:
                raise ValueError("nenhum jogo reconhecido na página")
            novos += jogos
            ok += 1
        except Exception as e:
            aviso("copa %s não atualizou, mantive os dados antigos: %s" % (campeonato, e))
    return novos, ok


def mesclar_copas(antigos, novos):
    por_jogo = {(g["c"], g["h"], g["a"]): g for g in antigos}
    for g in novos:
        antigo = por_jogo.get((g["c"], g["h"], g["a"]), {})
        g["tv"] = g["tv"] or antigo.get("tv", "")
        por_jogo[(g["c"], g["h"], g["a"])] = g
    return list(por_jogo.values())


# ---------- Notícias: feed RSS de cada time na Gazeta Esportiva ----------
def buscar_noticias(antigas):
    noticias = {k: list(v) for k, v in antigas.items()}
    ok, falhas = 0, []
    for clube, slug in FEEDS.items():
        try:
            corpo = get("%stimes/%s/feed/" % (GAZETA, slug))
            if clube == "Santos":
                guardar_copia("feed-santos.xml", corpo)
            itens = list(ET.fromstring(corpo.encode("utf-8")).iter("item"))
            if not itens:
                raise ValueError("feed vazio")
            atual = {x["u"]: x for x in noticias.get(clube, [])}
            for it in itens:
                titulo = html.unescape((it.findtext("title") or "").strip())
                url = (it.findtext("link") or "").strip()
                if not titulo or not url.startswith(GAZETA):
                    continue
                try:
                    dt = parsedate_to_datetime(it.findtext("pubDate")).astimezone(TZ)
                except Exception:
                    dt = datetime.now(TZ)
                atual[url] = {"t": titulo, "d": dt.strftime("%d/%m/%Y"), "u": url, "ts": int(dt.timestamp())}
            noticias[clube] = sorted(atual.values(), key=lambda x: x["ts"], reverse=True)[:5]
            ok += 1
        except Exception as e:
            falhas.append("%s: %s" % (clube, e))
        time.sleep(0.4)
    if ok == 0:
        raise ValueError("nenhum feed de time respondeu (%s)" % "; ".join(falhas[:2]))
    if falhas:
        aviso("%d feeds de times falharam, por exemplo %s" % (len(falhas), falhas[0]))
    return noticias


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

    # Brasileirão
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
        brasileirao = novos
    else:
        brasileirao = [g for g in jogos_antes if g["c"] == "br-a"]

    # Copas
    copas_antes = [g for g in jogos_antes if g["c"] != "br-a"]
    novas, ok = buscar_copas()
    copas = mesclar_copas(copas_antes, novas) if novas else copas_antes
    status["copas"] = "ok" if ok == len(COPAS) else ("parcial" if ok else "erro")
    guardar_paginas_claro_das_copas()

    dados["games"] = sorted(brasileirao + copas, key=lambda g: (g["date"], g["t"]))

    # Notícias
    try:
        dados["news"] = buscar_noticias(antes.get("news", {}))
        status["noticias"] = "ok"
    except Exception as e:
        status["noticias"] = "erro"
        aviso("notícias não atualizaram, mantive as antigas: %s" % e)

    dados["updated"] = datetime.now(TZ).isoformat(timespec="minutes")
    dados["status"] = status
    ordem = ["updated", "status", "table", "games", "news"]
    gravar({k: dados[k] for k in ordem if k in dados})
    print("pronto:", status, "| avisos:", len(avisos))


if __name__ == "__main__":
    sys.exit(main())
