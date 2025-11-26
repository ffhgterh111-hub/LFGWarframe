import discord
from discord.ext import commands
import json
from typing import Dict, Any, Optional
import os # <-- Необходим для чтения переменных окружения (BOT_TOKEN, EXTERNAL_URL, PORT)
import asyncio # <-- Необходим для асинхронного запуска бота и веб-сервера
from aiohttp import web, ClientSession # <-- Необходим для веб-сервера и самопинга

# =================================================================
# 1. КОНСТАНТЫ И НАСТРОЙКИ
# =================================================================

# ВАЖНОЕ ИЗМЕНЕНИЕ: Токен считывается из переменной окружения 'BOT_TOKEN' на Render.
BOT_TOKEN = os.environ.get('BOT_TOKEN') 
if not BOT_TOKEN:
    print("❌ ВНИМАНИЕ: Переменная окружения 'BOT_TOKEN' не найдена. Бот не сможет запуститься.")

CONFIG_FILE = 'config.json'
LFG_TIMEOUT = 3600 # 1 час (в секундах)

# --- ИЗОБРАЖЕНИЯ ДЛЯ СТИЛИЗАЦИИ ---
NAV_IMAGE_URL = 'https://avatars.mds.yandex.net/i?id=bfb7df6ab9ff7534c87f3996ad64e2cb_l-5869570-images-thumbs&n=13' 
CASCAD_IMAGE_URL = 'https://static.wikia.nocookie.net/warframe/images/6/64/%D0%A2%D1%80%D0%B0%D0%BA%D1%81%D0%BE%D0%B2%D0%B0%D1%8F_%D0%9F%D0%BB%D0%B0%D0%B7%D0%BC%D0%B0_%D0%B2%D0%B8%D0%BA%D0%B8.png/revision/latest?cb=20220428000041&path-prefix=ru'

# --- АРБИТРАЖ: СТИЛИЗАЦИЯ (ЦВЕТА И ИКОНКИ РАС) ---
FACTION_ICONS = {
    "Гринир": "https://images-ext-1.discordapp.net/external/Wmh0isPGDXG8s1_xJKjSW_F6CHl6aBQXoRIINUdvm0g/https/assets.empx.cc/Lotus/Interface/Graphics/WorldStatePanel/Grineer.png?format=webp&quality=lossless",
    "Корпус": "https://images-ext-1.discordapp.net/external/BUNqoLvclDjqa3OUzE04XI4E1nXvU8qR9f_IIb5AP7o/https/assets.empx.cc/Lotus/Interface/Graphics/WorldStatePanel/Corpus.png?format=webp&quality=lossless",
    "Зараженные": "https://images-ext-1.discordapp.net/external/9_z1utcRwJxSSw4n6ebRLAzqynWnAJAVJDphsjyrg9E/https/assets.empx.cc/Lotus/Interface/Graphics/WorldStatePanel/Infested.png?format=webp&quality=lossless"
}

TIER_COLORS = {
    "S-ТИР": discord.Color.red(), 
    "A-ТИР": discord.Color.gold(), 
    "B-ТИР": discord.Color.blue() 
}

# --- ДАННЫЕ КАРТ (обновлено для включения Расы и Тайлсета) ---
MAP_TIERS_DATA = {
    "S-ТИР": [
        {"name": "Casta", "faction": "Гринир", "mission": "Оборона", "tileset": "Grineer Asteroid"},
        {"name": "Cinxia", "faction": "Гринир", "mission": "Перехват", "tileset": "Grineer Galleon"},
        {"name": "Seimeni", "faction": "Зараженные", "mission": "Оборона", "tileset": "Infested Ship"},
    ],
    "A-ТИР": [
        {"name": "Hydron", "faction": "Гринир", "mission": "Оборона", "tileset": "Grineer Galleon"},
        {"name": "Helenе", "faction": "Гринир", "mission": "Оборона", "tileset": "Grineer Asteroid"},
        {"name": "Sechura", "faction": "Зараженные", "mission": "Оборона", "tileset": "Infested Ship"},
        {"name": "Odin", "faction": "Гринир", "mission": "Перехват", "tileset": "Grineer Shipyard"},
    ],
    "B-ТИР": [
        {"name": "Hyf", "faction": "Зараженные", "mission": "Оборона", "tileset": "Infested Ship"},
        {"name": "Ose", "faction": "Корпус", "mission": "Перехват", "tileset": "Corpus Ice Planet"},
        {"name": "Outer Terminus", "faction": "Корпус", "mission": "Оборона", "tileset": "Corpus Gas City"}
    ]
}

# Слоты для Арбитража
ARBITRAGE_SLOTS = [
    "Сарина (Пребаф)",
    "Сарина (DPS)",
    "Вольт / Хрома",
    "Висп"
]

