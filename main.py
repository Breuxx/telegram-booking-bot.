#!/usr/bin/env python3
import os, sys, time, random, math, copy
from collections import Counter, defaultdict
import requests
import numpy as np

# —————————————————————————————————————————————
#                        Настройки
# —————————————————————————————————————————————
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    print("Error: BOT_TOKEN not set", file=sys.stderr)
    sys.exit(1)
API_URL = f"https://api.telegram.org/bot{TOKEN}"

RANKS = ['6','7','8','9','J','Q','K','A']
SUITS = ['♠','♥','♦','♣']
FULL = [r+s for r in RANKS for s in SUITS]

# —————————————————————————————————————————————
#                      HTTP-обёртки
# —————————————————————————————————————————————
def get_updates(offset=None):
    r = requests.get(f"{API_URL}/getUpdates", params={"timeout":30,"offset":offset})
    return r.json().get("result", [])

def send_message(chat_id, text, keyboard=None):
    payload = {"chat_id":chat_id, "text":text, "parse_mode":"HTML"}
    if keyboard:
        payload["reply_markup"] = {"keyboard":keyboard, "resize_keyboard":True, "one_time_keyboard":True}
    requests.post(f"{API_URL}/sendMessage", json=payload)

# —————————————————————————————————————————————
#                    Карты и логика
# —————————————————————————————————————————————
def parse_card(c): return c[:-1], c[-1]
def beats(att, dfn, trump):
    r1,s1 = parse_card(att); r2,s2 = dfn
    return (s1==s2 and RANKS.index(r2)>RANKS.index(r1)) or (s2==trump and s1!=trump)

def estimate_dist(state, trials=200):
    rem = [c for c in FULL if c not in state['gone'] and c not in state['my']]
    cnt = Counter()
    for _ in range(trials):
        cnt.update(random.sample(rem, state['opp']))
    total = sum(cnt.values())
    if total==0:
        return {c:1/len(rem) for c in rem}
    return {c: cnt[c]/total for c in rem}

# —————————————————————————————————————————————
#                         MCTS
# —————————————————————————————————————————————
class MCTSState:
    def __init__(self,my,opp,deck,gone,trump,turn,last_att=None):
        self.my=list(my); self.opp=opp; self.deck=deck
        self.gone=set(gone); self.trump=trump
        self.turn=turn; self.last_att=last_att

    def clone(self): return copy.deepcopy(self)

    def possible_moves(self):
        moves = {}
        if self.turn=='me' and self.last_att is None:
            hand = [c for c in self.my if parse_card(c)[1]!=self.trump]
            hand = [c for c in hand if parse_card(c)[0]!='A'] or self.my
            for c in hand:
                st = self.clone()
                st.my.remove(c); st.gone.add(c)
                st.last_att = c; st.turn = 'opp'
                moves[c] = st
        elif self.turn=='opp' and self.last_att:
            for c in [x for x in self.my if beats(self.last_att, parse_card(x), self.trump)]:
                st = self.clone()
                st.my.remove(c); st.gone.add(c)
                st.last_att = None; st.turn = 'me'
                moves['def_'+c] = st
            st = self.clone()
            st.opp += 1; st.last_att = None; st.turn = 'me'
            moves['take'] = st
        return moves

    def is_terminal(self):
        return not self.my or (self.opp==0 and self.deck==0)

    def reward(self):
        return 1 if self.opp==0 else 0

class Node:
    def __init__(self,state,parent=None):
        self.state=state; self.parent=parent
        self.children={}; self.wins=0; self.visits=0

    def ucb(self, child):
        return child.wins/child.visits + math.sqrt(2*math.log(self.visits)/child.visits)

def mcts(root_state, iters=300):
    root = Node(root_state)
    for _ in range(iters):
        node = root
        while node.children:
            node = max(node.children.values(), key=lambda c: node.ucb(c))
        moves = node.state.possible_moves()
        if moves and node.visits>0:
            for mv, st in moves.items():
                node.children[mv] = Node(st, node)
            node = random.choice(list(node.children.values()))
        sim = node.state.clone()
        while not sim.is_terminal():
            pm = sim.possible_moves()
            if not pm: break
            sim = random.choice(list(pm.values()))
        res = sim.reward()
        while node:
            node.visits += 1
            node.wins   += res
            node = node.parent
    if not root.children: return None
    return max(root.children.items(), key=lambda kv: kv[1].visits)[0]

# —————————————————————————————————————————————
#                      Клавиатуры
# —————————————————————————————————————————————
def kb_trump():   return [[s] for s in SUITS]
def kb_cards(av): return [av[i:i+4] for i in range(0,len(av),4)] + [["✅ Готово"]]
def kb_first():   return [["Я","Соперник"]]
def kb_play():    return [["⚔️ walk","📊 stat"]]
def kb_def(av):   return [av[i:i+4] for i in range(0,len(av),4)] + [["Не отбился"]]

