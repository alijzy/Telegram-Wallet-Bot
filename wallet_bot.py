import sqlite3
import datetime
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes,
)

# --- تنظیمات اولیه ---
# توکن ربات شما
TOKEN = "8580562864:AAE8klmt0Qc3uhs7b76y2IaWHEH4zxBC4xU" 
DATABASE_NAME = 'wallet_bot.db'

# رمز عبور شما برای ورود به ربات (در صورت نیاز می‌توانید آن را در آینده تغییر دهید)
ACCESS_CODE = "55555" 

# وضعیت‌های ربات برای مدیریت مکالمه (States)
ADD_PERSON_NAME = 1
CHANGE_PERSON_NAME = 4 
TRANSACTION_AMOUNT_INPUT = 5
TRANSACTION_REASON_INPUT = 6
# وضعیت جدید برای درخواست رمز
ACCESS_CODE_INPUT = 7 

# ----------------------------------------------------------------------------------------------------------------------
# بخش الف: توابع پایگاه داده (SQLite) و توابع کمکی
# ----------------------------------------------------------------------------------------------------------------------

def setup_db():
    """ایجاد جدول‌ها در صورت عدم وجود"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    # ۱. جدول کاربران/افراد
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            balance REAL DEFAULT 0.0
        )
    """)
    
    # ۲. جدول تراکنش‌ها
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL NOT NULL,
            type TEXT NOT NULL, -- 'increase' or 'decrease'
            reason TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    
    # ۳. جدول دسترسی (جدول جدید)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS access (
            user_id INTEGER PRIMARY KEY,
            allowed INTEGER DEFAULT 0 -- 1 for allowed, 0 for not allowed
        )
    """)
    
    conn.commit()
    conn.close()

def db_execute(query, params=None, fetch=False):
    """تابع کمکی برای اجرای کوئری‌های دیتابیس"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    if params:
        cursor.execute(query, params)
    else:
        cursor.execute(query)
    
    if fetch:
        result = cursor.fetchall()
        conn.close()
        return result
    
    conn.commit()
    conn.close()
    return None

def check_access(user_id):
    """بررسی دسترسی کاربر بر اساس user_id تلگرام"""
    result = db_execute("SELECT allowed FROM access WHERE user_id=?", (user_id,), fetch=True)
    if result and result[0][0] == 1:
        return True
    return False

def allow_access(user_id):
    """مجاز کردن دسترسی کاربر"""
    # ابتدا سعی می‌کنیم رکورد را به‌روز کنیم (اگر وجود دارد)
    db_execute("UPDATE access SET allowed=1 WHERE user_id=?", (user_id,))
    # اگر رکورد به‌روز نشد (وجود نداشت)، آن را درج می‌کنیم
    if db_execute("SELECT changes()", fetch=True)[0][0] == 0:
        db_execute("INSERT INTO access (user_id, allowed) VALUES (?, 1)", (user_id,))

# (بقیه توابع کمکی مانند check_person_exists، get_person_list و format_amount بدون تغییر هستند)
def check_person_exists(person_name):
    """بررسی می‌کند که آیا شخصی با این نام وجود دارد یا خیر (بررسی بدون حساسیت به حروف کوچک و بزرگ)."""
    result = db_execute("SELECT id FROM users WHERE name=? COLLATE NOCASE", (person_name,), fetch=True)
    return len(result) > 0

def get_person_list():
    """دریافت لیست افراد برای نمایش دکمه‌ای"""
    return db_execute("SELECT id, name, balance FROM users ORDER BY name", fetch=True)

def get_person_details(user_id):
    """دریافت جزئیات یک فرد"""
    return db_execute("SELECT name, balance FROM users WHERE id=?", (user_id,), fetch=True)

def get_transactions(user_id):
    """دریافت تاریخچه تراکنش‌های یک فرد"""
    return db_execute("SELECT id, amount, type, reason, timestamp FROM transactions WHERE user_id=? ORDER BY timestamp DESC", (user_id,), fetch=True)

def format_amount(amount):
    """نمایش مبلغ با فرمت هزارگان و تومان"""
    if amount is None:
        return "۰ تومان"
        
    # استفاده از قابلیت format برای جداکننده هزارگان و جایگزینی با نقطه
    if amount >= 0:
        formatted_amount = f"{amount:,.0f}".replace(",", ".")
        return f"+ {formatted_amount} تومان"
    else:
        abs_amount = abs(amount)
        formatted_abs = f"{abs_amount:,.0f}".replace(",", ".")
        return f"- {formatted_abs} تومان"


