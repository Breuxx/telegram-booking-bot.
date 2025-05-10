#!/usr/bin/env python3
import os
import random
import math
import logging
import copy
from collections import Counter
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup
import numpy as np

API_TOKEN = os.getenv("BOT_TOKEN", "ВАШ_ТОКЕН_ЗДЕСЬ")
logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# —————————————————————————————————————————————
#    FSM состояния
# —————————————————————————————————————————————
class GameStates(StatesGroup):
    ChoosingTrump = State()
    EnterCards    = State()
    ChooseFirst   = State()
    Playing       = State()
    Defending     = State()
    PickingUp     = State()

# —————————————————————————————————————————————
#   Константы и утилиты для «мастер-AI»
# —————————————————————————————————————————————
RANKS = ['6','7','8','9','J','Q','K','A']
SUITS = ['♠','♥','♦','♣']
FULL = [r+s for r in RANKS for s in SUITS]  # 24 карты

def parse_card(c): return c[:-1], c[-1]
def beats(att, dfn, trump):
    r1,s1 = parse_card(att); r2,s2 = dfn
    return (s1==s2 and RANKS.index(r2)>RANKS.index(r1)) or (s2==trump and s1!=trump)

def estimate_dist(state, trials=200):
    rem=[c for c in FULL if c not in state['gone'] and c not in state['my']]
    cnt=Counter()
    for _ in range(trials):
        cnt.update(random.sample(rem, state['opp']))
    total=sum(cnt.values())
    return {c:(cnt[c]/total if total>0 else 1/len(rem)) for c in rem}

class MCTSState:
    def __init__(self, my, opp, deck, gone, trump, turn, last_att=None):
        self.my=list(my); self.opp=opp; self.deck=deck
        self.gone=set(gone); self.trump=trump
        self.turn=turn; self.last_att=last_att
    def clone(self): return copy.deepcopy(self)
    def possible_moves(self):
        moves={}
        # атака
        if self.turn=='me' and self.last_att is None:
            hand=[c for c in self.my if parse_card(c)[1]!=self.trump]
            hand=[c for c in hand if parse_card(c)[0]!='A'] or self.my
            for c in hand:
                st=self.clone(); st.my.remove(c); st.gone.add(c)
                st.last_att=c; st.turn='opp'
                moves[c]=st
        # защита
        elif self.turn=='opp' and self.last_att:
            for c in [x for x in self.my if beats(self.last_att, parse_card(x), self.trump)]:
                st=self.clone(); st.my.remove(c); st.gone.add(c)
                st.last_att=None; st.turn='me'
                moves['def_'+c]=st
            st=self.clone(); st.opp+=1; st.last_att=None; st.turn='me'
            moves['take']=st
        return moves
    def is_terminal(self):
        return not self.my or (self.opp==0 and self.deck==0)
    def reward(self):
        return 1 if self.opp==0 else 0

class MCTSNode:
    def __init__(self, state, parent=None):
        self.state=state; self.parent=parent
        self.children={}; self.wins=0; self.visits=0
    def ucb(self, child):
        return child.wins/child.visits + math.sqrt(2*math.log(self.visits)/child.visits)

def mcts(root_state, iters=300):
    root=MCTSNode(root_state)
    for _ in range(iters):
        node=root
        while node.children:
            node=max(node.children.values(), key=lambda c: node.ucb(c))
        moves=node.state.possible_moves()
        if moves and node.visits>0:
            for mv,st in moves.items():
                node.children[mv]=MCTSNode(st,node)
            node=random.choice(list(node.children.values()))
        sim=node.state.clone()
        while not sim.is_terminal():
            pm=sim.possible_moves()
            if not pm: break
            sim=random.choice(list(pm.values()))
        result=sim.reward()
        while node:
            node.visits+=1; node.wins+=result; node=node.parent
    if not root.children: return None
    return max(root.children.items(), key=lambda kv: kv[1].visits)[0]

# —————————————————————————————————————————————
#         Inline-клавиатуры
# —————————————————————————————————————————————
def trump_kb():
    ik = types.InlineKeyboardMarkup()
    for s in SUITS:
        ik.add(types.InlineKeyboardButton(text=s, callback_data=f"trump:{s}"))
    return ik

def cards_kb(av, done_count):
    ik = types.InlineKeyboardMarkup(row_width=4)
    for c in av:
        ik.insert(types.InlineKeyboardButton(text=c, callback_data=f"card:{c}"))
    ik.add(types.InlineKeyboardButton(text="✅ Готово", callback_data="card:done"))
    return ik

def first_kb():
    return types.InlineKeyboardMarkup().add(
        types.InlineKeyboardButton("Я", callback_data="first:me"),
        types.InlineKeyboardButton("Соперник", callback_data="first:opp")
    )

def actions_kb():
    return types.InlineKeyboardMarkup(row_width=2).add(
        types.InlineKeyboardButton("⚔️ Walk", callback_data="act:walk"),
        types.InlineKeyboardButton("📊 Stat", callback_data="act:stat")
    )

def def_kb(av):
    ik=types.InlineKeyboardMarkup(row_width=4)
    for c in av:
        ik.insert(types.InlineKeyboardButton(c, callback_data=f"def:{c}"))
    ik.add(types.InlineKeyboardButton("Не отбился", callback_data="def:take"))
    return ik

def pickup_kb(av):
    ik=types.InlineKeyboardMarkup(row_width=4)
    for c in av:
        ik.insert(types.InlineKeyboardButton(c, callback_data=f"pick:{c}"))
    ik.add(types.InlineKeyboardButton("✅ Готово", callback_data="pick:done"))
    return ik