# Слоты для Каскада
CASCAD_SLOTS = ["Слот 1", "Слот 2", "Слот 3", "Слот 4"]


# =================================================================
# 2. ФУНКЦИИ УПРАВЛЕНИЯ КОНФИГУРАЦИЕЙ
# =================================================================

def save_config(config_data):
    """Сохраняет настройки в файл JSON."""
    with open('config.json', 'w') as f:
        json.dump(config_data, f, indent=4)

def load_config() -> Dict[str, Any]:
    """
    Загружает настройки из файла JSON и гарантирует наличие всех необходимых ключей.
    """
    DEFAULT_CONFIG = {
        "NAV_CHANNEL_ID": None,
        "LFG_CHANNEL_ID": None,
        "ARBITRAGE_ROLE_ID": None,
        "CASCAD_ROLE_ID": None, 
        "MAP_ROLES": {} 
    }
    
    config = DEFAULT_CONFIG.copy()
    
    try:
        with open('config.json', 'r') as f:
            loaded_config = json.load(f)
            config.update(loaded_config)
    except FileNotFoundError:
        pass
    except json.JSONDecodeError:
        pass
        
    save_config(config)
    
    return config

CONFIG = load_config()

# =================================================================
# 3. ИНИЦИАЛИЗАЦИЯ БОТА И НАМЕРЕНИЯ (INTENTS)
# =================================================================

intents = discord.Intents.default()
intents.members = True 
intents.message_content = True 

bot = commands.Bot(command_prefix='!', intents=intents)

# Словарь для отслеживания активных тикетов: {user_id: message_id}
ACTIVE_TICKETS = {}

# =================================================================
# 4. КЛАССЫ ИНТЕРАКТИВНЫХ КОМПОНЕНТОВ (VIEWS)
# =================================================================

async def check_and_delete_old_ticket(initiator: discord.Member, lfg_channel):
    """Проверяет и удаляет старый тикет инициатора."""
    old_message_id = ACTIVE_TICKETS.get(initiator.id)
    if old_message_id:
        try:
            old_message = await lfg_channel.fetch_message(old_message_id)
            await old_message.delete()
        except discord.NotFound:
            pass 
        except Exception as e:
            print(f"Не удалось удалить старый тикет {old_message_id}: {e}")
        finally:
            if initiator.id in ACTIVE_TICKETS:
                del ACTIVE_TICKETS[initiator.id]


