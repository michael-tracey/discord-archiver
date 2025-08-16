import subprocess
import os
import shlex
import discord
from discord.ext import commands
import asyncio
from dotenv import load_dotenv
import shutil
import tempfile
import io
import re # Import regex for filename sanitization

# Import rich for enhanced display
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Prompt, Confirm
from rich.panel import Panel
from rich.text import Text
from rich.rule import Rule
from rich.tree import Tree
from rich.style import Style

# Initialize Rich Console
console = Console()

# --- Custom Styles ---
prompt_style = Style(color="white", bgcolor="blue")
category_style = Style(color="white", bgcolor="red")

# Load environment variables from .env file
load_dotenv()

# Constants for retry logic when sending to Discord
MAX_RETRIES = 5
INITIAL_DELAY = 1  # seconds

# --- Utility Function for Filename Sanitization ---
def sanitize_filename(name):
    """
    Sanitizes a string to be used as a filename by removing invalid characters.
    """
    # Replace invalid characters with an underscore
    s = re.sub(r'[\\/:*?"<>|]', '_', name)
    # Remove leading/trailing spaces and dots
    s = s.strip()
    # Replace multiple spaces/underscores with single
    s = re.sub(r'[\s_]+', '_', s)
    # Truncate if too long (max 255 chars is common, leave space for extension)
    return s[:200]

# --- Bot Setup ---
intents = discord.Intents.default()
intents.guilds = True
intents.message_content = True
intents.members = True # Required to access guild members for DM functionality

bot = commands.Bot(command_prefix='!', intents=intents)

def run_command(command, description):
    """
    Executes a shell command and prints its output using rich.
    Handles potential errors during command execution.
    """
    console.print(Rule(f"[bold cyan]{description}[/bold cyan]"))
    console.print(f"[grey]Executing: {' '.join(shlex.quote(arg) for arg in command)}[/grey]")
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        console.print(Panel(result.stdout, title="[green bold]STDOUT[/green bold]", border_style="green"))
        if result.stderr:
            console.print(Panel(result.stderr, title="[yellow bold]STDERR[/yellow bold]", border_style="yellow"))
        return True
    except FileNotFoundError:
        console.print(f"[bold red]Error:[/] Command '[cyan]{command[0]}[/cyan]' not found.", style="red")
        return False
    except subprocess.CalledProcessError as e:
        console.print(f"[bold red]Error:[/] Command '[cyan]{command[0]}[/cyan]' failed with exit code [bold]{e.returncode}[/bold]", style="red")
        console.print(Panel(e.stdout, title="[red bold]STDOUT (Error)[/red bold]", border_style="red"))
        console.print(Panel(e.stderr, title="[red bold]STDERR (Error)[/red bold]", border_style="red"))
        return False
    except Exception as e:
        console.print(f"[bold red]An unexpected error occurred while executing the command:[/bold red] {e}", style="red")
        return False

async def archive_one_channel(chat_to_process, discord_token, save_directory, dce_cli_path):
    """
    Archives a single channel to a PDF and returns the file path.
    """
    channel_name_for_file = f"#{chat_to_process.name}" if not isinstance(chat_to_process, discord.DMChannel) else f"DM with {chat_to_process.recipient.name}"
    console.print(Rule(f"[bold cyan]Processing: {channel_name_for_file} (ID: {chat_to_process.id})[/bold cyan]"))

    sanitized_chat_name = sanitize_filename(channel_name_for_file)
    
    output_filename_base = f"discord_export_{sanitized_chat_name}_{chat_to_process.id}"

    html_file = os.path.join(save_directory, f"{output_filename_base}.html")
    pdf_file = os.path.join(save_directory, f"{output_filename_base}.pdf")

    # --- Export Discord chat to HTML ---
    console.print(Rule(f"[bold cyan]Exporting to HTML for {channel_name_for_file}[/bold cyan]"))
    export_command = [dce_cli_path, "export", "-t", discord_token, "-c", str(chat_to_process.id), "-o", html_file, "--media", "--markdown"]

    if not run_command(export_command, f"DiscordChatExporter for {channel_name_for_file}"):
        return None
    if not os.path.exists(html_file):
        return None

    # --- Convert HTML to PDF ---
    console.print(Rule(f"[bold cyan]Converting to PDF for {channel_name_for_file}[/bold cyan]"))
    weasyprint_args = []
    temp_css_file = None
    try:
        temp_css_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.css', encoding='utf-8')
        temp_css_file.write("@page { margin: 0; }")
        temp_css_file.close()
        weasyprint_args.extend(["--stylesheet", temp_css_file.name])
    except Exception as e:
        console.print(f"[bold red]Error creating temporary stylesheet for margins: {e}[/bold red]")

    convert_command = ["weasyprint", *weasyprint_args, "--encoding", "utf-8", html_file, pdf_file]
    
    pdf_path = None
    if run_command(convert_command, f"WeasyPrint Conversion for {channel_name_for_file}"):
        if os.path.exists(pdf_file):
            pdf_path = pdf_file

    if temp_css_file and os.path.exists(temp_css_file.name):
        os.remove(temp_css_file.name)

    # --- Cleanup ---
    try:
        if os.path.exists(html_file):
            os.remove(html_file)
        media_dir = os.path.join(save_directory, f"{os.path.splitext(os.path.basename(html_file))[0]}_attachments")
        if os.path.isdir(media_dir):
            shutil.rmtree(media_dir)
    except OSError as e:
        console.print(f"[bold red]Error during cleanup: {e}[/bold red]")

    return pdf_path

