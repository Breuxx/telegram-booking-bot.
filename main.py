#!/usr/bin/env python3
import os
import time
import requests
from collections import defaultdict, Counter
import numpy as np

# —————————————————————————————————————————————————————————————————————————————
#                          Конфигурация
# —————————————————————————————————————————————————————————————————————————————

TOKEN = os.getenv("BOT_TOKEN", "ВАШ_ТОКЕН_ЗДЕСЬ")
API = f"https://api.telegram.org/bot{TOKEN}"

# Полный «дек» из 24 карт (6–9, J, Q, K, A × все 4 масти)
RANKS = ['6','7','8','9','J','Q','K','A']
SUITS = ['♠','♥','♦','♣']
FULL_DECK = [r + s for r in RANKS for s in SUITS]

# Сессии пользователей
# stage: start → choose_trump → enter_cards → confirm_start → play
sessions = defaultdict(lambda: {
    "stage": "start",
    "trump": None,
    "my": [],            # ваши карты
    "opp": 0,            # число карт у соперника
    "deck": 0,           # число карт в колоде
    "max": 0,            # начальный размер руки
    "gone": set(),       # сыгранные карты
})

# —————————————————————————————————————————————————————————————————————————————
#                          HTTP / Telegram API
# —————————————————————————————————————————————————————————————————————————————

def get_updates(offset=None, timeout=30):
    r = requests.get(API + "/getUpdates", params={"offset": offset, "timeout": timeout})
    return r.json().get("result", [])

def send_message(chat_id, text, keyboard=None):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if keyboard is not None:
        payload["reply_markup"] = keyboard
    requests.post(API + "/sendMessage", json=payload)

def build_keyboard(rows):
    return {"keyboard": rows, "resize_keyboard": True, "one_time_keyboard": True}

# —————————————————————————————————————————————————————————————————————————————
#                          Логика «тренера»
# —————————————————————————————————————————————————————————————————————————————

def parse_card(c):
    return c[:-1], c[-1]

def beats(att, dfn, trump):
    r1, s1 = parse_card(att)
    r2, s2 = dfn
    if s1 == s2 and RANKS.index(r2) > RANKS.index(r1):
        return True
    if s2 == trump and s1 != trump:
        return True
    return False

def mc_best_attack(state, trials=200):
    """Выбираем карту для атаки, дающую наибольшую вероятность непринятия."""
    my = state["my"]
    opp = state["opp"]
    deck = state["deck"]
    gone = state["gone"]
    trump = state["trump"]

    remaining = [c for c in FULL_DECK if c not in gone and c not in my]
    wins = Counter()
    for card in my:
        win = 0
        for _ in range(trials):
            hand = np.random.choice(remaining, opp, replace=False)
            # если ни одна карта соперника не бьёт нашу
            if not any(beats(card, parse_card(c2), trump) for c2 in hand):
                win += 1
        wins[card] = win / trials
    best = max(wins, key=wins.get)
    return best, wins[best]

def mc_best_defense(att_card, state, trials=200):
    """Выбираем карту для защиты от att_card с наибольшей вероятностью успеха."""
    my = state["my"]
    opp = state["opp"]
    deck = state["deck"]
    gone = state["gone"]
    trump = state["trump"]

    remaining = [c for c in FULL_DECK if c not in gone and c not in my]
    candidates = [c for c in my if beats(att_card, parse_card(c), trump)]
    if not candidates:
        return None, 0.0

    wins = Counter()
    for card in candidates:
        win = 0
        for _ in range(trials):
            hand = np.random.choice(remaining, opp, replace=False)
            # считаем выигрыш, если никто из них не сможет перебить нашу защиту
            if not any(beats(card, parse_card(c2), trump) for c2 in hand):
                win += 1
        wins[card] = win / trials
    best = max(wins, key=wins.get)
    return best, wins[best]

def do_otb(state):
    """Завершение раунда: автодобор карт."""
    draws_me = min(state["max"] - len(state["my"]), state["deck"])
    state["my"] += ["?"] * draws_me
    state["deck"] -= draws_me

    draws_opp = min(state["max"] - state["opp"], state["deck"])
    state["opp"] += draws_opp
    state["deck"] -= draws_opp

    return f"▶ Раунд окончен. Добрали: ты +{draws_me}, оппонент +{draws_opp}. В колоде {state['deck']}."

# —————————————————————————————————————————————————————————————————————————————
#                          Утилиты клавиатур
# —————————————————————————————————————————————————————————————————————————————

