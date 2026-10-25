#!/usr/bin/env python3
"""Envia os jogos e placares do data.json para o Supabase (para o ranking de palpites).

Roda no GitHub Actions logo depois do update.py. Usa a chave service_role, que fica só no
Secret SUPABASE_SERVICE_KEY do GitHub. Nunca coloque essa chave em arquivo nenhum.

Se o Secret ainda não existir, o script avisa e termina sem erro (o app continua funcionando).
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

URL = os.environ.get("SUPABASE_URL", "https://djtqnswhjbixwavbbndx.supabase.co").rstrip("/")
KEY = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
DATA_FILE = "data.json"
FUSO = "-03:00"  # horário de Brasília (o Brasil não usa mais horário de verão)


def req(method, path, body=None, extra=None):
    h = {"apikey": KEY, "Authorization": "Bearer " + KEY, "Content-Type": "application/json"}
    h.update(extra or {})
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(URL + "/rest/v1/" + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            corpo = resp.read().decode("utf-8")
            return json.loads(corpo) if corpo else None
    except urllib.error.HTTPError as e:
        detalhe = e.read().decode("utf-8", "replace")[:400]
        raise RuntimeError("Supabase respondeu %s em %s: %s" % (e.code, path.split("?")[0], detalhe))


def linhas_do_feed():
    with open(DATA_FILE, encoding="utf-8") as f:
        jogos = json.load(f).get("games", [])
    com_placar, sem_placar, vistos = [], [], set()
    for g in jogos:
        if g.get("tbc"):  # horário ainda não confirmado: não libera palpite
            continue
        try:
            datetime.fromisoformat("%sT%s:00%s" % (g["date"], g["t"], FUSO))
        except (KeyError, ValueError):
            continue
        key = "%s|%s|%s" % (g["date"], g["h"], g["a"])
        if key in vistos:
            continue
        vistos.add(key)
        linha = {
            "key": key, "champ": g["c"], "home": g["h"], "away": g["a"],
            "kickoff": "%sT%s:00%s" % (g["date"], g["t"], FUSO),
            "active": True,
        }
        s = g.get("s")
        if isinstance(s, list) and len(s) == 2 and all(isinstance(x, int) and x >= 0 for x in s):
            linha["home_goals"], linha["away_goals"] = s
            com_placar.append(linha)
        else:
            sem_placar.append(linha)  # não manda gols: assim um placar já salvo nunca é apagado
    return com_placar, sem_placar


def enviar(linhas):
    for i in range(0, len(linhas), 200):
        req("POST", "games?on_conflict=key", linhas[i:i + 200],
            {"Prefer": "resolution=merge-duplicates,return=minimal"})


def main():
    if not KEY:
        print("AVISO: Secret SUPABASE_SERVICE_KEY não configurado; ranking de palpites não foi atualizado.")
        return 0
    com, sem = linhas_do_feed()
    total = len(com) + len(sem)
    if total < 100:
        print("AVISO: só %d jogos no data.json; não vou mexer no Supabase." % total)
        return 0
    enviar(com)
    enviar(sem)

    # jogo futuro que saiu da lista (adiado, mudou de dia): sai da lista de palpites
    feed = {l["key"] for l in com + sem}
    agora = (datetime.now(timezone.utc) + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ativos = req("GET", "games?select=key&active=eq.true&kickoff=gt." + urllib.parse.quote(agora) + "&limit=2000") or []
    sumiram = [a["key"] for a in ativos if a["key"] not in feed]
    for k in sumiram:
        req("PATCH", "games?key=eq." + urllib.parse.quote(k, safe=""), {"active": False},
            {"Prefer": "return=minimal"})
    print("Supabase: %d jogos enviados (%d com placar); %d tirados da lista." % (total, len(com), len(sumiram)))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # o robô principal não deve falhar por causa do ranking
        print("AVISO: não consegui atualizar o Supabase:", e)
        sys.exit(0)
