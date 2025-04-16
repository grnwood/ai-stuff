import os
import sys
import argparse
import re
import requests
from dotenv import load_dotenv

load_dotenv()

PROXY_URL = os.getenv("OPENAI_PROXY_URL", "http://localhost:3000/chat")
API_SECRET = os.getenv("API_SECRET_TOKEN", "my-secret-token")

def parse_input(raw_text: str):
    prompt_match = re.search(r'(?i)^prompt:\s*(.*)', raw_text, re.MULTILINE)
    ai_input_match = re.search(r'(?i)^ai:\s*(.*)', raw_text, re.MULTILINE)
    model_match = re.search(r'(?i)^model:\s*(.*)', raw_text, re.MULTILINE)
    system_match = re.search(r'(?i)^system:\s*(.*)', raw_text, re.MULTILINE)

    prompt = prompt_match.group(1).strip() if prompt_match else ""
    ai_input = ai_input_match.group(1).strip() if ai_input_match else raw_text.strip()
    system = system_match.group(1).strip() if system_match else None
    full_prompt = f"{prompt}\n\n{ai_input}" if prompt else ai_input
    model_override = model_match.group(1).strip() if model_match else None

    return full_prompt, prompt, ai_input, model_override, system

def main():
    parser = argparse.ArgumentParser(description="Send prompt+input to OpenAI via proxy.")
    parser.add_argument("text", type=str, nargs="*", help="Combined prompt and AI input")
    parser.add_argument("--model", type=str, default="gpt-3.5-turbo", help="Default OpenAI model to use")
    parser.add_argument("--stream", action="store_true", help="Stream output live")
    args = parser.parse_args()

    if not args.text:
        print("❌ Error: No input text provided.")
        sys.exit(1)

    raw_text = "\n".join(args.text)
    full_prompt, prompt, ai_input, model_override, system = parse_input(raw_text)
    selected_model = model_override or args.model

    payload = {
        "model": selected_model,
        "prompt": prompt if prompt else None,
        "ai": ai_input,
        "stream": args.stream
    }

    if system:
        payload["system"] = system

    print("Sending payload to proxy:")
    print(payload)
    try:
        headers = {
            "Content-Type": "application/json",
            "x-api-secret": API_SECRET
        }

        if args.stream:
            with requests.post(PROXY_URL, json=payload, headers=headers, stream=True) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines(decode_unicode=True):
                    if line.startswith("data: "):
                        chunk = line[6:]
                        if chunk.strip() == "[DONE]":
                            break
                        try:
                            delta = eval(chunk) if chunk.startswith("{") else {}
                            content = delta.get("choices", [{}])[0].get("delta", {}).get("content")
                            if content:
                                print(content, end="", flush=True)
                        except Exception:
                            pass
                print()
        else:
            resp = requests.post(PROXY_URL, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            print(data['choices'][0]['message']['content'].strip())

    except Exception as e:
        print(f"❌ Proxy/API Error: {e}", file=sys.stderr)

if __name__ == "__main__":
    main()

