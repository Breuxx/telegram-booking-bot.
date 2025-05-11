#!/usr/bin/env python3
import os, sys, time, random, math, copy
from collections import Counter, defaultdict
import numpy as np
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, CallbackContext

# ------------- Конфиг -------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    print("Error: BOT_TOKEN not set", file=sys.stderr)
    sys.exit(1)

# ------------- Карты и утилиты -------------
RANKS = ['6','7','8','9','J','Q','K','A']
SUITS = ['♠','♥','♦','♣']
FULL = [r+s for r in RANKS for s in SUITS]

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
        return {c: 1/len(rem) for c in rem}
    return {c: cnt[c]/total for c in rem}

# ------------- MCTS -------------
class MCTSState:
    def __init__(self,my,opp,deck,gone,trump,turn,last_att=None):
        self.my = list(my)
        self.opp = opp
        self.deck = deck
        self.gone = set(gone)
        self.trump = trump
        self.turn = turn
        self.last_att = last_att

    def clone(self): return copy.deepcopy(self)

    def possible_moves(self):
        moves = {}
        # моя атака
        if self.turn=='me' and self.last_att is None:
            hand = [c for c in self.my if parse_card(c)[1]!=self.trump]
            hand = [c for c in hand if parse_card(c)[0]!='A'] or self.my
            for c in hand:
                st = self.clone()
                st.my.remove(c); st.gone.add(c)
                st.last_att = c; st.turn='opp'
                moves[c] = st
        # защита оппонента
        elif self.turn=='opp' and self.last_att:
            for c in [x for x in self.my if beats(self.last_att, parse_card(x), self.trump)]:
                st = self.clone()
                st.my.remove(c); st.gone.add(c)
                st.last_att=None; st.turn='me'
                moves['def_'+c] = st
            st = self.clone()
            st.opp += 1; st.last_att=None; st.turn='me'
            moves['take'] = st
        return moves

    def is_terminal(self):
        return not self.my or (self.opp==0 and self.deck==0)

    def reward(self):
        return 1 if self.opp==0 else 0

class Node:
    def __init__(self,state,parent=None):
        self.state = state
        self.parent = parent
        self.children = {}
        self.wins = 0
        self.visits = 0

    def ucb(self, child):
        return child.wins/child.visits + math.sqrt(2*math.log(self.visits)/child.visits)

def mcts(root_state, iters=300):
    root = Node(root_state)
    for _ in range(iters):
        node = root
        # selection
        while node.children:
            node = max(node.children.values(), key=lambda c: node.ucb(c))
        # expansion
        moves = node.state.possible_moves()
        if moves and node.visits>0:
            for mv, st in moves.items():
                node.children[mv] = Node(st, node)
            node = random.choice(list(node.children.values()))
        # simulation
        sim = node.state.clone()
        while not sim.is_terminal():
            pm = sim.possible_moves()
            if not pm: break
            sim = random.choice(list(pm.values()))
        res = sim.reward()
        # backprop
        while node:
            node.visits += 1
            node.wins   += res
            node = node.parent
    if not root.children:
        return None
    return max(root.children.items(), key=lambda kv: kv[1].visits)[0]

# ------------- UI-helpers -------------
def make_trump_kb():
    kb = InlineKeyboardMarkup(row_width=4)
    for s in SUITS:
        kb.insert(InlineKeyboardButton(s, callback_data=f"trump|{s}"))
    return kb

def make_cards_kb(av, picked):
    kb = InlineKeyboardMarkup(row_width=4)
    for c in av:
        kb.insert(InlineKeyboardButton(c, callback_data=f"card|{c}"))
    kb.add(InlineKeyboardButton(f"✅ Готово ({picked}/6)", callback_data="card|done"))
    return kb

def make_first_kb():
    return InlineKeyboardMarkup().add(
        InlineKeyboardButton("Я", callback_data="first|me"),
        InlineKeyboardButton("Соперник", callback_data="first|opp")
    )

def make_actions_kb():
    return InlineKeyboardMarkup(row_width=2).add(
        InlineKeyboardButton("⚔️ Walk", callback_data="act|walk"),
        InlineKeyboardButton("📊 Stat", callback_data="act|stat")
    )

def make_def_kb(av):
    kb = InlineKeyboardMarkup(row_width=4)
    for c in av:
        kb.insert(InlineKeyboardButton(c, callback_data=f"def|{c}"))
    kb.add(InlineKeyboardButton("Не отбился", callback_data="def|take"))
    return kb

