#!/usr/bin/env python3
import os
import sys
from openai import OpenAI

# Load API key
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    print("❌ Error: OPENAI_API_KEY environment variable not set.")
    sys.exit(1)

# Initialize OpenAI client
client = OpenAI(api_key=api_key)

# List available models
try:
    models = client.models.list()
    for model in models.data:
        print(model.id)
except Exception as e:
    print(f"❌ Failed to retrieve models: {e}", file=sys.stderr)
    sys.exit(1)