async def run_standard_post_archive_flow(generated_pdf_files, chosen_guild, initial_selection):
    """
    Runs the standard post-archive steps: Upload, DM, and Delete.
    """
    # --- Step 5: Optional PDF Upload ---
    console.print(Rule("[bold cyan]Step 5: PDF Upload[/bold cyan]"))
    if generated_pdf_files:
        upload_channel = None
        upload_guild = chosen_guild
        
        upload_server_id_str = os.getenv('UPLOAD_SERVER_ID')
        if upload_server_id_str:
            try:
                guild = bot.get_guild(int(upload_server_id_str))
                if guild: upload_guild = guild
                else: console.print(f"[yellow]Warning: Bot not in server with ID {upload_server_id_str}. Defaulting to current server.[/yellow]")
            except ValueError:
                 console.print(f"[yellow]Warning: Invalid UPLOAD_SERVER_ID. Defaulting to current server.[/yellow]")

        upload_channel_id_str = os.getenv('UPLOAD_CHANNEL_ID')
        if upload_channel_id_str:
            try:
                if upload_guild:
                    upload_channel = upload_guild.get_channel(int(upload_channel_id_str))
            except ValueError:
                console.print(f"[yellow]Warning: Invalid UPLOAD_CHANNEL_ID format.[/yellow]")
        elif upload_guild:
            upload_channel = discord.utils.get(upload_guild.text_channels, name='channel-archive')

        if upload_channel and upload_channel.permissions_for(upload_guild.me).send_messages and upload_channel.permissions_for(upload_guild.me).attach_files:
            upload_prompt = Text(f"Upload the generated PDF(s) to #{upload_channel.name} in server {upload_guild.name}?", style=prompt_style)
            if Confirm.ask(upload_prompt, default=True):
                 with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
                    upload_task = progress.add_task("[cyan]Uploading PDFs...", total=len(generated_pdf_files))
                    for pdf in generated_pdf_files:
                        try:
                            with open(pdf, 'rb') as f:
                                await upload_channel.send(file=discord.File(f, filename=os.path.basename(pdf)))
                        except Exception as e:
                            progress.console.print(f"[red]Failed to upload {os.path.basename(pdf)}: {e}[/red]")
                        progress.update(upload_task, advance=1)
        # ... error handling ...

    # --- Step 6: Optional DM to channel members ---
    console.print(Rule("[bold cyan]Step 6: Optional DM to Channel Members[/bold cyan]"))
    if generated_pdf_files and Confirm.ask(Text("DM the PDF(s) to other channel members?", style=prompt_style), default=False):
        if hasattr(initial_selection, 'guild') and not initial_selection.guild.chunked: 
            await initial_selection.guild.chunk()
        
        members_in_channel = []
        if hasattr(initial_selection, 'members'):
            members_in_channel = [m for m in initial_selection.members if not m.bot]

        if members_in_channel:
            member_display_list = []
            member_id_map = {}
            for i, m in enumerate(members_in_channel):
                member_number = i + 1
                member_display_list.append(f"[{member_number}] {m.display_name} (@{m.name}) (ID: {m.id})")
                member_id_map[str(member_number)] = str(m.id)

            console.print(Panel("\n".join(member_display_list), title="[green]Members in Channel[/green]"))
            
            while True:
                dm_target_numbers_str = Prompt.ask(Text("Enter comma-separated numbers of members to DM (or leave blank to skip)", style=prompt_style), default="")
                if not dm_target_numbers_str:
                    console.print("[yellow]Skipping DM to channel members.[/yellow]")
                    break
                
                dm_target_numbers = [num.strip() for num in dm_target_numbers_str.split(',') if num.strip().isdigit()]
                
                if not dm_target_numbers:
                    console.print("[red]No valid member numbers entered. Please enter comma-separated numbers.[/red]")
                    continue

                selected_member_ids = []
                for num in dm_target_numbers:
                    if num in member_id_map:
                        selected_member_ids.append(member_id_map[num])

                if not selected_member_ids:
                    console.print("[yellow]None of the entered numbers match members in this channel. Please try again.[/yellow]")
                    continue
                
                selected_members_to_dm = [m for m in members_in_channel if str(m.id) in selected_member_ids]

                with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
                    dm_task = progress.add_task("[cyan]Sending DMs...", total=len(selected_members_to_dm) * len(generated_pdf_files))
                    for member in selected_members_to_dm:
                        for pdf in generated_pdf_files:
                            try:
                                with open(pdf, 'rb') as f:
                                    await member.send(file=discord.File(f, filename=os.path.basename(pdf)))
                                
                                dm_message = f"This is an archived copy of the Discord channel: "
                                if initial_selection.guild:
                                    dm_message += f"**Server:** {initial_selection.guild.name}, "
                                
                                if isinstance(initial_selection, discord.Thread):
                                    dm_message += f"**Channel:** #{initial_selection.parent.name}, **Thread:** {initial_selection.name}"
                                else:
                                    dm_message += f"**Channel:** #{initial_selection.name}"
                                dm_message += ".\n\nFor your records."
                                
                                await member.send(dm_message)
                                progress.console.print(f"[green]DM sent to {member.display_name} for {os.path.basename(pdf)}[/green]")
                            except Exception as e:
                                progress.console.print(f"[red]Failed to send DM to {member.display_name} for {os.path.basename(pdf)}: {e}[/red]")
                            progress.update(dm_task, advance=1)
                break
        else:
            console.print("[yellow]No non-bot members found in this channel to DM.[/yellow]")

    # --- Step 7: Optional Channel Deletion ---
    console.print(Rule("[bold cyan]Step 7: Optional Channel Deletion[/bold cyan]"))
    if initial_selection and not isinstance(initial_selection, discord.DMChannel) and initial_selection.permissions_for(chosen_guild.me).manage_channels:
        delete_prompt = Text(f"Delete the {'thread' if isinstance(initial_selection, discord.Thread) else 'channel'} '[bold]{initial_selection.name}[/bold]'?", style=prompt_style)
        if Confirm.ask(delete_prompt, default=False):
            try:
                await initial_selection.delete()
                console.print(f"[green]Channel deleted.[/green]")
            except Exception as e:
                console.print(f"[red]Failed to delete channel: {e}[/red]")

