import openai
import os
import sys
import argparse
import re

# Load your API key
api_key = os.getenv("OPENAI_API_KEY")

if not api_key:
    print("❌ Error: OPENAI_API_KEY environment variable not set.")
    sys.exit(1)

client = openai.OpenAI(api_key=api_key)

def parse_input(raw_text: str):
    prompt_match = re.search(r'(?i)^prompt:\s*(.*)', raw_text, re.MULTILINE)
    ai_input_match = re.search(r'(?i)^ai:\s*(.*)', raw_text, re.MULTILINE)
    model_match = re.search(r'(?i)^model:\s*(.*)', raw_text, re.MULTILINE)

    prompt = prompt_match.group(1).strip() if prompt_match else ""
    ai_input = ai_input_match.group(1).strip() if ai_input_match else raw_text.strip()
    full_prompt = f"{prompt}\n\n{ai_input}" if prompt else ai_input
    model_override = model_match.group(1).strip() if model_match else None

    return full_prompt, model_override

def list_models():
    print("📦 Available Models:")
    try:
        models = client.models.list()
        for model in models.data:
            print(f"- {model.id}")
    except Exception as e:
        print(f"❌ Error fetching models: {e}", file=sys.stderr)

def main():
    parser = argparse.ArgumentParser(description="Send prompt+input to OpenAI.")
    parser.add_argument("text", type=str, nargs="*", help="Combined prompt and AI input")
    parser.add_argument("--model", type=str, default="gpt-3.5-turbo", help="Default OpenAI model to use")
    parser.add_argument("--models", action="store_true", help="List available OpenAI models and exit")
    args = parser.parse_args()

    if args.models:
        list_models()
        sys.exit(0)

    if not args.text:
        print("❌ Error: No input text provided. Use --models or provide prompt text.")
        sys.exit(1)

    raw_text = " ".join(args.text)
    full_prompt, model_override = parse_input(raw_text)
    selected_model = model_override or args.model

    try:
        response = client.chat.completions.create(
            model=selected_model,
            messages=[{"role": "user", "content": full_prompt}]
        )
        print(response.choices[0].message.content.strip())
    except Exception as e:
        print(f"❌ API Error: {e}", file=sys.stderr)

if __name__ == "__main__":
    main()
