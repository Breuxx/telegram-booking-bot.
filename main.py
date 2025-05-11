#!/usr/bin/env python3
import os, sys, time, random, math, copy
from collections import Counter, defaultdict
import requests
import numpy as np

print("=== USING UPDATED MAIN.PY ===")  # <-- контрольная строка

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    print("Error: BOT_TOKEN not set", file=sys.stderr)
    sys.exit(1)
API_URL = f"https://api.telegram.org/bot{TOKEN}"

RANKS = ['6','7','8','9','J','Q','K','A']
SUITS = ['♠','♥','♦','♣']
FULL = [r+s for r in RANKS for s in SUITS]

def get_updates(offset=None):
    r = requests.get(f"{API_URL}/getUpdates", params={"timeout":30,"offset":offset})
    return r.json().get("result", [])

def send_message(chat_id, text, keyboard=None):
    payload = {"chat_id":chat_id, "text":text, "parse_mode":"HTML"}
    if keyboard:
        payload["reply_markup"] = {"keyboard":keyboard, "resize_keyboard":True, "one_time_keyboard":True}
    requests.post(f"{API_URL}/sendMessage", json=payload)

def parse_card(c): return c[:-1], c[-1]
def beats(att, dfn, trump):
    r1,s1 = parse_card(att); r2,s2 = dfn
    return (s1==s2 and RANKS.index(r2)>RANKS.index(r1)) or (s2==trump and s1!=trump)

# MCTS omitted for brevity — используем ту же реализацию, что и перед этим
# ...

# Стадии (stage) строго:
# start → choose_trump → enter_cards → choose_first → play → defense → pickup → play → …

sessions = defaultdict(lambda:{
    "stage":"start","trump":None,"available":[],"my":[],
    "opp":0,"deck":0,"max":0,"gone":set(),
    "last_att":None,"pending":0,"turn":None
})

def main():
    offset=None
    while True:
        for upd in get_updates(offset):
            offset=upd["update_id"]+1
            m=upd.get("message")
            if not m or "text" not in m: continue
            ch,txt=m["chat"]["id"],m["text"].strip()
            s=sessions[ch]

            # 1) START
            if s["stage"]=="start" or txt.lower() in ("/start","/init"):
                s.update(stage="choose_trump", my=[], gone=set(), pending=0, last_att=None)
                send_message(ch, "Выберите козырь:", [[s] for s in SUITS])
                continue

            # 2) CHOOSE TRUMP
            if s["stage"]=="choose_trump" and txt in SUITS:
                s["trump"]=txt; s["stage"]="enter_cards"
                s["available"]=FULL.copy(); s["my"]=[]
                send_message(ch, f"Козырь {txt}\nВыберите 6 карт:", [s[i:i+4] for i in range(0,24,4)]+[["✅ Готово"]])
                continue

            # 3) ENTER CARDS
            if s["stage"]=="enter_cards":
                if txt=="✅ Готово":
                    if len(s["my"])<6:
                        send_message(ch, f"Нужно 6, выбрано {len(s['my'])}", [s["available"][i:i+4] for i in range(0,len(s["available"]),4)]+[["✅ Готово"]])
                    else:
                        s["max"]=6; s["gone"]=set(s["my"]); s["stage"]="choose_first"
                        send_message(ch, "Кто ходит первым?", [["Я","Соперник"]])
                elif txt in s["available"]:
                    s["my"].append(txt); s["available"].remove(txt)
                    send_message(ch, f"Выбрано {len(s['my'])}/6", [s["available"][i:i+4] for i in range(0,len(s["available"]),4)]+[["✅ Готово"]])
                else:
                    send_message(ch, "Нажмите карту или ✅ Готово")
                continue

            # 4) CHOOSE FIRST
            if s["stage"]=="choose_first" and txt in ("Я","Соперник"):
                s["turn"]="me" if txt=="Я" else "opp"; s["stage"]="play"
                s["opp"]=6; s["deck"]=12
                send_message(ch, "Игра началась!", [["⚔️ walk","📊 stat"]])
                continue

            # 5) PLAY
            if s["stage"]=="play":
                if txt=="⚔️ walk":
                    # вычисляем mcts...
                    s["stage"]="defense"
                    send_message(ch, "⚔️ Вы ходите ...\nСоперник отбивается:", [["..."]])
                    continue
                if txt=="📊 stat":
                    send_message(ch, "Шанс ...", [["⚔️ walk","📊 stat"]])
                    continue

            # 6) DEFENSE
            if s["stage"]=="defense":
                # аналогично — после всех веток ставим continue
                continue

            # 7) PICKUP
            if s["stage"]=="pickup":
                continue

            # 8) FALLBACK
            send_message(ch, "Введите /start для новой игры")
        time.sleep(1)

if __name__=="__main__":
    main()