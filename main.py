#!/usr/bin/env python3
import os, time, requests, random, math, copy
from collections import defaultdict, Counter

TOKEN = os.getenv("BOT_TOKEN", "ВАШ_ТОКЕН_ЗДЕСЬ")
API = f"https://api.telegram.org/bot{TOKEN}/"

RANKS = ['6','7','8','9','J','Q','K','A']
SUITS = ['♠','♥','♦','♣']
FULL = [r+s for r in RANKS for s in SUITS]  # все 24 карты

def get_updates(offset=None):
    return requests.get(API+"getUpdates", params={"offset":offset,"timeout":30}).json().get("result",[])

def send(chat, text, kb=None):
    payload = {"chat_id":chat,"text":text,"parse_mode":"HTML"}
    if kb: payload["reply_markup"] = kb
    requests.post(API+"sendMessage", json=payload)

def kb(rows):
    return {"keyboard":rows,"resize_keyboard":True,"one_time_keyboard":True}

def parse_card(c): return c[:-1],c[-1]
def beats(att, dfn, trump):
    r1,s1 = parse_card(att); r2,s2 = dfn
    if s1==s2 and RANKS.index(r2)>RANKS.index(r1): return True
    if s2==trump and s1!=trump: return True
    return False

# particle filter для модели соперника
def estimate_dist(state, trials=200):
    rem=[c for c in FULL if c not in state['gone'] and c not in state['my']]
    cnt=Counter()
    for _ in range(trials):
        sample=random.sample(rem, state['opp'])
        cnt.update(sample)
    total=sum(cnt.values())
    if total==0: return {c:1/len(rem) for c in rem}
    return {c:cnt[c]/total for c in rem}

# MCTS
class State:
    def __init__(self,my,opp,deck,gone,trump,turn,last_att=None):
        self.my=list(my); self.opp=opp; self.deck=deck
        self.gone=set(gone); self.trump=trump
        self.turn=turn; self.last_att=last_att
    def clone(self): return copy.deepcopy(self)
    def possible_moves(self):
        moves={}
        if self.turn=='me' and self.last_att is None:
            # атака: любые карты, но сначала некозырные, не-A
            hand=[c for c in self.my if parse_card(c)[1]!=self.trump]
            hand=[c for c in hand if parse_card(c)[0]!='A'] or self.my
            for c in hand:
                st=self.clone()
                st.my.remove(c); st.gone.add(c)
                st.last_att=c; st.turn='opp'
                moves[c]=st
        elif self.turn=='opp' and self.last_att:
            # защита: все возможные
            for c in [x for x in self.my if beats(self.last_att,parse_card(x),self.trump)]:
                st=self.clone()
                st.my.remove(c); st.gone.add(c)
                st.last_att=None; st.turn='me'
                moves['def_'+c]=st
            # либо берёт
            st=self.clone(); st.opp+=1; st.last_att=None; st.turn='me'
            moves['take']=st
        return moves
    def is_terminal(self):
        return not self.my or (self.opp==0 and self.deck==0)
    def reward(self):
        return 1 if self.opp==0 else 0

class Node:
    def __init__(self,state,parent=None):
        self.state=state; self.parent=parent
        self.children={}; self.wins=0; self.visits=0
    def ucb(self,child):
        return child.wins/child.visits + math.sqrt(2*math.log(self.visits)/child.visits)

def mcts(root_state,iters=300):
    root=Node(root_state)
    for _ in range(iters):
        node=root
        # selection
        while node.children:
            node=max(node.children.values(), key=lambda c: node.ucb(c))
        # expansion
        moves=node.state.possible_moves()
        if moves and node.visits>0:
            for mv,st in moves.items():
                node.children[mv]=Node(st,node)
            node=random.choice(list(node.children.values()))
        # simulation
        st=node.state.clone()
        while not st.is_terminal():
            pm=st.possible_moves()
            if not pm: break
            st=random.choice(list(pm.values()))
        res=st.reward()
        # backprop
        while node:
            node.visits+=1
            node.wins+=res
            node=node.parent
    if not root.children: return None
    return max(root.children.items(), key=lambda kv: kv[1].visits)[0]

def do_otb(s):
    draws=min(s['max']-len(s['my']), s['deck'])
    s['deck']-=draws
    draws2=min(s['max']-s['opp'], s['deck'])
    s['deck']-=draws2
    s['pending']=draws
    return f"Раунд окончен. Вы берёте {draws}, оппонент {draws2}. Осталось в колоде {s['deck']}."

