# ==========================================================
# [FILE]        : main.py  
# [VERSION]     : 2.1.2 - Complete Working Version
# [DATE]        : 2025-10-29
# [PROJECT]     : HKKM - Yuzu Companion
# [DESCRIPTION] : Complete CLI with all menu methods implemented
# [AUTHOR]      : Project Lead: Bani Baskara
# [TEAM]        : Deepseek, GPT, Qwen, Aihara
# [REPOSITORY]  : https://guthib.com/icedeyes12
# [LICENSE]     : MIT
# ==========================================================

from app import handle_user_message, handle_user_message_streaming, start_session, end_session_cleanup, summarize_memory, summarize_global_player_profile
from app import get_available_providers, get_all_models, set_preferred_provider, get_provider_models, get_vision_capabilities
from database import Database
from providers import get_ai_manager
from tools import multimodal_tools
from datetime import datetime
import threading
import webbrowser
import time
import re
import os
import json
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.markdown import Markdown
from rich.tree import Tree
from rich.table import Table
from rich.text import Text
from rich.prompt import Prompt, Confirm, IntPrompt
from rich.live import Live
from rich import print as rprint

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.patch_stdout import patch_stdout

console = Console()

def info(msg: str):
    console.print(f"[bold cyan]>[/] {msg}")

def success(msg: str):
    console.print(f"[bold green]OK[/] {msg}")

def error(msg: str):
    console.print(f"[bold red]ERR[/] {msg}")

def warning(msg: str):
    console.print(f"[bold yellow]WARN[/] {msg}")

def welcome_banner():
    profile = Database.get_profile()
    active_session = Database.get_active_session()
    time_now = datetime.now().strftime("%H:%M")
    
    vision_capabilities = get_vision_capabilities()
    multimodal_status = []
    if vision_capabilities['has_vision']:
        multimodal_status.append("Vision")
    if vision_capabilities['has_image_generation']:
        multimodal_status.append("ImageGen")
    
    banner = Panel.fit(
        f"[bold magenta]Yuzu Companion[/] • [cyan]{profile['partner_name']}[/]\n"
        f"[dim]User: {profile['display_name']} • Affection: {profile.get('affection', 50)}[/]\n"
        f"[dim]Session: {active_session.get('name')} • Messages: {active_session.get('message_count', 0)}[/]\n"
        f"[dim]{time_now} • Multimodal: {', '.join(multimodal_status) if multimodal_status else 'None'}[/]",
        style="bold magenta"
    )
    console.print(banner)

def fancy_prompt():
    profile = Database.get_profile()
    return f"{profile['display_name']} > "

