# Discord Archiver

This script archives Discord channels to PDF files. It provides an interactive command-line interface to select a server and channel, then exports the channel's history to a PDF. It can also be used to archive channels based on user search, and provides options to notify users and remove them from channels.

## Prerequisites

- Python 3.7+
- [DiscordChatExporter.Cli](https://github.com/Tyrrrz/DiscordChatExporter)
- The Python packages listed in `requirements.txt`.

## Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/your-username/discord-archiver.git
    cd discord-archiver
    ```

2.  **Install Python dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Install DiscordChatExporter.Cli:**
    Follow the installation instructions on the [DiscordChatExporter releases page](https://github.com/Tyrrrz/DiscordChatExporter/releases). Make sure the `DiscordChatExporter.Cli` executable is in your system's PATH or provide the path to it in the `.env` file.

## Getting a Discord Bot Token

To use this script, you need a Discord bot token. Follow these steps to create a bot and get a token:

1.  **Go to the Discord Developer Portal:**
    Open your web browser and navigate to the [Discord Developer Portal](https://discord.com/developers/applications).

2.  **Create a New Application:**
    - Click the "New Application" button.
    - Give your application a name (e.g., "Discord Archiver") and click "Create".

3.  **Create a Bot:**
    - In the left-hand menu, click on "Bot".
    - Click the "Add Bot" button and confirm by clicking "Yes, do it!".

4.  **Get the Bot Token:**
    - Under the "Token" section, click the "Copy" button to copy the bot token.
    - **Important:** Keep this token secure and do not share it with anyone.

5.  **Enable Privileged Gateway Intents:**
    - On the same "Bot" page, scroll down to the "Privileged Gateway Intents" section.
    - Enable the "SERVER MEMBERS INTENT" and "MESSAGE CONTENT INTENT".

6.  **Invite the Bot to Your Server:**
    - In the left-hand menu, click on "OAuth2" and then "URL Generator".
    - Under "Scopes", select `bot`.
    - Under "Bot Permissions", select the following permissions:
        - `Read Messages/View Channels`
        - `Send Messages`
        - `Manage Channels`
        - `Read Message History`
        - `Attach Files`
    - Copy the generated URL and paste it into your web browser to invite the bot to your server.

## Usage

1.  **Create a `.env` file:**
    Copy the `.env.example` to `.env` and fill in the required values.
    ```bash
    cp .env.example .env
    ```

    **`.env` file variables:**

    - `DISCORD_TOKEN`: Your Discord bot token.
    - `DCE_CLI_PATH`: (Optional) The path to the `DiscordChatExporter.Cli` executable. If not provided, the script will try to find it in your system's PATH.
    - `SAVE_DIRECTORY`: (Optional) The directory where the exported PDF files will be saved. Defaults to the current directory.
    - `UPLOAD_SERVER_ID`: (Optional) The ID of the server where you want to upload the archived PDFs.
    - `UPLOAD_CHANNEL_ID`: (Optional) The ID of the channel where you want to upload the archived PDFs.

2.  **Run the script:**
    ```bash
    python archive.py
    ```

    The script will guide you through the process of selecting a server, channel, and other options.

## Features

- Interactive CLI for selecting servers and channels.
- Archive channels to PDF.
- Search for channels by username.
- Option to upload the PDF to a Discord channel.
- Option to DM the PDF to channel members.
- Option to delete the channel after archiving.
- Richly formatted output in the terminal.