async def run_user_search_flow():
    """
    Handles the workflow for finding channels by searching for a user.
    """
    console.print(Rule("[bold cyan]Archive by User Search[/bold cyan]"))
    
    target_user = None
    while target_user is None:
        username_prompt = Text("Enter username/handle to search for (or 'q' to go back)", style=prompt_style)
        search_query = Prompt.ask(username_prompt, default="").lower()
        
        if search_query == 'q': return True
        if not search_query: continue

        if not any(g.chunked for g in bot.guilds):
             with Progress(SpinnerColumn(), TextColumn("[cyan]Fetching server members..."), console=console) as progress:
                for guild in bot.guilds: await guild.chunk()

        found_users_map = {}
        for member in bot.get_all_members():
             if search_query in member.name.lower() or search_query in member.display_name.lower() or (member.global_name and search_query in member.global_name.lower()):
                if member.id not in found_users_map:
                    found_users_map[member.id] = member

        found_users = list(found_users_map.values())

        if not found_users:
            console.print(f"[yellow]No users found matching '{search_query}'.[/yellow]")
            continue
        
        if len(found_users) == 1:
            target_user = found_users[0]
        else:
            user_choices = {str(i+1): f"{u.display_name} (@{u.name})" for i, u in enumerate(found_users)}
            console.print(Panel("\n".join([f"[{k}] {v}" for k,v in user_choices.items()]), title="[green]Select a User[/green]"))
            choice_str = Prompt.ask(Text("Enter the number of the user", style=prompt_style), choices=list(user_choices.keys()))
            if choice_str: target_user = found_users[int(choice_str) - 1]
            else: continue
    
    console.print(Rule(f"[bold cyan]Finding mutual channels for {target_user.display_name}[/bold cyan]"))
    
    # --- Build Tree of Mutual Channels ---
    tree = Tree(f"[bold green]Mutual Channels with {target_user.display_name}[/bold green]", guide_style="bold cyan")
    
    flat_channel_list = []
    
    try:
        dm_channel = await target_user.create_dm()
        tree.add(f"[[bold]1[/bold]] Direct Message with {target_user.name}")
        flat_channel_list.append(dm_channel)
    except Exception:
        pass

    for guild in bot.guilds:
        member = guild.get_member(target_user.id)
        if not member: continue
        
        guild_channels = []
        for channel in guild.text_channels:
            if channel.permissions_for(member).read_messages and channel.permissions_for(guild.me).read_messages:
                guild_channels.append(channel)
        for thread in guild.threads:
            if thread.permissions_for(member).read_messages and thread.permissions_for(guild.me).read_messages:
                guild_channels.append(thread)
        
        if guild_channels:
            guild_node = tree.add(f"[bold blue]Server: {guild.name}[/bold blue]")
            
            guild_channels.sort(key=lambda c: (c.category.position if hasattr(c, 'category') and c.category else float('inf'), c.position if hasattr(c, 'position') else float('inf')))

            last_category_id = object()
            category_node = None
            for channel in guild_channels:
                current_index = len(flat_channel_list) + 1
                
                category_id = channel.category_id if hasattr(channel, 'category') and channel.category else None
                if category_id != last_category_id:
                    last_category_id = category_id
                    category_name = channel.category.name if channel.category else "No Category"
                    category_node = guild_node.add(Text(f"--- {category_name} ---", style=category_style))

                (category_node or guild_node).add(f"[[bold]{current_index}[/bold]] #{channel.name}")
                flat_channel_list.append(channel)


    if not flat_channel_list:
        console.print(f"[red]No mutual readable channels found with {target_user.display_name}.[/red]")
        return True

    console.print(tree)
    
    initial_selection = None
    choice_str = Prompt.ask(Text("Enter channel number", style=prompt_style), choices=[str(i+1) for i in range(len(flat_channel_list))])
    if not choice_str: return True
    initial_selection = flat_channel_list[int(choice_str) - 1]
    
    target_member = target_user
    if not isinstance(initial_selection, discord.DMChannel):
        target_member = initial_selection.guild.get_member(target_user.id)

    # --- Post-Selection Actions ---
    console.print(Rule("[bold cyan]Post-Archive Options[/bold cyan]"))
    if not isinstance(initial_selection, discord.DMChannel):
        member_list = "\n".join([f"- {m.display_name}" for m in initial_selection.members])
        console.print(Panel(member_list, title=f"Members in #{initial_selection.name}", border_style="green"))
        
    action_choices = {
        "1": "Remove user only",
        "2": "Remove user, archive, and DM",
        "3": "Remove user, archive, DM, and notify channel (default)",
        "4": "Remove user, archive, save to archive channel, and notify",
        "5": "None"
    }
    console.print(Panel("\n".join([f"[{k}] {v}" for k,v in action_choices.items()]), title="[green]Select Action[/green]"))
    action_choice = Prompt.ask(Text("Select action", style=prompt_style), choices=list(action_choices.keys()), default="3")

    if action_choice == "5":
        console.print("[yellow]No action taken.[/yellow]")
        return True

    # --- Perform Actions ---
    pdf_file_path = None
    
    # Archive if needed
    if action_choice in ["2", "3", "4"]:
        current_discord_token = bot.http.token
        dce_cli_path = os.getenv('DCE_CLI_PATH') or shutil.which("DiscordChatExporter.Cli")
        save_directory = os.getenv('SAVE_DIRECTORY', ".")
        pdf_file_path = await archive_one_channel(initial_selection, current_discord_token, save_directory, dce_cli_path)
        if not pdf_file_path:
            console.print("[bold red]Archiving failed. Aborting further actions.[/bold red]")
            return True

    # DM if needed
    if action_choice in ["2", "3"] and pdf_file_path:
        console.print(f"[cyan]Sending PDF to {target_member.display_name}...[/cyan]")
        try:
            with open(pdf_file_path, 'rb') as f:
                await target_member.send(file=discord.File(f, filename=os.path.basename(pdf_file_path)))
            console.print("[green]DM sent successfully.[/green]")
        except Exception as e:
            console.print(f"[red]Failed to send DM: {e}[/red]")

    # Remove user if not a DM
    if not isinstance(initial_selection, discord.DMChannel):
        can_manage = initial_selection.permissions_for(initial_selection.guild.me).manage_permissions
        if isinstance(initial_selection, discord.Thread):
            can_manage = initial_selection.permissions_for(initial_selection.guild.me).manage_threads

        if can_manage:
            console.print(f"[cyan]Removing {target_member.display_name} from {initial_selection.name}...[/cyan]")
            try:
                if isinstance(initial_selection, discord.Thread):
                    await initial_selection.remove_user(target_member)
                else: # Is a TextChannel
                    await initial_selection.set_permissions(target_member, overwrite=None)
                console.print(f"[green]Removed {target_member.display_name}.[/green]")

                # Notify if needed
                if action_choice in ["3", "4"]:
                    await initial_selection.send(f":wave: {target_member.mention} has been removed from this channel. An archive of the conversation has been processed.")
            except Exception as e:
                console.print(f"[red]Failed to remove user or post notice: {e}[/red]")
        else:
            console.print(f"[yellow]Warning: Bot lacks permissions to remove users from {initial_selection.name}.[/yellow]")

    # Upload to archive channel if needed
    if action_choice == "4" and pdf_file_path:
        await run_standard_post_archive_flow([pdf_file_path], initial_selection.guild, initial_selection)

    return True