class PartyView(discord.ui.View):
    """Универсальный View для управления созданным тикетом (Арбитраж/Каскад)."""
    
    def __init__(self, bot, map_info: str, initial_slots: Dict[str, Any], initiator: discord.Member, slot_names: list, message_id: int, comment: Optional[str] = None):
        super().__init__(timeout=LFG_TIMEOUT) 
        self.bot = bot
        self.map_info = map_info 
        self.slots = initial_slots
        self.initiator = initiator
        self.slot_names = slot_names
        self.message_id = message_id 
        self.comment = comment 
        self._add_role_buttons() 

    # --- ЛОГИКА АВТОМАТИЧЕСКОГО УДАЛЕНИЯ ---
    async def on_timeout(self):
        channel_id = CONFIG.get('LFG_CHANNEL_ID')
        channel = self.bot.get_channel(channel_id)
        if channel:
            try:
                message = await channel.fetch_message(self.message_id)
                await message.delete()
                if self.initiator.id in ACTIVE_TICKETS and ACTIVE_TICKETS[self.initiator.id] == self.message_id:
                    del ACTIVE_TICKETS[self.initiator.id]
            except discord.NotFound:
                pass 

    def _create_summary_embed(self) -> discord.Embed:
        """Создает финальный Embed с информацией о собранной пати."""
        members_list = []
        for role, player in self.slots.items():
            if isinstance(player, discord.Member):
                member_display = player.mention
            else:
                member_display = self.initiator.mention

            members_list.append(f"**{role}:** {member_display}")
            
        try:
            map_data = json.loads(self.map_info)
            title = "🚀 Пати на Арбитраж Собрана!"
            description = (
                f"**Карта:** {map_data['name']} ({map_data['tier']})\n"
                f"**Миссия:** {map_data['mission']} - {map_data['faction']}\n"
                f"**Тайлсет:** {map_data['tileset']}"
            )
            color = TIER_COLORS.get(map_data["tier"], discord.Color.green())
        except json.JSONDecodeError:
            title = "🚀 Пати на Каскад Собрана!"
            description = (
                "**Миссия:** Каскад (Бездна) \n"
                "**Награда:** Мистификаторы (Праймхлам/Отголоски)"
            )
            color = discord.Color.dark_green()
        
        embed = discord.Embed(
            title=title,
            description=description,
            color=color
        )
        
        embed.add_field(
            name="⚔️ Состав группы:",
            value="\n".join(members_list),
            inline=False
        )
        
        if self.comment:
            embed.add_field(
                name="📝 Комментарий создателя:",
                value=f"> *{self.comment}*",
                inline=False
            )

        embed.set_footer(text=f"Пати успешно закрыта. Создатель: {self.initiator.display_name}")
        return embed


    def _update_embed(self, embed: discord.Embed) -> discord.Embed:
        """Обновляет Embed на основе текущего состояния слотов, данных карты и комментария."""
        
        embed.clear_fields() 
            
        is_full = all(self.slots[role] != "[СВОБОДНО]" for role in self.slot_names)
        
        try:
            map_data = json.loads(self.map_info)
            
            final_color = TIER_COLORS.get(map_data["tier"], discord.Color.gold())
            embed.color = final_color
            
            faction_icon_url = FACTION_ICONS.get(map_data["faction"])
            if faction_icon_url:
                embed.set_thumbnail(url=faction_icon_url)

            map_info_text = f"{map_data['tier']} | {map_data['name']} ({map_data['mission']})"
            if is_full:
                 final_title = f"✅ ЗАКРЫТО | {map_info_text} | Пати собрана!"
            else:
                 final_title = f"⚠️ СБОР | {map_info_text} | Нужны игроки"

            embed.add_field(name="Тип", value=f"{map_data['mission']} - {map_data['faction']}", inline=True)
            embed.add_field(name="Сет/Тайлы", value=map_data['tileset'], inline=True)
            embed.add_field(name="Истекает", value="1 час с момента создания", inline=True) 
            
            field_icon = "⚙️" 
            
        except json.JSONDecodeError:
            if self.map_info == "Каскад":
                final_color = discord.Color.blue()
                embed.color = final_color
                
                if CASCAD_IMAGE_URL:
                    embed.set_thumbnail(url=CASCAD_IMAGE_URL)
                
                field_icon = "✨" 
                
                if is_full:
                    final_title = f"✅ ЗАКРЫТО | {self.map_info} | Пати собрана!"
                else:
                    final_title = f"⚠️ СБОР | {self.map_info} | Нужны игроки"
                
                embed.add_field(name="Награда", value="Мистификаторы (Праймхлам/Отголоски)", inline=True)
                embed.add_field(name="Тип", value="Каскад (Бездна)", inline=True)
                embed.add_field(name="Истекает", value="1 час с момента создания", inline=True)

            else: 
                final_title = f"⚠️ СБОР | {self.map_info} | Нужны игроки"
                final_color = discord.Color.gold()
                field_icon = "⚙️"
            

        # Добавляем Комментарий, если он есть
        if self.comment:
            embed.add_field(
                name="📝 Комментарий создателя:", 
                value=f"> *{self.comment}*", 
                inline=False
            )


        # Заполняем поля ролями
        for role, player in self.slots.items():
            if player == "[СВОБОДНО]":
                value = "**[СВОБОДНО]**"
            elif isinstance(player, discord.Member):
                value = player.mention
            else:
                # Универсальная обработка, чтобы избежать ошибок, если тип не Member
                value = str(player)
            
            embed.add_field(name=f"{field_icon} {role}", value=value, inline=False)
        
        embed.title = final_title
        embed.color = final_color

        embed.set_footer(text=f"Создатель: {self.initiator.display_name} | Удаление через 1 час после создания.")
        return embed
    
    
    def _add_role_buttons(self):
        """Создает и добавляет кнопки 'Бронь', а также восстанавливает кнопки 'Закрыть' и 'Покинуть'."""
        self.clear_items()
        
        # 1. Кнопки бронирования (Join Buttons)
        for role_name in self.slot_names:
            if self.slots[role_name] == "[СВОБОДНО]":
                label_text = role_name.split('(')[0].strip()
                if "Слот" not in label_text:
                    label_text = f"Бронь: {label_text}"

                button = discord.ui.Button(
                    label=label_text,
                    style=discord.ButtonStyle.secondary,
                    custom_id=f"join_{role_name}",
                    row=0
                )
                button.callback = self._create_join_callback(role_name)
                self.add_item(button)
                
        # 2. ВОССТАНОВЛЕНИЕ КНОПОК УПРАВЛЕНИЯ
        self.add_item(self.close_party_callback)
        self.add_item(self.leave_party_callback)


    def _create_join_callback(self, role_name: str):
        """Генерирует callback для кнопки 'Бронь'."""
        async def join_callback(interaction: discord.Interaction):
            
            await interaction.response.defer() 
            
            user = interaction.user
            current_slot = None
            message = ""
            
            for slot_key, player in self.slots.items():
                if isinstance(player, discord.Member) and player.id == user.id:
                    current_slot = slot_key
                    break
            
            if current_slot:
                if current_slot == role_name:
                    return await interaction.followup.send(
                        f"Вы уже занимаете слот **{role_name}**.", 
                        ephemeral=True
                    )
                
                if self.slots[role_name] != "[СВОБОДНО]":
                    return await interaction.followup.send(
                        "Этот слот только что заняли!", 
                        ephemeral=True
                    )
                
                # Перемещение
                self.slots[current_slot] = "[СВОБОДНО]" 
                message = f"Вы покинули слот **{current_slot}** и заняли **{role_name}**."
            else:
                # Занятие нового слота
                if self.slots[role_name] != "[СВОБОДНО]":
                    return await interaction.followup.send(
                        "Этот слот только что заняли!", 
                        ephemeral=True
                    )
                message = f"Вы заняли слот **{role_name}**."

            self.slots[role_name] = user 
            
            # --- ЛОГИКА: ПРОВЕРКА НА ПОЛНЫЙ СБОР И ЗАКРЫТИЕ ТИКЕТА ---
            is_full = all(self.slots[role] != "[СВОБОДНО]" for role in self.slot_names)
            
            if is_full:
                self.stop()
                summary_embed = self._create_summary_embed()
                lfg_channel = interaction.channel
                mentions = [p.mention for p in self.slots.values() if isinstance(p, discord.Member)]
                final_content = f"✅ **ПАТИ СОБРАНА!** {', '.join(mentions)} — ВПЕРЕД НА МИССИЮ!"
                
                await lfg_channel.send(final_content, embed=summary_embed)
                
                await interaction.message.delete()
                
                await interaction.followup.send(
                    f"🎉 **Пати полностью собрана!** Тикет закрыт. Проверьте канал {lfg_channel.mention} для деталей.",
                    ephemeral=True
                )
                
                if self.initiator.id in ACTIVE_TICKETS and ACTIVE_TICKETS[self.initiator.id] == interaction.message.id:
                    del ACTIVE_TICKETS[self.initiator.id]
                
                return 

            # --- КОНЕЦ ЛОГИКИ ---
            
            self._add_role_buttons()
            embed = self._update_embed(interaction.message.embeds[0])
            
            await interaction.edit_original_response(embed=embed, view=self)
            
            await interaction.followup.send(message, ephemeral=True)
            
        return join_callback
        
    @discord.ui.button(label="Закрыть пати ❌", style=discord.ButtonStyle.danger, custom_id="close_party", row=1)
    async def close_party_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Удаляет тикет (Embed) из канала LFG и из ACTIVE_TICKETS. Доступно только создателю."""
        if interaction.user.id != self.initiator.id:
            return await interaction.response.send_message(
                "Только создатель пати может её закрыть.", 
                ephemeral=True
            )
            
        await interaction.response.send_message("Тикет успешно закрыт.", ephemeral=True)
        
        try:
            await interaction.message.delete()
        except discord.NotFound:
            pass
        
        if self.initiator.id in ACTIVE_TICKETS and ACTIVE_TICKETS[self.initiator.id] == interaction.message.id:
            del ACTIVE_TICKETS[self.initiator.id]


    @discord.ui.button(label="Покинуть слот 🏃", style=discord.ButtonStyle.blurple, custom_id="leave_party", row=1)
    async def leave_party_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Позволяет игроку покинуть занятый слот."""
        
        await interaction.response.defer()
        
        user_id = interaction.user.id
        slot_to_leave = None
        
        for role_name in self.slot_names:
            player = self.slots.get(role_name)
            if (isinstance(player, discord.Member) and player.id == user_id):
                slot_to_leave = role_name
                break
        
        if not slot_to_leave:
            return await interaction.followup.send(
                "Вы не занимаете ни одного слота в этой пати.", 
                ephemeral=True
            )

        if interaction.user.id == self.initiator.id and len([p for p in self.slots.values() if p != '[СВОБОДНО]']) == 1:
             return await interaction.followup.send("Как создатель тикета, вы не можете покинуть слот, пока это единственный занятый слот. Вы можете только закрыть тикет.", ephemeral=True)

        self.slots[slot_to_leave] = "[СВОБОДНО]"
        
        self._add_role_buttons()
        embed = self._update_embed(interaction.message.embeds[0])
        
        await interaction.edit_original_response(embed=embed, view=self)
        
        await interaction.followup.send(
            f"Вы успешно покинули слот **{slot_to_leave}**.", 
            ephemeral=True
        )


