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
    data = {"chat_id": chat, "text": text, "parse_mode": "HTML"}
    if kb: data["reply_markup"] = kb
    requests.post(API + "/sendMessage", json=data)

def build_kb(rows):
    return {"keyboard": rows, "resize_keyboard": True, "one_time_keyboard": True}

# —————————————————————————————————————————————
#                   Карты и логика
# —————————————————————————————————————————————
RANKS = ['6','7','8','9','J','Q','K','A']
SUITS = ['♠','♥','♦','♣']
FULL = [r+s for r in RANKS for s in SUITS]  # 24 карты

def parse_card(c): return c[:-1], c[-1]

def beats(att, dfn, trump):
    r1,s1 = parse_card(att); r2,s2 = dfn
    if s1==s2 and RANKS.index(r2)>RANKS.index(r1): return True
    if s2==trump and s1!=trump: return True
    return False

def mc_best_attack(state, trials=80):
    hand, opp, gone, trump = state["my"], state["opp"], state["gone"], state["trump"]
    remaining = [c for c in FULL if c not in gone and c not in hand]
    scores = Counter()
    for card in hand:
        win = 0
        for _ in range(trials):
            opph = np.random.choice(remaining, opp, replace=False)
            if not any(beats(card, parse_card(o), trump) for o in opph):
                win += 1
        scores[card] = win
    # выбираем карту с максимальным числом непринятия
    return max(scores, key=scores.get)

def do_otb(state):
    # добор карт: сначала вы, потом оппонент
    draws = min(state["max"] - len(state["my"]), state["deck"])
    state["my"] += ["?"] * draws
    state["deck"] -= draws
    draws2 = min(state["max"] - state["opp"], state["deck"])
    state["opp"] += draws2
    state["deck"] -= draws2
    return f"Раунд окончен.\nДобрали: вы +{draws}, соперник +{draws2}.\nВ колоде: {state['deck']}"

# —————————————————————————————————————————————
#                   Клавиатуры
# —————————————————————————————————————————————
def kb_trump():   return build_kb([[s] for s in SUITS])
def kb_cards(av): return build_kb([av[i:i+4] for i in range(0,len(av),4)] + [["✅ Готово"]])
def kb_start():   return build_kb([["Я","Соперник"]])
def kb_actions(): return build_kb([["⚔️ walk","📊 stat"]])
def kb_defense(av):
    rows = [av[i:i+4] for i in range(0,len(av),4)]
    rows.append(["Не отбился"])
    return build_kb(rows)

# —————————————————————————————————————————————
#                   Сессии
# —————————————————————————————————————————————
sessions = defaultdict(lambda: {
    "stage":"start","trump":None,
    "available":[], "my":[],
    "opp":0,"deck":0,"max":0,
    "gone":set(),"last_att":None
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

            # 1) /start или новое
            if t in ("/start","/init") or s["stage"]=="start":
                s.update(stage="choose_trump", my=[], gone=set())
                send(ch, "Выберите козырь:", kb_trump())
                continue

            # 2) выбор козыря
            if s["stage"]=="choose_trump" and t in SUITS:
                s["trump"] = t
                s["stage"] = "enter_cards"
                s["available"] = FULL.copy()
                s["my"] = []
                send(ch, f"Козырь: {t}\nВыберите 6 карт:", kb_cards(s["available"]))
                continue

            # 3) ввод своих 6 карт
            if s["stage"]=="enter_cards":
                if t=="✅ Готово":
                    if len(s["my"])<6:
                        send(ch, f"Нужно 6 карт, выбрано {len(s['my'])}", kb_cards(s["available"]))
                    else:
                        s["max"] = 6
                        s["gone"] = set(s["my"])
                        s["stage"] = "confirm_first"
                        send(ch, "Кто ходит первым?", kb_start())
                elif t in s["available"]:
                    s["my"].append(t)
                    s["available"].remove(t)
                    send(ch, f"Выбрано {len(s['my'])}/6", kb_cards(s["available"]))
                else:
                    send(ch, "Нажмите карту или ✅ Готово.")
                continue

            # 4) выбор первого хода
            if s["stage"]=="confirm_first" and t in ("Я","Соперник"):
                s["turn"] = "me" if t=="Я" else "opp"
                s["stage"] = "play"
                # из 24 карт: 6 мои, 6 соперника, 12 в колоде
                s["opp"] = 6
                s["deck"] = 12
                send(ch, "Игра началась! Ваш ход:", kb_actions())
                continue

            # 5) стадия игры
            if s["stage"]=="play":
                # 5.1 атака
                if t=="⚔️ walk":
                    card = mc_best_attack(s)
                    s["last_att"] = card
                    s["my"].remove(card)
                    s["gone"].add(card)
                    s["stage"] = "await_def"
                    # клавиатура защиты: все карты (24) за вычетом my и gone
                    defense_pool = [c for c in FULL if c not in s["gone"] and c not in s["my"]]
                    send(ch, f"⚔️ Вы походили: {card}\nСоперник отбивается:", kb_defense(defense_pool))
                # 5.2 статистика
                elif t=="📊 stat":
                    tm, opp = len(s["my"]), s["opp"]
                    p = tm/(tm+opp)*100 if tm+opp>0 else 0
                    send(ch, f"Шанс ≈ {p:.0f}% (у тебя {tm}, опп {opp}, deck {s['deck']})", kb_actions())
                else:
                    send(ch, "Нажмите ⚔️ walk или 📊 stat.", kb_actions())
                continue

            # 6) обработка защиты
            if s["stage"]=="await_def":
                if t=="Не отбился":
                    res = do_otb(s)
                    s["stage"] = "play"
                    send(ch, "Соперник взял!\n" + res, kb_actions())
                elif t in FULL and t not in s["gone"] and t not in s["my"]:
                    # соперник отбился картой t
                    s["gone"].add(t)
                    send(ch, f"Соперник отбился {t}.")
                    res = do_otb(s)
                    s["stage"] = "play"
                    send(ch, "Бито!\n" + res, kb_actions())
                else:
                    send(ch, "Выберите карту защиты или «Не отбился».", kb_defense([]))
                continue

            # fallback
            send(ch, "Введите /start для новой игры.")
        time.sleep(1)

if __name__=="__main__":
    main()