# ----------------------------------------------------------------------------------------------------------------------
# بخش ب: توابع مربوط به کیبوردها (UI)
# ----------------------------------------------------------------------------------------------------------------------

def create_person_menu_keyboard(person_id, person_name):
    """ایجاد کیبورد عملیات‌های فردی"""
    keyboard = [
        [
            InlineKeyboardButton("➕ افزودن مبلغ", callback_data=f"op_add_{person_id}"),
            InlineKeyboardButton("➖ کسر مبلغ", callback_data=f"op_deduct_{person_id}")
        ],
        [
            InlineKeyboardButton("📜 تاریخچه و موجودی", callback_data=f"op_history_{person_id}"),
            InlineKeyboardButton("✏️ تغییر نام", callback_data=f"op_rename_{person_id}")
        ],
        [
            InlineKeyboardButton("🗑️ حذف شخص", callback_data=f"op_confirm_delete_{person_id}"),
        ],
        [
            InlineKeyboardButton("بازگشت به لیست", callback_data="list_people")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def create_main_menu_keyboard():
    """ایجاد کیبورد اصلی ربات"""
    keyboard = [
        [KeyboardButton("👥 لیست افراد"), KeyboardButton("➕ افزودن شخص")],
        [KeyboardButton("📊 گزارش کلی")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

def create_list_people_keyboard(people_list):
    """ایجاد کیبورد دکمه‌ای برای لیست افراد"""
    keyboard = []
    for person_id, name, _ in people_list:
        keyboard.append([InlineKeyboardButton(name, callback_data=f"person_{person_id}")])
        
    keyboard.append([InlineKeyboardButton("بازگشت به منوی اصلی", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)

# ----------------------------------------------------------------------------------------------------------------------
# بخش ج: Handlers ربات (منطق اصلی)
# ----------------------------------------------------------------------------------------------------------------------

# --- توابع مربوط به دسترسی (Access) ---

async def check_access_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بررسی رمز عبور وارد شده توسط کاربر"""
    if context.user_data.get('state') == ACCESS_CODE_INPUT:
        entered_code = update.message.text
        user_id = update.effective_user.id
        
        if entered_code == ACCESS_CODE:
            allow_access(user_id)
            context.user_data.clear()
            
            await update.message.reply_text(
                "✅ دسترسی تأیید شد. به ربات خوش آمدید!",
                reply_markup=create_main_menu_keyboard()
            )
            return True
        else:
            await update.message.reply_text("❌ رمز عبور اشتباه است. لطفاً رمز صحیح را وارد کنید:")
            return True
    return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """پاسخ به دستور /start و نمایش منوی اصلی یا درخواست رمز"""
    user_id = update.effective_user.id
    
    if check_access(user_id):
        context.user_data.clear()
        await update.message.reply_text(
            "👋 خوش آمدید به ربات کیف پول شخصی. لطفاً یکی از گزینه‌ها را انتخاب کنید:",
            reply_markup=create_main_menu_keyboard()
        )
    else:
        context.user_data.clear()
        context.user_data['state'] = ACCESS_CODE_INPUT
        await update.message.reply_text("🔒 برای استفاده از ربات، لطفاً رمز عبور (Access Code) را وارد کنید:")


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """لغو فرآیند جاری و بازگشت به منوی اصلی"""
    
    if not check_access(update.effective_user.id):
        await update.message.reply_text("🔒 لطفاً ابتدا با وارد کردن رمز، وارد ربات شوید.")
        return
        
    # پاکسازی وضعیت و داده‌های موقت
    context.user_data.clear()
    
    await update.message.reply_text(
        '❌ عملیات جاری لغو شد. لطفاً برای شروع مجدد، گزینه مورد نظر را انتخاب کنید.',
        reply_markup=create_main_menu_keyboard()
    )

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بازگشت به منوی اصلی (برای استفاده در Callback Query و دکمه‌ها)"""
    
    if not check_access(update.effective_user.id):
        await update.callback_query.answer("🔒 شما به این بخش دسترسی ندارید.")
        return
        
    chat_id = update.effective_chat.id
    
    context.user_data.clear()
    
    text = "لطفاً یکی از گزینه‌ها را انتخاب کنید:"
    
    if update.callback_query:
        await update.callback_query.answer()
        try:
            await update.callback_query.edit_message_text(text, reply_markup=create_main_menu_keyboard())
        except Exception:
             await context.bot.send_message(chat_id, text, reply_markup=create_main_menu_keyboard())
    elif update.message:
         await update.message.reply_text(text, reply_markup=create_main_menu_keyboard())
         
# --- مدیریت افراد ---

async def add_person_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """درخواست نام شخص جدید"""
    if not check_access(update.effective_user.id): return
    
    await update.message.reply_text("👤 لطفاً **نام** شخص جدید را وارد کنید:")
    context.user_data['state'] = ADD_PERSON_NAME

async def handle_add_person(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ثبت نام شخص جدید یا تغییر نام در دیتابیس"""
    
    if not check_access(update.effective_user.id): return
    
    current_state = context.user_data.get('state')
    
    if current_state == ADD_PERSON_NAME:
        person_name = update.message.text
        if not person_name:
            await update.message.reply_text("نام نمی‌تواند خالی باشد. دوباره امتحان کنید.")
            return True 

        if check_person_exists(person_name):
            await update.message.reply_text(f"❌ شخصی با نام **{person_name}** از قبل ثبت شده است. لطفاً نام دیگری وارد کنید:", parse_mode='Markdown')
            return True 

        db_execute("INSERT INTO users (name) VALUES (?)", (person_name,))
        
        del context.user_data['state']
        
        await update.message.reply_text(
            f"✅ شخص **{person_name}** با موفقیت اضافه شد.",
            reply_markup=create_main_menu_keyboard(),
            parse_mode='Markdown'
        )
        return True
        
    elif current_state == CHANGE_PERSON_NAME:
        new_name = update.message.text
        person_id = context.user_data.get('current_person_id')
        
        if check_person_exists(new_name):
            await update.message.reply_text(f"❌ شخصی با نام **{new_name}** از قبل ثبت شده است. لطفاً نام دیگری وارد کنید:", parse_mode='Markdown')
            return True 
        
        db_execute("UPDATE users SET name=? WHERE id=?", (new_name, person_id))
        
        del context.user_data['state']
        del context.user_data['current_person_id']
        
        await update.message.reply_text(f"✅ نام شخص با موفقیت به **{new_name}** تغییر یافت.", reply_markup=create_main_menu_keyboard(), parse_mode='Markdown')
        return True 

    return None 

async def list_people(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش لیست افراد به صورت دکمه‌ای"""
    
    if not check_access(update.effective_user.id): 
        if update.callback_query: await update.callback_query.answer("🔒 شما به این بخش دسترسی ندارید.")
        return
        
    people = get_person_list()
    if not people:
        text = "🤷‍♂️ در حال حاضر هیچ شخصی ثبت نشده است. لطفاً ابتدا یک نفر را اضافه کنید."
        reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("➕ افزودن شخص جدید", callback_data="add_person")]])
    else:
        text = "👥 **لیست افراد:**\nلطفاً برای مشاهده جزئیات، روی نام شخص کلیک کنید:"
        reply_markup = create_list_people_keyboard(people)
    
    if update.callback_query:
        await update.callback_query.answer()
        try:
             await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
        except Exception:
             await context.bot.send_message(update.effective_chat.id, text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def show_person_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش منوی عملیات برای یک فرد خاص"""
    
    if not check_access(update.effective_user.id): 
        await update.callback_query.answer("🔒 شما به این بخش دسترسی ندارید.")
        return
        
    query = update.callback_query
    await query.answer()
    
    person_id = int(query.data.split('_')[1])
    context.user_data['current_person_id'] = person_id
    
    details = get_person_details(person_id)
    if not details:
        await query.edit_message_text("⚠️ شخص مورد نظر یافت نشد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("بازگشت به لیست", callback_data="list_people")]]))
        return
        
    person_name, balance = details[0]
    
    text = f"✨ **منوی {person_name}**\n\n💰 **موجودی فعلی:** {format_amount(balance)}"
    reply_markup = create_person_menu_keyboard(person_id, person_name)
    
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def handle_rename_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """درخواست نام جدید برای تغییر نام"""
    
    if not check_access(update.effective_user.id): 
        await update.callback_query.answer("🔒 شما به این بخش دسترسی ندارید.")
        return
        
    query = update.callback_query
    await query.answer()
    
    person_id = int(query.data.split('_')[1])
    context.user_data['current_person_id'] = person_id
    context.user_data['state'] = CHANGE_PERSON_NAME
    
    await query.edit_message_text("✏️ لطفاً نام جدید شخص را وارد کنید:")

async def handle_confirm_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """درخواست تایید حذف شخص"""
    
    if not check_access(update.effective_user.id): 
        await update.callback_query.answer("🔒 شما به این بخش دسترسی ندارید.")
        return
        
    query = update.callback_query
    await query.answer()
    
    person_id = int(query.data.split('_')[3])
    
    details = get_person_details(person_id)
    if not details:
        return await query.edit_message_text("⚠️ شخص مورد نظر یافت نشد.")

    person_name, _ = details[0]
    
    keyboard = [
        [
            InlineKeyboardButton("❌ لغو", callback_data=f"person_{person_id}"),
            InlineKeyboardButton("🔥 تایید حذف", callback_data=f"op_delete_{person_id}")
        ]
    ]
    await query.edit_message_text(f"⚠️ آیا مطمئن هستید که می‌خواهید شخص **{person_name}** و **تمامی تراکنش‌های مرتبط** با او را حذف کنید؟", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def handle_delete_person(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """اجرای عملیات حذف شخص و تراکنش‌ها"""
    
    if not check_access(update.effective_user.id): 
        await update.callback_query.answer("🔒 شما به این بخش دسترسی ندارید.")
        return
        
    query = update.callback_query
    await query.answer()
    
    person_id = int(query.data.split('_')[2])
    
    try:
        # حذف تراکنش‌ها
        db_execute("DELETE FROM transactions WHERE user_id=?", (person_id,))
        # حذف شخص
        db_execute("DELETE FROM users WHERE id=?", (person_id,))
        
        await query.edit_message_text("✅ شخص و تمامی تراکنش‌های مرتبط با موفقیت حذف شدند.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("بازگشت به لیست", callback_data="list_people")]]))
    except Exception as e:
        logging.error(f"Error deleting person ID {person_id}: {e}")
        await query.edit_message_text("❌ متأسفانه در حذف شخص خطایی رخ داد. لطفاً مجدداً امتحان کنید.")


# --- مدیریت تراکنش‌ها (درون منوی فرد) ---

async def transaction_prompt_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع فرآیند تراکنش: درخواست مبلغ"""
    
    if not check_access(update.effective_user.id): 
        await update.callback_query.answer("🔒 شما به این بخش دسترسی ندارید.")
        return
        
    query = update.callback_query
    await query.answer()
    
    op_type = query.data.split('_')[1] # 'add' or 'deduct'
    person_id = int(query.data.split('_')[2])
    
    context.user_data['temp_data'] = {'type': op_type, 'person_id': person_id}
    context.user_data['state'] = TRANSACTION_AMOUNT_INPUT
    
    action = "افزایش" if op_type == 'add' else "کاهش"
    
    await query.edit_message_text(f"لطفاً **مبلغ** مورد نظر برای **{action}** را وارد کنید (فقط عدد، بدون واحد):", parse_mode='Markdown')

async def transaction_prompt_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """درخواست دلیل/توضیحات تراکنش"""
    
    if not check_access(update.effective_user.id): return
    
    amount_text = update.message.text
    
    try:
        amount = float(amount_text.replace(',', '').replace('.', '')) 
        if amount <= 0:
            await update.message.reply_text("مبلغ باید یک عدد مثبت باشد. لطفاً دوباره وارد کنید.")
            return True 
        
        context.user_data['temp_data']['amount'] = amount
        context.user_data['state'] = TRANSACTION_REASON_INPUT
        
        await update.message.reply_text("📝 لطفاً **دلیل/توضیحات** این تراکنش را وارد کنید:")
        return True 
    except ValueError:
        await update.message.reply_text("⚠️ فرمت مبلغ وارد شده صحیح نیست. لطفاً فقط عدد وارد کنید:")
        return True 


async def transaction_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ثبت نهایی تراکنش در دیتابیس"""
    
    if not check_access(update.effective_user.id): return
    
    reason = update.message.text
    
    if not reason:
        await update.message.reply_text("دلیل تراکنش نمی‌تواند خالی باشد. دوباره وارد کنید.")
        return True 

    data = context.user_data.get('temp_data')
    if not data:
        await update.message.reply_text("⚠️ خطایی در فرآیند تراکنش رخ داده است. لطفاً مجدداً از منوی فرد اقدام کنید.")
        return True 

    person_id = data['person_id']
    amount = data['amount']
    op_type = data['type']

    balance_change = amount if op_type == 'add' else -amount
    
    db_execute("UPDATE users SET balance = balance + ? WHERE id=?", (balance_change, person_id))
    
    db_execute("INSERT INTO transactions (user_id, amount, type, reason) VALUES (?, ?, ?, ?)",
                (person_id, amount, op_type, reason))

    del context.user_data['temp_data']
    del context.user_data['state']
    
    await update.message.reply_text(
        f"✅ تراکنش **{format_amount(balance_change)}** با موفقیت ثبت شد.\nدلیل: {reason}",
        reply_markup=create_main_menu_keyboard(),
        parse_mode='Markdown'
    )
    return True 


async def show_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش تاریخچه تراکنش‌ها و موجودی"""
    
    if not check_access(update.effective_user.id): 
        await update.callback_query.answer("🔒 شما به این بخش دسترسی ندارید.")
        return
        
    query = update.callback_query
    await query.answer()
    
    person_id = int(query.data.split('_')[2])
    details = get_person_details(person_id)
    if not details: return await query.edit_message_text("⚠️ شخص مورد نظر یافت نشد.")
    
    person_name, balance = details[0]
    transactions = get_transactions(person_id)
    
    text = f"📜 **تاریخچه تراکنش‌های {person_name}**\n\n💰 **موجودی فعلی:** {format_amount(balance)}\n\n"
    
    if not transactions:
        text += "❌ تراکنشی یافت نشد."
        final_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("بازگشت به منوی فرد", callback_data=f"person_{person_id}")]])
    else:
        final_keyboard_rows = []
        for t_id, amount, t_type, reason, timestamp in transactions:
            sign = "➕" if t_type == 'increase' else "➖"
            
            amount_display = f"{amount:,.0f}".replace(",", ".")
            
            dt_object = datetime.datetime.strptime(timestamp.split('.')[0], '%Y-%m-%d %H:%M:%S')
            date_display = dt_object.strftime("%Y/%m/%d - %H:%M")
            
            text += f"{sign} **{amount_display}** ({t_type.replace('increase', 'افزایش').replace('decrease', 'کاهش')})\n دلیل: {reason} | تاریخ: {date_display}\n\n"
            
            final_keyboard_rows.append([
                InlineKeyboardButton(f"🗑️ حذف تراکنش #{t_id}", callback_data=f"op_confirm_t_delete_{t_id}")
            ])
            
        final_text = text

        keyboard = [
            [InlineKeyboardButton("بازگشت به منوی فرد", callback_data=f"person_{person_id}")]
        ]
        final_keyboard = InlineKeyboardMarkup(final_keyboard_rows + keyboard)
    
    await query.edit_message_text(final_text, reply_markup=final_keyboard, parse_mode='Markdown')
    
async def handle_confirm_transaction_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """درخواست تایید حذف تراکنش"""
    
    if not check_access(update.effective_user.id): 
        await update.callback_query.answer("🔒 شما به این بخش دسترسی ندارید.")
        return
        
    query = update.callback_query
    await query.answer()
    
    t_id = int(query.data.split('_')[3])
    
    transaction = db_execute("SELECT user_id, amount, type FROM transactions WHERE id=?", (t_id,), fetch=True)
    if not transaction:
        return await query.edit_message_text("⚠️ تراکنش یافت نشد.")
    
    user_id, amount, t_type = transaction[0]
    
    keyboard = [
        [
            InlineKeyboardButton("❌ لغو", callback_data=f"op_history_{user_id}"),
            InlineKeyboardButton("🔥 تایید حذف", callback_data=f"op_t_delete_{t_id}")
        ]
    ]
    
    action = "افزایش" if t_type == 'increase' else "کاهش"
    
    amount_display = f"{amount:,.0f}".replace(",", ".")
    
    await query.edit_message_text(
        f"⚠️ آیا مطمئن هستید که می‌خواهید تراکنش **{amount_display} تومان** ({action}) را حذف کنید؟ این عمل موجودی فرد را تغییر خواهد داد.", 
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def handle_transaction_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """اجرای عملیات حذف تراکنش"""
    
    if not check_access(update.effective_user.id): 
        await update.callback_query.answer("🔒 شما به این بخش دسترسی ندارید.")
        return
        
    query = update.callback_query
    await query.answer()
    
    t_id = int(query.data.split('_')[2])
    
    transaction = db_execute("SELECT user_id, amount, type FROM transactions WHERE id=?", (t_id,), fetch=True)
    if not transaction:
        return await query.edit_message_text("⚠️ تراکنش یافت نشد.")

    user_id, amount, t_type = transaction[0]
    
    # ۱. برگرداندن موجودی (عملیات معکوس)
    balance_undo = -amount if t_type == 'increase' else amount
    db_execute("UPDATE users SET balance = balance + ? WHERE id=?", (balance_undo, user_id))
    
    # ۲. حذف تراکنش
    db_execute("DELETE FROM transactions WHERE id=?", (t_id,))
    
    await query.edit_message_text(f"✅ تراکنش #{t_id} با موفقیت حذف و موجودی به‌روزرسانی شد.")
    
    # فراخوانی مجدد نمایش تاریخچه
    query.data = f"op_history_{user_id}"
    await show_history(update, context)


# --- گزارش کلی و CSV ---

async def generate_csv_report():
    """تولید محتوای فایل CSV"""
    all_users = db_execute("SELECT name, balance FROM users ORDER BY balance DESC", fetch=True)
    
    # BOM for Farsi support in Excel
    csv_content = '\ufeff' + "نام,موجودی,وضعیت\n"
    for name, balance in all_users:
        status = "بستانکار" if balance >= 0 else "بدهکار"
        formatted_balance = f"{abs(balance):,.0f}".replace(",", ".")
        csv_content += f"{name},{formatted_balance},{status}\n"
        
    return csv_content.encode('utf-8')

async def global_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش گزارش کلی و دکمه CSV"""
    
    if not check_access(update.effective_user.id): return
    
    all_users = db_execute("SELECT name, balance FROM users ORDER BY balance DESC", fetch=True)
    
    text = "📊 **گزارش کلی وضعیت افراد**:\n\n"
    total_balance = 0.0
    
    if not all_users:
        text += "❌ هیچ شخصی در سیستم ثبت نشده است."
    else:
        for name, balance in all_users:
            status = "🟢 بستانکار" if balance >= 0 else "🔴 بدهکار"
            text += f"{status} **{name}**: `{format_amount(balance)}`\n"
            total_balance += balance
            
        text += "\n---\n"
        text += f"⚖️ **جمع موجودی‌ها (تراز):** `{format_amount(total_balance)}`"
    
    keyboard = [
        [InlineKeyboardButton("⬇️ دریافت CSV گزارش", callback_data="get_csv_report")]
    ]
    
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def send_csv_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ارسال فایل CSV"""
    
    if not check_access(update.effective_user.id): 
        await update.callback_query.answer("🔒 شما به این بخش دسترسی ندارید.")
        return
        
    query = update.callback_query
    await query.answer("در حال آماده‌سازی فایل CSV...")
    
    csv_data = await generate_csv_report()
    
    await context.bot.send_document(
        chat_id=query.message.chat_id,
        document=csv_data,
        filename=f"Global_Wallet_Report_{datetime.date.today().isoformat()}.csv",
        caption="فایل گزارش کلی وضعیت مالی افراد:",
        reply_markup=None 
    )
    
    try:
        await query.edit_message_reply_markup(reply_markup=None) 
    except Exception:
        pass


# --- هندلر واحد برای مدیریت تمام حالت‌های متنی ---

async def handle_states_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    هندلر واحد برای مدیریت تمام حالت‌های Conversation (گروه 0).
    """
    
    state = context.user_data.get('state')
    
    if state == ACCESS_CODE_INPUT:
        return await check_access_code(update, context)

    # اگر کاربر دسترسی ندارد، نباید اجازه ادامه داشته باشد
    if not check_access(update.effective_user.id):
        return None # اجازه می‌دهد به handle_message در گروه 1 برود
    
    if state == ADD_PERSON_NAME or state == CHANGE_PERSON_NAME:
        return await handle_add_person(update, context)
        
    elif state == TRANSACTION_AMOUNT_INPUT:
        return await transaction_prompt_reason(update, context)
        
    elif state == TRANSACTION_REASON_INPUT:
        return await transaction_confirm(update, context)
        
    return None 


# --- مدیریت پیام‌های ناشناخته ---

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت پیام‌های متنی در صورت عدم تطابق با حالت‌های (state) مختلف یا دکمه‌های Reply Keyboard"""
    
    if not check_access(update.effective_user.id):
        # اگر رمز وارد نکرده باشد، پیام خطا نمایش می‌دهد (در صورتی که handle_states_text آن را پردازش نکرده باشد)
        await update.message.reply_text("🔒 برای استفاده از ربات، لطفاً دستور /start را وارد کنید و رمز عبور را وارد نمایید.")
        return
        
    if context.user_data.get('state'):
        # اگر در حالت مکالمه فعال هستیم اما هیچکدام از Handlers گروه ۰ آن را پردازش نکردند
        await update.message.reply_text("لطفاً فرآیند جاری (مانند افزودن شخص یا تراکنش) را با وارد کردن اطلاعات خواسته شده، تکمیل یا **دستور /cancel** را وارد کنید.", reply_markup=create_main_menu_keyboard())
        return

    # مدیریت دکمه‌های Reply Keyboard
    text = update.message.text
    if text == "➕ افزودن شخص":
        await add_person_prompt(update, context)
    elif text == "👥 لیست افراد":
        await list_people(update, context)
    elif text == "📊 گزارش کلی":
        await global_report(update, context)
    else:
         await update.message.reply_text("لطفاً از دکمه‌ها برای عملیات استفاده کنید.", reply_markup=create_main_menu_keyboard())


# ----------------------------------------------------------------------------------------------------------------------
# بخش د: اجرای ربات
# ----------------------------------------------------------------------------------------------------------------------

def main() -> None:
    """اجرای اصلی ربات"""
    setup_db() 
    
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    
    application = Application.builder().token(TOKEN).build()

    # --- Handlers فرمان‌ها ---
    application.add_handler(CommandHandler("start", start))
    
    # --- دستور /cancel (اولویت 0) ---
    application.add_handler(CommandHandler("cancel", cancel_command), group=0) 

    # --- Handlers وضعیت (اولویت بالا: گروه ۰) ---
    # این هندلر واحد، تمام پیام‌های متنی غیرفرمان را در حالت Conversation (State) مدیریت می‌کند.
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_states_text), group=0)
    
    # --- Handler دکمه‌های Reply Keyboard و پیام‌های ناشناخته (اولویت متوسط: گروه ۱) ---
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message), group=1) 


    # --- Handlers دکمه‌های Inline (Callback Queries) ---
    application.add_handler(CallbackQueryHandler(show_main_menu, pattern="^main_menu$"))
    application.add_handler(CallbackQueryHandler(list_people, pattern="^list_people$|^add_person$"))
    application.add_handler(CallbackQueryHandler(show_person_menu, pattern="^person_")) 
    
    # عملیات‌های فردی (افزودن/کسر، تاریخچه، تغییر نام)
    application.add_handler(CallbackQueryHandler(transaction_prompt_amount, pattern="^op_add_|^op_deduct_"))
    application.add_handler(CallbackQueryHandler(show_history, pattern="^op_history_"))
    application.add_handler(CallbackQueryHandler(handle_rename_prompt, pattern="^op_rename_"))
    
    # حذف فرد
    application.add_handler(CallbackQueryHandler(handle_confirm_delete, pattern="^op_confirm_delete_"))
    application.add_handler(CallbackQueryHandler(handle_delete_person, pattern="^op_delete_"))
    
    # گزارش و CSV
    application.add_handler(CallbackQueryHandler(send_csv_file, pattern="^get_csv_report$"))
    
    # حذف تراکنش
    application.add_handler(CallbackQueryHandler(handle_confirm_transaction_delete, pattern="^op_confirm_t_delete_"))
    application.add_handler(CallbackQueryHandler(handle_transaction_delete, pattern="^op_t_delete_"))


    print("Bot is polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()