class YuzuCompanionAgent:
    def __init__(self):
        self.config = self.load_config()
        self._profile_cache = None
        self._session_cache = None
        self._vision_capabilities_cache = None
        self._last_profile_update = 0
        self._last_session_update = 0
        self.CACHE_TTL = 5
        
        self.commands = self.get_available_commands()
        self.session_state = {
            'streaming': self.profile.get('providers_config', {}).get('streaming_enabled', False),
            'system_prompt': None,
            'current_provider': self.profile.get('providers_config', {}).get('preferred_provider', 'ollama'),
            'current_model': self.profile.get('providers_config', {}).get('preferred_model', 'glm-4.6:cloud')
        }
    
    @property
    def profile(self):
        current_time = time.time()
        if (self._profile_cache is None or 
            current_time - self._last_profile_update > self.CACHE_TTL):
            self._profile_cache = Database.get_profile()
            self._last_profile_update = current_time
        return self._profile_cache
    
    @property
    def session(self):
        current_time = time.time()
        if (self._session_cache is None or 
            current_time - self._last_session_update > self.CACHE_TTL):
            self._session_cache = Database.get_active_session()
            self._last_session_update = current_time
        return self._session_cache
    
    @property
    def vision_capabilities(self):
        if self._vision_capabilities_cache is None:
            self._vision_capabilities_cache = get_vision_capabilities()
        return self._vision_capabilities_cache
    
    def load_config(self):
        config_path = os.path.join(os.path.expanduser("~"), ".yuzu_companion_terminal.json")
        default_config = {
            "enable_rich_display": True,
            "auto_save_code_blocks": True,
            "show_typing_indicator": True,
            "command_history_size": 1000,
            "auto_detect_images": True,
            "confirm_clear_history": True
        }
        
        if not os.path.exists(config_path):
            with open(config_path, "w") as f:
                json.dump(default_config, f, indent=2)
            return default_config
        
        try:
            with open(config_path, "r") as f:
                return json.load(f)
        except:
            return default_config
    
    def save_config(self):
        config_path = os.path.join(os.path.expanduser("~"), ".yuzu_companion_terminal.json")
        try:
            with open(config_path, "w") as f:
                json.dump(self.config, f, indent=2)
            return True
        except Exception as e:
            error(f"Could not save config: {e}")
            return False
    
    def get_available_commands(self):
        return {
            "chat": ["/help", "/exit", "/quit", "/bye", "/cls"],
            "ai_control": ["/model", "/models", "/providers", "/system", "/stream", "/info", "/vision", "/capabilities"],
            "multimodal": ["/imagine", "/vision"],
            "session": ["/session", "/sessions", "/clear", "/history", "/context", "/profile", "/memory"],
            "system": ["/config", "/web"]
        }
    
    def print_help(self):
        help_table = Table(show_header=True, header_style="bold magenta", title="Yuzu Companion Commands")
        help_table.add_column("Category", style="cyan")
        help_table.add_column("Commands", style="white")
        
        for category, commands in self.commands.items():
            help_table.add_row(
                category.upper(),
                ", ".join(commands)
            )
        
        console.print(help_table)
        
        examples = Panel(
            "[bold]Quick Examples:[/]\n"
            "[cyan]/imagine[/] a cute anime cat with blue eyes\n"
            "[cyan]/vision[/] - switch to vision model\n"
            "[cyan]/model ollama/glm-4.6:cloud[/] - change AI model\n"
            "[cyan]/stream on[/] - enable real-time streaming\n"
            "[cyan]/stream off[/] - use complete responses\n"
            "[cyan]/config[/] - open configuration menu\n"
            "[cyan]/web[/] - launch web interface\n"
            "[cyan]/cls[/] - clear terminal screen",
            title="Examples",
            border_style="green"
        )
        console.print(examples)
    
    def clear_screen(self):
        os.system('clear')
        welcome_banner()
        console.print("\n[dim]Screen cleared. Type your message or use /help for commands.[/]")
        console.print("-" * 60)
    
    def handle_command(self, cmd_line: str):
        if not cmd_line.startswith('/'):
            return True
            
        parts = cmd_line[1:].strip().split()
        if not parts:
            return True
        
        cmd = parts[0].lower()
        args = parts[1:]
        
        match cmd:
            case 'exit' | 'quit' | 'bye':
                return self._handle_exit()
            
            case 'help' | '?':
                self.print_help()
            
            case 'cls':
                self.clear_screen()
            
            case 'model':
                self.handle_model_command(args)
            
            case 'models':
                self.show_available_models()
            
            case 'providers':
                self.show_available_providers()
            
            case 'stream':
                self.handle_stream_command(args)
            
            case 'vision' | 'imagine' | 'capabilities':
                self._handle_multimodal_commands(cmd, args)
            
            case 'session' | 'sessions' | 'clear' | 'history' | 'context' | 'profile' | 'memory':
                self._handle_session_commands(cmd, args)
            
            case 'config' | 'web':
                self._handle_system_commands(cmd, args)
            
            case 'system' | 'info':
                self._handle_misc_commands(cmd, args)
            
            case _:
                error(f"Unknown command '{cmd}'. Type /help for available commands.")
        
        return True
    
    def _handle_exit(self):
        console.print(f"\n[magenta]{self.profile['partner_name']}[/] > Ending terminal session...")
        end_session_cleanup(self.profile, interface="terminal", unexpected_exit=False)
        return False
    
    def _handle_multimodal_commands(self, cmd: str, args: list):
        command_handlers = {
            'vision': self.switch_to_vision,
            'imagine': self.generate_image,
            'capabilities': self.show_capabilities
        }
        if cmd in command_handlers:
            command_handlers[cmd](args if cmd == 'imagine' else None)
    
    def _handle_session_commands(self, cmd: str, args: list):
        command_handlers = {
            'session': self.session_management_menu,
            'sessions': self.list_sessions,
            'clear': self.clear_chat_history,
            'history': self.show_chat_history,
            'context': self.update_session_context,
            'profile': self.update_global_profile,
            'memory': self.show_memory_status
        }
        if cmd in command_handlers:
            command_handlers[cmd]()
    
    def _handle_system_commands(self, cmd: str, args: list):
        if cmd == 'config':
            self.config_menu()
        elif cmd == 'web':
            self.launch_web_interface()
    
    def _handle_misc_commands(self, cmd: str, args: list):
        if cmd == 'system':
            self.handle_system_prompt(args)
        elif cmd == 'info':
            self.show_status_info()
    
    def handle_stream_command(self, args):
        if not args:
            status = "ON" if self.session_state['streaming'] else "OFF"
            console.print(f"Streaming mode is currently: [bold cyan]{status}[/]")
            console.print("Usage: [cyan]/stream <on|off|status>[/]")
            return
        
        subcommand = args[0].lower()
        
        if subcommand in ['on', 'enable', 'true', '1']:
            self.session_state['streaming'] = True
            profile = Database.get_profile()
            providers_config = profile.get('providers_config', {})
            providers_config['streaming_enabled'] = True
            Database.update_profile({'providers_config': providers_config})
            success("Streaming mode: [bold green]ENABLED[/]")
            
        elif subcommand in ['off', 'disable', 'false', '0']:
            self.session_state['streaming'] = False
            profile = Database.get_profile()
            providers_config = profile.get('providers_config', {})
            providers_config['streaming_enabled'] = False
            Database.update_profile({'providers_config': providers_config})
            success("Streaming mode: [bold yellow]DISABLED[/]")
            
        elif subcommand in ['status', 'check']:
            status = "ON" if self.session_state['streaming'] else "OFF"
            console.print(f"Streaming mode is currently: [bold cyan]{status}[/]")
            
        else:
            error(f"Unknown stream command: {subcommand}")
            console.print("Usage: [cyan]/stream <on|off|status>[/]")
    
    def handle_model_command(self, args):
        if not args:
            console.print("Usage: [cyan]/model <provider>/<model>[/] OR [cyan]/model <model_name>[/]")
            return
        
        model_arg = ' '.join(args)
        if '/' in model_arg:
            provider_part, model_part = model_arg.split('/', 1)
            result = set_preferred_provider(provider_part.strip(), model_part.strip())
            success(result)
            self.update_session_state()
            console.print(f"[bold cyan]>[/] Active model set to: [green]{self.session_state['current_provider']}/{self.session_state['current_model']}[/]")
        else:
            all_models = get_all_models()
            found = False
            for provider, models in all_models.items():
                if model_arg in models:
                    result = set_preferred_provider(provider, model_arg)
                    success(result)
                    self.update_session_state()
                    console.print(f"[bold cyan]>[/] Active model set to: [green]{self.session_state['current_provider']}/{self.session_state['current_model']}[/]")
                    found = True
                    break
            if not found:
                error(f"Model '{model_arg}' not found in any provider")
    
    def show_available_models(self):
        all_models = get_all_models()
        table = Table(show_header=True, header_style="bold blue", title="Available AI Models")
        table.add_column("Provider", style="cyan")
        table.add_column("Models", style="white")
        
        for provider, models in all_models.items():
            current_marker = " *" if provider == self.session_state['current_provider'] else ""
            models_list = []
            for model in models[:8]:
                model_marker = " *" if model == self.session_state['current_model'] else ""
                vision_marker = " [V]" if multimodal_tools.is_vision_model(model, provider) else ""
                models_list.append(f"{model}{model_marker}{vision_marker}")
            
            table.add_row(
                f"{provider}{current_marker}",
                "\n".join(models_list)
            )
        
        console.print(table)
    
    def show_available_providers(self):
        providers = get_available_providers()
        table = Table(show_header=True, header_style="bold green", title="AI Providers")
        table.add_column("Provider", style="cyan")
        table.add_column("Status", style="white")
        table.add_column("Capabilities", style="yellow")
        
        for provider in providers:
            current_marker = " *CURRENT" if provider == self.session_state['current_provider'] else ""
            
            ai_manager = get_ai_manager()
            provider_obj = ai_manager.providers.get(provider)
            status = "Connected" if provider_obj and provider_obj.test_connection() else "Failed"
            
            capabilities = []
            vision_models = multimodal_tools.get_available_vision_models(provider)
            if vision_models:
                capabilities.append("Vision")
            if provider in ['openrouter']:
                capabilities.append("ImageGen")
            
            table.add_row(
                f"{provider}{current_marker}",
                status,
                ", ".join(capabilities) if capabilities else "Text only"
            )
        
        console.print(table)
    
    def handle_system_prompt(self, args):
        if args:
            self.session_state['system_prompt'] = ' '.join(args)
            success(f"System prompt set: {self.session_state['system_prompt']}")
        else:
            console.print("Usage: [cyan]/system <your system prompt>[/]")
    
    def show_status_info(self):
        active_session = Database.get_active_session()
        session_memory = Database.get_session_memory(active_session['id'])
        
        status_table = Table(show_header=False, title="Current Status", style="blue")
        status_table.add_column("Field", style="cyan")
        status_table.add_column("Value", style="white")
        
        status_table.add_row("Session", f"{active_session.get('name')} (ID: {active_session.get('id')})")
        status_table.add_row("Messages", str(active_session.get('message_count', 0)))
        status_table.add_row("AI Provider", f"{self.session_state['current_provider']}/{self.session_state['current_model']}")
        status_table.add_row("Streaming", "ON" if self.session_state['streaming'] else "OFF")
        status_table.add_row("System Prompt", self.session_state['system_prompt'] or "Not set")
        status_table.add_row("Session Context", f"{len(session_memory.get('session_context', ''))} chars")
        status_table.add_row("Vision", "Available" if self.vision_capabilities['has_vision'] else "Unavailable")
        status_table.add_row("Image Generation", "Available" if self.vision_capabilities['has_image_generation'] else "Unavailable")
        
        console.print(status_table)
    
    def switch_to_vision(self):
        if not self.vision_capabilities['has_vision']:
            error("No vision capabilities available.")
            return
        
        vision_provider = self.vision_capabilities['vision_provider']
        vision_model = self.vision_capabilities['vision_model']
        
        result = set_preferred_provider(vision_provider, vision_model)
        success(result)
        self.update_session_state()
        console.print("\n[green]Now using vision model. Send messages with image URLs to analyze them![/]")
    
    def generate_image(self, args):
        if not self.vision_capabilities['has_image_generation']:
            error("Image generation not available.")
            return
        
        if not args:
            console.print("Usage: [cyan]/imagine <prompt>[/]")
            return
        
        prompt = ' '.join(args)
        console.print(f"[dim]Generating image: {prompt}[/]")
        
        image_url, error_msg = multimodal_tools.generate_image(prompt)
        
        if image_url:
            success("Image generated successfully!")
            console.print(f"Image URL: [cyan]{image_url}[/]")
            active_session = Database.get_active_session()
            session_id = active_session['id']
            Database.add_message('user', f"/imagine {prompt}", session_id)
            Database.add_image_tools_message(image_url, session_id)
            image_markdown = f"![Generated Image]({image_url})"
            Database.add_message('assistant', f"Image generated!\n\n{image_markdown}", session_id)
        else:
            error(f"Image generation failed: {error_msg}")
    
    def show_capabilities(self):
        table = Table(show_header=True, header_style="bold yellow", title="Multimodal Capabilities")
        table.add_column("Feature", style="cyan")
        table.add_column("Status", style="white")
        table.add_column("Details", style="green")
        
        table.add_row(
            "Vision Analysis",
            "Available" if self.vision_capabilities['has_vision'] else "Unavailable",
            f"{self.vision_capabilities['vision_provider']}/{self.vision_capabilities['vision_model']}" 
            if self.vision_capabilities['has_vision'] else "None"
        )
        
        table.add_row(
            "Image Generation", 
            "Available" if self.vision_capabilities['has_image_generation'] else "Unavailable",
            self.vision_capabilities['image_generation_provider'] 
            if self.vision_capabilities['has_image_generation'] else "None"
        )
        
        console.print(table)
        
        providers = get_available_providers()
        vision_models_found = False
        for provider in providers:
            vision_models = multimodal_tools.get_available_vision_models(provider)
            if vision_models:
                if not vision_models_found:
                    console.print("\n[bold]Vision Models by Provider:[/]")
                    vision_models_found = True
                console.print(f"  [cyan]{provider.upper()}:[/]")
                for model in vision_models:
                    console.print(f"    - {model}")
    
    def update_session_state(self):
        self._profile_cache = None
        self._session_cache = None
        profile = self.profile
        providers_config = profile.get('providers_config', {})
        self.session_state.update({
            'current_provider': providers_config.get('preferred_provider', 'ollama'),
            'current_model': providers_config.get('preferred_model', 'glm-4.6:cloud'),
            'streaming': providers_config.get('streaming_enabled', False)
        })
        if self._vision_capabilities_cache is None:
            self._vision_capabilities_cache = get_vision_capabilities()
    
    def display_user_message_panel(self, user_message: str):
        console.print("-" * 60)
        console.print()
    
    def display_normal_response_panel(self, response: str, response_time: float):
        title = f"[bold magenta]{self.profile['partner_name']}[/] [dim]• {response_time:.1f}s[/]"
        
        if not response.strip():
            console.print(Panel("(Empty response)", title=title, border_style="magenta"))
            return
        
        code_blocks = self.extract_code_blocks(response)
        
        if code_blocks and self.config.get('auto_save_code_blocks', True):
            info("Auto-saving code blocks...")
            for lang, code, _ in code_blocks:
                base_name = self._generate_filename(code, lang, "generated_code")
                self.save_code_block(code, lang, base_name)
        
        if code_blocks:
            renderable = self._create_optimized_renderable(response, code_blocks)
        else:
            renderable = Markdown(response) if any(c in response for c in '#*`>') else response
        
        panel = Panel(
            renderable,
            title=title,
            title_align="left",
            border_style="magenta",
            padding=(0, 1)
        )
        console.print(panel)
        console.print()
    
    def _create_optimized_renderable(self, response: str, code_blocks):
        parts = response.split('```')
        renderable_parts = []
        
        for i, part in enumerate(parts):
            if not part.strip():
                continue
                
            if i % 2 == 0:
                if any(md_char in part for md_char in '#*`>-_'):
                    renderable_parts.append(Markdown(part))
                else:
                    renderable_parts.append(part)
            else:
                if i // 2 < len(code_blocks):
                    lang, code, _ = code_blocks[i // 2]
                    renderable_parts.append(
                        Syntax(code, lang or "text", theme="default", line_numbers=len(code.split('\n')) > 5)
                    )
        
        return renderable_parts[0] if len(renderable_parts) == 1 else renderable_parts
        
    def display_streaming_response_panel(self, response_generator):
        start_time = time.time()
        full_response = ""
        current_display = Text()
        
        title = f"[bold magenta]{self.profile['partner_name']}[/]"
        streaming_panel = Panel(
            current_display, 
            title=title, 
            title_align="left",
            border_style="magenta"
        )
        
        try:
            with Live(streaming_panel, refresh_per_second=15, transient=False) as live:
                for chunk in response_generator:
                    if not chunk:
                        continue
                    full_response += chunk
                    current_display.append(chunk)
                
                final_title = f"{title} [dim]• {time.time()-start_time:.1f}s[/]"
                final_panel = Panel(
                    current_display, 
                    title=final_title, 
                    title_align="left",
                    border_style="magenta"
                )
                live.update(final_panel)
                
        except Exception as e:
            error(f"Streaming error: {e}")
        
        return full_response
    
    def _initialize_prompt_session(self):
        return PromptSession(
            history=FileHistory(os.path.expanduser("~/.yuzu_companion_history")),
            completer=WordCompleter([cmd for category in self.commands.values() for cmd in category], ignore_case=True),
        )
    
    def _print_initial_info(self):
        console.print("[dim]Type your message or use /help for commands. Multi-line: type '...' on empty line.[/]")
        console.print("[dim]Include image URLs for automatic vision analysis.[/]")
        console.print("[dim]Use /cls to clear the screen.[/]")
        stream_status = "ON" if self.session_state['streaming'] else "OFF"
        console.print(f"[dim]Streaming mode: {stream_status} (use /stream to toggle)[/]")
        console.print("-" * 60)
        console.print()
    
    def _get_user_input(self, prompt_session) -> str:
        try:
            return prompt_session.prompt(fancy_prompt()).strip()
        except KeyboardInterrupt:
            raise
        except Exception as e:
            error(f"Input error: {e}")
            return ""
    
    def _get_multiline_input(self) -> str:
        console.print("[yellow]Multi-line input mode. Type '...' on empty line to finish.[/]")
        lines = []
        while True:
            try:
                line = PromptSession().prompt("... ").strip()
                if line == '...':
                    break
                lines.append(line)
            except KeyboardInterrupt:
                console.print("\n[yellow]Input cancelled.[/]")
                return ""
        return "\n".join(lines) if lines else ""
    
    def _process_input(self, user_input: str) -> bool:
        if user_input.startswith('/'):
            return self.handle_command(user_input)
        
        if user_input == '...':
            user_input = self._get_multiline_input()
            if not user_input:
                return True
        
        return self._handle_chat_message(user_input)
    
    def _handle_chat_message(self, user_input: str) -> bool:
        self.display_user_message_panel(user_input)
        
        if self.session_state['streaming']:
            start_time = time.time()
            response_generator = handle_user_message_streaming(
                user_input, 
                interface="terminal",
                provider=self.session_state['current_provider'],
                model=self.session_state['current_model']
            )
            full_response = self.display_streaming_response_panel(response_generator)
        else:
            start_time = time.time()
            response = handle_user_message(user_input, interface="terminal")
            response_time = time.time() - start_time
            self.display_normal_response_panel(response, response_time)
        
        console.print("-" * 60)
        console.print()
        return True
    
    def _handle_graceful_exit(self):
        console.print("\n[green]Goodbye![/]")
        end_session_cleanup(self.profile, interface="terminal", unexpected_exit=False)
    
    def _handle_unexpected_error(self, e: Exception):
        error(f"Unexpected error: {e}")
        end_session_cleanup(self.profile, interface="terminal", unexpected_exit=True)
    
    def chat_loop(self):
        start_session(interface="terminal")
        welcome_banner()
        prompt_session = self._initialize_prompt_session()
        self._print_initial_info()
        
        try:
            while True:
                try:
                    user_input = self._get_user_input(prompt_session)
                    if not user_input:
                        continue
                    if not self._process_input(user_input):
                        break
                except KeyboardInterrupt:
                    console.print("\n[yellow]Input interrupted. Press Ctrl+D to exit.[/]")
        except EOFError:
            self._handle_graceful_exit()
        except Exception as e:
            self._handle_unexpected_error(e)
    
    def extract_code_blocks(self, text: str):
        pattern = r"```(\w+)?\n(.*?)```"
        matches = re.findall(pattern, text, re.DOTALL)
        return [(lang or "text", code.strip(), f"```{lang or ''}\n{code.strip()}\n```") 
                for lang, code in matches]
    
    def save_code_block(self, code: str, lang: str, base_name: str = "generated"):
        EXT_MAP = {
            'python': 'py', 'javascript': 'js', 'typescript': 'ts', 
            'html': 'html', 'css': 'css', 'shell': 'sh', 'bash': 'sh',
            'json': 'json', 'yaml': 'yml', 'markdown': 'md', 'text': 'txt'
        }
        ext = EXT_MAP.get(lang, 'txt')
        base_name = self._generate_filename(code, lang, base_name)
        code_dir = Path("code_blocks")
        code_dir.mkdir(exist_ok=True)
        filename = code_dir / f"{base_name}.{ext}"
        try:
            filename.write_text(code, encoding='utf-8')
            success(f"Code saved to: {filename}")
            return str(filename)
        except Exception as e:
            error(f"Could not save file: {e}")
            return None

    def _generate_filename(self, code: str, lang: str, base_name: str) -> str:
        if lang == "python":
            patterns = [
                (r'def\s+(\w+)', 1),
                (r'class\s+(\w+)', 1),
                (r'"""(.*?)"""', 1),
            ]
            for pattern, group in patterns:
                match = re.search(pattern, code[:500], re.MULTILINE | re.DOTALL)
                if match:
                    name = match.group(group).strip()
                    if name and name != "generated":
                        base_name = re.sub(r'[^\w\-_]', '_', name.lower())
                        break
        if base_name == "generated":
            base_name = f"yuzu_code_{int(time.time())}"
        return base_name

    # === COMPLETE MENU METHODS ===

    def config_menu(self):
        while True:
            self.update_session_state()
            profile = Database.get_profile()
            api_keys = Database.get_api_keys()
            active_session = Database.get_active_session()
            session_memory = Database.get_session_memory(active_session['id'])
            global_knowledge = profile.get('global_knowledge', {})
            profile_memory = profile.get('memory', {})
            
            config_panel = Panel.fit(
                f"[bold cyan]User:[/] {profile['display_name']} • [bold cyan]Partner:[/] {profile['partner_name']}\n"
                f"[bold yellow]Affection:[/] {profile.get('affection', 50)} • [bold green]Session:[/] {active_session.get('name', 'Unknown')}\n"
                f"[bold magenta]AI Provider:[/] {self.session_state['current_provider']}/{self.session_state['current_model']}",
                title="Yuzu Companion Configuration",
                border_style="magenta"
            )
            console.print(config_panel)
            console.print()
            
            stats_table = Table(show_header=False, style="blue")
            stats_table.add_column("Metric", style="cyan")
            stats_table.add_column("Value", style="white")
            stats_table.add_row("Session Context", f"{len(session_memory.get('session_context', ''))} chars")
            stats_table.add_row("Global Profile", f"{len(profile_memory.get('player_summary', ''))} chars")
            stats_table.add_row("Global Knowledge", f"{len(global_knowledge.get('facts', ''))} chars")
            stats_table.add_row("API Keys", f"{len(api_keys)} configured")
            console.print(stats_table)
            console.print()
            
            menu_table = Table(show_header=True, header_style="bold green")
            menu_table.add_column("Option", style="cyan")
            menu_table.add_column("Description", style="white")
            menu_options = [
                ("1", "User & Partner Settings"),
                ("2", "API Key Management"),
                ("3", "Session Management"),
                ("4", "Memory & Context"),
                ("5", "AI Provider Settings"),
                ("6", "Multimodal Settings"),
                ("0", "Back to Main")
            ]
            for opt_num, opt_name in menu_options:
                menu_table.add_row(opt_num, opt_name)
            console.print(menu_table)
            
            try:
                choice = Prompt.ask("\nSelect option", choices=["0", "1", "2", "3", "4", "5", "6"], default="0")
            except KeyboardInterrupt:
                break
            
            if choice == "1":
                self.user_settings_menu()
            elif choice == "2":
                self.api_key_management_menu()
            elif choice == "3":
                self.session_management_menu()
            elif choice == "4":
                self.memory_management_menu()
            elif choice == "5":
                self.provider_settings_menu()
            elif choice == "6":
                self.multimodal_settings_menu()
            elif choice == "0":
                break

    def user_settings_menu(self):
        profile = Database.get_profile()
        console.print(Panel.fit(
            f"Current: [cyan]{profile['display_name']}[/] → [magenta]{profile['partner_name']}[/]\n"
            f"Affection: [yellow]{profile.get('affection', 50)}[/]",
            title="User & Partner Settings",
            border_style="cyan"
        ))
        console.print()
        
        options_table = Table(show_header=False)
        options_table.add_column("Option", style="cyan")
        options_table.add_column("Action", style="white")
        options_table.add_row("1", "Change your display name")
        options_table.add_row("2", "Change partner's name")
        options_table.add_row("3", "Set affection level")
        options_table.add_row("0", "Back")
        console.print(options_table)
        
        try:
            choice = Prompt.ask("Select action", choices=["0", "1", "2", "3"], default="0")
        except KeyboardInterrupt:
            return
        
        if choice == "1":
            new_name = Prompt.ask("Enter your display name", default=profile['display_name'])
            if new_name and new_name != profile['display_name']:
                Database.update_profile({'display_name': new_name})
                success(f"Your name set to {new_name}")
                self._profile_cache = None
        elif choice == "2":
            new_name = Prompt.ask("Enter partner's name", default=profile['partner_name'])
            if new_name and new_name != profile['partner_name']:
                Database.update_profile({'partner_name': new_name})
                success(f"Partner name set to {new_name}")
                self._profile_cache = None
        elif choice == "3":
            try:
                current_affection = profile.get('affection', 50)
                new_affection = IntPrompt.ask("Set affection level (0-100)", default=current_affection)
                if 0 <= new_affection <= 100:
                    Database.update_profile({'affection': new_affection})
                    success(f"Affection set to {new_affection}")
                    self._profile_cache = None
                else:
                    error("Affection must be between 0 and 100")
            except Exception as e:
                error(f"Invalid input: {e}")

    def api_key_management_menu(self):
        while True:
            keys = Database.get_api_keys()
            console.print(Panel.fit(
                f"Configured keys: [green]{len(keys)}[/]",
                title="API Key Management",
                border_style="yellow"
            ))
            console.print()
            
            if keys:
                keys_table = Table(show_header=True, header_style="bold green")
                keys_table.add_column("Service", style="cyan")
                keys_table.add_column("Key Preview", style="white")
                for key_name, key_value in keys.items():
                    keys_table.add_row(key_name.upper(), f"{key_value[:8]}...{key_value[-4:]}")
                console.print(keys_table)
            else:
                console.print("[yellow]No API keys configured yet.[/]")
            console.print()
            
            options_table = Table(show_header=False)
            options_table.add_column("Option", style="cyan")
            options_table.add_column("Action", style="white")
            options_table.add_row("1", "Add OpenRouter API key")
            options_table.add_row("2", "Add Chutes API key")
            options_table.add_row("3", "Add Cerebras API key")
            options_table.add_row("4", "Remove API key")
            options_table.add_row("0", "Back")
            console.print(options_table)
            
            try:
                choice = Prompt.ask("Select action", choices=["0", "1", "2", "3", "4"], default="0")
            except KeyboardInterrupt:
                break
            
            if choice == "1":
                new_key = Prompt.ask("Enter OpenRouter API key", password=True)
                if new_key and Database.add_api_key('openrouter', new_key):
                    success("OpenRouter API key added!")
            elif choice == "2":
                new_key = Prompt.ask("Enter Chutes API key", password=True)
                if new_key and Database.add_api_key('chutes', new_key):
                    success("Chutes API key added!")
            elif choice == "3":
                new_key = Prompt.ask("Enter Cerebras API key", password=True)
                if new_key and Database.add_api_key('cerebras', new_key):
                    success("Cerebras API key added!")
            elif choice == "4":
                if not keys:
                    error("No API keys to remove")
                    continue
                key_names = list(keys.keys())
                for i, key_name in enumerate(key_names, 1):
                    console.print(f"{i}. {key_name.upper()}: {keys[key_name][:8]}...{keys[key_name][-4:]}")
                try:
                    key_choice = IntPrompt.ask("Select key to remove", default=1)
                    if 1 <= key_choice <= len(key_names):
                        key_to_remove = key_names[key_choice - 1]
                        if Confirm.ask(f"Remove {key_to_remove.upper()} API key?"):
                            if Database.remove_api_key(key_to_remove):
                                success(f"Removed {key_to_remove.upper()} API key")
                    else:
                        error("Invalid selection")
                except Exception as e:
                    error(f"Invalid input: {e}")
            elif choice == "0":
                break

    def session_management_menu(self):
        while True:
            sessions = Database.get_all_sessions()
            active_session = Database.get_active_session()
            console.print(Panel.fit(
                f"Active: [green]{active_session.get('name')}[/] • Total: [cyan]{len(sessions)}[/] sessions",
                title="Session Management",
                border_style="green"
            ))
            console.print()
            
            sessions_table = Table(show_header=True, header_style="bold cyan")
            sessions_table.add_column("ID", style="white", justify="right")
            sessions_table.add_column("Name", style="cyan")
            sessions_table.add_column("Messages", justify="right")
            sessions_table.add_column("Status", style="green")
            for session in sessions:
                is_active = session['id'] == active_session['id']
                sessions_table.add_row(
                    str(session['id']),
                    session['name'],
                    str(session.get('message_count', 0)),
                    "ACTIVE" if is_active else ""
                )
            console.print(sessions_table)
            console.print()
            
            options_table = Table(show_header=False)
            options_table.add_column("Option", style="cyan")
            options_table.add_column("Action", style="white")
            options_table.add_row("1", "Switch to session")
            options_table.add_row("2", "Create new session")
            options_table.add_row("3", "Rename session")
            options_table.add_row("4", "Delete session")
            options_table.add_row("0", "Back")
            console.print(options_table)
            
            try:
                choice = Prompt.ask("Select action", choices=["0", "1", "2", "3", "4"], default="0")
            except KeyboardInterrupt:
                break
            
            if choice == "1":
                try:
                    session_id = IntPrompt.ask("Enter session ID to switch to")
                    if Database.switch_session(session_id):
                        success(f"Switched to session {session_id}")
                        self._session_cache = None
                    else:
                        error("Session not found")
                except Exception as e:
                    error(f"Invalid input: {e}")
            elif choice == "2":
                name = Prompt.ask("Enter session name", default="New Chat")
                session_id = Database.create_session(name)
                Database.switch_session(session_id)
                success(f"Created and switched to session {session_id}")
                self._session_cache = None
            elif choice == "3":
                try:
                    session_id = IntPrompt.ask("Enter session ID to rename")
                    new_name = Prompt.ask("Enter new name")
                    if new_name and Database.rename_session(session_id, new_name):
                        success(f"Renamed session {session_id}")
                    else:
                        error("Session not found")
                except Exception as e:
                    error(f"Invalid input: {e}")
            elif choice == "4":
                try:
                    session_id = IntPrompt.ask("Enter session ID to delete")
                    if session_id == active_session['id']:
                        error("Cannot delete active session")
                        continue
                    if Confirm.ask(f"Delete session {session_id}?"):
                        if Database.delete_session(session_id):
                            success(f"Deleted session {session_id}")
                        else:
                            error("Session not found")
                except Exception as e:
                    error(f"Invalid input: {e}")
            elif choice == "0":
                break

    def memory_management_menu(self):
        profile = Database.get_profile()
        active_session = Database.get_active_session()
        session_memory = Database.get_session_memory(active_session['id'])
        console.print(Panel.fit(
            f"Session: [green]{len(session_memory.get('session_context', ''))} chars[/] • "
            f"Global: [cyan]{len(profile.get('memory', {}).get('player_summary', ''))} chars[/]",
            title="Memory Management",
            border_style="blue"
        ))
        console.print()
        
        options_table = Table(show_header=False)
        options_table.add_column("Option", style="cyan")
        options_table.add_column("Action", style="white")
        options_table.add_row("1", "Update session context")
        options_table.add_row("2", "Update global player profile")
        options_table.add_row("3", "View session context")
        options_table.add_row("4", "View global profile")
        options_table.add_row("0", "Back")
        console.print(options_table)
        
        try:
            choice = Prompt.ask("Select action", choices=["0", "1", "2", "3", "4"], default="0")
        except KeyboardInterrupt:
            return
        
        if choice == "1":
            self.update_session_context()
        elif choice == "2":
            self.update_global_profile()
        elif choice == "3":
            console.print(Panel.fit(
                session_memory.get('session_context', 'No session context yet.'),
                title=f"Session Context: {active_session.get('name')}",
                border_style="green"
            ))
        elif choice == "4":
            memory = profile.get('memory', {})
            key_facts = memory.get("key_facts", {})
            profile_panel = Panel.fit(
                f"[bold]Summary:[/] {memory.get('player_summary', 'No global summary yet')}\n\n"
                f"[bold]Likes:[/] {', '.join(key_facts.get('likes', [])) or 'None'}\n"
                f"[bold]Dislikes:[/] {', '.join(key_facts.get('dislikes', [])) or 'None'}\n"
                f"[bold]Personality:[/] {', '.join(key_facts.get('personality_traits', [])) or 'None'}",
                title="Global Player Profile",
                border_style="cyan"
            )
            console.print(profile_panel)

    def provider_settings_menu(self):
        console.print(Panel.fit(
            f"Current: [green]{self.session_state['current_provider']}/{self.session_state['current_model']}[/]",
            title="AI Provider Settings",
            border_style="yellow"
        ))
        console.print()
        
        options_table = Table(show_header=False)
        options_table.add_column("Option", style="cyan")
        options_table.add_column("Action", style="white")
        options_table.add_row("1", "Change preferred provider")
        options_table.add_row("2", "Change preferred model")
        options_table.add_row("3", "View available providers")
        options_table.add_row("4", "View available models")
        options_table.add_row("0", "Back")
        console.print(options_table)
        
        try:
            choice = Prompt.ask("Select action", choices=["0", "1", "2", "3", "4"], default="0")
        except KeyboardInterrupt:
            return
        
        if choice == "1":
            self.show_available_providers()
            providers = get_available_providers()
            try:
                provider_num = IntPrompt.ask("Select provider number", default=1)
                if 1 <= provider_num <= len(providers):
                    selected_provider = providers[provider_num - 1]
                    result = set_preferred_provider(selected_provider)
                    success(result)
                    self.update_session_state()
                else:
                    error("Invalid selection")
            except Exception as e:
                error(f"Invalid input: {e}")
        elif choice == "2":
            self.show_available_models()
        elif choice == "3":
            self.show_available_providers()
        elif choice == "4":
            self.show_available_models()

    def multimodal_settings_menu(self):
        console.print(Panel.fit(
            f"Vision: [green]{'Available' if self.vision_capabilities['has_vision'] else 'Unavailable'}[/] • "
            f"ImageGen: [cyan]{'Available' if self.vision_capabilities['has_image_generation'] else 'Unavailable'}[/]",
            title="Multimodal Settings",
            border_style="magenta"
        ))
        console.print()
        
        options_table = Table(show_header=False)
        options_table.add_column("Option", style="cyan")
        options_table.add_column("Action", style="white")
        options_table.add_row("1", "Switch to vision model")
        options_table.add_row("2", "View vision capabilities")
        options_table.add_row("3", "Generate test image")
        options_table.add_row("0", "Back")
        console.print(options_table)
        
        try:
            choice = Prompt.ask("Select action", choices=["0", "1", "2", "3"], default="0")
        except KeyboardInterrupt:
            return
        
        if choice == "1":
            self.switch_to_vision()
        elif choice == "2":
            self.show_capabilities()
        elif choice == "3":
            test_prompt = Prompt.ask("Enter test image prompt", default="a cute anime cat with blue eyes")
            self.generate_image([test_prompt])

    def list_sessions(self):
        sessions = Database.get_all_sessions()
        active_session = Database.get_active_session()
        table = Table(show_header=True, header_style="bold cyan", title="All Sessions")
        table.add_column("ID", style="white", justify="right")
        table.add_column("Name", style="cyan")
        table.add_column("Messages", justify="right")
        table.add_column("Status", style="green")
        for session in sessions:
            is_active = session['id'] == active_session['id']
            table.add_row(
                str(session['id']),
                session['name'],
                str(session.get('message_count', 0)),
                "ACTIVE" if is_active else ""
            )
        console.print(table)

    def clear_chat_history(self):
        if self.config.get('confirm_clear_history', True):
            if not Confirm.ask("Clear current chat history?", default=False):
                return
        active_session = Database.get_active_session()
        Database.clear_chat_history(active_session['id'])
        success("Chat history cleared!")

    def show_chat_history(self):
        active_session = Database.get_active_session()
        chat_history = Database.get_chat_history()
        user_messages = len([m for m in chat_history if m['role'] == 'user'])
        assistant_messages = len([m for m in chat_history if m['role'] == 'assistant'])
        
        table = Table(show_header=False, title="Chat Statistics", style="green")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="white")
        table.add_row("Total Messages", str(len(chat_history)))
        table.add_row("Your Messages", str(user_messages))
        table.add_row("AI Responses", str(assistant_messages))
        table.add_row("Session Name", active_session.get('name', 'Unknown'))
        console.print(table)

    def update_session_context(self):
        active_session = Database.get_active_session()
        session_id = active_session['id']
        chat_history = Database.get_chat_history(session_id=session_id)
        
        if len(chat_history) < 5:
            error("Need at least 5 conversation messages to generate context")
            return
        
        last_user_msg = next((msg for msg in reversed(chat_history) if msg['role'] == 'user'), None)
        last_ai_reply = next((msg for msg in reversed(chat_history) if msg['role'] == 'assistant'), None)
        
        if last_user_msg and last_ai_reply:
            console.print("[dim]Generating session context...[/]")
            if summarize_memory(self.profile, last_user_msg['content'], last_ai_reply['content'], session_id):
                success("Session context updated!")
            else:
                error("Session context update failed")
        else:
            error("Need conversation history to generate context")

    def update_global_profile(self):
        console.print("[dim]Analyzing player profile from ALL sessions...[/]")
        if summarize_global_player_profile():
            success("Global player profile updated from ALL sessions!")
        else:
            error("Global profile analysis failed")

    def show_memory_status(self):
        profile = Database.get_profile()
        active_session = Database.get_active_session()
        session_memory = Database.get_session_memory(active_session['id'])
        
        table = Table(show_header=False, title="Memory Status", style="blue")
        table.add_column("Memory Type", style="cyan")
        table.add_column("Details", style="white")
        table.add_row("Session Memory", f"{len(session_memory.get('session_context', ''))} chars")
        table.add_row("Global Profile", f"{len(profile.get('memory', {}).get('player_summary', ''))} chars")
        console.print(table)

    def launch_web_interface(self):
        def start_flask_server():
            from web import app
            app.run(debug=False, port=5000, host='0.0.0.0', use_reloader=False)
        
        console.print("[dim]Starting web interface...[/]")
        flask_thread = threading.Thread(target=start_flask_server, daemon=True)
        flask_thread.start()
        time.sleep(2)
        webbrowser.open('http://127.0.0.1:5000')
        success("Web interface launched at: http://127.0.0.1:5000")
        console.print("[yellow]Press Ctrl+C to return to terminal.[/]")
        
        try:
            while flask_thread.is_alive():
                time.sleep(1)
        except KeyboardInterrupt:
            console.print("\n[yellow]Returning to terminal interface...[/]")

def main():
    agent = YuzuCompanionAgent()
    agent.chat_loop()

if __name__ == "__main__":
    main()