# —————————————————————————————————————————————
#                      Сессии
# —————————————————————————————————————————————
sessions = defaultdict(lambda: {
    "stage":"start","trump":None,"available":[], "my":[],
    "opp":0,"deck":0,"max":0,"gone":set(),
    "last_att":None,"pending":0,"turn":None
})

# —————————————————————————————————————————————
#                    Главный цикл
# —————————————————————————————————————————————
def main():
    offset = None
    while True:
        for upd in get_updates(offset):
            offset = upd["update_id"] + 1
            msg = upd.get("message")
            if not msg or "text" not in msg: continue
            ch, txt = msg["chat"]["id"], msg["text"].strip()
            s = sessions[ch]

            # старт
            if txt.lower() in ("/start","/init") or s["stage"]=="start":
                s.update(stage="choose_trump", my=[], gone=set(), pending=0, last_att=None)
                send_message(ch, "Выберите козырь:", kb_trump())
                continue

            # выбор козыря
            if s["stage"]=="choose_trump" and txt in SUITS:
                s["trump"]=txt; s["stage"]="enter_cards"
                s["available"]=FULL.copy(); s["my"]=[]
                send_message(ch, f"Козырь: {txt}\nВыберите 6 карт:", kb_cards(s["available"]))
                continue

            # ввод карт
            if s["stage"]=="enter_cards":
                if txt=="✅ Готово":
                    if len(s["my"])<6:
                        send_message(ch, f"Нужно 6 карт, выбрано {len(s['my'])}", kb_cards(s["available"]))
                    else:
                        s["max"]=6; s["gone"]=set(s["my"]); s["stage"]="choose_first"
                        send_message(ch, "Кто ходит первым?", kb_first())
                elif txt in s["available"]:
                    s["my"].append(txt); s["available"].remove(txt)
                    send_message(ch, f"Выбрано {len(s['my'])}/6", kb_cards(s["available"]))
                else:
                    send_message(ch, "Нажмите карту или ✅ Готово", kb_cards(s["available"]))
                continue

            # первый ход
            if s["stage"]=="choose_first" and txt in ("Я","Соперник"):
                s["turn"]="me" if txt=="Я" else "opp"
                s["stage"]="play"; s["opp"]=6; s["deck"]=12
                send_message(ch, "Игра началась!", kb_play())
                continue

            # атака
            if s["stage"]=="play":
                if txt=="⚔️ walk":
                    st = MCTSState(s["my"], s["opp"], s["deck"], s["gone"], s["trump"], "me")
                    mv = mcts(st, iters=500)
                    card = mv
                    s["last_att"]=card; s["my"].remove(card); s["gone"].add(card)
                    s["stage"]="defense"
                    defenders = [c for c in s["my"] if beats(card, parse_card(c), s["trump"])]
                    send_message(ch, f"⚔️ Вы ходите {card}\nСоперник отбивается:", kb_def(defenders))
                    continue
                if txt=="📊 stat":
                    tm,op = len(s["my"]), s["opp"]
                    pct = tm/(tm+op)*100 if tm+op else 0
                    send_message(ch, f"Шанс ≈ {pct:.0f}%", kb_play())
                    continue

            # защита
            if s["stage"]=="defense":
                if txt=="Не отбился":
                    draws = min(s["max"]-len(s["my"]), s["deck"])
                    s["deck"]-=draws; s["pending"]=draws; s["stage"]="pickup"
                    pool=[c for c in FULL if c not in s["gone"] and c not in s["my"]]
                    send_message(ch, f"Соперник не отбился. Добор {draws} карт:", kb_cards(pool))
                    continue
                if txt in s["my"] and beats(s["last_att"], parse_card(txt), s["trump"]):
                    s["my"].remove(txt); s["gone"].add(txt)
                    draws = min(s["max"]-len(s["my"]), s["deck"])
                    s["deck"]-=draws; s["pending"]=draws; s["stage"]="pickup"
                    pool=[c for c in FULL if c not in s["gone"] and c not in s["my"]]
                    send_message(ch, f"Соперник отбился {txt}. Добор {draws} карт:", kb_cards(pool))
                    continue

            # добор
            if s["stage"]=="pickup":
                if txt=="✅ Готово":
                    s["pending"]=0; s["stage"]="play"
                    send_message(ch, "Продолжаем раунд", kb_play())
                elif txt in s["available"] and s["pending"]>0:
                    s["my"].append(txt); s["available"].remove(txt); s["pending"]-=1
                    send_message(ch, f"Взяли {txt}, осталось взять {s['pending']}", kb_cards(s["available"]))
                else:
                    send_message(ch, "Нажмите карту или ✅ Готово", kb_cards(s["available"]))
                continue

            # fallback
            send_message(ch, "Введите /start для новой игры")
        time.sleep(1)

if __name__=="__main__":
    main()