async def run_server_channel_flow_complete():
    console.print(Rule("[bold cyan]Archive by Server/Channel Selection[/bold cyan]"))
    current_discord_token = bot.http.token
    
    # --- Step 1: Choose a Server ---
    guilds = bot.guilds
    if not guilds:
        console.print("[bold red]The bot is not in any Discord servers.[/bold red]", style="red")
        return True

    server_choices = {str(i+1): f"{guild.name} (ID: {guild.id})" for i, guild in enumerate(guilds)}
    console.print(Panel("\n".join([f"[{key}] {value}" for key, value in server_choices.items()]), title="[green bold]Available Discord Servers[/green bold]", border_style="blue"))

    chosen_guild = None
    while chosen_guild is None:
        choice_str = Prompt.ask(Text("Enter the number of the server to export from", style=prompt_style), choices=list(server_choices.keys()))
        if choice_str: chosen_guild = guilds[int(choice_str) - 1]

    # --- Step 2: Choose a Channel ---
    console.print(Rule("[bold cyan]Step 2: Choose a Channel or Thread to Export[/bold cyan]"))
    
    initial_selection = None
    chats_to_export = []
    
    full_readable_channels_for_selection = sorted(
        [ch for ch in chosen_guild.text_channels if ch.permissions_for(chosen_guild.me).read_messages] +
        [th for th in chosen_guild.threads if th.permissions_for(chosen_guild.me).read_messages],
        key=lambda x: (
            (x.category.position if hasattr(x, 'category') and x.category else float('inf')),
            x.position if hasattr(x, 'position') else float('inf')
        ))

    if not full_readable_channels_for_selection:
        console.print(f"[bold red]No readable text channels or threads found in '[bold]{chosen_guild.name}[/bold]'.[/bold red]", style="red")
        return True

    def build_channel_display_tree(channels_to_display):
        tree = Tree(f"[bold]Available Channels & Threads in {chosen_guild.name}[/bold]", guide_style="bold green")
        last_category_id = object()
        current_category_node = None
        for i, item in enumerate(channels_to_display):
            category_id = item.category_id if hasattr(item, 'category') and item.category else None
            
            if category_id != last_category_id:
                last_category_id = category_id
                category_name = item.category.name if item.category else "No Category"
                category_text = Text(f"--- {category_name} ---", style=category_style)
                current_category_node = tree.add(category_text)
            
            node_text = f"[[bold]{i + 1}[/bold]] #{item.name}"
            node_parent = current_category_node if current_category_node is not None else tree
            node_parent.add(node_text)
        return tree

    filtered_channels = []
    while True:
        filter_prompt = Text("Enter text to filter channels (or leave blank for all, 'q' to go back):", style=prompt_style)
        filter_string = Prompt.ask(filter_prompt).lower()

        if filter_string == 'q':
            return True # Go back to main menu

        if filter_string:
            filtered_channels = [ch for ch in full_readable_channels_for_selection if filter_string in ch.name.lower()]
            if not filtered_channels:
                console.print("[yellow]No channels found matching your filter. Please try again.[/yellow]")
                continue
        else:
            filtered_channels = full_readable_channels_for_selection
        break

    console.print(build_channel_display_tree(filtered_channels))
    
    prompt_choices = [str(i+1) for i in range(len(filtered_channels))] if len(filtered_channels) <= 10 else None
    if len(filtered_channels) > 10:
        console.print("[yellow]Note: Due to the large number of channels, choices are not displayed in the prompt. Please enter the number directly.[/yellow]")

    choice_str = Prompt.ask(Text("Enter the number of the channel/thread to export", style=prompt_style), choices=prompt_choices)
    if not choice_str: return True
    initial_selection = filtered_channels[int(choice_str) - 1]
    
    if isinstance(initial_selection, discord.TextChannel):
        chats_to_export.append(initial_selection)
        chats_to_export.extend([t for t in initial_selection.threads if t.permissions_for(chosen_guild.me).read_messages])
    else:
        chats_to_export.append(initial_selection)

    generated_pdf_files = []
    dce_cli_path = os.getenv('DCE_CLI_PATH') or shutil.which("DiscordChatExporter.Cli")
    save_directory = os.getenv('SAVE_DIRECTORY', ".")

    for chat in chats_to_export:
        pdf_path = await archive_one_channel(chat, current_discord_token, save_directory, dce_cli_path)
        if pdf_path:
            generated_pdf_files.append(pdf_path)
    
    await run_standard_post_archive_flow(generated_pdf_files, chosen_guild, initial_selection)

    return True

