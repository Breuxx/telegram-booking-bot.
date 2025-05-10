#!/usr/bin/env python3
import os, time, requests
from collections import defaultdict, Counter
import numpy as np

# —————————————————————————————————————————————
#                 Настройки и API
# —————————————————————————————————————————————
TOKEN = os.getenv("BOT_TOKEN", "ВАШ_ТОКЕН_ЗДЕСЬ")
API = f"https://api.telegram.org/bot{TOKEN}"

def get_updates(offset=None):
    r = requests.get(API+"/getUpdates", params={"offset":offset, "timeout":30})
    return r.json().get("result", [])

def send(chat, text, kb=None):
    data = {"chat_id":chat, "text":text, "parse_mode":"HTML"}
    if kb: data["reply_markup"] = kb
    requests.post(API+"/sendMessage", json=data)

def kb(rows):
    return {"keyboard":rows, "resize_keyboard":True, "one_time_keyboard":True}

# —————————————————————————————————————————————
#                   Карты и логика
# —————————————————————————————————————————————
RANKS = ['6','7','8','9','J','Q','K','A']
SUITS = ['♠','♥','♦','♣']
FULL = [r+s for r in RANKS for s in SUITS]

def beats(att, dfn, trump):
    r1,s1 = att[0], att[1]
    r2,s2 = dfn
    if s1==s2 and RANKS.index(r2)>RANKS.index(r1): return True
    if s2==trump and s1!=trump: return True
    return False

def mc_attack(state, trials=80):
    hand, opp, gone, trump = state["my"], state["opp"], state["gone"], state["trump"]
    rem = [c for c in FULL if c not in gone and c not in hand]
    score=Counter()
    for card in hand:
        w=0
        for _ in range(trials):
            opph = np.random.choice(rem, opp, replace=False)
            if not any(beats((card[0],card[1]), (o[0],o[1]), trump) for o in opph):
                w+=1
        score[card]+=w
    best = max(score, key=score.get)
    return best

def do_otb(state):
    draws = min(state["max"]-len(state["my"]), state["deck"])
    state["my"] += ["?"]*draws
    state["deck"] -= draws
    draws2= min(state["max"]-state["opp"], state["deck"])
    state["opp"] += draws2
    state["deck"] -= draws2
    return f"Раунд окончен.\nДобрано: тебе +{draws}, сопернику +{draws2}.\nОсталось в колоде {state['deck']}."

# —————————————————————————————————————————————
#                  Клавиатуры
# —————————————————————————————————————————————
def kb_trump():      return kb([[s] for s in SUITS])
def kb_cards(av):    return kb([av[i:i+4] for i in range(0,len(av),4)]+[["✅ Готово"]])
def kb_start():      return kb([["Я","Соперник"]])
def kb_actions():    return kb([["⚔️ walk","📊 stat"]])
def kb_result():     return kb([["Бито","Взять"]])

# —————————————————————————————————————————————
#                   Сессии
# —————————————————————————————————————————————
sessions = defaultdict(lambda:{
    "stage":"start","trump":None,
    "available":[], "my":[], "opp":0, "deck":0, "max":0, "gone":set()
})

# —————————————————————————————————————————————
#                   Главный цикл
# —————————————————————————————————————————————
def main():
    offset=None
    while True:
        for upd in get_updates(offset):
            offset=upd["update_id"]+1
            msg = upd.get("message")
            if not msg or "text" not in msg: continue
            ch, t = msg["chat"]["id"], msg["text"].strip()
            s = sessions[ch]

            # 1) /start → выбор козыря
            if t in ("/start","/init") or s["stage"]=="start":
                s.update(stage="choose_trump", my=[], gone=set())
                send(ch, "Выберите козырь:", kb_trump())
                continue

            # 2) козырь
            if s["stage"]=="choose_trump" and t in SUITS:
                s["trump"]=t; s["stage"]="enter_cards"
                s["available"]=FULL.copy(); s["my"]=[]
                send(ch, f"Козырь: {t}\nВыберите 6 карт:", kb_cards(s["available"]))
                continue

            # 3) ввод 6 карт
            if s["stage"]=="enter_cards":
                if t=="✅ Готово":
                    if len(s["my"])<6:
                        send(ch,f"Нужно 6, выбрано {len(s['my'])}", kb_cards(s["available"]))
                    else:
                        s["max"]=6; s["gone"]=set(s["my"])
                        s["stage"]="confirm_first"
                        send(ch,"Кто ходит первым?", kb_start())
                elif t in s["available"]:
                    s["my"].append(t); s["available"].remove(t)
                    send(ch,f"Выбрано {len(s['my'])}/6", kb_cards(s["available"]))
                else:
                    send(ch,"Нажмите карту или ✅ Готово.")
                continue

            # 4) кто первый
            if s["stage"]=="confirm_first" and t in ("Я","Соперник"):
                s["turn"]="me" if t=="Я" else "opp"
                s["stage"]="play"
                send(ch,"Игра началась! Выберите действие:", kb_actions())
                continue

            # 5) игровой этап
            if s["stage"]=="play":
                # 5.1 атака
                if t=="⚔️ walk":
                    card = mc_attack(s)
                    s["my"].remove(card); s["gone"].add(card)
                    s["stage"]="resolve"  # ждем результат
                    send(ch, f"⚔️ Ход: {card}\n\nВыберите результат:", kb_result())
                # 5.2 статистика
                elif t=="📊 stat":
                    total=len(s["my"]); opp=s["opp"]
                    p= total/(total+opp)*100 if total+opp>0 else 0
                    send(ch,f"Шанс ≈ {p:.0f}% (у тебя {total}, опп {opp}, deck {s['deck']})")
                else:
                    send(ch,"Нажмите ⚔️ walk или 📊 stat.", kb_actions())
                continue

            # 6) результат раунда
            if s["stage"]=="resolve" and t in ("Бито","Взять"):
                res = do_otb(s)
                s["stage"]="play"
                send(ch, f"{t}!\n{res}\n\nСнова:", kb_actions())
                continue

            # fallback
            send(ch,"Напишите /start для новой игры.")
        time.sleep(1)

if __name__=="__main__":
    main()