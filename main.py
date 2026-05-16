import discord
from discord.ext import commands
from discord.ui import Button, View, Modal, TextInput
from dotenv import load_dotenv
import os
import asyncio
from datetime import datetime, timedelta

# ==================== ЗАГРУЗКА ПЕРЕМЕННЫХ ====================

load_dotenv()

TOKEN = os.getenv('DISCORD_TOKEN')
GUILD_ID = int(os.getenv('GUILD_ID'))
ROLE_ID = int(os.getenv('ROLE_ID'))  # Роль "Верификация"
GUEST_ROLE_ID = int(os.getenv('GUEST_ROLE_ID'))  # Роль "Гость"
ADMIN_ROLE_ID = int(os.getenv('ADMIN_ROLE_ID'))
TICKET_CHANNEL_ID = int(os.getenv('TICKET_CHANNEL_ID'))
LOG_CHANNEL_ID = int(os.getenv('LOG_CHANNEL_ID'))
APPROVER_ROLE_ID = int(os.getenv('APPROVER_ROLE_ID'))
GUIDE_ROLE_ID = int(os.getenv('GUIDE_ROLE_ID'))
VERIFY_CHANNEL_ID = int(os.getenv('VERIFY_CHANNEL_ID'))

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.dm_messages = True
bot = commands.Bot(command_prefix='!', intents=intents)

# ==================== ЗАЩИТА ОТ RATE LIMIT ====================

async def safe_delete_messages(channel, limit=5, delay=0.5):
    """Безопасное удаление сообщений с задержками"""
    deleted = 0
    async for msg in channel.history(limit=limit):
        if msg.author == bot.user:
            try:
                await msg.delete()
                deleted += 1
                await asyncio.sleep(delay)
            except discord.Forbidden:
                pass
            except discord.HTTPException as e:
                if e.status == 429:
                    retry_after = int(e.response.headers.get('Retry-After', 5))
                    print(f"⏳ Rate limit! Ждём {retry_after} сек...")
                    await asyncio.sleep(retry_after + 1)
                    continue
                print(f"❌ Ошибка удаления: {e}")
    return deleted

async def safe_panel_cleanup(channel):
    """Очистка панели с защитой от rate limit"""
    deleted = 0
    async for msg in channel.history(limit=3):
        if msg.author == bot.user:
            try:
                await msg.delete()
                deleted += 1
                await asyncio.sleep(1)
            except discord.HTTPException as e:
                if e.status == 429:
                    print(f"⚠️ Превышен лимит, прекращаем очистку")
                    break
                print(f"❌ Ошибка: {e}")
    return deleted

# ==================== ПРОВЕРКА ПРАВ ====================

def is_approver():
    """Проверка: есть ли у пользователя высокая роль"""
    async def predicate(ctx):
        if ctx.author.guild_permissions.administrator:
            return True
        role = ctx.guild.get_role(APPROVER_ROLE_ID)
        return role and role in ctx.author.roles
    return commands.check(predicate)

# Хранилища
dm_responses = {}
verified_users = set()

# ==================== ВЕРИФИКАЦИЯ ====================

