#!/usr/bin/env python3
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from collections import defaultdict
import os

API_TOKEN = os.getenv("BOT_TOKEN", "7654501983:AAGi8L3LHBck1tlu4FVvRDeUfq0FgKzCWiA")

# Логирование
logging.basicConfig(level=logging.INFO)

# Инициализация бота и диспетчера
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# Класс с логикой терминального тренера (упрощённо)
RANKS = ['6','7','8','9','10','J','Q','K','A']
SUITS = {'s':'♠','h':'♥','d':'♦','c':'♣'}

def parse_card(card):
    return card[:-1], card[-1]

def card_to_str(c):
    return c[0] + SUITS[c[1]]

def beats(att, dfn, trump):
    r1,s1 = att; r2,s2 = dfn
    if s1==s2 and RANKS.index(r2)>RANKS.index(r1): return True
    if s2==trump and s1!=trump: return True
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
    def init(self, trump, my_cards, opp, deck):
        self.trump = trump
        self.my = [parse_card(c) for c in my_cards]
        self.opp = opp
        self.deck = deck
        self.max_hand = len(self.my)
        self.unknown = 0
    def do_walk(self, card=None):
        if card:
            c = parse_card(card)
            if c in self.my: self.my.remove(c)
            else: self.unknown = max(0, self.unknown-1)
        else:
            non_tr = [c for c in self.my if c[1]!=self.trump]
            pick = (min(non_tr, key=lambda c:RANKS.index(c[0]))
                    if non_tr else min(self.my, key=lambda c:RANKS.index(c[0])))
            self.my.remove(pick)
            c = pick
        chance = (len(self.my)+self.unknown)/( (len(self.my)+self.unknown)+self.opp )*100
        return f"▶ Ходи: {card_to_str(c)}\n▶ Шанс ≈ {chance:.0f}%"
    def do_def(self, att_card):
        att = parse_card(att_card)
        cand = [c for c in self.my if beats(att,c,self.trump)]
        if cand:
            pick = min(cand, key=lambda c:(c[1]!=self.trump, RANKS.index(c[0])))
            self.my.remove(pick)
            msg = f"▶ Отбивка: {card_to_str(pick)}"
        else:
            self.unknown = max(0, self.unknown-1)
            msg = "▶ Отбивайся: [неизвестная карта]"
        chance = (len(self.my)+self.unknown)/( (len(self.my)+self.unknown)+self.opp )*100
        return msg + f"\n▶ Шанс ≈ {chance:.0f}%"
    def do_otb(self):
        draws_me = min(self.max_hand - (len(self.my)+self.unknown), self.deck)
        self.unknown += draws_me
        self.deck -= draws_me
        draws_op = min(self.max_hand - self.opp, self.deck)
        self.opp += draws_op
        self.deck -= draws_op
        return (f"▶ Раунд завершён.\n"
                f"Добрано: тебе +{draws_me}, сопернику +{draws_op}\n"
                f"В колоде: {self.deck}")

# Сессии по user_id
sessions = defaultdict(TrainerSession)

# ——— Команда /start и кнопка Init ———
@dp.message_handler(commands=['start','init'])
async def cmd_start(message: types.Message):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add('♠ s','♥ h','♦ d','♣ c')
    await message.answer("Выбери козырь (нажми символ или букву):", reply_markup=kb)

# ——— Выбор козыря — и переход к вводу карт ———
@dp.message_handler(lambda m: m.text in ['s','h','d','c','♠','♥','♦','♣'])
async def choose_trump(m: types.Message):
    tr = m.text[-1] if m.text[0] in 'shdc' else {'♠':'s','♥':'h','♦':'d','♣':'c'}[m.text]
    sess = sessions[m.from_user.id]
    sess.reset()
    sess.trump = tr
    await m.answer(f"Козырь: {SUITS[tr]}\nТеперь введи свои карты через пробел (напр. 6s 7h Ah):",
                   reply_markup=types.ReplyKeyboardRemove())

# ——— Ввод своих карт и opp/deck ———
@dp.message_handler(lambda m: sess := sessions[m.from_user.id] and sess.trump and not sess.my)
async def input_my_cards(m: types.Message):
    cards = m.text.split()
    sess = sessions[m.from_user.id]
    sess.my = [parse_card(c) for c in cards]
    sess.max_hand = len(sess.my)
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    # фиксируем типовые варианты opp/deck или ввод вручную
    kb.add('opp:6 deck:12','opp:5 deck:13')
    await m.answer(f"Твои карты: {m.text}\nТеперь выбери или введи opp:<N> deck:<M>:", reply_markup=kb)

# ——— opp/deck ввод ———
@dp.message_handler(lambda m: m.text.startswith('opp:'))
async def input_opp_deck(m: types.Message):
    parts = m.text.split()
    opp = int(parts[0].split(':')[1])
    deck = int(parts[1].split(':')[1])
    sess = sessions[m.from_user.id]
    sess.opp = opp
    sess.deck = deck
    await m.answer(
        f"Игра запущена!\nКозырь {SUITS[sess.trump]},\n"
        f"У тебя {len(sess.my)}, у соперника {sess.opp}, в колоде {sess.deck}.\n\n"
        "Теперь кнопки: ⚔️ walk 🛡️ def 🔄 otb 📊 stat",
        reply_markup=types.ReplyKeyboardMarkup(resize_keyboard=True)
            .row('⚔️ walk','🛡️ def')
            .row('🔄 otb','📊 stat')
    )

# ——— Игровые действия ———
@dp.message_handler(lambda m: m.text in ['⚔️ walk','🛡️ def','🔄 otb','📊 stat'])
async def game_action(m: types.Message):
    sess = sessions[m.from_user.id]
    text = m.text
    if 'walk' in text:
        await m.answer(sess.do_walk())
    elif 'def' in text:
        # для примера берём атаку 6s — можно доработать: спросить у пользователя
        await m.answer(sess.do_def('6s'))
    elif 'otb' in text:
        await m.answer(sess.do_otb())
    elif 'stat' in text:
        # просто повторим stat через walk(без хода)
        await m.answer(sess.do_walk(card=None).split('\n')[1])
    # клавиатура остаётся той же

# ——— Запуск Long Polling ———
if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)p