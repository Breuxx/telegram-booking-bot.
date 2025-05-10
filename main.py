#!/usr/bin/env python3
import os
import sys
import time
import requests
from collections import defaultdict

TOKEN = os.getenv("BOT_TOKEN", "ВАШ_ТОКЕН_ЗДЕСЬ")
API_URL = f"https://api.telegram.org/bot{TOKEN}"

# Сессии для каждого пользователя
sessions = defaultdict(lambda: {
    "stage": "start",
    "trump": None,
    "my": [],
    "opp": 0,
    "deck": 0,
    "max_hand": 0,
    "unknown": 0
})

# Логика «тренера» (коротко)
RANKS = ['6','7','8','9','10','J','Q','K','A']
SUITS = {'s':'♠','h':'♥','d':'♦','c':'♣'}

def parse_card(card):
    return card[:-1], card[-1]

def card_to_str(c):
    return c[0] + SUITS.get(c[1], c[1])

def beats(att, dfn, trump):
    r1, s1 = att; r2, s2 = dfn
    if s1==s2 and RANKS.index(r2)>RANKS.index(r1): return True
    if s2==trump and s1!=trump: return True
    return False

def do_walk(sess, card=None):
    if card:
        c = parse_card(card)
        if c in sess["my"]:
            sess["my"].remove(c)
        else:
            sess["unknown"] = max(0, sess["unknown"]-1)
    else:
        non_tr = [c for c in sess["my"] if c[1]!=sess["trump"]]
        pick = (min(non_tr, key=lambda x:RANKS.index(x[0]))
                if non_tr else min(sess["my"], key=lambda x:RANKS.index(x[0])))
        sess["my"].remove(pick)
        c = pick
    chance = (len(sess["my"])+sess["unknown"]) / ((len(sess["my"])+sess["unknown"])+sess["opp"]) * 100
    return f"▶ Ходи: {card_to_str(c)}\n▶ Шанс ≈ {chance:.0f}%"

def do_def(sess, att_card):
    att = parse_card(att_card)
    cand = [c for c in sess["my"] if beats(att, c, sess["trump"])]
    if cand:
        pick = min(cand, key=lambda x:(x[1]!=sess["trump"], RANKS.index(x[0])))
        sess["my"].remove(pick)
        msg = f"▶ Отбивайся: {card_to_str(pick)}"
    else:
        sess["unknown"] = max(0, sess["unknown"]-1)
        msg = "▶ Отбивайся: [неизвестная карта]"
    chance = (len(sess["my"])+sess["unknown"]) / ((len(sess["my"])+sess["unknown"])+sess["opp"]) * 100
    return f"{msg}\n▶ Шанс ≈ {chance:.0f}%"

def do_otb(sess):
    draws_me = min(sess["max_hand"] - (len(sess["my"])+sess["unknown"]), sess["deck"])
    sess["unknown"] += draws_me; sess["deck"] -= draws_me
    draws_op = min(sess["max_hand"] - sess["opp"], sess["deck"])
    sess["opp"] += draws_op; sess["deck"] -= draws_op
    return (f"▶ Раунд завершён.\n"
            f"Добрано: тебе +{draws_me}, сопернику +{draws_op}\n"
            f"В колоде осталось {sess['deck']}")

def do_stat(sess):
    total_my = len(sess["my"])+sess["unknown"]
    total_opp = sess["opp"]
    if total_my+total_opp==0:
        return "▶ Нет карт — нечего считать."
    chance = total_my/(total_my+total_opp)*100
    return f"▶ Шанс победы ≈ {chance:.0f}%"

# Работа с API
def get_updates(offset=None):
    params = {"timeout": 30, "offset": offset}
    resp = requests.get(API_URL + "/getUpdates", params=params)
    return resp.json()["result"]

def send_message(chat_id, text, reply_markup=None):
    data = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        data["reply_markup"] = reply_markup
    requests.post(API_URL + "/sendMessage", json=data)

# Клавиатуры
def keyboard(items):
    return {"keyboard": items, "resize_keyboard": True, "one_time_keyboard": True}

# Основной цикл
def main():
    offset = None
    while True:
        updates = get_updates(offset)
        for upd in updates:
            offset = upd["update_id"] + 1
            msg = upd.get("message")
            if not msg or "text" not in msg: continue
            chat_id = msg["chat"]["id"]
            text = msg["text"].strip()
            sess = sessions[chat_id]

            # Сценарии
            if text in ["/start", "/init"]:
                sess.update({"stage":"choose_trump"})
                kb = [[ "♠ s", "♥ h" ], [ "♦ d", "♣ c" ]]
                send_message(chat_id, "Выбери козырь:", reply_markup=keyboard(kb))
            elif sess["stage"] == "choose_trump" and text in ['s','h','d','c','♠','♥','♦','♣']:
                trump = text if text in SUITS else {v:k for k,v in SUITS.items()}[text]
                sess.update({"stage":"enter_cards","trump":trump})
                send_message(chat_id,
                    f"Козырь: {SUITS[trump]}\nВведи свои карты (напр. 6s 7h Ah):",
                    reply_markup={"remove_keyboard":True})
            elif sess["stage"]=="enter_cards" and text and text.split()[0][:-1] in RANKS:
                cards = text.split()
                sess["my"] = [parse_card(c) for c in cards]
                sess["max_hand"] = len(sess["my"])
                sess["stage"]="enter_setup"
                kb = [[ "opp:6 deck:12", "opp:5 deck:13" ]]
                send_message(chat_id,
                    f"Твои карты: {' '.join(text.split())}\nТеперь opp и deck:",
                    reply_markup=keyboard(kb))
            elif sess["stage"]=="enter_setup" and text.startswith("opp:"):
                opp, deck = map(int, [text.split()[0].split(":")[1], text.split()[1].split(":")[1]])
                sess.update({"opp":opp,"deck":deck,"unknown":0,"stage":"play"})
                kb = [[ "⚔️ walk", "🛡️ def" ], [ "🔄 otb", "📊 stat" ]]
                send_message(chat_id,
                    f"Игра началась!\nКозырь {SUITS[sess['trump']]}, у тебя {len(sess['my'])}, у соперника {sess['opp']}, в колоде {sess['deck']}",
                    reply_markup=keyboard(kb))
            elif sess["stage"]=="play":
                if text == "⚔️ walk":
                    send_message(chat_id, do_walk(sess))
                elif text == "🛡️ def":
                    # для простоты: берем атаку '6s'; можно спросить
                    send_message(chat_id, do_def(sess, "6s"))
                elif text == "🔄 otb":
                    send_message(chat_id, do_otb(sess))
                elif text == "📊 stat":
                    send_message(chat_id, do_stat(sess))
                else:
                    send_message(chat_id, "Неожиданная команда.")
            else:
                send_message(chat_id, "Нажми /start чтобы начать.", reply_markup={"remove_keyboard":True})
        time.sleep(1)

if __name__ == "__main__":
    main()