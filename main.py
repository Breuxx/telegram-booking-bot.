#!/usr/bin/env python3
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from collections import defaultdict
import os

logging.basicConfig(level=logging.INFO)
API_TOKEN = os.getenv("BOT_TOKEN", "7654501983:AAHuFHxXlqeGnmco-r-RpTwXptVq-28flKA")

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

RANKS = ['6','7','8','9','10','J','Q','K','A']
SUITS = {'s':'♠','h':'♥','d':'♦','c':'♣'}

def parse_card(card: str):
    return card[:-1], card[-1]

def card_to_str(c: tuple):
    return c[0] + SUITS.get(c[1], c[1])

def beats(att: tuple, dfn: tuple, trump: str) -> bool:
    r1, s1 = att; r2, s2 = dfn
    if s1 == s2 and RANKS.index(r2) > RANKS.index(r1):
        return True
    if s2 == trump and s1 != trump:
        return True
    return False

class TrainerSession:
    def __init__(self):
        self.reset()
    def reset(self):
        self.trump = None
        self.my = []
        self.opp = 0
        self.deck = 0
        self.max_hand = 0
        self.unknown = 0
    def do_walk(self):
        # упрощённо: всегда автоподбор
        non_tr = [c for c in self.my if c[1] != self.trump]
        pick = (min(non_tr, key=lambda x:RANKS.index(x[0]))
                if non_tr else min(self.my, key=lambda x:RANKS.index(x[0])))
        self.my.remove(pick)
        chance = (len(self.my)+self.unknown)/((len(self.my)+self.unknown)+self.opp)*100
        return f"▶ Ходи: {card_to_str(pick)}\n▶ Шанс ≈ {chance:.0f}%"
    def do_def(self, att_card: str):
        att = parse_card(att_card)
        cand = [c for c in self.my if beats(att,c,self.trump)]
        if cand:
            pick = min(cand, key=lambda x:(x[1]!=self.trump, RANKS.index(x[0])))
            self.my.remove(pick)
            msg = f"▶ Отбивайся: {card_to_str(pick)}"
        else:
            self.unknown = max(0, self.unknown - 1)
            msg = "▶ Отбивайся: [неизвестная карта]"
        chance = (len(self.my)+self.unknown)/((len(self.my)+self.unknown)+self.opp)*100
        return f"{msg}\n▶ Шанс ≈ {chance:.0f}%"
    def do_otb(self):
        draws_me = min(self.max_hand - (len(self.my)+self.unknown), self.deck)
        self.unknown += draws_me; self.deck -= draws_me
        draws_op = min(self.max_hand - self.opp, self.deck)
        self.opp += draws_op; self.deck -= draws_op
        return (f"▶ Раунд завершён.\n"
                f"Добрано: тебе +{draws_me}, сопернику +{draws_op}\n"
                f"В колоде осталось {self.deck}")
    def do_stat(self):
        total_my = len(self.my)+self.unknown; total_opp = self.opp
        if total_my+total_opp == 0:
            return "▶ Нет карт — нечего считать."
        chance = total_my/(total_my+total_opp)*100
        return f"▶ Шанс победы ≈ {chance:.0f}%"

sessions = defaultdict(TrainerSession)

# 1) /start → выбор козыря
@dp.message_handler(commands=['start','init'])
async def cmd_start(msg: types.Message):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.add('♠ s','♥ h').add('♦ d','♣ c')
    await msg.answer("Выбери козырь:", reply_markup=kb)

# 2) Обработка ВСЕХ текстовых сообщений
@dp.message_handler()
async def all_messages(msg: types.Message):
    text = msg.text.strip()
    sess = sessions[msg.from_user.id]

    # выбор козыря
    if text in ['s','h','d','c','♠','♥','♦','♣'] and sess.trump is None:
        trump = text if text in SUITS else {v:k for k,v in SUITS.items()}[text]
        sess.reset(); sess.trump = trump
        await msg.answer(f"Козырь: {SUITS[trump]}\nВведи свои карты (напр. 6s 7h Ah):",
                         reply_markup=types.ReplyKeyboardRemove())
        return

    # ввод своих карт
    if sess.trump and not sess.my:
        cards = text.split()
        sess.my = [parse_card(c) for c in cards]
        sess.max_hand = len(sess.my)
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        kb.add('opp:6 deck:12','opp:5 deck:13')
        await msg.answer(f"Твои карты: {text}\nТеперь opp и deck:", reply_markup=kb)
        return

    # ввод opp/deck
    if text.startswith('opp:') and sess.my and sess.opp==0:
        opp, deck = map(int, [text.split()[0].split(':')[1], text.split()[1].split(':')[1]])
        sess.opp = opp; sess.deck = deck
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        kb.row('⚔️ walk','🛡️ def').row('🔄 otb','📊 stat')
        await msg.answer(f"Старт!\nКозырь {SUITS[sess.trump]}, ты {len(sess.my)}, опп {sess.opp}, deck {sess.deck}",
                         reply_markup=kb)
        return

    # игровые кнопки
    if text == '⚔️ walk':
        await msg.answer(sess.do_walk()); return
    if text == '🛡️ def':
        # для примера используем атаку '6s'
        await msg.answer(sess.do_def('6s')); return
    if text == '🔄 otb':
        await msg.answer(sess.do_otb()); return
    if text == '📊 stat':
        await msg.answer(sess.do_stat()); return

    # всё остальное
    await msg.answer("Неизвестная команда.")
  
if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)