async def run_main_process():
    """
    The main process loop that presents the top-level choice.
    """
    console.clear()
    console.print(Panel("[bold cyan]--- Interactive Discord Chat Exporter & PDF Converter ---[/bold cyan]", title="[yellow]Welcome![/yellow]"))
    
    mode_prompt = Text("How would you like to select a channel to archive?", style=prompt_style)
    choices = {"1": "Select from a server's channel list", "2": "Find channels by searching for a user"}
    console.print(Panel("\n".join([f"[{k}] {v}" for k, v in choices.items()]), title="[green]Select Mode[/green]"))
    mode_choice = Prompt.ask(mode_prompt, choices=list(choices.keys()), default="1")

    if mode_choice == "1":
        return await run_server_channel_flow_complete()
    elif mode_choice == "2":
        return await run_user_search_flow()
    
    return True

@bot.event
async def on_ready():
    """
    When the bot is ready, it will start the main export loop.
    """
    console.print(Rule(f'[bold green]Logged in as {bot.user.name} ({bot.user.id})[/bold green]'))
    
    while True:
        should_continue = await run_main_process()
        if not should_continue:
            break

        continue_prompt = Text("Perform another export?", style=prompt_style)
        if not Confirm.ask(continue_prompt, default=True):
            break

    await bot.close()


async def main_async():
    """Asynchronous main function to run the bot."""
    discord_token = os.getenv('DISCORD_TOKEN')
    if not discord_token:
        token_prompt = Text("Enter your Discord Bot or User Token", style=prompt_style)
        discord_token = Prompt.ask(token_prompt, password=True)
        
    if not discord_token:
        console.print("[red]Discord Token cannot be empty. Exiting.[/red]")
        return

    try:
        await bot.start(discord_token)
    except discord.LoginFailure:
        console.print("\n[red]Error: Invalid Discord token provided.[/red]")
    finally:
        console.print(Rule("[bold green]Bot has been shut down.[/bold green]"))


if __name__ == "__main__":
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        console.print("\n[yellow]Operation cancelled by user.[/yellow]")
    except Exception as e:
        console.print(f"\n[red]An unexpected error occurred: {e}[/red]")