def build_trump_keyboard():
    return build_keyboard([[s] for s in SUITS])

def build_cards_keyboard(available):
    # раскладываем по 4 в ряд
    rows, row = [], []
    for c in available:
        row.append(c)
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append(["✅ Готово"])
    return build_keyboard(rows)

def build_start_keyboard():
    return build_keyboard([["Я","Соперник"]])

def build_action_keyboard():
    return build_keyboard([["⚔️ walk", "🛡️ def"], ["🔄 otb", "📊 stat"]])

# —————————————————————————————————————————————————————————————————————————————
#                          Основной цикл
# —————————————————————————————————————————————————————————————————————————————

def main():
    offset = None
    while True:
        updates = get_updates(offset)
        for upd in updates:
            offset = upd["update_id"] + 1
            msg = upd.get("message")
            if not msg or "text" not in msg:
                continue
            chat = msg["chat"]["id"]
            text = msg["text"].strip()
            s = sessions[chat]

            # --- /start или stage == start ---
            if text in ("/start","/init") or s["stage"] == "start":
                s.update(stage="choose_trump",
                         trump=None, my=[], opp=0, deck=0, max=0, gone=set())
                send_message(chat, "Выберите козырь:", build_trump_keyboard())
                continue

            # --- выбор козыря ---
            if s["stage"] == "choose_trump" and text in SUITS:
                s["trump"] = text
                s["stage"] = "enter_cards"
                # начальный список доступных карт
                s["available"] = FULL_DECK.copy()
                s["my"] = []
                send_message(chat,
                             f"Козырь: {text}\nВыберите ваши 6 карт:",
                             build_cards_keyboard(s["available"]))
                continue

            # --- ввод карт через кнопки ---
            if s["stage"] == "enter_cards":
                if text == "✅ Готово":
                    if len(s["my"]) < 6:
                        send_message(chat,
                                     f"Нужно 6 карт, выбрано {len(s['my'])}:",
                                     build_cards_keyboard(s["available"]))
                    else:
                        s["max"] = len(s["my"])
                        s["gone"] = set(s["my"])
                        s["stage"] = "confirm_start"
                        send_message(chat, "Кто ходит первым?", build_start_keyboard())
                elif text in s.get("available",[]):
                    s["my"].append(text)
                    s["available"].remove(text)
                    send_message(chat,
                                 f"Выбрано {len(s['my'])}/6:",
                                 build_cards_keyboard(s["available"]))
                else:
                    send_message(chat, "Нажмите на нужную карту или ✅ Готово.")
                continue

            # --- подтверждение первого хода ---
            if s["stage"] == "confirm_start" and text in ("Я","Соперник"):
                s["turn"] = "me" if text == "Я" else "opp"
                s["stage"] = "play"
                send_message(chat,
                             "Игра началась! Выберите действие:",
                             build_action_keyboard())
                continue

            # --- игровой этап ---
            if s["stage"] == "play":
                # атака
                if text == "⚔️ walk":
                    card, p = mc_best_attack(s)
                    send_message(chat,
                                 f"▶ Предлагаю ходить: {card}\n▶ Вероятность принятия: {p*100:.0f}%")
                # защита
                elif text == "🛡️ def":
                    send_message(chat, "Введите карту, которой атакует соперник (напр. 9♣):")
                    s["stage"] = "await_att"
                # завершить раунд
                elif text == "🔄 otb":
                    res = do_otb(s)
                    send_message(chat, res)
                # статистика
                elif text == "📊 stat":
                    total = len(s["my"]); opp = s["opp"]
                    chance = total/(total+opp)*100 if (total+opp)>0 else 0
                    send_message(chat,
                                 f"▶ Шанс победы ≈ {chance:.0f}%\n"
                                 f"(У тебя {total}, у соперника {opp}, колода {s['deck']})")
                else:
                    send_message(chat, "Пожалуйста, выберите одно из действий.", build_action_keyboard())
                continue

            # --- ввод карты атаки соперника ---
            if s["stage"] == "await_att":
                att = text
                s["stage"] = "play"
                # сохраняем атаку в gone
                s["gone"].add(att)
                card, p = mc_best_defense(att, s)
                if card:
                    send_message(chat,
                                 f"▶ Предлагаю отбиваться: {card}\n▶ Вероятность успеха: {p*100:.0f}%")
                else:
                    send_message(chat, "▶ Нечем отбиться — можно брать.")
                continue

            # --- всё остальное ---
            send_message(chat, "Нажмите /start для начала.")
        time.sleep(1)

if __name__ == "__main__":
    main()