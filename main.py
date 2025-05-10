#!/usr/bin/env python3
import os
import time
import requests
import random
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

def build_kb(rows):
    return {"keyboard": rows, "resize_keyboard": True, "one_time_keyboard": True}

# —————————————————————————————————————————————
#                   Карты и логика
# —————————————————————————————————————————————
RANKS = ['6','7','8','9','J','Q','K','A']
SUITS = ['♠','♥','♦','♣']
FULL = [r + s for r in RANKS for s in SUITS]  # 24 карты

def parse_card(c): return c[:-1], c[-1]

def beats(att, dfn, trump):
    r1, s1 = parse_card(att)
    r2, s2 = dfn
    if s1 == s2 and RANKS.index(r2) > RANKS.index(r1):
        return True
    if s2 == trump and s1 != trump:
        return True
    return False

# —————————————————————————————————————————————
#           Оценка распределения руки оппонента
# —————————————————————————————————————————————
def estimate_opponent_distribution(state, trials=200):
    """
    Particle filter: строим вероятности карт в руках оппонента
    на основании оставшихся в колоде карт и числа карт у оппонента.
    """
    rem = [c for c in FULL if c not in state["gone"] and c not in state["my"]]
    counts = Counter()
    for _ in range(trials):
        sample = random.sample(rem, state["opp"])
        for c in sample:
            counts[c] += 1
    total = sum(counts.values())
    if total == 0:
        # равновероятно
        return {c: 1/len(rem) for c in rem}
    return {c: counts[c]/total for c in rem}

def weighted_choice(population, weights, k):
    """
    Выбираем k элементов из population по весам weights
    (может повторяться — используем replace=False, но при малых остатках можно True).
    """
    return list(np.random.choice(population, size=k, replace=False, p=weights))

# —————————————————————————————————————————————
#                AI-стратегии с учётом distrib
# —————————————————————————————————————————————
def mc_best_attack(state, trials=80):
    hand, opp, gone, trump = state["my"], state["opp"], state["gone"], state["trump"]
    # оценить distribution оппонента
    opp_dist = estimate_opponent_distribution(state, trials=200)
    rem = list(opp_dist.keys())
    probs = np.array([opp_dist[c] for c in rem])
    probs = probs / probs.sum()
    scores = Counter()
    for card in hand:
        win = 0
        for _ in range(trials):
            opph = weighted_choice(rem, probs, opp)
            if not any(beats(card, parse_card(o), trump) for o in opph):
                win += 1
        scores[card] = win
    return max(scores, key=scores.get)

def mc_best_defense(att, state, trials=80):
    hand, opp, gone, trump = state["my"], state["opp"], state["gone"], state["trump"]
    opp_dist = estimate_opponent_distribution(state, trials=200)
    rem = list(opp_dist.keys())
    probs = np.array([opp_dist[c] for c in rem])
    probs = probs / probs.sum()
    candidates = [c for c in hand if beats(att, parse_card(c), trump)]
    if not candidates:
        return None
    scores = Counter()
    for card in candidates:
        win = 0
        for _ in range(trials):
            opph = weighted_choice(rem, probs, opp)
            if not any(beats(card, parse_card(o), trump) for o in opph):
                win += 1
        scores[card] = win
    return max(scores, key=scores.get)

def do_otb(state):
    draws = min(state["max"] - len(state["my"]), state["deck"])
    state["deck"] -= draws
    draws2 = min(state["max"] - state["opp"], state["deck"])
    state["deck"] -= draws2
    state["pending_pickup"] = draws
    return f"Раунд окончен.\nВы берёте: {draws}, соперник берёт: {draws2}.\nОсталось в колоде: {state['deck']}."

