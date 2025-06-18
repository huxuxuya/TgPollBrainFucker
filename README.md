# TgPollBrainFucker: Advanced Telegram Poll Bot

A powerful and feature-rich bot for Telegram designed to create highly customizable polls and manage fundraising campaigns directly within your groups. All management is handled through a convenient and interactive dashboard in a private chat with the bot, ensuring group chats remain clean.

---

## Key Features

### 🚀 **Convenient and Clean Management**
- **Private Dashboard**: All poll creation, editing, and management happens in a private chat with the bot. No more command spam in your groups!
- **Step-by-Step Wizard**: An intuitive wizard guides you through creating new polls, making the process quick and error-free.
- **Drafts**: Save polls as drafts to fine-tune them before publishing.

### 🔧 **Deep Poll Customization**
- **Per-Option Settings**: Customize the behavior of *each* poll option individually.
  - **Show/Hide Voters**: Choose whether to display the names of users who voted for an option.
  - **Name Display Styles**: Display voter names as a simple list, a numbered list, or a compact inline list.
  - **Show/Hide Vote Count**: Toggle the visibility of the vote counter for each option.
  - **Priority Option**: Mark an option as a "priority" to highlight it with a ⭐.
  - **Custom Emojis**: Assign a unique emoji to each option that appears next to the voters' names.
- **Web App Polls**: Create polls that open in a separate Web App for more complex voting scenarios (e.g., timeline selection, advanced forms).

### 💰 **Integrated Fundraising**
- **Contribution Amounts**: Assign a specific monetary value to each poll option.
- **Automatic Calculation**: The bot automatically calculates the total amount collected based on votes.
- **Progress Bar**: A visual progress bar shows how close you are to a fundraising goal.
- **Goal Setting**: Define a target sum for your collection.

### 🛠️ **Powerful Admin Tools**
- **Nudge Non-Voters**: Send a formatted message into the group that tags all participants who haven't voted yet.
- **Repost Poll**: "Bump" the poll message to the bottom of the chat to increase visibility.
- **Manual Vote Editing**: Manually add or remove votes for any user.
- **Participant Management**: View the list of registered participants, exclude users from polls, and manually add new users via a forwarded message.

### ⚙️ **Reliability and Administration**
- **Automatic Participant Discovery**: The bot automatically registers active users in a group as potential participants.
- **Supergroup Migration Ready**: Works seamlessly even after a group is upgraded to a supergroup.
- **Full Data Backup/Restore**: The bot owner can export the entire database to a JSON file and import it later, ensuring no data is lost.

---

## How to Use

1.  **Add the Bot to Your Group**: Find the bot on Telegram and add it as a member to your group.
2.  **Grant Admin Rights**: Promote the bot to an administrator. This is necessary for it to see messages, manage participants, and post polls.
3.  **Start a Private Chat**: Go to the bot's profile and send the `/start` command in a private message.
4.  **Select Your Chat**: The bot will show you a list of groups where you are both an admin. Choose the group you want to manage.
5.  **Create a Poll**: Use the "Create Poll" button and follow the wizard's instructions.
6.  **Customize and Launch**: After creating a draft, you can fine-tune its settings from the dashboard and then launch it into the group.

---

## Commands

While most actions are done via buttons, here are the primary commands:

- `/start` - Opens the management dashboard in a private chat.
- `/help` - Provides a brief help message and a link to the dashboard.
- `/debug` - (Owner only) Toggles debug logging.
- `/export_json` - (Owner only) Exports the entire database to a `JSON` file.
- `/import_json` - (Owner only) Reply to a `JSON` file with this command to restore the database. **Warning:** This will overwrite all existing data.

---

## Local Setup

1.  **Clone the Repository**:
    ```bash
    git clone <repository_url>
    cd TgPollBrainFucker
    ```
2.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```
3.  **Configure Environment**:
    -   Create a file named `.env` in the root directory.
    -   Add your bot's token to it:
        ```
        BOT_TOKEN="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
        BOT_OWNER_ID="987654321" # Your numeric Telegram user ID
        WEB_URL="https://your-app-name.onrender.com" # Required for Web Apps
        ```
4.  **Run the Bot**:
    ```bash
    python bot.py
    ```

---

## FAQ

-   **Why doesn't the bot see my group?**
    -   Ensure the bot has been added to the group and promoted to an administrator. It needs admin rights to function correctly.
-   **How are participants added?**
    -   The bot automatically adds users to the participant list when they send a message in the group. You can also add them manually via the dashboard.
-   **Why aren't results updating?**
    -   Make sure the bot is still an admin and has not been blocked by any group members. Check the bot's logs for any errors.

---

**Tech Stack:**
- `python-telegram-bot`
- `SQLAlchemy`
- `python-dotenv`