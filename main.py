#!/usr/bin/env python3
import os
import time
import requests
from collections import defaultdict, Counter
import numpy as np

# —————————————————————————————————————————————
#                   Настройки и API
# —————————————————————————————————————————————
TOKEN = os.getenv("BOT_TOKEN", "ВАШ_ТОКЕН_ЗДЕСЬ")
API = f"https://api.telegram.org/bot{TOKEN}"

def get_updates(offset=None):
    r = requests.get(API + "/getUpdates", params={"offset": offset, "timeout": 30})
    return r.json().get("result", [])

def send(chat, text, kb=None):
    payload = {"chat_id": chat, "text": text, "parse_mode": "HTML"}
    if kb:
        payload["reply_markup"] = kb
    requests.post(API + "/sendMessage", json=payload)

def kb(rows):
    return {"keyboard": rows, "resize_keyboard": True, "one_time_keyboard": True}

# —————————————————————————————————————————————
#                   Карты и логика
# —————————————————————————————————————————————
RANKS = ['6','7','8','9','J','Q','K','A']
SUITS = ['♠','♥','♦','♣']
FULL = [r+s for r in RANKS for s in SUITS]

def parse_card(c): return c[:-1], c[-1]

def beats(att, dfn, trump):
    r1,s1 = parse_card(att); r2,s2 = dfn
    if s1 == s2 and RANKS.index(r2) > RANKS.index(r1): return True
    if s2 == trump and s1 != trump: return True
    return False

# ——————— Гибридная стратегия атаки ———————
def get_attack_options(state, top_n=3, trials=80):
    hand, opp, gone, trump = state["my"], state["opp"], state["gone"], state["trump"]
    remaining = [c for c in FULL if c not in gone and c not in hand]
    # ранговая стоимость
    rank_score = {r: i+1 for i,r in enumerate(RANKS)}
    # кандидаты
    candidates = hand.copy()
    if not gone:
        candidates = [c for c in candidates if parse_card(c)[0] != 'A']
    scores = {}
    for card in candidates:
        # MC: шанс непринятия
        reject = 0
        for _ in range(trials):
            opph = np.random.choice(remaining, opp, replace=False)
            if not any(beats(card, parse_card(o), trump) for o in opph):
                reject += 1
        p_rej = reject / trials
        rank, suit = parse_card(card)
        cost = rank_score[rank]
        is_trump = (suit == trump)
        # весовая функция
        scores[card] = 0.7 * p_rej - 0.2 * cost - 0.1 * is_trump
    best = sorted(scores, key=lambda c: scores[c], reverse=True)
    return best[:top_n]

# ——————— Гибридная стратегия защиты ———————
def get_defense_options(att, state, top_n=3, trials=80):
    hand, opp, gone, trump = state["my"], state["opp"], state["gone"], state["trump"]
    candidates = [c for c in hand if beats(att, parse_card(c), trump)]
    if not candidates:
        return []
    remaining = [c for c in FULL if c not in gone and c not in hand]
    rank_score = {r: i+1 for i,r in enumerate(RANKS)}
    scores = {}
    for card in candidates:
        success = 0
        for _ in range(trials):
            opph = np.random.choice(remaining, opp, replace=False)
            if not any(beats(card, parse_card(o), trump) for o in opph):
                success += 1
        p_succ = success / trials
        rank, suit = parse_card(card)
        cost = rank_score[rank]
        is_trump = (suit == trump)
        scores[card] = 0.6 * p_succ - 0.3 * cost - 0.1 * is_trump
    best = sorted(scores, key=lambda c: scores[c], reverse=True)
    return best[:top_n]

def do_otb(state):
    draws = min(state["max"] - len(state["my"]), state["deck"])
    state["my"] += ["?"] * draws
    state["deck"] -= draws
    draws2 = min(state["max"] - state["opp"], state["deck"])
    state["opp"] += draws2
    state["deck"] -= draws2
    return f"Раунд окончен.\nДобрано: тебе +{draws}, оппоненту +{draws2}.\nВ колоде {state['deck']}."

# —————————————————————————————————————————————
#               Клавиатуры
# —————————————————————————————————————————————
def kb_trump():      return kb([[s] for s in SUITS])
def kb_cards(av):    return kb([av[i:i+4] for i in range(0,len(av),4)] + [["✅ Готово"]])
def kb_start():      return kb([["Я","Соперник"]])
def kb_actions():    return kb([["⚔️ walk","📊 stat"]])
def kb_attack(opts): return kb([opts, ["Другой","Отмена"]])
def kb_defense(opts): return kb([opts[i:i+4] for i in range(0,len(opts),4)] + [["Не отбился"]])

