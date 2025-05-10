#!/usr/bin/env python3
import os, time, requests
from collections import defaultdict, Counter
import numpy as np

# —————————————————————————————————————————————
#               Конфигурация и API
# —————————————————————————————————————————————

TOKEN = os.getenv("BOT_TOKEN", "ВАШ_ТОКЕН_ЗДЕСЬ")
API = f"https://api.telegram.org/bot{TOKEN}"

def get_updates(offset=None, timeout=30):
    r = requests.get(API+"/getUpdates", params={"offset": offset, "timeout": timeout})
    return r.json().get("result", [])

def send_message(chat_id, text, keyboard=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if keyboard:
        payload["reply_markup"] = keyboard
    requests.post(API+"/sendMessage", json=payload)

def build_kb(rows):
    return {"keyboard": rows, "resize_keyboard": True, "one_time_keyboard": True}

# —————————————————————————————————————————————
#                   Карты и логика
# —————————————————————————————————————————————

RANKS = ['6','7','8','9','J','Q','K','A']
SUITS = ['♠','♥','♦','♣']
FULL_DECK = [r+s for r in RANKS for s in SUITS]

def parse_card(c): return c[:-1], c[-1]
def beats(att, dfn, trump):
    r1,s1 = parse_card(att); r2,s2 = dfn
    if s1==s2 and RANKS.index(r2)>RANKS.index(r1): return True
    if s2==trump and s1!=trump: return True
    return False

# быстрый Monte Carlo выбор (можно уменьшить trials для скорости)
def mc_best_attack(state, trials=100):
    my, opp, deck, gone, trump = state["my"], state["opp"], state["deck"], state["gone"], state["trump"]
    rem = [c for c in FULL_DECK if c not in gone and c not in my]
    scores = Counter()
    for card in my:
        win=0
        for _ in range(trials):
            hand = np.random.choice(rem, opp, replace=False)
            if not any(beats(card, parse_card(o), trump) for o in hand):
                win+=1
        scores[card]=win
    best = max(scores, key=scores.get)
    return best

def mc_best_defense(att, state, trials=100):
    my, opp, deck, gone, trump = state["my"], state["opp"], state["deck"], state["gone"], state["trump"]
    rem = [c for c in FULL_DECK if c not in gone and c not in my]
    cand = [c for c in my if beats(att, parse_card(c), trump)]
    if not cand: return None
    scores=Counter()
    for card in cand:
        win=0
        for _ in range(trials):
            hand = np.random.choice(rem, opp, replace=False)
            if not any(beats(card, parse_card(o), trump) for o in hand):
                win+=1
        scores[card]=win
    return max(scores, key=scores.get)

def do_otb(state):
    draws_me = min(state["max"]-len(state["my"]), state["deck"])
    state["my"] += ["?"]*draws_me
    state["deck"] -= draws_me
    draws_op = min(state["max"]-state["opp"], state["deck"])
    state["opp"] += draws_op
    state["deck"] -= draws_op
    return f"▶ Раунд окончен. Добрали: ты+{draws_me}, оппонент+{draws_op}. В колоде {state['deck']}."

# —————————————————————————————————————————————
#                 Клавиатуры-конструкторы
# —————————————————————————————————————————————

def kb_trump():       return build_kb([[s] for s in SUITS])
def kb_start():       return build_kb([["Я","Соперник"]])
def kb_actions():     return build_kb([["⚔️ walk","🛡️ def"],["🔄 otb","📊 stat"]])
def kb_cards(avail):
    rows=[]; row=[]
    for c in avail:
        row.append(c)
        if len(row)==4:
            rows.append(row); row=[]
    if row: rows.append(row)
    rows.append(["✅ Готово"])
    return build_kb(rows)

# —————————————————————————————————————————————
#                    Сессии
# —————————————————————————————————————————————

sessions = defaultdict(lambda: {
    "stage":"start","trump":None,"available":[],
    "my":[],"opp":0,"deck":0,"max":0,"gone":set(),
    "last_att":None
})

# —————————————————————————————————————————————
#                    Основной цикл
# —————————————————————————————————————————————

def main():
    offset=None
    while True:
        for upd in get_updates(offset):
            offset=upd["update_id"]+1
            m=upd.get("message")
            if not m or "text" not in m: continue
            chat, text = m["chat"]["id"], m["text"].strip()
            s = sessions[chat]

            # --- старт и выбор козыря ---
            if text in ("/start","/init") or s["stage"]=="start":
                s.update(stage="choose_trump", my=[], gone=set())
                send_message(chat,"Выбери козырь:", kb_trump())
                continue

            # --- козырь ---
            if s["stage"]=="choose_trump" and text in SUITS:
                s["trump"]=text; s["stage"]="enter_cards"
                s["available"]=FULL_DECK.copy(); s["my"]=[]
                send_message(chat,"Козырь: "+text+"\nВыбери 6 карт:", kb_cards(s["available"]))
                continue

            # --- ввод карт кнопками ---
            if s["stage"]=="enter_cards":
                if text=="✅ Готово":
                    if len(s["my"])<6:
                        send_message(chat,f"Нужно 6 карт, выбрано {len(s['my'])}", kb_cards(s["available"]))
                    else:
                        s["max"]=6; s["gone"]=set(s["my"])
                        s["stage"]="confirm_start"
                        send_message(chat,"Кто ходит первым?", kb_start())
                elif text in s["available"]:
                    s["my"].append(text); s["available"].remove(text)
                    send_message(chat,f"Выбрано {len(s['my'])}/6", kb_cards(s["available"]))
                else:
                    send_message(chat,"Нажми карту или ✅ Готово.")
                continue

            # --- кто ходит ---
            if s["stage"]=="confirm_start" and text in ("Я","Соперник"):
                s["turn"]= "me" if text=="Я" else "opp"
                s["stage"]="play"
                send_message(chat,"Играем — выбери действие:", kb_actions())
                continue

            # --- игра: атака/защита/отбой/стат ---
            if s["stage"]=="play":
                # Атака
                if text=="⚔️ walk":
                    # выбираем лучшую карту
                    card = mc_best_attack(s)
                    s["last_att"] = card
                    # обновляем руку и gone
                    s["my"].remove(card); s["gone"].add(card)
                    s["stage"]="await_defense"
                    send_message(chat,f"Атакую: {card}\nЖми 🛡️ def чтобы защититься.", build_kb([["🛡️ def"]]))
                # Защита
                elif text=="🛡️ def" and s["stage"]=="await_defense":
                    att = s["last_att"]
                    card = mc_best_defense(att, s)
                    if card:
                        s["my"].remove(card); s["gone"].add(card)
                        send_message(chat,f"Отбился: {card}")
                    else:
                        send_message(chat,"Нечем отбиться — берём.")
                    # завершили раунд
                    res = do_otb(s)
                    s["stage"]="play"
                    send_message(chat,res+"\nСнова выбирай действие:", kb_actions())
                # Завершить раунд вручную
                elif text=="🔄 otb":
                    res = do_otb(s)
                    send_message(chat,res+"\nДалее:", kb_actions())
                # Статистика
                elif text=="📊 stat":
                    total=len(s["my"]); opp=s["opp"]
                    p = total/(total+opp)*100 if (total+opp)>0 else 0
                    send_message(chat,f"Шанс ≈ {p:.0f}% (ты {total}, опп {opp}, deck {s['deck']})")
                else:
                    send_message(chat,"Выбери одну из кнопок.", kb_actions())
                continue

            # всё остальное
            send_message(chat,"Напиши /start чтобы начать заново.")
        time.sleep(1)

if __name__=="__main__":
    main()