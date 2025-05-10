#!/usr/bin/env python3
import os, time, requests
from collections import defaultdict, Counter
import numpy as np

TOKEN = os.getenv("BOT_TOKEN", "ВАШ_ТОКЕН_ЗДЕСЬ")
API = f"https://api.telegram.org/bot{TOKEN}"

# Карты
RANKS = ['6','7','8','9','J','Q','K','A']
SUITS = ['♠','♥','♦','♣']
FULL_DECK = [r + s for r in RANKS for s in SUITS]

# Сессии
sessions = defaultdict(lambda: {
    "stage":"start",
    "trump":None,
    "my":[],       # ваши известные карты
    "opp":0,
    "deck":0,
    "max":0,
    "gone":set(),  # сыгранные карты
})

def send(chat, text, keyboard=None):
    data = {"chat_id":chat, "text":text, "parse_mode":"HTML"}
    if keyboard:
        data["reply_markup"] = keyboard
    requests.post(API+"/sendMessage", json=data)

def get_updates(offset=None):
    r = requests.get(API+"/getUpdates", params={"timeout":30,"offset":offset})
    return r.json().get("result",[])

def draw_keyb(rows):
    return {"keyboard":rows,"resize_keyboard":True,"one_time_keyboard":True}

# Monte Carlo: оценить шанс отбоя/атакующего
def mc_best_defense(att_card, state, trials=200):
    # state: my_cards, opp_count, deck_count, gone, trump
    my = state["my"]
    opp = state["opp"]
    deck = state["deck"]
    gone = state["gone"]
    trump = state["trump"]
    # сформируем список возможных карт у оппонента/в колоде
    remaining = [c for c in FULL_DECK if c not in gone and c not in my]
    wins = Counter()
    # для каждой candidate карты защита тестируем trials
    candidates = [c for c in my
                  if beats_card(att_card, c, trump)]
    if not candidates:
        return None, 0.0
    for cand in candidates:
        win = 0
        for _ in range(trials):
            # рандомно сгенерировать руку оппонента из remaining
            opp_hand = np.random.choice(remaining, opp, replace=False)
            # если ни одна из opp_hand не бьёт cand, считаем выигрыш
            # простая модель: если никто не может отбить => win
            if not any(beats_card(cand, parse_card(c2), trump)
                       for c2 in opp_hand):
                win += 1
        wins[cand] = win
    # выбрать карту, при которой больше всего win
    best, win = max(wins.items(), key=lambda kv: kv[1])
    return best, win / (trials)

def parse_card(c): return (c[:-1], c[-1])
def beats_card(att, dfn, trump):
    r1,s1 = parse_card(att); r2,s2 = dfn
    idx = RANKS.index
    if s1==s2 and idx(r2)>idx(r1): return True
    if s2==trump and s1!=trump: return True
    return False

# Основной цикл
def main():
    offset = None
    while True:
        for upd in get_updates(offset):
            offset = upd["update_id"] + 1
            msg = upd.get("message")
            if not msg or "text" not in msg: continue
            chat = msg["chat"]["id"]
            t = msg["text"].strip()
            s = sessions[chat]

            # /start
            if t in ["/start","/init"] or s["stage"]=="start":
                s.update(stage="choose_trump", **{k:None for k in ["trump","my","opp","deck","max"]})
                rows = [[su] for su in SUITS]
                send(chat, "Выбери козырь:", draw_keyb(rows))
                continue

            # выбор козыря
            if s["stage"]=="choose_trump" and t in SUITS:
                s["trump"] = t
                s["stage"] = "enter_cards"
                send(chat,
                     f"Козырь: {t}\n"
                     "Введи свои 6 карт (напр. 6♠ 7♥ 8♦ 9♣ J♠ Q♥):",
                     draw_keyb([]))
                continue

            # ввод карт
            if s["stage"]=="enter_cards":
                cards = t.split()
                s["my"] = cards
                s["max"] = len(cards)
                s["gone"] = set(cards)
                s["stage"] = "enter_setup"
                rows = [["opp:6 deck:12"]]
                send(chat,
                     f"Ваши карты: {' '.join(cards)}\n"
                     "Теперь выбери стартовый opp и deck:",
                     draw_keyb(rows))
                continue

            # setup
            if s["stage"]=="enter_setup" and t.startswith("opp:"):
                opp, deck = map(int, t.replace("opp:","").replace("deck:","").split())
                s["opp"], s["deck"] = opp, deck
                s["stage"] = "play"
                kb = [["⚔️ walk","🛡️ def"],["🔄 otb","📊 stat"]]
                send(chat,
                     f"Игра началась!\n"
                     f"🃏 У вас {len(s['my'])}, у соперника {opp}, в колоде {deck}.",
                     draw_keyb(kb))
                continue

            # play
            if s["stage"]=="play":
                if t == "⚔️ walk":
                    # простой walk: Monte Carlo выбирает карту, которую атаковать
                    best, p = mc_best_defense(t, s)
                    send(chat, f"▶ Ходите: {best}\n▶ Вероятность непринятия: {p*100:.0f}%")
                elif t == "🛡️ def":
                    # предположим атакующая карта хранится в s["last_att"], но для примера:
                    att = s.get("last_att","6♠")
                    best, p = mc_best_defense(att, s)
                    send(chat, f"▶ Отбивайте: {best}\n▶ Вероятность успеха: {p*100:.0f}%")
                elif t == "🔄 otb":
                    # добор
                    draw_you = min(s["max"]-len(s["my"]), s["deck"])
                    s["deck"] -= draw_you; s["my"] += ["?"]*draw_you
                    send(chat, f"▶ Раунд окончен. Добрали {draw_you} карт. В колоде {s['deck']}")
                elif t == "📊 stat":
                    total = len(s["my"]); opp = s["opp"]
                    p = total/(total+opp)*100
                    send(chat, f"▶ Шанс победы ≈ {p:.0f}%")
                else:
                    send(chat, "Нажмите кнопку действия.")
                continue

            # fallback
            send(chat, "Напиши /start чтобы начать.")
        time.sleep(1)

if __name__=="__main__":
    main()