# —————————————————————————————————————————————
#                    Сессии
# —————————————————————————————————————————————
sessions = defaultdict(lambda: {
    "stage":"start","trump":None,"available":[], "my":[],
    "opp":0,"deck":0,"max":0,"gone":set(),
    "attack_opts": [], "last_att": None
})

# —————————————————————————————————————————————
#                   Основной цикл
# —————————————————————————————————————————————
def main():
    offset = None
    while True:
        for upd in get_updates(offset):
            offset = upd["update_id"] + 1
            msg = upd.get("message")
            if not msg or "text" not in msg:
                continue
            ch, t = msg["chat"]["id"], msg["text"].strip()
            s = sessions[ch]

            # 1) Старт
            if t in ("/start","/init") or s["stage"] == "start":
                s.update(stage="choose_trump", my=[], gone=set())
                send(ch, "Выберите козырь:", kb_trump())
                continue

            # 2) Козырь
            if s["stage"] == "choose_trump" and t in SUITS:
                s["trump"] = t; s["stage"] = "enter_cards"
                s["available"] = FULL.copy(); s["my"] = []
                send(ch, f"Козырь: {t}\nВыберите 6 карт:", kb_cards(s["available"]))
                continue

            # 3) Ввод карт
            if s["stage"] == "enter_cards":
                if t == "✅ Готово":
                    if len(s["my"]) < 6:
                        send(ch, f"Нужно 6, выбрано {len(s['my'])}", kb_cards(s["available"]))
                    else:
                        s["max"] = 6; s["gone"] = set(s["my"])
                        s["stage"] = "confirm_first"
                        send(ch, "Кто ходит первым?", kb_start())
                elif t in s["available"]:
                    s["my"].append(t); s["available"].remove(t)
                    send(ch, f"Выбрано {len(s['my'])}/6", kb_cards(s["available"]))
                else:
                    send(ch, "Нажмите карту или ✅ Готово.")
                continue

            # 4) Первый ход
            if s["stage"] == "confirm_first" and t in ("Я","Соперник"):
                s["turn"] = "me" if t == "Я" else "opp"
                s["stage"] = "play"
                send(ch, "Игра началась! Ваш ход:", kb_actions())
                continue

            # 5) Play
            if s["stage"] == "play":
                if t == "⚔️ walk":
                    opts = get_attack_options(s)
                    s["attack_opts"] = opts
                    s["stage"] = "choose_attack"
                    send(ch, "Выберите карту для атаки:", kb_attack(opts))
                elif t == "📊 stat":
                    tm,opp = len(s["my"]), s["opp"]
                    p = tm/(tm+opp)*100 if tm+opp>0 else 0
                    send(ch, f"Шанс ≈ {p:.0f}% (у тебя {tm}, опп {opp}, deck {s['deck']})", kb_actions())
                else:
                    send(ch, "Нажмите ⚔️ walk или 📊 stat.", kb_actions())
                continue

            # 6) Choose attack
            if s["stage"] == "choose_attack":
                if t in s["attack_opts"]:
                    card = t
                    s["last_att"] = card
                    s["my"].remove(card); s["gone"].add(card)
                    s["stage"] = "await_def"
                    # defense options
                    beaters = [c for c in FULL if c not in s["gone"] and beats(card, parse_card(c), s["trump"])]
                    send(ch, f"Атаковали {card}. Соперник отбивается:", kb_defense(beaters))
                elif t == "Другой":
                    s["attack_opts"] = s["attack_opts"][1:]
                    if not s["attack_opts"]:
                        send(ch, "Больше нет вариантов.", kb_actions()); s["stage"] = "play"
                    else:
                        send(ch, "Другой вариант:", kb_attack(s["attack_opts"]))
                else:
                    send(ch, "Выберите карту или «Другой».", kb_attack(s["attack_opts"]))
                continue

            # 7) Defense
            if s["stage"] == "await_def":
                if t == "Не отбился":
                    res = do_otb(s)
                    s["stage"] = "play"
                    send(ch, "Соперник взял!\n" + res, kb_actions())
                elif t in FULL and t not in s["gone"]:
                    card = t
                    s["gone"].add(card)
                    send(ch, f"Соперник отбился {card}.", None)
                    res = do_otb(s)
                    s["stage"] = "play"
                    send(ch, "Бито!\n" + res, kb_actions())
                else:
                    send(ch, "Выберите карту защиты или «Не отбился».", kb_defense([]))
                continue

            # fallback
            send(ch, "Введите /start для новой игры.")
        time.sleep(1)

if __name__ == "__main__":
    main()