# —————————————————————————————————————————————
#             Хранилище сессий
# —————————————————————————————————————————————
games = {}  # chat_id → data dict

# —————————————————————————————————————————————
#                   Хэндлеры
# —————————————————————————————————————————————
@dp.message(Command("start"))
async def cmd_start(m: types.Message, state: FSMContext):
    games[m.chat.id] = {
        "stage":"trump", "my":[], "available":FULL.copy(),
        "opp":0, "deck":0, "max":0, "gone":set(),
        "trump":None, "last_att":None, "pending":0, "turn":None
    }
    await state.set_state(GameStates.ChoosingTrump)
    await m.answer("Выберите козырь:", reply_markup=trump_kb())

@dp.callback_query(F.data.startswith("trump:"), GameStates.ChoosingTrump)
async def on_trump(cb: types.CallbackQuery, state: FSMContext):
    d=games[cb.message.chat.id]
    trump = cb.data.split(":",1)[1]
    d["trump"]=trump
    d["stage"]="enter"
    await state.set_state(GameStates.EnterCards)
    await cb.message.edit_text(f"Козырь: {trump}\nВыберите 6 карт:", reply_markup=cards_kb(d["available"],0))

@dp.callback_query(F.data.startswith("card:"), GameStates.EnterCards)
async def on_card(cb: types.CallbackQuery, state: FSMContext):
    d=games[cb.message.chat.id]
    val=cb.data.split(":",1)[1]
    if val=="done":
        if len(d["my"])<6:
            await cb.answer("Нужно выбрать 6 карт", show_alert=True)
        else:
            d["max"]=6; d["gone"]=set(d["my"])
            d["stage"]="first"
            await state.set_state(GameStates.ChooseFirst)
            await cb.message.edit_text("Кто ходит первым?", reply_markup=first_kb())
    else:
        if val in d["available"] and len(d["my"])<6:
            d["my"].append(val); d["available"].remove(val)
        await cb.message.edit_text(f"Выбрано {len(d['my'])}/6", reply_markup=cards_kb(d["available"],len(d["my"])))

@dp.callback_query(F.data.startswith("first:"), GameStates.ChooseFirst)
async def on_first(cb: types.CallbackQuery, state: FSMContext):
    d=games[cb.message.chat.id]
    who=cb.data.split(":",1)[1]
    d["turn"]=who; d["stage"]="play"; d["opp"]=6; d["deck"]=12
    await state.set_state(GameStates.Playing)
    await cb.message.edit_text("Игра началась!", reply_markup=actions_kb())

@dp.callback_query(F.data.startswith("act:"), GameStates.Playing)
async def on_act(cb: types.CallbackQuery, state: FSMContext):
    d=games[cb.message.chat.id]
    act=cb.data.split(":",1)[1]
    if act=="walk":
        st=MCTSState(d["my"],d["opp"],d["deck"],d["gone"],d["trump"],"me")
        mv=mcts(st, iters=500)
        card=mv
        d["last_att"]=card; d["my"].remove(card); d["gone"].add(card); d["stage"]="def"
        beat=[c for c in d["my"] if beats(card, parse_card(c), d["trump"])]
        await cb.message.edit_text(f"⚔️ Вы ходите {card}\nСоперник отбивается:", reply_markup=def_kb(beat))
        await state.set_state(GameStates.Defending)
    else:
        tm,op=len(d["my"]),d["opp"]
        p=tm/(tm+op)*100 if tm+op else 0
        await cb.answer(f"Шанс ≈ {p:.0f}%")

@dp.callback_query(F.data.startswith("def:"), GameStates.Defending)
async def on_def(cb: types.CallbackQuery, state: FSMContext):
    d=games[cb.message.chat.id]
    val=cb.data.split(":",1)[1]
    if val=="take":
        text=do_otb(d); d["stage"]="pickup"
        await state.set_state(GameStates.PickingUp)
        pool=[c for c in FULL if c not in d["gone"] and c not in d["my"]]
        await cb.message.edit_text(f"{text}\nВыберите добор:", reply_markup=pickup_kb(pool))
    else:
        # отбился
        d["my"].remove(val); d["gone"].add(val)
        await cb.message.answer(f"Соперник отбился {val}.")
        text=do_otb(d); d["stage"]="pickup"
        await state.set_state(GameStates.PickingUp)
        pool=[c for c in FULL if c not in d["gone"] and c not in d["my"]]
        await cb.message.edit_text(f"{text}\nВыберите добор:", reply_markup=pickup_kb(pool))

@dp.callback_query(F.data.startswith("pick:"), GameStates.PickingUp)
async def on_pick(cb: types.CallbackQuery, state: FSMContext):
    d=games[cb.message.chat.id]
    val=cb.data.split(":",1)[1]
    if val=="done":
        d["pending"]=0; d["stage"]="play"
        await state.set_state(GameStates.Playing)
        await cb.message.edit_text("Продолжаем!", reply_markup=actions_kb())
    else:
        if val in d["available"] and d["pending"]>0:
            d["my"].append(val); d["available"].remove(val); d["pending"]-=1
        pool=[c for c in FULL if c not in d["gone"] and c not in d["my"]]
        await cb.message.edit_text(f"Взяли {val}, осталось {d['pending']}", reply_markup=pickup_kb(pool))

if __name__ == "__main__":
    import asyncio
    asyncio.run(dp.start_polling(bot))