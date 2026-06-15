import aiohttp
import asyncio
import json
import os
from dotenv import load_dotenv

load_dotenv()


async def invoke_chute():
    api_token = os.getenv("CHUTES_API_KEY")
    if not api_token:
        print("Error: CHUTES_API_KEY not found in .env file")
        return

    try:
        with open("app/prompt.md", "r", encoding="utf-8") as f:
            system_message_content = f.read()
    except FileNotFoundError:
        print("Error: app/prompt.md not found in the current directory")
        return

    print("=== YUZUKI PROMPT BUILDER & OPTIMIZER ===")
    print("Example commands:")
    print("- 'tambahin tool git_push buat backup kode otomatis'")
    print("- 'ubah persona jadi fase dewasa yang lebih tenang'")
    print("- Leave empty for standard prompt optimization\n")

    user_change_request = input(
        "Masukkan instruksi perubahan atau penambahan: "
    ).strip()

    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }

    task_description = (
        "Your primary task is to critically refactor and optimize the provided SYSTEM MESSAGE to maximize efficiency "
        'and minimize "persona drift" and "pattern collapse."'
    )
    if user_change_request:
        task_description = (
            f"Your primary task is to MODIFY the provided SYSTEM MESSAGE according to this USER REQUEST:\n"
            f'"{user_change_request}"\n\n'
            "You must seamlessly integrate this change into the correct section of the prompt "
            "while simultaneously refactoring the entire document for maximum efficiency and stability."
        )

    instructions = (
        "You are an Expert LLM Prompt Engineer specializing in alignment and persona stability.\n\n"
        f"{task_description}\n\n"
        "Please follow these strict optimization rules during the process:\n\n"
        "1. REMOVE REDUNDANCY: Identify and delete overlapping instructions. If two rules say the same thing in different ways, merge them into one definitive statement.\n"
        "2. ELIMINATE NOISE: Remove flowery language, polite filler, and vague descriptions. Convert prose into clear, concise, and imperative constraints.\n"
        '3. RESOLVE CONTRADICTIONS: Find instructions that conflict with each other and resolve them based on the primary goal: "Natural, non-robotic companion".\n'
        "4. STRUCTURE FOR ATTENTION: You must organize the final system prompt into a strict top-to-bottom hierarchy to manage the model's focus layout:\n"
        "   - Core Persona (IDENTITY, DIGITAL NATURE, BEHAVIOR, COGNITIVE FRAMEWORK, FORMATTING)\n"
        "   - Data Layer (# KNOWLEDGE BASE & MEMORY containing global context and retrieval blocks)\n"
        "   - Execution Layer (TOOL EXECUTION, AVAILABLE TOOLS, OPERATIONAL DISCIPLINE)\n"
        "   - Hard Safeguards (# NEGATIVE CONSTRAINTS)\n"
        "   - Current Context (# ENVIRONMENT)\n"
        "   - Core Behavioral Anchor (The primary psychological driver, growth framework, adaptability rules, or maturity phase constraints present in the source prompt)\n"
        "5. CONSOLIDATE NEGATIVE CONSTRAINTS: Group all forbidden behaviors into a single, dedicated '# NEGATIVE CONSTRAINTS' list. You MUST explicitly inject a permanent 'Pattern Break' rule here. This rule must command the model to immediately break any patterns found in the conversation history that feature repetitive emojis, invalid formatting, or communication styles inconsistent with the current persona definitions. It must treat history strictly as dialogue context, never as a blueprint to replicate bad habits or rule violations.\n"
        "6. PRESERVE CORE ESSENCE: Do not remove the fundamental identity and unique traits of the persona, but express them more efficiently.\n"
        "7. POSITION CORE ANCHORS AT THE END: Identify whatever core evolution mechanic, adaptability rules, or maturity parameters are active in the current prompt. Optimize that specific behavioral anchor and place it at the absolute end of the system message to ensure it acts as the primary short-term memory driver for the model.\n"
        "8. NO TRUNCATION: You must completely rewrite the entire system message from start to finish. Do not omit any sections, do not use placeholders like '[rest of prompt remains the same]', and do not summarize. Every single operational parameter must be preserved.\n\n"
        "OUTPUT FORMAT: Provide only the final, optimized system message. No preamble, no explanations, no markdown code blocks wrapping the response, and no internal thinking tags. Just the raw, ready-to-use system prompt.\n\n"
        "---\n"
        "CURRENT SYSTEM MESSAGE TO MODIFTY/OPTIMIZE:\n"
        f"{system_message_content}"
    )

    body = {
        "model": "Qwen/Qwen3.5-397B-A17B-TEE",
        "prompt": instructions,
        "stream": True,
        "max_tokens": 4000,
        "temperature": 0.3,
    }

    print("\n--- Processing Request via Chutes API... ---\n")

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                "https://llm.chutes.ai/v1/completions", headers=headers, json=body
            ) as response:
                if response.status == 429:
                    print(
                        "Error: API Rate Limit hit (429). Please wait a moment before trying again."
                    )
                    return

                if response.status != 200:
                    print(f"Error: API returned status {response.status}")
                    return

                full_content = ""
                async for line in response.content:
                    line = line.decode("utf-8").strip()
                    if line.startswith("data: "):
                        data = line[6:]
                        if data == "[DONE]":
                            break
                        try:
                            chunk_json = json.loads(data)
                            content = chunk_json.get("choices", [{}])[0].get("text", "")
                            if content:
                                print(content, end="", flush=True)
                                full_content += content
                        except Exception:
                            if data:
                                print(data)

                if full_content:
                    with open("app/prompt.md", "a", encoding="utf-8") as f:
                        f.write(f"\n\n>>>> OPTIMIZED PROMPT <<<<\n\n{full_content}")
                    print(
                        "\n\n--- Process Complete. Results appended to app/prompt.md. ---"
                    )
                else:
                    print("\n\nError: No content received from the API.")

        except Exception as e:
            print(f"Connection Error: {e}")


if __name__ == "__main__":
    asyncio.run(invoke_chute())