# —————————————————————————————————————————————
#               Клавиатуры
# —————————————————————————————————————————————
def kb_trump():    return build_kb([[s] for s in SUITS])
def kb_cards(av):  return build_kb([av[i:i+4] for i in range(0,len(av),4)] + [["✅ Готово"]])
def kb_start():    return build_kb([["Я","Соперник"]])
def kb_actions():  return build_kb([["⚔️ walk","📊 stat"]])
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
    "gone":set(),"last_att":None,
    "pending_pickup":0
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

            # 1) /start
            if t in ("/start","/init") or s["stage"]=="start":
                s.update(stage="choose_trump", my=[], gone=set(),
                         pending_pickup=0, last_att=None)
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

            # 3) ввод карт
            if s["stage"]=="enter_cards":
                if t=="✅ Готово":
                    if len(s["my"])<6:
                        send(ch, f"Нужно 6, выбрано {len(s['my'])}", kb_cards(s["available"]))
                    else:
                        s["max"] = 6
                        s["gone"] = set(s["my"])
                        s["stage"]="confirm_first"
                        send(ch, "Кто ходит первым?", kb_start())
                elif t in s["available"]:
                    s["my"].append(t)
                    s["available"].remove(t)
                    send(ch, f"Выбрано {len(s['my'])}/6", kb_cards(s["available"]))
                else:
                    send(ch, "Нажмите карту или ✅ Готово.")
                continue

            # 4) первый ход
            if s["stage"]=="confirm_first" and t in ("Я","Соперник"):
                s["turn"] = "me" if t=="Я" else "opp"
                s["stage"] = "play"
                s["opp"] = 6
                s["deck"] = 12
                send(ch, "Игра началась! Ваш ход:", kb_actions())
                continue

            # 5) play
            if s["stage"]=="play":
                if t=="⚔️ walk":
                    card = mc_best_attack(s)
                    s["last_att"] = card
                    s["my"].remove(card)
                    s["gone"].add(card)
                    s["stage"] = "await_def"
                    defense_pool = [c for c in FULL if c not in s["gone"] and c not in s["my"]]
                    send(ch, f"⚔️ Вы походили: {card}\nСоперник отбивается:", kb_defense(defense_pool))
                elif t=="📊 stat":
                    tm,opp = len(s["my"]), s["opp"]
                    p = tm/(tm+opp)*100 if tm+opp>0 else 0
                    send(ch, f"Шанс ≈ {p:.0f}% (у тебя {tm}, опп {opp}, deck {s['deck']})", kb_actions())
                else:
                    send(ch, "Нажмите ⚔️ walk или 📊 stat.", kb_actions())
                continue

            # 6) await_def
            if s["stage"]=="await_def":
                if t=="Не отбился":
                    res = do_otb(s)
                    s["stage"]="pickup"
                    send(ch, res + "\nВыберите карты для добора:", kb_cards(
                        [c for c in FULL if c not in s["gone"] and c not in s["my"]]
                    ))
                elif t in FULL and t not in s["gone"] and t not in s["my"]:
                    s["gone"].add(t)
                    send(ch, f"Соперник отбился {t}.")
                    res = do_otb(s)
                    s["stage"]="pickup"
                    send(ch, res + "\nВыберите карты для добора:", kb_cards(
                        [c for c in FULL if c not in s["gone"] and c not in s["my"]]
                    ))
                else:
                    send(ch, "Выберите карту защиты или «Не отбился».", kb_defense([]))
                continue

            # 7) pickup
            if s["stage"]=="pickup":
                if t=="✅ Готово":
                    s["pending_pickup"] = 0
                    s["stage"]="play"
                    send(ch, "Продолжаем игру:", kb_actions())
                elif t in s["available"] and s["pending_pickup"]>0:
                    s["my"].append(t)
                    s["available"].remove(t)
                    s["pending_pickup"] -= 1
                    send(ch, f"Добавлено {t}. Осталось взять {s['pending_pickup']}.", kb_cards(s["available"]))
                else:
                    send(ch, "Нажмите карту или ✅ Готово.", kb_cards(s["available"]))
                continue

            # fallback
            send(ch, "Введите /start для новой игры.")
        time.sleep(1)

if __name__=="__main__":
    main()