# клавиатуры
def kb_trump():   return kb([[s] for s in SUITS])
def kb_cards(av): return kb([av[i:i+4] for i in range(0,len(av),4)] + [['✅ Готово']])
def kb_start():   return kb([['Я','Соперник']])
def kb_actions(): return kb([['⚔️ walk','📊 stat']])
def kb_defense(av):
    return kb([av[i:i+4] for i in range(0,len(av),4)] + [['Не отбился']])

sessions=defaultdict(lambda:{
    'stage':'start','trump':None,'available':[],'my':[],
    'opp':0,'deck':0,'max':0,'gone':set(),
    'last_att':None,'pending':0
})

def main():
    offset=None
    while True:
        for upd in get_updates(offset):
            offset=upd['update_id']+1
            msg=upd.get('message')
            if not msg or 'text' not in msg: continue
            ch,t=msg['chat']['id'],msg['text'].strip()
            s=sessions[ch]

            # старт
            if t in ('/start','/init') or s['stage']=='start':
                s.update(stage='choose_trump',my=[],gone=set(),pending=0,last_att=None)
                send(ch,'Выберите козырь:',kb_trump())
                continue

            # выбор козыря
            if s['stage']=='choose_trump' and t in SUITS:
                s['trump']=t; s['stage']='enter'
                s['available']=FULL.copy(); s['my']=[]
                send(ch,f'Козырь {t}. Выберите 6 карт:',kb_cards(s['available']))
                continue

            # ввод 6 карт
            if s['stage']=='enter':
                if t=='✅ Готово':
                    if len(s['my'])<6:
                        send(ch,f'Нужно 6 карт, выбрано {len(s["my"])}',kb_cards(s['available']))
                    else:
                        s['max']=6; s['gone']=set(s['my'])
                        s['stage']='first'
                        send(ch,'Кто ходит первым?',kb_start())
                elif t in s['available']:
                    s['my'].append(t); s['available'].remove(t)
                    send(ch,f'Выбрано {len(s["my"])}/6',kb_cards(s['available']))
                else:
                    send(ch,'Нажмите карту или ✅ Готово.')
                continue

            # первый ход
            if s['stage']=='first' and t in ('Я','Соперник'):
                s['turn']='me' if t=='Я' else 'opp'
                s['stage']='play'; s['opp']=6; s['deck']=12
                send(ch,'Игра началась!',kb_actions())
                continue

            # play
            if s['stage']=='play':
                if t=='⚔️ walk':
                    st=State(s['my'],s['opp'],s['deck'],s['gone'],s['trump'],'me')
                    mv=mcts(st, iters=500)
                    card=mv
                    s['last_att']=card; s['my'].remove(card); s['gone'].add(card)
                    s['stage']='def'
                    beat=[c for c in s['my'] if beats(card,parse_card(c),s['trump'])]
                    send(ch,f'⚔️ Вы ходите {card}\nСоперник отбивается:',kb_defense(beat))
                elif t=='📊 stat':
                    tm,op=len(s['my']),s['opp']
                    p=tm/(tm+op)*100 if tm+op else 0
                    send(ch,f'Шанс ≈ {p:.0f}%',kb_actions())
                else:
                    send(ch,'Нажмите ⚔️ walk или 📊 stat.',kb_actions())
                continue

            # defense
            if s['stage']=='def':
                if t=='Не отбился':
                    res=do_otb(s); s['stage']='pickup'
                    send(ch,res+'\nВыберите добор:',kb_cards([c for c in FULL if c not in s['gone'] and c not in s['my']]))
                elif t in s['my'] and beats(s['last_att'],parse_card(t),s['trump']):
                    s['my'].remove(t); s['gone'].add(t)
                    send(ch,f'Соперник отбился {t}.')
                    res=do_otb(s); s['stage']='pickup'
                    send(ch,res+'\nВыберите добор:',kb_cards([c for c in FULL if c not in s['gone'] and c not in s['my']]))
                else:
                    beat=[c for c in s['my'] if beats(s['last_att'],parse_card(c),s['trump'])]
                    send(ch,'Выберите карту защиты или «Не отбился»',kb_defense(beat))
                continue

            # pickup
            if s['stage']=='pickup':
                if t=='✅ Готово':
                    s['pending']=0; s['stage']='play'
                    send(ch,'Продолжаем...',kb_actions())
                elif t in s['available'] and s['pending']>0:
                    s['my'].append(t); s['available'].remove(t); s['pending']-=1
                    send(ch,f'Взяли {t}, осталось {s["pending"]}',kb_cards(s['available']))
                else:
                    send(ch,'Нажмите карту или ✅ Готово.',kb_cards(s['available']))
                continue

            # default
            send(ch,'Введите /start для новой игры.')
        time.sleep(1)

if __name__=='__main__':
    main()