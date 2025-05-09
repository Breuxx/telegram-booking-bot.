#!/usr/bin/env python3
import logging
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    Filters,
    CallbackContext,
)
from collections import defaultdict

# ====== Настройка логирования ======
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ====== Бот-токен ======
API_TOKEN = "ВАШ_ТОКЕН_От_BotFather"

# ====== Карты и логика ======
RANKS = ['6','7','8','9','10','J','Q','K','A']
SUITS = {'s':'♠','h':'♥','d':'♦','c':'♣'}

def parse_card(card: str):
    return card[:-1], card[-1]

def card_to_str(c: tuple):
    return c[0] + SUITS.get(c[1], c[1])

def beats(att: tuple, dfn: tuple, trump: str) -> bool:
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
    def do_walk(self):
        non_tr = [c for c in self.my if c[1]!=self.trump]
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
            self.unknown = max(0, self.unknown-1)
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
        if total_my+total_opp==0:
            return "▶ Нет карт — нечего считать."
        chance = total_my/(total_my+total_opp)*100
        return f"▶ Шанс победы ≈ {chance:.0f}%"

sessions = defaultdict(TrainerSession)

# ====== Обработчики ======

def start(update: Update, context: CallbackContext):
    kb = [
        [KeyboardButton('♠ s'), KeyboardButton('♥ h')],
        [KeyboardButton('♦ d'), KeyboardButton('♣ c')]
    ]
    update.message.reply_text(
        "Выбери козырь:",
        reply_markup=ReplyKeyboardMarkup(kb, one_time_keyboard=True, resize_keyboard=True)
    )

def text_handler(update: Update, context: CallbackContext):
    text = update.message.text.strip()
    sess = sessions[update.effective_user.id]

    # 1) выбор козыря
    if text in ['s','h','d','c','♠','♥','♦','♣'] and sess.trump is None:
        trump = text if text in SUITS else {v:k for k,v in SUITS.items()}[text]
        sess.reset(); sess.trump = trump
        update.message.reply_text(
            f"Козырь: {SUITS[trump]}\nВведи свои карты (напр. 6s 7h Ah):",
            reply_markup=ReplyKeyboardRemove()
        )
        return

    # 2) ввод своих карт
    if sess.trump and not sess.my:
        cards = text.split()
        sess.my = [parse_card(c) for c in cards]
        sess.max_hand = len(sess.my)
        kb = [['opp:6 deck:12','opp:5 deck:13']]
        update.message.reply_text(
            f"Твои карты: {' '.join(card_to_str(c) for c in sess.my)}\nТеперь opp и deck:",
            reply_markup=ReplyKeyboardMarkup(kb, one_time_keyboard=True, resize_keyboard=True)
        )
        return

    # 3) opp/deck
    if text.startswith('opp:') and sess.my and sess.opp==0:
        parts = text.split()
        sess.opp = int(parts[0].split(':')[1])
        sess.deck = int(parts[1].split(':')[1])
        kb = [['⚔️ walk','🛡️ def'], ['🔄 otb','📊 stat']]
        update.message.reply_text(
            f"Старт!\nКозырь {SUITS[sess.trump]}, ты {len(sess.my)}, опп {sess.opp}, deck {sess.deck}",
            reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True)
        )
        return

    # 4) игровые кнопки
    if text == '⚔️ walk':
        update.message.reply_text(sess.do_walk())
    elif text == '🛡️ def':
        # для примера берем атаку '6s'
        update.message.reply_text(sess.do_def('6s'))
    elif text == '🔄 otb':
        update.message.reply_text(sess.do_otb())
    elif text == '📊 stat':
        update.message.reply_text(sess.do_stat())
    else:
        update.message.reply_text("Неизвестная команда.")

def reset(update: Update, context: CallbackContext):
    sessions[update.effective_user.id].reset()
    update.message.reply_text("▶ Сессия сброшена. /start чтобы начать заново.", reply_markup=ReplyKeyboardRemove())

# ====== Main ======
def main():
    updater = Updater(API_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler('start', start))
    dp.add_handler(CommandHandler('init', start))
    dp.add_handler(CommandHandler('reset', reset))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, text_handler))

    updater.start_polling()
    logger.info("Бот запущен.")
    updater.idle()

if __name__ == '__main__':
    main()