def make_pickup_kb(av, pending):
    kb = InlineKeyboardMarkup(row_width=4)
    for c in av:
        kb.insert(InlineKeyboardButton(c, callback_data=f"pick|{c}"))
    kb.add(InlineKeyboardButton(f"✅ Done ({pending})", callback_data="pick|done"))
    return kb

# ------------- Хранилище игр -------------
games = {}

# ------------- Хэндлеры -------------
def start(update: Update, _: CallbackContext):
    chat = update.effective_chat.id
    games[chat] = {
        "stage":"trump", "my":[], "available":FULL.copy(),
        "opp":0, "deck":0, "max":0, "gone":set(),
        "trump":None, "last_att":None, "pending":0, "turn":None
    }
    update.message.reply_text("Выберите козырь:", reply_markup=make_trump_kb())

def button(update: Update, _: CallbackContext):
    chat = update.effective_chat.id
    data = update.callback_query.data
    d = games[chat]
    cmd,val = data.split("|",1)
    cq = update.callback_query
    cq.answer()

    # 1) Trump
    if d["stage"]=="trump" and cmd=="trump":
        d["trump"]=val; d["stage"]="enter"
        cq.edit_message_text(f"Козырь: {val}\nВыберите 6 карт:", 
                             reply_markup=make_cards_kb(d["available"],0))
        return

    # 2) Cards
    if d["stage"]=="enter" and cmd=="card":
        if val=="done":
            if len(d["my"])<6:
                cq.answer("Нужно 6 карт!", show_alert=True); return
            d["max"]=6; d["gone"]=set(d["my"]); d["stage"]="first"
            cq.edit_message_text("Кто ходит первым?", reply_markup=make_first_kb())
        else:
            if val in d["available"] and len(d["my"])<6:
                d["my"].append(val); d["available"].remove(val)
            cq.edit_message_text(f"Выбрано {len(d['my'])}/6", 
                                 reply_markup=make_cards_kb(d["available"], len(d["my"])))
        return

    # 3) First
    if d["stage"]=="first" and cmd=="first":
        d["turn"]=val; d["stage"]="play"; d["opp"]=6; d["deck"]=12
        cq.edit_message_text("Игра началась!", reply_markup=make_actions_kb())
        return

    # 4) Play
    if d["stage"]=="play" and cmd=="act":
        if val=="walk":
            st = MCTSState(d["my"],d["opp"],d["deck"],d["gone"],d["trump"],"me")
            mv = mcts(st, iters=500)
            card = mv
            d["last_att"]=card; d["my"].remove(card); d["gone"].add(card)
            d["stage"]="def"
            beat = [c for c in d["my"] if beats(card, parse_card(c), d["trump"])]
            cq.edit_message_text(f"⚔️ Вы ходите {card}\nСоперник отбивается:", 
                                 reply_markup=make_def_kb(beat))
        else:
            tm,op = len(d["my"]), d["opp"]
            p = tm/(tm+op)*100 if tm+op else 0
            cq.answer(f"Шанс ≈ {p:.0f}%")
        return

    # 5) Defend / Take
    if d["stage"]=="def" and cmd=="def":
        # соперник не отбился
        if val=="take":
            draws = min(d["max"]-len(d["my"]), d["deck"])
            d["deck"] -= draws; d["pending"] = draws; d["stage"]="pickup"
            pool = [c for c in FULL if c not in d["gone"] and c not in d["my"]]
            cq.edit_message_text(f"Соперник взял. Добор {draws} карт:", 
                                 reply_markup=make_pickup_kb(pool, draws))
        else:
            # отбился
            d["my"].remove(val); d["gone"].add(val)
            draws = min(d["max"]-len(d["my"]), d["deck"])
            d["deck"] -= draws; d["pending"]=draws; d["stage"]="pickup"
            pool = [c for c in FULL if c not in d["gone"] and c not in d["my"]]
            cq.edit_message_text(f"Соперник отбился {val}. Добор {draws} карт:", 
                                 reply_markup=make_pickup_kb(pool, draws))
        return

    # 6) Pickup
    if d["stage"]=="pickup" and cmd=="pick":
        if val=="done":
            d["pending"]=0; d["stage"]="play"
            cq.edit_message_text("Продолжаем раунд:", reply_markup=make_actions_kb())
        else:
            if val in d["available"] and d["pending"]>0:
                d["my"].append(val); d["available"].remove(val); d["pending"]-=1
            pool = [c for c in FULL if c not in d["gone"] and c not in d["my"]]
            cq.edit_message_text(f"Взяли {val}, осталось {d['pending']}", 
                                 reply_markup=make_pickup_kb(pool, d['pending']))
        return

def main():
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CallbackQueryHandler(button))
    updater.start_polling()
    updater.idle()

if __name__=="__main__":
    main()