# =================================================================
# АРБИТРАЖ, КАСКАД, МОДАЛЬНЫЕ ОКНА И VIEW-КОНТЕЙНЕРЫ 
# =================================================================

class RoleSelect(discord.ui.Select):
    """Dropdown для выбора первой роли инициатора (Арбитраж)."""
    def __init__(self, bot, map_id_string: str, initiator: discord.Member):
        self.bot = bot
        self.map_id_string = map_id_string 
        self.initiator = initiator
        
        options = [
            discord.SelectOption(label=role, value=role)
            for role in ARBITRAGE_SLOTS
        ]
        
        super().__init__(placeholder="Займите свой первый слот...", options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        selected_role = self.values[0]
        view = self.view 

        try:
            tier, map_name = self.map_id_string.split('|')
        except ValueError:
            return await interaction.response.send_message("❌ Ошибка формата данных карты.", ephemeral=True)
            
        map_data_object = next(
            (item for item in MAP_TIERS_DATA.get(tier, []) if item['name'] == map_name),
            None 
        )

        if not map_data_object:
            return await interaction.response.send_message("❌ Не удалось найти данные карты.", ephemeral=True)

        map_data_object["tier"] = tier
        map_data_string = json.dumps(map_data_object) 
        
        lfg_channel_id = CONFIG.get('LFG_CHANNEL_ID')
        if not lfg_channel_id:
            return await interaction.response.send_message("❌ Канал поиска пати не настроен! Используйте `!set_lfg`.", ephemeral=True)
            
        lfg_channel = self.bot.get_channel(lfg_channel_id)
        
        await check_and_delete_old_ticket(self.initiator, lfg_channel)
        
        initial_slots = {role: "[СВОБОДНО]" for role in ARBITRAGE_SLOTS}
        initial_slots[selected_role] = self.initiator 
        
        map_info_text = f"{map_data_object['tier']} | {map_data_object['name']} ({map_data_object['mission']})"
        
        initial_embed = discord.Embed(
            title=f"⏳ Загрузка тикета: {map_info_text}", 
            color=TIER_COLORS.get(map_data_object['tier'], discord.Color.gold())
        )
        
        role_id = CONFIG.get('ARBITRAGE_ROLE_ID')
        role_mention = f"<@&{role_id}>" if role_id else ""
        
        # Пингуем роль Арбитража и упомянаем создателя
        sent_message = await lfg_channel.send(
            f"{role_mention} | Пати на Арбитраж ищет игроков! Создатель: {self.initiator.mention} | Карта: **{map_info_text}**", 
            embed=initial_embed
        )
        
        ACTIVE_TICKETS[self.initiator.id] = sent_message.id
        
        lfg_view = PartyView(
            self.bot, 
            map_data_string, 
            initial_slots, 
            self.initiator, 
            ARBITRAGE_SLOTS, 
            sent_message.id,
            comment=getattr(view, 'comment_text', None) 
        )
        initial_embed = lfg_view._update_embed(initial_embed) 
        
        await sent_message.edit(embed=initial_embed, view=lfg_view)

        await interaction.response.edit_message(
            content=f"🎉 **Тикет создан!** Вы заняли слот **{selected_role}**. Комментарий: {getattr(view, 'comment_text', 'Нет') or 'Нет'}. Проверьте канал {lfg_channel.mention} и ждите других игроков.",
            view=None
        )


class TierSelect(discord.ui.Select):
    """Dropdown для выбора конкретной карты внутри выбранного Тира (Шаг 2)."""
    
    def __init__(self, bot, map_tier: str, initiator: discord.Member):
        self.bot = bot
        self.map_tier = map_tier
        self.initiator = initiator
        
        map_options = MAP_TIERS_DATA.get(map_tier, [])
        
        options = []
        for item in map_options:
            label = f"{item['name']} {item['faction']} ({item['mission']})"
            value = f"{map_tier}|{item['name']}" 
            options.append(discord.SelectOption(label=label, value=value))
        
        super().__init__(placeholder=f"Выберите карту в {map_tier}...", options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        map_id_string = self.values[0] # e.g., "S-ТИР|Casta"
        _, map_name = map_id_string.split('|')
        
        await interaction.response.edit_message(
            content=f"✅ Вы выбрали карту **{map_name}**.\n\n⏳ **Шаг 3: Займите свой стартовый слот (и добавьте коммент):**",
            view=RoleSelectView(self.bot, map_id_string, self.initiator) 
        )

class MapSelect(discord.ui.Select):
    """Dropdown для выбора Тира карты (Шаг 1)."""
    def __init__(self, bot, initiator: discord.Member):
        self.bot = bot
        self.initiator = initiator
        options = [
            discord.SelectOption(label="S-Тир (Лучшие)", value="S-ТИР", emoji="🔥"),
            discord.SelectOption(label="A-Тир (Средние)", value="A-ТИР", emoji="⭐"),
            discord.SelectOption(label="B-Тир (Базовые)", value="B-ТИР", emoji="🔰")
        ]
        super().__init__(placeholder="Выберите Тир карты...", options=options)

    async def callback(self, interaction: discord.Interaction):
        selected_tier = self.values[0]
        
        await interaction.response.edit_message(
            content=f"✅ Вы выбрали **{selected_tier}**.\n\n⏳ **Шаг 2: Выберите название карты:**",
            view=TierSelectView(self.bot, selected_tier, self.initiator) 
        )

# =================================================================
# КАСКАД: КЛАССЫ ВЫБОРА РОЛЕЙ
# =================================================================

class CascadeStartView(discord.ui.View):
    """Упрощенный View для создания пати на Каскад. Автоматически занимает Слот 1."""
    def __init__(self, bot, initiator: discord.Member):
        super().__init__(timeout=600)
        self.bot = bot
        self.comment_text = None 
        self.initiator = initiator # Сохраняем инициатора для кнопки запуска

    @discord.ui.button(label="Создать пати (Занять Слот 1) 🚀", style=discord.ButtonStyle.success, row=0, custom_id="cascade_start_btn")
    async def start_party_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Логика создания тикета: автоматически занимает Слот 1."""
        
        selected_role = "Слот 1" # Автоматически занимаем первый слот
        initiator = self.initiator
        map_info = "Каскад" 
        
        lfg_channel_id = CONFIG.get('LFG_CHANNEL_ID')
        if not lfg_channel_id:
            return await interaction.response.send_message("❌ Канал поиска пати не настроен. Используйте `!set_lfg`.", ephemeral=True)
            
        lfg_channel = self.bot.get_channel(lfg_channel_id)
        
        await check_and_delete_old_ticket(initiator, lfg_channel)

        initial_slots = {role: "[СВОБОДНО]" for role in CASCAD_SLOTS}
        initial_slots[selected_role] = initiator 
        
        initial_embed = discord.Embed(
            title=f"⏳ Загрузка тикета: {map_info}", 
            color=discord.Color.blue() 
        )
        
        role_id = CONFIG.get('CASCAD_ROLE_ID')
        role_mention = f"<@&{role_id}>" if role_id else ""
        
        ping_text = f"{role_mention} | Пати на **Каскад** ищет игроков! Создатель: {initiator.mention}"
        
        # Отправляем ephemeral ответ, чтобы сообщить о создании
        await interaction.response.send_message(
            f"🎉 **Тикет создан!** Вы заняли слот **{selected_role}** (Комм.: {self.comment_text if self.comment_text else 'Нет'}). Проверьте канал {lfg_channel.mention} и ждите других игроков.", 
            ephemeral=True
        )
        
        # Отправляем сообщение в LFG канал
        sent_message = await lfg_channel.send(
            ping_text, 
            embed=initial_embed
        )

        ACTIVE_TICKETS[initiator.id] = sent_message.id
        
        lfg_view = PartyView(
            self.bot, 
            map_info, 
            initial_slots, 
            initiator, 
            CASCAD_SLOTS, 
            sent_message.id,
            comment=self.comment_text 
        )
        initial_embed = lfg_view._update_embed(initial_embed) 
        await sent_message.edit(embed=initial_embed, view=lfg_view)

    @discord.ui.button(label="Добавить коммент 📝", style=discord.ButtonStyle.secondary, row=1)
    async def add_comment_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = CommentModal(view=self)
        await interaction.response.send_modal(modal)

# =================================================================
# МОДАЛЬНЫЕ ОКНА
# =================================================================

class CommentModal(discord.ui.Modal, title='Добавить комментарий к тикету'):
    """Модальное окно для ввода комментария."""
    
    comment_input = discord.ui.TextInput(
        label='Ваш комментарий (до 100 символов)',
        style=discord.TextStyle.short,
        placeholder='Например: +Каскад, Нужен хил, 4x60 и т.д.',
        required=False,
        max_length=100,
    )

    def __init__(self, view: discord.ui.View):
        super().__init__()
        self.view = view 

    async def on_submit(self, interaction: discord.Interaction):
        self.view.comment_text = self.comment_input.value
        
        comment_display = f"✅ **Комментарий добавлен:** *{self.comment_input.value}*" if self.comment_input.value else "Комментарий удален."

        # Разделяем контент по двойному переводу строки, чтобы не дублировать старый коммент
        current_content = interaction.message.content.split('\n\n')[0]
        
        await interaction.response.edit_message(
            content=f"{current_content}\n\n{comment_display}",
            view=self.view
        )

# =================================================================
# VIEW-КОНТЕЙНЕРЫ (С НОВЫМ ПОЛЕМ comment_text)
# =================================================================

class TierSelectView(discord.ui.View):
    """View-контейнер для TierSelect."""
    def __init__(self, bot, map_tier: str, initiator: discord.Member):
        super().__init__(timeout=600) 
        self.bot = bot
        self.add_item(TierSelect(bot, map_tier, initiator))

class RoleSelectView(discord.ui.View):
    """View-контейнер для RoleSelect."""
    def __init__(self, bot, map_id_string: str, initiator: discord.Member):
        super().__init__(timeout=600)
        self.bot = bot
        self.map_id_string = map_id_string
        self.initiator = initiator
        self.comment_text = None 

        self.add_item(RoleSelect(bot, map_id_string, initiator))

    @discord.ui.button(label="Добавить коммент 📝", style=discord.ButtonStyle.secondary, row=1)
    async def add_comment_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = CommentModal(view=self)
        await interaction.response.send_modal(modal)


class MapSelectView(discord.ui.View):
    """View-контейнер для MapSelect."""
    def __init__(self, bot, initiator: discord.Member):
        super().__init__(timeout=600)
        self.bot = bot
        self.add_item(MapSelect(bot, initiator))


class MainNavigationView(discord.ui.View):
    """Главный View для канала навигации, содержит кнопки выбора миссий."""
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Найти пати: АРБИТРАЖ", style=discord.ButtonStyle.green, custom_id="arbitrage_start", row=0)
    async def arbitrage_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        
        if not CONFIG.get('LFG_CHANNEL_ID'):
            return await interaction.response.send_message("❌ Канал поиска пати не настроен. Попросите администратора использовать `!set_lfg`.", ephemeral=True)
            
        await interaction.response.send_message(
            "⏳ **Шаг 1: Выберите Тир текущей карты Арбитража:**",
            view=MapSelectView(self.bot, interaction.user),
            ephemeral=True
        )

    @discord.ui.button(label="Найти пати: КАСКАД", style=discord.ButtonStyle.blurple, custom_id="cascade_start", row=0)
    async def cascade_button(self, interaction: discord.Interaction, button: discord.ui.Button): 
        
        if not CONFIG.get('LFG_CHANNEL_ID'):
            return await interaction.response.send_message("❌ Канал поиска пати не настроен. Попросите администратора использовать `!set_lfg`.", ephemeral=True)
            
        await interaction.response.send_message(
            "⏳ **Настройка пати на Каскад.** Вы автоматически займете **Слот 1**.\n\nНажмите **'Создать пати'** или сначала добавьте комментарий:",
            view=CascadeStartView(self.bot, interaction.user),
            ephemeral=True
        )

# =================================================================
# 5. АДМИНИСТРАТИВНЫЕ КОМАНДЫ ДЛЯ НАСТРОЙКИ
# =================================================================

requires_admin = commands.has_permissions(manage_guild=True)

@bot.command(name='set_nav')
@requires_admin
async def set_nav_channel(ctx, channel: discord.TextChannel):
    """
    [ИСПРАВЛЕНО] Устанавливает канал навигации и отправляет стартовое сообщение 
    только по команде, а не при каждом запуске.
    """
    global CONFIG
    
    # 1. Проверяем и удаляем старое сообщение (если оно было в этом канале)
    async for message in channel.history(limit=5):
        if message.author.id == ctx.bot.user.id and message.embeds:
            embed_title = message.embeds[0].title
            if embed_title and "СИСТЕМА ПОДБОРА ПАТИ WARFRAME" in embed_title:
                try:
                    await message.delete()
                    await ctx.send(f"⚠️ Старое сообщение навигации в канале {channel.mention} удалено.")
                except Exception:
                    pass

    # 2. Сохраняем ID канала в конфигурацию
    CONFIG['NAV_CHANNEL_ID'] = channel.id
    save_config(CONFIG)

    # 3. Отправляем новое сообщение навигации с кнопками
    embed = discord.Embed(
        title="⬇️ СИСТЕМА ПОДБОРА ПАТИ WARFRAME ⬇️",
        description="Нажмите кнопку, чтобы начать сбор группы для миссий **Арбитраж** или **Каскад**.",
        color=discord.Color.dark_red()
    )
    
    if NAV_IMAGE_URL:
        embed.set_image(url=NAV_IMAGE_URL)
        
    embed.set_footer(text="Автоматическое удаление тикетов через 1 час (требуется !set_lfg).")
    
    await channel.send(
        embed=embed,
        view=MainNavigationView(ctx.bot)
    )

    await ctx.send(f"✅ Канал навигации установлен и стартовое окно отправлено: {channel.mention}.")


@bot.command(name='set_lfg')
@requires_admin
async def set_lfg_channel(ctx, channel: discord.TextChannel):
    global CONFIG
    CONFIG['LFG_CHANNEL_ID'] = channel.id
    save_config(CONFIG)
    await ctx.send(f"✅ Канал поиска пати установлен: {channel.mention}. ID сохранен.")

@bot.command(name='set_role')
@requires_admin
async def set_arbitrage_role(ctx, role: discord.Role):
    global CONFIG
    CONFIG['ARBITRAGE_ROLE_ID'] = role.id
    save_config(CONFIG)
    await ctx.send(f"✅ Роль для пинга Арбитража установлена: {role.mention}. ID сохранен.")

@bot.command(name='set_cascade_role')
@requires_admin
async def set_cascade_role(ctx, role: discord.Role):
    global CONFIG
    CONFIG['CASCAD_ROLE_ID'] = role.id
    save_config(CONFIG)
    await ctx.send(f"✅ Роль для пинга Каскада установлена: {role.mention}. ID сохранен.")

@bot.command(name='set_map_role') 
@requires_admin
async def set_map_role(ctx, map_name: str, role: discord.Role):
    """Устанавливает роль для пинга конкретной карты Арбитража."""
    global CONFIG
    
    formatted_map_name = map_name.capitalize() 

    is_valid_map = any(
        formatted_map_name in [m['name'] for m in tier_maps]
        for tier_maps in MAP_TIERS_DATA.values()
    )

    if not is_valid_map:
        await ctx.send(f"❌ Карта с именем **{formatted_map_name}** не найдена в списке карт Арбитража. Проверьте правильность написания.")
        return

    CONFIG['MAP_ROLES'][formatted_map_name] = role.id
    save_config(CONFIG)
    await ctx.send(f"✅ Роль для карты **{formatted_map_name}** установлена: {role.mention}. ID сохранен.")


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ У вас нет прав `Управлять сервером` для выполнения этой команды.")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("❌ Неверный аргумент. Укажите канал или роль, например: `!set_nav #канал` или `!set_map_role Casta @роль`.")
    else:
        print(f"Ошибка в команде: {error}")
        
# =================================================================
# 6. ЗАПУСК БОТА (ФИНАЛЬНАЯ ВЕРСИЯ С KEEP-ALIVE)
# =================================================================

@bot.event
async def on_ready():
    """
    [ИСПРАВЛЕНО] Теперь on_ready только регистрирует MainNavigationView, 
    чтобы обеспечить работу кнопок после перезапуска.
    Отправка сообщения перенесена в !set_nav.
    """
    print(f'Бот готов: {bot.user}')
    
    # Регистрируем View для постоянных кнопок.
    bot.add_view(MainNavigationView(bot)) 
    
    print("Логика отправки навигационного сообщения перенесена в команду !set_nav.")


# ----------------- Блок Веб-Сервера -----------------

async def handle(request):
    """Минимальный обработчик запроса для Render."""
    return web.Response(text="Bot is running!")

async def start_server():
    """Запускает веб-сервер, который будет слушать порт, предоставленный хостом."""
    # Render предоставляет порт через переменную окружения PORT
    port = int(os.environ.get('PORT', 8080))
    app = web.Application()
    app.add_routes([web.get('/', handle)])
    
    # Запускаем сервер
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    
    print(f"✅ Web server started on port {port}")
    await site.start()

# ----------------- Блок Self-Ping (Ход Конем) -----------------

async def keep_alive_ping():
    """Периодически отправляет HTTP-запрос самому себе, чтобы не дать сервису заснуть."""
    # Переменная окружения должна быть установлена на Render
    external_url = os.environ.get('EXTERNAL_URL')
    
    if not external_url:
        print("⚠️ Предупреждение: Переменная EXTERNAL_URL не установлена. Бот может заснуть.")
        return

    # Используем aiohttp для асинхронного пинга
    async with ClientSession() as session:
        while True:
            # Пингуем каждые 14 минут (меньше, чем 15-минутный лимит Render)
            await asyncio.sleep(14 * 60) 
            try:
                # Отправляем HEAD запрос, чтобы не тратить лишний трафик
                async with session.get(external_url) as response:
                    print(f"📡 Self-ping OK: Status {response.status}")
            except Exception as e:
                print(f"❌ Ошибка при самопинге: {e}. Проверьте правильность EXTERNAL_URL.")


# ----------------- Главная точка запуска -----------------

async def main():
    """Запускает Discord-бота, веб-сервер и self-ping одновременно."""
    if not BOT_TOKEN:
        print("\n\n-- ОШИБКА ЗАПУСКА --")
        print("Бот не был запущен, так как переменная окружения 'BOT_TOKEN' не установлена.")
        return

    # asyncio.gather запускает все задачи параллельно
    await asyncio.gather(
        bot.start(BOT_TOKEN),
        start_server(),
        keep_alive_ping() 
    )


if __name__ == '__main__':
    try:
        # discord.py требует запуск через asyncio.run()
        asyncio.run(main())
    except discord.errors.LoginFailure:
        print("\n\n-- ОШИБКА АВТОРИЗАЦИИ --")
        print("Проверьте, правильно ли вы установили переменную окружения 'BOT_TOKEN'!")
    except KeyboardInterrupt:
        print("Бот остановлен вручную.")
    except Exception as e:
        print(f"Критическая ошибка при запуске: {e}")