class VerifyModal(Modal):
    def __init__(self):
        super().__init__(title="✅ Верификация", timeout=600)
        self.nickname = TextInput(
            label="Ваш никнейм",
            placeholder="Введите ник для сервера",
            style=discord.TextStyle.short,
            required=True,
            min_length=2,
            max_length=32
        )
        self.add_item(self.nickname)

    async def on_submit(self, interaction: discord.Interaction):
        nickname = self.nickname.value.strip()
        clean_nickname = ''.join(c for c in nickname if c.isalnum() or c in ' _-')
        
        if len(clean_nickname) < 2:
            await interaction.response.send_message("❌ Ник слишком короткий (минимум 2 символа)", ephemeral=True)
            return
        
        try:
            member = interaction.guild.get_member(interaction.user.id)
            await member.edit(nick=clean_nickname, reason="Верификация пройдена")
            
            guest_role = interaction.guild.get_role(GUEST_ROLE_ID)
            if guest_role:
                await member.add_roles(guest_role, reason="Верификация пройдена")
            
            verify_role = interaction.guild.get_role(ROLE_ID)
            if verify_role and verify_role in member.roles:
                await member.remove_roles(verify_role, reason="Верификация пройдена")
            
            verified_users.add(interaction.user.id)
            
            embed = discord.Embed(
                title="✅ Верификация пройдена!",
                description=f"Добро пожаловать, {clean_nickname}!\n\nТеперь вам доступны все каналы.",
                color=discord.Color.green()
            )
            embed.add_field(name="📋 Что дальше?", value="• Ознакомься с правилами\n• Заполни профиль\n• Общайся!", inline=False)
            embed.set_footer(text="При проблемах — создай тикет")
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
            # Лог
            log_channel = bot.get_channel(LOG_CHANNEL_ID)
            if log_channel:
                log_embed = discord.Embed(
                    title="👤 Новая верификация",
                    description=f"{interaction.user.mention} прошёл верификацию",
                    color=discord.Color.blue(),
                    timestamp=datetime.utcnow()
                )
                log_embed.add_field(name="Никнейм", value=clean_nickname, inline=True)
                log_embed.add_field(name="ID", value=str(interaction.user.id), inline=True)
                await log_channel.send(embed=log_embed)
            
        except discord.Forbidden:
            await interaction.response.send_message("❌ У бота нет прав изменить ник!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Ошибка: {e}", ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        print(f"❌ Ошибка верификации: {error}")
        try:
            await interaction.response.send_message(f"❌ Ошибка: {error}", ephemeral=True)
        except:
            pass


class VerifyButton(Button):
    def __init__(self):
        super().__init__(label="✅ Пройти верификацию", style=discord.ButtonStyle.green, custom_id="verify:start")

    async def callback(self, interaction: discord.Interaction):
        member = interaction.guild.get_member(interaction.user.id)
        guest_role = interaction.guild.get_role(GUEST_ROLE_ID)
        
        if guest_role and guest_role in member.roles:
            await interaction.response.send_message("✅ Вы уже прошли верификацию!", ephemeral=True)
            return
        
        modal = VerifyModal()
        await interaction.response.send_modal(modal)


class VerifyView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(VerifyButton())


async def create_verify_panel():
    channel = bot.get_channel(VERIFY_CHANNEL_ID)
    if not channel:
        print(f"❌ Канал верификации {VERIFY_CHANNEL_ID} не найден!")
        return

    await safe_panel_cleanup(channel)

    embed = discord.Embed(
        title="👋 Добро пожаловать!",
        description="**Для доступа ко всем каналам пройдите верификацию**\n\n"
                   "🔹 Нажмите кнопку ниже\n"
                   "🔹 Введите ваш никнейм\n"
                   "🔹 Получите доступ",
        color=discord.Color.blue()
    )
    embed.add_field(name="⚠️ Важно", value="• Ник от 2 до 32 символов\n• Разрешены буквы, цифры, _ и -", inline=False)
    embed.set_footer(text="При проблемах — создайте тикет")

    view = VerifyView()
    await channel.send(embed=embed, view=view)
    print("✅ Панель верификации создана!")

# ==================== ЛОГИРОВАНИЕ ТИКЕТОВ ====================

async def log_ticket_messages(channel, closed_by):
    log_channel = bot.get_channel(LOG_CHANNEL_ID)
    if not log_channel:
        print(f"❌ Лог-канал {LOG_CHANNEL_ID} не найден!")
        return None
    
    messages = []
    async for msg in channel.history(limit=None, oldest_first=True):
        messages.append(msg)
        if len(messages) >= 200:  # Ограничение для защиты от rate limit
            break
    
    if not messages:
        return None
    
    embed = discord.Embed(
        title="📋 Архив тикета",
        description=f"**Канал:** {channel.name}\n**Закрыт:** {closed_by.mention if closed_by else 'Неизвестно'}\n**Дата:** {datetime.now().strftime('%d.%m.%Y %H:%M')}",
        color=discord.Color.dark_blue(),
        timestamp=datetime.utcnow()
    )
    
    ticket_owner_name = channel.name.replace('тикет-', '')
    embed.add_field(name="👤 Создатель", value=ticket_owner_name, inline=True)
    embed.add_field(name="💬 Сообщений", value=str(len(messages)), inline=True)
    
    log_text = ""
    for msg in messages:
        author = msg.author
        timestamp = msg.created_at.strftime('%H:%M')
        content = msg.content.replace('`', "'")[:500]
        attachments = f" [📎{len(msg.attachments)}]" if msg.attachments else ""
        line = f"[{timestamp}] {author}: {content}{attachments}\n"
        
        if len(log_text) + len(line) < 3800:
            log_text += line
        else:
            break
    
    if log_text:
        chunks = [log_text[i:i+1024] for i in range(0, len(log_text), 1024)]
        for i, chunk in enumerate(chunks[:5]):
            embed.add_field(name=f"📄 Сообщения {i+1}" if i > 0 else "📄 История", value=chunk or "Пусто", inline=False)
    
    try:
        log_message = await log_channel.send(embed=embed)
        
        # Сохраняем только последние 5 вложений для защиты от rate limit
        attachment_count = 0
        for msg in messages:
            for attachment in msg.attachments:
                if attachment_count >= 5:
                    break
                try:
                    await log_channel.send(
                        content=f"📎 Вложение от {msg.author} ({channel.name})",
                        file=await attachment.to_file()
                    )
                    attachment_count += 1
                    await asyncio.sleep(1)  # Задержка между вложениями
                except:
                    pass
        
        return log_message
    except Exception as e:
        print(f"❌ Ошибка отправки лога: {e}")
        return None

# ==================== ПЕРЕХВАТ ЛС ====================

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    
    if isinstance(message.channel, discord.DMChannel):
        user_id = message.author.id
        
        if user_id not in dm_responses:
            dm_responses[user_id] = []
        
        dm_responses[user_id].append({
            'content': message.content,
            'timestamp': message.created_at,
            'attachments': [att.url for att in message.attachments]
        })
        
        guild = bot.get_guild(GUILD_ID)
        if guild:
            ticket_channel = None
            for channel in guild.text_channels:
                if channel.name.startswith('тикет-') and (message.author.name in channel.name or message.author.display_name in channel.name):
                    ticket_channel = channel
                    break
            
            if ticket_channel:
                embed = discord.Embed(
                    title="📩 Ответ в ЛС",
                    description=f"{message.author.mention} написал боту:",
                    color=discord.Color.blurple(),
                    timestamp=message.created_at
                )
                embed.add_field(name="💬 Текст", value=message.content[:1024] or "[Только вложения]", inline=False)
                if message.attachments:
                    embed.add_field(name="📎 Вложений", value=str(len(message.attachments)), inline=True)
                
                try:
                    await ticket_channel.send(embed=embed)
                    await asyncio.sleep(0.5)
                except:
                    pass
        
        await message.channel.send("✅ Сообщение получено!")
        return
    
    await bot.process_commands(message)

# ==================== КОМАНДЫ ЛС ====================

@bot.command()
@commands.has_permissions(administrator=True)
async def лс(ctx, member: discord.Member):
    if member.id not in dm_responses or not dm_responses[member.id]:
        await ctx.send(f"❌ Нет сообщений от {member.mention}")
        return
    
    embed = discord.Embed(
        title=f"📩 ЛС: {member.display_name}",
        description=f"Всего: {len(dm_responses[member.id])}",
        color=discord.Color.purple()
    )
    
    for i, msg in enumerate(dm_responses[member.id][-5:], 1):
        time = msg['timestamp'].strftime('%d.%m %H:%M')
        content = msg['content'][:500] or "[Вложения]"
        embed.add_field(name=f"#{i} ({time})", value=content, inline=False)
    
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(administrator=True)
async def очистить_лс(ctx, member: discord.Member = None):
    if member:
        if member.id in dm_responses:
            del dm_responses[member.id]
            await ctx.send(f"✅ История {member.mention} очищена")
        else:
            await ctx.send("❌ Нет истории")
    else:
        dm_responses.clear()
        await ctx.send("✅ Вся история ЛС очищена")

# ==================== ОЧИСТКА ЧАТА ====================

@bot.command()
@is_approver()
async def очистить(ctx, *, args: str = None):
    if not ctx.channel.name.startswith('тикет-') and not ctx.author.guild_permissions.manage_messages:
        await ctx.send("❌ Только в тикетах!", delete_after=5)
        return
    
    await ctx.message.delete()
    await asyncio.sleep(0.5)
    
    if not args:
        embed = discord.Embed(
            title="🧹 Очистка чата",
            description="**Использование:**\n"
                       "• `!очистить 50` — удалить последние 50 сообщений\n"
                       "• `!очистить дни 1` — удалить за 1 день\n"
                       "• `!очистить всё` — удалить ВСЁ",
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed, delete_after=15)
        return
    
    args = args.lower().strip()
    
    if args == 'всё':
        confirm_embed = discord.Embed(
            title="⚠️ Подтверждение",
            description="Удалить **ВСЕ** сообщения?",
            color=discord.Color.red()
        )
        confirm_view = View(timeout=30)
        
        async def confirm_yes(interaction: discord.Interaction):
            if interaction.user != ctx.author:
                await interaction.response.send_message("❌ Не ваша кнопка!", ephemeral=True)
                return
            await interaction.response.defer()
            deleted = 0
            async for msg in ctx.channel.history(limit=None):
                try:
                    await msg.delete()
                    deleted += 1
                    await asyncio.sleep(0.5)
                except discord.HTTPException as e:
                    if e.status == 429:
                        retry_after = int(e.response.headers.get('Retry-After', 5))
                        await asyncio.sleep(retry_after + 1)
                        continue
                    break
            await ctx.send(f"✅ Удалено {deleted} сообщений", delete_after=5)
            confirm_view.stop()
        
        async def confirm_no(interaction: discord.Interaction):
            if interaction.user != ctx.author:
                return
            await interaction.response.send_message("❌ Отменено", ephemeral=True)
            confirm_view.stop()
        
        btn_yes = Button(label="✅ Да", style=discord.ButtonStyle.danger, custom_id="confirm_yes")
        btn_no = Button(label="❌ Нет", style=discord.ButtonStyle.secondary, custom_id="confirm_no")
        btn_yes.callback = confirm_yes
        btn_no.callback = confirm_no
        confirm_view.add_item(btn_yes)
        confirm_view.add_item(btn_no)
        
        confirm_msg = await ctx.send(embed=confirm_embed, view=confirm_view)
        
        try:
            await bot.wait_for('interaction', timeout=30)
        except:
            pass
        try:
            await confirm_msg.delete()
        except:
            pass
        return
    
    elif args.startswith('дни') or args.startswith('день'):
        parts = args.split()
        if len(parts) < 2:
            await ctx.send("❌ Пример: `!очистить дни 1`", delete_after=10)
            return
        
        try:
            days = int(parts[1])
        except ValueError:
            await ctx.send("❌ Укажите число дней!", delete_after=10)
            return
        
        if days < 1 or days > 30:
            await ctx.send("❌ Дней должно быть от 1 до 30", delete_after=10)
            return
        
        cutoff = datetime.utcnow() - timedelta(days=days)
        deleted = 0
        
        await ctx.send(f"🔄 Удаляю сообщения старше {days} дн...", delete_after=5)
        
        async for msg in ctx.channel.history(limit=None, before=datetime.utcnow()):
            if msg.created_at < cutoff:
                try:
                    await msg.delete()
                    deleted += 1
                    await asyncio.sleep(0.3)
                except discord.Forbidden:
                    pass
                except discord.HTTPException as e:
                    if e.status == 429:
                        retry_after = int(e.response.headers.get('Retry-After', 5))
                        await asyncio.sleep(retry_after + 1)
                        continue
                    break
        
        await ctx.send(f"✅ Удалено {deleted} сообщений за {days} дн.", delete_after=10)
        return
    
    else:
        try:
            amount = int(args)
        except ValueError:
            await ctx.send("❌ Пример: `!очистить 50`", delete_after=10)
            return
        
        if amount < 1:
            await ctx.send("❌ Укажите число больше 0", delete_after=10)
            return
        
        if amount > 100:  # Уменьшили с 1000 до 100 для защиты
            await ctx.send("❌ Максимум 100 сообщений за раз", delete_after=10)
            return
        
        deleted = 0
        async for msg in ctx.channel.history(limit=amount):
            try:
                await msg.delete()
                deleted += 1
                await asyncio.sleep(0.3)
            except discord.Forbidden:
                pass
            except discord.HTTPException as e:
                if e.status == 429:
                    retry_after = int(e.response.headers.get('Retry-After', 5))
                    await asyncio.sleep(retry_after + 1)
                    continue
                break
        
        await ctx.send(f"✅ Удалено {deleted} сообщений", delete_after=10)
        return

# ==================== КНОПКИ И МОДАЛКИ ТИКЕТОВ ====================

class CloseTicketModal(Modal):
    def __init__(self, channel):
        super().__init__(title="🔒 Закрытие тикета", timeout=600)
        self.channel = channel
        self.reason = TextInput(
            label="Причина (необязательно)",
            placeholder="Заявка одобрена / Вопрос решён",
            style=discord.TextStyle.short,
            required=False,
            max_length=200
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        reason = self.reason.value or "Не указана"
        
        embed = discord.Embed(
            title="⏳ Закрытие...",
            description=f"**Причина:** {reason}\n**Закрывает:** {interaction.user.mention}",
            color=discord.Color.orange()
        )
        await interaction.response.send_message(embed=embed)
        
        await asyncio.sleep(2)
        await log_ticket_messages(self.channel, interaction.user)
        await asyncio.sleep(2)
        
        try:
            await self.channel.delete(reason=f"Закрыто: {reason}")
        except Exception as e:
            print(f"❌ Ошибка удаления: {e}")

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        print(f"❌ Ошибка модалки: {error}")
        try:
            await interaction.response.send_message(f"❌ Ошибка: {error}", ephemeral=True)
        except:
            pass


class TicketCloseView(View):
    def __init__(self, channel):
        super().__init__(timeout=None)
        self.channel = channel

    @discord.ui.button(label="🔒 Закрыть тикет", style=discord.ButtonStyle.red, custom_id="ticket:close")
    async def close_button(self, interaction: discord.Interaction, button: Button):
        modal = CloseTicketModal(self.channel)
        await interaction.response.send_modal(modal)


class TicketModal(Modal):
    def __init__(self):
        super().__init__(title="🎫 Создание тикета", timeout=600)
        self.reason = TextInput(
            label="Причина обращения",
            placeholder="Опишите проблему...",
            style=discord.TextStyle.long,
            required=True,
            max_length=500
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        for channel in interaction.guild.text_channels:
            if channel.name == f"тикет-{interaction.user.name}" and hasattr(channel, 'category'):
                await interaction.response.send_message("❌ У вас уже есть тикет!", ephemeral=True)
                return

        category = discord.utils.get(interaction.guild.categories, name="🎫 ТИКЕТЫ")
        if not category:
            category = await interaction.guild.create_category(name="🎫 ТИКЕТЫ")

        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            interaction.guild.get_role(ADMIN_ROLE_ID): discord.PermissionOverwrite(read_messages=True, send_messages=True),
            interaction.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }

        channel = await interaction.guild.create_text_channel(
            name=f"тикет-{interaction.user.name}",
            category=category,
            overwrites=overwrites
        )

        embed = discord.Embed(
            title="🎫 Новый тикет",
            description=f"**Пользователь:** {interaction.user.mention}\n**ID:** `{interaction.user.id}`\n\n**Причина:**\n{self.reason.value}",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )

        view = TicketCloseView(channel)
        await channel.send(
            content=f"{interaction.user.mention} {interaction.guild.get_role(ADMIN_ROLE_ID).mention}",
            embed=embed,
            view=view
        )

        await interaction.response.send_message(f"✅ Тикет: {channel.mention}", ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        print(f"❌ Ошибка TicketModal: {error}")
        await interaction.response.send_message(f"❌ Ошибка: {error}", ephemeral=True)


class TicketCreateButton(Button):
    def __init__(self):
        super().__init__(label="📩 Создать тикет", style=discord.ButtonStyle.blurple, custom_id="ticket:create")

    async def callback(self, interaction: discord.Interaction):
        modal = TicketModal()
        await interaction.response.send_modal(modal)


# ==================== ПАНЕЛЬ ТИКЕТОВ ====================

async def create_ticket_panel():
    channel = bot.get_channel(TICKET_CHANNEL_ID)
    if not channel:
        print(f"❌ Канал {TICKET_CHANNEL_ID} не найден!")
        return

    await safe_panel_cleanup(channel)

    embed = discord.Embed(
        title="📩 ПОДДЕРЖКА",
        description="**Нажмите кнопку, чтобы создать тикет**\n\n"
                   "🔹 Опишите проблему подробно\n"
                   "🔹 Не создавайте дубликаты",
        color=discord.Color.green()
    )
    embed.set_footer(text="Ответ: обычно в течение 24 часов")

    view = View(timeout=None)
    view.add_item(TicketCreateButton())
    await channel.send(embed=embed, view=view)
    print("✅ Панель тикетов создана!")

# ==================== СОБЫТИЯ ====================

@bot.event
async def on_ready():
    print(f'✅ Бот {bot.user} запущен!')
    print(f'📂 Сервер: {GUILD_ID}')
    print(f'📝 Лог-канал: {LOG_CHANNEL_ID}')
    
    await asyncio.sleep(5)
    
    bot.add_view(VerifyView())  # ✅ Оставляем только это
    # TicketCloseView регистрируется при создании тикета
    
    await create_verify_panel()
    await asyncio.sleep(2)
    await create_ticket_panel()

@bot.event
async def on_member_join(member):
    if member.guild.id == GUILD_ID:
        role = member.guild.get_role(ROLE_ID)
        if role:
            await member.add_roles(role, reason="Новый участник")
            print(f"✅ Выдана роль верификации {member.name}")

# ==================== КОМАНДЫ ЗАЯВОК ====================

@bot.command()
@is_approver()
async def вопросы(ctx, member: discord.Member = None):
    embed = discord.Embed(
        title="📋 Анкета: Гид",
        description="Добрый день! Ответьте на вопросы:",
        color=discord.Color.orange()
    )
    questions = [
        "1️⃣ Ваш никнейм",
        "2️⃣ Ваш возраст?",
        "3️⃣ Сколько часов наиграно?",
        "4️⃣ Как часто планируете играть?",
        "5️⃣ Почему хотите в гиды?",
        "6️⃣ Часовой пояс? (пример: +3 от мск)",
        "7️⃣ Что знаете о сервере и механиках?"
    ]
    for q in questions:
        embed.add_field(name="\u200b", value=q, inline=False)
    embed.set_footer(text="Отвечайте по порядку")

    target = member or ctx.channel
    if isinstance(target, discord.Member):
        await target.send(embed=embed)
        await ctx.send(f"✅ Анкета отправлена {member.mention}", delete_after=5)
    else:
        await ctx.send(embed=embed)
    try:
        await ctx.message.delete()
    except:
        pass

@bot.command()
@is_approver()
async def п(ctx, member: discord.Member):
    guild = ctx.guild
    role = guild.get_role(GUIDE_ROLE_ID)
    
    if not role:
        await ctx.send("❌ Роль не найдена!")
        return
    if role.position >= ctx.me.top_role.position:
        await ctx.send("❌ Роль выше моей!")
        return
    
    try:
        await member.add_roles(role, reason="Заявка одобрена")
        embed = discord.Embed(
            title="✅ Одобрено!",
            description=f"{member.mention}, добро пожаловать в команду! 🎉",
            color=discord.Color.green()
        )
        embed.add_field(name="🎁 Далее:", value="• Правила для гидов\n• Вопросы старшим\n• Помощь игрокам!", inline=False)
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(f"❌ Ошибка: {e}")
   # ... (код команды !п заканчивается здесь) ...
    try:
        await ctx.message.delete()
    except:
        pass


# ==================== НОВАЯ КОМАНДА !план (ВСТАВЬ СЮДА) ====================

@bot.command()
@is_approver()
async def план(ctx):
    """!план - отправить сообщение с планом работ для гидов"""
    embed = discord.Embed(
        title="📘 ПЛАН РАБОТЫ ДЛЯ ГИДА",
        description="**Добрый день, уважаемый гид!**\n\n"
                   "Поздравляем с вступлением в нашу команду! 🎉\n"
                   "Ниже представлен подробный план твоей будущей работы на сервере. "
                   "Ознакомься с каждым пунктом внимательно — это поможет тебе качественно помогать игрокам!",
        color=discord.Color.green(),
        timestamp=datetime.utcnow()
    )
    
    embed.set_thumbnail(url=ctx.guild.icon.url if ctx.guild.icon else None)
    
    embed.add_field(name="🏦 1. Банковская система", value="• **Открытие счёта:** Как создать личный банковский счёт\n• **Пополнение и снятие:** Внесение и вывод средств\n• **Банкиры:** Кто они, чем занимаются, как работают\n• **Трудоустройство:** Как стать банкиром\n• **📍 Локация:** Показать здание банка", inline=False)
    
    embed.add_field(name="⚔️ 2. Гвардия сервера", value="• **Функции:** Основные задачи и обязанности гвардии\n• **Правила:** По каким правилам работают гвардейцы\n• **Где найти:** Локация гвардейского поста\n• **Вступление:** Как вступить в гвардию\n• **📍 Локация:** Показать здание гвардии", inline=False)
    
    embed.add_field(name="🎯 3. Наша организация", value="• **О сервере:** Краткая информация о проекте\n• **Сообщество:** Чем мы живём и дышим\n• **⚠️ Необязательно:** Рассказывать по желанию", inline=False)
    
    embed.add_field(name="👑 4. Президент сервера", value="• **Обязанности:** Чем занимается президент\n• **Полномочия:** Какие права имеет\n• **Новости:** Где следить за обновлениями от президента\n• **📢 Канал:** Указать канал с новостями", inline=False)
    
    embed.add_field(name="⚖️ 5. Судебная система", value="• **Заявления:** Как подать исковое заявление\n• **Заседания:** Как проходят судебные процессы\n• **Где проходит:** Место проведения судов\n• **📍 Локация:** Показать здание суда", inline=False)
    
    embed.add_field(name=" 6. Министры измерений", value="• **Министр Спавна:** Обязанности и требования\n• **Министр Ада:** Обязанности и требования\n• **Министр Энда:** Обязанности и требования\n• **Как попасть:** Условия получения должности", inline=False)
    
    embed.add_field(name="🛒 7. Торговый центр", value="• **Расположение:** Где находится ТЦ\n• **Аренда лавки:** Как взять торговое место\n• **Продажа:** Как начать продавать ресурсы\n• **📍 Локация:** Показать торговый центр", inline=False)
    
    embed.add_field(name="⚙️ 8. Механики сервера", value="• **Кастомные крафты:** Уникальные рецепты\n• **Подписка Plus:** Преимущества и возможности\n• **Другие механики:** Кратко о главном с Вики\n• **📚 Вики:** Ссылка на вики-проект", inline=False)
    
    embed.add_field(name="🌾 9. Мир Ферм", value="• **Проход:** Где находится вход\n• **Назначение:** Для чего предназначен мир\n• **⚠️ Важно:** Фермы в Мире Построек **ЗАПРЕЩЕНЫ**\n• **📍 Локация:** Показать проход", inline=False)
    
    embed.add_field(name="📜 10. Основные правила", value="• **Нарушения:** За что чаще всего выдают наказания\n• **Гриферство:** Правила строительства\n• **Чат:** Правила общения\n• **📖 Документ:** Ссылка на полные правила", inline=False)
    
    embed.add_field(name="🏰 11. Города сервера", value="• **Существующие:** Список активных городов\n• **Главы:** Кто управляет городами\n• **Информация:** Актуальные данные от глав\n• **📍 Локации:** Показать города на карте", inline=False)
    
    embed.add_field(name="🎁 12. Кастомные предметы", value="• **Выставка:** Предметы в здании гидов\n• **Назначение:** Для чего нужны эти предметы\n• **Как получить:** Способы приобретения\n• **📍 Локация:** Показать здание гидов", inline=False)
    
    embed.set_footer(text="💡 Вопросы? Создай тикет или обратись к старшему гиду • Приятной работы!")
    
    # Кнопки с ссылкой на Вики
    view = View(timeout=None)
    view.add_item(Button(label="📩 Создать тикет", style=discord.ButtonStyle.blurple, custom_id="ticket:create"))
    view.add_item(Button(label="📚 Вики сервера", style=discord.ButtonStyle.link, url="https://necovanilla.gitbook.io/nekovanila-viki"))
    
    await ctx.send(embed=embed, view=view)
    
    try:
        await ctx.message.delete()
    except:
        pass

@bot.command()
@commands.has_permissions(administrator=True)
async def лог(ctx):
    if not ctx.channel.name.startswith('тикет-'):
        await ctx.send("❌ Только в тикетах!")
        return
    await ctx.send("📝 Сохраняю...")
    log_msg = await log_ticket_messages(ctx.channel, ctx.author)
    if log_msg:
        await ctx.send(f"✅ Лог: {log_msg.jump_url}")
    else:
        await ctx.send("❌ Не удалось сохранить")

@bot.command()
@commands.has_permissions(administrator=True)
async def панель(ctx):
    await ctx.send("🔄 Обновляю...", delete_after=5)
    await create_ticket_panel()

@bot.command()
@commands.has_permissions(administrator=True)
async def верификация(ctx):
    await ctx.send("🔄 Обновляю...", delete_after=5)
    await create_verify_panel()

# ==================== КОМАНДЫ УПРАВЛЕНИЯ КНОПКАМИ ====================

@bot.command()
@is_approver()
async def кнопка(ctx):
    if not ctx.channel.name.startswith('тикет-'):
        await ctx.send("❌ Только в тикетах!", delete_after=5)
        return
    
    deleted = await safe_delete_messages(ctx.channel, limit=5, delay=1)
    print(f"🗑️ Удалено {deleted} старых кнопок")
    
    embed = discord.Embed(
        title="🔒 Управление тикетом",
        description="Нажмите кнопку, чтобы закрыть тикет",
        color=discord.Color.blue()
    )
    embed.set_footer(text="Лог будет сохранён")
    
    view = TicketCloseView(ctx.channel)
    await ctx.channel.send(embed=embed, view=view)
    await ctx.send("✅ Кнопка создана!", delete_after=5)


@bot.command()
@is_approver()
async def обновить_кнопки(ctx):
    await ctx.send("🔄 Обновляю...", delete_after=5)
    await create_ticket_panel()


@bot.command()
@is_approver()
async def закрыть(ctx, *, reason: str = "Не указана"):
    if not ctx.channel.name.startswith('тикет-'):
        await ctx.send("❌ Только в тикетах!", delete_after=5)
        return
    
    embed = discord.Embed(
        title="⏳ Закрытие...",
        description=f"**Причина:** {reason}\n**Закрывает:** {ctx.author.mention}",
        color=discord.Color.orange()
    )
    msg = await ctx.send(embed=embed)
    
    await asyncio.sleep(2)
    await log_ticket_messages(ctx.channel, ctx.author)
    await asyncio.sleep(2)
    
    try:
        await ctx.channel.delete(reason=f"Закрыто: {reason}")
    except Exception as e:
        await msg.edit(content=f"❌ Ошибка: {e}", embed=None)

# ==================== ЗАПУСК ====================

bot.run(TOKEN)